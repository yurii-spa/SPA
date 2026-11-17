"""Контроли прибора #161 RLI (`scripts/edge_refusal_ledger_information.py`).

Каждая проверка — контроль В ОБЕ СТОРОНЫ: мир, где прибор ОБЯЗАН увидеть движение/проход/разрыв,
и мир, где он обязан сказать «нет». Положительный контроль здесь несущий: прибор, который на
живом журнале отвечает «сторона не двигается», обязан на подвижном журнале ответить «двигается» —
иначе его ответ есть свойство прибора, а не журнала.

Отдельный класс проверок — ТРЕТИЙ ИСХОД (инв. #17): отсутствие наблюдения обязано быть отличимо
от нуля. Строка без `exit_cap` не есть строка с нулевой ёмкостью выхода, а пустой журнал не есть
журнал без отказов.

Время и живой журнал: фикстуры СВОИ, в `tmp_path`; живой `data/` ни один тест не открывает на
запись, и один тест это ПРОВЕРЯЕТ побайтово.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: no-wall-clock-door — у ПРИБОРА нет ни одной двери к стенным часам (ни
# `now()`, ни `today()`, ни `time.time()`), и ни один его вопрос не сравнивает отметку с
# «сейчас»: такт считается между ДВУМЯ отметками, прочитанными из той же сцены. Литералы
# ниже — ЯКОРЬ сцены, от которого выведены обе стороны каждого сравнения, поэтому сдвиг
# календаря не меняет ни одного вердикта. Претензия не на слово: её МЕРИТ контроль
# `test_the_instrument_has_no_wall_clock_door` в этом же файле (AST прибора), а приём №1
# (`injected-clock`) здесь был бы ЛОЖЬЮ — инъектировать нечего, часов у прибора нет.
from __future__ import annotations

import ast
import datetime
import hashlib
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "edge_refusal_ledger_information.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("edge_rli_under_test", _SCRIPT)
    assert spec and spec.loader, f"прибор не загружается: {_SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rli = _load_module()


# ── конструктор сцен ────────────────────────────────────────────────────────────────────────────
def _row(seq: int, *, kind: str, underlying: str, net_edge: str, size: str = "0",
         reason: str = "none", ts: str | None = None, detail: dict | None = None,
         approved: bool | None = None) -> dict:
    stamp = ts or (datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
                   + datetime.timedelta(seconds=30 * seq)).isoformat()
    return {
        "seq": seq, "kind": kind, "underlying": underlying, "net_edge": net_edge,
        "approved_size_usd": size, "reason": reason, "ts": stamp,
        "approved": (kind == "ENTRY") if approved is None else approved,
        "detail": {} if detail is None else detail,
    }


def _chain(rows: list[dict]) -> list[dict]:
    """Сшить строки в честную цепь: `entry_hash` от содержимого, `prev_hash` от предыдущей."""
    prev = "0" * 64
    out = []
    for row in rows:
        body = dict(row)
        body["prev_hash"] = prev
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        body["entry_hash"] = digest
        prev = digest
        out.append(body)
    return out


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _frozen_world(n_ticks: int = 20) -> list[dict]:
    """Мир ЖИВОГО журнала: одобренная сторона стои́т, отказанная двигается."""
    rows: list[dict] = []
    seq = 0
    for tick in range(n_ticks):
        ts = (datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
              + datetime.timedelta(seconds=24 * tick)).isoformat()
        rows.append(_row(seq, kind="ENTRY", underlying="susde", net_edge="0.11",
                         size="7634.68", ts=ts)); seq += 1
        rows.append(_row(seq, kind="REFUSAL", underlying="usde",
                         net_edge=f"0.06{tick:04d}", reason="size_floor", ts=ts,
                         detail={"exit_cap": f"{40 + tick}.50",
                                 "min_tradeable_size_usd": "1000"})); seq += 1
    return _chain(rows)


def _moving_world(n_ticks: int = 20) -> list[dict]:
    """Мир, где ОДОБРЕННАЯ сторона двигается каждый тик — положительный контроль §2."""
    rows: list[dict] = []
    seq = 0
    for tick in range(n_ticks):
        ts = (datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
              + datetime.timedelta(seconds=24 * tick)).isoformat()
        rows.append(_row(seq, kind="ENTRY", underlying="susde",
                         net_edge=f"0.11{tick:04d}", size=f"{7000 + tick}.00", ts=ts)); seq += 1
    return _chain(rows)


# ── §0 ТРЕТИЙ ИСХОД у чтения журнала ───────────────────────────────────────────────────────────
def test_missing_log_is_unmeasured_not_empty(tmp_path):
    with pytest.raises(rli.Unmeasured) as exc:
        rli.load_rows(tmp_path / "нет-такого.jsonl")
    assert "нет по пути" in str(exc.value)


def test_empty_log_is_unmeasured_not_zero_refusals(tmp_path):
    path = _write(tmp_path / "log.jsonl", [])
    path.write_text("\n\n  \n", encoding="utf-8")
    with pytest.raises(rli.Unmeasured) as exc:
        rli.load_rows(path)
    assert "НЕ ИЗМЕРЕНО" in str(exc.value), "пустой журнал нельзя выдать за «отказов нет»"


def test_unparsable_line_refuses_the_whole_window(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text(json.dumps(_frozen_world(1)[0]) + "\nэто не json\n", encoding="utf-8")
    with pytest.raises(rli.Unmeasured) as exc:
        rli.load_rows(path)
    assert "строка 2" in str(exc.value), "причина обязана назвать номер строки"


def test_non_object_line_refuses(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(rli.Unmeasured):
        rli.load_rows(path)


def test_good_log_loads(tmp_path):
    rows = _frozen_world(3)
    path = _write(tmp_path / "log.jsonl", rows)
    assert len(rli.load_rows(path)) == len(rows)


# ── §0b ТРЕТИЙ ИСХОД у чтения числа ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [None, "", "abc", True, {}])
def test_absent_or_garbage_number_is_none_never_zero(raw):
    assert rli._dec({"x": raw}, "x") is None, "мусор в поле не есть замер, и уж точно не ноль"


def test_missing_key_is_none_never_zero():
    assert rli._dec({}, "x") is None


def test_zero_is_a_value_not_an_absence():
    assert rli._dec({"x": "0"}, "x") == Decimal(0), "ноль — ЗНАЧЕНИЕ, а не отсутствие"


def test_decimal_string_keeps_full_precision():
    value = rli._dec({"x": "7634.6882601905305000"}, "x")
    assert value == Decimal("7634.6882601905305000")
    assert str(value) == "7634.6882601905305000", "строка произвольной точности не округляется"


# ── §1 цепь: цела / разорвана / не прочитана ───────────────────────────────────────────────────
def test_intact_chain_is_called_intact():
    res = rli.check_chain(_frozen_world(5))
    assert res["intact"] is True
    assert res["breaks"] == []
    assert res["seq_contiguous"] is True


def test_broken_link_is_found_at_the_right_row():
    rows = _frozen_world(5)
    rows[4]["prev_hash"] = "f" * 64
    res = rli.check_chain(rows)
    assert res["intact"] is False
    assert [b["index"] for b in res["breaks"]] == [4]
    assert res["breaks"][0]["expected"] == rows[3]["entry_hash"][:12], (
        "сверять надо с ПРЕДЫДУЩЕЙ строкой, а не с собой")


def test_chain_compares_against_the_previous_row_not_itself():
    """Мутант «сверять с rows[i]» объявил бы целую цепь разорванной — и наоборот."""
    rows = _frozen_world(4)
    res = rli.check_chain(rows)
    assert res["intact"] is True
    # у честной цепи prev_hash НИКОГДА не равен своему же entry_hash
    assert all(r["prev_hash"] != r["entry_hash"] for r in rows)


def test_missing_hash_fields_are_counted_and_block_intact():
    rows = _frozen_world(4)
    del rows[2]["entry_hash"]
    res = rli.check_chain(rows)
    assert res["hash_fields_missing"] == 1
    assert res["intact"] is False, "строка без хэша не есть целая цепь"


def test_non_contiguous_seq_is_named():
    rows = _frozen_world(4)
    rows[3]["seq"] = 999
    res = rli.check_chain(rows)
    assert res["seq_contiguous"] is False
    assert "НЕТ" in res["seq_verdict"]


def test_seq_without_integers_is_unmeasured_not_false():
    rows = _frozen_world(3)
    rows[1]["seq"] = "вторая"
    res = rli.check_chain(rows)
    assert res["seq_contiguous"] is None
    assert "НЕ ИЗМЕРЕНО" in res["seq_verdict"]


def test_bool_is_not_an_integer_seq():
    rows = _frozen_world(2)
    rows[0]["seq"] = True
    res = rli.check_chain(rows)
    assert res["seq_contiguous"] is None, "«да» номером записи не является"


# ── §2 информация: прибор видит ДВИЖЕНИЕ, когда оно есть, и застой, когда его нет ──────────────
def test_frozen_approved_side_is_reported_frozen():
    res = rli.measure_information(_frozen_world(20))
    entry = res["per_side"]["ENTRY"]
    assert entry["rows"] == 20
    assert entry["distinct_tuples"] == 1
    assert entry["net_edge_distinct"] == 1
    assert entry["most_repeated"][0][1] == 20


def test_moving_approved_side_is_reported_moving():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: тот же прибор на подвижном журнале обязан увидеть движение."""
    res = rli.measure_information(_moving_world(20))
    entry = res["per_side"]["ENTRY"]
    assert entry["rows"] == 20
    assert entry["net_edge_distinct"] == 20, "прибор, слепой к движению, отвечает о себе"
    assert entry["size_distinct"] == 20
    assert entry["distinct_tuples"] == 20


def test_refused_side_movement_is_measured():
    res = rli.measure_information(_frozen_world(20))
    assert res["per_side"]["REFUSAL"]["net_edge_distinct"] == 20


def test_side_is_read_from_kind_not_from_approved():
    """Род записи объявляется полем рода. Мутант, читающий `approved`, покрасит эту проверку."""
    rows = _chain([_row(0, kind="ENTRY", underlying="susde", net_edge="0.1", approved=False),
                   _row(1, kind="REFUSAL", underlying="usde", net_edge="0.1", approved=True,
                        reason="size_floor")])
    res = rli.measure_information(rows)
    assert res["sides"] == {"ENTRY": 1, "REFUSAL": 1}


def test_unknown_kind_is_other_not_silently_an_entry():
    rows = _chain([_row(0, kind="WHATEVER", underlying="susde", net_edge="0.1")])
    res = rli.measure_information(rows)
    assert res["sides"] == {"OTHER": 1}
    assert res["per_side"]["ENTRY"]["rows"] == 0
    assert "НЕ ИЗМЕРЕНО" in res["per_side"]["ENTRY"]["verdict"]


def test_two_refusal_reasons_are_both_reported():
    """Если у отказа ДВЕ причины — прибор обязан показать две: «одна причина» должна быть замером."""
    rows = _chain([
        _row(0, kind="REFUSAL", underlying="usde", net_edge="0.06", reason="size_floor",
             detail={"exit_cap": "50", "min_tradeable_size_usd": "1000"}),
        _row(1, kind="REFUSAL", underlying="wsteth", net_edge="0.04", reason="peg_haircut",
             detail={"exit_cap": "5000", "min_tradeable_size_usd": "1000"}),
    ])
    res = rli.measure_information(rows)
    assert res["refusal_reasons"] == {"size_floor": 1, "peg_haircut": 1}
    assert set(res["refusal_underlyings"]) == {"usde", "wsteth"}


def test_missing_reason_is_unmeasured_not_none_string():
    rows = _chain([_row(0, kind="REFUSAL", underlying="usde", net_edge="0.06")])
    rows[0].pop("reason")
    res = rli.measure_information(rows)
    assert res["refusal_reasons"] == {"НЕ ИЗМЕРЕНО": 1}


def test_unmeasured_numbers_are_counted_separately_from_distinct():
    rows = _chain([_row(0, kind="ENTRY", underlying="susde", net_edge="0.11"),
                   _row(1, kind="ENTRY", underlying="susde", net_edge="0.11")])
    rows[1]["net_edge"] = None
    res = rli.measure_information(rows)
    entry = res["per_side"]["ENTRY"]
    assert entry["net_edge_distinct"] == 1 and entry["net_edge_unmeasured"] == 1, (
        "пропуск не увеличивает число РАЗЛИЧНЫХ наблюдений и не исчезает молча")


# ── §2b такт ───────────────────────────────────────────────────────────────────────────────────
def test_cadence_needs_two_distinct_stamps():
    rows = _chain([_row(0, kind="ENTRY", underlying="susde", net_edge="0.1",
                        ts="2026-01-01T00:00:00+00:00")])
    res = rli.measure_information(rows)
    assert "НЕ ИЗМЕРЕНО" in res["cadence"]["verdict"]


def test_cadence_counts_ticks_not_rows():
    rows = _frozen_world(20)      # 20 тиков × 2 строки
    res = rli.measure_information(rows)
    assert res["cadence"]["ticks"] == 20
    assert res["cadence"]["rows_per_tick"] == {2: 20}
    assert res["cadence"]["gap_median_s"] == 24.0


def test_unreadable_stamp_is_named_not_dropped():
    rows = _frozen_world(3)
    rows[1]["ts"] = "вчера"
    res = rli.measure_information(rows)
    assert res["ts_unreadable_count"] == 1
    assert "не разбирается" in res["ts_unreadable"][0]


# ── §3 экономика: порог проходится / не проходится / не измерен ────────────────────────────────
def test_capacity_below_floor_never_passes():
    res = rli.measure_economics(_frozen_world(20))
    assert res["rows_at_or_above_floor"] == 0
    assert res["measured"] == 20 and res["incomplete"] == 0
    assert Decimal(res["exit_cap_max"]) < Decimal("1000")
    assert Decimal(res["shortfall_best_case_x"]) > 1


def test_capacity_at_the_floor_passes_boundary_is_inclusive():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ границы: ровно пол — это проход (мутант `>` покраснеет)."""
    rows = _chain([_row(0, kind="REFUSAL", underlying="usde", net_edge="0.06",
                        reason="size_floor",
                        detail={"exit_cap": "1000", "min_tradeable_size_usd": "1000"})])
    res = rli.measure_economics(rows)
    assert res["rows_at_or_above_floor"] == 1


def test_capacity_just_below_the_floor_does_not_pass():
    rows = _chain([_row(0, kind="REFUSAL", underlying="usde", net_edge="0.06",
                        reason="size_floor",
                        detail={"exit_cap": "999.99", "min_tradeable_size_usd": "1000"})])
    assert rli.measure_economics(rows)["rows_at_or_above_floor"] == 0


def test_annual_edge_is_capacity_times_edge():
    rows = _chain([_row(0, kind="REFUSAL", underlying="usde", net_edge="0.10",
                        reason="size_floor",
                        detail={"exit_cap": "200", "min_tradeable_size_usd": "1000"})])
    res = rli.measure_economics(rows)
    assert Decimal(res["annual_edge_usd_max"]) == Decimal("20.00"), (
        "годовой эдж = ёмкость × ставка; мутант, потерявший ставку, напечатает 200")


def test_row_without_exit_cap_is_incomplete_not_zero_capacity():
    rows = _chain([
        _row(0, kind="REFUSAL", underlying="usde", net_edge="0.06", reason="size_floor",
             detail={"min_tradeable_size_usd": "1000"}),
        _row(1, kind="REFUSAL", underlying="usde", net_edge="0.06", reason="size_floor",
             detail={"exit_cap": "50", "min_tradeable_size_usd": "1000"}),
    ])
    res = rli.measure_economics(rows)
    assert res["incomplete"] == 1 and res["measured"] == 1
    assert Decimal(res["exit_cap_min"]) == Decimal("50.00"), (
        "строка без ёмкости не есть строка с нулевой ёмкостью")


def test_all_rows_incomplete_is_unmeasured_not_zero():
    rows = _chain([_row(0, kind="REFUSAL", underlying="usde", net_edge="0.06",
                        reason="size_floor", detail={})])
    res = rli.measure_economics(rows)
    assert "НЕ ИЗМЕРЕНО" in res["verdict"]
    assert "exit_cap" in res["verdict"]


def test_no_refusals_is_unmeasured_not_a_clean_pass():
    res = rli.measure_economics(_moving_world(3))
    assert "НЕ ИЗМЕРЕНО" in res["verdict"]


def test_several_floors_are_all_printed():
    """Пол — наблюдение из строки, а не константа прибора: два пола обязаны быть видны оба."""
    rows = _chain([
        _row(0, kind="REFUSAL", underlying="usde", net_edge="0.06", reason="size_floor",
             detail={"exit_cap": "50", "min_tradeable_size_usd": "1000"}),
        _row(1, kind="REFUSAL", underlying="usde", net_edge="0.06", reason="size_floor",
             detail={"exit_cap": "50", "min_tradeable_size_usd": "25000"}),
    ])
    assert rli.measure_economics(rows)["floors"] == ["1000", "25000"]


# ── §4 CLI: коды возврата различают три исхода ─────────────────────────────────────────────────
def test_cli_returns_zero_on_a_measured_window(tmp_path, capsys):
    path = _write(tmp_path / "log.jsonl", _frozen_world(5))
    assert rli.main(["--log", str(path)]) == 0
    out = capsys.readouterr().out
    assert "цепь ЦЕЛА" in out and "§3" in out


def test_cli_returns_two_when_nothing_could_be_read(tmp_path, capsys):
    assert rli.main(["--log", str(tmp_path / "нет.jsonl")]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_cli_returns_one_on_a_broken_chain(tmp_path, capsys):
    rows = _frozen_world(5)
    rows[3]["prev_hash"] = "0" * 64
    path = _write(tmp_path / "log.jsonl", rows)
    assert rli.main(["--log", str(path)]) == 1
    assert "РАЗОРВАНА" in capsys.readouterr().out


def test_cli_json_is_machine_readable(tmp_path, capsys):
    path = _write(tmp_path / "log.jsonl", _frozen_world(5))
    assert rli.main(["--log", str(path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["chain"]["intact"] is True
    assert doc["information"]["per_side"]["ENTRY"]["distinct_tuples"] == 1


def test_cli_section_asks_one_question_only(tmp_path, capsys):
    path = _write(tmp_path / "log.jsonl", _frozen_world(5))
    assert rli.main(["--log", str(path), "--section", "economics", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert "economics" in doc and "chain" not in doc and "information" not in doc


# ── §5 прибор ничего не пишет ──────────────────────────────────────────────────────────────────
def test_instrument_does_not_write_a_single_byte(tmp_path):
    path = _write(tmp_path / "log.jsonl", _frozen_world(5))
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert rli.main(["--log", str(path)]) == 0
    after = (path.read_bytes(), path.stat().st_mtime_ns)
    assert before == after, "прибор обязан открывать журнал ТОЛЬКО на чтение"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["log.jsonl"], (
        "прибор не создаёт рядом ни одного файла")


# ── §6 ВХОД решения (decomposition) — он же обязан быть отличим от его исхода ──────────────────
def test_frozen_decomposition_is_reported_frozen():
    rows = _chain([_row(i, kind="ENTRY", underlying="susde", net_edge="0.11",
                        detail={}) | {"decomposition": {"as_of": f"2026-01-{i+1:02d}",
                                                        "fair_yield": "-0.02",
                                                        "liquidity_haircut": "0.015"}}
                   for i in range(5)])
    info = rli.measure_information(rows)["per_side"]["ENTRY"]
    assert info["decomposition_distinct"] == 1, (
        "`as_of` в ключ не входит: меняющаяся ДАТА при неподвижных числах — это неподвижный вход")
    assert info["decomposition_unmeasured"] == 0


def test_moving_decomposition_is_reported_moving():
    rows = _chain([_row(i, kind="ENTRY", underlying="susde", net_edge="0.11")
                   | {"decomposition": {"as_of": "2026-01-01",
                                        "fair_yield": f"-0.0{i}",
                                        "liquidity_haircut": "0.015"}}
                   for i in range(5)])
    info = rli.measure_information(rows)["per_side"]["ENTRY"]
    assert info["decomposition_distinct"] == 5


def test_missing_decomposition_is_unmeasured_not_a_frozen_input():
    rows = _chain([_row(0, kind="ENTRY", underlying="susde", net_edge="0.11"),
                   _row(1, kind="ENTRY", underlying="susde", net_edge="0.11")
                   | {"decomposition": {"fair_yield": "-0.02"}}])
    info = rli.measure_information(rows)["per_side"]["ENTRY"]
    assert info["decomposition_unmeasured"] == 1 and info["decomposition_distinct"] == 1


# ── §7 претензия пометки FROZEN-DATE-OK — МЕРИТСЯ, а не объявляется ───────────────────────────
def test_the_instrument_has_no_wall_clock_door():
    """Пометка в шапке утверждает «у прибора нет часов». Вот её замер, а не записка.

    Урок #477: причина у `FROZEN-DATE-OK` живёт ровно до тех пор, пока её кто-то СВЕРЯЕТ с
    кодом. Здесь претензия проверяема дешевле всего: разобрать AST прибора и убедиться, что
    ни одна из дверей к «сейчас» не вызывается. Появится такая дверь — тест покраснеет, и
    пометку придётся переписать вместе с ней.
    """
    forbidden = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    doors = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None)
        if name in forbidden:
            doors.append(f"{name} (строка {node.lineno})")
    assert doors == [], f"у прибора появилась дверь к стенным часам: {doors}"
