"""Тесты переписи «две сессии на одном предмете» — заказ G38 п. 3 (ADR-413).

Каждый тест здесь — положительный контроль: он краснеет, если сломать ровно то
звено, о котором говорит. Батарея закрывает обе стороны каждого правила
(родня / не родня, квитанция / её отсутствие, загрузка / упоминание) и все
пять третьих исходов прибора.

# FROZEN-DATE-OK: injected-clock — прибор принимает `now=` параметром
# (`measure_receipts(..., now=)`, `run_census(..., now=)`), и каждый тест
# передаёт и фиксированный `now`, и фиксированные отметки записей: обе стороны
# закреплены, календарь на вердикт не влияет.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import duplicate_subject_census as M

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def ts(day: int, hour: int = 12) -> str:
    return f"2026-09-{day:02d}T{hour:02d}:00:00Z"


#: Отметка ЗАВЕДОМО вне тридцатидневного окна относительно :data:`NOW` —
#: фиксированная, как и `now`: обе стороны закреплены.
OLD = "2026-07-01T12:00:00Z"


def rec(*, ts_: str, card: str | None = "inbox-card", pid: int | None = 100,
        start: str | None = "Mon Sep 28 10:00:00 2026", files=(),
        state: str = "claim", summary: str = "работа", dropped=None) -> dict:
    doc: dict = {"ts": ts_, "session": f"cycle-{pid}", "summary": summary,
                 "files": list(files)}
    if card is not None:
        doc["card"] = card
        doc["card_state"] = state
    if pid is not None:
        doc["session_pid"] = pid
    if start is not None:
        doc["session_pid_start"] = start
    if dropped is not None:
        doc["dropped"] = dropped
    return doc


def base(paths, *, committed_at: str = "2026-09-28T00:00:00+00:00") -> dict:
    paths = set(paths)
    return {"measured": True, "reason": None, "ref": "origin/main", "sha": "deadbeef",
            "committed_at": committed_at, "paths": paths,
            "top_level": {p.split("/")[0] for p in paths}}


# ───────────────────────────── предмет и личность ─────────────────────────────

class TestSubjectAndIdentity:
    def test_subject_strips_path_and_extension(self):
        assert M.subject_of({"card": "nimbalyst-local/tracker/inbox-foo.md"}) == "inbox-foo"
        assert M.subject_of({"card": "inbox-foo"}) == "inbox-foo"

    def test_subject_absent_is_none_not_empty_string(self):
        assert M.subject_of({"ts": ts(1)}) is None
        assert M.subject_of({"card": "   "}) is None

    def test_subject_of_wrong_kind_is_absence(self):
        assert M.subject_of({"card": 17}) is None

    def test_anchor_needs_both_halves(self):
        assert M.anchor_of({"session_pid": 7, "session_pid_start": "S"}) == (7, "S")
        assert M.anchor_of({"session_pid": 7}) is None
        assert M.anchor_of({"session_pid_start": "S"}) is None

    def test_label_alone_is_not_an_identity(self):
        """Ярлык `cycle-6648` личностью не является — иначе одна сессия под двумя
        ярлыками изготовила бы столкновение из ФОРМЫ записи, а не из работы."""
        assert M.anchor_of({"session": "cycle-6648"}) is None

    def test_non_int_pid_is_absence(self):
        assert M.anchor_of({"session_pid": "6648", "session_pid_start": "S"}) is None


# ──────────────────────────────── координата ─────────────────────────────────

class TestNormalise:
    TOPS = {"spa_core", "scripts", "docs"}

    def test_worktree_prefix_is_stripped_by_the_tree_not_by_a_guess(self):
        got = M.normalise("/private/tmp/spa_c715/spa_core/monitoring/x.py", self.TOPS)
        assert got == "spa_core/monitoring/x.py"

    def test_unknown_prefix_is_not_normalisable(self):
        assert M.normalise("/tmp/scratch/notes.txt", self.TOPS) is None

    def test_relative_and_dotted_forms(self):
        assert M.normalise("./scripts/a.py", self.TOPS) == "scripts/a.py"
        assert M.normalise("scripts/a.py", self.TOPS) == "scripts/a.py"

    def test_empty_declaration_is_not_a_coordinate(self):
        assert M.normalise("   ", self.TOPS) is None


class TestKin:
    PATHS = {"spa_core/tests/test_tracker_board_matches_cards.py",
             "spa_core/tests/test_tracker_board_reads_origin.py",
             "docs/decisions/ADR-154-contracts-before-orchestration.md",
             "docs/decisions/ADR-467-defensive-tail-binding-three-of-six.md",
             "spa_core/monitoring/other_thing.py"}

    def test_three_shared_tokens_is_kin(self):
        kin = M.kin_of("spa_core/tests/test_tracker_board_composition.py", self.PATHS)
        assert kin == ["spa_core/tests/test_tracker_board_matches_cards.py",
                       "spa_core/tests/test_tracker_board_reads_origin.py"]

    def test_two_shared_tokens_is_not_kin(self):
        """ADR-154 с ДРУГИМ слагом — переиспользованный номер, а не переименование."""
        assert M.kin_of(
            "docs/decisions/ADR-154-unmeasured-origin-sweep-and-board-composition.md",
            self.PATHS) == []

    def test_five_shared_tokens_is_kin(self):
        assert M.kin_of("docs/decisions/ADR-467-defensive-tail-binding.md",
                        self.PATHS) == \
            ["docs/decisions/ADR-467-defensive-tail-binding-three-of-six.md"]

    def test_short_name_needs_every_token(self):
        """Двухтокенное имя: порог опускается до ДВУХ — иначе родня у короткого
        имени недостижима по построению, и переименование было бы неотличимо от
        потери. Нужны ОБЕ стороны, иначе жёсткая тройка неотличима от `min`."""
        # ни одного общего токена сверх первого ⇒ родни нет
        assert M.kin_of("spa_core/monitoring/orphan_runs.py", self.PATHS) == []
        assert M.kin_of("spa_core/monitoring/other_stuff.py",
                        {"spa_core/monitoring/other_thing.py"}) == []
        # ОБА токена общие ⇒ родня ЕСТЬ, хотя их всего два, а не три
        assert M.kin_of("spa_core/monitoring/orphan_runs.py",
                        {"spa_core/monitoring/orphan_runs_v2.py"}) == \
            ["spa_core/monitoring/orphan_runs_v2.py"]

    def test_kin_lives_in_the_same_directory_only(self):
        assert M.kin_of("scripts/test_tracker_board_composition.py", self.PATHS) == []

    def test_a_file_is_not_its_own_kin(self):
        assert M.kin_of("spa_core/tests/test_tracker_board_reads_origin.py",
                        self.PATHS) == ["spa_core/tests/test_tracker_board_matches_cards.py"]


# ──────────────────────────────── журнал ─────────────────────────────────────

class TestJournal:
    def test_missing_journal_is_not_measured(self, tmp_path):
        got = M.load_journal(tmp_path / "nope.jsonl")
        assert got["measured"] is False and "нет" in got["reason"]

    def test_empty_journal_is_not_measured_not_zero(self, tmp_path):
        p = tmp_path / "j.jsonl"
        p.write_text("\n\n", encoding="utf-8")
        assert M.load_journal(p)["measured"] is False

    def test_broken_lines_are_counted_not_swallowed(self, tmp_path):
        p = tmp_path / "j.jsonl"
        p.write_text(json.dumps(rec(ts_=ts(1))) + "\n{not json\n[]\n", encoding="utf-8")
        got = M.load_journal(p)
        assert got["measured"] is True
        assert len(got["records"]) == 1 and got["unparsed_lines"] == 2

    def test_record_without_timestamp_is_unparsed(self, tmp_path):
        p = tmp_path / "j.jsonl"
        p.write_text(json.dumps({"summary": "нет отметки"}) + "\n"
                     + json.dumps(rec(ts_=ts(1))) + "\n", encoding="utf-8")
        got = M.load_journal(p)
        assert got["unparsed_lines"] == 1 and len(got["records"]) == 1


# ──────────────────────────── дерево базового ref ────────────────────────────

def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    # Имя ветки — ВХОД СЦЕНЫ (`git init -b`): `init.defaultBranch` хоста иначе
    # решал бы вердикт (Apple Git даёт main, ubuntu-latest — master).
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "scene"], cwd=root, check=True,
                   capture_output=True)
    return root


class TestBaseTree:
    def test_real_ref_is_read(self, tmp_path):
        root = _repo(tmp_path, {"scripts/a.py": "x\n", "docs/b.md": "y\n"})
        got = M.read_base_tree(root, "main")
        assert got["measured"] is True
        assert got["paths"] == {"scripts/a.py", "docs/b.md"}
        assert got["top_level"] == {"scripts", "docs"}
        assert got["sha"] and got["committed_at"]

    def test_unknown_ref_is_not_measured(self, tmp_path):
        root = _repo(tmp_path, {"scripts/a.py": "x\n"})
        got = M.read_base_tree(root, "origin/does-not-exist")
        assert got["measured"] is False and "не прочитан" in got["reason"]

    def test_empty_tree_is_a_read_failure_not_an_empty_delivery(self, tmp_path):
        """Дерево репозитория пустым не бывает: пустой ответ есть поломка чтения.
        Иначе слепой проход объявил бы потерянным ВСЁ."""
        root = tmp_path / "bare"
        root.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "пусто"], cwd=root,
                       check=True, capture_output=True)
        got = M.read_base_tree(root, "main")
        assert got["measured"] is False and "пусто" in got["reason"]

    def test_not_a_repository_is_not_measured(self, tmp_path):
        got = M.read_base_tree(tmp_path, "main")
        assert got["measured"] is False


# ─────────────────────────── ось A: цена по координате ───────────────────────

class TestPrice:
    def test_two_sessions_on_an_absent_coordinate_without_kin_is_lost(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/spa_core/monitoring/orphan_runs.py"]),
                rec(ts_=ts(2), pid=2, files=["/t/b/spa_core/monitoring/orphan_runs.py"])]
        got = M.measure_price(recs, base({"spa_core/monitoring/keep.py"}))
        assert got["lost_coordinates"] == 1
        assert got["sessions_on_lost_coordinates"] == 2
        assert got["by_verdict"] == {"absent_lost": 1}

    def test_absent_coordinate_with_kin_is_a_rename_suspicion_not_a_price(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/spa_core/tests/test_tracker_board_composition.py"]),
                rec(ts_=ts(2), pid=2, files=["/t/b/spa_core/tests/test_tracker_board_composition.py"])]
        got = M.measure_price(
            recs, base({"spa_core/tests/test_tracker_board_matches_cards.py"}))
        assert got["lost_coordinates"] == 0
        assert got["by_verdict"] == {"absent_kin": 1}

    def test_coordinate_present_at_base_is_delivered(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/scripts/x.py"]),
                rec(ts_=ts(2), pid=2, files=["/t/b/scripts/x.py"])]
        got = M.measure_price(recs, base({"scripts/x.py"}))
        assert got["by_verdict"] == {"at_base": 1} and got["lost_coordinates"] == 0

    def test_one_session_twice_is_not_two_sessions(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/scripts/gone.py"]),
                rec(ts_=ts(2), pid=1, files=["/t/a/scripts/gone.py"])]
        got = M.measure_price(recs, base({"scripts/keep.py"}))
        assert got["coordinates_shared_by_two_or_more"] == 0

    def test_same_session_under_two_labels_is_still_one_session(self):
        """Личность — якорь, а не ярлык: иначе форма записи изготовила бы находку."""
        left = rec(ts_=ts(1), pid=5, files=["/t/a/scripts/gone.py"])
        right = rec(ts_=ts(2), pid=5, files=["/t/a/scripts/gone.py"])
        right["session"] = "cycle-другой-ярлык"
        got = M.measure_price([left, right], base({"scripts/keep.py"}))
        assert got["lost_coordinates"] == 0

    def test_declared_dropped_with_a_reason_is_a_decision_not_a_loss(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/scripts/gone.py"]),
                rec(ts_=ts(2), pid=2, files=["/t/b/scripts/gone.py"],
                    dropped=[{"path": "/t/b/scripts/gone.py", "reason": "черновик"}])]
        got = M.measure_price(recs, base({"scripts/keep.py"}))
        assert got["by_verdict"] == {"declared_dropped": 1}
        assert got["lost_coordinates"] == 0

    def test_dropped_without_a_reason_is_not_a_decision(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/scripts/gone.py"]),
                rec(ts_=ts(2), pid=2, files=["/t/b/scripts/gone.py"],
                    dropped=[{"path": "/t/b/scripts/gone.py", "reason": "  "}])]
        got = M.measure_price(recs, base({"scripts/keep.py"}))
        assert got["lost_coordinates"] == 1

    def test_declared_directory_is_neither_lost_nor_delivered(self):
        recs = [rec(ts_=ts(1), pid=1, files=["/t/a/nimbalyst-local/tracker"]),
                rec(ts_=ts(2), pid=2, files=["/t/b/nimbalyst-local/tracker"])]
        got = M.measure_price(recs, base({"nimbalyst-local/tracker/card.md"}))
        assert got["by_verdict"] == {"declared_a_directory": 1}

    def test_base_ref_older_than_the_declaration_yields_no_verdict(self):
        """«На базе нет» про работу, объявленную ПОЗЖЕ самой базы, есть
        утверждение о ref'е, а не о работе."""
        recs = [rec(ts_=ts(20), pid=1, files=["/t/a/scripts/new.py"]),
                rec(ts_=ts(21), pid=2, files=["/t/b/scripts/new.py"])]
        got = M.measure_price(recs, base({"scripts/keep.py"},
                                         committed_at="2026-09-10T00:00:00+00:00"))
        assert got["by_verdict"] == {"base_ref_older_than_declaration": 1}
        assert got["lost_coordinates"] == 0

    def test_the_earliest_declaration_decides_against_the_base_ref(self):
        """Сравнивать с базой надо ПЕРВОЕ объявление: взяв последнее, прибор
        объявил бы «база старше объявления» о работе, начатой ДО этой базы."""
        recs = [rec(ts_=ts(5), pid=1, files=["/t/scripts/gone.py"]),
                rec(ts_=ts(25), pid=2, files=["/t/scripts/gone.py"])]
        got = M.measure_price(recs, base({"scripts/keep.py"},
                                         committed_at="2026-09-10T00:00:00+00:00"))
        assert got["by_verdict"] == {"absent_lost": 1}

    def test_records_without_subject_or_anchor_are_counted_separately(self):
        recs = [rec(ts_=ts(1), card=None, files=["/t/a/scripts/x.py"]),
                rec(ts_=ts(2), pid=None, start=None, files=["/t/a/scripts/x.py"]),
                rec(ts_=ts(3), pid=1, files=["/t/zzz/unknown/x.py"])]
        got = M.measure_price(recs, base({"scripts/x.py"}))
        assert got["records_without_subject"] == 1
        assert got["records_without_durable_anchor"] == 1
        assert got["declarations_not_normalisable"] == 1

    def test_different_subjects_do_not_share_a_coordinate(self):
        recs = [rec(ts_=ts(1), pid=1, card="inbox-a", files=["/t/a/scripts/gone.py"]),
                rec(ts_=ts(2), pid=2, card="inbox-b", files=["/t/b/scripts/gone.py"])]
        got = M.measure_price(recs, base({"scripts/keep.py"}))
        assert got["coordinates_shared_by_two_or_more"] == 0


# ────────────────────────── ось B: квитанция сторожа ─────────────────────────

class TestReceipts:
    def test_taking_without_a_receipt_is_a_finding(self):
        got = M.measure_receipts([rec(ts_=ts(27), pid=1)], now=NOW)
        assert got["window_takings"] == 1
        assert got["window_takings_without_receipt"] == 1

    def test_taking_with_a_guard_receipt_is_clean(self):
        recs = [rec(ts_=ts(27), pid=1),
                rec(ts_=ts(27, 11), pid=1,
                    summary="[check_card_claim] захват карточки inbox-card")]
        got = M.measure_receipts(recs, now=NOW)
        assert got["window_takings"] == 1
        assert got["window_takings_without_receipt"] == 0
        assert got["receipts_in_journal"] == 1

    def test_a_receipt_for_another_subject_does_not_count(self):
        recs = [rec(ts_=ts(27), pid=1, card="inbox-card"),
                rec(ts_=ts(27, 11), pid=1, card="inbox-other",
                    summary="[check_card_claim] захват карточки inbox-other")]
        got = M.measure_receipts(recs, now=NOW)
        assert got["window_takings_without_receipt"] == 1

    def test_a_receipt_from_another_session_does_not_count(self):
        recs = [rec(ts_=ts(27), pid=1),
                rec(ts_=ts(27, 11), pid=2,
                    summary="[check_card_claim] захват карточки inbox-card")]
        got = M.measure_receipts(recs, now=NOW)
        assert got["window_takings_without_receipt"] == 1

    def test_release_is_not_a_taking(self):
        got = M.measure_receipts([rec(ts_=ts(27), pid=1, state="done")], now=NOW)
        assert got["window_takings"] == 0

    def test_window_is_an_input_not_the_calendar(self):
        old = [rec(ts_=OLD, pid=1)]
        assert M.measure_receipts(old, now=NOW, window_days=30)["window_takings"] == 0
        assert M.measure_receipts(old, now=NOW, window_days=90)["window_takings"] == 1

    def test_unparsed_timestamp_is_a_third_outcome(self):
        bad = rec(ts_=ts(27), pid=1)
        bad["ts"] = "не-дата"
        got = M.measure_receipts([bad], now=NOW)
        assert got["timestamps_unparsed"] == 1 and got["window_takings"] == 0

    def test_the_same_session_and_subject_counts_once(self):
        recs = [rec(ts_=ts(26), pid=1), rec(ts_=ts(27), pid=1)]
        assert M.measure_receipts(recs, now=NOW)["window_takings"] == 1

    def test_absence_of_a_receipt_is_declared_unobservable(self):
        got = M.measure_receipts([rec(ts_=ts(27), pid=1)], now=NOW)
        assert "НЕ НАБЛЮДАЕМО" in got["absence_means"]


# ───────────────────────────── ось B: проводка ───────────────────────────────

class TestWiring:
    def test_import_form_is_a_load(self, tmp_path):
        root = tmp_path / "r"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "a.py").write_text(
            "from check_card_claim import _CLAIM_KEYS\n", encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["loads"] == ["scripts/a.py"]

    def test_literal_inside_a_loading_call_is_a_load(self, tmp_path):
        root = tmp_path / "r"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "b.py").write_text(
            "import importlib.util, pathlib\n"
            "spec = importlib.util.spec_from_file_location(\n"
            "    'x', pathlib.Path('/r') / 'scripts' / 'check_card_claim.py')\n",
            encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["loads"] == ["scripts/b.py"]

    def test_literal_inside_a_printing_call_is_NOT_a_load(self, tmp_path):
        """Первая редакция считала это проводкой: подсказка в тексте доски."""
        root = tmp_path / "r"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "c.py").write_text(
            "lines = []\n"
            "lines.append('> Ставится scripts/check_card_claim.py claim')\n",
            encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["loads"] == [] and got["unfollowed_mentions"] == ["scripts/c.py"]

    def test_prose_only_mention_is_neither(self, tmp_path):
        root = tmp_path / "r"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "d.py").write_text(
            "# защищено check_card_claim с 30.07\nX = 1\n", encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["prose_only"] == ["scripts/d.py"]
        assert got["loads"] == [] and got["unfollowed_mentions"] == []

    def test_tests_are_not_wiring(self, tmp_path):
        root = tmp_path / "r"
        (root / "spa_core" / "tests").mkdir(parents=True)
        (root / "spa_core" / "tests" / "test_x.py").write_text(
            "import check_card_claim\n", encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["measured"] is False or got["loads"] == []

    def test_the_guard_itself_is_not_its_own_caller(self, tmp_path):
        root = tmp_path / "r"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "check_card_claim.py").write_text(
            "import check_card_claim\n", encoding="utf-8")
        (root / "scripts" / "other.py").write_text("X = 1\n", encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["loads"] == []

    def test_nothing_scanned_is_not_measured(self, tmp_path):
        got = M.measure_guard_wiring(tmp_path / "empty")
        assert got["measured"] is False and got["reason"]

    def test_unparsable_python_does_not_become_a_load(self, tmp_path):
        root = tmp_path / "r"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "e.py").write_text(
            "def broken(:\n  check_card_claim\n", encoding="utf-8")
        got = M.measure_guard_wiring(root)
        assert got["loads"] == [] and got["prose_only"] == ["scripts/e.py"]


# ──────────────────────────── сборка и вердикт ───────────────────────────────

def _scene(tmp_path: Path, records, files: dict[str, str]) -> tuple[Path, Path]:
    root = _repo(tmp_path, files)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "main"],
                   cwd=root, check=True, capture_output=True)
    data = root / "data"
    data.mkdir(exist_ok=True)
    (data / M.JOURNAL_NAME).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8")
    return root, data


class TestRunCensus:
    def test_missing_journal_is_unmeasured_and_leaves_an_artifact(self, tmp_path):
        root = _repo(tmp_path, {"scripts/a.py": "x\n"})
        report = M.run_census(root / "data", repo_root=root, base_ref="main", now=NOW)
        assert report["measured"] is False
        assert report["status"] == M.STATUS_UNMEASURED and report["reason"]

    def test_no_normalisable_coordinate_is_unmeasured_not_clean(self, tmp_path):
        """Слепой проход (приставка не распознана) выглядел бы как «дублей нет»."""
        recs = [rec(ts_=ts(27), pid=1, files=["/elsewhere/x.py"]),
                rec(ts_=ts(27), pid=2, files=["/elsewhere/x.py"])]
        root, data = _scene(tmp_path, recs, {"scripts/a.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW)
        assert report["measured"] is False
        assert "не приведена" in report["reason"]

    def test_empty_window_is_unmeasured_not_a_clean_pass(self, tmp_path):
        recs = [rec(ts_=OLD, pid=1, files=["/t/scripts/a.py"]),
                rec(ts_=OLD, pid=2, files=["/t/scripts/a.py"])]
        root, data = _scene(tmp_path, recs, {"scripts/a.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW)
        assert report["measured"] is False
        assert "ни одного взятия" in report["reason"]

    def test_lost_coordinate_alone_opens_the_class(self, tmp_path):
        """Квитанции есть у ВСЕХ взятий — и класс всё равно открыт: цена уже
        потрачена. Без этой сцены «потеря» выпадала бы из вердикта незаметно."""
        recs = [rec(ts_=ts(26), pid=1, files=["/t/scripts/gone.py"],
                    summary="[check_card_claim] захват карточки inbox-card"),
                rec(ts_=ts(27), pid=2, files=["/t/scripts/gone.py"],
                    summary="[check_card_claim] захват карточки inbox-card")]
        root, data = _scene(tmp_path, recs, {"scripts/keep.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW)
        assert report["measured"] is True
        assert report["status"] == M.STATUS_OPEN
        assert report["price"]["lost_coordinates"] == 1
        assert report["receipts"]["window_takings_without_receipt"] == 0

    def test_missing_receipt_alone_opens_the_class(self, tmp_path):
        recs = [rec(ts_=ts(26), pid=1, files=["/t/scripts/keep.py"]),
                rec(ts_=ts(27), pid=2, files=["/t/scripts/keep.py"])]
        root, data = _scene(tmp_path, recs, {"scripts/keep.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW)
        assert report["status"] == M.STATUS_OPEN
        assert report["price"]["lost_coordinates"] == 0
        assert report["receipts"]["window_takings_without_receipt"] == 2

    def test_class_closes_only_when_both_axes_are_clean(self, tmp_path):
        recs = [rec(ts_=ts(26), pid=1, files=["/t/scripts/keep.py"],
                    summary="[check_card_claim] захват карточки inbox-card"),
                rec(ts_=ts(27), pid=2, files=["/t/scripts/keep.py"],
                    summary="[check_card_claim] захват карточки inbox-card")]
        root, data = _scene(tmp_path, recs, {"scripts/keep.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW)
        assert report["measured"] is True and report["status"] == M.STATUS_CLOSED

    def test_base_ref_identity_is_recorded(self, tmp_path):
        recs = [rec(ts_=ts(26), pid=1, files=["/t/scripts/keep.py"]),
                rec(ts_=ts(27), pid=2, files=["/t/scripts/keep.py"])]
        root, data = _scene(tmp_path, recs, {"scripts/keep.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW)
        assert report["base_ref"]["sha"] and report["base_ref"]["files"] == 1

    def test_unreadable_base_ref_is_unmeasured(self, tmp_path):
        recs = [rec(ts_=ts(27), pid=1, files=["/t/scripts/keep.py"])]
        root, data = _scene(tmp_path, recs, {"scripts/keep.py": "x\n"})
        report = M.run_census(data, repo_root=root, base_ref="origin/nope", now=NOW)
        assert report["measured"] is False
        assert report["base_ref"]["measured"] is False


class TestArtifactAndExit:
    def test_run_writes_the_artifact_even_when_unmeasured(self, tmp_path):
        root = _repo(tmp_path, {"scripts/a.py": "x\n"})
        (root / "data").mkdir()
        out = M.run(root=str(root), now=NOW)
        assert out["measured"] is False
        doc = json.loads((root / "data" / M.ARTIFACT_NAME).read_text(encoding="utf-8"))
        assert doc["status"] == M.STATUS_UNMEASURED and doc["reason"]

    def test_report_shape_is_constant_even_when_unmeasured(self, tmp_path):
        """Ключи объявлены ВСЕГДА: «не вычислено» — это `None`, а не отсутствие
        ключа, иначе шаг 0-офис не отличит его от уехавшего производителя."""
        root = _repo(tmp_path, {"scripts/a.py": "x\n"})
        report = M.run_census(root / "data", repo_root=root, base_ref="main", now=NOW)
        for key in ("base_ref", "price", "receipts", "guard_wiring", "status",
                    "measured", "order", "journal"):
            assert key in report, key

    def test_format_report_says_not_measured_out_loud(self):
        lines = M.format_report({"measured": False, "reason": "журнала нет"})
        assert any("НЕ ИЗМЕРЕНО" in line for line in lines)

    def test_exit_code_two_when_unmeasured(self, tmp_path, capsys):
        root = _repo(tmp_path, {"scripts/a.py": "x\n"})
        code = M.main(["--repo-root", str(root), "--data-dir", str(root / "data"),
                       "--base-ref", "main"])
        assert code == 2

    def test_exit_code_one_when_the_class_is_open(self, tmp_path, capsys):
        recs = [rec(ts_=ts(26), pid=1, files=["/t/scripts/keep.py"]),
                rec(ts_=ts(27), pid=2, files=["/t/scripts/keep.py"])]
        root, data = _scene(tmp_path, recs, {"scripts/keep.py": "x\n"})
        # Окно меряется от НАСТОЯЩИХ часов в CLI намеренно: это боевая форма
        # вызова. Отметки сцены свежие относительно 2026-09-28, поэтому тест
        # закрепляет вход, а не календарь — окно расширено до предела.
        code = M.main(["--repo-root", str(root), "--data-dir", str(data),
                       "--base-ref", "main", "--window-days", "36500"])
        assert code == 1
        assert "CLASS_OPEN" in capsys.readouterr().out
