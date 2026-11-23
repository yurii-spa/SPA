"""Одиннадцатая дверь семейства доставки (ADR-1073): перепись обязана НАЗЫВАТЬ
модуль, уезжающий рядом с ней.

Каждый тест здесь — положительный контроль из ЖИЗНИ, а не украшение
(`.claude/rules/deployment.md` § «Проверка сторожа сторожей»). Авария, которую
они воспроизводят, измерена на `origin/main`: с рождения переписи 29.08
(`a2c412ab3`) по 23.11 **31** вершина добавила публичный модуль
`spa_core/analytics/`, и **31 из 31** увезла перепись, этот модуль НЕ
называющую — каждая красила `main` живым сторожем
`test_untiered_census.CensusMarkupMatchesMeasurement`.

Дешёвая ось «тронул ли коммит перепись» отвечает «да» у ТРЁХ из 31, и у всех
трёх перепись своего же модуля не называет: генератор звали в дереве, где нового
модуля ещё не было. Поэтому гейт спрашивает ИМЯ, а не присутствие файла в
наборе, — и тесты ниже проверяют именно это различие.

# FROZEN-DATE-OK: исторический инцидент — даты 2026-08-29 и 2026-11-23 суть сам
# предмет замера (окно, в котором класс измерен), а не отметка свежести: ни один
# вердикт здесь от календаря не зависит, стенных часов в файле нет вовсе.
"""
import importlib.util

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _push():
    return _load("_push_for_census_gate_test", "push_to_github.py")


def _generator():
    return _load("_gen_for_census_gate_test", "scripts/audit_untiered_analytics.py")


def _scene(tmp: Path, census_names_the_module: bool):
    """Одноразовый репозиторий с `origin`, где модуля ещё нет."""
    upstream = tmp / "upstream.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)],
                   check=True, capture_output=True)
    work = tmp / "work"
    subprocess.run(["git", "init", "-b", "main", str(work)],
                   check=True, capture_output=True)
    # Имя ветки — ВХОД СЦЕНЫ (`-b main`), а не умолчание хоста: на
    # `ubuntu-latest` `init.defaultBranch` даёт `master`, и ссылка
    # `origin/main` молча не нашлась бы (§ GIT-ОКРУЖЕНИЕ правила доставки).
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(work), "config", k, v], check=True)
    census_dir = work / "spa_core" / "analytics"
    census_dir.mkdir(parents=True)
    (census_dir / "_untiered_census.py").write_text(
        "from typing import Dict\n"
        "NOT_A_SIGNAL_MODULE: Dict[str, str] = {\n"
        "    'already_there': 'нет публичного класса с методом-входом',\n"
        "}\n", encoding="utf-8")
    (census_dir / "already_there.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "base"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin",
                    str(upstream)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "fetch", "-q", "origin"],
                   check=True, capture_output=True)
    # ── теперь цикл ДОБАВЛЯЕТ новый модуль ──
    new_mod = census_dir / "brand_new_census.py"
    new_mod.write_text("y = 2\n", encoding="utf-8")
    files = [str(new_mod)]
    if census_names_the_module:
        (census_dir / "_untiered_census.py").write_text(
            "from typing import Dict\n"
            "NOT_A_SIGNAL_MODULE: Dict[str, str] = {\n"
            "    'already_there': 'нет публичного класса с методом-входом',\n"
            "    'brand_new_census': 'нет публичного класса с методом-входом',\n"
            "}\n", encoding="utf-8")
        files.append(str(census_dir / "_untiered_census.py"))
    return files



class BothDeliveryDoorsCallOneImplementation(unittest.TestCase):
    """Дверей доставки две, реализация обязана быть ОДНА.

    Разойдись они — одна отказывала бы, а вторая молча везла модуль, которого
    перепись не называет, то есть класс проходил бы целиком через вторую дверь.
    """

    def test_root_door_exposes_the_gate(self):
        push = _push()
        for door in ("enforce_delivery_census_names", "census_after_delivery",
                     "delivery_census_name_summary",
                     "DeliveredModuleIsNotInTheCensus", "UNCENSUSED_MODULE_EXIT"):
            self.assertTrue(hasattr(push, door),
                            f"корневая дверь доставки не несёт `{door}`")

    def test_batch_door_imports_it_and_does_not_copy_it(self):
        text = (REPO_ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
        self.assertIn("enforce_delivery_census_names = _root_push."
                      "enforce_delivery_census_names", text,
                      "batch-CLI не ВВОЗИТ гейт — своя копия здесь запрещена")
        self.assertNotIn("def enforce_delivery_census_names", text,
                         "batch-CLI объявил СВОЮ копию гейта: разойдись она с "
                         "корневой — класс уехал бы через вторую дверь")

    def test_batch_door_calls_the_gate(self):
        text = (REPO_ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
        self.assertIn("enforce_delivery_census_names(all_files", text,
                      "batch-CLI гейт ввозит, но не ЗОВЁТ — ввоз без зова есть "
                      "ложное усиление")

    def test_the_exit_code_is_its_own(self):
        push = _push()
        self.assertEqual(push.UNCENSUSED_MODULE_EXIT, 19)
        for neighbour in ("CARDLESS_BOARD_EXIT", "STALE_BOARD_STATUS_EXIT",
                          "FAT_ADR_TITLE_EXIT", "NOT_PYTHON_EXIT"):
            self.assertNotEqual(
                push.UNCENSUSED_MODULE_EXIT, getattr(push, neighbour),
                f"код одиннадцатой двери совпал с `{neighbour}` — читатель кода "
                f"не отличил бы один отказ от другого")

    def test_every_name_the_batch_handler_mentions_actually_resolves(self):
        """Имя в `except`, которого в модуле НЕТ, превращает отказ в крах.

        Контроль из жизни: на чистом `origin/main` батч ссылался на
        `DeliveredCardBoardStatusDiffers` и `STALE_BOARD_STATUS_EXIT`, не ввезя
        ни одно, — и ровно в миг отказа оси 2 (ADR-1062) поднимал `NameError`
        вместо названной причины, с кодом 1 вместо 18. Звёздного импорта в файле
        нет, так что проверка «имя разрешается» этот класс и ловит.
        """
        batch = _load("_batch_for_census_gate_test", "push_to_github_batch.py")
        text = (REPO_ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
        import ast
        import builtins
        tree = ast.parse(text)
        missing = []

        def resolves(ident: str) -> bool:
            # Встроенные имена (`Exception`, `RuntimeError`) разрешаются областью
            # builtins, а атрибутами модуля НЕ являются. Считать их пропавшими —
            # дефект МЕРКИ, а не находка: первая редакция этой пробы назвала
            # ровно их и была красной на починенном файле.
            return hasattr(batch, ident) or hasattr(builtins, ident)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                for sub in ast.walk(handler.type) if handler.type else []:
                    if isinstance(sub, ast.Name) and not resolves(sub.id):
                        missing.append(sub.id)
                for sub in ast.walk(handler):
                    if isinstance(sub, ast.Call) and \
                       isinstance(sub.func, ast.Attribute) and \
                       sub.func.attr == "exit":
                        for a in sub.args:
                            if isinstance(a, ast.Name) and not resolves(a.id):
                                missing.append(a.id)
        self.assertEqual(sorted(set(missing)), [],
                         f"batch-CLI ссылается на имена, которых в нём нет — в "
                         f"миг отказа это NameError, а не отказ: "
                         f"{sorted(set(missing))}")


class ThePathDoorIsTheGeneratorsOwn(unittest.TestCase):
    """«Путь → имя переписи» — одно правило, и живёт оно у ПИСАТЕЛЯ."""

    def test_the_generator_owns_the_rule(self):
        gen = _generator()
        self.assertTrue(hasattr(gen, "census_key_for_path"))
        self.assertTrue(hasattr(gen, "census_names_from_source"))

    def test_the_gate_does_not_carry_its_own_copy_of_the_rule(self):
        text = (REPO_ROOT / "push_to_github.py").read_text(encoding="utf-8")
        gate = text[text.index("def enforce_delivery_census_names"):]
        gate = gate[:gate.index("\ndef delivery_census_name_summary")]
        # Тот же урок, что у соседней пробы: зов меряется AST, а не подстрокой —
        # иначе имя двери в докстринге гейта зачлось бы за обращение к ней.
        import ast
        fn = next(n for n in ast.walk(ast.parse(gate))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "enforce_delivery_census_names")
        attr_calls = {n.func.attr for n in ast.walk(fn)
                      if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute)}
        self.assertIn("census_key_for_path", attr_calls,
                      "гейт не ЗОВЁТ дверь генератора — своя копия правила "
                      "принадлежности разошлась бы с ним молча")
        self.assertNotIn('.endswith(".py")', gate,
                         "гейт решает принадлежность САМ: это вторая копия "
                         "правила рядом с генераторской")

    def test_the_rule_answers_the_measured_cases(self):
        gen = _generator()
        self.assertEqual(
            gen.census_key_for_path(
                "spa_core/analytics/foreign_carrier_cadence_census.py"),
            "foreign_carrier_cadence_census")
        self.assertEqual(gen.census_key_for_path("spa_core/analytics/gross_of/x.py"),
                         "gross_of.x",
                         "вложенный модуль обязан читаться как `gross_of.x`: "
                         "иначе 15 зарегистрированных ложно уйдут «вне тиров»")
        for not_mine in ("spa_core/analytics/_untiered_census.py",
                         "spa_core/analytics/test_x.py",
                         "spa_core/monitoring/x.py",
                         "spa_core/analytics/notes.txt"):
            self.assertIsNone(gen.census_key_for_path(not_mine),
                              f"{not_mine} переписи не принадлежит")

    def test_disk_scan_uses_the_same_door(self):
        """Круговой контроль: обход диска обязан ЗВАТЬ ту же дверь.

        Меряется AST, а не подстрокой, и это не вкус. Первая редакция этой
        пробы искала имя двери в ТЕКСТЕ срезанной функции — и мутация, которая
        вернула обходу его собственную копию правила, ВЫЖИЛА: имя двери стояло
        в ДОКСТРИНГЕ («Само правило живёт в :func:`census_key_for_path`»), то
        есть проба зачла прозу зовом. Тот же класс уже оплачен проектом
        (ADR-1072 записал его про собственный греп; `has_entrypoint` читал
        сырой текст и считал `__main__` в прозе).
        """
        import ast
        text = (REPO_ROOT / "scripts" / "audit_untiered_analytics.py").read_text(
            encoding="utf-8")
        tree = ast.parse(text)
        scan = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)
                     and n.name == "modules_on_disk"), None)
        self.assertIsNotNone(scan, "функции `modules_on_disk` в генераторе нет")
        calls = {n.func.id for n in ast.walk(scan)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("census_key_for_path", calls,
                      "`modules_on_disk` не ЗОВЁТ дверь (упоминание в докстринге "
                      "зовом не является) — две копии правила разошлись бы молча")


class TheReaderAgreesWithTheWriter(unittest.TestCase):
    """Круговая сверка: читатель байтов обязан видеть то, что пишет писатель."""

    def test_reader_reproduces_ALL_UNTIERED_of_the_live_census(self):
        gen = _generator()
        text = (REPO_ROOT / "spa_core" / "analytics"
                / "_untiered_census.py").read_text(encoding="utf-8")
        names, why = gen.census_names_from_source(text)
        self.assertIsNone(why, f"живая перепись не прочитана: {why}")
        from spa_core.analytics import _untiered_census as census
        self.assertEqual(names, set(census.ALL_UNTIERED),
                         "читатель по байтам и `ALL_UNTIERED` расходятся — "
                         "гейт судил бы не тот набор, что сторож")

    def test_every_declared_bucket_is_one_the_writer_emits(self):
        gen = _generator()
        emitted = (REPO_ROOT / "scripts"
                   / "audit_untiered_analytics.py").read_text(encoding="utf-8")
        body = emitted[emitted.index("def emit_markup"):]
        for bucket in gen.CENSUS_BUCKETS:
            self.assertIn(f"{bucket}: Dict[str, str]", body,
                          f"читатель ждёт набор `{bucket}`, а писатель его не "
                          f"печатает — целая корзина стала бы невидимой, и "
                          f"«имя не названо» было бы неотличимо от «в эту "
                          f"корзину не заглянули»")

    def test_the_union_the_census_builds_is_the_one_the_reader_reads(self):
        """Набор, объявленный читателю, обязан быть тем, из которого файл
        складывает `ALL_UNTIERED`: иначе читатель видит больше или меньше."""
        gen = _generator()
        text = (REPO_ROOT / "spa_core" / "analytics"
                / "_untiered_census.py").read_text(encoding="utf-8")
        union = text[text.index("OUT_OF_DENOMINATOR = ("):]
        for bucket in gen.CENSUS_BUCKETS:
            self.assertIn(bucket, union,
                          f"`{bucket}` объявлен читателю, но в объединение "
                          f"`ALL_UNTIERED` не входит")


class ThreeOutcomesAreDistinguishable(unittest.TestCase):
    """Инв. #17: прочитано · не разбирается · ни одного набора — РАЗНЫЕ исходы."""

    def test_unparsable_text_is_unmeasured_not_an_empty_set(self):
        gen = _generator()
        names, why = gen.census_names_from_source("def (")
        self.assertIsNone(names,
                          "битый текст дал ПУСТОЙ набор вместо «не измерено» — "
                          "пустой набор означал бы отказ по каждому модулю "
                          "набора от одного непонятого файла")
        self.assertIn("не разбирается", why)

    def test_text_without_any_bucket_is_unmeasured_with_a_named_cause(self):
        gen = _generator()
        names, why = gen.census_names_from_source("X = {'a': 'b'}\n")
        self.assertIsNone(names)
        self.assertIn("ни одного объявленного набора", why)

    def test_a_real_census_is_measured_and_says_so(self):
        gen = _generator()
        names, why = gen.census_names_from_source(
            "NOT_A_SIGNAL_MODULE: Dict[str, str] = {'alpha': 'нет класса'}\n")
        self.assertIsNone(why)
        self.assertEqual(names, {"alpha"},
                         "измеренный набор обязан отличаться от «не измерено» "
                         "ЗНАЧЕНИЕМ, а не только причиной")


class TheGateRefusesOnTheMeasuredFailureAndPassesOnTheFix(unittest.TestCase):
    """Контроль в ОБЕ стороны на НАСТОЯЩЕМ гейте, в одноразовом репозитории.

    Сцена воспроизводит аварию: НОВЫЙ модуль аналитики уезжает, перепись
    (которая останется на origin) его не называет. Обратная половина —
    перепись, перемеренная из дерева, где модуль уже лежит.
    """

    def test_it_REFUSES_when_the_census_does_not_name_the_new_module(self):
        import tempfile
        push = _push()
        with tempfile.TemporaryDirectory() as td:
            files = _scene(Path(td), census_names_the_module=False)
            with self.assertRaises(push.DeliveredModuleIsNotInTheCensus) as ctx:
                push.enforce_delivery_census_names(files, runner_file=str(REPO_ROOT / "push_to_github.py"))
        self.assertIn("brand_new_census", str(ctx.exception))
        self.assertIn("--emit-markup", str(ctx.exception),
                      "отказ обязан НАЗВАТЬ команду починки")

    def test_it_PASSES_when_the_delivered_census_names_it(self):
        import tempfile
        push = _push()
        with tempfile.TemporaryDirectory() as td:
            files = _scene(Path(td), census_names_the_module=True)
            verdicts = push.enforce_delivery_census_names(
                files, runner_file=str(REPO_ROOT / "push_to_github.py"))
        states = {v["state"] for v in verdicts}
        self.assertEqual(states, {"named"},
                         f"починенная сцена не прошла: {verdicts}")

    def test_the_named_override_turns_the_refusal_into_a_named_warning(self):
        import tempfile
        push = _push()
        with tempfile.TemporaryDirectory() as td:
            files = _scene(Path(td), census_names_the_module=False)
            verdicts = push.enforce_delivery_census_names(
                files, allow=True, runner_file=str(REPO_ROOT / "push_to_github.py"))
        self.assertEqual([v["state"] for v in verdicts], ["absent"],
                         "обход обязан СОХРАНИТЬ вердикт, а не стереть его")

    def test_a_set_without_analytics_modules_is_its_own_outcome(self):
        push = _push()
        verdicts = push.enforce_delivery_census_names(
            [str(REPO_ROOT / "docs" / "STATE.md")], runner_file=str(REPO_ROOT / "push_to_github.py"))
        self.assertEqual(verdicts, [])
        self.assertIn("модулей аналитики в наборе нет",
                      push.delivery_census_name_summary(),
                      "«судить нечего» и «гейт не зван» обязаны различаться")

    def test_the_gate_never_called_is_not_the_same_as_nothing_to_judge(self):
        push = _push()
        self.assertIn("не зван НИ РАЗУ", push.delivery_census_name_summary(),
                      "свежий модуль обязан говорить «гейт не зван», а не "
                      "«названы все 0»")


class TheQuestionIsAboutOriginAfterDelivery(unittest.TestCase):
    """Спрашивать ДЕРЕВО значило бы зеленеть ровно в предмете замера.

    Все ТРИ вершины, что генератор звали, перепись в дереве имели — и всё равно
    своего модуля не называли. Источник обязан быть один из двух: уезжающие
    байты либо `origin/<branch>`, и ВЫБОР обязан печататься.
    """

    def test_the_source_of_the_census_is_named_in_the_verdict(self):
        push = _push()
        text = (REPO_ROOT / "push_to_github.py").read_text(encoding="utf-8")
        fn = text[text.index("def census_after_delivery"):]
        fn = fn[:fn.index("\ndef _module_is_new_on_origin")]
        self.assertIn("read_delivery_bytes", fn,
                      "байты уезжающей переписи обязаны идти ЕДИНСТВЕННОЙ "
                      "дверью (ADR-774), иначе её предмет вернётся здесь")
        self.assertIn("origin/", fn,
                      "второй источник — ссылка origin; без него гейт судил бы "
                      "дерево, то есть зеленел бы в предмете замера")
        self.assertIn("этим пушем не меняется", fn,
                      "ВЫБОР источника обязан печататься (поправка #1031)")

    def test_a_census_FIXED_IN_THE_TREE_but_NOT_DELIVERED_still_REFUSES(self):
        """РАЗЛИЧАЮЩАЯ сцена: дерево починено, набор доставки — нет.

        Это несущая половина ADR-1073 и ровно случай 28 из 31: цикл
        перегенерировал перепись у себя, но в `--files` её не положил, и на
        origin она не поедет. Спроси гейт ДЕРЕВО — он бы зазеленел ровно здесь.

        Сцена нужна именно РАЗЛИЧАЮЩАЯ: пока перепись и в дереве, и в наборе
        несла одно и то же, мутация «спрашивать дерево» ВЫЖИВАЛА — набор упавших
        имён не менялся (тот же урок, что в ADR-1060: одинаковая доска в HEAD и
        в origin/main не различает источник).
        """
        import tempfile
        push = _push()
        with tempfile.TemporaryDirectory() as td:
            # Сцена кладёт модуль и ПОЧИНЕННУЮ перепись в дерево, а в набор
            # доставки отдаёт ТОЛЬКО модуль.
            files = _scene(Path(td), census_names_the_module=True)
            only_the_module = [f for f in files
                               if not f.endswith("_untiered_census.py")]
            self.assertEqual(len(only_the_module), 1, "сцена собрана неверно")
            with self.assertRaises(push.DeliveredModuleIsNotInTheCensus) as ctx:
                push.enforce_delivery_census_names(
                    only_the_module,
                    runner_file=str(REPO_ROOT / "push_to_github.py"))
        self.assertIn("brand_new_census", str(ctx.exception))
        self.assertIn("origin/", str(ctx.exception),
                      "отказ обязан НАЗВАТЬ источник переписи — им была ссылка "
                      "origin, а не починенное дерево")

    def test_a_prober_without_a_door_is_UNMEASURED_not_a_crash(self):
        """Прибор без двери разбора — третий исход, а не падение.

        Дыру нашёл мутационный прогон: ни одна сцена не подавала гейту прибор
        БЕЗ двери, и снятие проверки `hasattr` ВЫЖИВАЛО. Без проверки гейт
        обратился бы к несуществующему атрибуту уже после ввоза — то есть
        «прибора нет» стало бы крахом вместо названной причины.
        """
        import tempfile
        push = _push()
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td) / "fake_tree"
            (fake_root / "scripts").mkdir(parents=True)
            # Прибор ВВОЗИТСЯ, но несёт лишь ОДНУ дверь из двух.
            (fake_root / "scripts" / "audit_untiered_analytics.py").write_text(
                "def census_key_for_path(p):\n"
                "    return 'brand_new_census'\n", encoding="utf-8")
            files = _scene(Path(td), census_names_the_module=False)
            verdicts = push.enforce_delivery_census_names(
                files, runner_file=str(fake_root / "push_to_github.py"))
        self.assertEqual([v["state"] for v in verdicts], ["unmeasured"],
                         f"прибор без двери судился не третьим исходом: {verdicts}")
        self.assertIn("census_names_from_source", verdicts[0]["reason"])
        self.assertIn("ЗАПРЕЩЕНО", verdicts[0]["reason"],
                      "причина обязана НАЗВАТЬ, что своя копия разбора запрещена")

    def test_a_pre_existing_debt_is_named_but_does_not_block(self):
        """Отказ за ДАВНИЙ долг покраснел бы на ВЕРНОМ состоянии.

        Перепись, устаревшая про модуль, который на origin лежит давно, — тоже
        правда, но не ЭТОЙ доставки: запереть чужую починку из-за неё значило бы
        чинить симптом ценой ложного отказа.
        """
        import tempfile
        push = _push()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._base = self._scene_with_unnamed_old_module(tmp)
            verdicts = push.enforce_delivery_census_names(
                self._base, runner_file=str(REPO_ROOT / "push_to_github.py"))
        self.assertEqual([v["state"] for v in verdicts], ["pre_existing"],
                         f"давний долг судился как отказ: {verdicts}")

    def _scene_with_unnamed_old_module(self, tmp: Path):
        upstream = tmp / "up.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)],
                       check=True, capture_output=True)
        work = tmp / "w"
        subprocess.run(["git", "init", "-b", "main", str(work)], check=True,
                       capture_output=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(work), "config", k, v], check=True)
        d = work / "spa_core" / "analytics"
        d.mkdir(parents=True)
        (d / "_untiered_census.py").write_text(
            "from typing import Dict\n"
            "NOT_A_SIGNAL_MODULE: Dict[str, str] = {'other': 'нет класса'}\n",
            encoding="utf-8")
        (d / "old_unnamed.py").write_text("z = 3\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(work), "add", "-A"], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(work), "commit", "-m", "base"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "remote", "add", "origin",
                        str(upstream)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "fetch", "-q", "origin"],
                       check=True, capture_output=True)
        (d / "old_unnamed.py").write_text("z = 4\n", encoding="utf-8")
        return [str(d / "old_unnamed.py")]


class TheLiveCensusCoversTheLiveTree(unittest.TestCase):
    """То, ради чего всё: сторож переписи обязан быть ЗЕЛЁН на этом дереве."""

    def test_no_public_analytics_module_is_outside_both_registry_and_census(self):
        gen = _generator()
        from spa_core.analytics import _untiered_census as census
        missed = sorted(set(gen.untiered_modules()) - set(census.ALL_UNTIERED))
        self.assertEqual(
            missed, [],
            f"модул(и) вне тиров И вне переписи: {missed[:8]} — для знаменателя "
            f"метрики они не существуют; починка: `python3 "
            f"scripts/audit_untiered_analytics.py --emit-markup`")


if __name__ == "__main__":
    unittest.main()
