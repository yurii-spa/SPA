"""Контроль пробы `decision_journal_keeps_every_run` (ADR-395) — в ОБЕ стороны.

`.claude/rules/acceptance.md`, п. 3: новая проба регистрируется только с тестом,
где она ЗЕЛЁНАЯ на целом контуре и КРАСНАЯ на каждом порванном звене — с
названным звеном, — и где вердикт НЕ проходит подстрокой (ADR-333).

Звеньев четыре, и каждое рвётся здесь ОТДЕЛЬНО, потому что каждое отвечает на
свой вопрос. Именно на этом стоял приказ владельца ([ADR-392] решение 3-A):
*«починка одного писателя — это работа, которая выглядит законченной и ничего не
меняет, а такие починки опаснее, чем отсутствие починки»*. Тест с одним звеном
подтвердил бы ровно такую починку.

Каждая порванная ветка — ВОСПРОИЗВЕДЕНИЕ настоящей аварии, а не выдумка:

* звено 1 — правило `cycle_date` как ключа замены (замер ADR-314: 206 прогонов
  вне журнала на 17 днях; ADR-383: единственный ACT за сорок дней стёрт);
* звено 2 — вторая копия того же правила у читателя (замер
  `run_identity_key_price`, заказ #602/G16: не менее 25 читателей из 108
  схлопывали день САМИ, среди них сам критерий взвода);
* звено 3 — «дописывать всегда», то есть размен дефекта на удвоение знаменателя;
* звено 4 — форвардный горизонт, посчитанный в ЗАПИСЯХ при объявленных ДНЯХ.

Литеральных дат в файле нет ни одной: записи стенда строятся ОТ ЭПОХИ и дата в
них есть ключ ПОРЯДКА, а не отметка свежести (`.claude/rules/deployment.md`).
"""
# FROZEN-DATE-OK: в файле нет ни одной литеральной даты — стенд строится от эпохи
import json

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.paper_trading import allocation_rationale as ar
from spa_core.paper_trading import shadow_trigger_eval as ste

PROBE = "decision_journal_keeps_every_run"


def _run(monkeypatch=None):
    return ca.run_probe(PROBE)


# ── положительный контроль: целый контур ──────────────────────────────────────

def test_probe_is_green_on_the_whole_contour():
    status, reason = _run()
    assert status == ca.SATISFIED, reason
    # Вердикт назван ЧИСЛАМИ, а не словами: критерий обязан двинуться.
    assert "ACT 0 → 1" in reason, reason


def test_probe_is_registered_and_its_declaration_validates():
    assert PROBE in ca.PROBES
    assert ca.validate_spec(PROBE) is None


# ── звено 1: писатель снова ключует одной датой ───────────────────────────────

def test_writer_keyed_by_date_alone_reddens_the_probe(monkeypatch):
    """Возврат правила ADR-314/383: последний прогон дня стирает предыдущие."""
    def date_keyed(record, data_dir, book_id=None):
        from pathlib import Path
        path = Path(data_dir) / ar.history_filename(book_id)
        date = record.get("cycle_date")
        kept = []
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    kept.append(raw)
                    continue
                if isinstance(obj, dict) and obj.get("cycle_date") == date:
                    continue
                kept.append(raw)
        kept.append(json.dumps(record, sort_keys=True, default=str))
        ar.atomic_save_text("\n".join(kept) + "\n", str(path))
        return len(kept)

    monkeypatch.setattr(ar, "append_rationale_history", date_keyed)
    status, reason = _run()
    assert status == ca.NOT_SATISFIED, reason
    assert "писатель СТЁР прогон дня" in reason, reason


# ── звено 2: вторая копия правила у читателя ──────────────────────────────────

def test_reader_collapsing_by_date_reddens_the_probe(monkeypatch):
    """Починка писателя при живом схлопывании у читателя — «выглядит доставленной»."""
    real = ste.load_history

    def collapsing(data_dir, book_id=None):
        records, bad = real(data_dir, book_id)
        by_date = {}
        for rec in records:          # later line wins (снятое правило)
            by_date[str(rec.get("cycle_date"))] = rec
        return [by_date[d] for d in sorted(by_date)], bad

    monkeypatch.setattr(ste, "load_history", collapsing)
    status, reason = _run()
    assert status == ca.NOT_SATISFIED, reason
    assert "читатель СХЛОПНУЛ день" in reason, reason


def test_reader_collapsing_only_inside_the_judge_still_reddens(monkeypatch):
    """Худший случай: `load_history` честна, а СУДЬЯ схлопывает у себя.

    Отдельное звено от предыдущего: там немела общая дверь, здесь — только
    критерий взвода. Замер заказа #602/G16 нашёл ровно такую форму («не
    ломается, а молча СХЛОПЫВАЕТ»), и без этого теста проба принимала бы за
    починку исправного читателя при неисправном критерии.
    """
    real_forward = ste._forward_days
    real_eval = ste.evaluate_window

    def collapsing_eval(data_dir, **kw):
        real_load = ste.load_history

        def one_per_day(dd, book_id=None):
            records, bad = real_load(dd, book_id)
            by_date = {}
            for rec in records:
                by_date[str(rec.get("cycle_date"))] = rec
            return [by_date[d] for d in sorted(by_date)], bad

        ste.load_history = one_per_day
        try:
            return real_eval(data_dir, **kw)
        finally:
            ste.load_history = real_load

    monkeypatch.setattr(ste, "evaluate_window", collapsing_eval)
    monkeypatch.setattr(ste, "_forward_days", real_forward)
    status, reason = _run()
    assert status == ca.NOT_SATISFIED, reason
    assert "вердикт критерия НЕ ИЗМЕНИЛСЯ" in reason, reason


# ── звено 3: «дописывать всегда» ──────────────────────────────────────────────

def test_writer_appending_always_reddens_the_probe(monkeypatch):
    """Размен дефекта: прогон цел, зато каждый повтор удваивается в знаменателе."""
    def append_always(record, data_dir, book_id=None):
        from pathlib import Path
        path = Path(data_dir) / ar.history_filename(book_id)
        kept = []
        if path.exists():
            kept = [r for r in path.read_text(encoding="utf-8").splitlines()
                    if r.strip()]
        kept.append(json.dumps(record, sort_keys=True, default=str))
        ar.atomic_save_text("\n".join(kept) + "\n", str(path))
        return len(kept)

    monkeypatch.setattr(ar, "append_rationale_history", append_always)
    status, reason = _run()
    assert status == ca.NOT_SATISFIED, reason
    assert "повторная запись ТОГО ЖЕ прогона" in reason, reason


# ── звено 4: горизонт посчитан в ЗАПИСЯХ ──────────────────────────────────────

def test_forward_window_counting_runs_reddens_the_probe(monkeypatch):
    """Прежняя форма `forward[:horizon_days]` — семь ЗАПИСЕЙ вместо семи ДНЕЙ."""
    monkeypatch.setattr(ste, "_forward_days",
                        lambda history, index: history[index + 1:])
    status, reason = _run()
    assert status == ca.NOT_SATISFIED, reason
    assert "вошёл в форвардное окно" in reason, reason


# ── третий исход: прибор не отработал ⇒ никогда не «критерий не выполнен» ─────

def test_instrument_failure_is_unmeasured_not_a_verdict(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("судья недоступен")

    monkeypatch.setattr(ste, "evaluate_window", boom)
    status, reason = _run()
    assert status == ca.UNMEASURED, reason
    assert "стенд журнала не отработал" in reason, reason


# ── контроль ADR-333: вердикт не проходит подстрокой ──────────────────────────

def test_verdict_does_not_pass_by_substring(monkeypatch):
    """`ACTUALLY_HOLD` содержит «ACT» подстрокой и вердиктом ACT не является.

    Без этого контроля проба могла бы считать ACT текстовым поиском, и тогда её
    зелёный свет не значил бы, что критерий увидел вернувшийся прогон.
    """
    real = ca._run_keep_record

    def poisoned(day_index, hour, verdict):
        rec = real(day_index, hour, verdict)
        if verdict == "ACT":
            rec["verdict"] = "ACTUALLY_HOLD"
        return rec

    monkeypatch.setattr(ca, "_run_keep_record", poisoned)
    status, reason = _run()
    assert status != ca.SATISFIED, reason


def test_probe_never_raises_on_a_broken_link(monkeypatch):
    """Порванное звено обязано стать ВЕРДИКТОМ, а не исключением наружу."""
    monkeypatch.setattr(ar, "append_rationale_history",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("диск")))
    status, reason = _run()
    assert status in (ca.NOT_SATISFIED, ca.UNMEASURED), (status, reason)


# ── удержание журнала: потолок обязан связывать в ДНЯХ, а не в строках ────────
#
# Это дефект, внесённый САМОЙ правкой ADR-395 и найденный до доставки. До неё
# строка равнялась дню, поэтому «1000 строк» и означало «1000 дней». Как только
# день несёт несколько прогонов, прежний потолок связывает раньше дневного: при
# наблюдённом максимуме 36 прогонов в день 1000 строк есть 28 дн., то есть
# МЕНЬШЕ 30-дневного окна критерия взвода — окно голодало бы молча.

def test_line_ceiling_never_leaves_half_a_day(tmp_path, monkeypatch):
    """Потолок строк сбрасывает дни ЦЕЛИКОМ: половина дня подделала бы знаменатель.

    День, от которого уцелела часть прогонов, даёт критерию число, зависящее от
    того, ГДЕ пришёлся потолок, и неотличим от дня, в котором прогонов и было
    меньше.
    """
    monkeypatch.setattr(ar, "HISTORY_MAX_LINES", 7)
    monkeypatch.setattr(ar, "HISTORY_MAX_DAYS", 1000)
    for day in range(5):
        for hour in (9, 15, 23):          # ТРИ прогона в каждом дне
            ar.append_rationale_history(
                ca._run_keep_record(day, hour, "HOLD"), tmp_path)
    rows = [json.loads(ln) for ln in
            (tmp_path / ar.history_filename(None)).read_text(encoding="utf-8")
            .splitlines() if ln.strip()]
    per_day = {}
    for r in rows:
        per_day.setdefault(r["cycle_date"], 0)
        per_day[r["cycle_date"]] += 1
    assert rows, "журнал пуст — потолок съел и только что записанный день"
    assert set(per_day.values()) == {3}, (
        f"день уцелел ЧАСТИЧНО: прогонов по дням {per_day} — потолок обрезал "
        f"строками, а не днями")
    assert len(rows) <= 7, per_day


def test_day_ceiling_binds_in_days_not_lines(tmp_path, monkeypatch):
    """При дневном потолке N в журнале ровно N ДНЕЙ, сколько бы прогонов в них ни было."""
    monkeypatch.setattr(ar, "HISTORY_MAX_DAYS", 3)
    monkeypatch.setattr(ar, "HISTORY_MAX_LINES", 8000)
    for day in range(6):
        for hour in (9, 23):
            ar.append_rationale_history(
                ca._run_keep_record(day, hour, "HOLD"), tmp_path)
    rows = [json.loads(ln) for ln in
            (tmp_path / ar.history_filename(None)).read_text(encoding="utf-8")
            .splitlines() if ln.strip()]
    dates = sorted({r["cycle_date"] for r in rows})
    assert len(dates) == 3, dates
    assert len(rows) == 6, "каждый уцелевший день обязан сохранить ОБА прогона"


def test_unreadable_line_survives_day_trimming(tmp_path, monkeypatch):
    """Писатель не вправе удалять то, чего не писал — даже обрезая дни."""
    monkeypatch.setattr(ar, "HISTORY_MAX_DAYS", 1)
    path = tmp_path / ar.history_filename(None)
    path.write_text("{не json\n", encoding="utf-8")
    for day in range(3):
        ar.append_rationale_history(
            ca._run_keep_record(day, 23, "HOLD"), tmp_path)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[0] == "{не json", lines[:2]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
