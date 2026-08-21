"""Regression tests for ``scripts/safe_site_push.py`` — the ONLY sanctioned path for
the autonomous orchestrator to push ``landing/`` changes to live earn-defi.com
(ADR-OWN-2026-07-autoship).

This module had ZERO dedicated coverage. It guards a critical human-in-the-loop:
on a GATED (owner-gated) site change it MUST (a) create a ``needs-owner`` card and
(b) Telegram-notify the owner (invariant #8). A latent bug broke exactly that path —
``_route_to_owner_card`` called ``create_card(card_type=...)`` while the real kwarg is
``tracker_type=...`` → ``TypeError`` on every gated push → the card was NEVER created
and the owner was NEVER notified (the push was still fail-closed, but the owner went
blind). These tests pin the whole state machine: GATED → card + notify with the FULL
card path; guard-error → fail closed (no push); CLEAN → delegate to the batch push
with the ``SPA_SITE_PUSH_VERIFIED=1`` marker.

Pure stdlib; the guard and the push/notify subprocesses are stubbed (offline, no
network, no Telegram, no real GitHub push).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import safe_site_push as sp
from spa_core.owner_queue import queue as ownq


class _FakeRun:
    """Records every ``subprocess.run`` call and returns rc=0 without executing."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), "kwargs": kwargs})
        return SimpleNamespace(returncode=0)


@pytest.fixture()
def fake_run(monkeypatch):
    fr = _FakeRun()
    monkeypatch.setattr(sp.subprocess, "run", fr)
    return fr


@pytest.fixture()
def tracker_tmp(monkeypatch, tmp_path):
    """Point the real card queue at a throwaway tracker dir."""
    d = tmp_path / "tracker"
    d.mkdir()
    monkeypatch.setattr(ownq, "TRACKER_DIR", d)
    return d


# --------------------------------------------------------------------------- #
# GATED (rc==2): the regression — must create a card AND notify with FULL path #
# --------------------------------------------------------------------------- #
def test_gated_creates_card_and_notifies_with_full_path(monkeypatch, fake_run, tracker_tmp):
    report = {
        "violations": [
            {"klass": "B", "file": "landing/src/pages/index.astro",
             "rule": "yield-number", "matched_text": "up to 12%"},
        ]
    }
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (2, report))

    rc = sp.main(["--files", "landing/src/pages/index.astro", "-m", "bump headline to 12%"])

    # Gated → blocked, exit 2 (push must NOT happen).
    assert rc == 2

    # A real needs-owner card was written to the tracker dir (pre-fix: TypeError → none).
    cards = list(tracker_tmp.glob("owner-decision-*.md"))
    assert len(cards) == 1, f"expected exactly one owner card, got {[c.name for c in cards]}"
    card = cards[0]
    assert "status: needs-owner" in card.read_text(encoding="utf-8")

    # The owner MUST be notified — and with the card's FULL path, not a bare basename
    # (a basename would not resolve against TRACKER_DIR and load_card would raise).
    notify_calls = [c for c in fake_run.calls if "notify" in c["cmd"]]
    assert len(notify_calls) == 1, "owner notify subprocess was not invoked exactly once"
    notify_arg = notify_calls[0]["cmd"][-1]
    assert notify_arg == str(card), "notify was passed the wrong path"
    assert notify_arg != card.name, "notify was passed a bare basename (the latent bug)"
    from pathlib import Path
    assert Path(notify_arg).is_absolute() and Path(notify_arg).exists()

    # No batch push in the gated path.
    assert not any("push_to_github_batch.py" in " ".join(c["cmd"]) for c in fake_run.calls)


# --------------------------------------------------------------------------- #
# Guard ERROR (rc==1): fail CLOSED — no card, no notify, no push               #
# --------------------------------------------------------------------------- #
def test_guard_error_fails_closed(monkeypatch, fake_run, tracker_tmp):
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (1, {}))

    rc = sp.main(["--files", "landing/src/pages/x.astro", "-m", "whatever"])

    assert rc == 1
    # Nothing ran: no notify, no push (fail closed).
    assert fake_run.calls == []
    assert list(tracker_tmp.glob("*.md")) == []


# --------------------------------------------------------------------------- #
# CLEAN (rc==0): delegate to the batch push WITH the verified marker           #
# --------------------------------------------------------------------------- #
def test_clean_delegates_to_batch_with_verified_marker(monkeypatch, fake_run):
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (0, {}))

    rc = sp.main(["--files", "landing/src/pages/x.astro", "-m", "safe copy tweak"])

    assert rc == 0
    push_calls = [c for c in fake_run.calls
                  if any("push_to_github_batch.py" in part for part in c["cmd"])]
    assert len(push_calls) == 1, "clean change should delegate to exactly one batch push"
    env = push_calls[0]["kwargs"].get("env", {})
    assert env.get("SPA_SITE_PUSH_VERIFIED") == "1", "batch push missing the verified marker"


# --------------------------------------------------------------------------- #
# No landing/ files: skip the guard entirely, still push                       #
# --------------------------------------------------------------------------- #
def test_no_site_files_skips_guard_still_pushes(monkeypatch, fake_run):
    # If the guard were consulted it would explode; assert it is never called.
    def _boom(files, msg):  # pragma: no cover - must not run
        raise AssertionError("guard must not run when there are no landing/ files")

    monkeypatch.setattr(sp, "_run_guard", _boom)

    rc = sp.main(["--files", "spa_core/foo.py", "-m", "code-only change"])

    assert rc == 0
    push_calls = [c for c in fake_run.calls
                  if any("push_to_github_batch.py" in part for part in c["cmd"])]
    assert len(push_calls) == 1
    env = push_calls[0]["kwargs"].get("env", {})
    assert env.get("SPA_SITE_PUSH_VERIFIED") == "1"


# --------------------------------------------------------------------------- #
# Спам владельцу (замер 21.08): один owner-gated вопрос — ОДНО уведомление,    #
# даже когда каждый цикл идёт в свежем worktree                               #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ledger_tmp(monkeypatch, tmp_path):
    """Включить персистентный реестр уведомлений и увести его в throwaway-файл.

    Без опт-ина реестр под pytest выключен (`_ledger_disabled`), чтобы прогон не
    читал/писал живое состояние. Этому тесту реестр НУЖЕН — включаем явно.
    """
    ledger = tmp_path / "owner_gate_notify_ledger.json"
    monkeypatch.setenv("SPA_OWNER_GATE_LEDGER_TEST", "1")
    monkeypatch.setenv("SPA_OWNER_GATE_LEDGER", str(ledger))
    return ledger


def _gated_once(monkeypatch, tmp_path, report, *, tracker_name):
    """Один цикл автономного оркестратора: СВОЙ пустой worktree-трекер, общий реестр."""
    d = tmp_path / tracker_name
    d.mkdir()
    monkeypatch.setattr(ownq, "TRACKER_DIR", d)
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (2, report))
    return sp.main(["--files", "landing/src/pages/packages.astro", "-m", "paper numbers"])


def test_same_owner_gated_change_notifies_owner_only_once(monkeypatch, fake_run,
                                                          ledger_tmp, tmp_path):
    report = {"violations": [
        {"klass": "B", "file": "landing/src/pages/packages.astro",
         "rule": "yield-number", "matched_text": "APY 8%"}]}

    # Два цикла подряд, КАЖДЫЙ в своём (пустом) worktree-трекере — точное
    # воспроизведение прода: worktree-проверка прежней карточки не видит.
    assert _gated_once(monkeypatch, tmp_path, report, tracker_name="tracker_cycle1") == 2
    assert _gated_once(monkeypatch, tmp_path, report, tracker_name="tracker_cycle2") == 2

    notify_calls = [c for c in fake_run.calls if "notify" in c["cmd"]]
    assert len(notify_calls) == 1, (
        "владельца уведомили дважды об ОДНОМ owner-gated вопросе — это и есть спам, "
        f"который чинится: {len(notify_calls)} уведомлений")


def test_different_violations_still_notify(monkeypatch, fake_run, ledger_tmp, tmp_path):
    """Обратный контроль: ДРУГОЙ набор нарушений — новый вопрос, новое уведомление."""
    report_a = {"violations": [
        {"klass": "B", "file": "landing/src/pages/packages.astro",
         "rule": "yield-number", "matched_text": "APY 8%"}]}
    report_b = {"violations": [
        {"klass": "L", "file": "landing/src/pages/faq.astro",
         "rule": "legal-disclaimer", "matched_text": "no lock-up"}]}

    assert _gated_once(monkeypatch, tmp_path, report_a, tracker_name="t1") == 2
    assert _gated_once(monkeypatch, tmp_path, report_b, tracker_name="t2") == 2

    notify_calls = [c for c in fake_run.calls if "notify" in c["cmd"]]
    assert len(notify_calls) == 2, (
        "разные owner-gated вопросы обязаны уведомлять раздельно — иначе дедуп "
        "проглотил бы настоящий второй вопрос")


# --------------------------------------------------------------------------- #
# Единичные проверки логики реестра (часы — вход, fail-OPEN на битом файле)    #
# --------------------------------------------------------------------------- #
def test_ledger_cooldown_expires(monkeypatch, ledger_tmp):
    import datetime as dt

    monkeypatch.setenv("SPA_OWNER_GATE_LEDGER_TEST", "1")
    t0 = dt.datetime(2026, 8, 21, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock (обе стороны часов — вход, тест бессмертен)
    sp._record_notified("abc123", now=t0)

    within, _ = sp._recently_notified("abc123", now=t0 + dt.timedelta(hours=1))
    assert within is True, "в пределах окна отката повтор обязан подавляться"

    after, _ = sp._recently_notified("abc123",
                                     now=t0 + dt.timedelta(hours=sp._RENOTIFY_COOLDOWN_H + 1))
    assert after is False, "после окна отката владельца можно переспросить (потерянное первое)"


def test_ledger_unreadable_fails_open(monkeypatch, ledger_tmp):
    # Битый реестр НЕ имеет права подавить вопрос владельцу (fail-OPEN сюда — по замыслу).
    ledger_tmp.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("SPA_OWNER_GATE_LEDGER_TEST", "1")
    skip, _ = sp._recently_notified("whatever")
    assert skip is False, "нечитаемый реестр обязан пропустить уведомление, а не съесть его"


def test_ledger_disabled_under_pytest_without_optin(monkeypatch):
    # Без опт-ина реестр молчит: прогон тестов не читает и не пишет живое состояние.
    monkeypatch.delenv("SPA_OWNER_GATE_LEDGER_TEST", raising=False)
    monkeypatch.delenv("SPA_OWNER_GATE_LEDGER", raising=False)
    assert sp._ledger_disabled() is True
    sp._record_notified("x")  # no-op, must not raise or write anywhere
    assert sp._recently_notified("x") == (False, None)
