"""Публикуемая ставка НИКОГДА не выше измеренной — решение владельца ADR-563.

Мера по ИСХОДУ, а не по тексту файла: JS исполняется настоящим `node`, и
утверждение проверяется напечатанной строкой. Претензия в комментарии здесь не
годится — в этом репозитории они ветшают молча (урок `injected-clock`, ADR-477).

Положительный контроль у каждой проверки — та же сцена с ПРЕЖНЕЙ арифметикой
(`toFixed(1)`, округление к ближайшему): она обязана напечатать 5,0 % там, где
новая печатает 4,9 %. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md`).

`node` не найден ⇒ **НЕ ИЗМЕРЕНО** громким отказом, а не скипом: «не измерено»
не имеет права стать неотличимым от «прошло» (урок `pyflakes`, цикл #465).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

#: Замер, вызвавший вопрос владельца: измерено 4,9637 %, печаталось 5,0 %.
MEASURED_PCT = 4.9637

_LIB = Path(__file__).resolve().parents[2] / "landing" / "src" / "lib"

#: Строка импорта JSON в исходниках: Astro разрешает её сам, а `node` требует
#: атрибут типа. Подменяется ТОЛЬКО она — остальной файл идёт как есть, иначе
#: мерился бы не тот код, который уезжает на сайт.
_JSON_IMPORT = "import NUMBERS from '../data/site_numbers.json';"
_JSON_IMPORT_NODE = ("import NUMBERS from '../data/site_numbers.json' "
                     "with { type: 'json' };")


def _node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.fail("НЕ ИЗМЕРЕНО: `node` не найден — исход JS не наблюдён; "
                    "это третий исход, а не зелёная проверка")
    return found


def _scene(tmp_path: Path, apy: float, *, legacy: bool = False) -> Path:
    """Одноразовая сцена: настоящие модули витрины + витрина с заданной ставкой.

    `legacy=True` возвращает арифметику к округлению к ближайшему — это
    положительный контроль: он обязан напечатать 5,0 % на том же входе.
    """
    lib = tmp_path / "src" / "lib"
    data = tmp_path / "src" / "data"
    lib.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for name in ("site_numbers.js", "realized_rate.js"):
        text = (_LIB / name).read_text(encoding="utf-8")
        text = text.replace(_JSON_IMPORT, _JSON_IMPORT_NODE)
        if legacy:
            text = text.replace("floorTo(n, 1)", "n").replace(
                "floorTo(n, digits)", "n")
        (lib / name).write_text(text, encoding="utf-8")
    (data / "site_numbers.json").write_text(json.dumps({
        "measured_at": "4 октября",
        "headline": {"apy": {"value": apy}},
        "books": {"balanced": {"apy": {"value": apy},
                               "drawdown": {"value": 2.0}}},
    }), encoding="utf-8")
    return lib


def _ask(tmp_path: Path, apy: float, *, legacy: bool = False) -> dict:
    """Спросить у JS, что он НАПЕЧАТАЕТ. Исход, а не текст исходника."""
    lib = _scene(tmp_path, apy, legacy=legacy)
    (lib / "ask.mjs").write_text(
        "import { realizedApyLabel } from './realized_rate.js';\n"
        "import { rateWithTail, pctDown, floorTo } from './site_numbers.js';\n"
        "console.log(JSON.stringify({\n"
        "  label_ru: realizedApyLabel(null, true),\n"
        "  label_en: realizedApyLabel(null, false),\n"
        "  book_ru: rateWithTail('balanced', true).text,\n"
        "  pct_down: pctDown({ value: " + repr(apy) + " }, false),\n"
        "  floor_raw: floorTo(" + repr(apy) + ", 1),\n"
        "}));\n", encoding="utf-8")
    proc = subprocess.run([_node(), str(lib / "ask.mjs")], capture_output=True,
                          text=True, timeout=120)
    if proc.returncode != 0:
        pytest.fail("НЕ ИЗМЕРЕНО: node не исполнил витрину — "
                    f"{proc.returncode}: {proc.stderr.strip()[:600]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_headline_rate_is_never_published_above_the_measured_value(tmp_path):
    """4,9637 % обязано печататься как 4,9 %, а не как 5,0 % (инв. #8)."""
    out = _ask(tmp_path, MEASURED_PCT)
    assert out["label_ru"] == "4,9%", out
    assert out["label_en"] == "4.9%", out


def test_the_previous_arithmetic_published_more_than_measured(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: прежний код печатал 5,0 % — проверка бьётся."""
    out = _ask(tmp_path, MEASURED_PCT, legacy=True)
    assert out["label_ru"] == "5,0%", out


def test_the_book_rate_goes_through_the_same_arithmetic(tmp_path):
    """У ставки книги цена ошибки та же — она тоже видна посетителю."""
    out = _ask(tmp_path, MEASURED_PCT)
    assert out["book_ru"].startswith("4,9% годовых"), out
    assert "просадка" in out["book_ru"], out


def test_a_rate_that_is_already_exact_does_not_lose_a_digit(tmp_path):
    """Двоичная дробь 2.9 лежит как 2.8999999999999996.

    Без эпсилона «вниз» срезало бы знак у числа, которое УЖЕ ровно, — и
    занижение стало бы не осторожностью, а ошибкой.
    """
    out = _ask(tmp_path, 2.9)
    assert out["label_ru"] == "2,9%", out
    assert out["floor_raw"] == 2.9, out


def test_rounding_down_holds_for_a_value_just_below_the_next_tenth(tmp_path):
    out = _ask(tmp_path, 5.0999)
    assert out["label_en"] == "5.0%", out


def test_rounding_down_holds_where_nearest_rounds_up(tmp_path):
    """Разность пород видна на одном входе: 5,06 % → 5,0 % вниз, 5,1 % к ближайшему."""
    assert _ask(tmp_path, 5.06)["label_en"] == "5.0%"
    assert _ask(tmp_path, 5.06, legacy=True)["label_en"] == "5.1%"


def test_the_literal_midpoint_does_not_round_up_in_js_and_that_was_measured(
        tmp_path):
    """ЗАМЕР, а не предположение: `(5.05).toFixed(1)` в JS даёт «5.0», не «5.1».

    Первая редакция этого контроля брала 5,05 % как середину, на которой
    округление к ближайшему обязано дать 5,1 %, — и контроль покраснел. Причина
    не в коде витрины: двоичная 5.05 лежит чуть НИЖЕ середины, поэтому `toFixed`
    честно идёт вниз. Утверждение сохранено отдельной строкой, потому что ложная
    посылка в положительном контроле опаснее его отсутствия: она объявила бы
    исправную арифметику сломанной.
    """
    assert _ask(tmp_path, 5.05, legacy=True)["label_en"] == "5.0%"
    assert _ask(tmp_path, 5.05)["label_en"] == "5.0%"


def test_an_absent_rate_still_renders_no_number_at_all(tmp_path):
    """Нет замера ⇒ «нет данных», НИКОГДА последнее известное число."""
    out = _ask(tmp_path, 0)
    assert out["label_ru"] == "нет данных", out
    assert out["label_en"] == "data unavailable", out
