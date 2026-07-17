"""Regression coverage for ``spa_core/utils/atomic.py`` — the implementation of **invariant #5**
("атомарные записи: tmp в той же директории + ``os.replace``, никогда прямой ``open(..., 'w')``
на state-файлы"). Every state file in the system is written through these helpers: ``atomic_save``
alone is imported by ~657 files, including the paper-trading cycle, the allocator, and every
monitoring/analytics writer.

The blast radius of a silent regression here is the whole ``data/`` tree. The properties that make
these helpers *atomic* are exactly the ones nothing else pins:

* the temp file is created **in the same directory** as the destination — ``os.replace`` is only
  atomic within one filesystem (a cross-device rename raises ``EXDEV``), so a "tidier" ``dir=/tmp``
  would silently downgrade every write in the system to non-atomic;
* a crash **mid-write leaves the previous file intact** and drops no ``.tmp`` orphan — that is the
  entire point of the tmp+replace dance, and a partially-written ``data/`` state file is precisely
  what invariant #5 exists to prevent.

On origin the only dedicated test file (``test_atomic_junk_path_guard.py``) covers just the
repr-junk path guard on ``atomic_save`` / ``atomic_save_text``; ``atomic_load``, ``atomic_append``,
``atomic_append_ring``, ``atomic_write_via_tmp`` and ``atomic_update`` had **no dedicated coverage
at all**, and ``atomic_save``'s atomicity contract itself was never asserted. This file pins that
surface. The junk-path guard is deliberately *not* re-tested here (it is well covered next door).

Hermetic & offline: every path used is under ``tmp_path``. No file in the real ``data/`` tree — and
in particular the live go-live track — is read or written by any test in this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spa_core.utils import atomic as atomic_mod
from spa_core.utils.atomic import (
    atomic_append,
    atomic_append_ring,
    atomic_load,
    atomic_save,
    atomic_save_text,
    atomic_update,
    atomic_write_via_tmp,
)


def _tmp_leftovers(directory: Path) -> list[str]:
    """Every ``*.tmp`` orphan left behind in *directory* (there must never be any)."""
    return sorted(p.name for p in Path(directory).iterdir() if p.name.endswith(".tmp"))


# ---------------------------------------------------------------------------
# atomic_save — the core write path of invariant #5
# ---------------------------------------------------------------------------


class TestAtomicSave:
    def test_round_trip(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"a": 1, "b": [1, 2]}, str(target))
        assert json.loads(target.read_text()) == {"a": 1, "b": [1, 2]}

    def test_creates_missing_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "state.json"
        atomic_save({"ok": True}, str(target))
        assert json.loads(target.read_text()) == {"ok": True}

    def test_overwrites_existing_file_completely(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"old": "much longer previous content" * 10}, str(target))
        atomic_save({"new": 1}, str(target))
        # os.replace swaps the whole inode: no remnant of the longer old payload.
        assert json.loads(target.read_text()) == {"new": 1}

    def test_leaves_no_tmp_orphan_on_success(self, tmp_path: Path) -> None:
        atomic_save({"a": 1}, str(tmp_path / "state.json"))
        assert _tmp_leftovers(tmp_path) == []

    def test_tmp_is_created_in_the_destination_directory(self, tmp_path: Path, monkeypatch) -> None:
        """Invariant #5: tmp must live in the SAME directory as the destination.

        ``os.replace`` is atomic only within a single filesystem. If the tmp file were created in
        the system temp dir (a different device on many setups), the rename would either raise
        ``EXDEV`` or degrade into a non-atomic copy — silently breaking every state write.
        """
        target = tmp_path / "sub" / "state.json"
        seen: list[str] = []
        real_mkstemp = atomic_mod.tempfile.mkstemp

        def spy(*args, **kwargs):
            seen.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(atomic_mod.tempfile, "mkstemp", spy)
        atomic_save({"a": 1}, str(target))

        assert seen == [str(target.parent)]
        assert os.path.dirname(os.path.abspath(str(target))) == seen[0]

    def test_publishes_via_os_replace_not_in_place_write(self, tmp_path: Path, monkeypatch) -> None:
        """The destination must be published by a rename, never by writing into it directly."""
        target = tmp_path / "state.json"
        calls: list[tuple[str, str]] = []
        real_replace = atomic_mod.os.replace

        def spy(src, dst):
            calls.append((str(src), str(dst)))
            return real_replace(src, dst)

        monkeypatch.setattr(atomic_mod.os, "replace", spy)
        atomic_save({"a": 1}, str(target))

        assert len(calls) == 1
        src, dst = calls[0]
        assert dst == str(target)
        assert src.endswith(".tmp") and os.path.dirname(src) == str(tmp_path)

    def test_crash_mid_write_keeps_previous_file_and_drops_no_orphan(self, tmp_path: Path) -> None:
        """THE atomicity guarantee: a failed write must not corrupt the existing state file.

        A self-referencing dict makes ``json.dump`` raise *after* it has already streamed bytes
        into the tmp file — the exact "partial write" scenario. The destination must still hold
        the previous, complete payload, and the half-written tmp must be cleaned up.
        """
        target = tmp_path / "state.json"
        atomic_save({"good": "previous"}, str(target))

        circular: dict = {"payload": "x" * 5000}
        circular["self"] = circular
        with pytest.raises(ValueError):
            atomic_save(circular, str(target))

        assert json.loads(target.read_text()) == {"good": "previous"}
        assert _tmp_leftovers(tmp_path) == []

    def test_crash_on_first_ever_write_creates_no_file_and_no_orphan(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        circular: dict = {}
        circular["self"] = circular
        with pytest.raises(ValueError):
            atomic_save(circular, str(target))

        assert not target.exists()
        assert _tmp_leftovers(tmp_path) == []

    def test_non_serializable_values_fall_back_to_str(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"path": Path("/x/y"), "s": {1, 2}}, str(target))
        loaded = json.loads(target.read_text())
        assert loaded["path"] == "/x/y"
        assert isinstance(loaded["s"], str)

    def test_indent_is_honoured(self, tmp_path: Path) -> None:
        flat = tmp_path / "flat.json"
        pretty = tmp_path / "pretty.json"
        atomic_save({"a": 1}, str(flat), indent=None)
        atomic_save({"a": 1}, str(pretty), indent=2)
        assert "\n" not in flat.read_text().strip()
        assert "\n" in pretty.read_text().strip()

    def test_pathlike_destination_is_accepted(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"a": 1}, target)  # type: ignore[arg-type]  # PathLike accepted by the guard
        assert json.loads(target.read_text()) == {"a": 1}

    def test_relative_path_resolves_against_cwd(self, tmp_path: Path, monkeypatch) -> None:
        """A bare filename has no dirname; the helper must still resolve a real directory."""
        monkeypatch.chdir(tmp_path)
        atomic_save({"a": 1}, "relative.json")
        assert json.loads((tmp_path / "relative.json").read_text()) == {"a": 1}
        assert _tmp_leftovers(tmp_path) == []


# ---------------------------------------------------------------------------
# atomic_load — the _MISSING sentinel contract
# ---------------------------------------------------------------------------


class TestAtomicLoad:
    def test_missing_file_without_default_returns_empty_dict(self, tmp_path: Path) -> None:
        assert atomic_load(str(tmp_path / "nope.json")) == {}

    def test_missing_file_with_explicit_none_returns_none_not_empty_dict(self, tmp_path: Path) -> None:
        """The ``_MISSING`` sentinel exists precisely to keep these two cases apart.

        Collapsing the signature to ``default=None`` would make an explicit ``default=None``
        indistinguishable from "no default" and hand callers ``{}`` where they asked for ``None``.
        """
        assert atomic_load(str(tmp_path / "nope.json"), default=None) is None

    @pytest.mark.parametrize("default", [[], {"seed": 1}, 0, "", False])
    def test_missing_file_returns_falsy_defaults_verbatim(self, tmp_path: Path, default) -> None:
        assert atomic_load(str(tmp_path / "nope.json"), default=default) == default

    def test_existing_file_wins_over_default(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text(json.dumps({"real": 1}))
        assert atomic_load(str(target), default={"seed": 2}) == {"real": 1}

    def test_corrupt_json_raises_rather_than_silently_returning_default(self, tmp_path: Path) -> None:
        """Fail-CLOSED (invariant #2): a truncated state file must surface, not read as empty.

        Swallowing the decode error here would let a corrupt ``data/`` file masquerade as a fresh
        one and be silently overwritten by the next save.
        """
        target = tmp_path / "state.json"
        target.write_text('{"a": 1')  # truncated
        with pytest.raises(json.JSONDecodeError):
            atomic_load(str(target), default={})

    def test_round_trip_with_atomic_save_handles_unicode(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"владелец": "Юрий"}, str(target))
        assert atomic_load(str(target)) == {"владелец": "Юрий"}


# ---------------------------------------------------------------------------
# atomic_append
# ---------------------------------------------------------------------------


class TestAtomicAppend:
    def test_creates_file_with_seeded_list(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        atomic_append({"i": 1}, str(target))
        assert json.loads(target.read_text()) == {"items": [{"i": 1}]}

    def test_appends_in_order(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        for i in range(3):
            atomic_append({"i": i}, str(target))
        assert json.loads(target.read_text())["items"] == [{"i": 0}, {"i": 1}, {"i": 2}]

    def test_custom_key(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        atomic_append({"i": 1}, str(target), key="events")
        assert json.loads(target.read_text()) == {"events": [{"i": 1}]}

    def test_cap_keeps_the_newest_entries(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        for i in range(5):
            atomic_append(i, str(target), cap=3)
        assert json.loads(target.read_text())["items"] == [2, 3, 4]

    def test_cap_none_is_unbounded(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        for i in range(4):
            atomic_append(i, str(target), cap=None)
        assert json.loads(target.read_text())["items"] == [0, 1, 2, 3]

    def test_sibling_keys_are_preserved(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        target.write_text(json.dumps({"items": [1], "meta": {"v": "1.0"}}))
        atomic_append(2, str(target))
        data = json.loads(target.read_text())
        assert data["items"] == [1, 2]
        assert data["meta"] == {"v": "1.0"}

    def test_existing_file_without_the_key_gets_it_seeded(self, tmp_path: Path) -> None:
        target = tmp_path / "log.json"
        target.write_text(json.dumps({"meta": 1}))
        atomic_append("x", str(target))
        assert json.loads(target.read_text()) == {"meta": 1, "items": ["x"]}

    def test_corrupt_file_raises_rather_than_dropping_history(self, tmp_path: Path) -> None:
        """Unlike ``atomic_append_ring``, this helper does not reset a corrupt file — it fails
        closed, so a damaged log is never silently replaced by a one-entry file."""
        target = tmp_path / "log.json"
        target.write_text("{not json")
        with pytest.raises(json.JSONDecodeError):
            atomic_append(1, str(target))


# ---------------------------------------------------------------------------
# atomic_append_ring — two storage formats
# ---------------------------------------------------------------------------


class TestAtomicAppendRing:
    def test_bare_array_format(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        assert atomic_append_ring({"i": 1}, str(target)) == 1
        assert json.loads(target.read_text()) == [{"i": 1}]

    def test_keyed_format(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        assert atomic_append_ring({"i": 1}, str(target), list_key="events") == 1
        assert json.loads(target.read_text()) == {"events": [{"i": 1}]}

    def test_keyed_format_preserves_extra_keys(self, tmp_path: Path) -> None:
        """Documented contract: ``{"k": [...], ...}`` — the sibling metadata must survive."""
        target = tmp_path / "ring.json"
        target.write_text(json.dumps({"events": [1], "updated_at": "yesterday", "v": 2}))
        atomic_append_ring(2, str(target), list_key="events")
        data = json.loads(target.read_text())
        assert data["events"] == [1, 2]
        assert data["updated_at"] == "yesterday"
        assert data["v"] == 2

    def test_returns_new_length_and_caps_at_cap(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        lengths = [atomic_append_ring(i, str(target), cap=3) for i in range(5)]
        assert lengths == [1, 2, 3, 3, 3]
        assert json.loads(target.read_text()) == [2, 3, 4]

    def test_keyed_cap_keeps_newest(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        for i in range(5):
            atomic_append_ring(i, str(target), cap=2, list_key="e")
        assert json.loads(target.read_text())["e"] == [3, 4]

    def test_default_cap_is_100(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        target.write_text(json.dumps(list(range(100))))
        assert atomic_append_ring("new", str(target)) == 100
        ring = json.loads(target.read_text())
        assert len(ring) == 100
        assert ring[0] == 1 and ring[-1] == "new"

    def test_corrupt_array_file_resets_instead_of_raising(self, tmp_path: Path) -> None:
        """A ring buffer is disposable telemetry: it self-heals rather than blocking the writer."""
        target = tmp_path / "ring.json"
        target.write_text("{{{ not json")
        assert atomic_append_ring("x", str(target)) == 1
        assert json.loads(target.read_text()) == ["x"]

    def test_non_list_array_file_resets(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        target.write_text(json.dumps({"unexpected": "dict"}))
        assert atomic_append_ring("x", str(target)) == 1
        assert json.loads(target.read_text()) == ["x"]

    def test_non_dict_file_with_list_key_resets(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        target.write_text(json.dumps(["bare", "array"]))
        assert atomic_append_ring("x", str(target), list_key="e") == 1
        assert json.loads(target.read_text()) == {"e": ["x"]}

    def test_non_list_value_at_list_key_resets(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        target.write_text(json.dumps({"e": "not-a-list", "keep": 1}))
        assert atomic_append_ring("x", str(target), list_key="e") == 1
        data = json.loads(target.read_text())
        assert data["e"] == ["x"]
        assert data["keep"] == 1

    def test_corrupt_keyed_file_resets(self, tmp_path: Path) -> None:
        target = tmp_path / "ring.json"
        target.write_text("not json at all {")
        assert atomic_append_ring("x", str(target), list_key="e") == 1
        assert json.loads(target.read_text()) == {"e": ["x"]}


# ---------------------------------------------------------------------------
# atomic_save_text
# ---------------------------------------------------------------------------


class TestAtomicSaveText:
    def test_round_trip_and_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "reports" / "tear_sheet.md"
        atomic_save_text("# Tear sheet\n", str(target))
        assert target.read_text() == "# Tear sheet\n"

    def test_leaves_no_tmp_orphan(self, tmp_path: Path) -> None:
        atomic_save_text("x", str(tmp_path / "a.md"))
        assert _tmp_leftovers(tmp_path) == []

    def test_tmp_is_created_in_the_destination_directory(self, tmp_path: Path, monkeypatch) -> None:
        target = tmp_path / "sub" / "a.md"
        seen: list[str] = []
        real_mkstemp = atomic_mod.tempfile.mkstemp

        def spy(*args, **kwargs):
            seen.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        monkeypatch.setattr(atomic_mod.tempfile, "mkstemp", spy)
        atomic_save_text("x", str(target))
        assert seen == [str(target.parent)]

    def test_encoding_is_honoured(self, tmp_path: Path) -> None:
        target = tmp_path / "a.md"
        atomic_save_text("Юрий", str(target), encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "Юрий"

    def test_fsync_false_still_writes(self, tmp_path: Path) -> None:
        target = tmp_path / "a.md"
        atomic_save_text("x", str(target), fsync=False)
        assert target.read_text() == "x"

    def test_fsync_true_by_default_flushes_before_rename(self, tmp_path: Path, monkeypatch) -> None:
        calls: list[int] = []
        real_fsync = atomic_mod.os.fsync
        monkeypatch.setattr(atomic_mod.os, "fsync", lambda fd: (calls.append(fd), real_fsync(fd))[1])
        atomic_save_text("x", str(tmp_path / "a.md"))
        assert len(calls) == 1

    def test_encoding_failure_keeps_previous_file_and_drops_no_orphan(self, tmp_path: Path) -> None:
        target = tmp_path / "a.md"
        atomic_save_text("previous", str(target))
        with pytest.raises(UnicodeEncodeError):
            atomic_save_text("Юрий", str(target), encoding="ascii")
        assert target.read_text() == "previous"
        assert _tmp_leftovers(tmp_path) == []


# ---------------------------------------------------------------------------
# atomic_write_via_tmp — context manager for binary / external writers
# ---------------------------------------------------------------------------


class TestAtomicWriteViaTmp:
    def test_yields_tmp_in_destination_dir_and_renames_on_clean_exit(self, tmp_path: Path) -> None:
        target = tmp_path / "out" / "report.pdf"
        with atomic_write_via_tmp(str(target)) as tmp:
            assert tmp.parent == target.parent  # same-filesystem rename (invariant #5)
            assert target.parent.exists()
            tmp.write_bytes(b"%PDF-1.4 binary")
            assert not target.exists()  # not published until the block exits
        assert target.read_bytes() == b"%PDF-1.4 binary"
        assert not tmp.exists()
        assert _tmp_leftovers(target.parent) == []

    def test_exception_cleans_tmp_keeps_previous_file_and_reraises(self, tmp_path: Path) -> None:
        target = tmp_path / "report.pdf"
        target.write_bytes(b"previous")
        captured: dict = {}
        with pytest.raises(RuntimeError, match="writer blew up"):
            with atomic_write_via_tmp(str(target)) as tmp:
                captured["tmp"] = tmp
                tmp.write_bytes(b"half-written")
                raise RuntimeError("writer blew up")

        assert target.read_bytes() == b"previous"
        assert not captured["tmp"].exists()
        assert _tmp_leftovers(tmp_path) == []

    def test_pathlike_destination_is_accepted(self, tmp_path: Path) -> None:
        target = tmp_path / "report.bin"
        with atomic_write_via_tmp(target) as tmp:  # type: ignore[arg-type]
            tmp.write_bytes(b"ok")
        assert target.read_bytes() == b"ok"

    def test_writer_that_never_writes_publishes_empty_file(self, tmp_path: Path) -> None:
        """mkstemp already created the tmp file, so a no-op writer publishes an empty destination
        rather than raising — pinned so the behaviour is a choice, not a surprise."""
        target = tmp_path / "report.bin"
        with atomic_write_via_tmp(str(target)):
            pass
        assert target.exists()
        assert target.read_bytes() == b""


# ---------------------------------------------------------------------------
# atomic_update — read-modify-write
# ---------------------------------------------------------------------------


class TestAtomicUpdate:
    def test_documented_example_works_on_a_missing_file(self, tmp_path: Path) -> None:
        """The docstring's own example — ``lambda d: {**d, "count": d.get("count", 0) + 1}`` — must
        work on a missing file, since the documented contract is "Seed value ... (default: {})".

        This was RED before the fix in this cycle: the default seed was a literal ``None``, so
        ``atomic_load`` returned ``None`` (its ``_MISSING`` sentinel keeps explicit-``None`` apart
        from "no default"), and the documented example died with
        ``TypeError: 'NoneType' object is not a mapping``.
        """
        target = tmp_path / "state.json"
        result = atomic_update(str(target), lambda d: {**d, "count": d.get("count", 0) + 1})
        assert result == {"count": 1}
        assert json.loads(target.read_text()) == {"count": 1}

    def test_read_modify_write_on_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"count": 4, "keep": "me"}, str(target))
        result = atomic_update(str(target), lambda d: {**d, "count": d["count"] + 1})
        assert result == {"count": 5, "keep": "me"}
        assert json.loads(target.read_text()) == {"count": 5, "keep": "me"}

    def test_repeated_updates_accumulate(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        for _ in range(3):
            atomic_update(str(target), lambda d: {**d, "n": d.get("n", 0) + 1})
        assert json.loads(target.read_text()) == {"n": 3}

    def test_explicit_default_seeds_a_missing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        result = atomic_update(str(target), lambda d: d + [1], default=[])
        assert result == [1]
        assert json.loads(target.read_text()) == [1]

    def test_explicit_none_default_is_still_passed_through(self, tmp_path: Path) -> None:
        """An explicit ``default=None`` must keep reaching ``update_fn`` — callers use it to tell
        "file absent" apart from "file holds an empty dict"."""
        target = tmp_path / "state.json"
        seen: list = []
        result = atomic_update(str(target), lambda d: (seen.append(d), {"seeded": True})[1], default=None)
        assert seen == [None]
        assert result == {"seeded": True}

    def test_failing_update_fn_leaves_the_file_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        atomic_save({"count": 1}, str(target))

        def boom(_):
            raise RuntimeError("update failed")

        with pytest.raises(RuntimeError, match="update failed"):
            atomic_update(str(target), boom)
        assert json.loads(target.read_text()) == {"count": 1}
        assert _tmp_leftovers(tmp_path) == []
