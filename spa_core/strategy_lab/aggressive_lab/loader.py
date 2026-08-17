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
  • LIVENESS IS CARRIED, NOT DROPPED: each point's ``killed`` flag is aggregated onto the Track
    (killed_since / n_killed_points / killed_final). A dead book's flat line must never reach the
    ranking layer looking like a calm one — see Track's docstring for the measured failure.

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
    """One phase's series (forward OR backtest) as an ordered list of {date, equity_usd} points,
    PLUS the book's liveness on that track.

    WHY LIVENESS LIVES HERE (docs/AGGRESSIVE_PANEL_FEEDS.md §5). Lane 1 stamps ``killed`` on every
    point it writes (harness.py), and until 2026-08-16 nothing downstream read it: this file and
    scorecard.py contained not one mention of the word. A liquidated book keeps emitting points at
    a frozen equity, so it hands the ranking layer a perfectly flat line — zero volatility, zero
    drawdown — and beats the books that are still trading. The flag was never missing; it was
    simply dropped on the floor at the first consumer. It is carried on the Track, not stamped into
    each point dict, so the point shape the metrics/integrity layers consume is unchanged.
    """

    phase: str
    series: List[dict] = field(default_factory=list)
    #: how many points on this track were written AFTER the book was killed
    n_killed_points: int = 0
    #: first date whose point reported killed=True (None if the book never died on this track)
    killed_since: Optional[str] = None
    #: the book's state at the LAST point of this track
    killed_final: bool = False

    @property
    def n_points(self) -> int:
        return len(self.series)

    @property
    def final_equity_usd(self) -> Optional[float]:
        """Last marked equity on this track (None on an empty track). This is the number that says
        how much capital a DEAD book is sitting on."""
        return float(self.series[-1]["equity_usd"]) if self.series else None


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

    @property
    def killed(self) -> bool:
        """Is this book dead? The FORWARD track is the book's current life when it has one; a book
        with no forward points is judged by where its backtest ended."""
        return self.forward.killed_final if self.forward.n_points else self.backtest.killed_final

    @property
    def killed_since(self) -> Optional[str]:
        """Earliest date on either track at which the book reported itself killed."""
        dates = [t.killed_since for t in (self.backtest, self.forward) if t.killed_since]
        return min(dates) if dates else None

    @property
    def n_killed_points(self) -> int:
        return self.backtest.n_killed_points + self.forward.n_killed_points


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
    # liveness, tracked per phase alongside the points (see Track's docstring for why)
    kills: Dict[str, dict] = {
        "forward":  {"n": 0, "since": None, "last": False},
        "backtest": {"n": 0, "since": None, "last": False},
    }
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
        # ``killed`` is Lane 1's own verdict on the book. A point that does not carry the field is
        # NOT evidence of death (old points predate the flag) — absence means "no kill reported",
        # and the panel-level summary is what tells a reader whether anyone reported one at all.
        k = kills[phase]
        if obj.get("killed") is True:
            k["n"] += 1
            if k["since"] is None:
                k["since"] = pt["date"]
            k["last"] = True
        else:
            # a book that reports itself alive again (restart / un-kill) stops being dead-final;
            # the FIRST kill date is kept, so the history of the death is not erased.
            k["last"] = False

    # also accept a risk_shape stamped inline on the first usable point if meta didn't set one
    out.forward = Track("forward", fwd, n_killed_points=kills["forward"]["n"],
                        killed_since=kills["forward"]["since"],
                        killed_final=kills["forward"]["last"])
    out.backtest = Track("backtest", bt, n_killed_points=kills["backtest"]["n"],
                         killed_since=kills["backtest"]["since"],
                         killed_final=kills["backtest"]["last"])
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
