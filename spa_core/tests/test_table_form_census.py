"""Форма «таблица с длинными строками, несущая язык права изменения» — G58 п. 1.

ADR-435 назвал ОДНУ таблицу `CLAUDE.md`, держащую тринадцать пар, и сам же
поставил вопрос: «одна таблица» может оказаться свойством ВЫБОРКИ, а не
репозитория. Разница не академическая: форма, живущая только в выборке,
чинится одним абзацем; форма, живущая по репозиторию, одним абзацем не
чинится вовсе.

Сцены строятся из ``tmp_path``, а пределы берутся ВЫЧИСЛЕНИЕМ от самих
констант модуля: литерал `400` здесь был бы второй копией порога — ровно тем
классом, перепись которого этот модуль и есть.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import rule_second_copy_census as census
# Имена, существующие на `origin` ДО этой правки, берутся ввозом: тест о них
# не спорит. Всё НОВОЕ зовётся через модуль (`census.X`) намеренно — иначе
# ввоз падал бы на сборе, один ERROR подменил бы 27 вердиктов, и контроль
# «что именно тут новое» перестал бы существовать.
from spa_core.monitoring.rule_second_copy_census import (
    ADR_REGISTRY, AUTHORITY_MARKS, MAX_DECLARING_LINE,
    MAX_DECLARING_PARAGRAPH, RULE_DIR, RULE_TEXT, WIDE_BY_BOTH,
    WIDE_BY_LINES, WIDE_BY_LINE_LENGTH)

#: Язык права изменения — берётся ИЗ модуля, а не перепечатывается: сцена,
#: несущая свою копию маркера, молча переживёт переименование маркера.
AUTHORITY = AUTHORITY_MARKS[0]


def _block(text):
    """Абзац в форме, которую отдаёт ``declaring_paragraphs``."""
    return [(i, line) for i, line in enumerate(text.splitlines(), 1)
            if line.strip()]


def _long_cell():
    """Ячейка, гарантированно делающая строку длиннее предела строки."""
    return "x" * (MAX_DECLARING_LINE + 10)


def _table(rows, cell="краткая ячейка", header=None):
    """Markdown-таблица из ``rows`` строк тела с ячейкой ``cell``."""
    out = [header or "| что | сколько |", "|---|---|"]
    out += [f"| строка {i} | {cell} |" for i in range(rows)]
    return "\n".join(out)


class TableDetector(unittest.TestCase):
    """Признак формы обязан быть позываемым отдельно — иначе он непроверяем."""

    def test_a_real_table_is_a_table(self):
        self.assertTrue(census.is_markdown_table(_block(_table(2))))

    def test_prose_without_pipes_is_not_a_table(self):
        self.assertFalse(census.is_markdown_table(_block(
            "обычный абзац правила\nбез единой трубы")))

    def test_pipes_without_a_separator_row_are_not_a_table(self):
        """Труба живёт в коде, в цитате и в перечне.

        Считать её таблицей значило бы посчитать формой то, чего в тексте нет,
        — и раздуть ответ заказу за счёт чужих абзацев.
        """
        self.assertFalse(census.is_markdown_table(_block(
            "| a | b |\n| c | d |\n| e | f |")))

    def test_a_separator_alone_is_not_a_table(self):
        """Шапка и хотя бы одна строка тела — часть признака, а не украшение."""
        self.assertFalse(census.is_markdown_table(_block("|---|---|")))

    def test_the_body_row_requirement_is_the_declared_constant(self):
        """Порог трубных строк объявлен константой, и тест меряет ЕЁ.

        Литерал `2` здесь сделал бы тест слепым к изменению константы — то
        есть завёл бы вторую копию порога в сторожа этой самой переписи.
        """
        just_under = ["| ш | ш |"] * (census.MIN_TABLE_PIPE_LINES - 1)
        block = _block("\n".join(["|---|---|"] + just_under))
        self.assertFalse(census.is_markdown_table(block))
        block = _block("\n".join(["|---|---|"] + just_under + ["| ещё | одна |"]))
        self.assertTrue(census.is_markdown_table(block))

    def test_alignment_colons_are_still_a_separator(self):
        self.assertTrue(census.is_markdown_table(_block(
            "| a | b |\n| :--- | ---: |\n| c | d |")))


class Scene:
    """Дерево-сцена: объявленный канал правил + контроль `docs/` и ADR."""

    def __init__(self, root: Path):
        self.root = root
        (root / RULE_DIR).mkdir(parents=True, exist_ok=True)
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs/decisions").mkdir(parents=True, exist_ok=True)
        (root / RULE_TEXT).write_text("# правило\n\nобычный текст\n",
                                      encoding="utf-8")

    def write(self, rel, body):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def wide_table_by_line(self, rel, authority=True):
        """Таблица, отброшенная ДЛИНОЙ СТРОКИ — форма заказа."""
        mark = AUTHORITY if authority else "просто пояснение"
        return self.write(rel, f"# документ\n\n{_table(2, _long_cell())}\n"
                               f"| {mark} | да |\n")

    def wide_table_by_lines(self, rel):
        """Таблица, отброшенная ЧИСЛОМ строк — форма ДРУГАЯ."""
        return self.write(
            rel, f"# документ\n\n{_table(MAX_DECLARING_PARAGRAPH + 4)}\n"
                 f"| {AUTHORITY} | да |\n")


class FormCounting(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.scene = Scene(self.root)
        self.addCleanup(self._tmp.cleanup)

    def test_the_form_is_counted_in_the_declared_rule_channel(self):
        self.scene.wide_table_by_line(f"{RULE_DIR}/some-rule.md")
        data = census.table_form_population(self.root, census.TABLE_CHANNEL_RULES)
        self.assertEqual(data["form_long_line"], 1)
        self.assertEqual(data["form_by_reason"][WIDE_BY_LINE_LENGTH], 1)

    def test_a_wide_table_without_authority_language_is_not_the_form(self):
        """Отбор — про ПРАВО менять число, а не про ширину.

        Без этого различения формой стала бы любая широкая таблица, и ответ
        заказу вырос бы на весь репозиторий, ничего о нём не сказав.
        """
        self.scene.wide_table_by_line(f"{RULE_DIR}/some-rule.md",
                                      authority=False)
        data = census.table_form_population(self.root, census.TABLE_CHANNEL_RULES)
        self.assertEqual(data["form_long_line"], 0)
        self.assertEqual(data["wide_paragraphs"], 1)

    def test_a_narrow_table_with_authority_language_is_not_the_form(self):
        """Узкую таблицу мера пути ЧИТАЕТ — слепоты, о которой заказ, там нет."""
        self.scene.write(f"{RULE_DIR}/some-rule.md",
                         f"# правило\n\n{_table(2)}\n| {AUTHORITY} | да |\n")
        data = census.table_form_population(self.root, census.TABLE_CHANNEL_RULES)
        self.assertEqual(data["form_long_line"], 0)
        self.assertEqual(data["tables"], 1)

    def test_a_table_wide_only_by_line_count_is_a_different_form(self):
        """Заказ дословно про ДЛИННЫЕ СТРОКИ.

        Предел строки и предел абзаца защищают от разного; сложить их в одно
        число значило бы ответить не на тот вопрос — и «одна таблица» стала бы
        «две» без единого нового наблюдения.
        """
        self.scene.wide_table_by_lines(f"{RULE_DIR}/some-rule.md")
        data = census.table_form_population(self.root, census.TABLE_CHANNEL_RULES)
        self.assertEqual(data["form_by_reason"][WIDE_BY_LINES], 1)
        self.assertEqual(data["form_long_line"], 0)
        self.assertEqual(data["form_any_reason"], 1)

    def test_a_table_wide_by_both_limits_counts_as_the_form(self):
        """Длинная строка есть длинная строка, даже если абзац ещё и длинный."""
        self.scene.write(
            f"{RULE_DIR}/some-rule.md",
            f"# правило\n\n{_table(MAX_DECLARING_PARAGRAPH + 4, _long_cell())}\n"
            f"| {AUTHORITY} | да |\n")
        data = census.table_form_population(self.root, census.TABLE_CHANNEL_RULES)
        self.assertEqual(data["form_by_reason"][WIDE_BY_BOTH], 1)
        self.assertEqual(data["form_long_line"], 1)

    def test_the_docs_control_excludes_the_adr_and_journal_channels(self):
        """Контроль `docs/` не ест ни ADR, ни журнал.

        Батарея мутаций нашла это исключение без сторожа: снести его можно
        было молча. Оно не косметическое — без него ADR считались бы ДВАЖДЫ
        (в своём канале и в контроле), а журнал, который есть хроника, а не
        правило, поднимал бы число, ничего о репозитории не говоря.
        """
        self.scene.wide_table_by_line("docs/decisions/ADR-000-scene.md")
        self.scene.wide_table_by_line("docs/journal/2026-W00.md")
        self.scene.wide_table_by_line("docs/ordinary.md")

        docs = census.table_form_population(self.root, census.TABLE_CHANNEL_DOCS)
        seen = {hit["text"] for hit in docs["hits"]}
        self.assertEqual(seen, {"docs/ordinary.md"})

        # Положительный контроль на ту же проводку с другой стороны: ADR,
        # выброшенный из контроля, обязан быть найден СВОИМ каналом — иначе
        # «исключено» было бы неотличимо от «не прочитано».
        adr = census.table_form_population(self.root, census.TABLE_CHANNEL_ADR)
        self.assertEqual({hit["text"] for hit in adr["hits"]},
                         {"docs/decisions/ADR-000-scene.md"})

    def test_the_declared_registry_is_counted_apart(self):
        """`INDEX.md` объявлен реестром, а не каналом.

        Подпереть утверждение о репозитории тем, что репозиторий уже объявил
        исключением, значило бы посчитать своё же решение наблюдением.
        """
        self.scene.wide_table_by_line(ADR_REGISTRY)
        data = census.table_form_population(self.root, census.TABLE_CHANNEL_ADR)
        self.assertEqual(data["registry_hits"], 1)
        self.assertEqual(data["form_long_line"], 0)
        self.assertEqual(data["form_any_reason"], 1)


class Verdict(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.scene = Scene(self.root)
        self.addCleanup(self._tmp.cleanup)

    def test_form_only_in_the_sample_is_sample_bound(self):
        self.scene.wide_table_by_line(f"{RULE_DIR}/some-rule.md")
        self.scene.write("docs/plain.md", "# документ\n\nобычный текст\n")
        out = census.table_form_census(self.root)
        self.assertEqual(out["verdict"], census.TABLE_FORM_SAMPLE_BOUND)
        self.assertEqual(out["sample_form_long_line"], 1)
        self.assertEqual(out["control_form_long_line"], 0)

    def test_form_outside_the_sample_is_repo_wide(self):
        """Тот самый ответ заказу: «одна таблица» — свойство выборки."""
        self.scene.wide_table_by_line(f"{RULE_DIR}/some-rule.md")
        self.scene.wide_table_by_line("docs/other.md")
        out = census.table_form_census(self.root)
        self.assertEqual(out["verdict"], census.TABLE_FORM_REPO_WIDE)
        self.assertEqual(out["control_form_long_line"], 1)

    def test_control_alone_is_still_repo_wide(self):
        """Форма вне выборки есть свойство репозитория и без выборки.

        Иначе пустая выборка читалась бы как «формы нет» — то самое «не
        измерено», выданное за чистоту.
        """
        self.scene.wide_table_by_line("docs/other.md")
        out = census.table_form_census(self.root)
        self.assertEqual(out["verdict"], census.TABLE_FORM_REPO_WIDE)
        self.assertEqual(out["sample_form_long_line"], 0)

    def test_no_form_anywhere_is_its_own_verdict(self):
        self.scene.write("docs/plain.md", "# документ\n\nобычный текст\n")
        out = census.table_form_census(self.root)
        self.assertEqual(out["verdict"], census.TABLE_FORM_NOTHING_FOUND)

    def test_unread_sample_is_unmeasured_not_clean(self):
        """Выборка не прочитана ⇒ третий исход, а не «формы нет».

        Инв. #17 внутри самого прибора: контроль за выборку не отвечает, и
        молчание о ней обязано быть отдельным значением.
        """
        empty = Path(self._tmp.name) / "empty"
        (empty / "docs").mkdir(parents=True)
        (empty / "docs/plain.md").write_text("# д\n\nтекст\n", encoding="utf-8")
        out = census.table_form_census(empty)
        self.assertEqual(out["verdict"], census.TABLE_FORM_UNMEASURED)
        # Контроль ПРОЧИТАН — и причина обязана сказать именно это, иначе она
        # неотличима от «не прочитано ничего».
        self.assertGreater(out["texts_read"], 0)
        self.assertIn("контроль за неё не отвечает", out["reason"])

    def test_nothing_read_at_all_is_unmeasured(self):
        empty = Path(self._tmp.name) / "bare"
        empty.mkdir()
        out = census.table_form_census(empty)
        self.assertEqual(out["verdict"], census.TABLE_FORM_UNMEASURED)
        self.assertEqual(out["texts_read"], 0)

    def test_the_two_unmeasured_reasons_are_told_apart(self):
        """Два «не измерено» — РАЗНЫЕ, и различает их только причина.

        Батарея мутаций нашла это местом без сторожа: вердикт у обеих веток
        один, и «не прочитано ничего» субсумировано веткой «не прочитана
        выборка» (ноль текстов всего ⇒ ноль текстов выборки). Проверять
        вердикт значило бы не проверять ничего — ветку сносит без единого
        красного теста. Сторожит ПРИЧИНА: «нечем было мерить вовсе» и
        «мерили, но не то» — разные состояния мира.
        """
        bare = Path(self._tmp.name) / "bare2"
        bare.mkdir()
        nothing = census.table_form_census(bare)

        control_only = Path(self._tmp.name) / "control-only"
        (control_only / "docs").mkdir(parents=True)
        (control_only / "docs/plain.md").write_text(
            "# д\n\nтекст\n", encoding="utf-8")
        sample_unread = census.table_form_census(control_only)

        self.assertEqual(nothing["verdict"], sample_unread["verdict"])
        self.assertNotEqual(nothing["reason"], sample_unread["reason"])
        self.assertIn("ни в одном канале", nothing["reason"])

    def test_an_unreadable_text_is_named_not_silently_zero(self):
        """Нечитаемый файл — причина в отчёте, а не молчаливый ноль."""
        path = self.scene.write(f"{RULE_DIR}/broken.md", "заглушка\n")
        path.write_bytes(b"\xff\xfe\x00 not utf8 \xff")
        out = census.table_form_census(self.root)
        named = [u["text"] for u in out["texts_unreadable"]]
        self.assertIn(f"{RULE_DIR}/broken.md", named)
        self.assertTrue(all(u["reason"] for u in out["texts_unreadable"]))


class ShareControl(unittest.TestCase):
    """Счёт без доли отвечает о РАЗМЕРЕ канала, а не о его свойстве."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.scene = Scene(self.root)
        self.addCleanup(self._tmp.cleanup)

    def test_share_is_measured_against_wide_authority_paragraphs(self):
        self.scene.wide_table_by_line(f"{RULE_DIR}/a.md")
        # Широкий абзац с тем же языком, но НЕ таблица — знаменатель доли.
        self.scene.write(f"{RULE_DIR}/b.md",
                         "# правило\n\n" + f"{AUTHORITY} " + _long_cell() + "\n")
        cell = census.table_form_census(self.root)[
            "table_share_of_wide_authority"][census.TABLE_CHANNEL_RULES]
        self.assertEqual(cell["wide_authority_paragraphs"], 2)
        self.assertEqual(cell["form_any_reason"], 1)
        self.assertAlmostEqual(cell["share"], 0.5)

    def test_share_without_a_denominator_is_none_with_a_reason(self):
        """Ноль в знаменателе — «НЕ ИЗМЕРЕНА», а не доля, равная нулю."""
        cell = census.table_form_census(self.root)[
            "table_share_of_wide_authority"][census.TABLE_CHANNEL_DOCS]
        self.assertIsNone(cell["share"])
        self.assertTrue(cell["share_reason"])
        self.assertNotEqual(cell["share_reason"], "измерено")


class Wiring(unittest.TestCase):
    """Координата обязана быть ПОЗВАНА сборкой, а не просто существовать.

    Предмет здесь — проводка НАСТОЯЩЕГО производителя, поэтому и дерево берётся
    настоящее. Сцена из ``tmp_path`` ответила бы на вопрос о сцене: `measure`
    на неполном дереве отказывает третьим исходом ещё до координаты, и «зелено»
    там значило бы лишь, что отказ случился раньше проверки.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = census._ROOT
        cls.doc = census.measure(cls.root)

    def test_measure_calls_the_coordinate(self):
        """Проводка меряется ВЫЗОВОМ, а не подстрокой в исходнике.

        Тест по подстроке переживает любое расцепление: строка остаётся в
        файле и тогда, когда результат никуда не кладётся.
        """
        sentinel = {"verdict": "СЕНТИНЕЛ", "reason": "проводка"}
        calls = []

        def fake(root):
            calls.append(root)
            return dict(sentinel)

        original = census.table_form_census
        census.table_form_census = fake
        try:
            doc = census.measure(self.root)
        finally:
            census.table_form_census = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(doc["table_form_census"], sentinel)

    def test_report_renders_the_section(self):
        printed = "\n".join(census.report(self.doc))
        self.assertIn("ФОРМА ТАБЛИЦЫ", printed)

    def test_a_report_without_the_key_says_unmeasured(self):
        """Отсутствие ключа — названный третий исход, а не пустая строка."""
        doc = dict(self.doc)
        doc.pop("table_form_census")
        printed = "\n".join(census.report(doc))
        # Ярлык секции — часть утверждения. Голое «НЕ ИЗМЕРЕНА» совпало бы с
        # любой соседней строкой отчёта, и тест зеленел бы, ничего не проверив.
        self.assertIn("[ФОРМА ТАБЛИЦЫ] НЕ ИЗМЕРЕНА", printed)

    def test_the_coordinate_does_not_widen_the_declared_surfaces(self):
        """Контроль каналом объявления НЕ становится.

        Если бы `docs/` попал в население поверхностей решения, предел
        `MAX_DECLARING_LINE` был бы тихо снят — ровно тот дефект, от которого
        он и написан. Контроль при этом обязан быть НЕПУСТЫМ: сравнение с
        пустым множеством прошло бы при любой проводке.
        """
        surfaces = self.doc["decision_surfaces"]["surfaces"]
        declared = {s["path"] for s in surfaces}
        control = self.doc["table_form_census"]["channels"][census.TABLE_CHANNEL_DOCS]
        self.assertTrue(control["hits"], "контроль пуст — сравнивать не с чем")
        for hit in control["hits"]:
            self.assertNotIn(hit["text"], declared)

    def test_a_coordinate_without_shares_says_unmeasured(self):
        """Пропавшая доля — НАЗВАННЫЙ третий исход, а не молчащий цикл.

        Ветку нашёл храповик инв. #17: `or {}` превратил бы отсутствие ключа
        в пустую долю, цикл не напечатал бы ни строки, и «не измерено» стало
        бы неотличимо от «нечего показать».
        """
        doc = dict(self.doc)
        form = dict(doc["table_form_census"])
        form.pop("table_share_of_wide_authority")
        doc["table_form_census"] = form
        printed = "\n".join(census.report(doc))
        self.assertIn("[ФОРМА · ДОЛЯ] НЕ ИЗМЕРЕНА", printed)

    def test_a_coordinate_without_channels_says_unmeasured(self):
        doc = dict(self.doc)
        form = dict(doc["table_form_census"])
        form.pop("channels")
        doc["table_form_census"] = form
        printed = "\n".join(census.report(doc))
        self.assertIn("[ФОРМА · ГДЕ] НЕ ИЗМЕРЕНО", printed)

    def test_a_single_missing_channel_is_named_not_skipped(self):
        """Канал, пропавший поодиночке, тоже обязан быть НАЗВАН."""
        doc = dict(self.doc)
        form = dict(doc["table_form_census"])
        shares = dict(form["table_share_of_wide_authority"])
        shares.pop(census.TABLE_CHANNEL_DOCS)
        form["table_share_of_wide_authority"] = shares
        doc["table_form_census"] = form
        printed = "\n".join(census.report(doc))
        self.assertIn(
            f"[ФОРМА · ДОЛЯ] {census.TABLE_CHANNEL_DOCS}: НЕ ИЗМЕРЕНА",
            printed)

    def test_the_coordinate_is_serialisable(self):
        json.dumps(self.doc["table_form_census"])

    def test_the_live_tree_answers_the_order(self):
        """Ответ заказу на ЖИВОМ дереве, а не на сцене.

        Числа здесь не закрепляются литералом: они меняются с каждой правкой
        документа, и тест, пришпиливший «семь», краснел бы от чужого абзаца.
        Закрепляется СВОЙСТВО, ради которого заказ и поставлен: форма выходит
        за пределы объявленного канала, и потому «одна таблица» есть свойство
        выборки.
        """
        form = self.doc["table_form_census"]
        self.assertEqual(form["verdict"], census.TABLE_FORM_REPO_WIDE)
        self.assertGreater(form["control_form_long_line"], 0)
        shares = form["table_share_of_wide_authority"]
        rules = shares[census.TABLE_CHANNEL_RULES]["share"]
        adr = shares[census.TABLE_CHANNEL_ADR]["share"]
        self.assertIsNotNone(rules)
        self.assertIsNotNone(adr)
        # Форма характерна именно для ПРАВИЛ: язык права изменения там живёт
        # в таблицах заметно чаще, чем в нарративе ADR. Если это перестанет
        # быть так, отбор «таблица» больше не различает каналы, и знать об
        # этом надо от теста, а не от следующего заказа.
        self.assertGreater(rules, adr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
