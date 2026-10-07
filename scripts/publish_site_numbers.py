#!/usr/bin/env python3
"""publish_site_numbers.py — step (1е) of the orchestrator as ONE deterministic command (ADR-630).

    build (weekly, judged by the PUBLISHED shelf) → publication gate → push via safe_site_push.py

and, on every later run, the RETRY after the owner's decision: a built-but-undelivered shelf that now
carries an owner-closed approval naming it (`publication-approves: … sha256:…`) is pushed; one still
waiting is left alone (no daily rebuild); one that no approval can clear (stale, inputs lost) is
superseded once and rebuilt. Nothing here decides a public number: the gate and the owner do.

Exit: 0 nothing to do / pushed · 2 NOT MEASURED · 3 sequencing gate · 4 waiting for the owner ·
otherwise the push's own code (safe_site_push: 2 = routed to an owner card).
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(*, published_at=None, published=None, out=None, bsn=None, ssp=None, message=None,
        dry_run: bool = False) -> int:
    bsn = bsn or _load("_bsn_publish", "scripts/build_site_numbers.py")
    ssp = ssp or _load("_ssp_publish", "scripts/safe_site_push.py")
    try:
        outcome = bsn.run(published_at=published_at, if_due=True, out=out, published=published)
    except bsn.NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2
    except bsn.SequencingViolation as exc:
        print(f"ГЕЙТ ПОСЛЕДОВАТЕЛЬНОСТИ ОТКАЗАЛ — {exc}")
        return 3
    if outcome.get("not_delivered"):
        print(outcome["reason"])
        return 4
    if not (outcome.get("published") or outcome.get("ready")):
        print(f"публикация не назначена: {outcome['reason']}")
        return 0
    shelf = outcome["artifact"]
    msg = message or ("chore(site numbers): weekly shelf (ADR-630)" if outcome.get("published")
                      else "chore(site numbers): owner-approved weekly shelf (ADR-630)")
    print(("собрана новая витрина" if outcome.get("published") else "одобренная витрина") + f" → {shelf}")
    if dry_run:
        print(f"DRY-RUN: витрина НЕ публикуется (был бы пуш {shelf} через safe_site_push.py)")
        return 0
    return ssp.main(["--files", str(shelf), "-m", msg])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--published-at", default=None)
    ap.add_argument("--published", default=None, help="the PUBLISHED shelf (default: the origin mirror)")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and gate as usual, but publish NOTHING (no push)")
    a = ap.parse_args(argv)   # --help / -h ⇒ prints and exits 0 HERE, before any build or push;
    #                           an unknown argument ⇒ exits 2 here, before any write (CAPITAL-SOURCES-01 §0)
    return run(published_at=a.published_at, published=Path(a.published) if a.published else None,
               dry_run=a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
