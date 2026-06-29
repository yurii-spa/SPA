"""
spa_core/strategy_lab/aggressive_lab/loader.py — consume Lane 1's realized series.

Reads ``data/aggressive_lab/<strategy_id>/realized_series.jsonl`` (one JSON object per line,
append-only, proof-chained by Lane 1) + the optional ``meta.json`` sidecar, and produces a
normalized in-memory view for the risk/ranking layer:

    LoadedStrategy(
        strategy_id, risk_class, risk_shape, headline_apy_pct, note,
        forward=Track(series=[{date, equity_usd, ...}]),   # the live accruing paper track
        backtest=Track(series=[...]),                       # the real 2024-26 backtest series
    )

The two tracks are the SAME JSONL split on each point's ``phase`` field ("forward" | "backtest").
A point with no ``phase`` defaults to "forward" (a brand-new live track). Each track's series is
shaped to be directly consumable by track_integrity.check_track_integrity + metrics (a list of
{"date","equity_usd"} dicts in stored order).

HONESTY / fail-CLOSED:
  • a malformed JSONL line (bad JSON, missing/non-numeric equity, missing date) is DROPPED and
    counted in ``n_malformed_lines`` — it never becomes a fabricated point. (Continuity/dup/gap
    faults are NOT decided here; they are the integrity gate's job downstream, on the clean series.)
  • a missing file / empty file → an EMPTY track (INSUFFICIENT_DATA downstream), never a crash.
  • we TRUST Lane 1's proof-chain (prev_hash/hash) — we do NOT re-verify the crypto here (that is
    Lane 1's domain); OUR integrity gate is the continuity gate (track_integrity), applied later.

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.aggressive_lab import (
    AGGRESSIVE_LAB_DIR,
    META_NAME,
    REALIZED_SERIES_NAME,
    RISK_SHAPES,
    RiskClass,
)


@dataclass
class Track:
    """One phase's series (forward OR backtest) as an ordered list of {date, equity_usd} points."""

    phase: str
    series: List[dict] = field(default_factory=list)

    @property
    def n_points(self) -> int:
        return len(self.series)


@dataclass
class LoadedStrategy:
    strategy_id: str
    risk_class: str = RiskClass.C_RISK_COMPENSATION.value  # default: most aggressive books are C
    risk_shape: str = "funding_flip"
    headline_apy_pct: Optional[float] = None
    note: str = ""
    forward: Track = field(default_factory=lambda: Track("forward"))
    backtest: Track = field(default_factory=lambda: Track("backtest"))
    n_malformed_lines: int = 0


def _coerce_point(obj: object) -> Optional[dict]:
    """A clean {date, equity_usd, phase, ret?} point, or None if the line is unusable.

    fail-CLOSED: a non-dict, a missing/non-string date, or a missing/non-finite/non-numeric
    equity_usd → None (dropped). bool is excluded from numeric (a True/False equity is malformed).
    """
    if not isinstance(obj, dict):
        return None
    date = obj.get("date")
    if not isinstance(date, str) or not date:
        return None
    eq = obj.get("equity_usd")
    if not isinstance(eq, (int, float)) or isinstance(eq, bool):
        return None
    eqf = float(eq)
    # fail-CLOSED on NaN/inf (poisons every downstream metric + emits invalid JSON tokens).
    if eqf != eqf or eqf in (float("inf"), float("-inf")):
        return None
    point = {"date": date[:10], "equity_usd": eqf}
    phase = obj.get("phase")
    point["phase"] = phase if phase in ("forward", "backtest") else "forward"
    ret = obj.get("ret")
    if isinstance(ret, (int, float)) and not isinstance(ret, bool):
        rf = float(ret)
        if rf == rf and rf not in (float("inf"), float("-inf")):
            point["ret"] = rf
    return point


def load_strategy(
    strategy_id: str,
    *,
    data_dir: Optional[Path] = None,
) -> LoadedStrategy:
    """Load ONE aggressive strategy's realized series + meta from disk. Fail-CLOSED: a missing file
    yields empty tracks (INSUFFICIENT_DATA downstream); a malformed line is dropped + counted."""
    root = (Path(data_dir) if data_dir is not None else AGGRESSIVE_LAB_DIR)
    sdir = root / strategy_id
    out = LoadedStrategy(strategy_id=strategy_id)

    # ── meta sidecar (risk_class / risk_shape / headline_apy) — optional, fail-safe ──
    meta_path = sdir / META_NAME
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a corrupt meta is ignored (defaults stand), never a crash
            meta = None
        if isinstance(meta, dict):
            rc = meta.get("risk_class")
            if rc in (c.value for c in RiskClass):
                out.risk_class = rc
            rs = meta.get("risk_shape")
            if rs in RISK_SHAPES:
                out.risk_shape = rs
            ha = meta.get("headline_apy_pct")
            if isinstance(ha, (int, float)) and not isinstance(ha, bool):
                out.headline_apy_pct = float(ha)
            note = meta.get("note")
            if isinstance(note, str):
                out.note = note

    # ── realized series JSONL (append-only) ──
    jpath = sdir / REALIZED_SERIES_NAME
    if not jpath.is_file():
        return out
    try:
        raw = jpath.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return out

    fwd: List[dict] = []
    bt: List[dict] = []
    malformed = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:  # noqa: BLE001 — a bad JSON line is dropped + counted, never fabricated
            malformed += 1
            continue
        pt = _coerce_point(obj)
        if pt is None:
            malformed += 1
            continue
        phase = pt.pop("phase")
        (bt if phase == "backtest" else fwd).append(pt)

    # also accept a risk_shape stamped inline on the first usable point if meta didn't set one
    out.forward = Track("forward", fwd)
    out.backtest = Track("backtest", bt)
    out.n_malformed_lines = malformed
    return out


def discover_strategy_ids(*, data_dir: Optional[Path] = None) -> List[str]:
    """Sorted list of strategy_ids that have a directory under the aggressive-lab data root.
    A strategy needs a realized_series.jsonl OR a meta.json to be discoverable (fail-safe: an
    unreadable root → empty list, never a crash)."""
    root = (Path(data_dir) if data_dir is not None else AGGRESSIVE_LAB_DIR)
    if not root.is_dir():
        return []
    out: List[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / REALIZED_SERIES_NAME).is_file() or (child / META_NAME).is_file():
            out.append(child.name)
    return out


def load_all(*, data_dir: Optional[Path] = None) -> Dict[str, LoadedStrategy]:
    """{strategy_id: LoadedStrategy} for every discoverable strategy. Deterministic (sorted)."""
    return {
        sid: load_strategy(sid, data_dir=data_dir)
        for sid in discover_strategy_ids(data_dir=data_dir)
    }
