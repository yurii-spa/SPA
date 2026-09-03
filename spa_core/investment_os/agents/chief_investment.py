"""spa_core/investment_os/agents/chief_investment.py — Chief Investment analyst (Head of Product, docs/08).

The capstone of the AI Investment OS. It SYNTHESISES the other analysts' advisory artifacts
(stablecoin_yield · market_regime · reporting · red_team · liquidity from data/investment_os/) into ONE
house-view: overall posture, top opportunities, the evidenced track, threats, exit liquidity — surfacing
(never averaging away) conflicts. It preserves each input's evidence tag; it invents no number.

**HARD OWNER-GATE (docs/08 §2.1, ADR_004):** it can recommend, it NEVER decides. Any allocation
direction is emitted as an ADVISORY `house_view` only — it moves NO capital, is NOT a gate, and any real
allocation change requires the owner's approval. Fail-CLOSED: if no analyst artifacts exist → UNKNOWN.

CLI::  python3 -m spa_core.investment_os.agents.chief_investment [--check]
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.investment_os.harness import ProductAgent, UNKNOWN

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода — вывести производителя разбором нельзя
#: (замер 28.08: верно 13 из 27, одна ошибка, семья harness недостижима).
#: Сверяется с фактической записью — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/investment_os/chief_investment.json",
)

log = logging.getLogger("spa.investment_os.chief_investment")

# The analyst artifacts this synthesiser consumes (produced by the other product agents).
_INPUTS = ("stablecoin_yield", "market_regime", "reporting", "red_team", "liquidity",
           "protocol_risk", "yield_quality")


class ChiefInvestmentAgent(ProductAgent):
    agent_key = "chief_investment"
    role_prompt = ("Chief Investment analyst (Head of Product) — synthesise the analysts into one "
                   "house-view; surface conflicts; RECOMMEND only, NEVER decide (owner-gated).")

    def __init__(self, *, data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)

    def _load_input(self, agent: str) -> Any:
        path = self.data_dir / f"{agent}.json"
        return self.read_feed(lambda: json.loads(path.read_text()))

    def _load_books(self) -> Any:
        """Восьмой вход (директива владельца 2026-08-31, карточка
        `inbox-sliv-aggressive-cio-obyazan-kurirovat-pr`): три независимые книги +
        совокупная ёмкость пулов. Вливается в СУЩЕСТВУЮЩИЙ контур тем же
        ``read_feed``-механизмом (прецедент газ-агента — не второй копией CIO).

        До этого входа CIO был слеп к книгам: его семь аналитиков —
        протокольные, а Balanced/Aggressive ведут реальный трек с 23.08
        (ADR-125). Книги живут уровнем выше ``investment_os/`` — в ``data/``.
        """
        def _loader() -> dict:
            from spa_core.reporting.books_summary import collect_books_summary
            from spa_core.risk.capacity_coordinator import read_books_capacity_check
            root = self.data_dir.parent  # data/investment_os → data/
            return {
                "summary": collect_books_summary(root),
                "capacity": read_books_capacity_check(root),
            }
        return self.read_feed(_loader)

    def _load_gas(self) -> Any:
        """Девятый вход (ADR-183, план читателей карточки активации): режим цены
        газа от com.spa.gas_price_agent — тем же ``read_feed``-контуром, что и
        книги. Строго ВНЕ постуры: газ-агент advisory и не гейтит (ADR-168 —
        де-риск не задерживается при любом газе); режим влияет только на
        house_view. Протухший файл (старше 3 тактов по 30 мин) ⇒ UNKNOWN —
        вчерашний газ хуже честного «не знаю».
        """
        path = self.data_dir.parent / "gas_price_history.json"

        def _loader() -> dict:
            raw = json.loads(path.read_text())
            chains = raw.get("chains") or {}
            if not chains:
                raise ValueError("gas_price_history: пустые chains")
            keep = ("source", "gwei", "regime", "usd_per_leg", "advice")
            return {
                "generated_at": raw.get("generated_at"),
                "eth_usd": (raw.get("eth_usd") or {}).get("usd"),
                "chains": {c: {k: e[k] for k in keep if k in e}
                           for c, e in chains.items() if isinstance(e, dict)},
            }

        mtime = path.stat().st_mtime if path.exists() else None
        return self.read_feed(_loader, max_age_s=5400, mtime=mtime)

    def analyze(self) -> dict:
        inputs: dict[str, Any] = {}
        for a in _INPUTS:
            v = self._load_input(a)
            if isinstance(v, dict):
                inputs[a] = v
        # ADR-066 Фаза 2: квитанция потребления за КАЖДЫЙ фактически прочитанный
        # вход (и только за него) — синтез chief и есть настоящий потребитель
        # аналитиков. Отказ записи не валит анализ (fail-open на границе).
        try:
            from spa_core.monitoring.consumption_receipts import write_receipt
            root = str(self.data_dir.parent.parent)
            for a in inputs:
                write_receipt(f"data/investment_os/{a}.json",
                              "com.spa.io_chief_investment", root=root)
        except Exception:  # noqa: BLE001
            pass
        if not inputs:
            return {"status": UNKNOWN,
                    "reason": "no analyst artifacts to synthesise yet (fail-closed)"}

        # ── posture: most-cautious of regime + red-team (surface, do not average) ──
        regime = (inputs.get("market_regime") or {}).get("combined_posture")
        threat = (inputs.get("red_team") or {}).get("posture")
        posture, conflicts = _synthesise_posture(regime, threat)

        # ── opportunities: top from stablecoin_yield (evidence preserved) ──
        sy = inputs.get("stablecoin_yield") or {}
        top_opps = (sy.get("top_stablecoin_yields") or [])[:3]

        # ── track + liquidity, surfaced verbatim (each carries its own L6/L4 tag) ──
        track = (inputs.get("reporting") or {}).get("track")
        exitliq = (inputs.get("liquidity") or {}).get("exit_liquidity")

        # ── восьмой вход: книги + ёмкость (директива владельца 31.08) ──
        # Строго ВНЕ постуры: координатор ёмкости — warn-only по решению владельца
        # 30.08 (owner_choice в карточке `owner-decision-koordinator-emkosti-...`);
        # пропусти его в _synthesise_posture — и предупреждение стало бы гейтом
        # через чёрный ход (постура ранга 3 включает no_increase в directive.py).
        # Не входит и в n_analysts: покрытие считает СЕМЬ продукт-агентов с их
        # артефактами; книги — прямой read_feed без артефакта-посредника.
        books = self._load_books()
        books_ok = isinstance(books, dict)
        capacity_violations: list = []
        if books_ok:
            capacity_violations = list(
                ((books.get("capacity") or {}).get("violations")) or [])

        # ── девятый вход: цена газа (ADR-183) — строго вне постуры ──
        # Advisory-агент не гейтит: режим газа НЕ участвует в _synthesise_posture
        # и в n_analysts (прямой read_feed без артефакта-посредника, как книги);
        # он только называется в house_view — решает по-прежнему владелец и
        # детерминированные гейты.
        gas = self._load_gas()
        gas_ok = isinstance(gas, dict)
        if gas_ok:
            try:
                from spa_core.monitoring.consumption_receipts import write_receipt
                write_receipt("data/gas_price_history.json",
                              "com.spa.io_chief_investment",
                              root=str(self.data_dir.parent.parent))
            except Exception:  # noqa: BLE001
                pass

        # honest coverage: which analysts were available vs UNKNOWN/missing.
        available = sorted(inputs.keys())
        missing = [a for a in _INPUTS if a not in inputs]

        return {
            "status": "ok",
            "house_view": {
                "overall_posture": posture,
                "conflicts": conflicts,     # surfaced, never averaged away
                "top_opportunities": top_opps,
                "evidenced_track": track,
                "exit_liquidity": exitliq,
                "threat_posture": threat,
                "regime": regime,
                "books": books if books_ok else UNKNOWN,
                "gas": gas if gas_ok else UNKNOWN,
                "risk_concerns": {
                    "protocol_risk": (inputs.get("protocol_risk") or {}).get("concern"),
                    "yield_quality": (inputs.get("yield_quality") or {}).get("concern"),
                    # Совокупная ёмкость трёх книг (phase A): warn-only —
                    # называется здесь, НИКОГДА не поднимает постуру.
                    "cross_book_capacity": (
                        capacity_violations if books_ok else UNKNOWN),
                },
            },
            "coverage": {"available": available, "missing_or_unknown": missing,
                         "n_analysts": len(inputs),
                         "books_input": "available" if books_ok else "unknown",
                         "gas_input": "available" if gas_ok else "unknown"},
            "owner_gate": True,
            "note": ("Advisory HOUSE-VIEW synthesis. RECOMMENDS only — it NEVER decides and moves NO "
                     "capital; any allocation change is the OWNER's decision (owner-gate). Conflicts are "
                     "surfaced, not averaged. Each input keeps its own L0-L6 evidence tag. Not a gate; the "
                     "deterministic RiskPolicy v1.0 remains the only execution gate."),
        }


# posture cautiousness rank (higher = more cautious); unknown labels sort most cautious (fail-safe).
_RANK = {"GREEN": 0, "NO_THREAT_OBSERVED": 0, "NEUTRAL": 1, "STABLE": 1, "YELLOW": 2,
         "THREATS_PRESENT": 2, "COMPRESSION": 2, "RED": 3, "CRITICAL": 3, "STRESS": 3}


def _synthesise_posture(regime: Optional[str], threat: Optional[str]) -> tuple[str, list[str]]:
    """Most-cautious of the regime + threat posture (fail-safe). Returns (posture, conflicts)."""
    def rank(x: Optional[str]) -> int:
        if not x or str(x).upper().startswith("UNKNOWN"):
            return 99
        return _RANK.get(str(x).upper(), 99)
    rr, rt = rank(regime), rank(threat)
    conflicts: list[str] = []
    if rr != 99 and rt != 99 and abs(rr - rt) >= 2:
        conflicts.append(f"regime={regime} vs threat={threat} diverge — surfaced, not averaged")
    if rr == 99 and rt == 99:
        return "UNKNOWN_CAUTIOUS", conflicts
    # most cautious wins; if one is unknown, use the known one's label
    if rr == 99:
        return (str(threat).upper(), conflicts)
    if rt == 99:
        return (str(regime).upper(), conflicts)
    return (str(regime).upper() if rr >= rt else str(threat).upper(), conflicts)


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return ChiefInvestmentAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.chief_investment")
    ap.add_argument("--check", action="store_true", help="synthesise + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = ChiefInvestmentAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
