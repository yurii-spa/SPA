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
        """Parse pytest output into structured summary dict."""
        passed = len(re.findall(r" PASSED", output))
        failed = len(re.findall(r" FAILED", output))
        errors = len(re.findall(r" ERROR", output))
        skipped = len(re.findall(r" SKIPPED", output))

        # Extract failed test names (e.g. "FAILED tests/test_foo.py::test_bar")
        failed_tests = re.findall(r"FAILED (tests/\S+)", output)

        # Last pytest summary line: "=== X passed, Y failed in Zs ==="
        summary_match = re.search(
            r"=+\s*([\d\s\w,]+)\s*=+\s*$", output, re.MULTILINE
        )
        summary_line = (
            summary_match.group(1).strip() if summary_match else f"{passed} passed"
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if returncode == 0 else "FAIL",
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "total": passed + failed + errors + skipped,
            "duration_seconds": round(duration, 1),
            "failed_tests": failed_tests,
            "summary": summary_line,
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
        """Format test results as an HTML Telegram message."""
        status_emoji = "✅" if summary["status"] == "PASS" else "❌"
        msg = f"{status_emoji} <b>SPA Test Suite</b>\n\n"
        msg += f"📊 {summary['passed']} passed"
        if summary["failed"]:
            msg += f" · {summary['failed']} failed"
        if summary["errors"]:
            msg += f" · {summary['errors']} errors"
        msg += f"\n⏵ {summary['duration_seconds']}s\n"

        if summary["failed_tests"]:
            msg += "\n<b>Failed:</b>\n"
            for t in summary["failed_tests"][:5]:
                msg += f"• {t}\n"

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
    print(
        f"Tests:    {summary['passed']} passed, "
        f"{summary['failed']} failed, "
        f"{summary['errors']} errors"
    )
    print(f"Duration: {summary['duration_seconds']}s")
    if summary["failed_tests"]:
        print(f"Failed:   {', '.join(summary['failed_tests'])}")
    print(f"{'='*50}\n")

    if not args.no_telegram:
        tester.send_telegram_report(summary)


if __name__ == "__main__":
    main()
