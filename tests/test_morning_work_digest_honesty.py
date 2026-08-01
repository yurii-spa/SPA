"""Honesty tests for ``scripts/morning_work_digest.py`` (live agent ``com.spa.work_digest``).

Why this file exists (цикл #77, card ``agent-morning-digest-claims-delivery-it-never-made``)
--------------------------------------------------------------------------------------------
This is the one agent that talks to the owner directly every morning, and it had **zero**
tests. Three statements it made were wider than what it measured:

1. ``digest sent`` printed unconditionally. ``TelegramBot.send_message`` returns
   ``Optional[Dict]`` and never raises, so a failed send was reported as a successful one.
   Not hypothetical — ``/tmp/spa_work_digest.log`` for 2026-07-26 holds
   ``API call sendMessage failed: <urlopen error [Errno 65] No route to host>`` immediately
   followed by ``digest sent`` and ``exit 0``.
2. ``Вчера было тихо`` printed when every source returned ``""`` — including when they
   returned ``""`` *because reading them failed*.
3. The "yesterday" window compared UTC stamps from ``session_changes.jsonl`` against naive
   LOCAL bounds, sliding the window by the UTC offset (2h in CEST) in both directions.

Every test below is hermetic: no network, no Telegram, no git remote, tmp dirs only.
The tests marked POSITIVE CONTROL are green both before and after the fix — they pin that the
honest paths were not traded away for the new ones (invariant #16).
"""
from __future__ import annotations

import importlib.util
import io
import json
import contextlib
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TARGET = _REPO_ROOT / "scripts" / "morning_work_digest.py"


def _load_module():
    """Fresh import of the script under test (it is a script, not a package module)."""
    spec = importlib.util.spec_from_file_location("spa_morning_work_digest", _TARGET)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text_and_unread(result):
    """Read a gatherer result under BOTH contracts (pre- and post-цикл #77).

    Before the fix the gatherers returned a bare string; now they return ``(text, unread)``.
    These tests are about WHAT IS CLAIMED, not about a return shape: normalising here keeps
    every red below attributable to the defect itself, and lets the POSITIVE CONTROLS stay
    green on the pre-fix code — which is the only thing that makes them controls.
    """
    if isinstance(result, tuple):
        return result[0], list(result[1])
    return result, []


def _git_run(log_rc=0, log_out="", log_err="", fetch_rc=0, fetch_err="", claude=None):
    """A ``subprocess.run`` stand-in that answers git and ``claude`` separately.

    Patching ``subprocess.run`` (rather than the gatherer functions) keeps these tests
    runnable against BOTH code versions — a lambda returning the new tuple shape would blow
    up on the old code for a reason that has nothing to do with the defect under test.
    """
    def run(cmd, **_kw):
        argv = list(cmd)
        if argv[:2] == ["git", "fetch"]:
            return subprocess.CompletedProcess(argv, fetch_rc, b"", fetch_err.encode())
        if argv[:1] == ["git"]:
            return subprocess.CompletedProcess(argv, log_rc, log_out, log_err)
        if claude is None:
            raise OSError("claude binary not available in tests")
        if isinstance(claude, BaseException):
            raise claude
        return subprocess.CompletedProcess(argv, 0, claude, "")
    return run


class _FakeBot:
    """Stands in for ``spa_core.telegram.bot.TelegramBot`` — records, never sends."""

    def __init__(self, resp):
        self._resp = resp
        self.sent: list[str] = []

    def __call__(self):  # the module calls ``TelegramBot()``
        return self

    def send_message(self, text, **_kw):
        self.sent.append(text)
        return self._resp


@contextlib.contextmanager
def _bot(resp):
    """Inject a fake ``spa_core.telegram.bot`` for the duration of the block."""
    import types

    fake_mod = types.ModuleType("spa_core.telegram.bot")
    bot = _FakeBot(resp)
    fake_mod.TelegramBot = bot
    saved = sys.modules.get("spa_core.telegram.bot")
    sys.modules["spa_core.telegram.bot"] = fake_mod
    try:
        yield bot
    finally:
        if saved is None:
            sys.modules.pop("spa_core.telegram.bot", None)
        else:
            sys.modules["spa_core.telegram.bot"] = saved


class DeliveryVerdictTests(unittest.TestCase):
    """Defect 1 — a send that did not happen must never read as one that did."""

    def setUp(self):
        self.m = _load_module()

    def test_none_response_is_not_delivered(self):
        """``None`` is what the bot returns on network/HTTP failure, flood-drop, no chat_id."""
        delivered, reason = self.m.delivery_verdict(None)
        self.assertFalse(delivered)
        self.assertIn("None", reason)

    def test_ok_true_is_delivered(self):
        """POSITIVE CONTROL — the real Telegram success document still counts as delivered."""
        delivered, reason = self.m.delivery_verdict({"ok": True, "result": {"message_id": 7}})
        self.assertTrue(delivered)
        self.assertEqual(reason, "")

    def test_ok_false_is_not_delivered_and_quotes_description(self):
        delivered, reason = self.m.delivery_verdict(
            {"ok": False, "description": "Bad Request: chat not found"})
        self.assertFalse(delivered)
        self.assertIn("chat not found", reason)

    def test_unknown_shape_is_not_measured_not_success(self):
        """A document without ``ok`` is unrecognised — fail-CLOSED, and quoted verbatim."""
        delivered, reason = self.m.delivery_verdict({"result": {"message_id": 7}})
        self.assertFalse(delivered)
        self.assertIn("message_id", reason)

    def test_bool_sender_contract_is_read_explicitly(self):
        """The repo's other sender returns a bool; both values are read, not truthy-tested."""
        self.assertEqual(self.m.delivery_verdict(True)[0], True)
        self.assertEqual(self.m.delivery_verdict(False)[0], False)


class MainReportsDeliveryTruthfullyTests(unittest.TestCase):
    """Defect 1, end to end — the log line is the only delivery evidence the system keeps."""

    def setUp(self):
        self.m = _load_module()
        self.m.build_digest = lambda now=None: ("raw", "digest text")

    def _run_main(self, resp, argv=("morning_work_digest.py",)):
        out, err = io.StringIO(), io.StringIO()
        with _bot(resp) as bot, mock.patch.object(sys, "argv", list(argv)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = self.m.main()
        return rc, out.getvalue(), err.getvalue(), bot

    def test_failed_send_does_not_claim_it_was_sent(self):
        """THE 2026-07-26 LOG LINE. ``None`` back from the bot must not print 'digest sent'."""
        rc, out, err, _ = self._run_main(None)
        self.assertNotEqual(rc, 0, "a send that did not happen must not exit 0")
        self.assertNotIn("digest sent", out)
        self.assertIn("NOT sent", err)

    def test_failed_send_names_the_reason_verbatim(self):
        rc, _out, err, _ = self._run_main({"ok": False, "description": "Too Many Requests"})
        self.assertNotEqual(rc, 0)
        self.assertIn("Too Many Requests", err)

    def test_successful_send_still_says_sent_and_exits_zero(self):
        """POSITIVE CONTROL — the happy path text is unchanged (nothing greps it, but the
        operator does), and the message really is handed to the sender."""
        rc, out, _err, bot = self._run_main({"ok": True, "result": {"message_id": 1}})
        self.assertEqual(rc, 0)
        self.assertIn("digest sent", out)
        self.assertEqual(bot.sent, ["digest text"])

    def test_dry_run_prints_and_never_touches_the_sender(self):
        """POSITIVE CONTROL — ``--dry-run`` must stay send-free (it is the safe smoke path)."""
        rc, out, _err, bot = self._run_main(
            None, argv=("morning_work_digest.py", "--dry-run"))
        self.assertEqual(rc, 0)
        self.assertIn("digest text", out)
        self.assertEqual(bot.sent, [])

    def test_sender_that_raises_is_still_reported_not_swallowed(self):
        """POSITIVE CONTROL — the pre-existing exception path keeps failing loudly."""
        import types

        fake_mod = types.ModuleType("spa_core.telegram.bot")

        class Boom:
            def __call__(self):
                return self

            def send_message(self, *_a, **_kw):
                raise RuntimeError("keychain unavailable")

        fake_mod.TelegramBot = Boom()
        saved = sys.modules.get("spa_core.telegram.bot")
        sys.modules["spa_core.telegram.bot"] = fake_mod
        try:
            err = io.StringIO()
            with mock.patch.object(sys, "argv", ["morning_work_digest.py"]):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    rc = self.m.main()
        finally:
            if saved is None:
                sys.modules.pop("spa_core.telegram.bot", None)
            else:
                sys.modules["spa_core.telegram.bot"] = saved
        self.assertNotEqual(rc, 0)
        self.assertIn("keychain unavailable", err.getvalue())


class _RepoFixture:
    """A tmp stand-in for the repo layout the gatherers read."""

    def __init__(self, mod, root: Path):
        self.mod, self.root = mod, root
        mod._REPO = root
        (root / "docs" / "journal").mkdir(parents=True, exist_ok=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
        # Default: every source READABLE and empty — so "quiet" is the honest verdict unless a
        # test deliberately breaks a source. A missing file is a finding, not a neutral start.
        (root / "data" / "session_changes.jsonl").write_text("", encoding="utf-8")

    def journal(self, name: str, text: str) -> Path:
        p = self.root / "docs" / "journal" / name
        p.write_text(text, encoding="utf-8")
        return p

    def changes(self, rows: list[dict]) -> Path:
        p = self.root / "data" / "session_changes.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return p


class QuietDayHonestyTests(unittest.TestCase):
    """Defect 2 — «тихо» is a conclusion about sources that were READ."""

    def setUp(self):
        self.m = _load_module()
        self._tmp = TemporaryDirectory()
        self.fx = _RepoFixture(self.m, Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def _digest(self, **git):
        """build_digest with git answered by a stub — no network, no real repo."""
        with mock.patch.object(self.m.subprocess, "run", side_effect=_git_run(**git)):
            return self.m.build_digest(datetime(2026, 8, 1, 9, 0))

    def test_unreadable_sources_do_not_become_a_quiet_day(self):
        """No journal dir, no changes file: nothing was read, so nothing may be claimed."""
        (self.fx.root / "docs" / "journal").rmdir()
        (self.fx.root / "data" / "session_changes.jsonl").unlink()
        raw, text = self._digest()
        self.assertEqual(raw, "")
        self.assertNotIn("Вчера было тихо", text)
        self.assertIn("Прочитано не всё", text)

    def test_the_unread_reason_is_named_verbatim(self):
        self.fx.changes([{"ts": "2026-07-31T10:00:00Z", "summary": "x"}])
        with mock.patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
            raw, text = self._digest()
        self.assertEqual(raw, "")
        self.assertIn("Permission denied", text)
        self.assertNotIn("Вчера было тихо", text)

    def test_a_genuinely_quiet_day_still_says_quiet(self):
        """POSITIVE CONTROL — all three sources read fine and hold nothing ⇒ «тихо» stays."""
        self.fx.journal("2026-W31.md", "## 2026-07-20 · старое\nне вчера\n")
        self.fx.changes([{"ts": "2026-07-01T10:00:00Z", "summary": "давно"}])
        raw, text = self._digest()
        self.assertEqual(raw, "")
        self.assertIn("Вчера было тихо", text)
        self.assertNotIn("Прочитано не всё", text)

    def test_unparsed_log_lines_are_counted_not_dropped_silently(self):
        p = self.fx.changes([{"ts": "2026-07-31T10:00:00Z", "summary": "настоящая работа"}])
        p.write_text(p.read_text(encoding="utf-8") + "{not json at all\n", encoding="utf-8")
        start, end, _day = self.m._yesterday_bounds(datetime(2026, 8, 1, 9, 0))
        text, unread = _text_and_unread(self.m._gather_session_changes(start, end))
        self.assertIn("настоящая работа", text)
        self.assertTrue(unread, "a line we could not parse must be reported")
        self.assertIn("1", unread[0])

    def test_unread_footer_survives_the_llm_summary(self):
        """The LLM must not be able to lose the warning — it is appended deterministically."""
        self.fx.journal("2026-W31.md", "## 2026-07-31 · работа\nсделано многое\n")
        _raw, text = self._digest(fetch_rc=128, fetch_err="Could not resolve host: github.com",
                                  claude="✨ красиво")
        self.assertIn("красиво", text)
        self.assertIn("Could not resolve host", text)

    def test_llm_fallback_also_carries_the_unread_footer(self):
        """Claude unavailable ⇒ raw bullets, and the warning still rides along."""
        self.fx.journal("2026-W31.md", "## 2026-07-31 · работа\nсделано многое\n")
        _raw, text = self._digest(log_rc=128, log_err="fatal: bad revision 'origin/main'")
        self.assertIn("сырьём", text)
        self.assertIn("bad revision", text)


class CommitGatheringHonestyTests(unittest.TestCase):
    """Defect 2, git half — an unread ref must not read as a day with no commits."""

    def setUp(self):
        self.m = _load_module()

    def _commits(self, **git):
        with mock.patch.object(self.m.subprocess, "run", side_effect=_git_run(**git)):
            return _text_and_unread(self.m._gather_commits("2026-07-31"))

    def test_failed_git_log_is_reported_not_read_as_no_commits(self):
        text, unread = self._commits(log_rc=128, log_err="fatal: bad revision 'origin/main'")
        self.assertEqual(text, "")
        self.assertTrue(unread, "a ref we could not read is not a day with no commits")
        self.assertIn("bad revision", unread[0])

    def test_failed_fetch_is_reported_even_when_log_succeeds(self):
        text, unread = self._commits(fetch_rc=1, fetch_err="Could not resolve host: github.com",
                                     log_out="старый коммит\n")
        self.assertIn("старый коммит", text)
        self.assertTrue(unread, "a stale ref makes the commit list possibly incomplete")
        self.assertIn("Could not resolve host", unread[0])

    def test_clean_git_run_reports_nothing_unread(self):
        """POSITIVE CONTROL — the normal path must not grow a daily warning."""
        text, unread = self._commits(log_out="цикл #77: fix\n")
        self.assertEqual(text, "- цикл #77: fix")
        self.assertEqual(unread, [])


class YesterdayWindowIsOneIntervalTests(unittest.TestCase):
    """Defect 3 — UTC stamps vs a naive LOCAL window slid 'yesterday' by the UTC offset."""

    def setUp(self):
        self.m = _load_module()
        self._tmp = TemporaryDirectory()
        self.fx = _RepoFixture(self.m, Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    @staticmethod
    def _cest(dt: datetime) -> datetime:
        """The same instant, expressed in a fixed UTC+2 zone (CEST, the host's summer zone)."""
        return dt.astimezone(timezone(timedelta(hours=2)))

    def test_work_just_after_local_midnight_belongs_to_that_local_day(self):
        """2026-07-31T01:30 CEST == 2026-07-30T23:30Z — yesterday's work, previously dropped."""
        self.fx.changes([{"ts": "2026-07-30T23:30:00Z", "summary": "работа сразу после полуночи"}])
        start = self._cest(datetime(2026, 7, 31, 0, 0, tzinfo=timezone(timedelta(hours=2))))
        end = start + timedelta(days=1)
        text, unread = _text_and_unread(self.m._gather_session_changes(start, end))
        self.assertIn("работа сразу после полуночи", text)
        self.assertEqual(unread, [])

    def test_work_after_todays_local_midnight_is_not_filed_as_yesterday(self):
        """2026-08-01T01:30 CEST == 2026-07-31T23:30Z — today's work, previously counted."""
        self.fx.changes([{"ts": "2026-07-31T23:30:00Z", "summary": "уже сегодняшняя работа"}])
        start = self._cest(datetime(2026, 7, 31, 0, 0, tzinfo=timezone(timedelta(hours=2))))
        end = start + timedelta(days=1)
        text, _unread = _text_and_unread(self.m._gather_session_changes(start, end))
        self.assertNotIn("уже сегодняшняя работа", text)

    def test_utc_window_converts_a_naive_local_bound(self):
        start, end, _day = self.m._yesterday_bounds(datetime(2026, 8, 1, 9, 0))
        s_utc, e_utc = self.m._utc_window(start, end)
        self.assertIsNotNone(s_utc.tzinfo)
        self.assertIsNotNone(e_utc.tzinfo)
        self.assertEqual(s_utc, start.astimezone(timezone.utc))
        self.assertEqual(e_utc - s_utc, timedelta(days=1))

    def test_naive_stamps_are_read_as_utc_like_the_writer_emits_them(self):
        """``log_session_change.py`` stamps UTC; a stamp without 'Z' came from the same writer."""
        t = self.m._parse_log_ts("2026-07-31T10:00:00")
        self.assertIsNotNone(t)
        self.assertEqual(t.utcoffset(), timedelta(0))

    def test_unparseable_stamp_is_none_not_an_exception(self):
        self.assertIsNone(self.m._parse_log_ts("not-a-date"))
        self.assertIsNone(self.m._parse_log_ts(""))


class ExistingBehaviourStillHoldsTests(unittest.TestCase):
    """POSITIVE CONTROLS for behaviour that predates цикл #77 and must not have drifted."""

    def setUp(self):
        self.m = _load_module()
        self._tmp = TemporaryDirectory()
        self.fx = _RepoFixture(self.m, Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def _digest(self, **git):
        with mock.patch.object(self.m.subprocess, "run", side_effect=_git_run(**git)):
            return self.m.build_digest(datetime(2026, 8, 1, 9, 0))

    def test_yesterday_bounds_is_the_previous_local_midnight_to_midnight(self):
        start, end, day = self.m._yesterday_bounds(datetime(2026, 8, 1, 9, 13, 44))
        self.assertEqual(start, datetime(2026, 7, 31, 0, 0))
        self.assertEqual(end, datetime(2026, 8, 1, 0, 0))
        self.assertEqual(day, "2026-07-31")

    def test_journal_keeps_the_block_under_a_matching_heading(self):
        self.fx.journal(
            "2026-W31.md",
            "## 2026-07-30 · позавчера\nстарое\n"
            "## Цикл #77 (2026-07-31, автономный) — заголовок\nтело записи\n"
            "## 2026-08-01 · сегодня\nновое\n",
        )
        text, unread = _text_and_unread(self.m._gather_journal("2026-07-31"))
        self.assertIn("тело записи", text)
        self.assertNotIn("старое", text)
        self.assertNotIn("новое", text)
        self.assertEqual(unread, [])

    def test_digest_headline_carries_the_local_date(self):
        raw, text = self._digest()
        self.assertEqual(raw, "")
        self.assertIn("Что сделано вчера (2026-07-31)", text)

    def test_llm_summary_is_used_when_claude_answers(self):
        """POSITIVE CONTROL — a fully-read day still ships the LLM prose and nothing else."""
        self.fx.journal("2026-W31.md", "## 2026-07-31 · работа\nсделано\n")
        raw, text = self._digest(claude="☀️ человеческий текст")
        self.assertIn("сделано", raw)
        self.assertEqual(text, "☀️ человеческий текст")

    def test_module_is_stdlib_only_and_llm_free_outside_the_reporting_call(self):
        """The LLM is allowed HERE (reporting), but only via the one documented subprocess.

        Invariants #3 (no LLM in risk/execution/monitoring) and #4 (stdlib only) meet in this
        file: it may shell out to ``claude`` for prose, and may not grow an SDK dependency or
        a second call site that a future reader would not expect.
        """
        src = _TARGET.read_text(encoding="utf-8")
        self.assertEqual(src.count("[_CLAUDE, \"-p\""), 1,
                         "claude is invoked from exactly one place")
        for banned in ("import requests", "import anthropic", "import openai",
                       "from anthropic", "from openai"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
