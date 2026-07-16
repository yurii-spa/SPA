"""spa_core/cmo/editorial_agent.py — CMO editorial DRAFT agent (first live product-layer agent).

Turns the dry auto-changelog facts (scripts/generate_research_changelog.py → landing/src/data/changelog.json)
into "richer than dry" copy, validates it through the deterministic HONESTY-GATE, and stores it as a
DRAFT (`data/cmo_drafts/<date>.json`, status "draft"). It NEVER publishes — flow B (owner approves → publish)
is a later step. Deterministic template rewrite for now (no LLM / no key needed); an LLM rewrite drops in
later behind the SAME gate.

Hard boundaries (docs/CMO_EDITORIAL_LAYER.md): stdlib · fail-CLOSED (no data → no draft, never fabricate) ·
no fabricated numbers (every figure comes from the facts, re-checked by honesty_gate) · all disclaimers
present · never presents paper as live · never a solicitation · never auto-publishes.

CLI::
    python3 -m spa_core.cmo.editorial_agent            # build today's draft (if new data)
    python3 -m spa_core.cmo.editorial_agent --check    # dry-run: build + gate, print, do NOT write
"""
# LLM_FORBIDDEN  (this module is deterministic; the optional LLM rewrite, when added, stays behind honesty_gate)
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save
from spa_core.strategy_lab.swarm.common import append_daily_proof
from spa_core.cmo import honesty_gate

log = logging.getLogger("spa.cmo.editorial_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHANGELOG = _REPO_ROOT / "landing" / "src" / "data" / "changelog.json"
_DRAFTS_DIR = _REPO_ROOT / "data" / "cmo_drafts"

# The honesty footer — every one of the four disclaimer categories, true and always attached.
# (paper · not-a-guarantee · tail-shown · evidence-tagged; and explicitly not an offer.)
_FOOTER_EN = ("Paper research, advisory — variable and not a guarantee; the worst drawdown is shown, "
              "never hidden; every figure is evidence-tagged. Not an offer.")
_FOOTER_RU = ("Paper-исследование, advisory — переменная и не гарантия; макс. просадка показана, "
              "никогда не скрыта; каждое число evidence-tagged. Не оферта.")


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _load_latest_entry() -> Optional[dict]:
    """Return the newest dry changelog entry (the facts to rewrite), or None fail-closed."""
    try:
        data = json.loads(_CHANGELOG.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None
    return data[0]


def _rich_copy(entry: dict) -> tuple[str, str]:
    """Deterministic "richer than dry" rewrite (EN, RU). Uses ONLY numbers/tokens from ``entry`` and
    appends the honesty footer, so it passes the gate by construction. No LLM."""
    sig = entry.get("_sig") or {}
    n_days = sig.get("n_days")
    refusals = sig.get("refusals")
    dry_en = str(entry.get("summary") or "")
    dry_ru = str(entry.get("summaryRu") or "")

    # A warmer lede that leads with the differentiator (the refusal log), then the dry facts verbatim.
    lede_en = "The honest desk, in the open: "
    lede_ru = "Честный деск, в открытую: "
    if refusals is not None:
        lede_en += f"{refusals} yields declined this period, each logged and hash-chained. "
        lede_ru += f"{refusals} доходностей отклонено за период, каждое в hash-chained журнале. "
    if n_days is not None:
        lede_en += f"{n_days} days of evidenced paper track and counting. "
        lede_ru += f"{n_days} дней evidenced paper-трека и растёт. "

    body_en = f"{lede_en}\n\n{dry_en}\n\n{_FOOTER_EN}"
    body_ru = f"{lede_ru}\n\n{dry_ru}\n\n{_FOOTER_RU}"
    return body_en, body_ru


def build_draft(*, now: Optional[datetime] = None) -> Optional[dict]:
    """Build (but do not store) today's CMO draft from the latest changelog facts, gated. Returns the
    draft dict, or None fail-closed if there is no source data."""
    entry = _load_latest_entry()
    if entry is None:
        return None

    body_en, body_ru = _rich_copy(entry)
    # Gate each language against the SAME facts (the dry entry). Fail → fall back to the dry summary,
    # which is honest by construction, still footered so disclaimers are present.
    gate_en = honesty_gate.check(body_en, entry)
    gate_ru = honesty_gate.check(body_ru, entry)
    gated_ok = gate_en.passed and gate_ru.passed
    if not gated_ok:
        dry_en = f"{entry.get('summary','')}\n\n{_FOOTER_EN}"
        dry_ru = f"{entry.get('summaryRu','')}\n\n{_FOOTER_RU}"
        # re-gate the dry fallback; if even that fails, hold (return a held draft, never publish-eligible)
        fen, fru = honesty_gate.check(dry_en, entry), honesty_gate.check(dry_ru, entry)
        body_en, body_ru = dry_en, dry_ru
        gated_ok = fen.passed and fru.passed
        gate_reasons = {"en": fen.reasons, "ru": fru.reasons}
    else:
        gate_reasons = {"en": [], "ru": []}

    ts = _now(now)
    return {
        "slug": entry.get("slug", f"draft-{ts.strftime('%Y-%m-%d')}"),
        "date": ts.strftime("%Y-%m-%d"),
        "source_slug": entry.get("slug"),
        "title": entry.get("title"),
        "titleRu": entry.get("titleRu"),
        "body_en": body_en,
        "body_ru": body_ru,
        "evidence": entry.get("evidence"),
        "rewrite": "deterministic-template",   # LLM rewrite drops in here later (behind the same gate)
        "honesty_gate_passed": gated_ok,
        "gate_reasons": gate_reasons,
        # status is publish-eligible only if the gate passed; otherwise HELD for owner review, never auto.
        "status": "draft" if gated_ok else "held",
        "is_advisory": True,
        "note": "CMO draft — flow B: awaits owner approval, never auto-published.",
        "generated_at": ts.isoformat(),
    }


def run(*, now: Optional[datetime] = None, write: bool = True,
        drafts_dir: Optional[Path] = None) -> dict:
    """Build today's draft and (if new) store it to data/cmo_drafts/<date>.json + append proof.
    Returns a result dict. Never raises; fail-CLOSED (no data → created:False)."""
    ddir = Path(drafts_dir) if drafts_dir is not None else _DRAFTS_DIR
    draft = build_draft(now=now)
    if draft is None:
        return {"created": False, "reason": "no source data (fail-closed)"}
    ddir.mkdir(parents=True, exist_ok=True)
    out = ddir / f"{draft['date']}.json"
    # idempotent: same date + same source signature → do not rewrite/duplicate
    try:
        existing = json.loads(out.read_text())
        if existing.get("source_slug") == draft.get("source_slug"):
            return {"created": False, "reason": "unchanged source — draft exists", "path": str(out)}
    except (OSError, ValueError):
        pass
    if write:
        atomic_save(draft, str(out))
        try:
            append_daily_proof(
                {"agent": "cmo_editorial", "date": draft["date"], "status": draft["status"]},
                ddir / "cmo_editorial_proof.jsonl", day=draft["date"],
            )
        except Exception:  # noqa: BLE001 — proof best-effort
            log.warning("cmo_editorial: proof append failed", exc_info=True)
    return {"created": bool(write), "status": draft["status"],
            "honesty_gate_passed": draft["honesty_gate_passed"], "path": str(out)}


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.cmo.editorial_agent",
                                 description="CMO editorial DRAFT agent (deterministic, gated, never publishes)")
    ap.add_argument("--check", action="store_true", help="build + gate + print, do NOT write")
    args = ap.parse_args(argv)
    if args.check:
        draft = build_draft()
        if draft is None:
            print("no source data (fail-closed) — no draft")
            return 0
        print(json.dumps({"status": draft["status"], "honesty_gate_passed": draft["honesty_gate_passed"],
                          "gate_reasons": draft["gate_reasons"], "title": draft["title"]},
                         ensure_ascii=False, indent=2))
        return 0
    res = run()
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
