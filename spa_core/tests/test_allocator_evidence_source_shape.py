"""ADR-061 — the evidence reader must survive a *valid* JSON that is not an object.

Found by cycle #95 while tracing why ``SPA CI-Lite`` went red on 2026-08-02T19:14Z
(first red run ``30762909474``, still red on ``49d0d1122``). Its ``Type check —
mypy on key modules`` step failed with a single error::

    spa_core/allocator/allocator.py:244: error: Returning Any from function
        declared to return "dict[Any, Any]"  [no-any-return]

``git log -S`` attributes the function to exactly one commit — ``f35ff96ed``
("ADR-061: evidence gate in money-path allocator"). The mypy error is not
cosmetic; it names a real hole. ``json.loads`` returns ``Any``, so the ``-> dict``
annotation checked nothing, and a *valid* JSON document that simply is not an
object (``[]``, ``"text"``, ``5``) flowed straight through into ``.get`` /
``.items`` / ``for``:

    orch = [] (valid JSON array)      -> AttributeError: 'list' object has no attribute 'get'
    orch = "text"                     -> AttributeError: 'str' object has no attribute 'get'
    orch = 5                          -> AttributeError: 'int' object has no attribute 'get'
    orch adapters = 5                 -> TypeError: 'int' object is not iterable
    status = [] (valid JSON array)    -> AttributeError: 'list' object has no attribute 'get'
    status adapters = [1, 2]          -> AttributeError: 'list' object has no attribute 'items'

All six reproduce verbatim on ``origin/main`` ``49d0d1122``. That contradicts the
documented contract of ``_load_evidenced_apy`` — "Never raises: any
unreadable/invalid input contributes nothing" — and the caller
(``allocator.py``, the ADR-061 evidence block) does **not** wrap the call, so the
exception escapes into the money-path allocation step of the daily cycle. The
``try`` in ``_read`` only ever covered reading and parsing, never the *shape* of
what was parsed.

Contract pinned here: a non-object document is an unreadable input — logged and
worth no evidence (fail-CLOSED, invariant 2), exactly like a truncated file.

Hermetic: every case writes its own files under ``tmp_path``. No network, no
dependence on the live repo's ``data/``. Thresholds, RiskPolicy and the
kill-switch are untouched by this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.allocator.allocator import _load_evidenced_apy


# ── fixtures ────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _well_formed_orch(path: Path) -> Path:
    """An orchestrator snapshot with one genuinely observed pool."""
    return _write(path, json.dumps({
        "generated_at": "2026-08-02T06:00:00+00:00",
        "adapters": [
            {"protocol": "pendle", "status": "ok", "apy_pct": 13.9419,
             "live_data": True},
        ],
    }))


def _well_formed_status(path: Path) -> Path:
    """An ``adapter_status.json`` with one non-null ``live_apy`` (== observed)."""
    return _write(path, json.dumps({
        "generated_at": "2026-08-02T15:01:33+00:00",
        "adapters": {"morpho_steakhouse": {"live_apy": 3.4657}},
    }))


# Every one of these is *valid* JSON. None of them is an object of the shape the
# producers actually write — which is the whole point.
NON_OBJECT_DOCUMENTS = ["[]", '"text"', "5", "null", "true", '[{"protocol": "x"}]']


# ── the defect: a valid non-object document must not raise ──────────────────


@pytest.mark.parametrize("document", NON_OBJECT_DOCUMENTS)
def test_non_object_orchestrator_document_yields_no_evidence(
    tmp_path: Path, document: str
) -> None:
    """``adapter_orchestrator_status.json`` that is not an object ⇒ no evidence.

    On ``origin/main`` this raised ``AttributeError`` out of the allocator.
    """
    orch = _write(tmp_path / "orch.json", document)
    status = _well_formed_status(tmp_path / "status.json")

    # The well-formed second source must still be read: one broken source does
    # not blind the other (that would be an unnecessary widening of the refusal).
    assert _load_evidenced_apy(orch, status) == {
        "morpho_steakhouse": (pytest.approx(0.034657), "adapter_status_live"),
    }


@pytest.mark.parametrize("document", NON_OBJECT_DOCUMENTS)
def test_non_object_status_document_yields_no_evidence(
    tmp_path: Path, document: str
) -> None:
    """``adapter_status.json`` that is not an object ⇒ no evidence from it."""
    orch = _well_formed_orch(tmp_path / "orch.json")
    status = _write(tmp_path / "status.json", document)

    assert _load_evidenced_apy(orch, status) == {
        "pendle": (pytest.approx(0.139419), "orchestrator_live"),
    }


def test_both_sources_non_object_is_an_empty_map_not_a_crash(tmp_path: Path) -> None:
    """Both sources unusable ⇒ ``{}`` — the same answer as "file not found"."""
    assert _load_evidenced_apy(
        _write(tmp_path / "orch.json", "[]"),
        _write(tmp_path / "status.json", '"text"'),
    ) == {}


# ── the defect one level down: the ``adapters`` container's own shape ───────


@pytest.mark.parametrize("adapters", [5, "text", True, {"pendle": {}}])
def test_orchestrator_adapters_that_is_not_a_list_yields_no_evidence(
    tmp_path: Path, adapters: object
) -> None:
    """A well-formed object whose ``adapters`` is not a list must not raise.

    ``adapters: 5`` raised ``TypeError: 'int' object is not iterable`` on
    ``origin/main``. A mapping (the *other* producer's schema) never yielded
    evidence there either — iterating a dict yields its keys, which are not
    dicts — so refusing it outright changes no outcome, only adds a log line.
    """
    orch = _write(tmp_path / "orch.json", json.dumps({
        "generated_at": "2026-08-02T06:00:00+00:00", "adapters": adapters,
    }))
    status = _well_formed_status(tmp_path / "status.json")

    assert _load_evidenced_apy(orch, status) == {
        "morpho_steakhouse": (pytest.approx(0.034657), "adapter_status_live"),
    }


@pytest.mark.parametrize("adapters", [[1, 2], "text", 5, True])
def test_status_adapters_that_is_not_a_mapping_yields_no_evidence(
    tmp_path: Path, adapters: object
) -> None:
    """``adapters: [1, 2]`` raised ``AttributeError`` (``list.items``) before."""
    orch = _well_formed_orch(tmp_path / "orch.json")
    status = _write(tmp_path / "status.json", json.dumps({
        "generated_at": "2026-08-02T15:01:33+00:00", "adapters": adapters,
    }))

    assert _load_evidenced_apy(orch, status) == {
        "pendle": (pytest.approx(0.139419), "orchestrator_live"),
    }


# ── positive controls: the fix must not clamp a healthy read ───────────────


def test_well_formed_sources_still_produce_both_evidences(tmp_path: Path) -> None:
    """POSITIVE CONTROL — the refusal is about shape, not about reading less.

    Fails if the shape guard is written too wide (e.g. rejecting any document
    whose values are not all dicts).
    """
    assert _load_evidenced_apy(
        _well_formed_orch(tmp_path / "orch.json"),
        _well_formed_status(tmp_path / "status.json"),
    ) == {
        "pendle": (pytest.approx(0.139419), "orchestrator_live"),
        "morpho_steakhouse": (pytest.approx(0.034657), "adapter_status_live"),
    }


def test_missing_adapters_key_is_still_simply_no_evidence(tmp_path: Path) -> None:
    """POSITIVE CONTROL — an object with no ``adapters`` key was always fine."""
    assert _load_evidenced_apy(
        _write(tmp_path / "orch.json", json.dumps({"generated_at": "2026-08-02T06:00:00+00:00"})),
        _write(tmp_path / "status.json", json.dumps({"generated_at": "2026-08-02T15:01:33+00:00"})),
    ) == {}


def test_a_single_malformed_entry_does_not_discard_its_neighbours(
    tmp_path: Path,
) -> None:
    """POSITIVE CONTROL — per-entry junk is skipped, the good entry survives.

    Fails if the guard is hoisted from the container to the whole document.
    """
    orch = _write(tmp_path / "orch.json", json.dumps({
        "generated_at": "2026-08-02T06:00:00+00:00",
        "adapters": [
            "not-a-dict",
            {"protocol": "pendle", "status": "ok", "apy_pct": 13.9419,
             "live_data": True},
        ],
    }))
    status = _write(tmp_path / "status.json", json.dumps({
        "generated_at": "2026-08-02T15:01:33+00:00",
        "adapters": {"junk": "not-a-dict",
                     "morpho_steakhouse": {"live_apy": 3.4657}},
    }))

    assert _load_evidenced_apy(orch, status) == {
        "pendle": (pytest.approx(0.139419), "orchestrator_live"),
        "morpho_steakhouse": (pytest.approx(0.034657), "adapter_status_live"),
    }


def test_unparseable_bytes_are_still_refused_the_same_way(tmp_path: Path) -> None:
    """POSITIVE CONTROL — the pre-existing "broken file" path is unchanged."""
    assert _load_evidenced_apy(
        _write(tmp_path / "orch.json", "{not json at all"),
        _write(tmp_path / "status.json", "{"),
    ) == {}


def test_absent_files_are_still_refused_the_same_way(tmp_path: Path) -> None:
    """POSITIVE CONTROL — mirrors ``test_unreadable_evidence_source_never_raises``."""
    assert _load_evidenced_apy(tmp_path / "nope.json", tmp_path / "also-nope.json") == {}


# ── the reason must stay visible, not be swallowed as "no evidence" ────────


def test_the_refusal_names_the_actual_type_it_saw(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A silent ``{}`` would read as "the producers observed nothing".

    The distinction between "nothing was observed" and "the file is the wrong
    shape" has to survive into the log, or the refusal is indistinguishable
    from a quiet world (the class of defects behind #29/#31/#35–#38).
    """
    with caplog.at_level("WARNING"):
        _load_evidenced_apy(
            _write(tmp_path / "orch.json", "[]"),
            _write(tmp_path / "status.json", json.dumps({"adapters": [1, 2]})),
        )

    text = caplog.text
    assert "list" in text, "the type actually seen is not quoted verbatim"
    assert "orch.json" in text and "status.json" in text, "the source is not named"
