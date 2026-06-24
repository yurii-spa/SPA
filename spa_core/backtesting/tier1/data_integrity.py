"""
spa_core/backtesting/tier1/data_integrity.py — historical-data integrity / no-lookahead.

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. A Tier-1 backtest is only
credible if its input data is clean: chronologically sorted, no FUTURE dates (lookahead),
no duplicate dates, no implausible APY, and no excessive gaps. This audits
data/bee/defillama_apy_history.json and writes data/tier1_data_integrity.json. If it finds
problems, the backtest's conclusions should be treated as suspect.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path

_DATA = Path(__file__).resolve().parents[3] / "data"
_CACHE = _DATA / "bee" / "defillama_apy_history.json"
_OUT = _DATA / "tier1_data_integrity.json"

MAX_GAP_DAYS = 7        # warn if a series has a gap longer than this
APY_MIN, APY_MAX = 0.0, 1.0   # decimal APY plausible band (0%..100%)


def audit(write: bool = True) -> dict:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    try:
        cache = json.loads(_CACHE.read_text())
    except Exception as exc:
        out = {"status": "NO_DATA", "error": str(exc), "checked": 0}
        return out

    per_protocol = {}
    total_issues = 0
    for key, val in (cache.get("pool_results") or {}).items():
        series = val.get("apy_series") if isinstance(val, dict) else None
        if not series:
            per_protocol[key] = {"status": "empty"}
            continue
        issues = []
        dates = []
        prev = None
        for pt in series:
            try:
                d = datetime.date.fromisoformat(pt["date"])
                apy = float(pt["apy"])
            except Exception:
                issues.append("unparseable_point")
                continue
            if d > today:
                issues.append(f"future_date:{d}")        # lookahead
            if not (APY_MIN <= apy <= APY_MAX):
                issues.append(f"apy_out_of_band:{apy}")
            if prev is not None:
                if d == prev:
                    issues.append(f"duplicate_date:{d}")
                elif d < prev:
                    issues.append(f"out_of_order:{d}")
                elif (d - prev).days > MAX_GAP_DAYS:
                    issues.append(f"gap_{(d - prev).days}d_before_{d}")
            prev = d
            dates.append(d)
        total_issues += len(issues)
        per_protocol[key] = {
            "n": len(dates),
            "first": dates[0].isoformat() if dates else None,
            "last": dates[-1].isoformat() if dates else None,
            "issues": issues[:10],   # cap noise
            "issue_count": len(issues),
            "clean": not issues,
        }

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_data_integrity",
        "llm_forbidden": True,
        "checked": len(per_protocol),
        "total_issues": total_issues,
        "status": "CLEAN" if total_issues == 0 else "ISSUES",
        "protocols": per_protocol,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1di_")
        with os.fdopen(fd, "w") as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, _OUT)
    return out


if __name__ == "__main__":
    a = audit()
    print(f"status={a['status']} checked={a.get('checked')} total_issues={a.get('total_issues')}")
    for k, v in a.get("protocols", {}).items():
        if not v.get("clean", True):
            print(f"  {k}: {v.get('issue_count')} issues {v.get('issues')[:3]}")
