"""
spa_core.strategies.strategy_config — ADR-033 strategy-loop activation config.

Reads ``data/strategy_config.json`` — the persistent control file that records
whether the shadow→allocator feedback loop (the "strategy loop") is running in

    * ``"off"``     — loop is fully disabled; the allocator never consults
                      shadow strategies (legacy behaviour pre-ADR-033),
    * ``"shadow"``  — loop is **observability-only**: the tournament / shadow
                      leaderboard is evaluated and logged each cycle, but the
                      result NEVER changes the real allocation (ADR-033 default),
    * ``"active"``  — loop may steer the real allocation once a shadow strategy
                      reaches medium/high confidence (full SPA-V408 behaviour).

The cycle runner reads this file once per cycle and emits a log line + a note so
that the activation state is auditable in the daily record. The module is
strictly read-only, stdlib-only, and **fail-safe**: a missing or malformed file
degrades to the ADR-033 default (``"shadow"``) without raising, so a bad config
can never crash a paper-trading cycle.

See ``docs/adr/ADR-033-strategy-loop-activation.md``.
"""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "data" / "strategy_config.json"

#: Recognised modes, lowest→highest authority over the real allocation.
VALID_MODES = ("off", "shadow", "active")

#: ADR-033 default when the file is absent / unreadable / invalid.
DEFAULT_MODE = "shadow"


def load_strategy_config(data_dir: str | Path | None = None) -> dict:
    """Return the normalised strategy-loop config.

    Parameters
    ----------
    data_dir :
        Directory holding ``strategy_config.json``. ``None`` → repo ``data/``.

    Returns
    -------
    dict
        Always a well-formed dict with at least::

            {
              "strategy_loop_mode": "off" | "shadow" | "active",
              "activated_at":       <str | None>,
              "reason":             <str | None>,
            }

        Unknown / malformed modes fall back to :data:`DEFAULT_MODE`. The
        ``source`` key reports where the value came from
        (``"file"`` / ``"default_missing"`` / ``"default_invalid"``).
    """
    path = (
        Path(data_dir) / "strategy_config.json"
        if data_dir is not None
        else _DEFAULT_CONFIG_PATH
    )

    if not path.exists():
        return {
            "strategy_loop_mode": DEFAULT_MODE,
            "activated_at": None,
            "reason": None,
            "source": "default_missing",
        }

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "strategy_loop_mode": DEFAULT_MODE,
            "activated_at": None,
            "reason": None,
            "source": "default_invalid",
        }

    if not isinstance(raw, dict):
        return {
            "strategy_loop_mode": DEFAULT_MODE,
            "activated_at": None,
            "reason": None,
            "source": "default_invalid",
        }

    mode = raw.get("strategy_loop_mode")
    mode = str(mode).strip().lower() if mode is not None else ""
    if mode not in VALID_MODES:
        mode = DEFAULT_MODE
        source = "default_invalid"
    else:
        source = "file"

    return {
        "strategy_loop_mode": mode,
        "activated_at": raw.get("activated_at"),
        "reason": raw.get("reason"),
        "source": source,
    }


def get_strategy_loop_mode(data_dir: str | Path | None = None) -> str:
    """Convenience: just the validated mode string (``off``/``shadow``/``active``)."""
    return load_strategy_config(data_dir)["strategy_loop_mode"]


def loop_enabled_for_allocator(data_dir: str | Path | None = None) -> bool:
    """Whether the allocator may steer real allocation from shadow strategies.

    True only in ``"active"`` mode. In ``"off"`` and ``"shadow"`` modes the
    allocator must run with ``strategy_loop_enabled=False`` so the real target
    allocation is never altered — ``"shadow"`` still evaluates and logs the
    tournament, but advisory-only (ADR-033).
    """
    return get_strategy_loop_mode(data_dir) == "active"


__all__ = [
    "load_strategy_config",
    "get_strategy_loop_mode",
    "loop_enabled_for_allocator",
    "VALID_MODES",
    "DEFAULT_MODE",
]
