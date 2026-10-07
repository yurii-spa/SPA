#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Контроли переписи читателей ЧУЖОЙ разметки (заказ G103 п. 2, ADR-523).

Каждый тест — ЛИБО воспроизведение настоящего дефекта, найденного при
постройке прибора 07.10, ЛИБО контроль в обратную сторону к нему. Проверка,
никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Дефекты, воспроизведённые здесь дословно:

1. **признак «литерал рядом с чтением» не нашёл единственного известного члена
   класса** — личность кустодиана живёт в таблице, чтение идёт по
   деструктуризованному шаблону (`test_the_table_shape_is_found_at_all`);
2. **грубая деструктуризация выдумала 42 опровержения** — литералы соседних
   колонок строки приписывались позиции шаблона
   (`test_a_neighbouring_column_is_not_attributed_to_the_pattern`);
3. **склейка f-строки выдумала личность `view-`** — `id="view-{key}"`
   схлопывалось в `id="view-"` (`test_an_interpolated_identity_is_a_prefix`);
4. **фикстура читателя подтверждала его же претензию** (fail-OPEN): `sl-day`
   объявлялся подтверждённым, хотя живая страница его опровергла (ADR-594)
   (`test_the_readers_own_scene_does_not_confirm_its_claim`);
5. **одной формы ссылки на читателя не хватило**: фикстура грузит кустодиана
   через `spec_from_file_location`, статического ввоза нет вовсе
   (`test_a_reference_by_path_literal_counts_as_the_readers_scene`);
6. **дверь «вызов через границу модуля» — самая населённая**, и без неё
   19 настоящих членов уходили в «не измерено»
   (`test_a_call_across_a_module_border_is_a_foreign_haystack`);
7. **разбор находки ОТМЕНЯЛ находку**: `.md` считался разметкой, и текст
   ADR-620 «подтвердил» ровно те две личности, которые опровергает
   (`test_prose_naming_an_identity_is_not_a_producer`);
8. **прибор жил в населении, которое мерит**: его батареи писали синтетическую
   разметку, и она попадала в оракул третьих читателей
   (`test_the_instruments_own_scene_is_excluded_from_the_oracle`);
9. **элемент контейнера наследовал литералы контейнера через ИНДЕКС** —
   `row["identity"]` в ЭТОЙ батарее дал два выдуманных опровержения
   (`test_an_element_of_a_named_container_inherits_nothing`).

Часы приходят ВХОДОМ: `measure(now=...)`.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` уходит параметром `now=` в
# measure()/run(), и отметка отчёта вычислена ОТ НЕГО (`generated_at == _NOW`,
# контроль `test_the_clock_arrives_as_an_input`). Стенных часов в файле нет ни
# одной: прибор свои `dt.datetime.now` зовёт только когда `now` не подан.
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spa_core.monitoring import foreign_markup_reader_census as fmrc

_NOW = dt.datetime(2026, 10, 7, 6, 30, tzinfo=dt.timezone.utc)


# ───────────────────────────── сцена ───────────────────────────────────────

def _tree(tmp_path: Path, files: dict) -> Path:
    """Одноразовое дерево. Каждый путь — относительный, содержимое — текст."""
    root = tmp_path / "tree"
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _rows(root: Path) -> list:
    return fmrc.measure(root, now=_NOW)["rows"]


def _by_identity(root: Path) -> dict:
    return {row["identity"]: row for row in _rows(root) if row["identity"]}


_READER_PARAM = '''
import re

def check(html):
    return 'id="hero-day"' in html
'''

_MARKUP = '<main><span id="hero-day">60</span></main>\n'


# ───────────── ось «верность»: подтверждение, опровержение, эхо ────────────

def test_a_markup_file_confirms_the_claim(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM,
                            "landing/src/pages/index.astro": _MARKUP})
    row = _by_identity(root)["hero-day"]
    assert row["parity"] == fmrc.CONFIRMED
    assert row["haystack_origin"] == fmrc.HAY_PARAMETER


def test_nothing_in_the_tree_refutes_the_claim(tmp_path: Path) -> None:
    """Обратная сторона предыдущего: разметки нет — претензия опровергнута."""
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM,
                            "landing/src/pages/index.astro": "<main/>\n"})
    row = _by_identity(root)["hero-day"]
    assert row["parity"] == fmrc.REFUTED


def test_an_empty_oracle_is_not_a_refutation(tmp_path: Path) -> None:
    """fail-CLOSED: НИ ОДНОГО файла разметки ⇒ третий исход, не «опровергнуто».

    Ноль прочитанной разметки и «разметка прочитана, личности в ней нет» —
    разные утверждения, и выдать первое за второе значило бы напечатать
    выдуманную находку (инв. #17).
    """
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM})
    row = _by_identity(root)["hero-day"]
    assert row["parity"] == fmrc.UNMEASURED_NO_ORACLE
    assert fmrc.measure(root, now=_NOW)["oracle_markup_files"] == 0


def test_the_readers_own_scene_does_not_confirm_its_claim(tmp_path: Path
                                                          ) -> None:
    """Дефект 4 (fail-OPEN первой редакции): фикстура читателя — не оракул.

    Личность пишет ТОЛЬКО модуль, ввозящий читателя. Первая редакция звала
    это подтверждением, и ровно так `sl-day`/`sl-gates`/`sl-apy` — живьём
    опровергнутые (ADR-594) — выглядели подтверждёнными.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "spa_core/tests/test_reader.py": (
            "import reader\n"
            "def test_it():\n"
            "    assert reader.check('<i id=\"hero-day\">1</i>')\n"),
    })
    row = _by_identity(root)["hero-day"]
    assert row["parity"] == fmrc.ECHOED_BY_OWN_SCENE
    assert fmrc.measure(root, now=_NOW)["echoed_by_own_scene"] == 1


def test_an_independent_python_producer_does_confirm_it(tmp_path: Path) -> None:
    """КОНТРОЛЬ к предыдущему: тот же файл БЕЗ ссылки на читателя — оракул.

    Без этой стороны «эхо» было бы не мерой, а запретом на python в оракуле:
    часть страниц дерева собирает именно python (`tear_sheet_html`,
    `portal_render`), и объявить их согласие поддельным значило бы
    опровергнуть каждого их читателя.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "scripts/render.py": (
            "def page():\n"
            "    return '<i id=\"hero-day\">1</i>'\n"),
    })
    row = _by_identity(root)["hero-day"]
    assert row["parity"] == fmrc.CONFIRMED_BY_PYTHON


def test_a_reference_by_path_literal_counts_as_the_readers_scene(
        tmp_path: Path) -> None:
    """Дефект 5: статического ввоза НЕТ, а сцена читателя — есть.

    Фикстура кустодиана грузит его `spec_from_file_location("…/
    site_freshness_monitor.py")`. По одной форме ссылки (AST-ввоз) сцена
    выглядела бы независимым производителем — замерено 07.10.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "spa_core/tests/test_reader.py": (
            "import importlib.util\n"
            "def test_it():\n"
            "    spec = importlib.util.spec_from_file_location(\n"
            "        'r', 'scripts/reader.py')\n"
            "    assert spec and '<i id=\"hero-day\">1</i>'\n"),
    })
    assert _by_identity(root)["hero-day"]["parity"] == fmrc.ECHOED_BY_OWN_SCENE


def test_an_assembled_producer_identity_is_a_third_outcome(tmp_path: Path
                                                            ) -> None:
    """Производитель собирает личность в рантайме ⇒ НЕ «опровергнуто».

    `web_shell` пишет `id="view-{key}"`; литерала `view-build` в дереве нет
    вовсе. Назвать такую претензию опровергнутой было бы ложью.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": (
            "def check(html):\n"
            "    return html.index('id=\"view-build\"')\n"),
        "landing/src/pages/shell.astro": '<div id="view-{key}"></div>\n',
    })
    row = _by_identity(root)["view-build"]
    assert row["parity"] == fmrc.UNMEASURED_ASSEMBLED


# ───────────── ось «личность»: таблица, позиция, склейка, перечислитель ────

_TABLE_READER = '''
import re

SOURCES = {
    "days": (
        ("home", "m-days", r'id="m-days"[^>]*>\\s*(\\d+)', "why"),
    ),
}


def locate(label, pages, sources=None):
    table = SOURCES if sources is None else sources
    for page, elem_id, pattern, _why in table.get(label, ()):
        html = (pages or {}).get(page)
        if not html:
            continue
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None
'''


def test_the_table_shape_is_found_at_all(tmp_path: Path) -> None:
    """Дефект 1: признак «литерал рядом с чтением» теряет кустодиана.

    Это ФОРМА живого кустодиана: личность в таблице, чтение —
    `re.search(pattern, html)`, где `pattern` пришёл деструктуризацией.
    Разведка по прямому аргументу дала 26 сайтов и НИ ОДНОГО кустодианского,
    то есть объявила класс населённым нулём известных членов.
    """
    root = _tree(tmp_path, {
        "scripts/custodian.py": _TABLE_READER,
        "landing/src/pages/index.astro": '<b id="m-days">60</b>\n'})
    row = _by_identity(root)["m-days"]
    assert row["parity"] == fmrc.CONFIRMED
    assert row["form"] == "re.search"
    assert row["identity_outcome"] == fmrc.IDENTITY_LITERAL


def test_a_neighbouring_column_is_not_attributed_to_the_pattern(
        tmp_path: Path) -> None:
    """Дефект 2: грубая деструктуризация выдумала 42 опровержения.

    В строке таблицы рядом с шаблоном лежит ЕЩЁ ОДИН id — колонка `elem_id`
    второй записи. Приписать её литералы позиции шаблона значит напечатать
    претензию, которой в коде нет.
    """
    source = _TABLE_READER.replace(
        '''        ("home", "m-days", r'id="m-days"[^>]*>\\s*(\\d+)', "why"),''',
        '''        ("home", "m-days", r'id="m-days"[^>]*>\\s*(\\d+)', "why"),
        ("home", "ghost-id", r'id="m-gates"[^>]*>\\s*(\\d+)', "why2"),''')
    root = _tree(tmp_path, {
        "scripts/custodian.py": source,
        "landing/src/pages/index.astro": '<b id="m-days">60</b>\n'})
    found = _by_identity(root)
    # ЧИТАЮТСЯ две личности из колонки ШАБЛОНА…
    assert set(found) == {"m-days", "m-gates"}
    # …а колонка `elem_id` шаблоном не является и претензией не становится.
    assert "ghost-id" not in found


def test_an_interpolated_identity_is_a_prefix(tmp_path: Path) -> None:
    """Дефект 3: `id="view-{key}"` схлопывалось в выдуманный `view-`."""
    root = _tree(tmp_path, {
        "scripts/reader.py": (
            "def check(page, key):\n"
            "    return f'id=\"view-{key}\"' in page\n"),
        "landing/src/pages/shell.astro": '<div id="view-build"></div>\n'})
    rows = _rows(root)
    assert [r["identity"] for r in rows] == [None]
    assert rows[0]["identity_outcome"] == fmrc.IDENTITY_TRUNCATED
    assert rows[0]["parity"] == fmrc.UNMEASURED_IDENTITY


def test_an_enumerator_has_no_subject_and_leaves_the_class(tmp_path: Path
                                                            ) -> None:
    """`id="([A-Za-z]+)"` просит ВСЕ личности — претензии к одной у него нет.

    Это НЕ третий исход: третий говорит «не знаю», а здесь известно точно,
    что предмета нет. `site_content_audit` и `check_change_evidence` именно
    такие, и зачесть их в класс значило бы раздуть население формой, которая
    вреда заказа не несёт.
    """
    root = _tree(tmp_path, {
        "scripts/audit.py": (
            "import re\n"
            "def ids(html):\n"
            "    return re.findall(r'id=\"([A-Za-z0-9_-]+)\"', html)\n"),
        "landing/src/pages/index.astro": _MARKUP})
    doc = fmrc.measure(root, now=_NOW)
    assert doc["enumerators_out_of_class"] == 1
    assert doc["foreign_population"] == 0
    assert doc["rows"] == []


def test_prose_naming_an_identity_is_not_a_producer(tmp_path: Path) -> None:
    """Дефект 7, самый дорогой: разбор находки ОТМЕНЯЛ находку.

    `.md` считался разметкой — и в ту минуту, когда ADR-620 назвал
    `spa-freshness-banner` неподтверждённым, его собственный текст стал
    «производителем» этой личности, и находка исчезла из ответа. `docs/` полон
    упоминаний id, и ни одно из них страницу не отдаёт.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "docs/decisions/ADR-999-finding.md": (
            'Личность `id="hero-day"` не пишет в дереве никто.\n')})
    assert _by_identity(root)["hero-day"]["parity"] == fmrc.REFUTED


def test_prose_under_a_page_serving_root_is_a_producer(tmp_path: Path) -> None:
    """КОНТРОЛЬ к предыдущему: под `landing/` `.mdx` — настоящая страница.

    Запретить прозу целиком значило бы опровергнуть читателей настоящих
    `.mdx`-страниц. Сцены различаются РОВНО корнем.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/post.mdx": '<span id="hero-day">60</span>\n'})
    assert _by_identity(root)["hero-day"]["parity"] == fmrc.CONFIRMED


def test_the_instruments_own_scene_is_excluded_from_the_oracle(tmp_path: Path
                                                               ) -> None:
    """Дефект 8: прибор живёт в населении, которое мерит (урок #776).

    Батарея прибора пишет синтетическую разметку. Зачесть её в оракул значило
    бы разрешить ФИКСТУРАМ ПРИБОРА подтверждать претензии третьих читателей —
    тот же вред, что `ECHOED_BY_OWN_SCENE`, но на уровень выше.
    """
    own = ("from spa_core.monitoring import foreign_markup_reader_census\n"
           "SCENE = '<b id=\"hero-day\">1</b>'\n")
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "spa_core/tests/test_the_instrument.py": own})
    doc = fmrc.measure(root, now=_NOW)
    assert doc["oracle_own_scene_files_excluded"] == [
        "spa_core/tests/test_the_instrument.py"]
    assert _by_identity(root)["hero-day"]["parity"] == fmrc.REFUTED


def test_a_file_not_referencing_the_instrument_stays_in_the_oracle(
        tmp_path: Path) -> None:
    """КОНТРОЛЬ к предыдущему: сцены различаются РОВНО ссылкой на прибор."""
    other = ("from spa_core.monitoring import declared_source_live_parity\n"
             "SCENE = '<b id=\"hero-day\">1</b>'\n")
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "spa_core/tests/test_the_other.py": other})
    doc = fmrc.measure(root, now=_NOW)
    assert doc["oracle_own_scene_files_excluded"] == []
    assert _by_identity(root)["hero-day"]["parity"] == fmrc.CONFIRMED_BY_PYTHON


def test_an_element_of_a_named_container_inherits_nothing(tmp_path: Path
                                                           ) -> None:
    """Дефект 9: утечка литералов контейнера через ИНДЕКС.

    `row["identity"] not in markup` — читатель БЕЗ литеральной личности: что
    он ищет, решает рантайм. Унаследовав литералы `row`, сайт объявлял
    претензию к каждой личности, упомянутой в файле.
    """
    root = _tree(tmp_path, {
        "scripts/reader.py": (
            "PROBES = [{'identity': 'hero-day'}]\n"
            "def check(rows, markup):\n"
            "    for row in rows:\n"
            "        if row['identity'] not in markup:\n"
            "            return row\n"
            "    return None\n"),
        "landing/src/pages/index.astro": _MARKUP})
    assert _rows(root) == []


# ───────────── ось «стог»: четыре двери наружу, своя, третий исход ────────

def test_a_call_across_a_module_border_is_a_foreign_haystack(tmp_path: Path
                                                              ) -> None:
    """Дефект 6: без этой двери 19 настоящих членов шли в «не измерено»."""
    root = _tree(tmp_path, {
        "tests/test_shell.py": (
            "import render\n"
            "def test_it():\n"
            "    page = render.page()\n"
            "    assert 'id=\"hero-day\"' in page\n"),
        "landing/src/pages/index.astro": _MARKUP})
    row = _by_identity(root)["hero-day"]
    assert row["haystack_origin"] == fmrc.HAY_PRODUCER_CALL
    assert row["parity"] == fmrc.CONFIRMED


def test_a_call_to_a_function_of_this_very_module_is_not_foreign(
        tmp_path: Path) -> None:
    """КОНТРОЛЬ к предыдущему: своя функция чужой двери не открывает.

    Иначе дверь «вызов» поглотила бы и модуль, собирающий разметку сам, —
    то есть ответила бы «чужая» там, где это догадка, а не замер.
    """
    root = _tree(tmp_path, {
        "scripts/own.py": (
            "def build():\n"
            "    return '<b id=\"hero-day\">1</b>'\n"
            "def check():\n"
            "    page = build()\n"
            "    return 'id=\"hero-day\"' in page\n"),
        "landing/src/pages/index.astro": _MARKUP})
    rows = _rows(_tree(tmp_path, {}))
    doc = fmrc.measure(root, now=_NOW)
    assert rows == []
    assert doc["haystack_origins"].get(fmrc.HAY_UNRESOLVED) == 1
    assert doc["foreign_population"] == 0


def test_the_network_door_is_named_as_its_own_origin(tmp_path: Path) -> None:
    root = _tree(tmp_path, {
        "scripts/fetcher.py": (
            "from urllib.request import urlopen\n"
            "def check(url):\n"
            "    html = urlopen(url).read().decode()\n"
            "    return 'id=\"hero-day\"' in html\n"),
        "landing/src/pages/index.astro": _MARKUP})
    assert _by_identity(root)["hero-day"]["haystack_origin"] == \
        fmrc.HAY_NETWORK


def test_the_file_door_is_named_as_its_own_origin(tmp_path: Path) -> None:
    root = _tree(tmp_path, {
        "scripts/linter.py": (
            "from pathlib import Path\n"
            "def check(path):\n"
            "    html = Path(path).read_text()\n"
            "    return 'id=\"hero-day\"' in html\n"),
        "landing/src/pages/index.astro": _MARKUP})
    assert _by_identity(root)["hero-day"]["haystack_origin"] == fmrc.HAY_FILE


def test_markup_built_by_this_module_is_out_of_the_class(tmp_path: Path
                                                          ) -> None:
    """Претензии к ЧУЖОЙ разметке у производителя нет — он её пишет."""
    root = _tree(tmp_path, {
        "scripts/writer.py": (
            "HTML = '<b id=\"hero-day\">1</b>'\n"
            "def check():\n"
            "    return 'id=\"hero-day\"' in HTML\n"),
        "landing/src/pages/index.astro": _MARKUP})
    doc = fmrc.measure(root, now=_NOW)
    assert doc["population"] == 1
    assert doc["own_markup"] == 1
    assert doc["foreign_population"] == 0


# ───────────── ось «громкость» ─────────────────────────────────────────────

def test_an_index_miss_is_loud_by_construction(tmp_path: Path) -> None:
    root = _tree(tmp_path, {
        "scripts/reader.py": (
            "def check(html):\n"
            "    return html.index('id=\"hero-day\"')\n"),
        "landing/src/pages/index.astro": _MARKUP})
    assert _by_identity(root)["hero-day"]["loudness"] == fmrc.LOUD_RAISES


def test_a_membership_miss_says_nothing(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM,
                            "landing/src/pages/index.astro": _MARKUP})
    assert _by_identity(root)["hero-day"]["loudness"] == \
        fmrc.SILENT_MEMBERSHIP


def test_loudness_behind_a_module_level_skip_is_not_called_loud(
        tmp_path: Path) -> None:
    """Громкий отказ за модульным скипом громким НЕ зовётся.

    Это живая форма: `test_dashboard_truth_layer` снимает себя целиком, когда
    `index.html` отсутствует, — и тринадцать его утверждений не исполняются
    НИ РАЗУ. Назвать такой сайт громким значило бы выдать НЕ ИЗМЕРЕННОЕ за
    пройденное (урок #465).
    """
    body = (
        "import pytest\n"
        "from pathlib import Path\n"
        "if not Path('gone.html').is_file():\n"
        "    pytest.skip('retired', allow_module_level=True)\n"
        "def test_it(src):\n"
        "    assert 'id=\"hero-day\"' in src\n")
    root = _tree(tmp_path, {"tests/test_guard.py": body,
                            "landing/src/pages/index.astro": _MARKUP})
    row = _by_identity(root)["hero-day"]
    assert row["loudness"] == fmrc.LOUD_BEHIND_MODULE_SKIP
    assert row["module_level_skip"] is True
    assert fmrc.measure(root, now=_NOW)["behind_a_module_level_skip"] == 1


def test_the_same_assert_without_the_module_skip_is_loud(tmp_path: Path
                                                          ) -> None:
    """КОНТРОЛЬ к предыдущему: сцена отличается РОВНО модульным скипом."""
    body = (
        "def test_it(src):\n"
        "    assert 'id=\"hero-day\"' in src\n")
    root = _tree(tmp_path, {"tests/test_guard.py": body,
                            "landing/src/pages/index.astro": _MARKUP})
    row = _by_identity(root)["hero-day"]
    assert row["loudness"] == fmrc.LOUD_ASSERTED
    assert row["module_level_skip"] is False


# ───────────── третий исход САМОГО шага ────────────────────────────────────

def test_a_missing_root_is_a_named_refusal_not_zero_findings(tmp_path: Path
                                                              ) -> None:
    with pytest.raises(fmrc.NotMeasured) as caught:
        fmrc.measure(tmp_path / "nope", now=_NOW)
    assert caught.value.gap == fmrc.GAP_NO_TREE


def test_a_tree_without_code_is_a_named_refusal(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"landing/src/pages/index.astro": _MARKUP})
    with pytest.raises(fmrc.NotMeasured) as caught:
        fmrc.measure(root, now=_NOW)
    assert caught.value.gap == fmrc.GAP_NO_CODE


def test_the_refusal_is_an_outcome_of_run_and_a_nonzero_exit(tmp_path: Path
                                                             ) -> None:
    """Отказ обязан быть ИСХОДОМ на любой глубине, а не трассировкой."""
    root = _tree(tmp_path, {"landing/src/pages/index.astro": _MARKUP})
    out = root / "census.json"
    outcome = fmrc.run(root, dest=out, now=_NOW)
    assert outcome["measured"] is False
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["status"] == "UNMEASURED" and doc["gap"] == fmrc.GAP_NO_CODE
    assert fmrc.main(["--root", str(root), "--out", str(out)]) == 2


def test_a_measured_run_exits_zero_and_writes_the_artifact(tmp_path: Path
                                                            ) -> None:
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM,
                            "landing/src/pages/index.astro": _MARKUP})
    out = root / "census.json"
    assert fmrc.main(["--root", str(root), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["status"] == "MEASURED"
    assert doc["applied"] is False


# ───────────── форма ответа ────────────────────────────────────────────────

def test_the_clock_arrives_as_an_input(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM,
                            "landing/src/pages/index.astro": _MARKUP})
    assert fmrc.measure(root, now=_NOW)["generated_at"] == _NOW.isoformat()


def test_the_unresolved_remainder_is_printed_loudly(tmp_path: Path) -> None:
    """Остаток «происхождение не свёрнуто» обязан быть ВИДЕН в отчёте.

    Он в класс не зачтён, и молчание о нём читалось бы как чистота.
    """
    root = _tree(tmp_path, {
        "scripts/own.py": (
            "def build():\n"
            "    return '<b id=\"hero-day\">1</b>'\n"
            "def check():\n"
            "    page = build()\n"
            "    return 'id=\"hero-day\"' in page\n"),
        "landing/src/pages/index.astro": _MARKUP})
    doc = fmrc.measure(root, now=_NOW)
    assert doc["origin_unresolved"] == 1
    text = "\n".join(fmrc.report(doc))
    assert "НЕ ИЗМЕРЕНО происхождение стога у 1" in text


def test_every_judged_site_carries_a_declared_parity(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"scripts/reader.py": _READER_PARAM,
                            "landing/src/pages/index.astro": _MARKUP,
                            "scripts/custodian.py": _TABLE_READER})
    doc = fmrc.measure(root, now=_NOW)
    assert doc["rows"]
    for row in doc["rows"]:
        assert row["parity"] in fmrc._PARITY_OUTCOMES
        assert row["loudness"] in fmrc._LOUDNESS_OUTCOMES
        assert row["identity_outcome"] in fmrc._IDENTITY_OUTCOMES
    assert sum(doc["parity_outcomes"].values()) == doc["foreign_population"]


def test_the_harm_tally_is_the_sum_of_its_two_named_halves(tmp_path: Path
                                                            ) -> None:
    """`unsupported` = «нигде» + «только своя сцена», и половины названы."""
    root = _tree(tmp_path, {
        "scripts/reader.py": _READER_PARAM,
        "landing/src/pages/index.astro": "<main/>\n",
        "scripts/other.py": (
            "def check(html):\n"
            "    return 'id=\"ghost\"' in html\n"),
        "spa_core/tests/test_other.py": (
            "import other\n"
            "def test_it():\n"
            "    assert other.check('<i id=\"ghost\">1</i>')\n"),
    })
    doc = fmrc.measure(root, now=_NOW)
    assert doc["refuted"] == 1 and doc["echoed_by_own_scene"] == 1
    assert doc["unsupported"] == doc["refuted"] + doc["echoed_by_own_scene"]


def test_the_instrument_does_not_import_the_network(tmp_path: Path) -> None:
    """Сеть — дверь кустодиана, а не прибора (та же граница, что ADR-594)."""
    source = Path(fmrc.__file__).read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "http.client", "socket"):
        assert f"import {forbidden}" not in source


# ───────────── сверка с живым деревом и с ADR-594 ─────────────────────────

#: Замер ЖИВОГО дерева стоит ~50 с (5 000 модулей + 2 700 файлов разметки),
#: и спрашивают его ДВА теста. Общая фикстура модуля — не украшение: без неё
#: файл добавлял бы к приёмочному прогону минуту ВТОРОЙ раз за тот же ответ,
#: а прогон и так вырос с 22 мин до 4 ч (замер #789).
@pytest.fixture(scope="module")
def live_tree() -> dict:
    root = fmrc._ROOT
    markup, _prefixes, files = fmrc.build_oracle(root)
    return {"doc": fmrc.measure(root, now=_NOW), "markup": markup,
            "oracle_files": files}


def test_the_live_tree_is_measured_and_the_custodian_is_in_the_class(
        live_tree: dict) -> None:
    """Кустодиан обязан БЫТЬ в населении: он и есть известный член класса.

    Если он выпал, значит признак снова отвечает на свой вопрос вместо
    нужного — ровно дефект 1 в его первой форме.
    """
    doc = live_tree["doc"]
    assert doc["status"] == "MEASURED"
    assert fmrc.REGISTRY_READER in doc["readers"]
    assert doc["foreign_population"] >= 1


def test_the_tree_agrees_with_the_live_measurement_of_adr_594(
        live_tree: dict) -> None:
    """Согласие с ADR-594 проверяется ИМПЛИКАЦИЕЙ, а не числом.

    ADR-594 ЖИВЫМ запросом назвал опровергнутыми `sl-day`/`sl-gates`/`sl-apy`.
    Утверждать «их ровно три» значило бы краснеть от законной правки сайта.
    Утверждение слабее и устойчивее: личность, которую НЕ пишет ни один файл
    разметки дерева, не вправе выйти из переписи подтверждённой.
    """
    doc = live_tree["doc"]
    markup = live_tree["markup"]
    assert live_tree["oracle_files"] > 0, (
        "оракул пуст — вердикт ниже был бы о пустоте, а не о дереве")
    for row in doc["rows"]:
        if row["identity"] and row["identity"] not in markup:
            assert row["parity"] != fmrc.CONFIRMED, (
                f"{row['identity']} объявлен подтверждённым РАЗМЕТКОЙ, "
                f"которой его не пишет ни один файл")
