"""Tests for spa_core.audit.proof_of_track (MP-406, SPA-V426).

Run with: python3 -m unittest spa_core.tests.test_proof_of_track -v

Чистый unittest (НЕ pytest), БЕЗ сети, вся персистентность — в tempdir.
Покрытие (45+ кейсов):
  - канонизация: детерминизм, порядок ключей, юникод, сепараторы;
  - Merkle-дерево: пустой набор → None, 1 лист, чётное/нечётное число,
    известный фиксированный вектор (hex-константы), правило дублирования;
  - inclusion proofs: валидные проходят, подмена листа/ветки/root — fail,
    дерево из 1 листа, неизвестный лист → None;
  - build_daily_root: фильтрация по дате, архивы, битые строки, пустой день;
  - персист: схема якоря, нет *.tmp, --check не пишет, идемпотентность,
    discrepancy-ветка (старый root не перезаписан), ротация ровно 500,
    битый файл якорей толерантен;
  - CLI: --check/--run ×2/--verify — exit 0, пустые данные без трейсбека;
  - гигиена: в модуле нет импортов LLM SDK / web3 / requests.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.audit import proof_of_track as pot

DATE = "2026-06-11"
OTHER_DATE = "2026-06-10"

# ─── Известный фиксированный вектор (правила 1–4 из докстринга модуля) ───────
# Листья = sha256("a"/"b"/"c"), родитель = sha256(left_hex + right_hex по ASCII),
# нечётный уровень — дублирование последнего. Константы посчитаны независимо.
LEAF_A = "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
LEAF_B = "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d"
LEAF_C = "2e7d2c03a9507ae265ecf5b5356885a53393a2029d241394997265a1a25aefc6"
ROOT_AB = "62af5c3cb8da3e4f25061e829ebeea5c7513c54949115b1acc225930a90154da"
ROOT_ABC = "0bdf27bf7ec894ca7cadfe491ec1a3ece840f117989e8c5e9bd7086467bf6c38"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _make_event(i: int, date: str = DATE, **extra) -> dict:
    ev = {
        "event_id": f"ev-{date}-{i}",
        "correlation_id": f"corr-{date}",
        "snapshot_id": f"{date}:deadbeef",
        "event_type": "cycle_start",
        "timestamp": f"{date}T0{i % 10}:00:00+00:00",
        "data": {"i": i},
        "prev_event_id": None,
    }
    ev.update(extra)
    return ev


def _write_trail(data_dir: str, events: list, filename: str = pot.AUDIT_FILENAME) -> None:
    path = Path(data_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


class _TmpDirMixin(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="spa_pot_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def anchors_path(self) -> Path:
        return Path(self.tmp) / pot.ANCHORS_FILENAME

    def assert_no_tmp_files(self) -> None:
        leftovers = list(Path(self.tmp).glob("*.tmp")) + list(Path(self.tmp).glob(".*.tmp"))
        self.assertEqual(leftovers, [], f"осиротевшие tmp-файлы: {leftovers}")


# ─── Канонизация ─────────────────────────────────────────────────────────────


class TestCanonicalization(unittest.TestCase):
    def test_deterministic_across_key_insertion_order(self):
        a = {"b": 2, "a": 1, "nested": {"y": 0, "x": 9}}
        b = {"nested": {"x": 9, "y": 0}, "a": 1, "b": 2}
        self.assertEqual(pot.canonicalize_event(a), pot.canonicalize_event(b))

    def test_keys_sorted(self):
        s = pot.canonicalize_event({"z": 1, "a": 2})
        self.assertEqual(s, '{"a":2,"z":1}')

    def test_compact_separators(self):
        s = pot.canonicalize_event({"a": [1, 2], "b": {"c": 3}})
        self.assertNotIn(" ", s)
        self.assertEqual(s, '{"a":[1,2],"b":{"c":3}}')

    def test_unicode_preserved_not_escaped(self):
        s = pot.canonicalize_event({"тест": "юникод"})
        self.assertIn("тест", s)
        self.assertIn("юникод", s)
        self.assertNotIn("\\u", s)

    def test_known_canonical_vector(self):
        ev = {"event_id": "e1", "correlation_id": "c1",
              "data": {"x": 1, "тест": "юникод"}}
        self.assertEqual(
            pot.canonicalize_event(ev),
            '{"correlation_id":"c1","data":{"x":1,"тест":"юникод"},"event_id":"e1"}',
        )
        self.assertEqual(
            pot.leaf_hash(ev),
            "0fbfb756f8b68bb5052151b1ad79f43b27e57a76b69fb2df8395d59ecfdbba24",
        )

    def test_leaf_hash_is_64_hex(self):
        h = pot.leaf_hash({"a": 1})
        self.assertEqual(len(h), 64)
        int(h, 16)  # валидный hex — не бросает

    def test_leaf_hash_deterministic_and_distinct(self):
        self.assertEqual(pot.leaf_hash({"a": 1}), pot.leaf_hash({"a": 1}))
        self.assertNotEqual(pot.leaf_hash({"a": 1}), pot.leaf_hash({"a": 2}))

    def test_canonicalize_includes_event_and_correlation_ids(self):
        ev = _make_event(1)
        s = pot.canonicalize_event(ev)
        self.assertIn(ev["event_id"], s)
        self.assertIn(ev["correlation_id"], s)

    def test_non_serializable_raises_typeerror(self):
        with self.assertRaises(TypeError):
            pot.canonicalize_event({"bad": {1, 2}})


# ─── Merkle-дерево ───────────────────────────────────────────────────────────


class TestMerkleTree(unittest.TestCase):
    def test_empty_leaves_root_is_none(self):
        self.assertIsNone(pot.merkle_root([]))
        self.assertEqual(pot.merkle_levels([]), [])

    def test_single_leaf_root_is_leaf(self):
        self.assertEqual(pot.merkle_root([LEAF_A]), LEAF_A)

    def test_two_leaves_fixed_vector(self):
        self.assertEqual(pot.merkle_root([LEAF_A, LEAF_B]), ROOT_AB)

    def test_three_leaves_fixed_vector_odd_duplication(self):
        self.assertEqual(pot.merkle_root([LEAF_A, LEAF_B, LEAF_C]), ROOT_ABC)

    def test_odd_rule_equals_explicit_duplicate(self):
        # [a, b, c] должно хэшироваться ровно как [a, b, c, c]
        self.assertEqual(
            pot.merkle_root([LEAF_A, LEAF_B, LEAF_C]),
            pot.merkle_root([LEAF_A, LEAF_B, LEAF_C, LEAF_C]),
        )

    def test_four_leaves_manual_recomputation(self):
        leaves = [_sha(x) for x in ("w", "x", "y", "z")]
        n1 = hashlib.sha256((leaves[0] + leaves[1]).encode("ascii")).hexdigest()
        n2 = hashlib.sha256((leaves[2] + leaves[3]).encode("ascii")).hexdigest()
        expected = hashlib.sha256((n1 + n2).encode("ascii")).hexdigest()
        self.assertEqual(pot.merkle_root(leaves), expected)

    def test_root_depends_on_leaf_order(self):
        self.assertNotEqual(
            pot.merkle_root([LEAF_A, LEAF_B]), pot.merkle_root([LEAF_B, LEAF_A])
        )

    def test_root_deterministic(self):
        leaves = [_sha(str(i)) for i in range(7)]
        self.assertEqual(pot.merkle_root(leaves), pot.merkle_root(list(leaves)))

    def test_levels_shape(self):
        leaves = [_sha(str(i)) for i in range(5)]
        levels = pot.merkle_levels(leaves)
        self.assertEqual(levels[0], leaves)
        self.assertEqual(len(levels[-1]), 1)
        self.assertEqual(pot.merkle_root(leaves), levels[-1][0])

    def test_merkle_levels_does_not_mutate_input(self):
        leaves = [LEAF_A, LEAF_B, LEAF_C]
        snapshot = list(leaves)
        pot.merkle_levels(leaves)
        self.assertEqual(leaves, snapshot)


# ─── Inclusion proofs ────────────────────────────────────────────────────────


class TestProofs(unittest.TestCase):
    def setUp(self) -> None:
        self.leaves = [_sha(str(i)) for i in range(5)]  # нечётное дерево
        self.root = pot.merkle_root(self.leaves)

    def test_valid_proof_verifies_for_every_leaf(self):
        for leaf in self.leaves:
            proof = pot.generate_proof(leaf, self.leaves)
            self.assertIsNotNone(proof)
            self.assertTrue(pot.verify_proof(leaf, proof, self.root),
                            f"proof не прошёл для листа {leaf}")

    def test_even_tree_proofs_verify(self):
        leaves = [_sha(str(i)) for i in range(4)]
        root = pot.merkle_root(leaves)
        for leaf in leaves:
            self.assertTrue(pot.verify_proof(leaf, pot.generate_proof(leaf, leaves), root))

    def test_tampered_leaf_fails(self):
        proof = pot.generate_proof(self.leaves[0], self.leaves)
        self.assertFalse(pot.verify_proof(_sha("tampered"), proof, self.root))

    def test_tampered_branch_fails(self):
        proof = pot.generate_proof(self.leaves[1], self.leaves)
        proof[0]["hash"] = _sha("evil-sibling")
        self.assertFalse(pot.verify_proof(self.leaves[1], proof, self.root))

    def test_tampered_position_fails(self):
        proof = pot.generate_proof(self.leaves[1], self.leaves)
        proof[0]["position"] = "left" if proof[0]["position"] == "right" else "right"
        self.assertFalse(pot.verify_proof(self.leaves[1], proof, self.root))

    def test_wrong_root_fails(self):
        proof = pot.generate_proof(self.leaves[2], self.leaves)
        self.assertFalse(pot.verify_proof(self.leaves[2], proof, _sha("wrong-root")))

    def test_single_leaf_tree_empty_proof(self):
        proof = pot.generate_proof(LEAF_A, [LEAF_A])
        self.assertEqual(proof, [])
        self.assertTrue(pot.verify_proof(LEAF_A, [], LEAF_A))

    def test_empty_proof_against_mismatching_root_fails(self):
        self.assertFalse(pot.verify_proof(LEAF_A, [], LEAF_B))

    def test_unknown_leaf_proof_is_none(self):
        self.assertIsNone(pot.generate_proof(_sha("ghost"), self.leaves))

    def test_proof_steps_count_matches_tree_height(self):
        proof = pot.generate_proof(self.leaves[0], self.leaves)
        # 5 листьев → 5→3(падд 6)→2→1: 3 шага
        self.assertEqual(len(proof), 3)

    def test_verify_none_root_false(self):
        proof = pot.generate_proof(self.leaves[0], self.leaves)
        self.assertFalse(pot.verify_proof(self.leaves[0], proof, None))

    def test_verify_garbage_inputs_false_no_raise(self):
        self.assertFalse(pot.verify_proof("", [], self.root))
        self.assertFalse(pot.verify_proof(self.leaves[0], "not-a-list", self.root))
        self.assertFalse(pot.verify_proof(self.leaves[0], ["not-a-dict"], self.root))
        self.assertFalse(pot.verify_proof(
            self.leaves[0], [{"position": "up", "hash": LEAF_A}], self.root))
        self.assertFalse(pot.verify_proof(
            self.leaves[0], [{"position": "left", "hash": 42}], self.root))


# ─── build_daily_root поверх audit trail ─────────────────────────────────────


class TestBuildDailyRoot(_TmpDirMixin):
    def test_empty_day_honest_none(self):
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertIsNone(result["merkle_root"])
        self.assertEqual(result["leaf_count"], 0)
        self.assertEqual(result["leaves"], [])

    def test_missing_trail_file_tolerated(self):
        # ни одного файла трека — не исключение, а пустой день
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertIsNone(result["merkle_root"])

    def test_filters_by_date(self):
        _write_trail(self.tmp, [_make_event(1), _make_event(2, OTHER_DATE), _make_event(3)])
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertEqual(result["leaf_count"], 2)
        other = pot.build_daily_root(OTHER_DATE, data_dir=self.tmp)
        self.assertEqual(other["leaf_count"], 1)

    def test_root_matches_manual_leaf_hashes(self):
        events = [_make_event(i) for i in range(3)]
        _write_trail(self.tmp, events)
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        expected_leaves = [pot.leaf_hash(ev) for ev in events]
        self.assertEqual(result["leaves"], expected_leaves)
        self.assertEqual(result["merkle_root"], pot.merkle_root(expected_leaves))

    def test_broken_lines_and_non_dicts_skipped(self):
        path = Path(self.tmp) / pot.AUDIT_FILENAME
        with path.open("w", encoding="utf-8") as fh:
            fh.write("{broken json\n")
            fh.write("\n")
            fh.write(json.dumps(["list", "not", "dict"]) + "\n")
            fh.write(json.dumps(_make_event(1)) + "\n")
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertEqual(result["leaf_count"], 1)

    def test_events_without_timestamp_skipped(self):
        ev = _make_event(1)
        del ev["timestamp"]
        _write_trail(self.tmp, [ev, _make_event(2)])
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertEqual(result["leaf_count"], 1)

    def test_rotated_archives_included_before_current(self):
        archived = _make_event(1)
        current = _make_event(2)
        _write_trail(self.tmp, [archived], filename="audit_trail_20260611T010101Z.jsonl")
        _write_trail(self.tmp, [current])
        result = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertEqual(result["leaf_count"], 2)
        self.assertEqual(result["leaves"][0], pot.leaf_hash(archived))
        self.assertEqual(result["leaves"][1], pot.leaf_hash(current))

    def test_deterministic_across_calls(self):
        _write_trail(self.tmp, [_make_event(i) for i in range(4)])
        r1 = pot.build_daily_root(DATE, data_dir=self.tmp)
        r2 = pot.build_daily_root(DATE, data_dir=self.tmp)
        self.assertEqual(r1, r2)

    def test_invalid_date_raises_valueerror(self):
        with self.assertRaises(ValueError):
            pot.build_daily_root("11-06-2026", data_dir=self.tmp)
        with self.assertRaises(ValueError):
            pot.build_daily_root("not-a-date", data_dir=self.tmp)


# ─── Персистентная очередь якорей ────────────────────────────────────────────


class TestAnchorPersistence(_TmpDirMixin):
    def test_run_creates_anchor_with_full_schema(self):
        _write_trail(self.tmp, [_make_event(1), _make_event(2)])
        outcome = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        self.assertEqual(outcome["status"], "anchored")
        state = json.loads(self.anchors_path().read_text(encoding="utf-8"))
        self.assertEqual(len(state["anchors"]), 1)
        anchor = state["anchors"][0]
        for key in ("date", "merkle_root", "leaf_count", "computed_at",
                    "published", "tx_hash", "note"):
            self.assertIn(key, anchor)
        self.assertEqual(anchor["date"], DATE)
        self.assertEqual(anchor["leaf_count"], 2)
        self.assertIs(anchor["published"], False)
        self.assertIsNone(anchor["tx_hash"])
        self.assertEqual(anchor["note"], pot.PENDING_NOTE)
        self.assertIn("MP-017", anchor["note"])

    def test_no_tmp_files_left_behind(self):
        _write_trail(self.tmp, [_make_event(1)])
        pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        self.assert_no_tmp_files()

    def test_empty_day_anchored_with_none_root(self):
        outcome = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        self.assertEqual(outcome["status"], "anchored")
        anchor = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"][0]
        self.assertIsNone(anchor["merkle_root"])
        self.assertEqual(anchor["leaf_count"], 0)

    def test_idempotent_rerun_no_duplicate_no_change(self):
        _write_trail(self.tmp, [_make_event(1)])
        first = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        before = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"]
        second = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        after = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"]
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(len(after), 1)
        self.assertEqual(before, after)  # запись байт-в-байт не изменилась
        self.assertEqual(first["anchor"]["merkle_root"], second["anchor"]["merkle_root"])

    def test_discrepancy_keeps_old_root_and_notes_it(self):
        _write_trail(self.tmp, [_make_event(1)])
        pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        old_root = json.loads(
            self.anchors_path().read_text(encoding="utf-8"))["anchors"][0]["merkle_root"]
        # «переписываем историю»: добавляем событие задним числом
        _write_trail(self.tmp, [_make_event(2)])
        outcome = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        self.assertEqual(outcome["status"], "discrepancy")
        anchor = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"][0]
        self.assertEqual(anchor["merkle_root"], old_root)  # root НЕ перезаписан
        self.assertNotEqual(outcome["computed_root"], old_root)
        self.assertIn("discrepancy", anchor["note"])
        self.assertIn(outcome["computed_root"], anchor["note"])

    def test_discrepancy_note_not_duplicated_on_rerun(self):
        _write_trail(self.tmp, [_make_event(1)])
        pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        _write_trail(self.tmp, [_make_event(2)])
        pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        note1 = json.loads(
            self.anchors_path().read_text(encoding="utf-8"))["anchors"][0]["note"]
        pot.persist_daily_anchor(DATE, data_dir=self.tmp)  # тот же конфликтующий root
        note2 = json.loads(
            self.anchors_path().read_text(encoding="utf-8"))["anchors"][0]["note"]
        self.assertEqual(note1.count("discrepancy"), 1)
        self.assertEqual(note2.count("discrepancy"), 1)

    def test_multiple_dates_coexist(self):
        _write_trail(self.tmp, [_make_event(1), _make_event(2, OTHER_DATE)])
        pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        pot.persist_daily_anchor(OTHER_DATE, data_dir=self.tmp)
        anchors = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"]
        self.assertEqual({a["date"] for a in anchors}, {DATE, OTHER_DATE})

    def test_rotation_capped_at_exactly_500_newest_kept(self):
        # префилл 600 синтетических якорей
        prefill = [
            {"date": f"2020-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}-{i}",
             "merkle_root": _sha(str(i)), "leaf_count": 1,
             "computed_at": "2020-01-01T00:00:00+00:00",
             "published": False, "tx_hash": None, "note": pot.PENDING_NOTE}
            for i in range(600)
        ]
        pot._atomic_write_json(self.anchors_path(),
                               {"schema_version": 1, "anchors": prefill})
        outcome = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        self.assertEqual(outcome["status"], "anchored")
        anchors = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"]
        self.assertEqual(len(anchors), pot.HISTORY_MAX)
        self.assertEqual(len(anchors), 500)
        self.assertEqual(anchors[-1]["date"], DATE)         # новая запись в хвосте
        self.assertEqual(anchors[0]["date"], prefill[101]["date"])  # старейшие вытеснены

    def test_corrupt_anchors_file_tolerated(self):
        self.anchors_path().write_text("{totally broken", encoding="utf-8")
        outcome = pot.persist_daily_anchor(DATE, data_dir=self.tmp)
        self.assertEqual(outcome["status"], "anchored")
        anchors = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"]
        self.assertEqual(len(anchors), 1)

    def test_non_dict_anchors_state_tolerated(self):
        self.anchors_path().write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        self.assertEqual(pot.load_anchors(data_dir=self.tmp)["anchors"], [])
        self.anchors_path().write_text(json.dumps({"anchors": "oops"}), encoding="utf-8")
        self.assertEqual(pot.load_anchors(data_dir=self.tmp)["anchors"], [])

    def test_non_dict_anchor_entries_dropped(self):
        pot._atomic_write_json(
            self.anchors_path(),
            {"schema_version": 1, "anchors": ["junk", 42, {"date": OTHER_DATE,
             "merkle_root": None, "leaf_count": 0,
             "computed_at": "x", "published": False, "tx_hash": None,
             "note": pot.PENDING_NOTE}]})
        state = pot.load_anchors(data_dir=self.tmp)
        self.assertEqual(len(state["anchors"]), 1)
        self.assertEqual(state["anchors"][0]["date"], OTHER_DATE)

    def test_load_anchors_missing_file_empty(self):
        state = pot.load_anchors(data_dir=self.tmp)
        self.assertEqual(state["anchors"], [])
        self.assertFalse(self.anchors_path().exists())  # load не создаёт файл


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _run_cli(argv: list) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pot.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCLI(_TmpDirMixin):
    def test_check_exit_0_and_writes_nothing(self):
        _write_trail(self.tmp, [_make_event(1)])
        code, out, err = _run_cli(["--check", "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("merkle_root", out)
        self.assertFalse(self.anchors_path().exists(), "--check не должен писать")
        self.assert_no_tmp_files()
        self.assertNotIn("Traceback", out + err)

    def test_run_exit_0_persists(self):
        _write_trail(self.tmp, [_make_event(1)])
        code, out, err = _run_cli(["--run", "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertTrue(self.anchors_path().exists())
        self.assertIn("status=anchored", out)
        self.assertIn("MP-017", out)
        self.assertNotIn("Traceback", out + err)

    def test_run_twice_idempotent_exit_0(self):
        _write_trail(self.tmp, [_make_event(1)])
        code1, _, _ = _run_cli(["--run", "--date", DATE, "--data-dir", self.tmp])
        code2, out2, _ = _run_cli(["--run", "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual((code1, code2), (0, 0))
        self.assertIn("status=unchanged", out2)
        anchors = json.loads(self.anchors_path().read_text(encoding="utf-8"))["anchors"]
        self.assertEqual(len(anchors), 1)
        self.assert_no_tmp_files()

    def test_empty_data_no_traceback(self):
        code, out, err = _run_cli(["--check", "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("None (empty day)", out)
        self.assertNotIn("Traceback", out + err)
        code, out, err = _run_cli(["--run", "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertNotIn("Traceback", out + err)

    def test_default_mode_is_check(self):
        code, out, _ = _run_cli(["--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("read-only", out)
        self.assertFalse(self.anchors_path().exists())

    def test_verify_valid_leaf(self):
        events = [_make_event(i) for i in range(3)]
        _write_trail(self.tmp, events)
        leaf = pot.leaf_hash(events[1])
        code, out, _ = _run_cli(["--verify", leaf, "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("verify=VALID", out)

    def test_verify_unknown_leaf_exit_0(self):
        _write_trail(self.tmp, [_make_event(1)])
        code, out, _ = _run_cli(["--verify", _sha("ghost"),
                                 "--date", DATE, "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("NOT FOUND", out)

    def test_invalid_date_no_traceback_exit_0(self):
        code, out, err = _run_cli(["--check", "--date", "garbage", "--data-dir", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", out + err)


# ─── Гигиена модуля (SPA-BL-011 / LLM_FORBIDDEN) ─────────────────────────────


class TestModuleHygiene(unittest.TestCase):
    SOURCE = Path(pot.__file__).read_text(encoding="utf-8")

    def test_no_llm_sdk_imports(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        violations = find_forbidden_imports(self.SOURCE, "proof_of_track.py")
        self.assertEqual(violations, [])

    def test_no_web3_or_network_imports(self):
        import ast
        tree = ast.parse(self.SOURCE)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                if node.module:
                    imported.add(node.module.split(".")[0])
        for banned in ("web3", "requests", "urllib", "socket", "http",
                       "anthropic", "openai", "langchain", "litellm"):
            self.assertNotIn(banned, imported, f"запрещённый импорт: {banned}")

    def test_only_stdlib_imports(self):
        import ast
        allowed = {"argparse", "hashlib", "json", "os", "sys", "tempfile",
                   "datetime", "pathlib", "typing", "__future__"}
        tree = ast.parse(self.SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertIn(a.name.split(".")[0], allowed)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                self.assertIn(node.module.split(".")[0], allowed)

    def test_pending_note_mentions_mp017(self):
        self.assertIn("MP-017", pot.PENDING_NOTE)
        self.assertEqual(pot.PENDING_NOTE,
                         "on-chain publication pending MP-017 RPC keys")

    def test_history_max_is_500(self):
        self.assertEqual(pot.HISTORY_MAX, 500)


if __name__ == "__main__":
    unittest.main()
