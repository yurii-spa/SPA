"""
SPA Tester Agent (v2.5 — BL-003)

Модель: Phase-1 — pure Python, детерминированная (без LLM-генерации тестов).

Роль:   Запускает существующий pytest suite по `spa_core/tests/` и `tests/`,
        парсит вывод pytest, выделяет failed/errored тесты и публикует
        краткий summary на шину сообщений (topic="tester.report").

Логика:
  1. discover_tests()   — `pytest --collect-only -q`, возвращает список tests
  2. run_tests()        — `pytest <dirs>`, парсит exit_code + summary
  3. parse_pytest_output() — pure парсер (тестируется без subprocess)
  4. dump_report()      — пишет data/tester_report.json
  5. run()              — публикует {report} в шину (topic="tester.report")
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from message_bus.bus import MessageBus
from message_bus.topics import Priority


# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT_S = 600
_STDOUT_TAIL_LINES = 50

_DEFAULT_TESTS_DIRS = ("spa_core/tests", "tests")

# The keys of `totals`. They are the SAME on every path through this module —
# measured, measured-and-zero, or never measured (invariant #17). pytest prints
# "1 error" (singular) for one error and "2 errors" for several; the singular is
# folded into "errors" while parsing, so the shape of the dict never depends on
# which branch produced it.
#
# Until 2026-10-27 the fold happened AFTER an early return, so the empty-stdout
# path alone leaked an extra `"error": 0` key — a consumer iterating the keys
# saw a different dict on that one path and nothing said a word (ADR-829).
_TOTAL_KEYS = (
    "passed", "failed", "errors",
    "skipped", "xfailed", "xpassed", "warnings", "deselected",
)

# Tokens accepted inside the bar, mapped onto `_TOTAL_KEYS`.
_BAR_TOKEN_TO_KEY = {tok: tok for tok in _TOTAL_KEYS} | {"error": "errors"}

# Why a tally can be absent, per door. The reason is part of the answer: "not
# measured" without a named cause is the same silence as a zero.
_NO_BAR_REASON = (
    "pytest printed no summary bar — the outcome tally was NOT measured "
    "(timeout, crash or truncated output)"
)
_NO_RUN_REASON = (
    "pytest was never run — no test directory was found, so the outcome "
    "tally was NOT measured"
)
_RUN_FAILED_REASON = (
    "the pytest subprocess did not finish — the outcome tally was NOT measured"
)


def _unmeasured_totals(collected: int | None = None) -> dict:
    """
    Totals for a run whose outcomes were never observed.

    `None`, not 0. Zeros here are what made a timeout read as a clean run:
    "measured and equal to zero" and "not measured" became the same value, and
    the agent then logged "0 passed / 0 failed / 0 errors" for a run that may
    have been entirely red (measured 2026-10-27 on a 61 s run that really
    reported 1 failed — ADR-828 §подъём, ADR-829).

    `collected` is kept separate on purpose: it comes from a DIFFERENT line of
    pytest's output ("collected N items"), so it can be measured when the bar
    is not. Folding it into the same verdict would hide one measurement behind
    another's absence.
    """
    return {key: None for key in _TOTAL_KEYS} | {"collected": collected}

# Sample summary lines we need to parse:
#   "200 passed in 8.91s"
#   "1 failed, 199 passed, 3 warnings in 12.34s"
#   "1 error, 199 passed in 5.00s"
#   "5 passed, 2 skipped in 0.50s"
#   "1 failed, 1 passed, 1 skipped in 61.12s (0:01:01)"   ← run longer than 1 min
#
# The last form is the one that cost us: pytest appends a human-readable
# duration in brackets for every run over a minute
# (`_pytest.terminal.format_session_duration`). Without the optional group this
# regex found NO summary line on such a run, and then every total stayed 0 —
# measured 2026-10-27 (cycle #954, live pytest 9.0.3, real 61.12s run):
# "1 failed" was reported as 0 failed, `summary_line` as None, while
# `collected` said 3. ADR-828 called these counts correct; that claim was
# measured on a 0.01s scene only, and this is the half it could not see.
_SUMMARY_LINE_RE = re.compile(
    r"^=+\s*(?P<body>.*?)\s+in\s+(?P<duration>[0-9]+(?:\.[0-9]+)?)\s*s"
    r"(?:\s+\([^)]*\))?\s*=+\s*$"
)
_SUMMARY_PART_RE = re.compile(r"(\d+)\s+([a-zA-Z]+)")

# "FAILED tests/foo.py::test_bar - AssertionError: …"
# "ERROR tests/foo.py::test_bar"
# "SUBFAILED(i=2) tests/foo.py::test_bar - AssertionError: …"
#
# The SUBFAILED form carries the subtest parameters inside the kind token, so
# a plain "^(FAILED|ERROR)" never matched it: the counts here were right (the
# summary bar does tally subtest failures) but the NAME list came back empty,
# i.e. the report said "2 failed" and could not say which test (measured
# 2026-10-27 on live pytest 9.0.3, ADR-828).
_FAILURE_LINE_RE = re.compile(
    r"^(?P<kind>FAILED|ERROR|SUBFAILED)(?:\((?P<params>[^)]*)\))?"
    r"\s+(?P<name>\S+)(?:\s+-\s+(?P<msg>.+))?\s*$"
)

# Collect-only output: "tests/foo.py::test_bar" or "tests/foo.py::TestX::test_y"
_COLLECT_LINE_RE = re.compile(r"^\S+\.py::\S+$")


def _normalise_summary_body(body: str) -> str:
    """
    Strip leading/trailing markers like '== ' or trailing '=='.
    Pytest sometimes embeds the body inside '=' bars, sometimes not.
    """
    return body.strip().strip("=").strip()


class TesterAgent(BaseAgent):
    """
    Tester Agent — runs the pytest suite and reports failures.

    Phase 1 (v2.5): pure-Python wrapper over `pytest` subprocess.
                    No LLM test-generation yet.
    """

    AGENT_ID = "tester_agent"
    # Prevent pytest from trying to collect this class as a test suite
    # (name starts with "Tester" which pytest treats as a Test* match).
    __test__ = False

    def __init__(
        self,
        bus: MessageBus,
        db_path: Path | None = None,
        tests_dirs: list[str] | tuple[str, ...] | None = None,
        repo_root: Path | None = None,
    ):
        super().__init__(bus, db_path)
        # repo_root = …/SPA_Claude  (this file: …/SPA_Claude/spa_core/agents/tester_agent.py)
        self._repo_root: Path = (
            Path(repo_root) if repo_root
            else Path(__file__).resolve().parent.parent.parent
        )
        self.tests_dirs: list[str] = list(
            tests_dirs if tests_dirs is not None else _DEFAULT_TESTS_DIRS
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _resolve_dirs(self, tests_dirs: list[str] | tuple[str, ...] | None) -> list[str]:
        dirs = list(tests_dirs) if tests_dirs is not None else list(self.tests_dirs)
        # Keep dirs as relative paths (as caller-provided) for stable CLI args,
        # but only include those that actually exist under repo_root.
        return [d for d in dirs if (self._repo_root / d).exists()]

    # ── Parsing (pure, no subprocess) ────────────────────────────────────────

    def parse_pytest_output(self, stdout: str) -> dict:
        """
        Pure deterministic parser of pytest stdout.

        Two doors, two independent questions, two independent third outcomes:

        * the **summary bar** answers "how did the tests end". No bar ⇒ the
          counts are ``None`` and ``counts_measured`` is False, with the reason
          named — never zeros (invariant #17).
        * the **collection line** answers "how many tests pytest found". It is
          measured, or not, on its own: ``collected_measured``.

        Returns a dict with keys:
          totals:            {passed, failed, errors, skipped, xfailed,
                              xpassed, warnings, deselected, collected}
                             — every value is ``int`` or ``None``
          counts_measured:   bool        — did pytest print a summary bar
          unmeasured_reason: str | None  — why not, when it did not
          collected_measured: bool       — was "collected N items" seen
          failures:          [{kind, name, msg, params}]
          duration_s:        float | None
          summary_line:      str | None  — the raw summary bar found
        """
        bar_body: str | None = None
        summary_line: str | None = None
        duration_s: float | None = None
        collected: int | None = None
        failures: list[dict] = []

        for raw_line in (stdout or "").splitlines():
            line = raw_line.rstrip()

            # FAILED / ERROR / SUBFAILED per-test lines (before the bar).
            m = _FAILURE_LINE_RE.match(line)
            if m:
                failures.append({
                    "kind": m.group("kind"),
                    "name": m.group("name"),
                    "msg": (m.group("msg") or "").strip() or None,
                    # None for FAILED/ERROR; "i=2" for a failed subtest, so two
                    # failed subtests of one test stay two distinguishable rows.
                    "params": m.group("params"),
                })
                continue

            # Final summary bar: "===== 1 failed, 199 passed in 12.34s ====="
            ms = _SUMMARY_LINE_RE.match(line)
            if ms:
                summary_line = line.strip()
                bar_body = _normalise_summary_body(ms.group("body"))
                try:
                    duration_s = float(ms.group("duration"))
                except ValueError:
                    duration_s = None
                # Keep scanning: if several lines look like a bar, the LAST one
                # wins (that is pytest's own behaviour).
                continue

            # Collection line: "collected 200 items"
            if "collected" in line:
                mcol = re.search(r"collected\s+(\d+)\s+item", line)
                if mcol:
                    try:
                        collected = int(mcol.group(1))
                    except ValueError:
                        pass

        if bar_body is None:
            return {
                "totals": _unmeasured_totals(collected),
                "counts_measured": False,
                "unmeasured_reason": _NO_BAR_REASON,
                "collected_measured": collected is not None,
                "failures": failures,
                "duration_s": None,
                "summary_line": None,
            }

        totals: dict[str, int | None] = {key: 0 for key in _TOTAL_KEYS}
        for count_str, token in _SUMMARY_PART_RE.findall(bar_body):
            key = _BAR_TOKEN_TO_KEY.get(token.lower())
            if key is None:
                continue
            try:
                totals[key] += int(count_str)
            except ValueError:
                pass
        totals["collected"] = collected

        return {
            "totals": totals,
            "counts_measured": True,
            "unmeasured_reason": None,
            "collected_measured": collected is not None,
            "failures": failures,
            "duration_s": duration_s,
            "summary_line": summary_line,
        }

    # ── Discover ─────────────────────────────────────────────────────────────

    def discover_tests(
        self, tests_dirs: list[str] | tuple[str, ...] | None = None
    ) -> list[dict]:
        """
        Runs `pytest --collect-only -q` and returns a list of discovered tests.

        Each entry: {"nodeid": "tests/foo.py::test_bar", "file": "tests/foo.py"}
        Returns [] on subprocess error.
        """
        dirs = self._resolve_dirs(tests_dirs)
        if not dirs:
            self.log.warning("No test directories found under %s", self._repo_root)
            return []

        cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *dirs]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self.log.error("pytest --collect-only failed: %s", exc)
            return []

        out: list[dict] = []
        for raw in (completed.stdout or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if _COLLECT_LINE_RE.match(line):
                file_part = line.split("::", 1)[0]
                out.append({"nodeid": line, "file": file_part})
        self.log.info("Discovered %d test(s) across %s", len(out), dirs)
        return out

    # ── Run ──────────────────────────────────────────────────────────────────

    def run_tests(
        self,
        tests_dirs: list[str] | tuple[str, ...] | None = None,
        extra_args: list[str] | None = None,
    ) -> dict:
        """
        Runs pytest on the given dirs. Returns a dict:
          {
            "exit_code":   int,
            "totals":      {...},
            "failures":    [...],
            "duration_s":  float | None,
            "stdout_tail": str,
            "dirs":        list[str],
            "cmd":         list[str],
          }
        """
        dirs = self._resolve_dirs(tests_dirs)
        cmd = [sys.executable, "-m", "pytest", "-v", *dirs]
        if extra_args:
            cmd.extend(extra_args)

        if not dirs:
            # pytest was not run at all. Zeros here claimed a clean suite for a
            # run that never happened — the same class as the missing bar
            # below, at a door that never reaches the parser (ADR-829).
            self.log.warning("No test directories found; skipping pytest run.")
            return {
                "exit_code": -1,
                "totals": _unmeasured_totals(),
                "counts_measured": False,
                "unmeasured_reason": _NO_RUN_REASON,
                "collected_measured": False,
                "failures": [],
                "duration_s": None,
                "stdout_tail": "",
                "dirs": [],
                "cmd": cmd,
            }

        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT_S,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            exit_code = completed.returncode
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            self.log.error("pytest run failed: %s", exc)
            return {
                "exit_code": -2,
                "totals": _unmeasured_totals(),
                "counts_measured": False,
                "unmeasured_reason": f"{_RUN_FAILED_REASON}: {exc}",
                "collected_measured": False,
                "failures": [{"kind": "ERROR", "name": "<subprocess>", "msg": str(exc)}],
                "duration_s": None,
                "stdout_tail": "",
                "dirs": dirs,
                "cmd": cmd,
            }

        parsed = self.parse_pytest_output(stdout)
        # If pytest exited non-zero but produced no FAILED lines and no summary,
        # surface stderr tail for visibility.
        combined = stdout if stdout else stderr
        tail_lines = combined.splitlines()[-_STDOUT_TAIL_LINES:]
        stdout_tail = "\n".join(tail_lines)

        return {
            "exit_code": exit_code,
            "totals": parsed["totals"],
            "counts_measured": parsed["counts_measured"],
            "unmeasured_reason": parsed["unmeasured_reason"],
            "collected_measured": parsed["collected_measured"],
            "failures": parsed["failures"],
            "duration_s": parsed["duration_s"],
            "stdout_tail": stdout_tail,
            "dirs": dirs,
            "cmd": cmd,
        }

    # ── Dump ─────────────────────────────────────────────────────────────────

    def dump_report(self, out_path: Path | None = None) -> Path:
        """
        Сохраняет результат прогона в JSON (для дашборда).
        По умолчанию — <repo_root>/data/tester_report.json.
        """
        out_path = (
            Path(out_path) if out_path
            else self._repo_root / "data" / "tester_report.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = self.run_tests()
        payload = {
            "generated_at": self._ts(),
            "agent": self.AGENT_ID,
            "report": report,
        }
        out_path.write_text(json.dumps(payload, indent=2))
        self.log.info("Tester report dumped to %s", out_path)
        return out_path

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self) -> list[str]:
        """Опубликовать report в шину под topic 'tester.report'."""
        self._run_count += 1
        self.log.info("Run #%d — tester cycle", self._run_count)

        report = self.run_tests()

        payload = {"report": report}
        msg_id = self.publish("tester.report", payload, priority=Priority.NORMAL)
        totals = report.get("totals", {})
        if report.get("counts_measured"):
            self.log.info(
                "Tester published report: %s passed / %s failed / %s errors "
                "(exit_code=%s, duration=%ss)",
                totals.get("passed"),
                totals.get("failed"),
                totals.get("errors"),
                report.get("exit_code"),
                report.get("duration_s"),
            )
        else:
            # Never "0 passed / 0 failed": that sentence is what a reader
            # mistook for a clean suite (ADR-829, invariant #17).
            self.log.warning(
                "Tester published report: counts NOT MEASURED — %s "
                "(exit_code=%s, collected=%s)",
                report.get("unmeasured_reason"),
                report.get("exit_code"),
                totals.get("collected"),
            )
        return [msg_id]
