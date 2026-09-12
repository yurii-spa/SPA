"""ADR-336: разовое разрешение CIO на пробный ход (решение владельца ADR-334, вариант 1).

Приёмка карточки inbox-probnyi-hod-sverh-byudzheta-oborota: разрешение одноразовое и
расходуемое, видно в вердикте, fail-CLOSED, RiskPolicy и пороги не тронуты, и
положительный контроль — разрешение израсходовано ⇒ ВТОРОЙ ход отказывает.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from spa_core.allocator.rebalance_economics import Decision, TriggerParams
from spa_core.paper_trading import cio_trial as ct

P = TriggerParams()
FREQ_ONLY = {"has_legs": True, "gain_above_band": True, "payback_within_horizon": True,
             "cooldown_ok": False, "min_hold_ok": True, "move_turnover_ok": False,
             "week_turnover_ok": False, "target_fully_evidenced": True}


def _hold(gates=None, gain=0.9, payback=12.0):
    return Decision(decision="HOLD", reasons=["x"], gain_pp=gain, payback_days=payback,
                    gates=dict(gates or FREQ_ONLY))


class _Dir:
    def __init__(self, trades=None, raw=None):
        self.td = TemporaryDirectory(); self.d = Path(self.td.name)
        if raw is not None:
            (self.d / "trades.json").write_text(raw, encoding="utf-8")
        elif trades is not None:
            (self.d / "trades.json").write_text(json.dumps(trades), encoding="utf-8")


class TheGrant(unittest.TestCase):
    def test_a_move_blocked_only_by_frequency_limits_becomes_a_trial_act(self):
        d = _Dir(trades=[])
        dec, why = ct.apply_trial_grant(_hold(), P, book_id="conservative", data_dir=d.d)
        self.assertEqual(dec.decision, "ACT")
        self.assertTrue(dec.gates[ct.MARK], "пробный ход неотличим от обычного")
        self.assertTrue(any(ct.MARK in r for r in dec.reasons))
        self.assertIn("ПРОБНЫЙ", why)

    def test_the_reversal_surcharge_is_waived_but_the_base_bar_is_not(self):
        g = dict(FREQ_ONLY, gain_above_band=False)   # провалил ПОВЫШЕННЫЙ порог разворота
        dec, _ = ct.apply_trial_grant(_hold(g, gain=0.6), P, book_id="conservative",
                                      data_dir=_Dir(trades=[]).d)
        self.assertEqual(dec.decision, "ACT")
        dec2, why = ct.apply_trial_grant(_hold(g, gain=0.3), P, book_id="conservative",
                                         data_dir=_Dir(trades=[]).d)
        self.assertEqual(dec2.decision, "HOLD", "ниже БАЗОВОГО порога пробовать нечего")
        self.assertIn("базового", why)


class EconomicsMustPassOnItsOwn(unittest.TestCase):
    def test_a_bad_payback_stays_hold(self):
        dec, why = ct.apply_trial_grant(_hold(dict(FREQ_ONLY, payback_within_horizon=False)),
                                        P, book_id="conservative", data_dir=_Dir(trades=[]).d)
        self.assertEqual(dec.decision, "HOLD")
        self.assertIn("экономика", why)

    def test_an_unevidenced_target_stays_hold(self):
        dec, _ = ct.apply_trial_grant(_hold(dict(FREQ_ONLY, target_fully_evidenced=False)),
                                      P, book_id="conservative", data_dir=_Dir(trades=[]).d)
        self.assertEqual(dec.decision, "HOLD")

    def test_an_unknown_failing_gate_holds(self):
        dec, why = ct.apply_trial_grant(_hold(dict(FREQ_ONLY, some_new_gate=False)),
                                        P, book_id="conservative", data_dir=_Dir(trades=[]).d)
        self.assertEqual(dec.decision, "HOLD")
        self.assertIn("неизвестный", why)


class ConsumableAndFailClosed(unittest.TestCase):
    def test_a_spent_grant_refuses_the_second_move(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ приёмки: израсходовано ⇒ второй ход отказывает."""
        spent = [{"trade_id": "T034", ct.MARK: ct.TRIAL_GRANT["adr"]}]
        d = _Dir(trades=spent)   # держим ссылку: иначе каталог удалит сборщик мусора
        dec, why = ct.apply_trial_grant(_hold(), P, book_id="conservative", data_dir=d.d)
        self.assertEqual(dec.decision, "HOLD")
        self.assertIn("израсходовано", why)

    def test_an_unreadable_journal_does_not_grant_a_second_move(self):
        d = _Dir(raw="{битый json")
        dec, why = ct.apply_trial_grant(_hold(), P, book_id="conservative", data_dir=d.d)
        self.assertEqual(dec.decision, "HOLD")
        self.assertIn("fail-CLOSED", why)

    def test_other_books_do_not_get_the_grant(self):
        dec, _ = ct.apply_trial_grant(_hold(), P, book_id="balanced", data_dir=_Dir(trades=[]).d)
        self.assertEqual(dec.decision, "HOLD")

    def test_the_grant_is_exactly_one_move_from_the_owner(self):
        self.assertEqual(ct.TRIAL_GRANT["moves"], 1)
        self.assertEqual(ct.TRIAL_GRANT["adr"], "ADR-334")

    def test_thresholds_are_untouched(self):
        self.assertEqual((P.min_gain_pp, P.max_payback_days, P.max_turnover_per_move,
                          P.max_turnover_per_week), (0.5, 30.0, 0.15, 0.25))


# ── сквозной: настоящий run_cycle, вердикт CIO ДЕЛАЕТСЯ пробным, сделка несёт метку ──
from spa_core.tests.test_cycle_runner import APY, TARGET, _run, _load  # noqa: E402


def _cio_doc_with_trial(monkeypatch, fire: bool):
    """Сцена: экономика CIO прошла, частота отказала — и пусть решает НАСТОЯЩЕЕ разрешение."""
    from spa_core.paper_trading import allocation_rationale as ar
    real_eval = ar.evaluate

    def fake_eval(**kw):
        d = real_eval(**kw)
        if d.gates.get("has_legs"):
            d.decision = "HOLD"
            d.gain_pp, d.payback_days = 0.9, 12.0
            d.gates.update(FREQ_ONLY if fire else dict(FREQ_ONLY, payback_within_horizon=False))
        return d
    monkeypatch.setattr(ar, "evaluate", fake_eval)


def test_cycle_takes_one_trial_move_and_refuses_the_second(tmp_path, monkeypatch):
    _cio_doc_with_trial(monkeypatch, fire=True)
    _run(tmp_path, APY, TARGET)                                   # первичное размещение
    # ИЗМЕНЕНО НАМЕРЕННО (ADR-357, инв. #16): сцена уменьшена с $20 000 до $14 000,
    # предмет теста НЕ тронут. Ответ владельца 12.09 ввёл потолок СУММЫ одного хода
    # ($15 000), и разрешение его не снимает и не должно: это потолок размера, а не
    # частоты. Прежняя сцена двигала $20 000 и с тех пор нарушала ДВА ограничения
    # сразу — своё (демпфер) и чужое (сумма), а сцена обязана нарушать ТОЛЬКО своё,
    # иначе тест доказывает не то, ради чего написан.
    swap = {"aave_v3": 40000.0, "morpho_blue": 6000.0, "maple": 14000.0, "yearn_v3": 14000.0}
    r2 = _run(tmp_path, APY, swap, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    assert r2.traded is True, "пробный ход не состоялся"
    trades = _load(tmp_path, "trades.json")
    assert trades[-1].get(ct.MARK) == ct.TRIAL_GRANT["adr"], "сделка не несёт признак расхода"
    back = {"aave_v3": 40000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}  # обратный ход той же величины
    r3 = _run(tmp_path, APY, back, now=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc))
    assert r3.traded is False, "второй ход прошёл по израсходованному разрешению"
    assert sum(1 for t in _load(tmp_path, "trades.json") if t.get(ct.MARK)) == 1


def test_cycle_without_passing_economics_takes_no_trial(tmp_path, monkeypatch):
    _cio_doc_with_trial(monkeypatch, fire=False)
    _run(tmp_path, APY, TARGET)
    # ИЗМЕНЕНО НАМЕРЕННО (ADR-357, инв. #16): сцена уменьшена с $20 000 до $14 000,
    # предмет теста НЕ тронут. Ответ владельца 12.09 ввёл потолок СУММЫ одного хода
    # ($15 000), и разрешение его не снимает и не должно: это потолок размера, а не
    # частоты. Прежняя сцена двигала $20 000 и с тех пор нарушала ДВА ограничения
    # сразу — своё (демпфер) и чужое (сумма), а сцена обязана нарушать ТОЛЬКО своё,
    # иначе тест доказывает не то, ради чего написан.
    swap = {"aave_v3": 40000.0, "morpho_blue": 6000.0, "maple": 14000.0, "yearn_v3": 14000.0}
    r2 = _run(tmp_path, APY, swap, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    assert r2.traded is False
    assert not any(t.get(ct.MARK) for t in _load(tmp_path, "trades.json"))


class NotSpentOnMovesThatPassAnyway(unittest.TestCase):
    """Замер 11.09 (сквозной тест): первая редакция сжигала разрешение на первичном размещении."""

    def test_placement_and_derisk_do_not_consume_the_grant(self):
        from spa_core.governance.churn_damper import (REASON_DERISK, REASON_INITIAL,
                                                      REASON_PLACE_IDLE)
        for reason in (REASON_INITIAL, REASON_PLACE_IDLE, REASON_DERISK):
            dec, why = ct.apply_trial_grant(_hold(), P, book_id="conservative",
                                            data_dir=_Dir(trades=[]).d, damper_reason=reason)
            self.assertEqual(dec.decision, "HOLD", reason)
            self.assertIn("не расходуется", why)


def test_the_trial_lifts_the_damper_that_really_blocks(tmp_path, monkeypatch):
    """Выжившая мутация №5 (11.09): демпфер в цикле судит по НАСТОЯЩИМ часам, сцены живут
    в июне-2026 — для него последний ход «три месяца назад», и он не блокирует НИКОГДА.
    Здесь он отказывает по-настоящему (min_hold) — и пробный ход обязан его снять."""
    from spa_core.governance import churn_damper as cd
    from spa_core.paper_trading import cycle_runner as cr
    real = cr._churn_decide

    def blocking(current, target, trades, capital, *a, **kw):
        v = real(current, target, trades, capital, *a, **kw)
        if v.reason not in (cd.REASON_INITIAL, cd.REASON_PLACE_IDLE, cd.REASON_DERISK):
            v.decision, v.reason = "BLOCK", cd.REASON_MIN_HOLD
        return v
    monkeypatch.setattr(cr, "_churn_decide", blocking)
    _cio_doc_with_trial(monkeypatch, fire=True)
    _run(tmp_path, APY, TARGET)
    # ИЗМЕНЕНО НАМЕРЕННО (ADR-357, инв. #16): сцена уменьшена с $20 000 до $14 000,
    # предмет теста НЕ тронут. Ответ владельца 12.09 ввёл потолок СУММЫ одного хода
    # ($15 000), и разрешение его не снимает и не должно: это потолок размера, а не
    # частоты. Прежняя сцена двигала $20 000 и с тех пор нарушала ДВА ограничения
    # сразу — своё (демпфер) и чужое (сумма), а сцена обязана нарушать ТОЛЬКО своё,
    # иначе тест доказывает не то, ради чего написан.
    swap = {"aave_v3": 40000.0, "morpho_blue": 6000.0, "maple": 14000.0, "yearn_v3": 14000.0}
    r2 = _run(tmp_path, APY, swap, now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc))
    assert r2.traded is True, "демпфер удержал пробный ход — разрешение его не сняло"
    assert _load(tmp_path, "trades.json")[-1].get(ct.MARK) == ct.TRIAL_GRANT["adr"]


def test_the_grant_classifies_the_move_on_the_cycle_clock(tmp_path):
    """Выжившая мутация №4 ADR-339: книгу опустошили продажей ВЧЕРА — по часам цикла
    это ход после недавнего оборота, а не «первичное размещение». По настенным часам
    (июнь-2026 в сцене = три месяца назад) демпфер назвал бы его первичным, и
    разрешение ответило бы «не нужно» на то, что по сути перетасовка."""
    from spa_core.paper_trading.allocation_rationale import write_shadow_rationale
    now = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
    sold = [{"trade_id": "T001", "ts": "2026-06-10T08:00:00+00:00", "type": "rebalance",
             "from_allocation": {"aave_v3": 40000.0}, "to_allocation": {},
             "delta_abs": 40000.0}]
    (tmp_path / "trades.json").write_text(json.dumps(sold), encoding="utf-8")
    doc = write_shadow_rationale(
        data_dir=tmp_path, current_positions={}, target_positions={"aave_v3": 40000.0},
        apy_pct={"aave_v3": 4.0}, apy_sources={"aave_v3": "live"}, capital_usd=100000.0,
        cycle_date="2026-06-11", run_ts=now.isoformat(), trades=sold, write=False, now=now)
    note = str(doc.get("cio_trial") or "")
    assert "initial_deployment" not in note, f"вчерашняя продажа прочитана как давняя: {note}"


if __name__ == "__main__":
    unittest.main()
