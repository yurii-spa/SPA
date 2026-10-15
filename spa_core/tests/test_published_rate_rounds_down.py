"""Публикуемая ставка — два знака, ROUND_HALF_UP (ADR-660, решение владельца 2026-10-08).

ИСТОРИЯ (инв. #16, запись в журнале): до 08.10 этот файл держал ADR-563 — ставка округлялась
ВНИЗ до одного знака. Владелец заменил это правило; проверки переписаны на новое правило
НАМЕРЕННО, не ослаблены: число проверяемых исходов выросло (ничьи 2.675/1.005, отрицательная
половина, «нет данных»), положительный контроль по-прежнему ловит прежнюю арифметику.

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
NB = "\u00a0"

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

    `legacy=True` возвращает двоичное `toFixed(2)` — это положительный контроль:
    на ничьих (2.675, 1.005) оно обязано разойтись с правилом владельца.
    """
    lib = tmp_path / "src" / "lib"
    data = tmp_path / "src" / "data"
    lib.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    # P1 wave 2: the arithmetic moved to pct_format.js (site_numbers.js re-exports it) — the scene copies
    # the real module, and the positive control patches the formatter where it now lives.
    for name in ("pct_format.js", "site_numbers.js", "realized_rate.js"):
        text = (_LIB / name).read_text(encoding="utf-8")
        text = text.replace(_JSON_IMPORT, _JSON_IMPORT_NODE)
        if legacy:
            marker = "export function fmtPct2(n, ru = false, signed = false) {\n"
            assert marker in text or name != "pct_format.js", "scene marker moved"
            text = text.replace(marker, marker + "  if (typeof n === 'number' && Number.isFinite(n)) "
                                "{ const s = n.toFixed(2); return (ru ? s.replace('.', ',') + '\\u00a0%' : s + '%'); }\n")
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
        "import { rateWithTail, pctDown } from './site_numbers.js';\n"
        "console.log(JSON.stringify({\n"
        "  label_ru: realizedApyLabel(null, true),\n"
        "  label_en: realizedApyLabel(null, false),\n"
        "  book_ru: rateWithTail('balanced', true).text,\n"
        "  pct_down: pctDown({ value: " + repr(apy) + " }, false),\n"

        "}));\n", encoding="utf-8")
    proc = subprocess.run([_node(), str(lib / "ask.mjs")], capture_output=True,
                          text=True, timeout=120)
    if proc.returncode != 0:
        pytest.fail("НЕ ИЗМЕРЕНО: node не исполнил витрину — "
                    f"{proc.returncode}: {proc.stderr.strip()[:600]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_headline_rate_has_two_decimals_half_up(tmp_path):
    """4,9637 % печатается как 4,96 % (было 4,9 % вниз по ADR-563)."""
    out = _ask(tmp_path, MEASURED_PCT)
    assert out["label_ru"] == "4,96" + NB + "%", out
    assert out["label_en"] == "4.96%", out
    assert out["pct_down"] == "4.96%", out   # имя прежнее, правило новое — у функции нет второй арифметики


def test_ties_round_half_up_on_the_decimal_not_the_binary_fraction(tmp_path):
    """2.675 лежит как 2.67499…; правило владельца — 2,68, а не 2,67."""
    assert _ask(tmp_path, 2.675)["label_en"] == "2.68%"
    assert _ask(tmp_path, 1.005)["label_en"] == "1.01%"
    assert _ask(tmp_path, 4.895)["label_en"] == "4.90%"


def test_positive_control_binary_toFixed_disagrees_on_the_ties(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: двоичное toFixed(2) на тех же ничьих печатает иное — проверка бьётся."""
    assert _ask(tmp_path, 2.675, legacy=True)["label_en"] == "2.67%"
    assert _ask(tmp_path, 1.005, legacy=True)["label_en"] == "1.00%"


def test_the_book_rate_goes_through_the_same_arithmetic(tmp_path):
    """У ставки книги цена ошибки та же — она тоже видна посетителю."""
    out = _ask(tmp_path, MEASURED_PCT)
    assert out["book_ru"].startswith("4,96" + NB + "% годовых"), out
    assert "просадка 2,00" + NB + "%" in out["book_ru"], out


def test_an_absent_rate_still_renders_no_number_at_all(tmp_path):
    """Нет замера ⇒ «нет данных», НИКОГДА последнее известное число."""
    out = _ask(tmp_path, 0)
    assert out["label_ru"] == "нет данных", out
    assert out["label_en"] == "data unavailable", out
