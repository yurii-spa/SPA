"""Portfolio State Tracker (SPA-V389) — advisory-учёт состояния портфеля.

Отслеживает текущие (``actual``) и целевые (``target``) позиции paper-портфеля.
Источник целей — ``data/target_allocation.json`` (output SPA-V388). Текущие
позиции в paper-режиме инициализируются из целевых (mock: «как будто уже стоим
в equal_weight»), затем хранятся в ``data/portfolio_state.json``.

Read-only / advisory: модуль НЕ исполняет сделок и не двигает реальные деньги —
он лишь фиксирует снимок состояния для расчёта дрейфа и сигналов ребаланса.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET_PATH = _REPO_ROOT / "data" / "target_allocation.json"
_STATE_PATH = _REPO_ROOT / "data" / "portfolio_state.json"
_EPS = 1e-12


@dataclass
class PortfolioPosition:
    """Позиция портфеля: фактическое и целевое состояние."""

    protocol: str
    actual_usd: float      # текущая позиция (mock — старт из target_allocation)
    target_usd: float      # целевая позиция из target_allocation.json
    actual_weight: float   # доля от total фактического капитала
    target_weight: float   # целевая доля

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PortfolioPosition":
        return cls(
            protocol=d["protocol"],
            actual_usd=float(d["actual_usd"]),
            target_usd=float(d["target_usd"]),
            actual_weight=float(d["actual_weight"]),
            target_weight=float(d["target_weight"]),
        )


class PortfolioStateTracker:
    """Загрузка / инициализация / сохранение состояния портфеля."""

    def __init__(
        self,
        state_path: str | os.PathLike | None = None,
        target_path: str | os.PathLike | None = None,
    ):
        self.state_path = Path(state_path) if state_path else _STATE_PATH
        self.target_path = Path(target_path) if target_path else _TARGET_PATH

    # ── инициализация из target_allocation ────────────────────────────────
    def _init_from_target(self) -> list[PortfolioPosition]:
        """Строит стартовое состояние из ``target_allocation.json``.

        В paper-режиме считаем, что фактические позиции уже равны целевым
        (mock-старт). Если файла целей нет — пустой портфель.
        """
        if not self.target_path.exists():
            return []
        with open(self.target_path, encoding="utf-8") as fh:
            target = json.load(fh)
        weights = target.get("target_weights", {})
        usd = target.get("target_usd", {})
        positions = []
        for protocol, tw in weights.items():
            tusd = float(usd.get(protocol, 0.0))
            positions.append(
                PortfolioPosition(
                    protocol=protocol,
                    actual_usd=tusd,
                    target_usd=tusd,
                    actual_weight=float(tw),
                    target_weight=float(tw),
                )
            )
        return positions

    # ── загрузка ──────────────────────────────────────────────────────────
    def load_state(self) -> list[PortfolioPosition]:
        """Читает ``portfolio_state.json`` если есть, иначе инициализирует."""
        if self.state_path.exists():
            with open(self.state_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return [PortfolioPosition.from_dict(p) for p in data.get("positions", [])]
        return self._init_from_target()

    # ── сохранение (атомарно) ─────────────────────────────────────────────
    def save_state(self, positions: list[PortfolioPosition]) -> Path:
        """Атомарно пишет состояние (tmp + os.replace)."""
        out = self.state_path
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = self._snapshot_payload(positions)
        fd, tmp = tempfile.mkstemp(dir=str(out.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return out

    # ── снимок ──────────────────────────────────────────────────────────────
    def _snapshot_payload(self, positions: list[PortfolioPosition]) -> dict:
        total_actual = sum(p.actual_usd for p in positions)
        total_target = sum(p.target_usd for p in positions)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "portfolio_state_tracker",
            "execution_mode": "read_only_simulation",
            "total_actual_usd": round(total_actual, 2),
            "total_target_usd": round(total_target, 2),
            "num_positions": len(positions),
            "positions": [p.to_dict() for p in positions],
        }

    def snapshot(self) -> dict:
        """Текущий снэпшот: позиции, total_value, дата."""
        return self._snapshot_payload(self.load_state())
