"""
spa_core/tests/test_academy_seedguard.py

Focused tests for the Academy SeedPhraseGuard middleware + its pure scan_payload
detector. Confirms it blocks private keys and BIP39 seed phrases, exempts a
legitimate top-level tx_hash, and never false-positives on ordinary or non-BIP39
Unicode text. Tmp-file DB, NO network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.api.app import create_academy_app
from spa_core.academy.api.middleware import scan_payload, BIP39_WORDLIST

_TWELVE_BIP39 = (
    "abandon ability able about above absent absorb abstract absurd "
    "abuse access accident"
)
_ELEVEN_BIP39 = (
    "abandon ability able about above absent absorb abstract absurd abuse access"
)
_PRIVKEY = "0x" + "a" * 64
_TXHASH = "0x" + "b" * 64
_UNICODE_NON_BIP39 = "привет мир как дела сегодня хорошо погода солнце ветер дождь снег лёд"


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    # Turn the rate limiter off so repeated POSTs to /verify never 429 here.
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")


@pytest.fixture()
def client(tmp_path):
    p = tmp_path / "academy_seedguard.db"
    d = AcademyDB(db_path=str(p))
    d.run_migrations()
    return TestClient(create_academy_app(db_path=str(p)))


# ── pure detector ────────────────────────────────────────────────────────────


def test_wordlist_loaded():
    assert len(BIP39_WORDLIST) == 2048
    assert "abandon" in BIP39_WORDLIST and "zoo" in BIP39_WORDLIST


def test_scan_twelve_bip39_words_flagged():
    assert scan_payload({"note": _TWELVE_BIP39}) is True


def test_scan_eleven_bip39_words_not_flagged():
    assert scan_payload({"note": _ELEVEN_BIP39}) is False


def test_scan_private_key_flagged():
    assert scan_payload({"note": _PRIVKEY}) is True


def test_scan_top_level_tx_hash_exempt():
    assert scan_payload({"tx_hash": _TXHASH}) is False


def test_scan_nested_tx_hash_not_exempt():
    # The exemption is TOP-LEVEL only; a nested 64-hex is still a rejected key.
    assert scan_payload({"proof": {"tx_hash": _TXHASH}}) is True


def test_scan_plain_text_not_flagged():
    assert scan_payload({"note": "hello world this is a normal note"}) is False


def test_scan_unicode_non_bip39_not_flagged():
    assert scan_payload({"note": _UNICODE_NON_BIP39}) is False


# ── HTTP boundary ────────────────────────────────────────────────────────────


def test_http_seed_phrase_rejected(client):
    r = client.post("/verify/submit", json={"note": _TWELVE_BIP39})
    assert r.status_code == 400
    assert r.json()["error"] == "SEED_PHRASE_REJECTED"


def test_http_eleven_words_pass_guard(client):
    r = client.post("/verify/submit", json={"note": _ELEVEN_BIP39})
    assert r.status_code != 400


def test_http_private_key_rejected(client):
    r = client.post("/verify/submit", json={"note": _PRIVKEY})
    assert r.status_code == 400


def test_http_tx_hash_passes_guard(client):
    r = client.post("/verify/submit", json={"tx_hash": _TXHASH})
    assert r.status_code != 400


def test_http_plain_text_passes_guard(client):
    r = client.post("/verify/submit", json={"note": "just an ordinary note here"})
    assert r.status_code != 400
