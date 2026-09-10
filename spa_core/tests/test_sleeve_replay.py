# FROZEN-DATE-OK: даты здесь — КЛЮЧИ ЗАПИСЕЙ, а не якоря свежести. `cycle_date` архива и
# дата бара истории сверяются ДРУГ С ДРУГОМ (пересечение множеств в `sleeve_replay.replay`);
# ни одна из них не сравнивается с «сейчас», и календарь на вердикт не влияет вовсе.
# Единственное место, где нужен ход времени, — второй день книги, и он делается сдвигом
# ЧАСОВ МОДУЛЯ (`hy.clock.utcnow`), а не переписыванием даты: переписывание разошлось бы
# с архивом, и пересчёт мерил бы артефакт теста.
"""Пересчёт дня книг Balanced/Aggressive из сохранённых входов (ADR-292 п.4, приёмка).

Приёмка ADR-292 требует у советательных книг ту же обвязку, что у консервативной: «пересчёт
кривой из сохранённых входов сходится». Проверяется не на выдуманном архиве, а на том, который
пишет НАСТОЯЩИЙ цикл: тест гоняет `run_hy_cycle`/`run_lp_cycle` в tmp_path и пересчитывает.

Оффлайн, stdlib, все пути инжектируются. LLM_FORBIDDEN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.audit import sleeve_inputs_archive as archive
from spa_core.audit import sleeve_replay
from spa_core.paper_trading import sleeve_book


def _rows(*pairs):
    return [{"protocol": n, "apy_pct": a, "apy_source": "live", "tvl_source": "live",
             "tvl_usd": 50_000_000.0, "network": "ethereum"} for n, a in pairs]


def _write_ranking(tmp: Path, *pairs):
    (tmp / "apy_ranking.json").write_text(json.dumps({"by_apy": _rows(*pairs)}), encoding="utf-8")


@pytest.fixture
def hy(monkeypatch, tmp_path):
    import spa_core.paper_trading.hy_cycle as m
    from spa_core.investment_os import directive
    monkeypatch.setattr(m, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", tmp_path / "hy_regime_log.json")
    monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
    monkeypatch.setattr(m, "refresh_hy_regime", lambda *a, **k: "ENTER")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(sleeve_book, "_PEG_HISTORY", tmp_path / "peg_history.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    return m


@pytest.fixture
def lp(monkeypatch, tmp_path):
    import spa_core.paper_trading.lp_cycle as m
    from spa_core.investment_os import directive
    monkeypatch.setattr(m, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(sleeve_book, "_PEG_HISTORY", tmp_path / "peg_history.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    return m


class TestThirdOutcome:
    def test_no_archive_is_unchecked_not_pass(self, tmp_path):
        """Пустой архив, выданный за успех, — самый тихий способ соврать о треке."""
        r = sleeve_replay.replay(tmp_path, "balanced")
        assert r["status"] == "UNCHECKED" and r["days"] == 0
        assert "архива входов" in r["reason"]

    def test_unknown_book_is_named_not_guessed(self, tmp_path):
        r = sleeve_replay.replay(tmp_path, "conservative")
        assert r["status"] == "UNCHECKED" and "unknown book" in r["reason"]

    def test_broken_chain_is_unchecked(self, tmp_path):
        archive.append_record(tmp_path, "balanced",
                              archive.build_record(
                                  book="balanced", cycle_date="2026-09-09", run_ts="t",
                                  open_equity=100.0, close_equity=100.0, book_before=[],
                                  book_after=[], candidates=[], chains={}, prices={},
                                  marks_before={}, daily_yield_usd=0.0, cost_usd=0.0,
                                  mtm_pnl_usd=0.0, accrual_basis="x"), "t")
        p = archive.path_for(tmp_path, "balanced")
        rec = json.loads(p.read_text().strip())
        rec["payload"]["daily_yield_usd"] = 999.0        # подмена задним числом
        p.write_text(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        r = sleeve_replay.replay(tmp_path, "balanced")
        assert r["status"] == "UNCHECKED" and "цепочк" in r["reason"]

    def test_replay_all_worst_of_two_and_unchecked_is_not_success(self, tmp_path):
        r = sleeve_replay.replay_all(tmp_path)
        assert r["status"] == "UNCHECKED"
        assert set(r["books"]) == {"balanced", "aggressive"}


class TestAgainstTheRealCycle:
    def test_balanced_day_re_derives_from_its_own_archive(self, hy, tmp_path):
        _write_ranking(tmp_path, ("maple", 9.5), ("fluid", 8.0))
        hy.run_hy_cycle(dry_run=False)
        r = sleeve_replay.replay(tmp_path, "balanced")
        assert r["status"] == "PASS", r
        assert r["days"] == 1 and r["max_abs_diff_usd"] <= r["tolerance_usd"]
        assert r["chain"]["ok"] is True

    def test_aggressive_day_re_derives_from_its_own_archive(self, lp, tmp_path):
        _write_ranking(tmp_path, ("maple", 9.5), ("fluid", 8.0), ("susde", 7.0))
        lp.run_lp_cycle(dry_run=False)
        r = sleeve_replay.replay(tmp_path, "aggressive")
        assert r["status"] == "PASS", r
        assert r["days"] == 1

    def test_a_tampered_bar_is_caught(self, hy, tmp_path):
        """Положительный контроль: подделанная строка истории обязана краснеть.

        Иначе PASS означал бы только «архив непротиворечив сам себе».
        """
        _write_ranking(tmp_path, ("maple", 9.5), ("fluid", 8.0))
        hy.run_hy_cycle(dry_run=False)
        st = json.loads((tmp_path / "hy_paper_trading.json").read_text())
        st["daily_history"][-1]["equity"] = st["daily_history"][-1]["equity"] + 50.0
        (tmp_path / "hy_paper_trading.json").write_text(json.dumps(st), encoding="utf-8")
        r = sleeve_replay.replay(tmp_path, "balanced")
        assert r["status"] == "FAIL"
        assert r["diffs"] and r["diffs"][0]["delta_usd"] == pytest.approx(50.0, abs=0.01)

    def test_the_replay_does_not_mutate_the_archive_or_the_book(self, hy, tmp_path):
        _write_ranking(tmp_path, ("maple", 9.5), ("fluid", 8.0))
        hy.run_hy_cycle(dry_run=False)
        arch_before = archive.path_for(tmp_path, "balanced").read_bytes()
        book_before = (tmp_path / "hy_paper_trading.json").read_bytes()
        sleeve_replay.replay(tmp_path, "balanced")
        assert archive.path_for(tmp_path, "balanced").read_bytes() == arch_before
        assert (tmp_path / "hy_paper_trading.json").read_bytes() == book_before

    def test_the_archive_is_written_by_the_cycle_at_all(self, hy, tmp_path):
        """Проводка: модуль, который никто не зовёт, — это ADR-259 в чистом виде."""
        _write_ranking(tmp_path, ("maple", 9.5))
        hy.run_hy_cycle(dry_run=False)
        assert archive.path_for(tmp_path, "balanced").is_file()
        rec = archive.read_all(tmp_path, "balanced")[-1]["payload"]
        assert rec["book"] == "balanced"
        assert rec["candidates"] and rec["book_after"]
        assert rec["accrual_basis"] == sleeve_book.ACCRUAL_BASIS


class TestArchiveShape:
    def test_legs_are_stored_verbatim_not_cleaned(self):
        """Пересчёт должен видеть ТЕ ЖЕ значения, что видел цикл, включая отвергнутый мусор."""
        rec = archive.build_record(
            book="balanced", cycle_date="2026-09-09", run_ts="t", open_equity=1.0,
            close_equity=1.0, book_before=[{"protocol": "x", "notional_usd": None, "apy_pct": "мусор"}],
            book_after=[], candidates=[], chains={}, prices={}, marks_before={},
            daily_yield_usd=0.0, cost_usd=0.0, mtm_pnl_usd=0.0, accrual_basis="x")
        assert rec["book_before"][0]["notional_usd"] is None
        assert rec["book_before"][0]["apy_pct"] == "мусор"

    def test_each_book_has_its_own_file_and_event_type(self):
        assert archive.filename_for("balanced") != archive.filename_for("aggressive")
        assert archive.event_type_for("balanced") != archive.event_type_for("aggressive")
        with pytest.raises(ValueError):
            archive.filename_for("conservative")


class TestSnapshotIsTheInputNotTheOutput:
    """Архив обязан хранить ВХОД дня, а не то, во что его превратили считающие функции.

    Мутация «снимать слепок ссылкой вместо копии» долго оставалась незамеченной: `stale`
    пересчитывается при пересчёте, а цены в фикстуре отсутствовали, поэтому подмена ничего не
    меняла. Тест ниже даёт цену — и тогда ссылка утаскивает в архив `mark_price`, записанный
    ПОСЛЕ снимка. Проверять надо не наличие копии в коде, а различимое последствие.
    """

    def test_a_mark_written_after_the_snapshot_never_reaches_the_archive(self, hy, tmp_path):
        _write_ranking(tmp_path, ("maple", 9.5), ("fluid", 8.0))
        (tmp_path / "peg_history.json").write_text(json.dumps({
            "latest": {"statuses": [{"adapter_id": "maple", "current_price": 1.0}]}}),
            encoding="utf-8")
        hy.run_hy_cycle(dry_run=False)
        rec = archive.read_all(tmp_path, "balanced")[-1]["payload"]
        marks_before = rec["marks_before"]
        assert marks_before == {}, "в первый день отметок ещё нет — предпосылка теста не обеспечена"
        for leg in rec["book_after"]:
            assert leg.get("mark_price") is None, (
                f"нога {leg['protocol']} принесла в архив отметку, поставленную ПОСЛЕ слепка — "
                "значит слепок снят ссылкой, а не копией")
        # и сам пересчёт при этом сходится
        assert sleeve_replay.replay(tmp_path, "balanced")["status"] == "PASS"

    def test_the_second_day_carries_the_previous_mark_and_still_re_derives(self, hy, tmp_path):
        """Второй день: отметка есть, движение цены даёт НЕнулевой P&L, пересчёт сходится."""
        import datetime as dt
        _write_ranking(tmp_path, ("maple", 9.5), ("fluid", 8.0))
        (tmp_path / "peg_history.json").write_text(json.dumps({
            "latest": {"statuses": [{"adapter_id": "maple", "current_price": 1.0}]}}),
            encoding="utf-8")
        hy.run_hy_cycle(dry_run=False)
        # Второй день делается СДВИГОМ ЧАСОВ, а не переписыванием уже записанной даты:
        # переписывание разошлось бы с архивом (в нём осталась бы вчерашняя дата цикла),
        # и пересчёт мерил бы артефакт теста, а не поведение книги.
        real_utcnow = hy.clock.utcnow
        hy.clock.utcnow = lambda: real_utcnow() + dt.timedelta(days=1)
        (tmp_path / "peg_history.json").write_text(json.dumps({
            "latest": {"statuses": [{"adapter_id": "maple", "current_price": 0.98}]}}),
            encoding="utf-8")
        try:
            hy.run_hy_cycle(dry_run=False)
        finally:
            hy.clock.utcnow = real_utcnow
        rec = archive.read_all(tmp_path, "balanced")[-1]["payload"]
        assert rec["marks_before"].get("maple") == 1.0
        assert rec["mtm_pnl_usd"] < 0, "депег на 2 % обязан дать отрицательную переоценку"
        r = sleeve_replay.replay(tmp_path, "balanced")
        assert r["status"] == "PASS", r
        assert r["days"] == 2
