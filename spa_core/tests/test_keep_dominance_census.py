"""Приёмка прибора «оптимум против DO NOTHING» (§49 Economics, цикл #702).

Каждый тест — либо воспроизведение НАСТОЯЩЕГО исхода журнала вердиктов, либо
контроль одного звена в обратную сторону, и звено названо в имени. Подстрокой
прибор не проходит ни в одном тесте: сверяются ПОЛЯ разбора, а не текст отчёта.

# FROZEN-DATE-OK: injected-clock — якорь `_ANCHOR` объявлен один раз и
# передаётся приборам аргументом `now=`; все даты сцен выводятся ИЗ него
# (`_day`), поэтому ни одна проверка не зависит от календаря машины.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import keep_dominance_census as census

#: Единственный литерал времени в файле. Часы инъектируются: он уезжает в
#: `run_census(now=...)`, и все даты сцен считаются от него.
_ANCHOR = datetime(2026, 9, 26, 6, 0, 0, tzinfo=timezone.utc)


def _day(offset_days: int = 0) -> str:
    """Дата сцены — производная ЯКОРЯ, а не литерал календаря."""
    return (_ANCHOR + timedelta(days=offset_days)).date().isoformat()


class _Params:
    """Колонка порогов сцены. Числа передаются явно — своих у прибора нет."""

    def __init__(self, min_leg_frac=0.005, max_payback_days=30.0,
                 min_gain_pp=0.50, mode="paper", version="test-v1"):
        self.min_leg_frac = min_leg_frac
        self.max_payback_days = max_payback_days
        self.min_gain_pp = min_gain_pp
        self.mode = mode
        self.version = version


def _record(*, day: str, current: dict, target: dict, apy: dict,
            capital: float = 100_000.0, cost_usd: float = 99.83,
            verdict: str = "HOLD", gates: dict | None = None,
            stamp_totals: bool = True) -> dict:
    """Запись журнала вердиктов в той же форме, что пишет живой цикл."""
    now_pp = sum(v * apy.get(k, 0.0) for k, v in current.items()) / capital
    opt_pp = sum(v * apy.get(k, 0.0) for k, v in target.items()) / capital
    rec = {
        "schema": "shadow-hist-v2",
        "cycle_date": day,
        "capital_usd": capital,
        "current_positions": dict(current),
        "target_positions": dict(target),
        "apy_evidenced_pct": dict(apy),
        "cost_usd": cost_usd,
        "verdict": verdict,
        "generated_at": day + "T06:00:00+00:00",
    }
    if gates is not None:
        rec["gates"] = dict(gates)
    if stamp_totals:
        rec.update({"book_apy_pp": round(now_pp, 6),
                    "target_apy_pp": round(opt_pp, 6),
                    "gain_pp": round(opt_pp - now_pp, 6)})
    return rec


def _journal(tmp_path: Path, records, book_id=None) -> Path:
    """Разложить записи по журналу нужной книги — ИМЕНЕМ ПИСАТЕЛЯ, не своим."""
    from spa_core.paper_trading.allocation_rationale import history_filename
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    path = data / history_filename(book_id)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records)
                    + "\n", encoding="utf-8")
    return data


# ── сцена, воспроизводящая настоящий исход 26.09 ─────────────────────────────

#: Позиции и ставки взяты из записи `conservative` 26.09 журнала вердиктов:
#: книга 4,014 пп, «оптимум» 3,602 пп, выведено из оборота $10 789 в кэш.
_REAL_CURRENT = {"aave_v3": 5000.0, "compound_v3": 40000.0, "fluid_fusdc": 20000.0,
                 "maple": 20000.0, "morpho_blue_base": 10000.0}
_REAL_TARGET = {"aave_v3": 4736.84, "compound_v3": 37894.74, "maple": 18947.37,
                "morpho_blue": 18947.37, "morpho_blue_base": 2631.58,
                "morpho_steakhouse": 1052.63}
_REAL_APY = {"aave_v3": 3.5879, "compound_v3": 3.7333, "fluid_fusdc": 4.33,
             "maple": 5.2573, "morpho_blue": 4.547, "morpho_blue_base": 4.2424,
             "morpho_steakhouse": 4.547}


def _real_scene(tmp_path: Path, day_offset: int = 0) -> Path:
    return _journal(tmp_path, [_record(day=_day(day_offset), current=_REAL_CURRENT,
                                       target=_REAL_TARGET, apy=_REAL_APY)])


def test_real_outcome_the_published_optimum_loses_to_doing_nothing(tmp_path):
    """Воспроизведение исхода 26.09: цель, названная оптимумом, хуже KEEP."""
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is True
    assert rep["status"] == census.STATUS_CRITICAL
    assert rep["dominated_by_keep"] == 1
    found = rep["findings"][0]
    assert found["kind"] == "dominated_by_keep"
    assert found["gain_pp"] < 0.0
    assert found["apy_opt_pp"] < found["apy_now_pp"]
    assert found["book_id"] == "conservative"


def test_cause_of_the_negative_sign_is_cash_not_a_worse_protocol_mix(tmp_path):
    """Звено «разложение причины»: смесь УЛУЧШАЛАСЬ, знак сделал размер."""
    data = _real_scene(tmp_path)
    found = census.run_census(data, now=_ANCHOR, params=_Params())["findings"][0]
    assert found["cause"] == "cash"
    assert found["mix_pp"] > 0.0, "смесь протоколов улучшалась — не она виновата"
    assert found["size_pp"] < 0.0
    assert found["dedeployed_usd"] > 10_000.0


def test_decomposition_sums_exactly_to_the_gain(tmp_path):
    """Звено «точность разложения»: смесь + размер тождественно равны приросту."""
    data = _real_scene(tmp_path)
    found = census.run_census(data, now=_ANCHOR, params=_Params())["findings"][0]
    assert abs(found["mix_pp"] + found["size_pp"] - found["gain_pp"]) < 1e-6


def test_unbalanced_decomposition_is_the_third_outcome_not_a_guess(monkeypatch,
                                                                  tmp_path):
    """Звено «разложение не сошлось»: запись уходит в НЕ ИЗМЕРЕНО, а не в находку."""
    data = _real_scene(tmp_path)
    monkeypatch.setattr(census, "_DECOMP_EPS_PP", -1.0)  # сойтись невозможно
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["findings"] == []
    assert rep["records_unmeasured"] == 1
    assert "decomposition_unbalanced" in rep["unmeasured_records"][0]["reason"]


# ── существенность: пыль владельца, а не наше суждение о «много ли» ──────────

def test_dust_sized_dedeployment_is_named_but_is_not_a_finding(tmp_path):
    """Сцена книг `balanced`/`aggressive`: знак отрицателен на $36 дрейфа."""
    cur = {"aave_v3": 99_906.0}
    tgt = {"aave_v3": 99_870.0}
    data = _journal(tmp_path, [_record(day=_day(), current=cur, target=tgt,
                                       apy={"aave_v3": 4.5})])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["status"] == census.STATUS_OK
    assert rep["findings"] == []
    book = rep["books"][0]
    assert book["dominated_by_keep"] == 1, "порода названа — она просто не материальна"
    assert book["findings_dust"] == 1


def test_materiality_threshold_comes_from_the_owner_column_not_from_the_tool(tmp_path):
    """Контроль в обратную сторону: подняв пыль владельца, находка исчезает."""
    data = _real_scene(tmp_path)
    strict = census.run_census(data, now=_ANCHOR, params=_Params(min_leg_frac=0.5))
    assert strict["findings"] == []
    assert strict["books"][0]["findings_dust"] == 1
    loose = census.run_census(data, now=_ANCHOR, params=_Params(min_leg_frac=0.0001))
    assert loose["findings_material"] == 1


def test_policy_column_unavailable_is_unmeasured_not_a_substituted_default(tmp_path):
    """Звено «колонка порогов»: её отсутствие — третий исход, а не своё число."""
    class _Broken:
        min_leg_frac = "не число"

    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Broken())
    assert rep["measured"] is False
    assert rep["status"] == census.STATUS_UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in rep["reason"]
    assert rep["findings"] == []


def test_policy_loader_names_the_reason_when_the_import_fails(monkeypatch):
    """Звено «импорт колонки»: причина называется, умолчание не подставляется."""
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **kw):
        if name == "spa_core.allocator.rebalance_economics":
            raise ImportError("сцена: колонка недоступна")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    out = census.load_policy()
    assert out["measured"] is False
    assert "config/policy" in out["reason"]
    assert "min_leg_frac" not in out


# ── второй производитель: пересчёт против записанного ───────────────────────

def test_recorded_numbers_are_recomputed_and_a_disagreement_refuses_the_record(tmp_path):
    """Звено «второй производитель»: спор двух производителей ≠ доверие журналу."""
    rec = _record(day=_day(), current=_REAL_CURRENT, target=_REAL_TARGET,
                  apy=_REAL_APY)
    rec["gain_pp"] = 42.0            # запись врёт
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["findings"] == []
    assert rep["records_unmeasured"] == 1
    assert "recomputation_mismatch" in rep["unmeasured_records"][0]["reason"]


def test_a_record_without_recorded_totals_is_still_measured_by_recomputation(tmp_path):
    """Обратная сторона: пересчёт САМОСТОЯТЕЛЕН — запись без итогов измерима."""
    rec = _record(day=_day(), current=_REAL_CURRENT, target=_REAL_TARGET,
                  apy=_REAL_APY, stamp_totals=False)
    assert "gain_pp" not in rec
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["dominated_by_keep"] == 1


def test_missing_capital_is_unmeasured_not_zero(tmp_path):
    """Звено «знаменатель»: без капитала ставка не наблюдена (инвариант #17)."""
    rec = _record(day=_day(), current=_REAL_CURRENT, target=_REAL_TARGET,
                  apy=_REAL_APY)
    rec["capital_usd"] = None
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["records_unmeasured"] == 1
    assert "capital_usd" in rep["unmeasured_records"][0]["reason"]


def test_unreadable_positions_are_named_field_by_field(tmp_path):
    """Звено «позиции»: нечитаемое поле называется, а не считается пустым."""
    rec = _record(day=_day(), current=_REAL_CURRENT, target=_REAL_TARGET,
                  apy=_REAL_APY)
    rec["target_positions"] = "не словарь"
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["records_unmeasured"] == 1
    assert "target_positions" in rep["unmeasured_records"][0]["reason"]


def test_a_record_without_cycle_date_cannot_be_attributed_to_a_day(tmp_path):
    rec = _record(day=_day(), current=_REAL_CURRENT, target=_REAL_TARGET,
                  apy=_REAL_APY)
    rec.pop("cycle_date")
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["records_unmeasured"] == 1
    assert "cycle_date" in rep["unmeasured_records"][0]["reason"]


def test_boolean_is_not_a_number(tmp_path):
    """`True` — не $1 и не ставка: иначе сцена с флагом прошла бы как замер."""
    assert census._num(True) is None
    assert census._num(False) is None
    assert census._num(1.5) == 1.5
    assert census._num("1.5") is None


# ── гейт окупаемости: находка ТОЛЬКО при промахе ─────────────────────────────

def _thin_gain_scene(tmp_path, gates):
    """Прирост положителен, но за горизонт не отбивает издержки."""
    cur = {"aave_v3": 95_000.0}
    tgt = {"morpho_blue": 95_000.0}
    apy = {"aave_v3": 4.00, "morpho_blue": 4.05}   # +0.0475 пп капитала
    return _journal(tmp_path, [_record(day=_day(), current=cur, target=tgt, apy=apy,
                                      cost_usd=50.0, gates=gates)])


def test_negative_net_is_a_finding_only_when_the_payback_gate_missed_it(tmp_path):
    data = _thin_gain_scene(tmp_path, {"payback_within_horizon": True})
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["net_negative_missed_by_gate"] == 1
    assert rep["status"] == census.STATUS_CRITICAL
    assert rep["findings"][0]["net_usd_horizon"] < 0.0


def test_a_negative_net_the_gate_caught_is_not_a_finding(tmp_path):
    """Контроль в обратную сторону: гейт за работой — не находка, а работа."""
    data = _thin_gain_scene(tmp_path, {"payback_within_horizon": False})
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["findings"] == []
    assert rep["status"] == census.STATUS_OK
    assert rep["net_negative_caught_by_gate"] == 1


def test_an_absent_payback_gate_is_the_third_outcome_not_zero_misses(tmp_path):
    """Старая схема без `gates`: «гейта нет» ≠ «промахов ноль»."""
    data = _thin_gain_scene(tmp_path, None)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["findings"] == []
    assert rep["net_gate_unchecked"] == 1
    assert rep["net_negative_missed_by_gate"] == 0


def test_cost_not_observed_leaves_the_net_породa_unmeasured(tmp_path):
    """Издержки не наблюдены ⇒ чистый исход НЕ ИЗМЕРЕН, а не «издержек нет»."""
    cur = {"aave_v3": 95_000.0}
    tgt = {"morpho_blue": 95_000.0}
    apy = {"aave_v3": 4.00, "morpho_blue": 4.05}
    rec = _record(day=_day(), current=cur, target=tgt, apy=apy,
                  gates={"payback_within_horizon": True})
    rec["cost_usd"] = None
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["findings"] == []
    assert rep["books"][0]["net_unmeasured"] == 1


# ── вердикт судит НАСТОЯЩЕЕ, история остаётся замером ────────────────────────

def test_a_finding_on_the_freshest_date_is_critical(tmp_path):
    clean = _record(day=_day(-1), current={"aave_v3": 95_000.0},
                    target={"aave_v3": 95_000.0}, apy={"aave_v3": 4.0},
                    cost_usd=0.0, gates={"payback_within_horizon": True})
    dirty = _record(day=_day(0), current=_REAL_CURRENT, target=_REAL_TARGET,
                    apy=_REAL_APY)
    data = _journal(tmp_path, [clean, dirty])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["status"] == census.STATUS_CRITICAL
    assert rep["fresh_findings"] == 1


def test_history_only_findings_warn_so_quiet_today_never_reads_as_never_happened(tmp_path):
    dirty = _record(day=_day(-3), current=_REAL_CURRENT, target=_REAL_TARGET,
                    apy=_REAL_APY)
    clean = _record(day=_day(0), current={"aave_v3": 95_000.0},
                    target={"aave_v3": 95_000.0}, apy={"aave_v3": 4.0},
                    cost_usd=0.0, gates={"payback_within_horizon": True})
    data = _journal(tmp_path, [dirty, clean])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["status"] == census.STATUS_WARNING
    assert rep["fresh_findings"] == 0
    assert rep["findings_material"] == 1


def test_a_book_that_never_lost_to_keep_is_ok(tmp_path):
    clean = _record(day=_day(), current={"aave_v3": 95_000.0},
                    target={"morpho_blue": 95_000.0},
                    apy={"aave_v3": 4.0, "morpho_blue": 6.0}, cost_usd=10.0,
                    gates={"payback_within_horizon": True})
    data = _journal(tmp_path, [clean])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["status"] == census.STATUS_OK
    assert rep["findings"] == []


# ── маршрутизация журналов: имя разбирается правилом ПИСАТЕЛЯ ────────────────

def test_every_book_ledger_is_measured_not_only_the_default_one(tmp_path):
    data = _journal(tmp_path, [_record(day=_day(), current=_REAL_CURRENT,
                                       target=_REAL_TARGET, apy=_REAL_APY)])
    _journal(tmp_path, [_record(day=_day(), current={"aave_v3": 95_000.0},
                                target={"morpho_blue": 95_000.0},
                                apy={"aave_v3": 4.0, "morpho_blue": 6.0},
                                cost_usd=10.0,
                                gates={"payback_within_horizon": True})],
             book_id="balanced")
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert {b["book_id"] for b in rep["books"]} == {"conservative", "balanced"}


def test_a_ledger_whose_name_does_not_round_trip_is_named_not_skipped(tmp_path):
    data = _journal(tmp_path, [_record(day=_day(), current=_REAL_CURRENT,
                                       target=_REAL_TARGET, apy=_REAL_APY)])
    # Имя с ЗАГЛАВНОЙ буквой: обратный разбор даст `Balanced`, а правило
    # писателя приводит идентификатор к нижнему регистру — круговой ход не
    # сходится, и файл обязан быть НАЗВАН, а не пропущен молча.
    (data / "allocation_rationale_history_Balanced.jsonl").write_text("{}\n",
                                                                     encoding="utf-8")
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert any("Balanced" in item["file"]
               for item in rep["unroutable_journals"]), rep["unroutable_journals"]


def test_no_ledger_at_all_is_unmeasured_never_a_clean_pass(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert rep["status"] == census.STATUS_UNMEASURED
    assert "НЕ «оптимум всегда побеждал KEEP»" in rep["reason"]


def test_unparsable_lines_are_counted_not_silently_dropped(tmp_path):
    data = _journal(tmp_path, [_record(day=_day(), current=_REAL_CURRENT,
                                       target=_REAL_TARGET, apy=_REAL_APY)])
    from spa_core.paper_trading.allocation_rationale import history_filename
    path = data / history_filename(None)
    path.write_text(path.read_text(encoding="utf-8") + "{ битая строка\n",
                    encoding="utf-8")
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["books"][0]["unparsable_lines"] == 1


def test_a_ledger_with_no_parsable_record_is_unmeasured(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    from spa_core.paper_trading.allocation_rationale import history_filename
    (data / history_filename(None)).write_text("{ мусор\n", encoding="utf-8")
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert rep["status"] == census.STATUS_UNMEASURED


# ── ось объяснения кэша: наблюдение, а не вердикт ────────────────────────────

def test_cash_explanation_is_silent_about_the_target_it_publishes(tmp_path):
    data = _real_scene(tmp_path)
    (data / "allocation_rationale.json").write_text(json.dumps({
        "cycle_date": _day(), "cash": {"excess_pct": 0.0, "status": "explained"}}),
        encoding="utf-8")
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    axis = rep["cash_explanation"]
    assert axis["status"] == "measured"
    assert axis["silent_on_target_idle"] is True
    assert axis["target_idle_beyond_current_usd"] > 10_000.0


def test_cash_explanation_that_does_see_the_excess_is_not_reported_as_silent(tmp_path):
    """Контроль в обратную сторону: объявленный излишек — не молчание."""
    data = _real_scene(tmp_path)
    (data / "allocation_rationale.json").write_text(json.dumps({
        "cycle_date": _day(), "cash": {"excess_pct": 10.8, "status": "explained"}}),
        encoding="utf-8")
    axis = census.run_census(data, now=_ANCHOR,
                             params=_Params())["cash_explanation"]
    assert axis["silent_on_target_idle"] is False


def test_a_missing_rationale_document_is_unchecked_never_false(tmp_path):
    data = _real_scene(tmp_path)
    axis = census.run_census(data, now=_ANCHOR,
                             params=_Params())["cash_explanation"]
    assert axis["status"] == "unchecked"
    assert "silent_on_target_idle" not in axis


def test_a_rationale_document_without_the_cash_field_is_unchecked(tmp_path):
    data = _real_scene(tmp_path)
    (data / "allocation_rationale.json").write_text(json.dumps({
        "cycle_date": _day(), "cash": {"status": "explained"}}), encoding="utf-8")
    axis = census.run_census(data, now=_ANCHOR,
                             params=_Params())["cash_explanation"]
    assert axis["status"] == "unchecked"
    assert "excess_pct" in axis["reason"]


# ── артефакт: контроль читает ДИСК, а не вывод ───────────────────────────────

def test_the_bridge_stage_leaves_the_artifact_on_disk(tmp_path):
    _real_scene(tmp_path)
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    path = tmp_path / "data" / census.ARTIFACT_NAME
    assert path.exists(), "вывод ступени не есть доказательство записи"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["status"] == out["doc"]["status"]
    assert on_disk["dominated_by_keep"] >= 1


def test_the_artifact_is_left_even_when_nothing_could_be_measured(tmp_path):
    (tmp_path / "data").mkdir()
    census.run(root=str(tmp_path), now=_ANCHOR)
    on_disk = json.loads(
        (tmp_path / "data" / census.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert on_disk["measured"] is False
    assert on_disk["status"] == census.STATUS_UNMEASURED


def test_a_write_failure_is_named_and_does_not_break_the_bridge(monkeypatch, tmp_path):
    _real_scene(tmp_path)
    monkeypatch.setattr(census, "save_artifact",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("сцена")))
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    assert "artifact_not_written" in out["doc"]
    assert out["measured"] is True


# ── коды возврата ────────────────────────────────────────────────────────────

def test_exit_code_is_nonzero_only_for_a_finding_on_the_freshest_date(tmp_path):
    data = _real_scene(tmp_path)
    assert census.main(["--data-dir", str(data)]) == 1


def test_exit_code_zero_when_the_class_lives_only_in_history(tmp_path):
    dirty = _record(day=_day(-3), current=_REAL_CURRENT, target=_REAL_TARGET,
                    apy=_REAL_APY)
    clean = _record(day=_day(0), current={"aave_v3": 95_000.0},
                    target={"aave_v3": 95_000.0}, apy={"aave_v3": 4.0},
                    cost_usd=0.0, gates={"payback_within_horizon": True})
    data = _journal(tmp_path, [dirty, clean])
    assert census.main(["--data-dir", str(data)]) == 0


def test_exit_code_three_when_nothing_was_measured(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    assert census.main(["--data-dir", str(data)]) == census.EXIT_UNMEASURED


# ── отчёт офиса: «не измерено» печатается как таковое ────────────────────────

def test_the_office_summary_says_unmeasured_out_loud(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    line = census.summary_line(rep)
    assert "НЕ ИЗМЕРЕНО" in line
    assert census.format_report(rep) == [line]


def test_the_office_report_names_the_door_of_the_finding(tmp_path):
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    text = "\n".join(census.format_report(rep))
    assert "ОПТИМУМ ПРОИГРАЛ KEEP" in text
    assert "выведено из оборота" in text
    assert "НЕ ДОКЛАДЫВАЕТ" in text


@pytest.mark.parametrize("field", ["findings_material", "dominated_by_keep",
                                   "fresh_findings", "records_unmeasured",
                                   "dedeployed_usd_max"])
def test_headline_numbers_are_readable_by_the_bridge_at_the_top_level(tmp_path, field):
    """Мост и офис читают `observed_number(doc, key)` — верхний уровень."""
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert field in rep and isinstance(rep[field], (int, float))


def test_the_unmeasured_report_still_names_every_refused_record(tmp_path):
    """Третий исход обязан НАЗВАТЬ причины: иначе он равен «мерить было нечего»."""
    rec = _record(day=_day(), current=_REAL_CURRENT, target=_REAL_TARGET,
                  apy=_REAL_APY)
    rec["gain_pp"] = 42.0
    data = _journal(tmp_path, [rec])
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert rep["records_unmeasured"] == 1
    text = "\n".join(census.format_report(rep))
    assert "ЗАПИСЬ НЕ ИЗМЕРЕНА" in text
    assert "recomputation_mismatch" in text


def test_a_report_without_the_cash_axis_field_says_unmeasured_not_silent(tmp_path):
    """Контроль честного чтения: поля НЕТ ⇒ «НЕ ИЗМЕРЕНО», а не «молчания нет»."""
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    rep.pop("cash_explanation")
    text = "\n".join(census.format_report(rep))
    assert "не несёт поля `cash_explanation`" in text


def test_a_report_without_the_refused_records_field_says_unmeasured_not_zero(tmp_path):
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    rep.pop("unmeasured_records")
    text = "\n".join(census.format_report(rep))
    assert "НЕ «непрошедших записей нет»" in text


def test_a_report_without_the_unroutable_field_says_unmeasured(tmp_path):
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    rep.pop("unroutable_journals")
    text = "\n".join(census.format_report(rep))
    assert "ЖУРНАЛЫ НЕ МАРШРУТИЗИРОВАНЫ] НЕ ИЗМЕРЕНО" in text
    assert "`unroutable_journals`" in text


def test_garbage_in_the_cash_axis_field_is_not_taken_as_an_observation(tmp_path):
    """Мусор в поле не есть замер: строка вместо объекта — третий исход."""
    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    rep["cash_explanation"] = "молчит"
    text = "\n".join(census.format_report(rep))
    assert "не несёт поля `cash_explanation`" in text


def test_the_unmeasured_artifact_still_names_the_criterion(tmp_path):
    """Артефакт третьего исхода обязан назвать, ЧТО не удалось измерить."""
    data = tmp_path / "data"
    data.mkdir()
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert rep["criterion"] == census.CRITERION
    assert "Economics" in rep["criterion"]


def test_the_criterion_text_is_one_copy_for_both_branches(tmp_path):
    """Одна редакция предмета на обе ветки — иначе две фразы разъедутся."""
    data = _real_scene(tmp_path)
    measured = census.run_census(data, now=_ANCHOR, params=_Params())
    empty = tmp_path / "empty"
    (empty / "data").mkdir(parents=True)
    unmeasured = census.run_census(empty / "data", now=_ANCHOR, params=_Params())
    assert measured["criterion"] == unmeasured["criterion"] == census.CRITERION


def test_the_policy_column_is_absent_not_invented_when_it_could_not_be_read(tmp_path):
    """Колонку не прочитали ⇒ поле `policy` пусто, а не заполнено умолчанием."""
    class _Broken:
        min_leg_frac = "не число"

    data = _real_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Broken())
    assert rep["policy"] is None
    assert rep["horizon_days"] is None
