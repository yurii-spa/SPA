"""Храповик: docs/allocation_logic_explicit.md против живого кода.

# LLM_FORBIDDEN

Документ, разъехавшийся с кодом, ХУЖЕ отсутствия документа: он врёт с видом
источника правды, и Allocation Auditor (AI1-1.1) будет судить книгу по числам,
которых в системе нет.

Тест читает числа из ``RiskConfig`` / ``TriggerParams`` / ``kill_switch`` /
``cost_model`` и требует, чтобы ровно они стояли в таблицах документа. Изменил
порог в коде и не обновил документ (или наоборот) — тест краснеет.

Положительный контроль (``test_ratchet_reddens_on_a_changed_number``): подмена
одного числа в КОПИИ документа обязана красить проверку — иначе парсер молча
ничего не находит и храповик становится украшением.

Времени в тесте нет: сравниваются только числа, дат нет ⇒ FROZEN-DATE неприменим.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from spa_core.allocator import allocator as alloc_mod
from spa_core.allocator.rebalance_economics import TriggerParams
from spa_core.governance import kill_switch as ks
from spa_core.risk.policy import RiskConfig

DOC = Path(__file__).resolve().parents[2] / "docs" / "allocation_logic_explicit.md"

_C = RiskConfig()
_T = TriggerParams()

# ── Ожидания: ID правила → числа, которые ОБЯЗАНЫ стоять в его строке ─────────
# Числа вычисляются ИЗ КОДА, не переписываются руками — иначе тест сторожит
# собственную копию, а не систему (урок «тест, сверяющий КОПИИ, слеп»).
EXPECTED: dict[str, tuple[float, ...]] = {
    # Слой A — допуск
    "ADM-02": (alloc_mod._EVIDENCE_MAX_AGE_H,),
    "ADM-03": (alloc_mod._LIVE_APY_MIN_DECIMAL * 100, alloc_mod._LIVE_APY_MAX_DECIMAL * 100),
    "ADM-04": (alloc_mod._EVIDENCE_MIN_COVERAGE,),
    "ADM-07": (_C.min_tvl_usd,),
    "ADM-08": (alloc_mod._REGISTRY_FALLBACK_TVL_USD,),
    # Слой B — потолки
    "CAP-01": (_C.max_concentration_t1 * 100,),
    "CAP-02": (_C.max_concentration_t2 * 100,),
    "CAP-03": (_C.max_single_protocol * 100,),
    "CAP-04": (_C.max_total_t2_allocation * 100,),
    "CAP-05": (_C.max_total_t3_allocation * 100,),
    "CAP-06": (_C.max_protocols,),
    "CAP-08": (_C.min_cash_pct * 100,),
    "CAP-09": (_C.max_apy_for_new_position,),
    "CAP-10": (_C.min_apy_for_new_position,),
    "CAP-11": (_C.min_tvl_usd / 1_000_000,),   # записан как «$5M»
    "CAP-13": (_C.max_single_chain_allocation * 100,),
    "CAP-14": (_C.max_l2_total_allocation * 100,),
    "CAP-15": (_C.BASE_CHAIN_CAP * 100,),
    "CAP-17": (_C.var_confidence * 100, _C.var_horizon_days, _C.max_var_pct * 100),
    "CAP-18": (_C.max_single_position_drawdown * 100,),
    # Слой C — ручки построения
    "BLD-03": (alloc_mod._LIVE_APY_CACHE_TTL,),
    # Слой D — экономика хода (колонка paper = то, что в коде)
    "ECON-01": (_T.min_gain_pp,),
    "ECON-02": (_T.max_payback_days,),
    "ECON-03": (_T.min_hold_days,),
    "ECON-04": (_T.act_cooldown_days,),
    "ECON-05": (_T.max_turnover_per_move * 100,),
    "ECON-06": (_T.max_turnover_per_week * 100,),
    "ECON-07": (_T.min_leg_frac * 100,),
    "ECON-08": (_T.reversal_window_days,),
    "ECON-09": (_T.reversal_escalation,),
    "ECON-10": (_T.below_median_cap_factor,),
    # Слой E — просадка
    "DD-02": (ks.SOFT_DERISK_THRESHOLD_PCT, ks.DRAWDOWN_THRESHOLD_PCT),
    "DD-03": (ks.DRAWDOWN_THRESHOLD_PCT,),
}

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _doc_text() -> str:
    assert DOC.exists(), f"нет документа {DOC} — храповику нечего сторожить"
    return DOC.read_text(encoding="utf-8")


def _value_cell(text: str, rule_id: str) -> str:
    """Ячейка со ЗНАЧЕНИЕМ (третья) в строке таблицы правила ``rule_id``."""
    for line in text.splitlines():
        if line.lstrip().startswith(f"| **{rule_id}**"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert len(cells) >= 3, f"{rule_id}: в строке меньше трёх ячеек: {line!r}"
            return cells[2]
    raise AssertionError(f"строка правила {rule_id} не найдена в {DOC.name}")


def _numbers(cell: str) -> list[float]:
    # «$5 000 000» / «50 000 000» — пробелы внутри числа снимаем, иначе распадётся
    normalised = re.sub(r"(?<=\d)[  ](?=\d)", "", cell)
    return [float(m.group(0).replace(",", ".")) for m in _NUM_RE.finditer(normalised)]


@pytest.mark.parametrize("rule_id", sorted(EXPECTED))
def test_doc_number_matches_code(rule_id: str) -> None:
    expected = EXPECTED[rule_id]
    found = _numbers(_value_cell(_doc_text(), rule_id))
    assert found[: len(expected)] == pytest.approx(list(expected)), (
        f"{rule_id}: документ говорит {found[: len(expected)]}, код — {list(expected)}. "
        "Либо порог изменили без обновления документа, либо документ переписали "
        "мимо кода. Молча выравнивать документ по коду НЕЛЬЗЯ, если менялся код: "
        "это изменение политики (ADR + одобрение владельца)."
    )


def test_every_rule_row_was_actually_found() -> None:
    """Защита от вакуумного прохода: парсер обязан найти КАЖДУЮ строку."""
    text = _doc_text()
    for rule_id in EXPECTED:
        assert _numbers(_value_cell(text, rule_id)), f"{rule_id}: в ячейке нет чисел"
    assert len(EXPECTED) >= 30, "храповик сузили — правил меньше, чем было"


def test_risk_policy_version_is_pinned() -> None:
    """v1.0 держится весь paper-период (инвариант 1)."""
    assert _C.version == "v1.0"
    assert "**v1.0**" in _doc_text()


def test_cost_model_numbers_match_the_doc() -> None:
    """§4.2 — стоимость хода: три числа, которые прямо решают ACT/HOLD."""
    from spa_core.backtesting.tier1.cost_model import (
        BRIDGE_BPS,
        GAS_USD_PER_POSITION_CHANGE,
        SLIPPAGE_BPS_STABLE,
    )
    text = _doc_text()
    assert f"${GAS_USD_PER_POSITION_CHANGE['ethereum']:.2f}" in text
    assert f"${GAS_USD_PER_POSITION_CHANGE['base']:.2f}" in text
    assert f"${GAS_USD_PER_POSITION_CHANGE['blended']:.2f}" in text
    assert f"{SLIPPAGE_BPS_STABLE:.0f} бп" in text
    assert f"{BRIDGE_BPS:.0f} бп" in text


def test_concentration_warning_band_still_lives_in_policy() -> None:
    """CAP-07 (0.85 × cap) — литерал в policy.py, поля под него нет."""
    src = (Path(__file__).resolve().parents[1] / "risk" / "policy.py").read_text(encoding="utf-8")
    assert "max_conc * 0.85" in src, "полоса предупреждения изменилась — обновить CAP-07"
    assert "0.85" in _value_cell(_doc_text(), "CAP-07")


def test_ratchet_reddens_on_a_changed_number(tmp_path: str) -> None:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: подмена числа обязана ронять проверку.

    Без него храповик может молча ничего не сверять (парсер не нашёл строку,
    ячейка пустая) и вечно зеленеть — ровно тот класс украшений, который правило
    доставки запрещает.
    """
    text = _doc_text()
    cell = _value_cell(text, "CAP-01")
    real = _numbers(cell)[0]
    sabotaged = cell.replace(str(int(real)), str(int(real) + 1), 1)
    assert sabotaged != cell, "саботаж не изменил ячейку — контроль был бы холостым"
    assert _numbers(sabotaged)[0] != pytest.approx(real)
