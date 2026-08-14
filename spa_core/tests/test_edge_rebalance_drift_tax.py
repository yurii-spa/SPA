"""Тесты записей реестра #49 (RDT — налог на дрейф весов) и #50 (NTB — полоса безразличия).

Обе записи держатся не на числе, а на СВОЙСТВАХ счётчика: «настоящий турновер никогда не меньше
того, что выставляет реестр», «равенство наступает ровно при отсутствии дрейфа», «точный
ежедневный возврат не меняет модель ни на знак», «смена пригодности книги торгуется всегда, как бы
широка ни была полоса». Вердикт стоит ровно столько, сколько закреплены эти свойства, поэтому
каждое проверено В ОБЕ СТОРОНЫ: рядом с утверждением стоит фикстура, на которой оно обязано быть
ЛОЖНЫМ. Тест, который прошёл бы и на сломанном модуле, доказательством не считается.

Литеральных дат нет: все фикстуры — синтетические массивы доходностей; два теста, которым нужна
настоящая панель, скипаются при отсутствии её файлов (это ночные артефакты, они в .gitignore и
в CI отсутствуют).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
PANEL_DIR = ROOT / "data" / "aggressive_lab"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


rdt = _load("edge_rebalance_drift_tax")
ecr = _load("edge_capital_recycling")

needs_panel = pytest.mark.skipif(
    not (PANEL_DIR / "susde_spot" / "realized_series.jsonl").exists(),
    reason="панель aggressive_lab — ночной артефакт, в CI её нет",
)


class _Panel:
    """Минимальная панель того же интерфейса, что `dgo.Panel`: books / n / rets."""

    def __init__(self, rets: Dict[str, List[float]]) -> None:
        self.books = sorted(rets)
        self.rets = {b: list(rets[b]) for b in self.books}
        self.axis = [f"d{i}" for i in range(len(next(iter(rets.values()))))]

    @property
    def n(self) -> int:
        return len(self.axis)


def _const(panel: _Panel, w: float) -> Dict[str, List[float]]:
    return {b: [w] * panel.n for b in panel.books}


# ═════════════════════ #49: механика дрейфа ═════════════════════
def test_drift_preserves_total_including_cash():
    """Дрейф не создаёт и не уничтожает капитал: Σ книг + кэш = 1 после любого дня."""
    w = {"a": 0.3, "b": 0.2}                      # 50 % кэша
    v = rdt.drifted_weights(w, {"a": 0.10, "b": -0.05})
    cash_before = 1.0 - sum(w.values())
    gross = sum(w[b] * (1.0 + r) for b, r in (("a", 0.10), ("b", -0.05))) + cash_before
    cash_after = cash_before / gross
    assert sum(v.values()) + cash_after == pytest.approx(1.0, abs=1e-12)


def test_drift_moves_weight_toward_the_winner():
    """Положительный контроль направления: выигравшая книга ТЯЖЕЛЕЕТ, проигравшая легчает."""
    v = rdt.drifted_weights({"a": 0.5, "b": 0.5}, {"a": 0.20, "b": -0.20})
    assert v["a"] > 0.5 > v["b"]


def test_drift_is_identity_when_returns_are_equal():
    """И обратная сторона: при равной доходности дрейфа НЕТ — веса не двигаются."""
    v = rdt.drifted_weights({"a": 0.4, "b": 0.6}, {"a": 0.07, "b": 0.07})
    assert v["a"] == pytest.approx(0.4, abs=1e-12)
    assert v["b"] == pytest.approx(0.6, abs=1e-12)


def test_drift_refuses_a_wiped_out_portfolio():
    """Обнулившийся портфель — не состояние, а сломанная панель: отказ, а не выдуманные веса."""
    with pytest.raises(ValueError):
        rdt.drifted_weights({"a": 1.0}, {"a": -1.0})


def test_cash_grows_at_its_own_rate_and_does_not_leak_into_books():
    """Кэш под ненулевую ставку РАЗБАВЛЯЕТ книги, а не подмешивается к ним пропорционально."""
    flat = rdt.drifted_weights({"a": 0.5}, {"a": 0.0}, cash_annual=0.0)
    paid = rdt.drifted_weights({"a": 0.5}, {"a": 0.0}, cash_annual=3.65)   # +1 %/день на кэш
    assert flat["a"] == pytest.approx(0.5, abs=1e-12)
    assert paid["a"] < 0.5


# ═════════════════════ #49: два счёта и неравенство между ними ═════════════════════
def test_target_turnover_reproduces_the_registry_bill_exactly():
    """`target_turnover` — это ровно та формула, по которой реестр считает счёт сегодня."""
    panel = _Panel({"a": [0.01, -0.02, 0.03, 0.0], "b": [-0.01, 0.02, 0.0, 0.01]})
    w = {"a": [0.5, 0.4, 0.6, 0.5], "b": [0.5, 0.6, 0.4, 0.5]}
    metrics = ecr.portfolio_metrics(panel, w)
    assert rdt.target_turnover(panel, w) == pytest.approx(metrics["turnover_yr"], rel=1e-12)


def test_implementation_turnover_is_never_below_the_registry_bill():
    """Центральное неравенство идеи #49 — на панели с разбросом оно СТРОГОЕ."""
    panel = _Panel({"a": [0.05, -0.04, 0.06], "b": [-0.05, 0.04, -0.06]})
    w = _const(panel, 0.5)
    assert rdt.implementation_turnover(panel, w) > rdt.target_turnover(panel, w)


def test_constant_weights_are_billed_zero_by_the_registry_and_are_not_free():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ всей записи #49: постоянная цель = счёт 0, а сделки есть.

    Это и есть дыра, которую запись называет: ни одна строка реестра с постоянными весами
    (`raw`, решающий контроль `static-matched`) не бесплатна, хотя оплачена как бесплатная.
    """
    panel = _Panel({"a": [0.05, -0.04, 0.06], "b": [-0.05, 0.04, -0.06]})
    w = _const(panel, 0.5)
    assert rdt.target_turnover(panel, w) == pytest.approx(0.0, abs=1e-12)
    assert rdt.implementation_turnover(panel, w) > 0.0


def test_the_two_bills_coincide_exactly_when_there_is_no_drift():
    """Обратная сторона того же: нет дрейфа — нет и разницы между счетами."""
    panel = _Panel({"a": [0.01, 0.02, -0.01], "b": [0.01, 0.02, -0.01]})   # книги идентичны
    w = {"a": [0.5, 0.3, 0.5], "b": [0.5, 0.7, 0.5]}
    assert rdt.implementation_turnover(panel, w) == pytest.approx(
        rdt.target_turnover(panel, w), rel=1e-12)


def test_zero_return_panel_has_no_tax():
    """Ещё одна сторона: доходности нулевые ⇒ дрейфа нет ⇒ налог ровно ноль."""
    panel = _Panel({"a": [0.0] * 5, "b": [0.0] * 5})
    w = _const(panel, 0.5)
    assert rdt.implementation_turnover(panel, w) == pytest.approx(0.0, abs=1e-12)


def test_attribution_shares_sum_to_one_and_name_the_volatile_book():
    """Налог платит не «портфель вообще»: доли суммируются в 1 и указывают на шумную книгу."""
    panel = _Panel({"quiet": [0.0005] * 40,
                    "wild": [0.08 if i % 2 else -0.08 for i in range(40)]})
    shares = rdt.turnover_attribution(panel, _const(panel, 0.5))
    assert sum(shares.values()) == pytest.approx(1.0, rel=1e-12)
    assert shares["wild"] > shares["quiet"]


def test_attribution_is_all_zeros_when_nothing_drifts():
    """И не выдумывает долей там, где турновера нет."""
    panel = _Panel({"a": [0.0] * 4, "b": [0.0] * 4})
    assert rdt.turnover_attribution(panel, _const(panel, 0.5)) == {"a": 0.0, "b": 0.0}


# ═════════════════════ #50: движок возврата к цели ═════════════════════
def test_exact_daily_run_reproduces_the_registry_return_path_to_the_last_digit():
    """Движок #50 не меняет модель реестра — он только выставляет ей счёт.

    Если это равенство когда-нибудь разойдётся, все числа записи #50 сравнивают РАЗНЫЕ
    портфели, а не разные политики ребаланса, — поэтому оно закреплено первым.
    """
    panel = _Panel({"a": [0.01, -0.02, 0.03, 0.005], "b": [-0.01, 0.02, 0.0, 0.01]})
    w = {"a": [0.5, 0.4, 0.6, 0.5], "b": [0.5, 0.6, 0.4, 0.5]}
    run = rdt.rebalance_run(panel, w)
    metrics = ecr.portfolio_metrics(panel, w)
    assert run["apy"] == pytest.approx(metrics["apy"], rel=1e-12)
    assert run["maxdd"] == pytest.approx(metrics["maxdd"], rel=1e-12)


def test_exact_daily_run_is_billed_the_implementation_turnover_not_the_target_one():
    """А счёт при точном ежедневном возврате — уже настоящий, а не счёт реестра."""
    panel = _Panel({"a": [0.05, -0.04, 0.06], "b": [-0.05, 0.04, -0.06]})
    w = _const(panel, 0.5)
    run = rdt.rebalance_run(panel, w)
    assert run["turnover_yr"] == pytest.approx(rdt.implementation_turnover(panel, w), rel=1e-12)
    assert run["turnover_yr"] > rdt.target_turnover(panel, w)


def test_zero_band_is_the_same_policy_as_exact_daily():
    """Полоса нулевой ширины — это и есть ежедневный возврат (граница определена, не случайна)."""
    panel = _Panel({"a": [0.03, -0.02, 0.04], "b": [-0.03, 0.02, -0.04]})
    w = _const(panel, 0.5)
    assert rdt.rebalance_run(panel, w, band=0.0)["turnover_yr"] == pytest.approx(
        rdt.rebalance_run(panel, w)["turnover_yr"], rel=1e-12)


def test_a_wide_band_trades_less_than_a_narrow_one():
    """Смысл полосы: шире ⇒ реже. Без этого вся таблица #50 — про что-то другое."""
    panel = _Panel({"a": [0.03, -0.02, 0.04, 0.01], "b": [-0.03, 0.02, -0.04, -0.01]})
    w = _const(panel, 0.5)
    wide = rdt.rebalance_run(panel, w, band=0.50)
    narrow = rdt.rebalance_run(panel, w, band=0.001)
    assert wide["rebalance_days"] < narrow["rebalance_days"]
    assert wide["turnover_yr"] < narrow["turnover_yr"]


def test_eligibility_flip_always_trades_however_wide_the_band():
    """ФЕЙЛ-КЛОУЗД записи #50: демоушен — решение о риске, полосой он не экономится.

    Полоса шире единицы не может быть превышена НИКАКИМ отклонением, поэтому единственная
    причина, по которой сделка тут вообще происходит, — смена пригодности книги.
    """
    panel = _Panel({"a": [0.01, 0.01, 0.01, 0.01], "b": [0.01, 0.01, 0.01, 0.01]})
    w = {"a": [0.5, 0.0, 0.0, 0.5], "b": [0.5, 1.0, 1.0, 0.5]}
    run = rdt.rebalance_run(panel, w, band=10.0)
    assert run["rebalance_days"] == 2.0        # выключение книги и её возврат


def test_a_wide_band_does_NOT_trade_when_only_the_size_changes():
    """Обратная сторона предыдущего: без смены пригодности широкая полоса молчит.

    Пара этих двух тестов и есть граница «риск торгуем всегда / размер — по полосе»; по
    отдельности ни один из них её не задаёт.
    """
    panel = _Panel({"a": [0.01, 0.01, 0.01, 0.01], "b": [0.01, 0.01, 0.01, 0.01]})
    w = {"a": [0.5, 0.4, 0.6, 0.5], "b": [0.5, 0.6, 0.4, 0.5]}
    assert rdt.rebalance_run(panel, w, band=10.0)["rebalance_days"] == 0.0


def test_full_schedule_equals_exact_daily():
    """Контроль равной частоты определён так, что при ВСЕХ днях он совпадает с ежедневным."""
    panel = _Panel({"a": [0.02, -0.03, 0.01], "b": [-0.02, 0.03, -0.01]})
    w = _const(panel, 0.5)
    every = rdt.rebalance_run(panel, w, schedule=set(range(panel.n)))
    assert every["turnover_yr"] == pytest.approx(rdt.rebalance_run(panel, w)["turnover_yr"],
                                                 rel=1e-12)


def test_empty_schedule_still_honours_eligibility_flips():
    """Пустое расписание — не «никогда не торгуем»: риск-сделки остаются обязательными."""
    panel = _Panel({"a": [0.01] * 3, "b": [0.01] * 3})
    w = {"a": [0.5, 0.0, 0.5], "b": [0.5, 1.0, 0.5]}
    assert rdt.rebalance_run(panel, w, schedule=set())["rebalance_days"] == 2.0


def test_negative_band_is_refused():
    with pytest.raises(ValueError):
        rdt.rebalance_run(_Panel({"a": [0.0, 0.0]}), {"a": [1.0, 1.0]}, band=-0.01)


def test_random_schedules_are_deterministic_and_of_the_requested_size():
    """Контроль обязан быть воспроизводимым, иначе его p-значение ничего не значит."""
    first = rdt.random_schedules(100, 7, seeds=5)
    assert first == rdt.random_schedules(100, 7, seeds=5)
    assert all(len(s) == 7 for s in first)
    assert len({tuple(sorted(s)) for s in first}) > 1        # разные seeds — разные расписания


def test_random_schedules_cannot_ask_for_more_days_than_exist():
    assert all(len(s) == 4 for s in rdt.random_schedules(4, 999, seeds=3))
    with pytest.raises(ValueError):
        rdt.random_schedules(10, -1)


# ═════════════════════ настоящая панель: то, на чём стоят вердикты ═════════════════════
@needs_panel
def test_real_panel_raw_pays_an_unbilled_tax():
    """Вердикт #49 на реальной панели: `raw` — база сравнения всего реестра — платит НЕ ноль."""
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    w = {b: [1.0 / len(panel.books)] * panel.n for b in panel.books}
    assert rdt.target_turnover(panel, w) == pytest.approx(0.0, abs=1e-12)
    tax_bp = 0.5 * rdt.COST_BP_ROUND_TRIP * rdt.implementation_turnover(panel, w)
    assert 50.0 < tax_bp < 150.0        # замерено 86.3 bp/год; границы широкие намеренно


@needs_panel
def test_real_panel_tax_does_not_overturn_the_ranking():
    """Вердикт #49 «ни один вердикт реестра не перевёрнут» — проверяемое утверждение, не мнение."""
    dgo = _load("edge_drift_gated_overlay")
    panel = dgo.Panel()
    order_registry, order_true = [], []
    for name, w in rdt.rule_weights(panel):
        apy = ecr.portfolio_metrics(panel, w)["apy"]
        order_registry.append((apy - 0.5 * rdt.COST_BP_ROUND_TRIP
                               * rdt.target_turnover(panel, w) / rdt.BP, name))
        order_true.append((apy - 0.5 * rdt.COST_BP_ROUND_TRIP
                           * rdt.implementation_turnover(panel, w) / rdt.BP, name))
    assert [n for _, n in sorted(order_registry, reverse=True)] == \
           [n for _, n in sorted(order_true, reverse=True)]
