"""Тесты настоящей книги рукавов (sleeve_book) и директивы CIO (ADR-103).

Каждый класс закрывает конкретную поломку или границу мандата:

  • #208 «книга фантомна»: доход начислялся на весь капитал при ПУСТОМ списке
    позиций. Убийца регрессии: пустая книга ⇒ доход РОВНО 0, всегда.
  • Правило владельца 19.08: «идёт paper-тест» — только когда positions_count > 0
    ИЗМЕРЕН. Снапшот-сторона закрыта в scripts/tests.
  • Мандат 21.08 (ADR-103): CIO решает, но fail-closed К НЕЙТРАЛИ — отсутствие /
    протухание advisory-артефакта НЕ меняет поведение цикла; действует только
    СВЕЖАЯ постура ранга 3 (RED/CRITICAL/STRESS), и запрещает она ТОЛЬКО новое
    (hold+reduce разрешены). RiskPolicy и kill-switch не тронуты.

Оффлайн, stdlib, все пути инжектируются. LLM_FORBIDDEN.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.investment_os import directive
from spa_core.paper_trading import sleeve_book

# FROZEN-DATE-OK: injected-clock — _NOW передаётся как now= во ВСЕ вызовы
# load_directive, а generated_at артефакта house-view пишется от ТОГО ЖЕ _NOW
# (_write_cio). Обе стороны сравнения свежести закреплены одним anchor, поэтому
# тест иммунен к календарю (preference #1, .claude/rules/deployment.md). Тесты
# с реальной свежестью (test_cio_red_prevents_opening) используют
# datetime.now(timezone.utc), а не эту литеральную дату.
_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _rows(*pairs, observable: bool = True):
    """Строки ранжирования для тестов.

    ADR-292 (инвариант #16 — изменение НАМЕРЕННОЕ и УЖЕСТОЧАЮЩЕЕ): кандидатом
    становится только НАБЛЮДЁННАЯ строка (`apy_source`/`tvl_source` == "live" и TVL
    выше пола политики). Прежняя фикстура отдавала `{protocol, apy_pct}` без
    провенанса — в новом контракте это «наблюдения не было», и книга такую строку
    не берёт. Фикстура объявляет наблюдение ЯВНО, чтобы тесты продолжали проверять
    ровно то, ради чего написаны (полосу, дедуп, начисление), а не гейт провенанса;
    сам гейт закрыт отдельным классом TestObservability ниже.

    `observable=False` даёт строку БЕЗ провенанса — материал для проверки отказа.
    """
    if not observable:
        return [{"protocol": n, "apy_pct": a} for n, a in pairs]
    return [{"protocol": n, "apy_pct": a, "apy_source": "live",
             "tvl_source": "live", "tvl_usd": 50_000_000.0, "network": "ethereum"}
            for n, a in pairs]


# ── кандидаты ────────────────────────────────────────────────────────────────

class TestCandidates:
    def test_hy_band_and_policy_cap(self):
        cands = sleeve_book.hy_candidates(_rows(
            ("aave", 4.0),        # ниже полосы (6%) — не HY-кандидат
            ("pendle", 14.0),
            ("degen", 31.0),      # выше полисного потолка 30% — не берём вовсе
            ("maple", 9.5),
        ))
        assert [c["protocol"] for c in cands] == ["pendle", "maple"]

    def test_dedup_keeps_best_apy_and_is_deterministic(self):
        rows = _rows(("pendle", 8.0), ("pendle", 12.0), ("maple", 12.0))
        cands = sleeve_book.hy_candidates(rows)
        # равный APY → тай-брейк по имени: детерминизм, а не порядок словаря
        assert cands == [{"protocol": "maple", "apy_pct": 12.0},
                         {"protocol": "pendle", "apy_pct": 12.0}]
        assert cands == sleeve_book.hy_candidates(list(rows))

    def test_lp_candidates_filter_by_name_hint(self):
        cands = sleeve_book.lp_candidates(_rows(
            ("curve_3pool", 7.0), ("aave", 9.0), ("aerodrome", 11.0)))
        assert [c["protocol"] for c in cands] == ["aerodrome", "curve_3pool"]

    def test_garbage_rows_are_ignored(self):
        cands = sleeve_book.hy_candidates(
            [{"protocol": "", "apy_pct": 9}, {"apy_pct": 9}, {"protocol": "x"},
             {"protocol": "y", "apy_pct": True}, {"protocol": "z", "apy_pct": -1}])
        assert cands == []


# ── перестройка книги ────────────────────────────────────────────────────────

class TestRebalance:
    def test_opens_top4_equal_weight(self):
        cands = _rows(("a", 20.0), ("b", 15.0), ("c", 10.0), ("d", 9.0), ("e", 8.0))
        book, opened, closed = sleeve_book.rebalance_book(
            [], [dict(c) for c in cands], 100_000.0, today="2026-08-21")
        assert [p["protocol"] for p in book] == ["a", "b", "c", "d"]
        assert opened == ["a", "b", "c", "d"] and closed == []
        assert all(p["notional_usd"] == 25_000.0 for p in book)

    def test_single_candidate_hits_per_protocol_cap(self):
        book, _, _ = sleeve_book.rebalance_book(
            [], _rows(("solo", 12.0)), 100_000.0, today="2026-08-21")
        # 40% cap: 40k в позиции, 60k честно остаётся кэшем
        assert book[0]["notional_usd"] == 40_000.0

    def test_no_candidates_holds_everything(self):
        """Fail-closed: нет данных — держим, не открываем, не закрываем."""
        held = [{"protocol": "pendle", "apy_pct": 12.0, "notional_usd": 30_000.0}]
        book, opened, closed = sleeve_book.rebalance_book(
            held, [], 100_000.0, today="2026-08-21")
        assert book == held and opened == [] and closed == []

    def test_dropped_from_band_is_closed(self):
        held = [{"protocol": "old", "apy_pct": 9.0, "notional_usd": 30_000.0}]
        book, opened, closed = sleeve_book.rebalance_book(
            held, _rows(("new", 11.0)), 100_000.0, today="2026-08-21")
        assert closed == ["old"] and opened == ["new"]
        assert [p["protocol"] for p in book] == ["new"]

    def test_cio_red_blocks_new_but_keeps_held(self):
        """Граница мандата: RED запрещает НОВОЕ, удержание разрешено."""
        held = [{"protocol": "pendle", "apy_pct": 12.0, "notional_usd": 30_000.0}]
        book, opened, closed = sleeve_book.rebalance_book(
            held, _rows(("pendle", 12.0), ("maple", 10.0)), 100_000.0,
            today="2026-08-21", allow_new=False)
        assert opened == [] and closed == []
        assert [p["protocol"] for p in book] == ["pendle"]


# ── начисление ───────────────────────────────────────────────────────────────

class TestAccrual:
    def test_per_position_at_own_live_apy(self):
        cands = _rows(("a", 10.0), ("b", 20.0))
        book, _, _ = sleeve_book.rebalance_book([], cands, 100_000.0, today="2026-08-21")
        dy, deployed = sleeve_book.accrue_book(book, cands)
        expected = 40_000.0 * 0.10 / 365.0 + 40_000.0 * 0.20 / 365.0
        assert dy == pytest.approx(expected, abs=1e-6)
        assert deployed == 80_000.0

    def test_empty_book_accrues_exactly_zero(self):
        """УБИЙЦА #208: нет позиций ⇒ дохода НЕТ. Никогда и нисколько."""
        dy, deployed = sleeve_book.accrue_book([], _rows(("a", 10.0)))
        assert dy == 0.0 and deployed == 0.0

    def test_protocol_gone_today_accrues_zero_and_marked_stale(self):
        book = [{"protocol": "ghost", "apy_pct": 12.0, "notional_usd": 40_000.0}]
        dy, deployed = sleeve_book.accrue_book(book, _rows(("other", 9.0)))
        assert dy == 0.0 and deployed == 40_000.0
        assert book[0]["stale"] is True

    def test_weighted_apy_zeroes_stale(self):
        book = [{"protocol": "a", "apy_pct": 10.0, "notional_usd": 50_000.0, "stale": False},
                {"protocol": "g", "apy_pct": 30.0, "notional_usd": 50_000.0, "stale": True}]
        assert sleeve_book.book_weighted_apy_pct(book) == 5.0


# ── директива CIO ────────────────────────────────────────────────────────────

def _write_cio(tmp: Path, *, posture="RED", status="ok", generated_at=None):
    d = tmp / "investment_os"
    d.mkdir(parents=True, exist_ok=True)
    ts = (generated_at or _NOW).isoformat()
    (d / "chief_investment.json").write_text(json.dumps({
        "status": status, "house_view": {"overall_posture": posture},
        "generated_at": ts, "is_advisory": True,
    }), encoding="utf-8")


class TestCioDirective:
    def test_no_artifact_is_neutral(self, tmp_path):
        d = directive.load_directive(tmp_path, now=_NOW)
        assert d["no_increase"] is False and "absent" in d["reason"]

    def test_fresh_red_blocks_increase(self, tmp_path):
        _write_cio(tmp_path, posture="RED")
        d = directive.load_directive(tmp_path, now=_NOW)
        assert d["no_increase"] is True and d["posture"] == "RED"

    @pytest.mark.parametrize("p", ["GREEN", "NEUTRAL", "YELLOW"])
    def test_calm_and_watch_postures_do_not_block(self, tmp_path, p):
        """YELLOW — наблюдение, не действие (SENSE часто · ACT редко)."""
        _write_cio(tmp_path, posture=p)
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is False

    def test_stale_red_is_neutral(self, tmp_path):
        """Протухший совет не двигает книгу — как stale-фид не входит в аллокацию."""
        _write_cio(tmp_path, posture="RED",
                   generated_at=_NOW - timedelta(hours=27))
        d = directive.load_directive(tmp_path, now=_NOW)
        assert d["no_increase"] is False and "stale" in d["reason"]

    def test_status_not_ok_is_neutral(self, tmp_path):
        _write_cio(tmp_path, posture="RED", status="UNKNOWN")
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is False

    def test_unreadable_artifact_is_neutral_not_raise(self, tmp_path):
        d = tmp_path / "investment_os"
        d.mkdir()
        (d / "chief_investment.json").write_text("{broken", encoding="utf-8")
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is False

    def test_allows_new_positions_inverse(self, tmp_path):
        _write_cio(tmp_path, posture="RED")
        assert directive.cio_allows_new_positions(tmp_path, now=_NOW) is False


class TestContinuousMovementWatch:
    """ADR-104: CIO следит за КАЖДЫМ движением через непрерывные сенсоры, а не раз
    в день. Движение вниз (intraday tier ≥ SOFT_DERISK или posture ≠ NORMAL) даёт
    no_increase НЕМЕДЛЕННО, обгоняя суточный house-view. DERISK всегда быстро."""

    def _write_intraday(self, tmp, tier, dd=-6.0):
        (tmp / "intraday_equity.json").write_text(
            json.dumps({"tier": tier, "drawdown_pct": dd}), encoding="utf-8")

    def _write_posture(self, tmp, portfolio):
        d = tmp / "monitoring"
        d.mkdir(parents=True, exist_ok=True)
        (d / "risk_posture.json").write_text(
            json.dumps({"portfolio": portfolio, "entries": {}}), encoding="utf-8")

    def test_intraday_soft_derisk_blocks_immediately(self, tmp_path):
        self._write_intraday(tmp_path, "SOFT_DERISK")
        d = directive.load_directive(tmp_path, now=_NOW)
        assert d["no_increase"] is True and "intraday_soft_derisk" in d["reason"]

    def test_intraday_hard_kill_blocks_immediately(self, tmp_path):
        self._write_intraday(tmp_path, "HARD_KILL", dd=-11.0)
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is True

    def test_intraday_none_does_not_block(self, tmp_path):
        self._write_intraday(tmp_path, "NONE", dd=-1.0)
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is False

    def test_rtmr_defensive_posture_blocks(self, tmp_path):
        self._write_posture(tmp_path, "DEFENSIVE")
        d = directive.load_directive(tmp_path, now=_NOW)
        assert d["no_increase"] is True and "rtmr_posture_defensive" in d["reason"]

    def test_rtmr_normal_posture_does_not_block(self, tmp_path):
        self._write_posture(tmp_path, "NORMAL")
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is False

    def test_movement_overrides_calm_daily_houseview(self, tmp_path):
        """Ключ мандата: суточный house-view спокоен (GREEN), но актив дёрнулся —
        CIO решает по ДВИЖЕНИЮ, не по вчерашнему синтезу."""
        _write_cio(tmp_path, posture="GREEN")
        self._write_intraday(tmp_path, "SOFT_DERISK")
        d = directive.load_directive(tmp_path, now=_NOW)
        assert d["no_increase"] is True and d["posture"] == "MOVEMENT_DERISK"

    def test_unreadable_intraday_is_not_movement(self, tmp_path):
        """Нечитаемый сигнал ≠ движение: молчит, не выдумывает просадку."""
        (tmp_path / "intraday_equity.json").write_text("{broken", encoding="utf-8")
        assert directive.load_directive(tmp_path, now=_NOW)["no_increase"] is False


# ── интеграция: hy_cycle строит НАСТОЯЩУЮ книгу ─────────────────────────────

@pytest.fixture
def hy(monkeypatch, tmp_path):
    import spa_core.paper_trading.hy_cycle as m
    monkeypatch.setattr(m, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", tmp_path / "hy_regime_log.json")
    monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
    monkeypatch.setattr(m, "refresh_hy_regime", lambda *a, **k: "ENTER")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    return m


def _write_ranking(tmp: Path, *pairs, observable: bool = True):
    """Живой файл ранжирования для интеграционных тестов циклов.

    Провенанс — по той же причине, что в `_rows` (ADR-292, инвариант #16).
    """
    (tmp / "apy_ranking.json").write_text(json.dumps(
        {"by_apy": _rows(*pairs, observable=observable)}), encoding="utf-8")


class TestHyCycleRealBook:
    def test_bar_holds_real_positions_and_per_position_accrual(self, hy, tmp_path):
        _write_ranking(tmp_path, ("pendle", 14.0), ("maple", 9.5))
        res = hy.run_hy_cycle(dry_run=False)
        assert res["cycle_skipped"] is False
        state = json.loads((tmp_path / "hy_paper_trading.json").read_text())
        bar = state["daily_history"][-1]
        assert bar["positions_count"] == 2
        assert bar["deployed_usd"] == pytest.approx(hy.HY_SEED_EQUITY * 0.8, abs=1.0)
        # ADR-292: базис переименован — «live» в старом имени значило «из файла
        # ранжирования», а не «наблюдено», и это была претензия на провенанс,
        # которую никто не проверял.
        assert bar["accrual_basis"] == "per_position_observed_apy"
        expected_dy = (hy.HY_SEED_EQUITY * 0.4 * 0.14 / 365.0
                       + hy.HY_SEED_EQUITY * 0.4 * 0.095 / 365.0)
        assert bar["daily_yield_usd"] == pytest.approx(expected_dy, abs=0.01)
        # ADR-292: за открытие двух позиций книга ПЛАТИТ, и в этот день нетто
        # отрицательно. До правки кривая книги не могла упасть ни в один день.
        #
        # Меряется КРИВАЯ, а не запись о ней. Первая редакция этого теста
        # проверяла только поля `cost_usd`/`net_pnl_usd` строки истории — и
        # проходила при мутации, снявшей списание с equity: поля считаются
        # отдельно от кривой, поэтому отчёт оставался верным, а книга не платила.
        assert bar["cost_usd"] > 0
        assert bar["net_pnl_usd"] < 0
        assert state["equity"] < hy.HY_SEED_EQUITY
        assert bar["equity"] == pytest.approx(
            hy.HY_SEED_EQUITY + bar["net_pnl_usd"], abs=0.01)
        assert [p["protocol"] for p in state["positions"]] == ["pendle", "maple"]

    def test_no_ranking_means_zero_yield_zero_positions(self, hy, tmp_path):
        """#208 навсегда: нет живых данных ⇒ книга пуста ⇒ equity НЕ растёт."""
        res = hy.run_hy_cycle(dry_run=False)
        assert res["cycle_skipped"] is False
        state = json.loads((tmp_path / "hy_paper_trading.json").read_text())
        bar = state["daily_history"][-1]
        assert bar["positions_count"] == 0
        assert bar["daily_yield_usd"] == 0.0
        assert state["equity"] == pytest.approx(hy.HY_SEED_EQUITY)

    def test_cio_red_prevents_opening(self, hy, tmp_path):
        _write_ranking(tmp_path, ("pendle", 14.0))
        # цикл зовёт директиву с реальными часами — артефакт пишем «сейчас»
        _write_cio(tmp_path / "data", posture="RED",
                   generated_at=datetime.now(timezone.utc))
        res = hy.run_hy_cycle(dry_run=False)
        assert res["cycle_skipped"] is False
        state = json.loads((tmp_path / "hy_paper_trading.json").read_text())
        bar = state["daily_history"][-1]
        assert bar["cio_allowed_new"] is False
        assert bar["positions_count"] == 0
        assert bar["daily_yield_usd"] == 0.0


# ── интеграция: lp_cycle — та же дисциплина ─────────────────────────────────

@pytest.fixture
def lp(monkeypatch, tmp_path):
    import spa_core.paper_trading.lp_cycle as m
    monkeypatch.setattr(m, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    return m


class TestLpCycleRealBook:
    def test_lp_bar_holds_real_positions(self, lp, tmp_path):
        # «Гоу B» (инвариант #16): рукав Aggressive берёт top-2 самых доходных имени
        # полосы (band_candidates + концентрация), а НЕ протоколы с LP-именем. Из
        # aerodrome 11 / aave 9 / curve_3pool 8 попадают два самых доходных.
        _write_ranking(tmp_path, ("curve_3pool", 8.0), ("aerodrome", 11.0), ("aave", 9.0))
        res = lp.run_lp_cycle(dry_run=False)
        assert res.get("kill_switch") is not True
        state = json.loads((tmp_path / "lp_paper_trading.json").read_text())
        bar = state["daily_history"][-1]
        assert bar["positions_count"] == 2          # AGG_MAX_POSITIONS
        assert {p["protocol"] for p in state["positions"]} == {"aerodrome", "aave"}
        assert bar["daily_yield_usd"] > 0
        # ADR-292: издержка перекладки списывается и у Aggressive — меряем КРИВУЮ,
        # а не запись о ней (та же ловушка, что у Balanced выше).
        assert bar["cost_usd"] > 0
        assert state["equity"] < lp.LP_SEED_EQUITY
        assert bar["equity"] == pytest.approx(
            lp.LP_SEED_EQUITY + bar["net_pnl_usd"], abs=0.01)

    def test_lp_no_ranking_zero_yield(self, lp, tmp_path):
        lp.run_lp_cycle(dry_run=False)
        state = json.loads((tmp_path / "lp_paper_trading.json").read_text())
        assert state["daily_history"][-1]["daily_yield_usd"] == 0.0
        assert state["equity"] == pytest.approx(lp.LP_SEED_EQUITY)


# ── проводка в cycle_runner (Step 1d) ────────────────────────────────────────

class TestCycleRunnerWiring:
    """Хук — 8 строк inline в 2800-строчном money-path файле; поведение обеих
    сторон закрыто выше (директива) и существующими тестами soft-derisk-гейта.
    Здесь закрепляется сама ПРОВОДКА: она обязана существовать и включать ровно
    ту же механику (сорванная строка = молча отключённый мандат)."""

    def test_step_1d_wires_directive_into_derisk_gate(self):
        src = (Path(__file__).resolve().parents[1]
               / "paper_trading" / "cycle_runner.py").read_text(encoding="utf-8")
        step = src.split("Step 1d (ADR-103", 1)
        assert len(step) == 2, "Step 1d (директива CIO) исчез из cycle_runner"
        body = step[1].split("Step 2:", 1)[0]
        assert "load_directive" in body
        assert "_derisk_active = True" in body, \
            "директива обязана включать ту же no-increase механику, что SOFT_DERISK"
        assert "cio_directive_no_increase" in body, "активация обязана быть видна в notes"


# ── ADR-292: наблюдаемость, издержки, переоценка ────────────────────────────
#
# Каждый тест ниже воспроизводит замеренную поломку 2026-09-09, а не гипотезу.
# Положительный контроль класса — TestObservability::test_the_2026_09_09_shape:
# он строит ровно тот файл ранжирования, который в тот день профинансировал обе
# книги литералами, и падал бы на коде до правки.

class TestObservability:
    def test_the_2026_09_09_shape(self):
        """Замер 09.09: четыре fallback-константы стояли ВЫШЕ каждой наблюдённой ставки.

        Сортировка по (−apy) поэтому гарантированно набирала книгу из чисел, которых
        никто не видел: pendle_yt_susde 14.0, ethena_susde 12.0, aerodrome 8.5,
        pendle 8.0 — все `apy_source="fallback"`. Лучшая НАБЛЮДЁННАЯ ставка того дня,
        проходящая пол TVL, была maple 4.96.
        """
        rows = [
            {"protocol": "pendle_yt_susde", "apy_pct": 14.0, "apy_source": "fallback",
             "tvl_source": "static", "tvl_usd": 0.0},
            {"protocol": "ethena_susde", "apy_pct": 12.0, "apy_source": "fallback",
             "tvl_source": "static", "tvl_usd": 0.0},
            {"protocol": "maple", "apy_pct": 4.9643, "apy_source": "live",
             "tvl_source": "live", "tvl_usd": 2_729_053_491.0},
        ]
        cands = sleeve_book.book_candidates(rows)
        assert [c["protocol"] for c in cands] == ["maple"]

    def test_missing_provenance_is_a_refusal_not_a_default(self):
        """Строки без apy_source/tvl_source нет в наборе, и причина НАЗВАНА.

        Молчание провенанса читается как отказ: иначе старая фикстура или новый
        адаптер без поля тихо вернули бы прежнее поведение.
        """
        kept, dropped = sleeve_book.observable_rows(_rows(("a", 9.0), observable=False))
        assert kept == []
        assert [d["reason"] for d in dropped] == ["apy_source_missing"]

    def test_tvl_floor_is_the_policy_floor(self):
        rows = _rows(("small", 9.0))
        rows[0]["tvl_usd"] = sleeve_book.MIN_TVL_USD - 1.0
        kept, dropped = sleeve_book.observable_rows(rows)
        assert kept == [] and dropped[0]["reason"].startswith("tvl_below_floor")
        rows[0]["tvl_usd"] = sleeve_book.MIN_TVL_USD
        assert len(sleeve_book.observable_rows(rows)[0]) == 1

    def test_static_tvl_source_does_not_pass(self):
        """`tvl_source="static"` — константа реестра, а не наблюдение (ADR-053)."""
        rows = _rows(("x", 9.0))
        rows[0]["tvl_source"] = "static"
        assert sleeve_book.observable_rows(rows)[0] == []


class TestMoveCost:
    def test_deploying_cash_is_not_halved(self):
        """Односторонний оборот: у развёртывания кэша нет продажи, gross/2 занизил бы вдвое."""
        after = [{"protocol": "a", "notional_usd": 50_000.0},
                 {"protocol": "b", "notional_usd": 50_000.0}]
        c = sleeve_book.book_move_cost([], after, {"a": "ethereum", "b": "ethereum"})
        assert c["turnover_usd"] == pytest.approx(100_000.0)
        assert c["slippage_usd"] == pytest.approx(100_000.0 * 8.0 / 10_000.0)

    def test_matched_swap_pays_one_side(self):
        before = [{"protocol": "a", "notional_usd": 50_000.0}]
        after = [{"protocol": "b", "notional_usd": 50_000.0}]
        c = sleeve_book.book_move_cost(before, after, {})
        assert c["turnover_usd"] == pytest.approx(50_000.0)
        assert sorted(c["touched"]) == ["a", "b"]

    def test_unchanged_book_costs_nothing(self):
        book = [{"protocol": "a", "notional_usd": 10.0}]
        assert sleeve_book.book_move_cost(book, list(book), {})["cost_usd"] == 0.0

    def test_bridge_only_when_more_than_one_chain(self):
        after = [{"protocol": "a", "notional_usd": 10_000.0},
                 {"protocol": "b", "notional_usd": 10_000.0}]
        same = sleeve_book.book_move_cost([], after, {"a": "base", "b": "base"})
        multi = sleeve_book.book_move_cost([], after, {"a": "base", "b": "arbitrum"})
        assert same["bridge_usd"] == 0.0 and multi["bridge_usd"] > 0.0


class TestMarkToMarket:
    def test_zero_coverage_is_not_zero_movement(self):
        """«Не измерено» и «не двигалось» обязаны быть различимы у потребителя.

        Оба дают pnl 0 — различает их ТОЛЬКО coverage_pct, поэтому поле есть в
        каждой строке истории, а не в комментарии.
        """
        book = [{"protocol": "unpriced", "notional_usd": 1000.0}]
        r = sleeve_book.mark_to_market(book, {})
        assert r["pnl_usd"] == 0.0 and r["coverage_pct"] == 0.0
        assert r["unmarked"] == ["unpriced"]

    def test_first_observation_marks_but_does_not_move_the_curve(self):
        book = [{"protocol": "p", "notional_usd": 1000.0}]
        r = sleeve_book.mark_to_market(book, {"p": 1.0})
        assert r["pnl_usd"] == 0.0 and r["coverage_pct"] == 100.0
        assert book[0]["mark_price"] == 1.0

    def test_price_fall_makes_the_book_lose(self):
        """Депег на 2 % на $1000 = −$20. Это и есть день, в который кривая падает."""
        book = [{"protocol": "p", "notional_usd": 1000.0, "mark_price": 1.0}]
        r = sleeve_book.mark_to_market(book, {"p": 0.98})
        assert r["pnl_usd"] == pytest.approx(-20.0)

    def test_partial_coverage_is_reported_as_a_number(self):
        book = [{"protocol": "p", "notional_usd": 750.0},
                {"protocol": "q", "notional_usd": 250.0}]
        r = sleeve_book.mark_to_market(book, {"p": 1.0})
        assert r["coverage_pct"] == pytest.approx(75.0)
        assert r["marked"] == ["p"] and r["unmarked"] == ["q"]
