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

# Tokens we count in the pytest summary line.
# Order matters only for stable iteration in tests.
_SUMMARY_TOKENS = (
    "passed", "failed", "error", "errors",
    "skipped", "xfailed", "xpassed", "warnings", "deselected",
)

# Sample summary lines we need to parse:
#   "200 passed in 8.91s"
#   "1 failed, 199 passed, 3 warnings in 12.34s"
#   "1 error, 199 passed in 5.00s"
#   "5 passed, 2 skipped in 0.50s"
_SUMMARY_LINE_RE = re.compile(
    r"^=+\s*(?P<body>.*?)\s+in\s+(?P<duration>[0-9]+(?:\.[0-9]+)?)\s*s\s*=+\s*$"
)
_SUMMARY_PART_RE = re.compile(r"(\d+)\s+([a-zA-Z]+)")

# "FAILED tests/foo.py::test_bar - AssertionError: …"
# "ERROR tests/foo.py::test_bar"
_FAILURE_LINE_RE = re.compile(
    r"^(?P<kind>FAILED|ERROR)\s+(?P<name>\S+)(?:\s+-\s+(?P<msg>.+))?\s*$"
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

        Returns a dict with keys:
          totals:    {passed, failed, errors, skipped, xfailed, xpassed,
                      warnings, deselected, collected}
          failures:  [{kind, name, msg}]  — FAILED/ERROR lines extracted
          duration_s: float | None
          summary_line: str | None        — the raw summary line found
        """
        totals: dict[str, int] = {tok: 0 for tok in _SUMMARY_TOKENS}
        totals["collected"] = 0
        duration_s: float | None = None
        summary_line: str | None = None
        failures: list[dict] = []

        if not stdout:
            return {
                "totals": totals,
                "failures": failures,
                "duration_s": duration_s,
                "summary_line": summary_line,
            }

        for raw_line in stdout.splitlines():
            line = raw_line.rstrip()

            # FAILED / ERROR per-test lines (printed before the summary bar).
            m = _FAILURE_LINE_RE.match(line)
            if m:
                failures.append({
                    "kind": m.group("kind"),
                    "name": m.group("name"),
                    "msg": (m.group("msg") or "").strip() or None,
                })
                continue

            # Final summary line: "===== 1 failed, 199 passed in 12.34s ====="
            ms = _SUMMARY_LINE_RE.match(line)
            if ms:
                summary_line = line.strip()
                try:
                    duration_s = float(ms.group("duration"))
                except ValueError:
                    duration_s = None
                body = _normalise_summary_body(ms.group("body"))
                for count_str, token in _SUMMARY_PART_RE.findall(body):
                    tok = token.lower()
                    if tok in totals:
                        try:
                            totals[tok] = int(count_str)
                        except ValueError:
                            pass
                # We keep scanning in case there are multiple summary-looking
                # lines; the LAST one wins (matches pytest's behaviour).
                continue

            # Collection line: "collected 200 items"
            if "collected" in line:
                mcol = re.search(r"collected\s+(\d+)\s+item", line)
                if mcol:
                    try:
                        totals["collected"] = int(mcol.group(1))
                    except ValueError:
                        pass

        # Normalise: "error" and "errors" → unified "errors" count.
        # We don't want both keys leaking — fold "error" into "errors".
        if totals.get("error"):
            totals["errors"] = totals.get("errors", 0) + totals["error"]
            totals.pop("error", None)
        else:
            totals.pop("error", None)

        return {
            "totals": totals,
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
            self.log.warning("No test directories found; skipping pytest run.")
            return {
                "exit_code": -1,
                "totals": {tok: 0 for tok in _SUMMARY_TOKENS} | {"collected": 0},
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
                "totals": {tok: 0 for tok in _SUMMARY_TOKENS} | {"collected": 0},
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
        self.log.info(
            "Tester published report: %d passed / %d failed / %d errors "
            "(exit_code=%s, duration=%ss)",
            totals.get("passed", 0),
            totals.get("failed", 0),
            totals.get("errors", 0),
            report.get("exit_code"),
            report.get("duration_s"),
        )
        return [msg_id]
