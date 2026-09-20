"""Канал ШИРОКОГО абзаца — цена слепоты обоих каналов (заказ G57 п. 1).

Предмет: :func:`spa_core.monitoring.rule_second_copy_census.paths_in_wide_paragraphs`
и :func:`...wide_paragraph_channel`.

**Почему файл отдельный, а не дописан к соседям.** Прежние два канала
отвечают на вопросы «какие пути объявлены» и «какие ИМЕНА объявлены»; этот —
на третий: «сколько стоит абзац, до содержимого которого мера пути не
доходит». Смешать их значило бы завести вторую копию правила отбора там, где
у трёх вопросов три разных населения.

**Ни одной литеральной даты и ни одного литерального pid** — сцены строятся
из tmp_path, вердикты не зависят ни от календаря, ни от того, какой номер
процесса сегодня занят.
"""

import json
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as census


# Строка длиннее MAX_DECLARING_LINE — второй предел «широты». Собирается
# ВЫЧИСЛЕНИЕМ от самого предела, а не переписывается числом: литерал здесь
# разошёлся бы с пределом молча в тот день, когда предел тронут.
_LONG = "x" * (census.MAX_DECLARING_LINE + 10)


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _row(name: str, value: object, remedy: str) -> dict:
    return {"name": name, "value": value, "remedy": remedy,
            "verdict": census.CLASS_TWO_COPIES}


def _shelf(root: Path, rel: str, **numbers: object) -> None:
    body = "\n".join(f"{name} = {value}" for name, value in numbers.items())
    _write(root, rel, body + "\n")


class WideParagraphPopulationTests(unittest.TestCase):
    """Что попадает в население канала, а что — нет."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_wide_by_line_length_with_authority_is_a_candidate(self) -> None:
        """Абзац широк ДЛИННОЙ СТРОКОЙ — путь внутри него считается."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| факт | не менять | `spa_core/shelf.py` {_LONG} |\n"
               "| ещё | строка | короткая |\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertIn("spa_core/shelf.py", out["candidates"])
        evidence = out["candidates"]["spa_core/shelf.py"][0]
        self.assertEqual(evidence["wide_because"], census.WIDE_BY_LINE_LENGTH)
        self.assertEqual(out["wide_authority_paragraphs"], 1)
        self.assertEqual(out["wide_authority_mentions"], 1)

    def test_wide_by_paragraph_length_with_authority_is_a_candidate(self) -> None:
        """Абзац широк ЧИСЛОМ СТРОК — тот же исход, другая причина."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        lines = ["не менять без ADR:"]
        lines += [f"строка {i}" for i in range(census.MAX_DECLARING_PARAGRAPH)]
        lines += ["см. `spa_core/shelf.py`"]
        _write(self.root, "CLAUDE.md", "# правило\n\n" + "\n".join(lines) + "\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertIn("spa_core/shelf.py", out["candidates"])
        self.assertEqual(
            out["candidates"]["spa_core/shelf.py"][0]["wide_because"],
            census.WIDE_BY_LINES)

    def test_both_limits_together_get_their_own_reason(self) -> None:
        """Оба предела разом — третий исход, а не «который-нибудь из двух»."""
        block = [_LONG] + [f"строка {i}"
                           for i in range(census.MAX_DECLARING_PARAGRAPH)]
        block.append("не менять: `spa_core/shelf.py`")
        self.assertEqual(census._wide_reason(list(enumerate(block, 1))),
                         census.WIDE_BY_BOTH)

    def test_the_paragraph_limit_is_a_boundary_not_a_direction(self) -> None:
        """Абзац РОВНО в предел — узкий. Иначе `>` тихо станет `>=`.

        Обе стороны границы пинятся в одном тесте: при `MAX` строках абзац
        читает мера пути, при `MAX + 1` — уже нет.
        """
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        head = ["не менять без ADR: `spa_core/shelf.py`"]
        body = [f"строка {i}" for i in range(census.MAX_DECLARING_PARAGRAPH - 1)]
        _write(self.root, "CLAUDE.md", "\n".join(head + body) + "\n")
        edge = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(edge["wide_authority_paragraphs"], 0)
        self.assertEqual(edge["narrow_authority_paragraphs"], 1)

        _write(self.root, "CLAUDE.md",
               "\n".join(head + body + ["ещё строка"]) + "\n")
        over = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(over["wide_authority_paragraphs"], 1)
        self.assertEqual(
            over["candidates"]["spa_core/shelf.py"][0]["wide_because"],
            census.WIDE_BY_LINES)

    def test_the_line_limit_is_a_boundary_not_a_direction(self) -> None:
        """Строка РОВНО в предел — узкая. Второй предел, та же граница."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        tail = "`spa_core/shelf.py` не менять "
        exact = tail + "y" * (census.MAX_DECLARING_LINE - len(tail))
        self.assertEqual(len(exact), census.MAX_DECLARING_LINE)
        _write(self.root, "CLAUDE.md", exact + "\n")
        edge = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(edge["wide_authority_paragraphs"], 0)

        _write(self.root, "CLAUDE.md", exact + "y\n")
        over = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(over["wide_authority_paragraphs"], 1)
        self.assertEqual(
            over["candidates"]["spa_core/shelf.py"][0]["wide_because"],
            census.WIDE_BY_LINE_LENGTH)

    def test_the_reason_label_has_its_own_boundaries(self) -> None:
        """У ЯРЛЫКА причины свои границы, и они не те же, что у допуска.

        Допуск решает, читать абзац или нет; ярлык — какой предел его
        отбросил. Абзац, широкий СТРОКОЙ и ровно в предел по числу строк,
        обязан называться `line_too_long`, а не `both_limits`: иначе `>` у
        ярлыка тихо станет `>=` и цена уедет в чужую корзину.
        """
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        lines = [f"не менять `spa_core/shelf.py` {_LONG}"]
        lines += [f"строка {i}"
                  for i in range(census.MAX_DECLARING_PARAGRAPH - 1)]
        self.assertEqual(len(lines), census.MAX_DECLARING_PARAGRAPH)
        _write(self.root, "CLAUDE.md", "\n".join(lines) + "\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(
            out["candidates"]["spa_core/shelf.py"][0]["wide_because"],
            census.WIDE_BY_LINE_LENGTH)

    def test_the_reason_label_boundary_on_the_line_limit(self) -> None:
        """Зеркало предыдущего: широк ЧИСЛОМ СТРОК, строка ровно в предел."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        head = "не менять `spa_core/shelf.py` "
        exact = head + "y" * (census.MAX_DECLARING_LINE - len(head))
        self.assertEqual(len(exact), census.MAX_DECLARING_LINE)
        lines = [exact] + [f"строка {i}"
                           for i in range(census.MAX_DECLARING_PARAGRAPH)]
        _write(self.root, "CLAUDE.md", "\n".join(lines) + "\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(
            out["candidates"]["spa_core/shelf.py"][0]["wide_because"],
            census.WIDE_BY_LINES)

    def test_values_are_returned_exactly_for_shelves(self) -> None:
        """Инвариант, на котором стои́т отбор контроля, ЗАКРЕПЛЁН, а не подразумеваем.

        `surface_numbers` отдаёт числа РОВНО у шкафа; у сторожа, у замера и у
        отсутствующего файла — `None`. Пока это так, проверка рода в отборе
        контроля вырождена ПО ПОСТРОЕНИЮ, и мутация её не убивает. Сказать об
        этом тестом честнее, чем оставить инвариант в голове автора.
        """
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _shelf(self.root, "spa_core/tests/test_guard.py", LIMIT=7)
        _write(self.root, "spa_core/stamped.json",
               json.dumps({"generated_at": "x", "n": 1}))
        for rel, kind, has_values in (
                ("spa_core/shelf.py", census.SURFACE_SHELF, True),
                ("spa_core/tests/test_guard.py", census.SURFACE_GUARD, False),
                ("spa_core/stamped.json", census.SURFACE_MEASUREMENT, False),
                ("spa_core/nope.py", census.SURFACE_ABSENT, False)):
            values, got, _reason = census.surface_numbers(self.root, rel)
            self.assertEqual(got, kind, rel)
            self.assertEqual(values is not None, has_values, rel)

    def test_a_narrow_paragraph_is_not_this_channels_business(self) -> None:
        """Узкий абзац читает мера ПУТИ — здесь он не population, а контроль.

        Положительный контроль на разделение: тот же текст, та же фраза права
        изменения, тот же путь; отличается ТОЛЬКО ширина — и канал молчит.
        """
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\nне менять `spa_core/shelf.py` без ADR\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(out["candidates"], {})
        self.assertEqual(out["narrow_authority_paragraphs"], 1)
        self.assertEqual(out["narrow_authority_mentions"], 1)
        self.assertEqual(out["wide_authority_paragraphs"], 0)

    def test_a_wide_paragraph_without_authority_goes_to_the_control(self) -> None:
        """Широкий абзац БЕЗ языка права изменения — контроль, не находка."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| пример | `spa_core/shelf.py` {_LONG} |\n| ещё | строка |\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(out["candidates"], {})
        self.assertEqual(out["control_candidates"], ["spa_core/shelf.py"])
        self.assertEqual(out["wide_control_paragraphs"], 1)
        self.assertEqual(out["wide_control_mentions"], 1)

    def test_an_unresolvable_path_is_named_and_not_dropped(self) -> None:
        """Путь, которого в дереве нет, уходит в свой исход, а не в тишину."""
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/net/ghost.py` {_LONG} |\n| x | y |\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(out["candidates"], {})
        self.assertEqual([e["named_as"] for e in out["unresolved"]],
                         ["spa_core/net/ghost.py"])

    def test_rules_directory_is_read_as_well_as_the_root_text(self) -> None:
        """Население — оба текста правил, а не только `CLAUDE.md`."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md", "# правило\n\nничего\n")
        _write(self.root, ".claude/rules/r.md",
               f"| owner-gated | `spa_core/shelf.py` {_LONG} |\n| x | y |\n")
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(out["texts_read"], 2)
        self.assertIn("spa_core/shelf.py", out["candidates"])

    def test_no_rule_text_at_all_is_measured_as_such(self) -> None:
        """Правил нет ⇒ `texts_read == 0`; это не «широких абзацев нет»."""
        out = census.paths_in_wide_paragraphs(self.root)
        self.assertEqual(out["texts_read"], 0)
        self.assertEqual(out["candidates"], {})


class EnrichmentTests(unittest.TestCase):
    """Третий исход у частоты ошибки — обязателен, и он не ноль."""

    def test_ratio_is_measured_when_both_populations_exist(self) -> None:
        ratio, why = census._enrichment((4, 8), (10, 5))
        self.assertAlmostEqual(ratio, 4.0)
        self.assertEqual(why, "измерено")

    def test_no_control_paragraphs_is_not_a_number(self) -> None:
        ratio, why = census._enrichment((4, 8), (0, 0))
        self.assertIsNone(ratio)
        self.assertIn("НЕ ИЗМЕРЕНА", why)

    def test_control_without_mentions_is_not_infinite_enrichment(self) -> None:
        """Знаменатель ноль — «обогащение бесконечно» было бы не измерением."""
        ratio, why = census._enrichment((4, 8), (10, 0))
        self.assertIsNone(ratio)
        self.assertIn("знаменател", why)

    def test_no_selected_paragraphs_is_its_own_reason(self) -> None:
        ratio, why = census._enrichment((0, 0), (10, 5))
        self.assertIsNone(ratio)
        self.assertIn("сгущать нечего", why)


class WideParagraphChannelTests(unittest.TestCase):
    """Зазор, его цена в парах и два контроля."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _scene(self) -> None:
        """Сцена: шкаф с числом 7, находка с тем же числом и формой агента."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/shelf.py` {_LONG} |\n| x | y |\n")

    def _rows(self) -> list:
        return [_row("LIMIT", 7, "agent_may_fix")]

    def test_a_wide_only_shelf_that_moves_pairs_is_a_SHIFT(self) -> None:
        self._scene()
        out = census.wide_paragraph_channel(
            self.root, self._rows(), path_candidates=[], name_candidates=[])
        self.assertEqual(out["verdict"], census.WIDE_CHANNEL_SHIFT)
        self.assertEqual(out["gap"], 1)
        self.assertEqual(out["shelves"], 1)
        self.assertEqual(out["would_move_total"], 1)

    def test_a_pair_already_in_owner_form_does_not_move(self) -> None:
        """Положительный контроль НА ОБРАТНОЕ состояние: та же сцена, но право
        чинить уже стои́т у владельца ⇒ сдвига нет, а населения — есть."""
        self._scene()
        rows = [_row("LIMIT", 7, census.REMEDY_OWNER)]
        out = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[])
        self.assertEqual(out["verdict"], census.WIDE_CHANNEL_NO_SHIFT)
        self.assertEqual(out["gap"], 1)
        self.assertEqual(out["would_move_total"], 0)

    def test_a_path_the_path_channel_already_knows_is_not_the_gap(self) -> None:
        """Зазор считается ПРОТИВ прежних каналов — иначе находка удвоится."""
        self._scene()
        out = census.wide_paragraph_channel(
            self.root, self._rows(),
            path_candidates=["spa_core/shelf.py"], name_candidates=[])
        self.assertEqual(out["gap"], 0)
        self.assertEqual([r["known_by"] for r in out["already_known"]], ["path"])
        self.assertEqual(out["already_known"][0]["matches"], 1)

    def test_a_path_the_NAME_channel_already_knows_is_not_the_gap(self) -> None:
        """Вторая дверь того же вычета — и она отдельная, а не та же самая."""
        self._scene()
        out = census.wide_paragraph_channel(
            self.root, self._rows(),
            path_candidates=[], name_candidates=["spa_core/shelf.py"])
        self.assertEqual(out["gap"], 0)
        self.assertEqual([r["known_by"] for r in out["already_known"]], ["name"])

    def test_an_asked_surface_cannot_move_anything(self) -> None:
        """Спрашиваемую сегодня поверхность сдвигать некуда ПО ПОСТРОЕНИЮ."""
        self._scene()
        out = census.wide_paragraph_channel(
            self.root, self._rows(), path_candidates=[], name_candidates=[],
            asked=("spa_core/shelf.py",))
        self.assertEqual(out["would_move_total"], 0)
        self.assertEqual(out["verdict"], census.WIDE_CHANNEL_NO_SHIFT)
        self.assertEqual(out["surfaces"][0]["matches"], 1)

    def test_a_guard_file_is_not_a_decision_surface(self) -> None:
        """Сторож — сторона, которую перепись судит; властью он не является."""
        _shelf(self.root, "spa_core/tests/test_thing.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/tests/test_thing.py` {_LONG} |\n| x | y |\n")
        out = census.wide_paragraph_channel(
            self.root, self._rows(), path_candidates=[], name_candidates=[])
        self.assertEqual(out["shelves"], 0)
        self.assertEqual(out["guards"], 1)
        self.assertEqual(out["would_move_total"], 0)

    def test_nothing_named_is_its_own_verdict(self) -> None:
        """Широкий абзац есть, путей в нём нет — это НЕ «сдвига нет»."""
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | ничего не назвали {_LONG} |\n| x | y |\n")
        out = census.wide_paragraph_channel(
            self.root, self._rows(), path_candidates=[], name_candidates=[])
        self.assertEqual(out["verdict"], census.WIDE_CHANNEL_NOTHING_NAMED)

    def test_no_rule_texts_is_UNMEASURED_not_clean(self) -> None:
        out = census.wide_paragraph_channel(
            self.root, self._rows(), path_candidates=[], name_candidates=[])
        self.assertEqual(out["verdict"], census.WIDE_CHANNEL_UNMEASURED)
        self.assertEqual(out["gap"], 0)

    def test_the_consequence_control_is_measured_separately(self) -> None:
        """Контроль по ПОСЛЕДСТВИЮ — своё население, а не пересказ первого.

        Сцена: два широких абзаца одинаковой ширины; у одного язык права
        изменения есть, у другого нет, и путь у каждого свой. Канал обязан
        отнести их в разные корзины и посчитать пары отдельно.
        """
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _shelf(self.root, "spa_core/other.py", OTHER=9)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/shelf.py` {_LONG} |\n| x | y |\n\n"
               f"| пример | `spa_core/other.py` {_LONG} |\n| x | y |\n")
        rows = [_row("LIMIT", 7, "agent_may_fix"),
                _row("OTHER", 9, "agent_may_fix")]
        out = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[])
        self.assertEqual(out["would_move_total"], 1)
        self.assertEqual(out["control_shelves"], 1)
        self.assertEqual(out["control_would_move"], 1)
        self.assertEqual([r["path"] for r in out["control_rows"]],
                         ["spa_core/other.py"])

    def test_the_cost_is_attributed_to_the_limit_that_holds_it(self) -> None:
        """Посылка заказа ПРОВЕРЯЕТСЯ: какой из двух пределов держит пары.

        Сцена: цену держит предел СТРОКИ, предел абзаца не держит ничего.
        Сложить их в одно число значило бы подтвердить посылку, не померив её.
        """
        self._scene()
        out = census.wide_paragraph_channel(
            self.root, self._rows(), path_candidates=[], name_candidates=[])
        self.assertEqual(out["would_move_by_wide_reason"],
                         {census.WIDE_BY_LINES: 0,
                          census.WIDE_BY_LINE_LENGTH: 1,
                          census.WIDE_BY_BOTH: 0})
        self.assertEqual(out["surfaces_by_wide_reason"][census.WIDE_BY_LINE_LENGTH], 1)

    def test_the_consequence_control_does_not_count_guards(self) -> None:
        """Контроль судит по тому же правилу, что и отбор: сторож — не шкаф.

        Иначе «у контроля ноль» означало бы лишь, что у контроля на пути
        случайно оказался тест, и обогащение было бы свойством выборки.
        """
        _shelf(self.root, "spa_core/tests/test_guard.py", OTHER=9)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| пример | `spa_core/tests/test_guard.py` {_LONG} |\n| x | y |\n")
        out = census.wide_paragraph_channel(
            self.root, [_row("OTHER", 9, "agent_may_fix")],
            path_candidates=[], name_candidates=[])
        self.assertEqual(out["control_shelves"], 0)
        self.assertEqual(out["control_would_move"], 0)

    def test_the_consequence_control_excludes_asked_surfaces_too(self) -> None:
        """Спрашиваемую поверхность контроль вычитает так же, как отбор.

        Не вычесть её у контроля значило бы сравнивать два разных правила и
        называть разницу обогащением.
        """
        _shelf(self.root, "spa_core/other.py", OTHER=9)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| пример | `spa_core/other.py` {_LONG} |\n| x | y |\n")
        rows = [_row("OTHER", 9, "agent_may_fix")]
        free = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[])
        self.assertEqual(free["control_would_move"], 1)
        asked = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[],
            asked=("spa_core/other.py",))
        self.assertEqual(asked["control_would_move"], 0)

    def test_the_cost_per_limit_counts_PAIRS_not_surfaces(self) -> None:
        """Две пары у ОДНОЙ поверхности — цена 2, а поверхность одна.

        Сцена подобрана так, что «считать поверхности» и «считать пары» дают
        РАЗНЫЕ числа: иначе подмена одного другим прошла бы незамеченной.
        """
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7, OTHER=9)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/shelf.py` {_LONG} |\n| x | y |\n")
        rows = [_row("LIMIT", 7, "agent_may_fix"),
                _row("OTHER", 9, "agent_may_fix")]
        out = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[])
        self.assertEqual(out["gap"], 1)
        self.assertEqual(out["would_move_total"], 2)
        self.assertEqual(out["would_move_by_wide_reason"][census.WIDE_BY_LINE_LENGTH], 2)
        self.assertEqual(out["surfaces_by_wide_reason"][census.WIDE_BY_LINE_LENGTH], 1)

    def test_the_denominator_of_the_claim_is_published(self) -> None:
        """«Сменили бы форму N» без знаменателя — число без смысла.

        Нечисловая находка в знаменатель не входит: витрина порогов говорит
        только о числах, и разбавлять им знаменатель значило бы считать
        вопрос, который никому не задавался.
        """
        self._scene()
        rows = [_row("LIMIT", 7, "agent_may_fix"),
                _row("VERSION", "v1.0", "agent_may_fix")]
        out = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[])
        self.assertEqual(out["population_total"], 2)
        self.assertEqual(out["population_numeric"], 1)

    def test_a_string_valued_finding_is_not_counted(self) -> None:
        """Нечисловая пара витрине не принадлежит — знаменатель не разбавлять."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/shelf.py` {_LONG} |\n| x | y |\n")
        rows = [_row("VERSION", "v1.0", "agent_may_fix")]
        out = census.wide_paragraph_channel(
            self.root, rows, path_candidates=[], name_candidates=[])
        self.assertEqual(out["would_move_total"], 0)
        self.assertEqual(out["surfaces"][0]["matches"], 0)


class ReportAndWiringTests(unittest.TestCase):
    """Вывод и проводка: координата обязана ДОЕХАТЬ до читателя."""

    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_report_says_NOT_MEASURED_when_the_key_is_absent(self) -> None:
        """Ключа нет ⇒ отчёт говорит «НЕ ИЗМЕРЕН», а не молчит (инв. #17)."""
        lines = census.report({"generated_at": "", "rows": [], "peer_rows": [],
                               "triple_rows": []})
        marker = [ln for ln in lines if ln.startswith("[ШИРОКИЙ АБЗАЦ]")]
        self.assertEqual(len(marker), 1)
        self.assertIn("НЕ ИЗМЕРЕН", marker[0])

    def test_report_prints_the_verdict_and_both_control_axes(self) -> None:
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/shelf.py` {_LONG} |\n| x | y |\n\n"
               f"| пример | `spa_core/shelf.py` {_LONG} |\n| x | y |\n")
        channel = census.wide_paragraph_channel(
            self.root, [_row("LIMIT", 7, "agent_may_fix")],
            path_candidates=[], name_candidates=[])
        lines = census.report({"generated_at": "", "rows": [], "peer_rows": [],
                               "triple_rows": [],
                               "wide_paragraph_channel": channel})
        heads = [ln.split("]")[0] + "]" for ln in lines]
        for marker in ("[ШИРОКИЙ АБЗАЦ]", "[ШИРОКИЙ ПОЧЕМУ]",
                       "[КАКОЙ ПРЕДЕЛ ДЕРЖИТ ЦЕНУ]",
                       "[ЧАСТОТА ОШИБКИ · ПОСЛЕДСТВИЕ]"):
            self.assertIn(marker, heads, marker)

    def test_measure_calls_the_channel_and_publishes_it(self) -> None:
        """Проводка проверяется ВЫЗОВОМ, а не наличием строки в исходнике."""
        import ast
        source = Path(census.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        measure = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == "measure")
        called = {node.func.id for node in ast.walk(measure)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name)}
        self.assertIn("wide_paragraph_channel", called)
        keys = {node.value for node in ast.walk(measure)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        self.assertIn("wide_paragraph_channel", keys)

    def test_measure_feeds_the_channel_BOTH_prior_channels(self) -> None:
        """Проводка проверяется ПРОИСХОЖДЕНИЕМ аргумента, а не его наличием.

        Вычет считается против двух прежних каналов; передать сюда пустой
        список значило бы посчитать чужую находку своей, и `name_candidates=[]`
        выглядел бы работающей проводкой.
        """
        import ast
        source = Path(census.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        measure = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == "measure")
        call = next(node for node in ast.walk(measure)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "wide_paragraph_channel")
        bound = {kw.arg: kw.value for kw in call.keywords}
        self.assertEqual(set(bound), {"path_candidates", "name_candidates"})
        for arg, origin in (("path_candidates", "surfaces"),
                            ("name_candidates", "names")):
            names = {node.id for node in ast.walk(bound[arg])
                     if isinstance(node, ast.Name)}
            self.assertIn(origin, names, arg)

    def test_the_channel_survives_json_serialisation(self) -> None:
        """Артефакт пишется json'ом — координата обязана в него влезть."""
        _shelf(self.root, "spa_core/shelf.py", LIMIT=7)
        _write(self.root, "CLAUDE.md",
               "# правило\n\n"
               f"| не менять | `spa_core/shelf.py` {_LONG} |\n| x | y |\n")
        channel = census.wide_paragraph_channel(
            self.root, [_row("LIMIT", 7, "agent_may_fix")],
            path_candidates=[], name_candidates=[])
        restored = json.loads(json.dumps(channel, ensure_ascii=False))
        self.assertEqual(restored["verdict"], channel["verdict"])
        self.assertEqual(restored["would_move_total"], channel["would_move_total"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
