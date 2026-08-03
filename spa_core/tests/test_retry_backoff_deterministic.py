"""A deterministic failure must not be slept on — and only a deterministic one.

Card: ``agent-offline-suite-still-pays-full-retry-backoff`` (cycle #103).

Two claims are pinned here, and the second one is the important one:

1. **The fast path exists.** A failure carrying
   :data:`~spa_core.utils.retry_backoff.DETERMINISTIC_FAILURE_ATTR` ends the
   retry loop immediately, with the same caller-visible outcome the exhausted
   loop produced (``None`` for the feeds, a re-raise for the Pendle helpers).

2. **Production still backs off.** A plain transport error keeps every sleep
   it had, and no runtime module marks its exceptions — so the change is
   provably inert outside the test suite. Without this half, a later "let's
   mark this one too" would silently turn a transient production failure into
   a no-retry one, which is a real fail-CLOSED regression: the adapter would
   report a dead feed after a single hiccup.

Nothing here weakens an assertion (invariant #16): the failure branches are the
same branches, exercised the same way, only the waiting is gone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from spa_core.adapters import pendle_pt
from spa_core.feeds import defi_llama_feed, perp_funding_feed
from spa_core.tests.network_guard import LiveNetworkAccessAttempted
from spa_core.utils.retry_backoff import DETERMINISTIC_FAILURE_ATTR, is_retryable

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _SleepSpy:
    """Records every ``time.sleep`` a retry loop asks for."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


# ── the contract itself ───────────────────────────────────────────────────────

def test_unmarked_exception_is_retryable() -> None:
    """Anything that does not opt in keeps its backoff (fail-OPEN to retrying)."""
    assert is_retryable(OSError("connection reset"))
    assert is_retryable(TimeoutError())
    assert is_retryable(ValueError("bad payload"))


def test_guard_refusal_is_not_retryable() -> None:
    """The offline guard's refusal declares itself deterministic."""
    assert not is_retryable(LiveNetworkAccessAttempted("offline"))
    assert getattr(LiveNetworkAccessAttempted, DETERMINISTIC_FAILURE_ATTR) is True
    # …and it is still an OSError, so callers take their normal transport-error
    # path — the fail-CLOSED contract the guard was built around.
    assert issubclass(LiveNetworkAccessAttempted, OSError)


def test_only_the_test_guard_marks_its_exceptions() -> None:
    """No runtime module may opt out of retries — the reason prod is unchanged.

    Scans the repository for assignments of the marker attribute. The single
    legitimate writer is ``spa_core/tests/network_guard.py``; ``retry_backoff``
    and this file only *name* the attribute.
    """
    allowed = {
        "spa_core/tests/network_guard.py",
        "spa_core/utils/retry_backoff.py",
        "spa_core/tests/test_retry_backoff_deterministic.py",
    }
    assign = re.compile(
        r"(^|[^\w.])" + re.escape(DETERMINISTIC_FAILURE_ATTR) + r"\s*=\s*"
    )
    offenders = []
    for path in _REPO_ROOT.joinpath("spa_core").rglob("*.py"):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in allowed:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover — unreadable file is not a finding
            continue
        if DETERMINISTIC_FAILURE_ATTR not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            marks = assign.search(line) or (
                "setattr(" in line and DETERMINISTIC_FAILURE_ATTR in line
            )
            if marks:
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "a module outside the test guard marks its exceptions non-retriable — "
        "that turns a TRANSIENT production failure into a no-retry one:\n"
        + "\n".join(offenders)
    )


# ── defi_llama_feed._fetch_with_retry ─────────────────────────────────────────

def _feed() -> "defi_llama_feed.DefiLlamaFeed":
    return defi_llama_feed.DefiLlamaFeed()


def test_defillama_transient_error_still_backs_off(monkeypatch) -> None:
    """Positive control: the sleeps a real network error earns are still paid."""
    spy = _SleepSpy()
    monkeypatch.setattr(defi_llama_feed.time, "sleep", spy)
    monkeypatch.setattr(
        defi_llama_feed.DefiLlamaFeed,
        "_fetch_url",
        lambda self, url, ua: (_ for _ in ()).throw(OSError("connection reset")),
    )

    assert _feed()._fetch_with_retry("http://example.invalid") is None
    assert len(spy.delays) == defi_llama_feed.MAX_RETRIES - 1
    assert all(d > 0 for d in spy.delays)


def test_defillama_deterministic_failure_does_not_sleep(monkeypatch) -> None:
    spy = _SleepSpy()
    calls: list[str] = []
    monkeypatch.setattr(defi_llama_feed.time, "sleep", spy)

    def _refuse(self, url, ua):  # noqa: ANN001
        calls.append(ua)
        raise LiveNetworkAccessAttempted("offline")

    monkeypatch.setattr(defi_llama_feed.DefiLlamaFeed, "_fetch_url", _refuse)

    # Same outcome as the exhausted loop — None — with no waiting and no
    # further attempts that could not have succeeded.
    assert _feed()._fetch_with_retry("http://example.invalid") is None
    assert spy.delays == []
    assert len(calls) == 1


# ── pendle helpers (they re-raise instead of returning None) ─────────────────

@pytest.mark.parametrize("mod", [pendle_pt])
def test_pendle_transient_error_still_backs_off(mod, monkeypatch) -> None:
    """Positive control for the live Pendle transport.

    Parametrised over one module on purpose: the sibling
    ``spa_core/adapters/pendle_pt_adapter.py`` carries the same loop but is
    RETIRED (MP-354) — it raises ``ImportError`` at import time, so its copy is
    unreachable and was deliberately left untouched.
    """
    spy = _SleepSpy()
    monkeypatch.setattr(mod.time, "sleep", spy)
    monkeypatch.setattr(
        mod, "_http_get",
        lambda url, timeout=None: (_ for _ in ()).throw(OSError("connection reset")),
    )

    with pytest.raises(OSError):
        mod._http_get_with_retry("http://example.invalid")
    assert len(spy.delays) >= 1


@pytest.mark.parametrize("mod", [pendle_pt])
def test_pendle_deterministic_failure_does_not_sleep(mod, monkeypatch) -> None:
    spy = _SleepSpy()
    attempts: list[int] = []
    monkeypatch.setattr(mod.time, "sleep", spy)

    def _refuse(url, timeout=None):  # noqa: ANN001
        attempts.append(1)
        raise LiveNetworkAccessAttempted("offline")

    monkeypatch.setattr(mod, "_http_get", _refuse)

    # The exhausted loop re-raises the last exception; so does the fast path.
    with pytest.raises(LiveNetworkAccessAttempted):
        mod._http_get_with_retry("http://example.invalid")
    assert spy.delays == []
    assert len(attempts) == 1


# ── perp_funding_feed._post_info ─────────────────────────────────────────────

def test_perp_funding_transient_error_still_backs_off(monkeypatch) -> None:
    spy = _SleepSpy()
    monkeypatch.setattr(perp_funding_feed.time, "sleep", spy)
    monkeypatch.setattr(
        perp_funding_feed.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("connection reset")),
    )

    feed = perp_funding_feed.PerpFundingFeed()
    assert feed._post_info({"type": "metaAndAssetCtxs"}) is None
    assert len(spy.delays) == perp_funding_feed.MAX_RETRIES - 1


def test_perp_funding_deterministic_failure_does_not_sleep(monkeypatch) -> None:
    spy = _SleepSpy()
    monkeypatch.setattr(perp_funding_feed.time, "sleep", spy)
    monkeypatch.setattr(
        perp_funding_feed.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(LiveNetworkAccessAttempted("offline")),
    )

    feed = perp_funding_feed.PerpFundingFeed()
    assert feed._post_info({"type": "metaAndAssetCtxs"}) is None
    assert spy.delays == []
