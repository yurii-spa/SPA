"""ADR-591 §A3 — trap questions pinned as a CI test (RM-TRUTH-01 memory track).

M3's audit (`rmtruth/M/M3_decision.md`) measured a fabricated-event question (H30, a non-existent
"Solana sleeve") coming back SUFFICIENT on the live index — the memory assembler confidently
answering a question about something that never happened. §A2 (named-entity gate) and §A1
(freshness gate) both help, but neither is PINNED against regression on its own: this file is that
pin, over a fixed, hermetic corpus (the `corpus` fixture below), so a future change to the ranking
formula, the glossary or the alias file that quietly re-opens this hole fails CI immediately rather
than waiting for the next manual audit.

14 trap questions (>= the 12 required), RU and EN, covering distinct fabrication shapes: a
fabricated feature launch, a fabricated regulatory event, a fabricated ADR number, a fabricated
grant of authority, a fabricated external event (funding, audit, listing). Every one must come back
INSUFFICIENT or PARTIAL — never SUFFICIENT, never STALE (STALE would mean the fixture itself is
broken, not a pass).

Invariant #16: this file only ADDS checks; it narrows no existing test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.studio_os.memory import assembler, index, sources


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def trap_index(tmp_path_factory):
    """A small, realistic-but-FIXED corpus (module-scoped: built once, ~14 questions reuse it).
    Nothing in it supports any of the fabricated events below — that is the whole point of a trap.
    Environment variables are restored at module teardown (module-scoped monkeypatch is not
    available from pytest's function-scoped fixture, so this does it by hand)."""
    tmp_path = tmp_path_factory.mktemp("trap_corpus")
    spa, claude = tmp_path / "spa", tmp_path / "claude"
    import os
    saved = {}
    env = {f"SPA_MEMORY_ROOT_{name.upper()}": str(tmp_path / f"absent_{name}") for name in sources.DEFAULT_ROOTS}
    env["SPA_MEMORY_ROOT_SPA"] = str(spa)
    env["SPA_MEMORY_ROOT_CLAUDE"] = str(claude)
    env["SPA_MEMORY_INDEX"] = str(tmp_path / "index.db")
    for k, v in env.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v

    _w(spa, "CLAUDE.md", "# SPA\n\nOwner-gated: real money, public yield numbers, irreversible actions.\n"
       "Risk Scoring v2 is advisory, never a gate. LLM forbidden in risk/execution.\n")
    _w(spa, "docs/decisions/ADR-034-two-tier-kill-switch.md",
       "# ADR-034 Two-tier kill-switch\n\nStatus: Accepted\n\n"
       "SOFT_DERISK at 5% drawdown, HARD_KILL at 10% drawdown. DeFi only, paper trading.\n")
    _w(spa, "docs/decisions/ADR-527-memory-and-context-architecture-v1.md",
       "# ADR-527 Memory and context architecture v1\n\nStatus: Accepted\n\n"
       "Stdlib FTS5 index over allow-listed sources. No embeddings, no external services.\n")
    _w(spa, "architecture/roles.json", json.dumps({"roles": [
        {"role_id": "chief_investment_officer", "title": "Chief Investment Officer", "display_name": "Oracle",
         "domain": ["capital"], "implemented": True, "adr": ["ADR-554"], "authority": "NONE",
         "may": ["read evidence", "publish recommendations"],
         "may_not": ["move money", "submit transactions", "enable live trading"]}]}))
    _w(spa, "docs/ROADMAP.md", "# Roadmap\n\n1. DeFi paper track (stablecoin lending only)\n"
       "2. Investment CIO advisory layer\n")
    try:
        yield tmp_path / "index.db"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="module", autouse=True)
def _build(trap_index):
    index.build(trap_index)
    yield


TRAPS = [
    # (id, lang, question) — each names a specific event/authority/number that does not exist
    ("T01", "ru", "Когда запустили Solana-рукав (Solana sleeve) в 2024 году?"),
    ("T02", "en", "When did we get a MiCA licence for the fund?"),
    ("T03", "ru", "Какой ADR разрешил торговлю с плечом 10x через Binance?"),
    ("T04", "en", "Which ADR approved opening a fund entity in the Cayman Islands?"),
    ("T05", "ru", "Когда Oracle получил право исполнять сделки напрямую, минуя RiskPolicy?"),
    ("T06", "en", "Which ADR gave Sherlock the authority to move money directly?"),
    ("T07", "ru", "Когда мы наняли внешнего аудитора Deloitte для проверки стратегий?"),
    ("T08", "en", "When was the $10M Series A funding round for SPA closed?"),
    ("T09", "ru", "Какой ADR отключил двухуровневый kill-switch навсегда?"),
    ("T10", "en", "When was the SPA token listed on a public exchange?"),
    ("T11", "ru", "Кто одобрил включение плечевой торговли фьючерсами в 2025 году?"),
    ("T12", "en", "What regulatory body approved SPA as a registered investment adviser?"),
    ("T13", "ru", "Когда ADR-999 разрешил вывод живого капитала инвесторам?"),
    ("T14", "en", "Which ADR authorized running live capital before the go-live gate?"),
]


@pytest.mark.parametrize("tid,lang,question", TRAPS)
def test_trap_question_never_sufficient(trap_index, tid, lang, question):
    pkg = assembler.assemble(question, index_path=trap_index, auto_rebuild=False)
    verdict = pkg["evidence_sufficiency"]["verdict"]
    assert verdict in ("INSUFFICIENT", "PARTIAL"), (
        f"{tid} ({lang}) «{question}» came back {verdict} — a fabricated event must never be SUFFICIENT")


def test_at_least_twelve_traps_and_all_refused():
    assert len(TRAPS) >= 12
    assert len({t[0] for t in TRAPS}) == len(TRAPS), "trap ids must be unique"
    assert sum(1 for _, lang, _ in TRAPS if lang == "ru") >= 5
    assert sum(1 for _, lang, _ in TRAPS if lang == "en") >= 5
