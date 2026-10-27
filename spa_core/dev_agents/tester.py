"""
SPA Tester Agent

Runs the full test suite and reports results via Telegram + data/test_results.json.

Usage:
    python -m spa_core.dev_agents.tester
    python -m spa_core.dev_agents.tester --module tests/test_paper_trading.py
    python -m spa_core.dev_agents.tester --no-telegram
"""

import subprocess
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


# ── The one door to pytest's own numbers ──────────────────────────────────────
#
# Counting occurrences of " PASSED" / " FAILED" in the raw log answers the
# question "how many times does this word appear", not "how many tests ended
# this way" — and on real output the two differ (measured 2026-10-27, ADR-828,
# live pytest 9.0.3):
#   · a test whose SUBTESTS failed prints "PASSED" on its own verbose line, so
#     occurrence-counting put it in `passed` and left `failed` at 0;
#   · a single errored test prints " ERROR" three times (verbose line, section
#     banner, short-summary line), so `errors` read 3 for one error.
# pytest already publishes the authoritative tally in its summary bar, and that
# bar does count subtest failures. It is the only door used for counts here.
#
#   "===== 2 failed, 2 passed, 2 skipped, 1 subtests passed in 0.01s ====="
#   "========================== 5 passed in 0.42s ========================"
#   "========================== 1 error in 0.01s ========================="
#   "========================= no tests ran in 0.00s ====================="
#
# The trailing "(H:MM:SS)" is NOT decoration and NOT optional in practice:
# pytest appends it to every run longer than a minute
# (`_pytest.terminal.format_session_duration`), so a bar from a real run reads
#   "====== 1 failed, 1 passed, 1 skipped in 61.12s (0:01:01) ======"
# Measured 2026-10-27 (cycle #954, live pytest 9.0.3, a scene that really
# sleeps 61 s): without this group the bar was not found at all and this very
# reader answered "счёт НЕ ИЗМЕРЕН: pytest printed no summary bar" while pytest
# had printed it. A false third outcome is as wrong as a false zero — and it
# fired on EVERY run over a minute, i.e. on every run that matters here.
_SUMMARY_BAR_RE = re.compile(
    r"^=+\s*(?P<body>.*?)\s+in\s+(?P<dur>[0-9]+(?:\.[0-9]+)?)s"
    r"(?:\s+\([^)]*\))?\s*=+\s*$"
)

# "1 subtests passed" must win over the bare "[a-z]+" alternative — otherwise
# the token reads "subtests" and the count is dropped without a word.
_BAR_COUNT_RE = re.compile(r"(\d+)\s+(subtests\s+[a-z]+|[a-z]+)")

_BAR_TOKENS = (
    "passed", "failed", "errors", "skipped",
    "xfailed", "xpassed", "warnings", "deselected",
)

# Short-summary name lines. A failed subtest is printed as
#   "SUBFAILED(i=2) path::test - msg"
# so the kind carries optional parameters. The name must look like a test id
# (contains ".py"): without that guard "ERROR at setup of test_x" would be
# read as a test named "at". Collection errors naming a bare directory are
# therefore NOT captured here — that boundary is named, not silently covered.
_NAME_LINE_RE = re.compile(
    r"^(?P<kind>FAILED|ERROR|SUBFAILED)(?:\([^)]*\))?"
    r"\s+(?P<name>\S*\.py(?:::\S+)?)(?:\s+-\s+(?P<msg>.+))?\s*$"
)


class SpaTester:
    """
    Deterministic test runner agent.

    Invokes pytest, parses output, saves structured results, and
    optionally sends a Telegram summary via TelegramSender.
    """

    def __init__(self):
        self.results_file = "data/test_results.json"

    # ── Test execution ─────────────────────────────────────────────────────────

    def run_tests(self, module: str = None) -> dict:
        """Run pytest and parse results. Returns summary dict."""
        cmd = ["python", "-m", "pytest"]
        if module:
            cmd.append(module)
        else:
            cmd.append("tests/")
        cmd.extend(["-v", "--tb=short", "--no-header"])

        t0 = datetime.now(timezone.utc)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            output = result.stdout + result.stderr
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            output = "TIMEOUT: tests exceeded 120 seconds"
            returncode = 1

        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        summary = self._parse_output(output, returncode, duration)
        self._save_results(summary, output)
        return summary

    # ── Output parsing ─────────────────────────────────────────────────────────

    def _parse_output(self, output: str, returncode: int, duration: float) -> dict:
        """
        Parse pytest output into a structured summary dict.

        Two different questions, two different doors:

        * ``status`` — pytest's **exit code**. It is the only signal that is
          authoritative no matter how the log is formatted.
        * the counts — pytest's **summary bar**. If no bar was printed (timeout,
          crash, truncated log) the counts are ``None`` and ``counts_measured``
          is False, so "measured zero" never looks like "never measured"
          (invariant #17).
        """
        bar_body: str | None = None
        bar_line: str | None = None
        pytest_duration_s: float | None = None
        for raw in output.splitlines():
            m = _SUMMARY_BAR_RE.match(raw.rstrip())
            if m:
                # pytest prints one bar per run; if several look like it, the
                # last one wins (that is pytest's own behaviour).
                bar_body = m.group("body").strip().strip("=").strip()
                bar_line = raw.strip()
                try:
                    pytest_duration_s = float(m.group("dur"))
                except ValueError:
                    pytest_duration_s = None

        # Names of what broke. Deduplicated: a test with two failed subtests
        # prints two SUBFAILED lines for one test id.
        failed_tests: list[str] = []
        seen: set[str] = set()
        for raw in output.splitlines():
            mn = _NAME_LINE_RE.match(raw.rstrip())
            if mn:
                name = mn.group("name")
                if name not in seen:
                    seen.add(name)
                    failed_tests.append(name)

        base = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if returncode == 0 else "FAIL",
            "returncode": returncode,
            "duration_seconds": round(duration, 1),
            "failed_tests": failed_tests,
        }

        if bar_body is None:
            # Third outcome: nothing was measured. Reporting zeros here is what
            # made a timeout read like a clean run.
            return {
                **base,
                "counts_measured": False,
                "unmeasured_reason": (
                    "pytest printed no summary bar — counts not measured "
                    "(timeout, crash or truncated output)"
                ),
                "passed": None,
                "failed": None,
                "errors": None,
                "skipped": None,
                "subtests_passed": None,
                "total": None,
                "pytest_duration_s": None,
                "summary": None,
            }

        counts = {tok: 0 for tok in _BAR_TOKENS}
        subtests_passed = 0
        for count_str, token in _BAR_COUNT_RE.findall(bar_body):
            try:
                n = int(count_str)
            except ValueError:
                continue
            tok = token.strip()
            if tok.startswith("subtests"):
                # A failed subtest is already inside the bar's "failed" tally;
                # "subtests passed" is extra information, not a second count.
                if tok.endswith("passed"):
                    subtests_passed = n
                elif tok.endswith("failed"):
                    counts["failed"] += n
            elif tok == "error":
                counts["errors"] += n
            elif tok in counts:
                counts[tok] = n

        return {
            **base,
            "counts_measured": True,
            "unmeasured_reason": None,
            "passed": counts["passed"],
            "failed": counts["failed"],
            "errors": counts["errors"],
            "skipped": counts["skipped"],
            "subtests_passed": subtests_passed,
            "total": (
                counts["passed"] + counts["failed"]
                + counts["errors"] + counts["skipped"]
            ),
            "pytest_duration_s": pytest_duration_s,
            "summary": bar_line,
        }

    # ── Persistence ────────────────────────────────────────────────────────────

    def _save_results(self, summary: dict, raw_output: str):
        Path("data").mkdir(exist_ok=True)
        # Structured JSON summary
        Path(self.results_file).write_text(json.dumps(summary, indent=2))
        # Last 200 lines of pytest output for debugging
        lines = raw_output.strip().split("\n")
        Path("data/test_output.txt").write_text("\n".join(lines[-200:]))

    # ── Telegram formatting ────────────────────────────────────────────────────

    def format_telegram(self, summary: dict) -> str:
        """
        Format test results as an HTML Telegram message.

        A red verdict must always carry a reason. Before ADR-828 this message
        could read "❌ 2 passed" with no failed count and no names, because the
        counts were occurrence-counted and the summary field held the
        "test session starts" banner instead of the result.
        """
        status_emoji = "✅" if summary["status"] == "PASS" else "❌"
        msg = f"{status_emoji} <b>SPA Test Suite</b>\n\n"

        if summary.get("counts_measured", True):
            msg += f"📊 {summary['passed']} passed"
            if summary["failed"]:
                msg += f" · {summary['failed']} failed"
            if summary["errors"]:
                msg += f" · {summary['errors']} errors"
            if summary.get("skipped"):
                msg += f" · {summary['skipped']} skipped"
            if summary.get("subtests_passed"):
                msg += f" · {summary['subtests_passed']} subtests passed"
        else:
            # Third outcome: say so instead of printing zeros.
            msg += "📊 счёт НЕ ИЗМЕРЕН: " + str(
                summary.get("unmeasured_reason") or "причина не названа"
            )
        msg += f"\n⏱ {summary['duration_seconds']}s\n"

        if summary["failed_tests"]:
            msg += "\n<b>Failed:</b>\n"
            for t in summary["failed_tests"][:5]:
                msg += f"• {t}\n"
            extra = len(summary["failed_tests"]) - 5
            if extra > 0:
                msg += f"• … и ещё {extra}\n"
        elif summary["status"] != "PASS":
            # Red with no names is exactly the report that cost us ADR-828.
            msg += "\n<b>Failed:</b>\n• имён нет в выводе pytest\n"

        if summary.get("summary"):
            msg += f"\n<code>{summary['summary']}</code>"
        return msg

    def send_telegram_report(self, summary: dict):
        """Send test results to Telegram using TelegramSender (if configured)."""
        token = os.environ.get("SPA_TELEGRAM_TOKEN")
        chat_id = os.environ.get("SPA_TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            print("[Tester] No Telegram credentials — skipping notification")
            return

        try:
            from spa_core.alerts.telegram_sender import TelegramSender

            sender = TelegramSender()
            sent = sender.send(self.format_telegram(summary))
            if sent:
                print("[Tester] Telegram notification sent")
            else:
                print("[Tester] Telegram send returned False (check credentials/network)")
        except Exception as e:
            print(f"[Tester] Telegram send failed: {e}")


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    import argparse

    p = argparse.ArgumentParser(description="SPA Tester Agent")
    p.add_argument(
        "--module", type=str, default=None, help="Specific test module to run"
    )
    p.add_argument(
        "--no-telegram", action="store_true", help="Skip Telegram notification"
    )
    args = p.parse_args()

    tester = SpaTester()
    summary = tester.run_tests(args.module)

    print(f"\n{'='*50}")
    print(f"Status:   {summary['status']}")
    if summary.get("counts_measured", True):
        print(
            f"Tests:    {summary['passed']} passed, "
            f"{summary['failed']} failed, "
            f"{summary['errors']} errors, "
            f"{summary['skipped']} skipped"
        )
    else:
        print(f"Tests:    НЕ ИЗМЕРЕНО — {summary['unmeasured_reason']}")
    print(f"Duration: {summary['duration_seconds']}s")
    if summary["failed_tests"]:
        print(f"Failed:   {', '.join(summary['failed_tests'])}")
    print(f"{'='*50}\n")

    if not args.no_telegram:
        tester.send_telegram_report(summary)


if __name__ == "__main__":
    main()
