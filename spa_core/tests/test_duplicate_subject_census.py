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


# ════════════════════ цикл #751 · заказ G88 п. 3 ════════════════════
#
# Три звена, добавленные после замера #751, и у каждого контроль в ОБЕ стороны.
# Замер, из которого они выросли: из 7 координат, объявленных прибором
# потерянными, ДВЕ потеряны не были — одна списана доставленным удалением,
# другая доставлена под переномерованным именем. Обе ошибки односторонни и в
# опасную сторону: цена завышена, а следующую сессию посылали «поднять» уже
# сделанную работу (а в случае списания — ОТМЕНИТЬ решение).


def _repo_with_history(tmp_path: Path, *, name: str = "repo",
                       steps: list[tuple[str, dict[str, str | None]]]) -> Path:
    """Репозиторий, у которого есть ИСТОРИЯ: по коммиту на шаг.

    ``None`` в значении = файл на этом шаге УДАЛЯЕТСЯ. Имя ветки — вход сцены
    (`git init -b`), иначе вердикт решал бы `init.defaultBranch` хоста.
    """
    root = tmp_path / name
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    for message, files in steps:
        for rel, text in files.items():
            path = root / rel
            if text is None:
                subprocess.run(["git", "rm", "-q", rel], cwd=root, check=True,
                               capture_output=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message, "--allow-empty"], cwd=root,
                       check=True, capture_output=True)
    return root


def _truncate(tmp_path: Path, source: Path, depth: int) -> Path:
    """Обрезанный клон — ровно та форма, в которой работает прод-дерево."""
    target = tmp_path / f"shallow{depth}"
    subprocess.run(["git", "clone", "--depth", str(depth), "-b", "main",
                    f"file://{source}", str(target)],
                   check=True, capture_output=True)
    assert subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=target,
                          capture_output=True, text=True).stdout.strip() == "true"
    return target


class TestKinOfARenumberedDocument:
    """Родня нумерованного документа ищется по СЛАГУ, а не по началу имени."""

    _DECLARED = "docs/decisions/ADR-365-capital-observability-over-history.md"

    def _verdict(self, base_paths) -> dict:
        recs = [rec(ts_=ts(1), pid=1, files=[f"/t/a/{self._DECLARED}"]),
                rec(ts_=ts(2), pid=2, files=[f"/t/b/{self._DECLARED}"])]
        return M.measure_price(recs, base(set(base_paths) | {"docs/decisions/keep.md"}))

    def test_the_same_slug_under_another_number_is_kin_not_a_loss(self):
        """Доставлено как ADR-366: номер 365 за сутки сиротства занял другой цикл.

        Сравнение по НАЧАЛУ имени такую родню увидеть не может по построению —
        токены расходятся вторыми, на номере.
        """
        got = self._verdict({"docs/decisions/ADR-366-capital-observability-over-history.md"})
        assert got["by_verdict"].get("absent_kin") == 1
        assert got["lost_coordinates"] == 0
        assert got["findings"][0]["kin"] == [
            "docs/decisions/ADR-366-capital-observability-over-history.md"]

    def test_the_same_number_with_another_slug_is_still_a_loss(self):
        """Обратная сторона: номер переиспользован, объявленного документа нет."""
        recs = [rec(ts_=ts(1), pid=1,
                    files=["/t/a/docs/decisions/ADR-154-unmeasured-origin-sweep-and-board-composition.md"]),
                rec(ts_=ts(2), pid=2,
                    files=["/t/b/docs/decisions/ADR-154-unmeasured-origin-sweep-and-board-composition.md"])]
        got = M.measure_price(recs, base({"docs/decisions/ADR-154-contracts-before-orchestration.md"}))
        assert got["lost_coordinates"] == 1
        assert got["by_verdict"].get("absent_kin") is None

    def test_a_neighbour_sharing_only_two_slug_tokens_is_not_kin(self):
        """Порог слага тот же, что у начала имени: два токена роднёй не делают."""
        got = self._verdict(
            {"docs/decisions/ADR-364-capital-observability-census-g1-acceptance.md"})
        assert got["lost_coordinates"] == 1

    def test_another_mark_with_the_same_slug_is_not_kin(self):
        """Марка документа — часть личности: RFC-366 не есть переименование ADR-365."""
        got = self._verdict(
            {"docs/decisions/RFC-366-capital-observability-over-history.md"})
        assert got["lost_coordinates"] == 1

    def test_an_unnumbered_name_keeps_the_old_rule(self):
        """Правило номера не отменяет прежнее: ненумерованные имена — по началу."""
        assert M.kin_of("spa_core/tests/test_tracker_board_composition.py",
                        {"spa_core/tests/test_tracker_board_matches_cards.py"})
        assert not M.kin_of("spa_core/tests/test_tracker_board_composition.py",
                            {"spa_core/tests/test_cycle_lock_watch.py"})


class TestRetirementDoor:
    """Доставленное УДАЛЕНИЕ не есть потеря — и отказ двери асимметричен."""

    _PATH = "scripts/day30_review.py"

    def _declared(self, day: int) -> list[dict]:
        return [rec(ts_=ts(day), pid=1, files=[f"/t/a/{self._PATH}"]),
                rec(ts_=ts(day + 1), pid=2, files=[f"/t/b/{self._PATH}"])]

    def test_a_deletion_delivered_after_the_declaration_is_a_retirement(self, tmp_path):
        """Сессия объявила координату, чтобы её УБРАТЬ, и убрала — работа доехала."""
        root = self._repo_deleting_after_declaration(tmp_path)
        got = M.measure_price(self._declared(1),
                              base({"scripts/keep.py"}, committed_at="2026-09-30T00:00:00+00:00"),
                              retirement=M.retirement_door(root, "main"))
        assert got["by_verdict"].get("retired_at_base") == 1
        assert got["lost_coordinates"] == 0
        assert got["retired_at_base"] == 1
        assert "списана коммитом" in got["findings"][0]["retirement"]

    def _repo_deleting_after_declaration(self, tmp_path) -> Path:
        """Удаление ПОЗЖЕ объявления: отметки коммитов — настоящие, объявления — 09-01/02."""
        return _repo_with_history(tmp_path, steps=[
            ("рождение", {self._PATH: "x\n", "scripts/keep.py": "k\n"}),
            ("списание", {self._PATH: None}),
        ])

    def test_a_deletion_BEFORE_the_declaration_is_still_a_loss(self, tmp_path):
        """Файл удалили раньше — значит сессия завела его ЗАНОВО и не доставила.

        Обратный контроль той же двери: оправдывает не «когда-то удалялся», а
        именно отметка позже объявления.
        """
        root = self._repo_deleting_after_declaration(tmp_path)
        far_future = [rec(ts_=f"2099-01-0{n}T12:00:00Z", pid=n,
                          files=[f"/t/{n}/{self._PATH}"]) for n in (1, 2)]
        got = M.measure_price(far_future,
                              base({"scripts/keep.py"}, committed_at="2099-12-31T00:00:00+00:00"),
                              retirement=M.retirement_door(root, "main"))
        assert got["lost_coordinates"] == 1
        assert "удалена ДО объявления" in got["findings"][0]["retirement"]

    def test_a_coordinate_never_at_base_is_a_loss_in_a_full_clone(self, tmp_path):
        """«Измерено и равно нулю»: полный клон удаления не помнит ⇒ потеря."""
        root = _repo_with_history(tmp_path, steps=[("рождение", {"scripts/keep.py": "k\n"})])
        got = M.measure_price(self._declared(1), base({"scripts/keep.py"}),
                              retirement=M.retirement_door(root, "main"))
        assert got["lost_coordinates"] == 1
        assert got["findings"][0]["retirement"] == "база удаления этой координаты не помнит"
        assert got["retirement_unmeasured"] == 0

    def test_a_truncated_clone_may_NOT_say_the_coordinate_was_never_deleted(self, tmp_path):
        """ТРЕТИЙ исход, и он не склеен ни с «потеряно», ни с «списано».

        Прод-дерево обрезано по построению (замер #751: 443 коммита, 20 точек
        обрезки), и `git log` по пути отдаёт там пустоту с кодом 0 при живом
        объекте удаляющего коммита. Прочесть эту пустоту как «не удалялось»
        значило бы объявить потерей каждое доставленное списание.
        """
        source = _repo_with_history(tmp_path, steps=[
            ("рождение", {self._PATH: "x\n", "scripts/keep.py": "k\n"}),
            ("списание", {self._PATH: None}),
            ("после", {"scripts/other.py": "o\n"}),
        ])
        shallow = _truncate(tmp_path, source, depth=1)
        got = M.measure_price(self._declared(1), base({"scripts/keep.py"}),
                              retirement=M.retirement_door(shallow, "main"))
        assert got["by_verdict"].get("absent_retirement_unmeasured") == 1
        assert got["lost_coordinates"] == 0
        assert got["retirement_unmeasured"] == 1
        assert "ОБРЕЗАНО" in got["findings"][0]["retirement"]

    def test_a_VISIBLE_deletion_is_measured_even_in_a_truncated_clone(self, tmp_path):
        """Асимметрия отказа: обрезка мешает заключить «не было», а не «увидеть».

        Положительный контроль ровно на то, что дверь не отказывает ОПТОМ по
        признаку «клон обрезан»: если удаляющий коммит достижим, вердикт есть.
        """
        source = _repo_with_history(tmp_path, steps=[
            ("рождение", {self._PATH: "x\n", "scripts/keep.py": "k\n"}),
            ("списание", {self._PATH: None}),
        ])
        shallow = _truncate(tmp_path, source, depth=2)
        answer = M.retirement_door(shallow, "main")(self._PATH)
        assert answer["measured"] is True and answer["deleted_at"]

    def test_not_a_repository_is_not_measured(self, tmp_path):
        answer = M.retirement_door(tmp_path, "main")(self._PATH)
        assert answer["measured"] is False and answer["reason"]

    def test_without_a_door_the_price_says_NOT_ASKED_out_loud(self):
        """«Не спрошено» обязано быть видно: иначе это тихий fail-OPEN.

        Ошибка при этом идёт в сторону ЗАВЫШЕНИЯ цены, а не занижения.
        """
        got = M.measure_price(self._declared(1), base({"scripts/keep.py"}))
        assert got["retirement_door_asked"] is False
        assert got["findings"][0]["retirement"] == "not_asked"
        report = {"measured": True, "status": M.STATUS_OPEN, "price": got,
                  "receipts": {"window_days": 30, "window_takings": 1,
                               "window_takings_without_receipt": 1,
                               "receipts_in_journal": 0, "absence_means": "—"},
                  "guard_wiring": {"measured": False, "reason": "—"}}
        assert any("НЕ СПРОШЕНО" in line for line in M.format_report(report))


class TestLiftabilityOfLostWork:
    """Подъёмность: окно подъёма равно времени жизни дерева, а не сроку заказа."""

    _PATH = "spa_core/monitoring/orphan_runs.py"

    def _recs(self, prefixes) -> list[dict]:
        return [rec(ts_=ts(n + 1), pid=n + 1, files=[f"{prefix}/{self._PATH}".lstrip("/") if not prefix
                                                     else f"{prefix}/{self._PATH}"])
                for n, prefix in enumerate(prefixes)]

    def test_a_gone_tree_makes_the_price_final(self):
        """Замер #751: все 11 объявленных деревьев стёрты ⇒ поднимать нечего."""
        got = M.measure_price(self._recs(["/tmp/spa_c400", "/tmp/spa_c403"]),
                              base({"spa_core/monitoring/keep.py"}),
                              tree_exists=lambda path: False)
        assert got["liftability"] == {"tree_gone": 1}
        assert got["findings"][0]["trees"] == ["/tmp/spa_c400", "/tmp/spa_c403"]
        assert got["findings"][0]["trees_alive"] == []

    def test_a_living_tree_NAMES_the_path_to_lift_from(self):
        """Обратная сторона: дерево цело ⇒ путь назван, и подъём возможен."""
        got = M.measure_price(self._recs(["/tmp/spa_c400", "/tmp/spa_c403"]),
                              base({"spa_core/monitoring/keep.py"}),
                              tree_exists=lambda path: path == "/tmp/spa_c403")
        assert got["liftability"] == {"tree_present": 1}
        assert got["findings"][0]["trees_alive"] == ["/tmp/spa_c403"]

    def test_a_declaration_without_a_tree_prefix_is_a_THIRD_outcome(self):
        """Объявление относительным путём: дерево не названо — сказать нечего.

        Это не «дерева нет»: цикл-398 объявил ADR относительным путём, и выдать
        его за стёртое дерево значило бы изготовить вердикт из формы записи.
        """
        recs = [rec(ts_=ts(1), pid=1, files=[self._PATH]),
                rec(ts_=ts(2), pid=2, files=[self._PATH])]
        got = M.measure_price(recs, base({"spa_core/monitoring/keep.py"}),
                              tree_exists=lambda path: False)
        assert got["liftability"] == {"tree_not_named": 1}
        assert got["findings"][0]["trees"] == []

    def test_the_filesystem_door_is_an_INPUT_not_the_host(self):
        """Положительный контроль проводки: пробу спрашивают, а не угадывают.

        Та же причина, по которой `pid_alive` инъектируется
        (`.claude/rules/deployment.md`): иначе тест судил бы о том, что сегодня
        лежит в `/tmp` у ЭТОГО хоста.
        """
        asked: list[str] = []

        def probe(path: str) -> bool:
            asked.append(path)
            return False

        M.measure_price(self._recs(["/tmp/spa_cA", "/tmp/spa_cB"]),
                        base({"spa_core/monitoring/keep.py"}), tree_exists=probe)
        assert sorted(asked) == ["/tmp/spa_cA", "/tmp/spa_cB"]


class TestTreePrefix:
    _TOPS = {"spa_core", "docs", "scripts"}

    def test_an_absolute_declaration_keeps_its_leading_slash(self):
        assert M.tree_prefix_of("/tmp/spa_c400/spa_core/monitoring/x.py",
                                self._TOPS) == "/tmp/spa_c400"

    def test_a_repo_relative_declaration_names_no_tree(self):
        assert M.tree_prefix_of("docs/decisions/ADR-1-x.md", self._TOPS) is None

    def test_an_unrecognised_declaration_names_no_tree(self):
        assert M.tree_prefix_of("/var/log/syslog", self._TOPS) is None


class TestProductionPathAlwaysAsks:
    """Боевой путь дверь передаёт ВСЕГДА, и обрезка не читается как «чисто»."""

    def test_run_census_asks_the_retirement_door(self, tmp_path):
        recs = [rec(ts_=ts(26), pid=1, files=["/t/a/scripts/gone.py"]),
                rec(ts_=ts(27), pid=2, files=["/t/b/scripts/gone.py"])]
        root = _repo_with_history(tmp_path, steps=[("рождение", {"scripts/keep.py": "k\n"})])
        data = root / "data"
        data.mkdir()
        (data / M.JOURNAL_NAME).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        report = M.run_census(data, repo_root=root, base_ref="main", now=NOW,
                              window_days=36500)
        assert report["price"]["retirement_door_asked"] is True

    def test_the_class_stays_OPEN_while_retirement_is_unmeasured(self, tmp_path):
        """Fail-CLOSED ПО ВЕРДИКТУ, а не по строке отчёта.

        Сцена подобрана так, что закрыть класс мешает ТОЛЬКО третий исход двери
        списания: потерянных координат ноль, квитанция у каждого взятия есть.
        Снять `or price["retirement_unmeasured"] > 0` из `run_census` — и тест
        краснеет, объявив класс закрытым на обрезанном клоне.

        Иначе обрезанное дерево — то есть обычное окружение этого прода —
        обнулило бы и цену, и вердикт разом, и это читалось бы как «чисто»
        (урок `pyflakes` в `.claude/rules/deployment.md`: отсутствие ответа
        тише красного).
        """
        source = _repo_with_history(tmp_path, steps=[
            ("рождение", {"scripts/gone.py": "x\n", "scripts/keep.py": "k\n"}),
            ("списание", {"scripts/gone.py": None}),
            ("после", {"scripts/other.py": "o\n"}),
        ])
        shallow = _truncate(tmp_path, source, depth=1)
        taking = rec(ts_=ts(26), pid=1, files=["/t/a/scripts/gone.py"])
        receipt = rec(ts_=ts(26, 13), pid=1, files=[],
                      summary=M._RECEIPT_PREFIX + " сторож спрошен")
        second = rec(ts_=ts(27), pid=2, files=["/t/b/scripts/gone.py"])
        second_receipt = rec(ts_=ts(27, 13), pid=2, files=[],
                             summary=M._RECEIPT_PREFIX + " сторож спрошен")
        data = tmp_path / "data"
        data.mkdir()
        (data / M.JOURNAL_NAME).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n"
                    for r in (taking, receipt, second, second_receipt)),
            encoding="utf-8")
        report = M.run_census(data, repo_root=shallow, base_ref="main", now=NOW,
                              window_days=36500)
        assert report["measured"] is True
        price = report["price"]
        assert price["lost_coordinates"] == 0, "сцена обязана не иметь потерь"
        assert price["retirement_unmeasured"] == 1
        assert report["receipts"]["window_takings_without_receipt"] == 0, \
            "сцена обязана не иметь взятий без квитанции"
        assert report["status"] == M.STATUS_OPEN

    def test_liftability_is_reported_even_when_retirement_is_unmeasured(self, tmp_path):
        """Подъёмность про ДЕРЕВО, а не про вопрос списания.

        На обрезанном клоне — то есть на боевом хосте — все отсутствующие
        координаты уходят в третий исход двери списания, и привязка подъёмности
        только к `absent_lost` молчала бы ровно там, где заказ G88 п. 3 её и
        спрашивает.
        """
        source = _repo_with_history(tmp_path, steps=[
            ("рождение", {"scripts/keep.py": "k\n"}),
            ("после", {"scripts/other.py": "o\n"}),
        ])
        shallow = _truncate(tmp_path, source, depth=1)
        recs = [rec(ts_=ts(1), pid=1, files=["/tmp/spa_cGONE/scripts/gone.py"]),
                rec(ts_=ts(2), pid=2, files=["/tmp/spa_cGONE/scripts/gone.py"])]
        got = M.measure_price(recs, base({"scripts/keep.py"}),
                              retirement=M.retirement_door(shallow, "main"),
                              tree_exists=lambda path: False)
        assert got["retirement_unmeasured"] == 1
        assert got["liftability"] == {"tree_gone": 1}
        assert got["findings"][0]["trees"] == ["/tmp/spa_cGONE"]
