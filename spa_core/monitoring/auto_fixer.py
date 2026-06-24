"""
spa_core/monitoring/auto_fixer.py
====================================
SPA Autonomous Bug Fixer — receives alert text, finds the affected file,
calls Claude API for a fix, runs tests, pushes, and confirms via Telegram.

Design constraints:
  - STDLIB ONLY (no anthropic SDK import at module level — imported lazily)
  - FAIL-SAFE: on any error → rollback → Telegram "manual review needed"
  - SAFE: only touches spa_core/ and tests/ — never scripts/, data/, .github/
  - Backup to /tmp/spa_autofix_backup_{filename} before any edit
  - Rate limit: max 3 auto-fix attempts per hour (tracked via /tmp files)
  - No hardcoded secrets: reads from macOS Keychain only

Keychain services:
  ANTHROPIC_API_KEY    — Claude API key
  TELEGRAM_BOT_TOKEN_SPA — Telegram bot token
  TELEGRAM_CHAT_ID_SPA   — Telegram chat ID
  GITHUB_PAT_SPA         — GitHub PAT for push
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("spa.monitoring.auto_fixer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root (spa_core/monitoring/→spa_core/→root)

ALLOWED_PREFIXES = (
    "spa_core/",
    "tests/",
)
FORBIDDEN_FILES = {
    "cycle_runner.py",
    "kill_switch.py",
}
FORBIDDEN_DIRS = {
    "scripts",
    "data",
    ".github",
}

MAX_FIXES_PER_HOUR = 3
RATE_LIMIT_PREFIX = "/tmp/spa_autofix_rate_"
BACKUP_PREFIX = "/tmp/spa_autofix_backup_"

CONTEXT_LINES = 200           # lines of file context sent to Claude
TEST_TIMEOUT_SEC = 120        # pytest timeout per run
PUSH_SCRIPT = BASE_DIR / "push_to_github.py"

ANTHROPIC_SERVICE = "ANTHROPIC_API_KEY"
TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 2000


# ---------------------------------------------------------------------------
# Keychain helpers
# ---------------------------------------------------------------------------

def _read_keychain(service: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val:
                return val
    except Exception:
        pass
    return None


def get_anthropic_key() -> Optional[str]:
    key = _read_keychain(ANTHROPIC_SERVICE)
    if not key:
        key = os.environ.get("ANTHROPIC_API_KEY")
    return key


def get_bot_token() -> Optional[str]:
    token = _read_keychain(TOKEN_SERVICE)
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN_SPA") or os.environ.get("TELEGRAM_BOT_TOKEN")
    return token


def get_chat_id() -> Optional[str]:
    cid = _read_keychain(CHAT_ID_SERVICE)
    if not cid:
        cid = os.environ.get("TELEGRAM_CHAT_ID_SPA") or os.environ.get("TELEGRAM_CHAT_ID")
    return cid


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _rate_limit_count() -> int:
    """Count fix attempts in the last hour."""
    now = time.time()
    count = 0
    for i in range(MAX_FIXES_PER_HOUR + 5):
        path = RATE_LIMIT_PREFIX + str(i)
        if os.path.exists(path):
            age = now - os.path.getmtime(path)
            if age < 3600:
                count += 1
    return count


def _rate_limit_record() -> None:
    """Record a fix attempt."""
    now = time.time()
    # Find an available slot
    for i in range(100):
        path = RATE_LIMIT_PREFIX + str(i)
        if not os.path.exists(path):
            try:
                with open(path, "w") as f:
                    f.write(str(now))
            except OSError:
                pass
            return
        age = now - os.path.getmtime(path)
        if age >= 3600:
            # Reuse expired slot
            try:
                with open(path, "w") as f:
                    f.write(str(now))
            except OSError:
                pass
            return


def is_rate_limited() -> bool:
    return _rate_limit_count() >= MAX_FIXES_PER_HOUR


# ---------------------------------------------------------------------------
# Traceback / file parsing
# ---------------------------------------------------------------------------

def find_affected_file(alert_text: str) -> Optional[Path]:
    """
    Parse a Python traceback to find the last (most recent) file reference
    inside an allowed directory. Returns absolute Path or None.
    """
    # Pattern: File "path/to/file.py", line N
    pattern = re.compile(r'File ["\']([^"\']+\.py)["\']', re.IGNORECASE)
    matches = pattern.findall(alert_text)

    # Walk from end (most recent frame) to start
    for raw_path in reversed(matches):
        path = Path(raw_path)
        # Try as absolute first
        if path.is_absolute() and path.exists():
            rel = _to_relative(path)
            if rel and safety_check(rel):
                return path
        # Try relative to BASE_DIR
        candidate = BASE_DIR / path
        if candidate.exists():
            rel = _to_relative(candidate)
            if rel and safety_check(rel):
                return candidate
        # Try stripping leading components until we find a match
        parts = path.parts
        for i in range(len(parts)):
            candidate = BASE_DIR / Path(*parts[i:])
            if candidate.exists():
                rel = _to_relative(candidate)
                if rel and safety_check(rel):
                    return candidate

    return None


def _to_relative(abs_path: Path) -> Optional[str]:
    """Convert absolute path to relative string from BASE_DIR. None if not under BASE_DIR."""
    try:
        return str(abs_path.relative_to(BASE_DIR))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

def safety_check(rel_path: str) -> bool:
    """
    Return True ONLY if the file is safe to auto-fix.
    Rules:
      - Must be under spa_core/ or tests/
      - Must not be a forbidden file (cycle_runner.py, kill_switch.py)
      - Must not be in a forbidden directory
    """
    # Normalize separators
    rel = rel_path.replace("\\", "/")

    # Must start with an allowed prefix
    if not any(rel.startswith(pfx) for pfx in ALLOWED_PREFIXES):
        log.warning("safety_check: %s not in allowed prefixes", rel)
        return False

    # Check forbidden file names
    filename = Path(rel).name
    if filename in FORBIDDEN_FILES:
        log.warning("safety_check: %s is a forbidden file", rel)
        return False

    # Check forbidden directories anywhere in the path
    parts = Path(rel).parts
    for part in parts:
        if part in FORBIDDEN_DIRS:
            log.warning("safety_check: %s contains forbidden dir '%s'", rel, part)
            return False

    return True


# ---------------------------------------------------------------------------
# Backup & rollback
# ---------------------------------------------------------------------------

def create_backup(file_path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """Copy file to a backup location. Returns backup path.

    Default backup dir is /tmp (via BACKUP_PREFIX).  Tests should pass
    ``backup_dir=tmp_path`` to avoid cross-session /tmp ownership conflicts.
    LLM FORBIDDEN — deterministic file copy.
    """
    if backup_dir is not None:
        backup_path = Path(backup_dir) / ("spa_autofix_backup_" + file_path.name)
    else:
        backup_path = Path(BACKUP_PREFIX + file_path.name)
    try:
        shutil.copy2(str(file_path), str(backup_path))
        log.info("Backup created: %s", backup_path)
        return backup_path
    except OSError as exc:
        log.error("Failed to create backup: %s", exc)
        return None


def rollback(file_path: Path, backup_path: Path) -> bool:
    """Restore file from backup. Returns True on success."""
    try:
        shutil.copy2(str(backup_path), str(file_path))
        log.info("Rollback successful: %s ← %s", file_path, backup_path)
        return True
    except OSError as exc:
        log.error("Rollback failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def call_claude_api(alert_text: str, file_content: str, api_key: str) -> Optional[str]:
    """
    Call Claude claude-sonnet-4-6 to fix the bug. Returns fixed Python code or None.
    Uses stdlib urllib only; imports anthropic SDK as fallback.
    """
    system_prompt = (
        "You are a Python bug fixer for the SPA DeFi trading system. "
        "Fix only the specific error shown. "
        "Return ONLY the corrected Python code for the entire file, with no explanation, "
        "no markdown code fences, and no extra text. "
        "Preserve all existing functionality and imports."
    )
    user_msg = (
        f"Error:\n{alert_text}\n\n"
        f"File content:\n{file_content}\n\n"
        "Return the complete fixed Python file code only."
    )

    # Try via anthropic SDK first (if installed)
    try:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text if response.content else None
        if text:
            return _clean_code_response(text)
        return None
    except ImportError:
        pass  # Fall through to raw HTTP
    except Exception as exc:
        log.error("anthropic SDK error: %s", exc)
        return None

    # Fallback: raw HTTP to Anthropic Messages API
    try:
        payload = json.dumps({
            "model": CLAUDE_MODEL,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_msg}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        text = result.get("content", [{}])[0].get("text", "")
        if text:
            return _clean_code_response(text)
    except Exception as exc:
        log.error("Raw Anthropic API error: %s", exc)

    return None


def _clean_code_response(text: str) -> str:
    """Strip markdown code fences if Claude added them despite instructions."""
    text = text.strip()
    # Remove ```python ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(module_name: str) -> Tuple[bool, str]:
    """
    Run pytest for the module. Returns (passed, output_summary).
    Tries tests/test_{module}.py, falls back to tests/ full suite with -x.
    """
    test_file = BASE_DIR / "tests" / f"test_{module_name}.py"
    if not test_file.exists():
        # No specific test file — run the broad suite with --co to count
        test_dir = BASE_DIR / "tests"
        cmd = [sys.executable, "-m", "pytest", str(test_dir), "-x", "-q",
               "--timeout=30", "--tb=short", "--no-header", "-rN"]
    else:
        cmd = [sys.executable, "-m", "pytest", str(test_file), "-x", "-q",
               "--timeout=30", "--tb=short", "--no-header", "-rN"]

    log.info("Running tests: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SEC,
            cwd=str(BASE_DIR),
        )
        output = (result.stdout + result.stderr).strip()
        passed = result.returncode == 0
        # Extract summary line (e.g. "12 passed in 3.4s")
        summary = _extract_pytest_summary(output) or output[-300:]
        log.info("Tests %s: %s", "PASSED" if passed else "FAILED", summary)
        return passed, summary
    except subprocess.TimeoutExpired:
        return False, "Tests timed out"
    except Exception as exc:
        return False, f"Test runner error: {exc}"


def _extract_pytest_summary(output: str) -> str:
    """Extract the last summary line from pytest output."""
    for line in reversed(output.split("\n")):
        line = line.strip()
        if "passed" in line or "failed" in line or "error" in line:
            return line
    return ""


# ---------------------------------------------------------------------------
# GitHub push
# ---------------------------------------------------------------------------

def push_file(rel_path: str) -> Optional[str]:
    """Push a file to GitHub via push_to_github.py. Returns short SHA or None."""
    if not PUSH_SCRIPT.exists():
        log.error("push_to_github.py not found at %s", PUSH_SCRIPT)
        return None
    try:
        cmd = [
            sys.executable, str(PUSH_SCRIPT),
            "--file", rel_path,
            "--message", f"auto-fix: {rel_path}",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(BASE_DIR),
        )
        if result.returncode == 0:
            # Try to extract SHA from output
            sha = _extract_sha(result.stdout + result.stderr)
            log.info("Pushed %s (SHA=%s)", rel_path, sha)
            return sha or "pushed"
        else:
            log.error("push_to_github failed: %s", result.stderr[:500])
            return None
    except Exception as exc:
        log.error("push_file error: %s", exc)
        return None


def _extract_sha(output: str) -> Optional[str]:
    """Try to extract a 7-char commit SHA from push output."""
    match = re.search(r'\b([0-9a-f]{7,40})\b', output, re.IGNORECASE)
    if match:
        return match.group(1)[:7]
    return None


# ---------------------------------------------------------------------------
# Telegram notifications
# ---------------------------------------------------------------------------

def _tg_request(token: str, method: str, payload: Optional[Dict] = None,
                timeout: int = 10) -> Optional[Dict]:
    # FLOOD-GUARD: outbound sendMessage is routed through the canonical
    # rate-limited client so auto-fix notifications share the cross-process
    # flood guard. Other methods (none used today) fall through to direct HTTP.
    if method == "sendMessage" and payload:
        try:
            from spa_core.alerts.telegram_client import send_message
            ok = send_message(
                payload.get("text", ""),
                parse_mode=payload.get("parse_mode", "HTML"),
            )
            return {"ok": bool(ok)}
        except Exception as exc:
            log.warning("Telegram API %s failed: %s", method, exc)
            return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload or {}).encode() if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    try:
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("Telegram API %s failed: %s", method, exc)
        return None


def notify_success(token: str, chat_id: str, rel_path: str,
                   error_type: str, fix_description: str,
                   test_summary: str, sha: str) -> None:
    text = (
        "🤖 <b>Auto-Fix Applied</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"<b>File:</b> <code>{rel_path}</code>\n"
        f"<b>Error:</b> {error_type}\n"
        f"<b>Fix:</b> {fix_description}\n"
        f"<b>Tests:</b> {test_summary} ✅\n"
        f"<b>Pushed:</b> <code>{sha}</code>"
    )
    _tg_request(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
    }, timeout=15)


def notify_failure(token: str, chat_id: str, rel_path: str,
                   error_type: str, reason: str) -> None:
    text = (
        "⚠️ <b>Auto-Fix Failed — Manual Review Needed</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"<b>File:</b> <code>{rel_path}</code>\n"
        f"<b>Error:</b> {error_type}\n"
        f"<b>Reason:</b> {reason}\n"
        "Please review and fix manually."
    )
    _tg_request(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
    }, timeout=15)


def notify_no_api_key(token: str, chat_id: str) -> None:
    text = (
        "ℹ️ <b>Auto-Fix: No API Key</b>\n"
        "━━━━━━━━━━━━━━\n"
        "ANTHROPIC_API_KEY not found in Keychain.\n"
        "Alert detected but auto-fix disabled.\n\n"
        "To enable:\n"
        "<code>security add-generic-password -s ANTHROPIC_API_KEY -a spa -w YOUR_KEY</code>"
    )
    _tg_request(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
    }, timeout=15)


# ---------------------------------------------------------------------------
# Main fix orchestration
# ---------------------------------------------------------------------------

def run_auto_fix(alert_text: str, token: Optional[str] = None,
                 chat_id: Optional[str] = None) -> bool:
    """
    Full auto-fix pipeline. Returns True if fix was applied and pushed.

    Steps:
      1. Check rate limit
      2. Get API key (graceful degradation if missing)
      3. Find affected file
      4. Safety check
      5. Read file content
      6. Call Claude API
      7. Apply fix
      8. Run tests
      9. PASS → push → notify success
      10. FAIL → rollback → notify failure
    """
    token = token or get_bot_token()
    chat_id = chat_id or get_chat_id()

    # 1. Rate limit
    if is_rate_limited():
        log.warning("Rate limit reached (%d fixes/hr). Skipping.", MAX_FIXES_PER_HOUR)
        return False

    # 2. API key check
    api_key = get_anthropic_key()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not found — detection only mode")
        if token and chat_id:
            notify_no_api_key(token, chat_id)
        return False

    # 3. Find affected file
    affected_file = find_affected_file(alert_text)
    if not affected_file:
        log.warning("Could not identify affected file from alert")
        if token and chat_id:
            from spa_core.monitoring.telegram_watcher import parse_alert_type
            error_type = parse_alert_type(alert_text)
            notify_failure(token, chat_id, "unknown", error_type,
                           "Could not identify affected file from traceback")
        return False

    # 4. Safety check
    rel_path = _to_relative(affected_file)
    if not rel_path or not safety_check(rel_path):
        log.warning("Safety check failed for %s", affected_file)
        return False

    # Parse error type
    from spa_core.monitoring.telegram_watcher import parse_alert_type
    error_type = parse_alert_type(alert_text)
    log.info("Auto-fix: file=%s error_type=%s", rel_path, error_type)

    # 5. Read file content
    try:
        file_content = affected_file.read_text(encoding="utf-8", errors="replace")
        # Limit context to CONTEXT_LINES lines around the error if possible
        lines = file_content.split("\n")
        if len(lines) > CONTEXT_LINES * 2:
            # Try to find error line and center around it
            lineno = _extract_error_lineno(alert_text)
            if lineno:
                start = max(0, lineno - CONTEXT_LINES // 2)
                end = min(len(lines), lineno + CONTEXT_LINES // 2)
                file_content = "\n".join(lines[start:end])
            else:
                file_content = "\n".join(lines[:CONTEXT_LINES])
    except Exception as exc:
        log.error("Cannot read %s: %s", affected_file, exc)
        if token and chat_id:
            notify_failure(token, chat_id, rel_path, error_type,
                           f"Cannot read file: {exc}")
        return False

    # 6. Call Claude API
    log.info("Calling Claude API (model=%s)…", CLAUDE_MODEL)
    fixed_code = call_claude_api(alert_text[:4000], file_content, api_key)
    if not fixed_code:
        log.error("Claude API returned no fix")
        if token and chat_id:
            notify_failure(token, chat_id, rel_path, error_type, "Claude API returned no fix")
        return False

    # 7. Apply fix (with backup)
    backup_path = create_backup(affected_file)
    if not backup_path:
        log.error("Cannot create backup — aborting fix")
        return False

    # Record attempt
    _rate_limit_record()

    try:
        # Atomic write
        tmp_path = affected_file.with_suffix(".tmp_autofix")
        tmp_path.write_text(fixed_code, encoding="utf-8")
        tmp_path.replace(affected_file)
        log.info("Fix applied to %s", affected_file)
    except Exception as exc:
        log.error("Failed to write fix: %s", exc)
        if backup_path:
            rollback(affected_file, backup_path)
        if token and chat_id:
            notify_failure(token, chat_id, rel_path, error_type, f"Write error: {exc}")
        return False

    # 8. Run tests
    module_name = affected_file.stem  # e.g. "uptime_monitor"
    tests_passed, test_summary = run_tests(module_name)

    if tests_passed:
        # 9. Push
        sha = push_file(rel_path)
        fix_description = _summarize_fix(alert_text, error_type)
        if token and chat_id:
            notify_success(
                token, chat_id, rel_path, error_type,
                fix_description, test_summary, sha or "unknown"
            )
        log.info("✅ Auto-fix complete: %s", rel_path)
        return True
    else:
        # 10. Tests failed — rollback
        log.warning("Tests failed after fix — rolling back")
        rollback(affected_file, backup_path)
        if token and chat_id:
            notify_failure(token, chat_id, rel_path, error_type,
                           f"Tests failed after fix: {test_summary}")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_error_lineno(text: str) -> Optional[int]:
    """Extract line number from traceback text."""
    match = re.search(r', line (\d+)', text)
    if match:
        return int(match.group(1))
    return None


def _to_relative(abs_path: Path) -> Optional[str]:
    try:
        return str(abs_path.relative_to(BASE_DIR))
    except ValueError:
        return None


def _summarize_fix(alert_text: str, error_type: str) -> str:
    """Generate a short human-readable description of the fix applied."""
    if error_type == "ImportError":
        return "Fixed missing import / module reference"
    if error_type == "AttributeError":
        return "Added None check / fixed attribute access"
    if error_type == "FileNotFoundError":
        return "Added file existence check / fallback path"
    if error_type == "TypeError":
        return "Fixed type mismatch / argument handling"
    if error_type == "KeyError":
        return "Added dict key check / .get() usage"
    if error_type == "ValueError":
        return "Fixed value validation / conversion"
    if error_type == "NetworkError":
        return "Added connection timeout / retry logic"
    return f"Fixed {error_type}"


# ---------------------------------------------------------------------------
# CLI entry point (for subprocess invocation by telegram_watcher)
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="SPA Auto Fixer")
    parser.add_argument("--alert", type=str, help="Alert text to process")
    parser.add_argument("--alert-file", type=str, help="File containing alert text")
    args = parser.parse_args()

    alert_text = ""
    if args.alert:
        alert_text = args.alert
    elif args.alert_file:
        alert_text = Path(args.alert_file).read_text()
    else:
        # Read from stdin
        alert_text = sys.stdin.read()

    if not alert_text.strip():
        log.error("No alert text provided")
        sys.exit(1)

    success = run_auto_fix(alert_text)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
