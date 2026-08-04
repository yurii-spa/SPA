"""d5.security.secrets — a name is not evidence; the content is.

The check matched only the BASENAME, so a markdown card titled "rotate the
exposed secret" and a protocol `token_emission_log.json` both raised CRITICAL.
Being the only CRITICAL in the report, they masked everything else — while
neither file holds a credential.

These tests pin BOTH directions: a real key still trips CRITICAL (protection
intact), and a name-only match is reported as WARNING (visible, not silence).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spa_core.monitoring.system_health_monitor import SystemHealthMonitor


def _monitor(tmp_path: Path, untracked) -> SystemHealthMonitor:
    m = SystemHealthMonitor.__new__(SystemHealthMonitor)
    m.repo_root = tmp_path
    m._git_untracked = list(untracked)
    return m


def test_real_credential_still_raises_critical(tmp_path: Path) -> None:
    """Protection intact: a key is a long high-entropy string, and that trips."""
    f = tmp_path / "prod_api_key.txt"
    f.write_text("ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", encoding="utf-8")
    res = _monitor(tmp_path, ["prod_api_key.txt"])._check_secrets("d5")
    assert res.status == "CRITICAL"
    assert "credential-shaped" in res.title


def test_pem_private_key_raises_critical(tmp_path: Path) -> None:
    f = tmp_path / "secret.pem"
    f.write_text("-----BEGIN RSA PRIVATE KEY-----\nabc\n", encoding="utf-8")
    assert _monitor(tmp_path, ["secret.pem"])._check_secrets("d5").status == "CRITICAL"


def test_card_named_like_a_secret_is_only_a_warning(tmp_path: Path) -> None:
    """The exact 2026-08-04 false positive: a card ABOUT rotating a secret."""
    f = tmp_path / "own-25-siwe-secret-exposed-rotate.md"
    f.write_text("# Сменить секрет входа\n\nСамо значение здесь НЕ приводится.\n",
                 encoding="utf-8")
    res = _monitor(tmp_path, ["own-25-siwe-secret-exposed-rotate.md"])._check_secrets("d5")
    assert res.status == "WARNING"      # named, visible — but not a false alarm
    assert res.evidence["paths"] == ["own-25-siwe-secret-exposed-rotate.md"]


def test_unreadable_file_counts_as_suspected_not_clean(tmp_path: Path) -> None:
    """Unknown is never reported as safe — that is how real leaks hide."""
    res = _monitor(tmp_path, ["token_that_does_not_exist.json"])._check_secrets("d5")
    assert res.status == "CRITICAL"     # cannot read ⇒ cannot clear it


def test_clean_tree_is_ok(tmp_path: Path) -> None:
    assert _monitor(tmp_path, [])._check_secrets("d5").status == "OK"
