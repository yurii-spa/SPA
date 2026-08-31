"""У графы «не измерено» есть ПОЛ, и ноль ею не цель (цикл #442, ADR-197).

Решение владельца 2026-08-31T14:33Z (карточка
`owner-decision-nol-ne-izmereno-etim-instrumentom-nedost`, **вариант 1**):
«признать, что у этого инструмента графа „не измерено“ пустой не бывает, и
перестать целиться в ноль ИМ; про такие модули отвечает второй инструмент —
аудит слепоты, который зовёт их так же, как настоящий прод».

**Авария, которую воспроизводит каждый тест.** Отчёт печатал графу «не
измерено» одним числом. Число прочиталось как показатель здоровья, который
надо гнать к нулю, и в таком виде уехало в критерий приёмки карточки
владельца («строка „не измерено“ станет нулём»). Выполнить его нельзя:
`COVERAGE_UNMEASURED` — это модули, которые берут факты из `_protocol_facts`
САМИ, мимо переданной записи, и покрытие ЭТОЙ записи у них не измеримо ПО
ПОСТРОЕНИЮ. Замер #441 (ADR-196 §6) поднял число 126 → 130 именно потому, что
заменил НЕВЕРНЫЙ вердикт на честный. Ноль достижим ровно одним способом —
назвать неизмеренное измеренным, то есть тем подлогом, ради поимки которого
инструмент и написан.

**Обратный контроль обязателен и здесь — и он тут главный.** Починка, которая
объявляет «полом» что угодно неудобное, была бы отмыванием дефектов: `NO_ENTRY`
/ `SHAPE_NOT_PROBED` / `IMPORT_ERR` сокращаются объявленным входом самого
модуля (ADR-158) и полом НЕ являются. Поэтому тесты краснеют в обе стороны.

Замер на живой популяции Tier-B 31.08 (479 модулей): 130 = пол 55 + остаток 75
(NO_ENTRY 72 + SHAPE_NOT_PROBED 3), вердикты не сдвинулись НИ У ОДНОГО модуля —
правка только в чтении.

Проверки герметичны: ни реестра, ни сети, ни `data/`. Времени в них нет,
литеральных дат нет — метка FROZEN-DATE-OK не нужна.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def feas():
    return _load("_test_wiring_feasibility_unmeasured_floor",
                 "scripts/audit_tier_c_wiring_feasibility.py")


def _row(module: str, verdict: str, measured: bool) -> dict:
    return {"module": module, "verdict": verdict, "measured": measured}


#: Портрет замера 31.08 в миниатюре: пол, остаток двух видов и измеренные.
POPULATION = [
    _row("ctx_taker_a", "COVERAGE_UNMEASURED", False),
    _row("ctx_taker_b", "COVERAGE_UNMEASURED", False),
    _row("no_entry_mod", "NO_ENTRY", False),
    _row("unshaped_mod", "SHAPE_NOT_PROBED", False),
    _row("broken_import", "IMPORT_ERR", False),
    _row("wirable_mod", "WIRABLE", True),
    _row("blind_mod", "BLIND", True),
    _row("uncovered_mod", "UNCOVERED", True),
]


# ─── ГЛАВНЫЙ контроль: у числа есть разбор, и он поимённый ──────────────────

def test_unmeasured_is_partitioned_into_floor_and_remainder(feas):
    """Без разбора графа — одно число, и читается как цель «ноль»."""
    out = feas.summarize_unmeasured(POPULATION)
    assert out["unmeasured_floor"] == ["ctx_taker_a", "ctx_taker_b"], out
    assert out["unmeasured_reducible"] == ["broken_import", "no_entry_mod",
                                           "unshaped_mod"], out
    assert out["unmeasured_floor_count"] == 2
    assert out["unmeasured_reducible_count"] == 3


def test_floor_and_remainder_cover_the_whole_column_without_overlap(feas):
    """Разбор обязан быть РАЗБИЕНИЕМ: потерянный модуль исчез бы из обоих
    списков молча, а посчитанный дважды раздул бы и пол, и остаток."""
    out = feas.summarize_unmeasured(POPULATION)
    floor, reducible = set(out["unmeasured_floor"]), set(out["unmeasured_reducible"])
    unmeasured = {r["module"] for r in POPULATION if not r["measured"]}
    assert floor | reducible == unmeasured
    assert floor & reducible == set()


def test_coverage_unmeasured_is_the_floor(feas):
    """Тот самый класс из ответа владельца: движок берёт факты сам."""
    assert feas.is_unmeasured_floor("COVERAGE_UNMEASURED") is True


# ─── ОБРАТНЫЕ контроли: полом не объявляется что попало ─────────────────────

@pytest.mark.parametrize("verdict", ["NO_ENTRY", "SHAPE_NOT_PROBED", "IMPORT_ERR"])
def test_fixable_verdicts_are_never_called_floor(feas, verdict):
    """Отмывание дефекта под видом «структурного пола» — тот самый дефект,
    который инструмент ловит у других. Эти три чинятся объявленным входом."""
    assert feas.is_unmeasured_floor(verdict) is False
    out = feas.summarize_unmeasured([_row("m", verdict, False)])
    assert out["unmeasured_floor"] == []
    assert out["unmeasured_reducible"] == ["m"]


def test_floor_verdicts_are_never_measured_verdicts(feas):
    """Состав пола под контролем: измеренный вердикт (`BLIND`, `WIRABLE`,
    `UNCOVERED`…) в полу означал бы, что измеренное объявлено неизмеримым."""
    assert feas.UNMEASURED_FLOOR_VERDICTS & feas.MEASURED_VERDICTS == frozenset()


def test_measured_rows_land_in_neither_list(feas):
    """Пол и остаток — про графу «не измерено», и только про неё."""
    out = feas.summarize_unmeasured(POPULATION)
    for name in ("wirable_mod", "blind_mod", "uncovered_mod"):
        assert name not in out["unmeasured_floor"]
        assert name not in out["unmeasured_reducible"]


def test_breakdown_is_computed_from_measured_flag_not_re_derived(feas):
    """`measured` проставляет `run_audit` по `MEASURED_VERDICTS` — разбор
    обязан читать ЕГО. Второе, независимое суждение «измерено ли» в другом
    месте и есть механизм, которым два ответа расходятся."""
    row = _row("declared_measured", "COVERAGE_UNMEASURED", True)
    out = feas.summarize_unmeasured([row])
    assert out["unmeasured_floor"] == []
    assert out["unmeasured_reducible"] == []


# ─── Читатель обязан это УВИДЕТЬ, а не найти в JSON ────────────────────────

def test_report_names_the_second_instrument_and_denies_zero_as_a_goal(feas):
    """Разбор, живущий только в JSON, читателя не достигает: жалоба владельца
    родилась из СТРОКИ вывода, а не из файла."""
    out = feas.summarize_unmeasured(POPULATION)
    caveat = out["unmeasured_floor_caveat"]
    assert "НЕДОСТИЖИМ" in caveat and "целью не является" in caveat
    assert out["second_instrument"] == "scripts/audit_protocol_blindness.py"
    assert out["second_instrument"] in caveat
    assert "ADR-197" in caveat


def test_summary_lines_show_floor_remainder_and_the_caveat(feas):
    """Печать — тот канал, который читают. Проверяется на синтетическом
    отчёте: гонять живую популяцию в тесте нельзя (модули пишут data/-логи)."""
    report = {
        "module_count": 8, "counts": {"BLIND": 1},
        "measured_count": 3, "unmeasured_count": 5,
        "unmeasured": sorted(r["module"] for r in POPULATION if not r["measured"]),
        "wirable": ["wirable_mod"],
        **feas.summarize_unmeasured(POPULATION),
    }
    lines = feas.format_summary(report)
    body = "\n".join(lines)
    assert "ПОЛ (этим инструментом недостижим): 2" in body
    assert "ОСТАТОК (сокращается объявленным входом модуля): 3" in body
    assert "scripts/audit_protocol_blindness.py" in body
    assert "НЕДОСТИЖИМ" in body


def test_run_audit_carries_the_breakdown_into_the_report(feas, monkeypatch):
    """Проводка проверяется ФОРМОЙ вызова, а не наличием функции: разбор,
    не доехавший до отчёта, не существует для читателя."""
    rows = [dict(r) for r in POPULATION]
    monkeypatch.setattr(feas.registry, "get_tier_modules",
                        lambda tier: [{"module": r["module"]} for r in rows])
    by_name = {r["module"]: r for r in rows}
    monkeypatch.setattr(
        feas, "probe_module",
        lambda info, **kw: {"module": info["module"],
                            "verdict": by_name[info["module"]]["verdict"]})
    report = feas.run_audit("B")
    assert report["unmeasured_floor"] == ["ctx_taker_a", "ctx_taker_b"]
    assert report["unmeasured_reducible_count"] == 3
    assert report["unmeasured_count"] == 5
    assert "unmeasured_floor_caveat" in report
