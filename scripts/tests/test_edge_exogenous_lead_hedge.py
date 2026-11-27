"""
#169 XLT + #170 CACH-REAL — pinned tests for `scripts/edge_exogenous_lead_hedge.py`.

Every test is a POSITIVE CONTROL on a synthetic world: plant the property and check the
instrument sees it, plant the violation and check it does NOT.  The real panel
(`data/aggressive_lab/`) and the real series (`data/rates_desk/`) are never read and never
written — every scene builds its own files under `tmp_path`.

The control that matters most for #169 is `test_a_PLANTED_exogenous_lead_IS_found`: the
registry verdict of #169 is NEGATIVE, and a negative verdict from a blind instrument is worth
nothing.  That test plants a deterministic 90-day lead and requires the same decision rule
that produced the negative verdict to answer "signal", loudly.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: literal ISO dates are synthetic axis labels; they are compared only to the
# TRAIN/TEST split constant and to each other, never to the wall clock.
from __future__ import annotations

import datetime
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"_t_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_t_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


x = _load("edge_exogenous_lead_hedge")

AXIS_START = datetime.date(2024, 1, 1)


def _axis(n: int) -> List[str]:
    return [(AXIS_START + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _write_panel(root: Path, books: Mapping[str, Sequence[float]], axis: Sequence[str]) -> Path:
    """Write a synthetic panel in the Lane-1 schema: one jsonl per book, phase='backtest'."""
    root.mkdir(parents=True, exist_ok=True)
    for book, rets in books.items():
        d = root / book
        d.mkdir(exist_ok=True)
        eq = 100000.0
        rows = [{"date": axis[0], "as_of": axis[0], "equity_usd": eq, "phase": "backtest"}]
        for i in range(1, len(axis)):
            eq *= (1.0 + rets[i])
            rows.append({"date": axis[i], "as_of": axis[i], "equity_usd": eq,
                         "phase": "backtest"})
        (d / "realized_series.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n")
    return root


def _write_rates(root: Path, axis: Sequence[str], prices: Sequence[float],
                 funding: Optional[Sequence[float]] = None,
                 reth: Optional[Sequence[float]] = None,
                 eeth: Optional[Sequence[float]] = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    series: dict = {"eth": {d: float(p) for d, p in zip(axis, prices)}}
    if eeth is not None:
        series["eeth"] = {d: float(p) for d, p in zip(axis, eeth)}
    (root / "prices_deep.json").write_text(json.dumps({"series": series}))
    f = funding if funding is not None else [0.00005] * len(axis)
    (root / "funding_deep.json").write_text(
        json.dumps({"series": {d: float(v) for d, v in zip(axis, f)}}))
    r = reth if reth is not None else [0.03] * len(axis)
    (root / "restaking_deep.json").write_text(
        json.dumps({"series": {"reth": {d: float(v) for d, v in zip(axis, r)}}}))
    return root


# ── объявленные свойства самого прибора ─────────────────────────────────────────────────────

def test_flags_are_advisory():
    assert x.IS_ADVISORY is True and x.OUTSIDE_RISKPOLICY is True


def test_toll_and_split_are_inherited_not_redeclared():
    """Пошлина и шов берутся из общего загрузчика — своей копии у прибора нет (#774-порядок)."""
    rpe = _load("edge_real_panel_ensemble")
    assert x.TOLL == rpe.PLB_ROUNDTRIP
    assert x.SPLIT == rpe.TRAIN_END
    # `is` здесь был бы дефектом СЦЕНЫ: `_load` создаёт ВТОРОЙ объект модуля по
    # построению, поэтому сверяется ЗНАЧЕНИЕ, а не тождество объекта.
    assert x.WINDOWS == rpe.CRISIS_WINDOWS


# ── align: пропуск ряда — третий исход, а не ноль ───────────────────────────────────────────

def test_align_fills_inside_the_declared_gap_and_refuses_beyond_it():
    axis = _axis(10)
    series = {axis[0]: 100.0, axis[4]: 200.0}
    out = x.align(series, axis, max_gap=2)
    assert out[0] == 100.0
    assert out[1] == 100.0 and out[2] == 100.0      # зазор 1 и 2 дня — протянуто
    assert out[3] is None                            # зазор 3 дня — отказ протягивать
    assert out[4] == 200.0
    assert out[7] is None                            # после 2 дней снова отказ


def test_align_never_substitutes_zero_for_a_missing_observation():
    axis = _axis(5)
    out = x.align({}, axis, max_gap=2)
    assert out == [None] * 5                         # НЕ [0,0,0,0,0] — инв. #17


# ── медленные эпизоды: предмет заказа #168 ──────────────────────────────────────────────────

def test_slow_episode_is_found_when_planted():
    axis = _axis(400)
    # Два отрезка по 80 дней падения, РАЗДЕЛЁННЫЕ восстановлением выше прежнего пика.
    # Восстановление — часть сцены, а не украшение: трейлинг-просадка меряет ВРЕМЯ ПОД ВОДОЙ,
    # поэтому без возврата к пику два провала были бы ОДНИМ открытым эпизодом (это свойство
    # меры, и его проверяет test_time_under_water_without_recovery_is_ONE_episode ниже).
    r = [0.0] * 400
    for i in range(50, 130):
        r[i] = -0.001
    for i in range(130, 230):
        r[i] = +0.0012          # возврат выше пика
    for i in range(250, 330):
        r[i] = -0.001
    eps = x.slow_episodes(r, axis)
    assert len(eps) == 2
    assert all(e["days"] >= x.SLOW_DAYS for e in eps)
    assert all(e["trough"] < x.SLOW_DEPTH for e in eps)


def test_a_SHORT_drawdown_is_NOT_a_slow_episode():
    """Контроль в обратную сторону: быстрый удар той же глубины предметом не является."""
    axis = _axis(400)
    r = [0.0] * 400
    for i in range(50, 60):          # 10 дней удара — короче SLOW_DAYS
        r[i] = -0.008
    for i in range(60, 90):          # и быстрое восстановление выше пика
        r[i] = +0.003
    eps = x.slow_episodes(r, axis)
    assert eps == []


def test_time_under_water_without_recovery_is_ONE_episode():
    """Объявленное свойство меры: предмет — ВРЕМЯ ПОД ВОДОЙ, а не форма падения.

    Короткий удар без возврата к пику ОСТАЁТСЯ медленным эпизодом, и это верно: капитал
    под водой, пока не вернулся пик.  Сцена закрепляет это, чтобы следующая сессия не
    прочитала результат выше как «короткий удар не считается» вообще.
    """
    axis = _axis(400)
    r = [0.0] * 400
    for i in range(50, 60):
        r[i] = -0.008
    eps = x.slow_episodes(r, axis)   # восстановления НЕТ
    assert len(eps) == 1 and eps[0]["days"] > x.SLOW_DAYS


def test_a_SHALLOW_long_dip_is_NOT_a_slow_episode():
    axis = _axis(400)
    r = [0.0] * 400
    for i in range(50, 200):
        r[i] = -0.00001           # 150 дней, но глубина не доходит до SLOW_DEPTH
    assert x.slow_episodes(r, axis) == []


# ── метка не видит своего дня ───────────────────────────────────────────────────────────────

def test_forward_label_does_not_see_its_own_day():
    r = [0.0] * 10
    r[3] = -0.9                       # собственный день — катастрофа
    for i in range(4, 10):
        r[i] = +0.01                  # дни ВПЕРЁД — прибыль
    labels = x.forward_loss_labels(r, 3)
    assert labels[3] is False         # метка дня 3 читает дни 4..6, а не день 3
    assert labels[0] is True          # дни 1..3 содержат −90 %


def test_forward_label_tail_is_unmeasured_not_false():
    labels = x.forward_loss_labels([0.001] * 10, 5)
    assert labels[-1] is None and labels[-5] is None   # хвост оси — None, не False


# ── AUC и семейное плацебо ──────────────────────────────────────────────────────────────────

def test_auc_is_one_on_perfect_separation_and_zero_when_inverted():
    feat = [1.0, 2.0, 3.0, 4.0]
    lab = [False, False, True, True]
    assert x.auc(feat, lab) == 1.0
    assert x.auc([-v for v in feat], lab) == 0.0


def test_auc_is_half_on_a_constant_feature_and_None_without_both_classes():
    assert x.auc([1.0] * 6, [True, True, True, False, False, False]) == 0.5
    assert x.auc([1.0, 2.0, 3.0], [True, True, True]) is None


def test_family_placebo_calls_a_planted_signal_SIGNAL():
    """Положительный контроль РЕШАЮЩЕГО ПРАВИЛА #169 на уровне единицы."""
    n = 300
    lab: List[Optional[bool]] = [(i % 100) < 50 for i in range(n)]
    feats = {"truth": [1.0 if lab[i] else 0.0 for i in range(n)],
             "noise": [float((i * 7) % 13) for i in range(n)]}
    stats, devs = x.family_placebo(feats, lab, draws=200, seed=1)
    real = max(abs(x.auc(feats[k], lab) - 0.5) for k in feats)
    assert real == pytest.approx(0.5)
    assert x.placebo_percentile(devs, real) >= 0.95
    assert stats["p95"] < real          # настоящий максимум ВЫШЕ семейного порога


def test_family_placebo_calls_pure_noise_NOISE():
    """Контроль в обратную сторону: признак без связи с меткой за порог не выходит."""
    n = 300
    lab: List[Optional[bool]] = [(i % 100) < 50 for i in range(n)]
    feats = {"a": [float((i * 37) % 101) for i in range(n)],
             "b": [float((i * 53) % 97) for i in range(n)]}
    _, devs = x.family_placebo(feats, lab, draws=200, seed=2)
    real = max(abs(x.auc(feats[k], lab) - 0.5) for k in feats)
    assert x.placebo_percentile(devs, real) < 0.95


def test_family_placebo_uses_ONE_shift_for_the_whole_family():
    """Один сдвиг на розыгрыш: иначе одиннадцать попыток сами подарят «значимый» признак.

    Сцена различающая: два признака — точная копия метки и её инверсия.  При ОДНОМ сдвиге на
    семейство их отклонения на каждом розыгрыше РАВНЫ по модулю, поэтому максимум семейства
    совпадает с отклонением одного признака; при независимых сдвигах это неверно почти всегда.
    """
    n = 200
    lab: List[Optional[bool]] = [(i % 40) < 20 for i in range(n)]
    truth = [1.0 if lab[i] else 0.0 for i in range(n)]
    feats = {"up": truth, "down": [-v for v in truth]}
    _, devs_family = x.family_placebo(feats, lab, draws=50, seed=3)
    _, devs_single = x.family_placebo({"up": truth}, lab, draws=50, seed=3)
    # поэлементное сравнение с допуском: у зеркальных признаков AUC совпадают до последних
    # битов мантиссы, и точное равенство списков ловило бы арифметику, а не правило
    assert devs_family == [pytest.approx(v) for v in devs_single]


def test_placebo_is_deterministic_for_a_given_seed():
    n = 150
    lab: List[Optional[bool]] = [(i % 30) < 15 for i in range(n)]
    feats = {"a": [float(i % 17) for i in range(n)]}
    first = x.family_placebo(feats, lab, draws=40, seed=7)[1]
    second = x.family_placebo(feats, lab, draws=40, seed=7)[1]
    assert first == second


# ── гейт, его причинность и статический двойник ─────────────────────────────────────────────

def test_causal_flag_reads_yesterday_only():
    values = [1.0, 99.0, 1.0, 1.0]
    flag = x.causal_flag(values, 50.0, above=True)
    assert flag[0] is None            # у первого дня вчера нет — третий исход
    assert flag[1] is False           # день 1 читает значение дня 0 (=1), не своё (=99)
    assert flag[2] is True            # день 2 читает значение дня 1 (=99)


def test_gate_charges_the_toll_only_on_a_state_CHANGE():
    rets = [0.01] * 6
    flag: List[Optional[bool]] = [False, True, True, True, False, False]
    out, changes, share = x.gate_overlay(rets, flag, toll=0.01, safe_daily=0.0)
    assert changes == 2                      # вошли в кэш и вышли — ровно две смены
    assert out[1] == pytest.approx(-0.01)    # день входа: кэш 0 минус пошлина
    assert out[2] == pytest.approx(0.0)      # день в кэше без смены — пошлины НЕТ
    assert out[4] == pytest.approx(0.0)      # день выхода: 0.01 минус пошлина 0.01
    assert share == pytest.approx(3 / 6)


def test_gate_treats_an_unmeasured_feature_as_HOLD_not_as_derisk():
    rets = [0.01] * 5
    flag: List[Optional[bool]] = [None, None, None, None, None]
    out, changes, share = x.gate_overlay(rets, flag, toll=0.01, safe_daily=0.0)
    assert changes == 0 and share == 1.0
    assert out == rets                        # «не измерено» состояние не меняет


def test_static_twin_has_the_same_average_risk_share_and_zero_timing():
    rets = [0.02, -0.03, 0.01, 0.00]
    twin = x.static_twin(rets, 0.5, safe_daily=0.0)
    assert twin == [pytest.approx(0.5 * r) for r in rets]


# ── β и хедж ────────────────────────────────────────────────────────────────────────────────

def test_ols_beta_recovers_a_planted_slope():
    xs = [((i * 13) % 29) / 100.0 - 0.14 for i in range(60)]
    ys = [2.5 * v for v in xs]
    assert x.ols_beta(xs, ys) == pytest.approx(2.5)


def test_ols_beta_refuses_a_degenerate_regressor_instead_of_answering_zero():
    with pytest.raises(x.Unmeasured):
        x.ols_beta([0.01] * 60, [0.02] * 60)
    with pytest.raises(x.Unmeasured):
        x.ols_beta([0.01, 0.02], [0.03, 0.04])      # пар меньше 30


def test_full_hedge_removes_a_planted_beta_exactly():
    eth = [((i * 7) % 23) / 100.0 - 0.11 for i in range(120)]
    panel = [0.0003 + 0.5 * v for v in eth]           # β = 0.5 ровно
    hedged, parts = x.hedged_returns(panel, eth, [0.0] * 120, h=1.0, beta=0.5,
                                     entry_toll=0.0)
    assert parts["notional"] == pytest.approx(0.5)
    assert all(v == pytest.approx(0.0003) for v in hedged)   # бета снята до байта


def test_a_PARTIAL_hedge_leaves_a_proportional_residual():
    eth = [((i * 7) % 23) / 100.0 - 0.11 for i in range(120)]
    panel = [0.5 * v for v in eth]
    hedged, _ = x.hedged_returns(panel, eth, [0.0] * 120, h=0.5, beta=0.5, entry_toll=0.0)
    assert hedged[3] == pytest.approx(0.25 * eth[3])


def test_funding_sign_convention_is_the_declared_one():
    """f > 0 ⇒ короткая нога ПОЛУЧАЕТ: вклад funding положителен."""
    hedged, parts = x.hedged_returns([0.0] * 10, [0.0] * 10, [0.001] * 10,
                                     h=1.0, beta=1.0, entry_toll=0.0)
    assert parts["carry_sum"] == pytest.approx(0.01)
    assert hedged[5] == pytest.approx(0.001)


def test_a_missing_funding_day_is_COUNTED_not_silently_zero():
    fund: List[Optional[float]] = [0.001, None, 0.001]
    _, parts = x.hedged_returns([0.0] * 3, [0.0] * 3, fund, h=1.0, beta=1.0, entry_toll=0.0)
    assert parts["funding_unmeasured_days"] == 1.0        # различимо от «funding был 0»
    assert parts["carry_sum"] == pytest.approx(0.002)


def test_entry_toll_is_charged_once_and_scaled_by_the_hedge_notional():
    hedged, _ = x.hedged_returns([0.0] * 5, [0.0] * 5, [0.0] * 5, h=1.0, beta=0.25,
                                 entry_toll=0.01)
    assert hedged[0] == pytest.approx(-0.01 * 0.25)
    assert all(v == pytest.approx(0.0) for v in hedged[1:])


def test_no_hedge_pays_no_toll_and_changes_nothing():
    panel = [0.01, -0.02, 0.03]
    hedged, parts = x.hedged_returns(panel, [0.05] * 3, [0.001] * 3, h=0.0, beta=0.9,
                                     entry_toll=0.01)
    assert hedged == [pytest.approx(v) for v in panel]
    assert parts["direction_sum"] == 0.0 and parts["carry_sum"] == 0.0


def test_maintenance_cost_is_proportional_to_notional_and_to_the_year_rate():
    _, p0 = x.hedged_returns([0.0] * 2, [0.0] * 2, [0.0] * 2, h=1.0, beta=0.1,
                             maint_bps_year=100.0, entry_toll=0.0)
    assert p0["maint_year_pct"] == pytest.approx(0.1 * 1.0)   # 100 bp × 0.1 = 0.1 %/год


def test_basis_noise_is_SCALED_BY_THE_HEDGE_NOTIONAL():
    """Различающая сцена (мутация «шум не масштабируется номиналом» выжила без неё).

    Остаточный базис бьёт по ХЕДЖУ, а не по всему капиталу: при номинале 0.1 тот же σ обязан
    испортить просадку примерно в десять раз слабее, чем при номинале 1.0.  Прежняя сцена
    звала прибор ровно с notional=1.0 — на ней мутация была ТОЖДЕСТВЕННА коду и выживала
    не потому, что код верен, а потому, что её никто не отличал.
    """
    hedged = [0.001, -0.002, 0.0015, -0.003, 0.002] * 20
    panel = [v * 3 for v in hedged]
    clean = _load("edge_real_panel_ensemble").perf(hedged)["maxdd"]
    big = x.basis_breakeven(panel, hedged, notional=1.0, sigmas=(0.02,), draws=40)[0]
    small = x.basis_breakeven(panel, hedged, notional=0.1, sigmas=(0.02,), draws=40)[0]
    hurt_big = abs(big["median_maxdd"] - clean)
    hurt_small = abs(small["median_maxdd"] - clean)
    assert hurt_big > 4.0 * hurt_small, (
        f"номинал не масштабирует базис: вред {hurt_big:.5f} против {hurt_small:.5f}")


def test_basis_breakeven_is_monotone_in_sigma_and_exact_at_zero():
    hedged = [0.001, -0.002, 0.0015, -0.003, 0.002] * 20
    panel = [v * 3 for v in hedged]
    rows = x.basis_breakeven(panel, hedged, notional=1.0,
                             sigmas=(0.0, 0.01, 0.05), draws=20)
    assert rows[0]["median_maxdd"] == pytest.approx(
        _load("edge_real_panel_ensemble").perf(hedged)["maxdd"])
    assert rows[2]["median_maxdd"] <= rows[1]["median_maxdd"] <= rows[0]["median_maxdd"]


# ── третий исход (инв. #17) ─────────────────────────────────────────────────────────────────

def test_missing_rates_file_is_a_named_refusal(tmp_path):
    with pytest.raises(x.Unmeasured) as e:
        x.load_series(tmp_path / "nowhere")
    assert "файла нет" in str(e.value)


def test_too_short_price_series_is_a_named_refusal(tmp_path):
    axis = _axis(50)
    rates = _write_rates(tmp_path / "rates", axis, [100.0] * 50)
    with pytest.raises(x.Unmeasured) as e:
        x.load_series(rates)
    assert "слишком короток" in str(e.value)


def test_unparseable_file_is_a_refusal_not_an_empty_series(tmp_path):
    d = tmp_path / "rates"
    d.mkdir()
    (d / "prices_deep.json").write_text("{not json")
    with pytest.raises(x.Unmeasured):
        x.load_series(d)


def test_too_few_slow_episodes_refuses_instead_of_reporting_no_edge(tmp_path):
    n = 300
    axis = _axis(n)
    flat = {f"b{k}": [0.0002] * n for k in range(3)}
    panel = _write_panel(tmp_path / "panel", flat, axis)
    rates = _write_rates(tmp_path / "rates", axis, [100.0 + i * 0.1 for i in range(n)])
    rpe = _load("edge_real_panel_ensemble")
    ax, rets, books = rpe.plb_load(panel)
    with pytest.raises(x.Unmeasured) as e:
        x.section_lead(ax, rets, books, x.load_series(rates))
    assert "медленных эпизодов" in str(e.value)


def test_short_paired_axis_refuses_in_the_hedge_section(tmp_path):
    n = 320
    axis = _axis(n)
    panel = _write_panel(tmp_path / "panel", {f"b{k}": [0.0002] * n for k in range(3)}, axis)
    # цена есть только на 250 днях из 320 ⇒ ось пар короче MIN_PAIRED_DAYS
    prices = [100.0 + i * 0.05 for i in range(n)]
    rates = tmp_path / "rates"
    rates.mkdir()
    (rates / "prices_deep.json").write_text(json.dumps({"series": {"eth": {
        d: p for d, p in list(zip(axis, prices))[:250]}}}))
    (rates / "funding_deep.json").write_text(json.dumps({"series": {}}))
    (rates / "restaking_deep.json").write_text(json.dumps({"series": {}}))
    rpe = _load("edge_real_panel_ensemble")
    ax, rets, books = rpe.plb_load(panel)
    with pytest.raises(x.Unmeasured) as e:
        x.section_hedge(ax, rets, books, x.load_series(rates))
    assert "пересечение" in str(e.value)


# ── СКВОЗНОЙ положительный контроль: посаженное опережение НАХОДИТСЯ ────────────────────────

def _cyclic_prices(n: int, period: int, amp: float = 0.35) -> List[float]:
    return [100.0 * (1.0 + amp * math.sin(2 * math.pi * i / period)) for i in range(n)]


def test_a_PLANTED_exogenous_lead_IS_found(tmp_path):
    """Вердикт #169 отрицателен — этот контроль показывает, что прибор НЕ слеп.

    Сцена: цена ETH ходит циклом, а доходность панели дня t ДЕТЕРМИНИРОВАННО определяется
    знаком 90-дневного момента ЗА ДЕНЬ ДО t.  Связь реальна и причинна ⇒ решающее правило
    #169 (максимум |AUC−0.5| против семейного плацебо) обязано сказать «сигнал».
    """
    n = 700
    axis = _axis(n)
    prices = _cyclic_prices(n, period=260)
    mom: List[Optional[float]] = [None] * n
    for i in range(n):
        if i >= 90:
            mom[i] = prices[i] / prices[i - 90] - 1.0
    rets = [0.0] * n
    for i in range(1, n):
        prev = mom[i - 1]
        rets[i] = 0.0015 if (prev is None or prev > 0) else -0.0015
    books = {f"b{k}": rets for k in range(3)}
    panel = _write_panel(tmp_path / "panel", books, axis)
    rates = _write_rates(tmp_path / "rates", axis, prices)
    rpe = _load("edge_real_panel_ensemble")
    ax, loaded, names = rpe.plb_load(panel)
    out = x.section_lead(ax, loaded, names, x.load_series(rates))
    blk = out["per_h"][60]
    assert blk["real_percentile"] >= 0.95, (
        f"посаженное опережение не найдено: перцентиль {blk['real_percentile']}")
    assert abs(blk["best_auc_full"] - 0.5) > blk["placebo"]["p95"]
    assert blk["best_feature"].startswith("eth_")


def test_the_same_scene_with_the_LINK_CUT_is_called_noise(tmp_path):
    """Контроль в обратную сторону: та же панель, но ряд цен не имеет к ней отношения.

    Доходности берутся из прежней сцены (эпизоды те же), а цена заменена монотонным рядом,
    из которого ни один признак про них ничего не знает.  Решающее правило обязано остаться
    внутри семейного плацебо.
    """
    n = 700
    axis = _axis(n)
    prices = _cyclic_prices(n, period=260)
    mom: List[Optional[float]] = [None] * n
    for i in range(n):
        if i >= 90:
            mom[i] = prices[i] / prices[i - 90] - 1.0
    rets = [0.0] * n
    for i in range(1, n):
        prev = mom[i - 1]
        rets[i] = 0.0015 if (prev is None or prev > 0) else -0.0015
    panel = _write_panel(tmp_path / "panel", {f"b{k}": rets for k in range(3)}, axis)
    unrelated = [100.0 * (1.0 + 0.0002 * i) for i in range(n)]      # связи с панелью нет
    rates = _write_rates(tmp_path / "rates", axis, unrelated)
    rpe = _load("edge_real_panel_ensemble")
    ax, loaded, names = rpe.plb_load(panel)
    out = x.section_lead(ax, loaded, names, x.load_series(rates))
    blk = out["per_h"][60]
    assert abs(blk["best_auc_full"] - 0.5) <= blk["placebo"]["max"], (
        "разорванная связь объявлена сигналом — правило красит шум")


def test_the_hedge_section_runs_end_to_end_and_reports_both_parts(tmp_path):
    n = 700          # ось обязана лежать по обе стороны шва — иначе прибор ОТКАЗЫВАЕТ
    axis = _axis(n)
    prices = _cyclic_prices(n, period=180)
    eth_r = [0.0] + [prices[i] / prices[i - 1] - 1.0 for i in range(1, n)]
    books = {"beta_book": [0.0002 + v for v in eth_r],
             "carry_a": [0.0004] * n,
             "carry_b": [0.0003 + 0.00001 * (i % 7) for i in range(n)]}
    panel = _write_panel(tmp_path / "panel", books, axis)
    rates = _write_rates(tmp_path / "rates", axis, prices)
    rpe = _load("edge_real_panel_ensemble")
    ax, loaded, names = rpe.plb_load(panel)
    out = x.section_hedge(ax, loaded, names, x.load_series(rates))
    # β книги с посаженной единичной бетой найдена, у carry-книг она около нуля
    assert out["per_book"]["beta_book"] == pytest.approx(1.0, abs=0.05)
    assert abs(out["per_book"]["carry_a"]) < 0.05
    assert out["beta_book"] == "beta_book"
    assert out["excision"]["book"] == "beta_book"
    # разложение печатается по частям и каждая часть измерена
    full = [a for a in out["arms"] if a["h"] == 1.0 and a["maint_bps"] == 0][0]
    assert full["parts"]["notional"] == pytest.approx(out["beta_train"])
    assert "direction_sum" in full["parts"] and "carry_sum" in full["parts"]
    # хедж обязан снять дисперсию портфеля на этой сцене (бета посажена)
    assert abs(full["FULL"]["vol"]) < abs(
        [a for a in out["arms"] if a["h"] == 0.0 and a["maint_bps"] == 0][0]["FULL"]["vol"])


def test_opportunity_threshold_is_the_alternative_use_minus_the_funding(tmp_path):
    """§6: порог окупаемости хеджа = доходность АЛЬТЕРНАТИВЫ минус полученный funding.

    Сцена различающая: carry-книги зарабатывают заметно больше, чем остаток хеджируемой
    книги, поэтому порог обязан оказаться ВЫШЕ остатка — то есть прибор обязан сказать
    «изъятие лучше хеджа» на сцене, где это верно по построению.
    """
    n = 700
    axis = _axis(n)
    prices = _cyclic_prices(n, period=180)
    eth_r = [0.0] + [prices[i] / prices[i - 1] - 1.0 for i in range(1, n)]
    books = {"beta_book": [0.00001 + v for v in eth_r],   # остаток почти нулевой
             "carry_a": [0.0005] * n,                     # альтернатива заметно богаче
             "carry_b": [0.0005] * n}
    panel = _write_panel(tmp_path / "panel", books, axis)
    rates = _write_rates(tmp_path / "rates", axis, prices)
    rpe = _load("edge_real_panel_ensemble")
    ax, loaded, names = rpe.plb_load(panel)
    out = x.section_hedge(ax, loaded, names, x.load_series(rates))
    # Величина funding в пороге сверяется с НЕЗАВИСИМО посчитанной из объявления сцены:
    # funding сцены 5e-5/д, номинал хеджа = β портфеля, доля книги = 1/3.  Прежняя редакция
    # читала это число у прибора и сравнивала его с собой — тавтология, на которой мутация
    # «порог без вычета funding» ВЫЖИЛА (дефект ПРОБЫ, не кода).
    expected_funding_on_slice = (5e-5 * out["beta_train"] * 365.0) / (1 / 3)
    for label in ("TRAIN", "TEST", "FULL"):
        o = out["opportunity"][label]
        assert o["next_best_apy"] == pytest.approx(out["excision"][label]["apy"])
        assert o["funding_apy_on_slice"] == pytest.approx(expected_funding_on_slice, rel=0.02)
        assert o["funding_apy_on_slice"] > 0.0
        need = o["next_best_apy"] - expected_funding_on_slice
        assert o["residual_apy"] is not None
        assert o["residual_apy"] < need, (
            f"{label}: остаток {o['residual_apy']} обязан быть НИЖЕ порога {need}")
    assert out["opportunity"]["FULL"]["weight"] == pytest.approx(1 / 3)


def test_the_instrument_writes_nothing(tmp_path):
    """Прибор read-only: ни один файл сцены не меняется и ни один новый не появляется."""
    n = 700
    axis = _axis(n)
    prices = _cyclic_prices(n, period=180)
    eth_r = [0.0] + [prices[i] / prices[i - 1] - 1.0 for i in range(1, n)]
    panel = _write_panel(tmp_path / "panel", {
        "beta_book": [0.0002 + v for v in eth_r],
        "carry_a": [0.0004] * n,
        "carry_b": [0.0003] * n}, axis)
    rates = _write_rates(tmp_path / "rates", axis, prices)
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size)
              for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    rc = x.main(["--section", "hedge", "--panel-dir", str(panel), "--rates-dir", str(rates)])
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size)
             for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    assert rc == 0
    assert before == after


def test_an_axis_that_does_not_straddle_the_split_is_a_refusal(tmp_path):
    """Пустое окно TRAIN/TEST — НЕ ИЗМЕРЕНО с названной причиной, а не нули в таблице."""
    with pytest.raises(x.Unmeasured) as e:
        x.require_straddle("сцена", [1, 2, 3], [])
    assert "не пересекает шов" in str(e.value)
    with pytest.raises(x.Unmeasured):
        x.require_straddle("сцена", [], [1, 2, 3])
    x.require_straddle("сцена", [1], [2])          # обе стороны есть — проходит молча


def test_main_returns_two_on_an_unmeasurable_scene(tmp_path):
    """Третий исход доходит до кода возврата: 2, а не 0 и не «эджа нет»."""
    n = 300
    axis = _axis(n)
    panel = _write_panel(tmp_path / "panel", {f"b{k}": [0.0002] * n for k in range(3)}, axis)
    rates = _write_rates(tmp_path / "rates", axis, [100.0] * n)
    rc = x.main(["--section", "lead", "--panel-dir", str(panel), "--rates-dir", str(rates)])
    assert rc == 2
