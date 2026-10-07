"""ADR-612 — the Telegram Capital surface and Director OS print the SAME numbers from ONE input.

The bot may not read Company Truth (ADR-580 C4, ``test_company_truth_import_ratchet.py``), so it
reads the same canonical readers Company Truth is built from. This test is the seam check that
the two never drift: the canonical reader is patched ONCE at its source module, then both the
cockpit's cell builders and the bot's screens are rendered from it, and the counts must agree.

(Named ``test_mission_*`` — the ratchet's allowed prefix for Mission Control's own tests.)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.studio_os import company_truth as CT
from spa_core.studio_os import mission_control as MC
from spa_core.telegram.views import capital as C
from spa_core.tests.test_telegram_capital_surface import CIO_OK, NOW, RF_OK, lab_doc


@pytest.fixture
def one_input(monkeypatch):
    from spa_core.investment_cio import read as cio_read
    from spa_core.research_factory import read as rf_read
    from spa_core.trading_research import read_model
    monkeypatch.setattr(read_model, "trading_lab_view", lambda data_dir, **kw: lab_doc())
    monkeypatch.setattr(cio_read, "latest", lambda data_dir, now=None: CIO_OK)
    monkeypatch.setattr(rf_read, "latest", lambda data_dir: RF_OK)
    # the bot keeps its DEFAULT readers — they import the patched functions at call time
    monkeypatch.setitem(C.READERS, "now", lambda: NOW)
    monkeypatch.setitem(C.READERS, "data_dir", lambda: Path("/nonexistent"))
    for k, f in (("lab", C._lab_view), ("cio", C._cio_latest), ("research", C._research_latest)):
        monkeypatch.setitem(C.READERS, k, f)


def test_lab_counts_match_the_cockpit_cell(one_input):
    cell = CT.capital_trading_lab(Path("/nonexistent"), NOW)
    text, _ = C.render_lab(lang="ru")
    assert "Стратегий исследовано: {}".format(cell["candidates"]) in text
    assert "На бумажном форвард-тесте: {}".format(cell["forward"]) in text
    assert "Чемпионов: {}".format(cell["champions"]) in text


def test_oracle_stance_matches_the_cockpit_cell(one_input):
    section = MC._investment_cio_section(Path("/nonexistent"), NOW)
    cell = CT.capital_oracle(section)
    assert cell["stance"] == "INSUFFICIENT_EVIDENCE"
    text, _ = C.render_oracle(lang="ru")
    assert C._STANCE_RU[cell["stance"]] in text


def test_sherlock_usable_matches_the_cockpit_cell(one_input):
    section = MC._research_universe_section(Path("/nonexistent"), NOW)
    cell = CT.capital_sherlock(section)
    text, _ = C.render_sherlock(lang="ru")
    assert "С готовыми доказательствами: {}".format(cell["usable"]) in text
    # the cockpit has no «total» in this source (None) — the bot must not invent one either
    assert cell["total"] is None and "Всего фактов:" not in text


def test_lab_staleness_rule_is_the_same_threshold(one_input):
    from spa_core.trading_research.read_model import STALE_AFTER_H
    assert C._lab_stale_after_min() == STALE_AFTER_H * 60.0
