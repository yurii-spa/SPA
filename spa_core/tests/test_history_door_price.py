"""Тесты прибора «откуда ступень берёт историю» — заказ G112 п. 1 (ADR-688).

Каждый тест здесь — положительный контроль: он краснеет, если сломать ровно то
звено, о котором говорит. Главный из них воспроизводит НАСТОЯЩУЮ аварию замера
10.10 — ложный ноль главного числа соседа от слепой двери — на одноразовой сцене
с настоящими репозиториями git и настоящим обрезанным клоном.

# FROZEN-DATE-OK: injected-clock — прибор принимает часы параметром
# (`build_report(..., now=)`), и сцена фиксирует ВТОРУЮ сторону тоже: отметки
# коммитов задаются `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` сцены, отметки записей
# журнала — литералами того же окна. Обе стороны закреплены, календарь на вердикт
# не влияет; литеральные даты здесь ЕСТЬ предмет (сравниваются отметка удаления и
# отметка объявления), и обе приходят из сцены, а не со стены.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import duplicate_subject_census as census
from spa_core.monitoring import history_door_price as M

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)

#: Отметки сцены. Удаление ПОЗЖЕ объявления — иначе сосед (и верно) назовёт
#: координату потерей, а не списанием, и предмет теста подменился бы.
DECLARED_AT = "2026-09-01T12:00:00Z"
BORN_AT = "2026-08-20T10:00:00 +0000"
DELETED_AT = "2026-09-05T10:00:00 +0000"

#: Координата, которая на базе ЕСТЬ: без неё `top_level` соседа пуст и ни одно
#: объявление не нормализуется — проход вышел бы слепым, а не измеренным.
KEEP = "scripts/keep.py"
RETIRED = "scripts/day30_review.py"
LOST = "scripts/orphan_runs.py"


def _git(root: Path, *args: str, date: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": str(root / ".gitconfig-none"),
                "GIT_CONFIG_SYSTEM": str(root / ".gitconfig-none"),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", *args], cwd=str(root), check=True,
                          capture_output=True, text=True, env=env)


def full_clone_source(tmp: Path, *, name: str = "source") -> Path:
    """Репозиторий с ИСТОРИЕЙ: координата рождается, потом списывается.

    Имя ветки — ВХОД сцены (`git init -b main`): `init.defaultBranch` хоста иначе
    решал бы вердикт за нас (Apple Git даёт `main`, git на `ubuntu-latest` —
    `master`), и тест был бы зелёным здесь и красным в CI.
    """
    root = tmp / name
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    (root / "scripts").mkdir()
    (root / KEEP).write_text("k\n", encoding="utf-8")
    (root / RETIRED).write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "рождение", date=BORN_AT)
    _git(root, "rm", "-q", RETIRED)
    _git(root, "commit", "-m", "списание", date=DELETED_AT)
    return root


def full_clone(tmp: Path, source: Path, *, name: str = "history") -> Path:
    """Полный клон — та форма, в которой живёт объявленный корень истории.

    Клон, а не исходный репозиторий сцены: ступень спрашивает базу `origin/main`,
    и у исходника такой ссылки нет по построению. Подсунуть исходник значило бы
    проверять дверь на ref, которого боевая ступень не называет.
    """
    target = tmp / name
    subprocess.run(["git", "clone", "-b", "main", f"file://{source}", str(target)],
                   check=True, capture_output=True)
    probe = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=target,
                           capture_output=True, text=True)
    assert probe.stdout.strip() == "false", "сцена не обеспечила полный клон"
    return target


def shallow_clone(tmp: Path, source: Path, *, name: str = "stage") -> Path:
    """Обрезанный клон — ровно та форма, в которой работает прод-дерево."""
    target = tmp / name
    subprocess.run(["git", "clone", "--depth", "1", "-b", "main",
                    f"file://{source}", str(target)], check=True, capture_output=True)
    probe = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=target,
                           capture_output=True, text=True)
    assert probe.stdout.strip() == "true", "сцена не обеспечила обрезанный клон"
    return target


def journal_at(root: Path) -> Path:
    """Журнал объявлений сцены: две РАЗНЫЕ сессии на каждой координате.

    Меньше двух сессий — и сосед по построению не считает координату вовсе
    (ось A про «две сессии на одном предмете»), то есть сцена не исполнила бы
    предпосылку и судила бы о пустом населении.
    """
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    path = data / census.JOURNAL_NAME
    records = []
    for pid, tree in ((1, "/tmp/spa_a"), (2, "/tmp/spa_b")):
        records.append({"ts": DECLARED_AT, "session": f"cycle-{pid}",
                        "session_pid": pid,
                        "session_pid_start": "Mon Sep 28 10:00:00 2026",
                        "summary": "работа", "card": "inbox-card",
                        "card_state": "claim",
                        "files": [f"{tree}/{RETIRED}", f"{tree}/{LOST}"]})
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                    encoding="utf-8")
    return path


def declare(root: Path, *paths: Path | str, env_var: str = "SPA_HISTORY_ROOT") -> Path:
    """Объявление корней истории в дереве сцены."""
    folder = root / "architecture"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "history_roots.json"
    path.write_text(json.dumps(
        {"schema_version": 1, "env_var": env_var,
         "roots": [{"path": str(p), "kind": "full_clone", "declared_by": "сцена"}
                   for p in paths]}, ensure_ascii=False), encoding="utf-8")
    return path


def report_for(stage: Path, *, env: dict | None = None) -> dict:
    return M.build_report(stage, base_ref="main", now=NOW, env=env or {})


def row(report: dict, door: str) -> dict:
    return next(d for d in report["doors"] if d["door"] == door)


class SceneMixin(unittest.TestCase):
    """Сцена одноразовая: `TemporaryDirectory`, живое дерево не трогается."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.origin = full_clone_source(self.tmp)
        self.source = full_clone(self.tmp, self.origin)
        self.stage = shallow_clone(self.tmp, self.origin)
        journal_at(self.stage)
        self.addCleanup(self._tmp.cleanup)


# ─────────────── ГЛАВНЫЙ контроль: ложный ноль главного числа ───────────────

class TestTheFalseZeroOfTheHeadlineNumber(SceneMixin):
    """Авария замера 10.10, воспроизведённая целиком.

    Слепая дверь не теряет строки — она ПЕРЕКЛАДЫВАЕТ их из «потеряно» в «не
    измерено», и наружу выходит НОЛЬ. Сцена несёт обе координаты: одну
    списанную (значит «потерей» её назвать нельзя — отказ соседа верен) и одну
    настоящую потерю (значит и молчать нельзя).
    """

    def test_the_blind_door_turns_a_real_loss_into_a_clean_zero(self):
        declare(self.stage, self.source)
        got = report_for(self.stage)
        own, chosen = row(got, M.DOOR_OWN), row(got, M.DOOR_DECLARED)
        self.assertEqual(own["state"], M.STATE_SHALLOW)
        self.assertEqual(chosen["state"], M.STATE_USABLE)
        # Население двери ОДНО И ТО ЖЕ у обеих — именно поэтому ноль и обманывает.
        self.assertEqual(own["outcome"]["population"], chosen["outcome"]["population"])
        self.assertEqual(own["outcome"]["lost_coordinates"], 0)
        self.assertEqual(own["outcome"]["blind"], own["outcome"]["population"])
        self.assertEqual(chosen["outcome"]["lost_coordinates"], 1)
        self.assertEqual(chosen["outcome"]["retired_at_base"], 1)
        self.assertEqual(chosen["outcome"]["blind"], 0)
        self.assertEqual(got["false_zero"]["hidden"], 1)
        self.assertEqual(got["status"], M.STATUS_CHOSEN)
        self.assertEqual(M.exit_code_for(got), 0)

    def test_without_the_declaration_the_stage_is_blind_and_says_so(self):
        """Обратная сторона: объявление не доехало ⇒ вердикт КРАСНЫЙ, не ноль."""
        got = report_for(self.stage)
        self.assertEqual(got["status"], M.STATUS_BLIND)
        self.assertTrue(got["effective"]["stage_is_blind"])
        self.assertEqual(M.exit_code_for(got), 1)
        self.assertIn("объявление не найдено", str(got["declaration"]["reason"]))
        # Ноль слепой двери при этом ИЗМЕРЕН и напечатан — он не исчезает.
        self.assertEqual(row(got, M.DOOR_OWN)["outcome"]["lost_coordinates"], 0)

    def test_the_survey_asks_the_own_door_even_when_a_better_one_was_found(self):
        """Обзор НЕ обрывается на первой пригодной двери.

        Обрыв был бы невидим: вердикт остался бы `HISTORY_DOOR_CHOSEN`, а
        сравнение «сколько прячет слепая дверь» молча стало бы НЕ ИЗМЕРЕНО
        ровно в момент успеха — то есть ответ на вопрос заказа исчез бы именно
        тогда, когда дверь нашлась.
        """
        declare(self.stage, self.source)
        got = report_for(self.stage)
        self.assertEqual([d["door"] for d in got["doors"]], list(M.DOORS))
        self.assertTrue(row(got, M.DOOR_OWN)["outcome"]["measured"])
        self.assertIsNotNone(got["false_zero"]["hidden"])


# ───────────────── порядок дверей и отвод каждой — ПО ПРИЧИНЕ ─────────────────

class TestDoorOrderAndNamedRefusals(SceneMixin):

    def test_the_environment_door_wins_over_the_declaration(self):
        """Переменная — ЯВНАЯ подмена оператора, и она первая в объявленном порядке."""
        declare(self.stage, self.source)
        other = full_clone(self.tmp, self.origin, name="override")
        got = report_for(self.stage, env={"SPA_HISTORY_ROOT": str(other)})
        self.assertEqual(got["chosen"]["door"], M.DOOR_ENV)
        self.assertEqual(got["effective"]["root"], str(other))
        # Объявленная дверь при этом ВСЁ РАВНО опрошена: цена её названа.
        self.assertEqual(row(got, M.DOOR_DECLARED)["state"], M.STATE_USABLE)

    def test_an_unusable_environment_door_is_refused_BY_NAME_not_skipped(self):
        """«Переменная задана, но мимо» ≠ «переменная не задана»: два ответа."""
        declare(self.stage, self.source)
        got = report_for(self.stage,
                         env={"SPA_HISTORY_ROOT": str(self.tmp / "no-such-tree")})
        env_row = row(got, M.DOOR_ENV)
        self.assertEqual(env_row["state"], M.STATE_ABSENT)
        self.assertIn("каталога нет", env_row["reason"])
        self.assertEqual(got["chosen"]["door"], M.DOOR_DECLARED)

    def test_an_unset_environment_variable_is_its_own_outcome(self):
        got = report_for(self.stage, env={})
        env_row = row(got, M.DOOR_ENV)
        self.assertEqual(env_row["state"], M.STATE_NOT_NAMED)
        self.assertIn("не задана", env_row["reason"])
        self.assertFalse(env_row["outcome"]["measured"])
        self.assertIn("спрашивать негде", env_row["outcome"]["reason"])

    def test_the_declaration_name_of_the_env_var_is_obeyed(self):
        """Имя переменной читается ИЗ объявления, а не из литерала модуля."""
        declare(self.stage, self.tmp / "no-such-tree", env_var="SPA_OTHER_ROOT")
        got = report_for(self.stage, env={"SPA_OTHER_ROOT": str(self.source)})
        self.assertEqual(got["chosen"]["door"], M.DOOR_ENV)
        self.assertEqual(got["declaration"]["env_var"], "SPA_OTHER_ROOT")

    def test_the_first_USABLE_declared_root_is_taken_not_the_first_declared(self):
        """Непригодный корень не останавливает обход и не выбирается молча."""
        declare(self.stage, self.tmp / "no-such-tree", self.source)
        got = report_for(self.stage)
        self.assertEqual(got["chosen"]["door"], M.DOOR_DECLARED)
        self.assertEqual(row(got, M.DOOR_DECLARED)["root"], str(self.source))

    def test_all_doors_unusable_leaves_root_None_and_never_substitutes_the_shallow_tree(self):
        """FAIL-CLOSED: «ну хоть что-то» вернуло бы ноль в заголовок соседа."""
        declare(self.stage, self.tmp / "no-such-tree")
        resolution = M.resolve_history_root(self.stage, base_ref="main", env={})
        self.assertIsNone(resolution["root"])
        self.assertIsNone(resolution["door"])
        self.assertEqual([p["door"] for p in resolution["trail"]], list(M.DOORS))


# ───────────── проба корня: каждый отвод отличим от остальных ─────────────

class TestRootProbeDiscriminatesEveryRefusal(SceneMixin):

    def test_a_shallow_root_is_refused_as_SHALLOW_not_as_absent(self):
        other = shallow_clone(self.tmp, self.origin, name="second-shallow")
        probe = M.probe_root(other, base_ref="main")
        self.assertEqual(probe["state"], M.STATE_SHALLOW)
        self.assertTrue(probe["shallow"])
        self.assertIn("история ОБРЕЗАНА", probe["reason"])

    def test_a_directory_that_is_not_a_git_tree_is_its_own_outcome(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        probe = M.probe_root(plain, base_ref="main")
        self.assertEqual(probe["state"], M.STATE_NOT_A_TREE)
        self.assertIn("не дерево git", probe["reason"])

    def test_a_missing_directory_is_absent_not_unmeasured(self):
        probe = M.probe_root(self.tmp / "nope", base_ref="main")
        self.assertEqual(probe["state"], M.STATE_ABSENT)
        self.assertIn("каталога нет", probe["reason"])

    def test_a_full_clone_without_the_base_ref_is_refused_BY_THAT_reason(self):
        probe = M.probe_root(self.source, base_ref="origin/does-not-exist")
        self.assertEqual(probe["state"], M.STATE_BASE_REF_ABSENT)
        self.assertIn("в дереве нет", probe["reason"])
        # Байты при этом ИЗМЕРЕНЫ: отвод по базе их не отменяет.
        self.assertTrue(probe["price"]["measured"])

    def test_a_root_that_is_not_named_at_all_is_not_an_absent_root(self):
        probe = M.probe_root(None, base_ref="main")
        self.assertEqual(probe["state"], M.STATE_NOT_NAMED)
        self.assertIsNone(probe["price"])

    def test_git_that_does_not_run_is_UNMEASURED_with_a_named_reason(self):
        """Отсутствие инструмента — самостоятельный третий исход, не ноль и не скип."""
        def _dead(*_args):
            raise OSError("git отсутствует на этом хосте")
        probe = M.probe_root(self.source, base_ref="main", git=_dead)
        self.assertEqual(probe["state"], M.STATE_UNMEASURED)
        self.assertIn("git не отработал", probe["reason"])


# ─────────────────────── цена в байтах: None, а не ноль ───────────────────────

class TestObjectStorePrice(SceneMixin):

    def test_a_full_clone_reports_bytes_and_reachable_commits(self):
        price = M.object_store_price(self.source)
        self.assertTrue(price["measured"])
        self.assertEqual(price["commits_reachable"], 2)
        self.assertEqual(price["total_kib"], price["loose_kib"] + price["pack_kib"])

    def test_a_shallow_clone_also_reports_its_commits_so_the_gap_is_visible(self):
        """Коммиты обрезанного дерева мерятся ТОЖЕ: 1 против 2 и есть цена обрезки."""
        price = M.object_store_price(self.stage)
        self.assertTrue(price["measured"])
        self.assertEqual(price["commits_reachable"], 1)

    def test_a_directory_without_a_store_gives_None_bytes_and_a_reason(self):
        """Ноль байт означал бы ИЗМЕРЕННЫЙ пустой склад — это другой ответ."""
        plain = self.tmp / "plain"
        plain.mkdir()
        price = M.object_store_price(plain)
        self.assertFalse(price["measured"])
        self.assertIsNone(price["total_kib"])
        self.assertIsNotNone(price["reason"])

    def test_a_store_answer_without_the_expected_fields_is_UNMEASURED(self):
        class _Fake:
            returncode = 0
            stdout = "count: 7\n"
            stderr = ""
        price = M.object_store_price(self.source, git=lambda *_a: _Fake())
        self.assertFalse(price["measured"])
        self.assertIn("`size`/`size-pack`", price["reason"])


# ──────────── объявление: прочитано · пусто · не прочитано — три ответа ────────────

class TestDeclarationOutcomes(SceneMixin):

    def test_a_missing_declaration_is_UNMEASURED_with_the_file_named(self):
        decl = M.read_declaration(self.stage)
        self.assertFalse(decl["measured"])
        self.assertIn(M.DECLARATION_REL, decl["reason"])

    def test_a_broken_declaration_is_UNMEASURED_not_an_empty_list(self):
        declare(self.stage, self.source)
        (self.stage / M.DECLARATION_REL).write_text("{не json", encoding="utf-8")
        decl = M.read_declaration(self.stage)
        self.assertFalse(decl["measured"])
        self.assertIn("не прочитано", decl["reason"])
        got = report_for(self.stage)
        self.assertEqual(got["status"], M.STATUS_BLIND)

    def test_a_declaration_that_is_not_a_mapping_is_refused_BY_THAT_reason(self):
        declare(self.stage, self.source)
        (self.stage / M.DECLARATION_REL).write_text("[]", encoding="utf-8")
        decl = M.read_declaration(self.stage)
        self.assertFalse(decl["measured"])
        self.assertIn("не словарь", decl["reason"])

    def test_an_empty_root_list_is_MEASURED_AND_ZERO_not_unread(self):
        """«Объявление есть, корней нет» лечится строкой в файле, а не доставкой файла."""
        declare(self.stage)
        decl = M.read_declaration(self.stage)
        self.assertTrue(decl["measured"])
        self.assertEqual(decl["roots"], [])
        got = report_for(self.stage)
        self.assertEqual(got["declaration"]["roots_declared"], 0)
        self.assertIn("объявленных корней нет", row(got, M.DOOR_DECLARED)["reason"])

    def test_a_root_declared_with_a_tilde_is_expanded(self):
        declare(self.stage, "~")
        probe = row(report_for(self.stage), M.DOOR_DECLARED)
        self.assertNotIn("~", str(probe["root"]))


# ─────────────── третий исход всего прибора и коды возврата ───────────────

class TestThirdOutcomeOfTheWholeInstrument(SceneMixin):

    def test_a_missing_journal_is_UNMEASURED_and_returns_two(self):
        (self.stage / "data" / census.JOURNAL_NAME).unlink()
        declare(self.stage, self.source)
        got = report_for(self.stage)
        self.assertFalse(got["measured"])
        self.assertEqual(got["status"], M.STATUS_UNMEASURED)
        self.assertIn("журнал объявлений не прочитан", got["reason"])
        self.assertEqual(M.exit_code_for(got), 2)

    def test_an_unreadable_base_is_UNMEASURED_and_returns_two(self):
        declare(self.stage, self.source)
        got = M.build_report(self.stage, base_ref="refs/heads/does-not-exist", now=NOW,
                             env={})
        self.assertFalse(got["measured"])
        self.assertIn("база не прочитана", got["reason"])
        self.assertEqual(M.exit_code_for(got), 2)

    def test_the_hidden_count_alone_does_NOT_redden_a_sighted_stage(self):
        """Цена слепой двери остаётся в отчёте и после починки — красным она не является.

        Иначе прибор был бы красен вечно и его перестали бы читать: ровно тот
        способ, которым сторож превращается в украшение.
        """
        declare(self.stage, self.source)
        got = report_for(self.stage)
        self.assertEqual(got["false_zero"]["hidden"], 1)
        self.assertEqual(M.exit_code_for(got), 0)

    def test_the_report_keeps_every_declared_key_even_when_unmeasured(self):
        """Форма отчёта ПОСТОЯННА: поле не исчезает, оно несёт `None` (инв. #17)."""
        (self.stage / "data" / census.JOURNAL_NAME).unlink()
        got = report_for(self.stage)
        for key in ("status", "measured", "order", "applied", "declaration",
                    "doors", "chosen", "effective", "false_zero"):
            self.assertIn(key, got)
        self.assertIsNone(got["doors"])
        self.assertIsNone(got["chosen"])

    def test_the_instrument_declares_itself_read_only(self):
        declare(self.stage, self.source)
        self.assertFalse(report_for(self.stage)["applied"])


# ───────── ПРОВОДКА: ступень берёт историю через дверь — измерено ИСХОДОМ ─────────

class TestTheStageActuallyUsesTheDoor(SceneMixin):
    """Контроль проводки меряет ВЕРДИКТ соседа, а не наличие аргумента.

    Утверждение «`run` зовёт `resolve_history_root`» к поведению слепо и
    контролем не является (ADR-333): оно останется верным и тогда, когда
    разрешённый корень до `run_census` не доедет.
    """

    def test_the_census_stage_answers_the_question_once_the_door_is_declared(self):
        declare(self.stage, self.source)
        doc = census.run(root=str(self.stage))["doc"]
        self.assertEqual(doc["history_door"], M.DOOR_DECLARED)
        self.assertEqual(doc["price"]["lost_coordinates"], 1)
        self.assertEqual(doc["price"]["retired_at_base"], 1)
        self.assertEqual(doc["price"]["retirement_unmeasured"], 0)

    def test_the_same_stage_WITHOUT_the_declaration_reports_the_false_zero(self):
        """Обратная сторона той же проводки — и это живое состояние до ADR-688."""
        doc = census.run(root=str(self.stage))["doc"]
        self.assertIsNone(doc["history_door"])
        self.assertEqual(doc["price"]["lost_coordinates"], 0)
        self.assertEqual(doc["price"]["retirement_unmeasured"], 2)

    def test_a_door_that_raises_does_not_bring_the_census_down(self):
        """Дверь не смеет валить мост: отказ НАЗВАН в артефакте, перепись идёт."""
        declare(self.stage, self.source)
        original = M.resolve_history_root

        def _boom(*_a, **_k):
            raise RuntimeError("дверь сломана")

        M.resolve_history_root = _boom
        try:
            doc = census.run(root=str(self.stage))["doc"]
        finally:
            M.resolve_history_root = original
        self.assertIn("НЕ РАЗРЕШЕНА", str(doc["history_door"]))
        # Судим по тому, что перепись СВОЮ работу сделала: ось A посчитана. Поле
        # `measured` целого отчёта здесь не предмет — его решает ось квитанций,
        # у которой своё тридцатидневное окно от СТЕННЫХ часов, и утверждать о
        # нём значило бы завести календарную бомбу (`.claude/rules/deployment.md`).
        self.assertIsNotNone(doc["price"])
        self.assertEqual(doc["price"]["retirement_unmeasured"], 2)


# ──────────────── читатель внутри цикла: шаг 0-офис и мост ────────────────

class TestTheArtifactHasAReaderInsideTheCycle(unittest.TestCase):
    """Артефакт без читателя — находка, которой никто не увидит (ADR-526/683)."""

    @staticmethod
    def _office():
        repo = Path(M.__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_cor_hdp", str(repo / "scripts" / "consume_office_reports.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _report(self) -> dict:
        return {
            "generated_at": "2026-09-28T12:00:00Z", "order": M.ORDER, "applied": False,
            "measured": True, "status": M.STATUS_CHOSEN, "reason": None,
            "base_ref": "origin/main",
            "declaration": {"path": "architecture/history_roots.json", "measured": True,
                            "reason": None, "roots_declared": 1,
                            "env_var": "SPA_HISTORY_ROOT"},
            "doors": [
                {"door": M.DOOR_ENV, "named_by": "SPA_HISTORY_ROOT (окружение)",
                 "root": None, "state": M.STATE_NOT_NAMED,
                 "reason": "переменная SPA_HISTORY_ROOT не задана", "shallow": None,
                 "price": None, "checkable_by": "data/history_door_price.json",
                 "deliverable_by": M.BY_OWNER, "deliverable_reason": "plist",
                 "outcome": {"measured": False, "reason": "спрашивать негде",
                             "latency_seconds": None}},
                {"door": M.DOOR_DECLARED, "named_by": "объявление", "root": "/m",
                 "state": M.STATE_USABLE, "reason": None, "shallow": False,
                 "price": {"measured": True, "loose_kib": 1, "pack_kib": 2,
                           "total_kib": 3, "commits_reachable": 27410},
                 "checkable_by": "architecture/history_roots.json",
                 "deliverable_by": M.BY_AGENT, "deliverable_reason": "ADR-285",
                 "outcome": {"measured": True, "reason": None, "latency_seconds": 2.0,
                             "population": 6, "answered": 6, "blind": 0,
                             "lost_coordinates": 5, "retired_at_base": 1,
                             "retirement_unmeasured": 0,
                             "sessions_on_lost_coordinates": 5,
                             "subjects_on_lost_coordinates": 1}},
                {"door": M.DOOR_OWN, "named_by": "своё дерево", "root": "/p",
                 "state": M.STATE_SHALLOW, "reason": "история ОБРЕЗАНА", "shallow": True,
                 "price": {"measured": True, "loose_kib": 1920000, "pack_kib": 195000,
                           "total_kib": 2115000, "commits_reachable": 443},
                 "checkable_by": "git rev-parse", "deliverable_by": M.BY_OWNER,
                 "deliverable_reason": "прод-дерево", "outcome":
                     {"measured": True, "reason": None, "latency_seconds": 0.3,
                      "population": 6, "answered": 0, "blind": 6,
                      "lost_coordinates": 0, "retired_at_base": 0,
                      "retirement_unmeasured": 6,
                      "sessions_on_lost_coordinates": 0,
                      "subjects_on_lost_coordinates": 0}},
            ],
            "chosen": {"door": M.DOOR_DECLARED, "root": "/m", "named_by": "объявление",
                       "why": "пригодна"},
            "effective": {"root": "/m", "door": M.DOOR_DECLARED, "stage_is_blind": False,
                          "agent_deliverable_doors": [M.DOOR_DECLARED],
                          "owner_doors_named": [M.DOOR_ENV, M.DOOR_OWN]},
            "false_zero": {"metric": "lost_coordinates", "through_own_door": 0,
                           "through_chosen_door": 5, "hidden": 5, "named": "ноль врёт"},
        }

    def test_the_office_step_prints_the_producers_own_lines(self):
        """Ветка меряется ИСХОДОМ: печатает ли офис строки ПРОИЗВОДИТЕЛЯ.

        Проверка подстрокой по исходнику шага сказала бы «ветка есть» и о
        мёртвой ветке тоже.
        """
        text = "\n".join(self._office()._summarize_json(
            "data/history_door_price.json", self._report()))
        self.assertTrue("ГЛАВНОЕ ЧИСЛО" in text,
                        "офис не напечатал главное число прибора")
        self.assertTrue("спрятано 5" in text, "офис не напечатал цену слепой двери")
        self.assertTrue(M.DOOR_DECLARED in text, "офис не назвал дверь ступени")

    def test_the_artifact_is_declared_in_the_office_schema_and_module_map(self):
        office = self._office()
        self.assertIn("history_door_price.json", office._READ_SCHEMA)
        for key in ("doors", "chosen", "effective", "false_zero", "declaration"):
            self.assertIn(key, office._READ_SCHEMA["history_door_price.json"])

    def test_the_bridge_declares_the_stage_and_its_artifact(self):
        from spa_core.monitoring import findings_bridge as bridge
        self.assertIn("history_door_price", bridge.CENSUS_STAGE)
        self.assertEqual(bridge.CENSUS_PRODUCT["history_door_price"]["artifact"],
                         f"data/{M.ARTIFACT_NAME}")

    def test_the_artifact_is_declared_in_the_manifest_with_a_producer_and_an_slo(self):
        repo = Path(M.__file__).resolve().parents[2]
        manifest = json.loads((repo / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        entry = next((a for a in manifest["artifacts"]
                      if a.get("path") == f"data/{M.ARTIFACT_NAME}"), None)
        self.assertIsNotNone(entry, "артефакт не объявлен в манифесте")
        self.assertEqual(entry["producer"], "com.spa.decision_loop")
        self.assertEqual(entry["slo_hours"], 12)
        agent = next(a for a in manifest["agents"]
                     if a.get("label") == "com.spa.decision_loop")
        self.assertIn(f"data/{M.ARTIFACT_NAME}",
                      [e.get("artifact") for e in agent["produces"]])

    def test_the_declaration_shipped_with_the_code_names_a_full_clone(self):
        """Объявление — часть доставки: без него проводка зелена, а ступень слепа."""
        repo = Path(M.__file__).resolve().parents[2]
        decl = M.read_declaration(repo)
        self.assertTrue(decl["measured"], decl["reason"])
        self.assertGreaterEqual(len(decl["roots"]), 1)
        self.assertEqual(decl["env_var"], M.DEFAULT_ENV_VAR)


# ───────────────────────── отрисовка прибора ─────────────────────────

class TestFormatting(SceneMixin):

    def test_the_unmeasured_report_says_so_in_its_first_line(self):
        (self.stage / "data" / census.JOURNAL_NAME).unlink()
        lines = M.format_report(report_for(self.stage))
        self.assertTrue(lines[0].startswith("откуда ступень берёт историю"))
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])

    def test_a_report_without_the_doors_section_is_NOT_rendered_as_clean(self):
        """Раздела нет ⇒ «не измерено», а не пустой обзор (инв. #17)."""
        declare(self.stage, self.source)
        got = report_for(self.stage)
        got["doors"] = None
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(M.format_report(got)))

    def test_bytes_of_an_unmeasured_store_are_printed_as_unmeasured(self):
        text = "\n".join(M.format_report(report_for(self.stage)))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("ADVISORY", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
