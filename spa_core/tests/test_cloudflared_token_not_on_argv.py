"""
test_cloudflared_token_not_on_argv.py — ADR-556 / RM-LIVE-01 hardening.

``scripts/run_cloudflared.sh`` used to exec cloudflared as
``cloudflared tunnel --no-autoupdate run --token "$TOKEN"`` — the secret sat
on the process's own argv, readable by any same-user process (``ps -ef``,
``/proc/<pid>/cmdline``) for the tunnel's whole lifetime. cloudflared reads
the identical secret from the ``TUNNEL_TOKEN`` environment variable, which is
NOT visible in a process listing the same way. This is a STATIC guard over
the script's source text — stricter-only, no execution, no network, no
Keychain access, no cloudflared restart (that is a separate, later, owner-
supervised deployment step per ``.claude/rules/deployment.md``).

Detection note: the script invokes the binary via a resolved ``"$bin"``
variable (``exec "$bin" tunnel --no-autoupdate run``), so a naive scan for
the literal word ``cloudflared`` on the exec line would miss it entirely —
and would therefore pass VACUOUSLY on both the buggy and the fixed script.
The guard instead keys off cloudflared's distinctive subcommand shape
(``tunnel ... run``), which the positive control below proves actually
catches the historical bug.
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_cloudflared.sh"

# cloudflared's tunnel-run invocation: "tunnel [flags...] run" (flags, e.g.
# --no-autoupdate, may appear in between; --token is one such flag we must
# never see here).
_TUNNEL_RUN_RE = re.compile(r"\btunnel\b.*\brun\b")


def _tunnel_run_lines(text: str) -> list[str]:
    """Every CODE line (comments excluded) that invokes cloudflared's
    ``tunnel ... run`` subcommand."""
    return [
        line for line in text.splitlines()
        if not line.strip().startswith("#") and _TUNNEL_RUN_RE.search(line)
    ]


def _lines_with_token_flag(text: str) -> list[str]:
    """Guard under test: tunnel-run lines that still carry ``--token`` on argv."""
    return [line for line in _tunnel_run_lines(text) if "--token" in line]


def _is_tunnel_token_exported(text: str) -> bool:
    """True if the script exports TUNNEL_TOKEN (cloudflared's own env var)."""
    return bool(re.search(r"^\s*export\s+TUNNEL_TOKEN=", text, re.MULTILINE))


class TestGuardPositiveControl:
    """Prove the checker catches the exact historical bug before trusting it
    on the real script (a checker that never saw a real failure is not
    verified) — and that it does NOT trigger on the fixed shape."""

    OLD_STYLE = (
        '#!/bin/bash\n'
        'TOKEN=$(security find-generic-password -s "CF_TUNNEL_TOKEN_SPA" -w)\n'
        'exec "$bin" tunnel --no-autoupdate run --token "$TOKEN"\n'
    )
    NEW_STYLE = (
        '#!/bin/bash\n'
        'TOKEN=$(security find-generic-password -s "CF_TUNNEL_TOKEN_SPA" -w)\n'
        'export TUNNEL_TOKEN="$TOKEN"\n'
        'exec "$bin" tunnel --no-autoupdate run\n'
    )

    def test_finds_the_tunnel_run_line_at_all(self):
        """Sanity for the detector itself: it must actually locate the
        invocation line in both snippets (otherwise later assertions about
        '--token' absence would be vacuous)."""
        assert _tunnel_run_lines(self.OLD_STYLE)
        assert _tunnel_run_lines(self.NEW_STYLE)

    def test_catches_token_on_argv_in_synthetic_old_style_snippet(self):
        offending = _lines_with_token_flag(self.OLD_STYLE)
        assert offending, "guard failed to catch --token on argv in the old-style snippet"

    def test_old_style_snippet_does_not_export_tunnel_token(self):
        """Sanity: the old-style snippet must NOT already export TUNNEL_TOKEN
        (otherwise the positive control above proves nothing about ordering)."""
        assert not _is_tunnel_token_exported(self.OLD_STYLE)

    def test_passes_synthetic_new_style_snippet(self):
        assert _lines_with_token_flag(self.NEW_STYLE) == []
        assert _is_tunnel_token_exported(self.NEW_STYLE)


class TestRealScript:
    """The actual guard, run over the real script shipped in this repo."""

    @classmethod
    def setup_class(cls):
        assert SCRIPT_PATH.is_file(), f"script not found: {SCRIPT_PATH}"
        cls.text = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_script_exists_and_is_nonempty(self):
        assert self.text.strip(), "run_cloudflared.sh is empty"

    def test_tunnel_run_line_present(self):
        """Sanity: the script really does invoke `tunnel ... run` somewhere,
        so the no-token assertion below is not vacuously true on an
        unrelated file."""
        lines = _tunnel_run_lines(self.text)
        assert lines, "no cloudflared `tunnel ... run` line found — wrong script?"

    def test_no_token_flag_on_the_tunnel_run_line(self):
        offending = _lines_with_token_flag(self.text)
        assert offending == [], (
            "run_cloudflared.sh still puts the tunnel token on argv "
            f"(--token found on): {offending!r}"
        )

    def test_tunnel_token_env_var_is_exported(self):
        assert _is_tunnel_token_exported(self.text), (
            "run_cloudflared.sh must `export TUNNEL_TOKEN=...` so cloudflared "
            "reads the secret from the environment, not argv"
        )

    def test_export_happens_before_the_tunnel_run_line(self):
        """Ordering matters: TUNNEL_TOKEN must be exported in THIS shell
        before the exec line replaces the process image."""
        lines = self.text.splitlines()
        export_idx = next(
            (i for i, l in enumerate(lines) if re.match(r"^\s*export\s+TUNNEL_TOKEN=", l)),
            None,
        )
        run_idx = next(
            (i for i, l in enumerate(lines)
             if not l.strip().startswith("#") and _TUNNEL_RUN_RE.search(l)),
            None,
        )
        assert export_idx is not None, "export TUNNEL_TOKEN line not found"
        assert run_idx is not None, "tunnel run line not found"
        assert export_idx < run_idx, "TUNNEL_TOKEN must be exported BEFORE the tunnel run line"

    def test_tunnel_run_line_uses_exec(self):
        """The invocation must replace the shell process (exec), not fork a
        child — otherwise the parent shell would still hold the env/secret
        lifecycle question open. Pre-existing property; pinned so a future
        edit can't silently drop `exec`."""
        lines = _tunnel_run_lines(self.text)
        assert lines and all(re.search(r"\bexec\b", l) for l in lines)

    def test_token_variable_never_echoed_or_printed(self):
        """Never print the secret (the raw Keychain read result) to a log."""
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\b(echo|printf)\b", stripped) and "$TOKEN" in stripped:
                raise AssertionError(f"token appears to be echoed: {line!r}")

    def test_keychain_read_is_still_present(self):
        """Stricter-only: the Keychain read itself must remain (no credential
        change), only the delivery mechanism to cloudflared changes."""
        assert "security find-generic-password" in self.text
        assert "CF_TUNNEL_TOKEN_SPA" in self.text
