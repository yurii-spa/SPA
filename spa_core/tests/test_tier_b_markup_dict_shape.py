"""test_tier_b_markup_dict_shape.py — разметка «различается не тем» перестала
быть слепой к форме входа движка.

**Реальная авария, которую воспроизводят эти тесты (циклы #134/#135 → #137/#138).**

Цикл #134 закрыл класс «правдоподобно различающееся число о неизмеренном»: 20
модулей Tier-B различают протоколы ПОБОЧНЫМИ полями, помечены в
``_protocol_key_coverage.UNSOURCED_DETAIL`` и исключены `run_tier_b` из
composite и из числителя confidence.

Но разметку производит `scripts/audit_tier_c_wiring_feasibility.py`, а он звал
ТОЛЬКО движки, объявившие вход СПИСКОМ записей; всё прочее получало
`SHAPE_NOT_PROBED`. Поэтому в разметку структурно не мог попасть ни один
`dict`-образный движок — и все 20 помеченных оказались `list`-образными не
потому, что остальные чисты, а потому, что их **ни разу не смотрели**: 186 из
479 модулей Tier-B. Это тот же класс #29/#31/#35–#40, только этажом выше —
сторож честно отвечал на СВОЙ вопрос («различается ли не тем ЛИСТОВОЙ движок»),
а читался как ответ на нужный («различается ли не тем движок»).

После расширения инструмента на `dict`-форму (цикл #137, тесты
`test_wiring_feasibility_dict_shape.py`) разметка выросла 20 → 35, и все 15
новых — `dict`-образные. Замер на прод-пути: `ok` 104 → 94, `unsourced`
20 → 30, confidence aave_v3 0.2129 → 0.1921. Направление — fail-CLOSED:
модули только ВЫБЫВАЮТ из composite, ни один не возвращается.

**Обратные контроли обязательны.** Без них «набор вырос» сошло бы за
доказательство: листовое плечо обязано остаться на месте (иначе это подмена, а
не расширение), и ни один прежде помеченный модуль не имеет права пропасть.

Времени и свежести здесь нет, литеральных дат нет — метка FROZEN-DATE-OK не
нужна (правило `.claude/rules/deployment.md`).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def markup():
    from spa_core.analytics import _protocol_key_coverage as cov
    return cov


#: Что разметка знала ДО расширения (цикл #134). Ни одно из этих имён не имеет
#: права исчезнуть: расширение — добавление формы, а не пересмотр вердиктов.
_BASELINE_20 = frozenset({
    "defi_gas_cost_yield_drag_analyzer",
    "defi_oracle_risk_scorer",
    "defi_protocol_borrower_concentration_risk_analyzer",
    "defi_protocol_composability_risk_analyzer",
    "defi_protocol_mev_protection_effectiveness_analyzer",
    "defi_protocol_oracle_manipulation_risk_analyzer",
    "defi_protocol_regulatory_risk_scorer",
    "defi_token_governance_power_analyzer",
    "defi_yield_bearing_collateral_analyzer",
    "lending_pool_utilization_analyzer",
    "protocol_audit_coverage_scorer",
    "protocol_defi_vault_fee_structure_breakeven_analyzer",
    "protocol_defi_yield_duration_mismatch_analyzer",
    "protocol_ecosystem_health_scorecard",
    "protocol_governance_attack_resistance_scorer",
    "protocol_liquidation_history_analyzer",
    "protocol_oracle_risk_analyzer",
    "protocol_regulatory_risk_assessor",
    "protocol_security_audit_tracker",
    "yield_bearing_stablecoin_comparator",
})


@pytest.fixture(scope="module")
def call_shape():
    """Классификатор формы входа — ТОТ ЖЕ, которым произведена разметка.

    Своя копия проверки была бы хуже: `"dict" in annotation` считает
    `list[dict]` записью, и тест зеленел бы на непочиненном дереве (поймано
    контрольным прогоном по `origin/main`). Сам классификатор закреплён
    отдельно — `test_wiring_feasibility_dict_shape.py`.
    """
    import importlib.util

    path = REPO_ROOT / "scripts" / "audit_tier_c_wiring_feasibility.py"
    spec = importlib.util.spec_from_file_location("_markup_shape_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.call_shape


def _entrypoint(module_name: str, entry: str = "analyze"):
    mod = importlib.import_module("spa_core.analytics." + module_name)
    return getattr(mod, entry)


# ─── положительные контроли: dict-образные ловушки теперь помечены ───────────

def test_the_depeg_scorer_trap_is_marked(markup):
    """Оценка риска депега, которая НИКОГДА не видела пега.

    `protocol_defi_yield_bearing_stablecoin_risk_analyzer` публикует
    различающийся риск (60/60/70/60/70/60 на шести протоколах) и по аудиту
    слепоты числится `sensitive` — «работает». При этом профиль не даёт ему ни
    `peg_asset`, ни `days_since_depeg_event`, ни `collateral_ratio_pct`:
    покрытие 0.1667, всё различие пришло из побочных полей. До цикла #137
    инструмент не мог его увидеть — движок `dict`-образный.
    """
    d = markup.UNSOURCED_DETAIL.get(
        "protocol_defi_yield_bearing_stablecoin_risk_analyzer")
    assert d is not None, (
        "dict-образная ловушка не помечена — значит разметку снова производит "
        "инструмент, слепой к форме входа")
    assert d["coverage"] < 0.2, d
    missing = set(d["missing_keys"])
    assert {"peg_asset", "days_since_depeg_event"} <= missing, (
        "отказ обязан назвать ПРЕДМЕТ, которого нет, поимённо: %r" % (sorted(missing),))


def test_the_position_health_monitor_trap_is_marked(markup):
    """Монитор здоровья позиции без `health_factor`.

    `protocol_defi_position_health_monitor` читает `health_factor`,
    `unrealized_pnl_usd`, `entry_value_usd` — профиль не даёт НИ ОДНОГО
    (покрытие 0.1667), и всё же выдаёт различающееся число.
    """
    d = markup.UNSOURCED_DETAIL.get("protocol_defi_position_health_monitor")
    assert d is not None, "dict-образная ловушка не помечена"
    assert "health_factor" in set(d["missing_keys"]), d


def test_markup_is_not_blind_to_dict_shaped_engines(markup, call_shape):
    """Ядро аварии, СТРУКТУРНО: среди помеченных обязан быть `dict`-образный.

    До цикла #137 все 20 помеченных были `list`-образными — и это выглядело
    как свойство мира, а было свойством инструмента.
    """
    shapes = {}
    for name in sorted(markup.UNSOURCED_MODULES):
        try:
            shapes[name] = call_shape(_entrypoint(name))[0]
        except Exception:                      # noqa: BLE001 — форма неизвестна
            continue
    assert shapes, "ни один помеченный модуль не импортировался — тест слеп"
    assert "dict" in shapes.values(), (
        "ни один помеченный движок не объявляет вход ЗАПИСЬЮ — разметку "
        "производит инструмент, который такие движки не зовёт вовсе; "
        "формы помеченных: %r" % (sorted(set(shapes.values())),))


# ─── обратные контроли: расширение, а не подмена ─────────────────────────────

def test_the_list_shaped_arm_is_still_marked(markup):
    """Листовое плечо на месте: ловушка цикла #134 никуда не делась."""
    d = markup.UNSOURCED_DETAIL.get("defi_protocol_regulatory_risk_scorer")
    assert d is not None, (
        "исходная ловушка #134 пропала — это подмена плеча, а не расширение")
    assert "entity_incorporated" in set(d["missing_keys"]), d


def test_markup_only_grew_never_shrank(markup):
    """Ни один прежде помеченный модуль не имеет права вернуться в composite.

    Направление разметки — fail-CLOSED. Снятие пометки — не побочный эффект
    перегенерации, а отдельное решение с обоснованием (карточка), см. шапку
    `_protocol_key_coverage.py`.
    """
    lost = _BASELINE_20 - set(markup.UNSOURCED_MODULES)
    assert not lost, (
        "модули выпали из разметки и вернулись в composite молча: %r"
        % (sorted(lost),))


def test_every_new_entry_names_what_is_missing(markup):
    """Отказ без поимённого списка неисполним — чинить нечего."""
    for name in sorted(set(markup.UNSOURCED_MODULES) - _BASELINE_20):
        d = markup.UNSOURCED_DETAIL[name]
        assert d["missing_keys"], f"{name}: пометка без списка недостающего"
        assert 0.0 <= d["coverage"] < markup.MIN_COVERAGE, (
            f"{name}: покрытие {d['coverage']} не ниже порога — "
            "модуль не должен был попасть в разметку")
