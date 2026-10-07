"""Hermetic scene for the ARB continuity tests (ADR-610).

A disposable canonical root (real curated contract + real cited ADRs copied from this repository) and a
SYNTHETIC published Mission Control bundle whose Company Truth cells have the production shape. Nothing
here reads the live data/ tree, the mirror or the network.
"""
# FROZEN-DATE-OK: injected-clock — AT is the scene anchor; every timestamp below is derived from it by
# _at(hours) and passed into continuity.build(generated_at=...) / continuity.check(now=...).
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.studio_os.memory import continuity as c

REPO = Path(__file__).resolve().parents[2]
AT = "2026-10-07T00:10:00Z"
SHA_A = "a" * 40
SHA_B = "b" * 40


def at(hours: float = 0.0) -> str:
    d = datetime.fromisoformat(AT.replace("Z", "+00:00")) + timedelta(hours=hours)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cell(value, display, metric, canon, as_of=None, state="MEASURED", **extra):
    out = dict(value=value, display_ru=display, display_en=display, metric_type=metric, state=state, as_of=as_of,
               canon=canon, freshness={"age_min": 1.0, "stale_after_min": 120.0, "rule": "declared"},
               unknown_ru="не измерено", unknown_en="not measured")
    out.update(extra)
    return out


def truth(computed_at: str) -> dict:
    prof = lambda metric, state, **kw: cell({"reportable": state == "MEASURED"}, None, metric, "data/x.json",
                                            computed_at, state=state, **kw)
    return {
        "schema": "company-truth/1", "computed_at": computed_at,
        "home": {"money_chip": cell(0, None, "POLICY", "paper_trading_status.execution_mode", computed_at, usd=0),
                 "strip": [cell({"apy_pct": 4.9}, "Консервативный: 4.9 % годовых", "REALIZED_PAPER",
                                "data/equity_curve_daily.json", computed_at, key="yield")]},
        "capital": {
            "trading_lab": cell({}, None, "OPERATIONAL", "trading_lab_view", computed_at, candidates=138, forward=5,
                                champions=0, chain_ok=True),
            "btc": cell({"1D": {"long": 1}}, "Консенсус: 1D лонг", "OBSERVED", "trading_lab_view.btc", computed_at),
            "oracle": cell({"stance": "INSUFFICIENT_EVIDENCE"}, None, "DECISION", "data/investment_cio/ledger.jsonl",
                           computed_at, stance="INSUFFICIENT_EVIDENCE"),
            "sherlock": cell({"evidence_ready": 1, "paper_active": 1, "cio_eligible": 0}, None, "COUNT",
                             "data/research_factory/ledger.jsonl", computed_at, usable=1, total=None),
            "readiness": cell({"status": "NOT_READY"}, None, "READINESS", "data/execution_readiness.json",
                              computed_at, ready=False, conditions_open=4),
            "defi": {"targets": cell({"conservative": 6.0}, "Консервативный 6.0 %", "TARGET",
                                     "landing/src/lib/tier_bands.json")},
        },
        "studio": {
            "claude_work": cell({"active": 1}, None, "OPERATIONAL", "data/session_changes.jsonl", computed_at,
                                epic="ARB-CONTINUITY-01"),
            "fleet": cell({"ok": 86, "declared": 92}, "в норме 86 из 92", "COUNT", "architecture/manifest.json", computed_at),
            "tasks": cell({"queued": 1}, "в очереди: 1", "COUNT", "build_loop.board"),
            "self_heal": cell({"healthy": True}, "провалов: 0", "OPERATIONAL", "data/self_heal_status.json", computed_at),
            "memory": cell({"lag": 0, "newest_indexed": 610, "truth_overrides": 12}, None, "OPERATIONAL",
                           "architecture/memory_truth.json", computed_at, state="MEASURED_ZERO", lag=0),
            "problems": cell({"open": ["com.spa.x.exit_nonzero_1"]}, "открыто: 1", "COUNT", "data/problems.json",
                             computed_at),
        },
        "product": {
            "public_release": cell({"published_at": "2026-10-01", "measured_at": "2026-10-01",
                                    "next_publication": "2026-10-08"}, None, "TIMESTAMP",
                                   "landing/src/data/site_numbers.json", computed_at),
            "website_health": cell({"status": "OK"}, "сайт: данные от 2026-10-01", "READINESS",
                                   "data/site_freshness_report.json", computed_at),
            "profiles": {"conservative": prof("REALIZED_PAPER", "MEASURED", rate_ru="4.9 %", evidenced_days=105),
                         "balanced": prof("REALIZED_PAPER", "NOT_ENOUGH_HISTORY", accumulating_days=5),
                         "aggressive": prof("REALIZED_PAPER", "NOT_ENOUGH_HISTORY", accumulating_days=5)},
        },
        "decisions": {"state": "MEASURED", "counts": {"owner": 3, "undeclared": 11},
                      "groups": {"owner": [{"title_ru": "Диск забит"}]}},
    }


def write_mission(dirpath: Path, computed_at: str = AT, mutate=None) -> Path:
    """A published bundle: current.json pointer → b-…/mission.json (the production layout)."""
    t = truth(computed_at)
    if mutate:
        mutate(t)
    bundle = "b-20261007T001000Z-0123abcd"
    (dirpath / bundle).mkdir(parents=True, exist_ok=True)
    (dirpath / bundle / "mission.json").write_text(json.dumps({"schema": "mission-control/1", "truth": t}))
    (dirpath / "current.json").write_text(json.dumps({"bundle": bundle, "schema": "mission-control/1"}))
    return dirpath / "current.json"


def write_receipt(path: Path, sha: str = SHA_A, result: str = "IN_SYNC", ts: str = AT) -> Path:
    path.write_text(json.dumps({"timestamp": ts, "result": result, "origin_main": sha}))
    return path


def make_root(tmp: Path) -> Path:
    """Copy the REAL contract and every ADR it cites (plus the ADR index's neighbours it needs)."""
    root = tmp / "root"
    for rel in c.REQUIRED_INPUTS:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst)
    ledger = (REPO / c.LEDGER_FILE).read_text(encoding="utf-8")
    ids = set(c._cited_adrs(c.parse_ledger(ledger), (REPO / "docs/ROADMAP.md").read_text(encoding="utf-8")))
    (root / "docs/decisions").mkdir(parents=True, exist_ok=True)
    for p in (REPO / "docs/decisions").glob("ADR-*.md"):
        aid = re.match(r"(ADR-\d+)-", p.name)
        if aid and aid.group(1) in ids:
            shutil.copyfile(p, root / "docs/decisions" / p.name)
    return root


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                               "HOME": str(root)}).stdout.strip()


def git_init(root: Path) -> str:
    """A git root whose `origin` is a local bare repository — `git ls-remote origin` answers offline."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "scene")
    bare = root.parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    git(root, "remote", "add", "origin", str(bare))
    publish(root)
    return git(root, "rev-parse", "HEAD")


def publish(root: Path) -> str:
    """Move the server's main to the root's HEAD (what a delivery does)."""
    git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
    return git(root, "rev-parse", "HEAD")
