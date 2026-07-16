"""spa_core/tests/test_lead_ping_routing.py — Q6 / Q-OWN-16 lead-ping materiality routing.

Owner decision (ADR-OWN-2026-07-lead-pings): a MATERIAL /pilot lead (B2B / early-access /
aggressive tier) fires an INSTANT per-lead Telegram ping via the ``pilot_request`` one-shot
Tier-1 key; a non-material (free-mail retail) lead stays demoted to the daily digest.

This proves the routing decision in ``interest._notify_owner_telegram`` and the pure classifier
``interest._is_material_lead``. Telegram transport is never touched — we capture which push_policy
entrypoint (instant ``push_critical`` vs ``enqueue_digest``) each lead was routed to.

PURE / deterministic / no network. LLM_FORBIDDEN.
"""
from __future__ import annotations

import pytest

from spa_core.api.routers import interest as I
from spa_core.telegram import push_policy


@pytest.fixture
def routed(monkeypatch):
    """Capture the push_policy entrypoint each lead is routed to (no transport)."""
    calls: list[tuple[str, str]] = []  # (route, event_key)

    def fake_push_critical(event_key, severity, title, body, **kw):
        calls.append(("instant", event_key))
        return True

    def fake_enqueue_digest(event_key, title, body="", **kw):
        calls.append(("digest", event_key))

    monkeypatch.setattr(push_policy, "push_critical", fake_push_critical)
    monkeypatch.setattr(push_policy, "enqueue_digest", fake_enqueue_digest)
    return calls


# ── pure classifier ──────────────────────────────────────────────────────────
def test_material_classifier_signals():
    # B2B / institutional domain → material
    assert I._is_material_lead("fund@family-office.io", "", "", "") is True
    assert I._is_material_lead("gp@acme-capital.com", "", "conservative", "") is True
    # early-access commitment → material even on free mail
    assert I._is_material_lead("someone@gmail.com", "", "", "early_access") is True
    # aggressive tier → material even on free mail
    assert I._is_material_lead("someone@gmail.com", "", "aggressive", "") is True
    # plain free-mail retail, no commitment marker → NOT material
    assert I._is_material_lead("someone@gmail.com", "just curious", "conservative", "") is False
    assert I._is_material_lead("x@yandex.ru", "", "balanced", "") is False


def test_material_classifier_is_case_insensitive():
    assert I._is_material_lead("A@GMAIL.COM", "", "AGGRESSIVE", "") is True
    assert I._is_material_lead("a@GMail.com", "", "Balanced", "EARLY_ACCESS") is True
    assert I._is_material_lead("a@gmail.com", "", "balanced", "pilot") is False


def test_no_at_sign_email_not_treated_as_b2b():
    # A malformed email (no domain) must not be mis-classified as a B2B domain.
    assert I._is_material_lead("garbage", "", "conservative", "") is False


# ── routing through _notify_owner_telegram ───────────────────────────────────
def test_material_lead_routes_to_instant_ping(routed):
    ok = I._notify_owner_telegram("gp@acme-capital.com", "let's talk", "balanced", "site:pilot")
    assert ok is True
    assert routed == [("instant", "pilot_request")]


def test_retail_lead_routes_to_digest(routed):
    ok = I._notify_owner_telegram("someone@gmail.com", "curious", "conservative", "")
    assert ok is True
    assert routed == [("digest", "pilot_request")]


def test_early_access_free_mail_still_instant(routed):
    ok = I._notify_owner_telegram("someone@gmail.com", "", "", "", source="early_access")
    assert ok is True
    assert routed == [("instant", "pilot_request")]


def test_notify_never_raises_on_push_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("telegram down")
    monkeypatch.setattr(push_policy, "push_critical", boom)
    # material lead + failing transport → best-effort False, never raises
    assert I._notify_owner_telegram("gp@acme-capital.com", "", "aggressive", "") is False
