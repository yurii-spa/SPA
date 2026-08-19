# LLM_FORBIDDEN
"""Турнир ранжирует ИЗМЕРЕННОЕ, а выдуманное — называет.

Что здесь сторожится (замер 2026-08-18, `mass_tournament` на 63 стратегиях)
--------------------------------------------------------------------------
Пометка мока на ВХОДЕ АЛЛОКАЦИИ (`MOCK_APY` → `mock_tainted`) уже работала: 7
строк из 63 названы. Не отвечал никто на ДРУГОЙ вопрос — чем обслужен РЯД
ДОХОДНОСТИ, по которому строка и получила своё место. Замер: 30 строк из 63
частью веса стояли на неизмеренном ряде

  * ``modeled_proxy``      — смоделированный ряд в коде (euler_v2, maple);
  * ``none``               — ряда нет вовсе ⇒ протокол молча даёт РОВНО 0 %
    (`_build_protocol_daily_apy`: `annual_clean = 0.0`) — успокаивающая
    константа вместо отказа (aave_v3_arbitrum, ethena_susde, fluid_usdc_eth,
    pendle_pt_susde);

и при этом весь файл штамповался одной оптимистичной меткой
``data_source = defillama_pit_real`` («лучший из обслуживших»), а все 30 строк
считались доверяемыми. Рейтинг смешивал измеренное с выдуманным и не говорил
об этом.

Положительный контроль — В ОБЕ СТОРОНЫ (правило `deployment.md`)
----------------------------------------------------------------
Сторож, который умеет краснеть только в одну сторону, чинится тем, что режет
всё подряд. Поэтому здесь два класса тестов, и снятие ЛЮБОГО из них красит:

  * `*_excluded_and_named` — строка на неизмеренном ряде обязана быть НАЗВАНА и
    вне доверяемого рейтинга. Краснеет, если пометку снять / порог ослабить.
  * `*_stays_trusted` — строка со 100 % измеренного ряда обязана ранжироваться
    как прежде. Краснеет, если её начали резать «на всякий случай».

Живой сети нет: турнир читает только локальные ряды (`data/historical_apy/`,
`data/bee/`), фиды в тесты не инжектируются, потому что не вызываются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.backtesting import mass_tournament as mass_tournament_module
from spa_core.backtesting.mass_tournament import (
    MEASURED_SERIES_SOURCES,
    MOCK_APY,
    MassTournament,
    return_metrics_refusal,
    series_provenance,
)

MEASURED_PCT = 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Общий прогон (дорогой) — один на модуль
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def tournament(tmp_path_factory):
    out = tmp_path_factory.mktemp("tournament")
    return MassTournament().run(data_dir=str(out))


# ─────────────────────────────────────────────────────────────────────────────
# Единица измерения провенанса — без прогона, мутационно-чувствительно
# ─────────────────────────────────────────────────────────────────────────────

def _bee(*keys):
    return {k: {"apy_series": [{"date": "2024-01-01", "apy": 0.05}]} for k in keys}


def test_modeled_and_unserved_series_are_named_not_averaged_away():
    """Смоделированный ряд и отсутствующий ряд названы ПОИМЁННО.

    Отрицательный полюс контроля: если пометку снять, `series_tainted` станет
    False и тест покраснеет.
    """
    prov = series_provenance(
        {"aave_v3": 0.5, "euler_v2": 0.3, "ethena_susde": 0.2},
        _bee("aave_v3_usdc_eth"), {},
    )
    assert prov["series_tainted"] is True
    assert prov["measured_series_weight_pct"] == pytest.approx(50.0)
    assert "euler_v2:modeled_proxy" in prov["unmeasured_protocols"]
    assert "ethena_susde:none" in prov["unmeasured_protocols"]
    # Молчаливый ноль назван отдельно: это НЕ «низкая доходность», это отказ,
    # который бэктест подменяет нулём.
    assert prov["unserved_protocols"] == ["ethena_susde"]


def test_fully_measured_series_is_not_tainted():
    """Положительный полюс: 100 % наблюдения — НЕ подстановка.

    Краснеет, если порог доверия ужесточить до недостижимого или начать метить
    измеренные ряды заодно с выдуманными.
    """
    prov = series_provenance(
        {"aave_v3": 0.6, "compound_v3": 0.4}, _bee("aave_v3_usdc_eth", "compound_v3_usdc_eth"), {},
    )
    assert prov["series_tainted"] is False
    assert prov["measured_series_weight_pct"] == pytest.approx(MEASURED_PCT)
    assert prov["unmeasured_protocols"] == []
    assert set(prov["apy_series_sources"]) <= set(MEASURED_SERIES_SOURCES)


def test_almost_measured_is_still_tainted():
    """Порог строгий: 99 % измеренного — это НЕ измеренное.

    Контроль против тихого ослабления («ну почти же»): подними допуск — покраснеет.
    """
    prov = series_provenance(
        {"aave_v3": 0.99, "euler_v2": 0.01}, _bee("aave_v3_usdc_eth"), {},
    )
    assert prov["series_tainted"] is True
    assert prov["measured_series_weight_pct"] == pytest.approx(99.0)


def test_empty_allocation_fails_closed():
    """Пустая книга — не «всё измерено», а отказ (fail-CLOSED)."""
    prov = series_provenance({}, {}, {})
    assert prov["series_tainted"] is True
    assert prov["measured_series_weight_pct"] == 0.0


def test_literal_fallback_snapshot_is_not_measurement():
    """Литеральный снимок в коде (`defillama_fallback`) — не наблюдение."""
    # Протокол без реального PIT-файла: иначе PIT-ряд честно перебивает снимок.
    fallback = _bee("ethena_susde")
    prov = series_provenance({"ethena_susde": 1.0}, {}, fallback)
    src = list(prov["apy_series_sources"])
    assert src == ["defillama_fallback"], src
    assert prov["series_tainted"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Живой прогон — обе стороны контроля на настоящем лидерборде
# ─────────────────────────────────────────────────────────────────────────────

def test_unmeasured_rows_are_excluded_and_named(tournament):
    """Строка на неизмеренном ряде: вне доверяемого рейтинга и С ПРИЧИНОЙ."""
    board = tournament["leaderboard"]
    assert board, "лидерборд пуст — сторожу нечего проверять"
    for row in board:
        if row["measured_series_weight_pct"] < MEASURED_PCT:
            assert row["series_tainted"] is True, row["id"]
            assert row["trusted_for_ranking"] is False, (
                f"{row['id']}: {row['measured_series_weight_pct']}% измеренного ряда, "
                "а строка выдана за доверяемую"
            )
            named = [r for r in row["untrusted_reasons"]
                     if r.startswith("apy_series_not_fully_measured:")]
            assert named, f"{row['id']}: подстановка в ряде не НАЗВАНА: {row}"
            # Причина называет протокол и источник, а не просто «не доверяем».
            assert row["unmeasured_protocols"], row["id"]
            for item in row["unmeasured_protocols"]:
                assert ":" in item and item.split(":")[1] not in MEASURED_SERIES_SOURCES


def test_measured_rows_stay_trusted_and_keep_their_ranking(tournament):
    """Строка со 100 % измеренного ряда ранжируется КАК ПРЕЖДЕ.

    Вторая сторона контроля: покраснеет, если новый фильтр начнёт срезать
    честно измеренные строки.
    """
    board = tournament["leaderboard"]
    clean = [
        r for r in board
        if r["measured_series_weight_pct"] == MEASURED_PCT
        and not r["mock_tainted"] and not r["rank_unknown"]
    ]
    assert clean, "ни одной полностью измеренной строки — контроль выродился"
    for row in clean:
        assert row["trusted_for_ranking"] is True, (
            f"{row['id']} измерен на 100 %, но вырезан из доверяемого рейтинга: "
            f"{row['untrusted_reasons']}"
        )
    trusted_ids = [r["id"] for r in tournament["trusted_leaderboard"]]
    assert trusted_ids == [r["id"] for r in board if r["trusted_for_ranking"]]
    assert {r["id"] for r in clean} == set(trusted_ids)

    # Порядок доверяемого рейтинга — тот же net-of-cost APY, что и раньше.
    nets = [r["net_annual_return_pct"] for r in tournament["trusted_leaderboard"]]
    assert nets == sorted(nets, reverse=True), nets
    assert [r["trusted_rank"] for r in tournament["trusted_leaderboard"]] == list(
        range(1, len(nets) + 1))


def test_mock_fed_rows_never_reach_the_trusted_ranking(tournament):
    """Кормление литеральным снимком — по-прежнему дисквалификация (не ослаблено)."""
    for row in tournament["leaderboard"]:
        if row["mock_apy_fed"]:
            assert row["trusted_for_ranking"] is False, row["id"]
            assert "fed_literal_mock_apy_snapshot" in row["untrusted_reasons"]


def test_mock_apy_units_are_named_and_never_rescaled(tournament):
    """Единицы снимка названы, а не «починены» умножением на 100.

    `MOCK_APY` в ДОЛЯХ, часть стратегий документирует вход как `apy_pct` и
    сравнивает с процентными порогами — расхождение стократное. Честный ответ:
    назвать единицы и не пускать такие строки в доверяемый рейтинг; подгонка
    числа без источника была бы той же подстановкой.
    """
    assert all(0.0 < v < 1.0 for v in MOCK_APY.values()), MOCK_APY
    meta = tournament["meta"]
    assert meta["mock_apy_snapshot_units"] == "decimal"
    assert meta["mock_apy_snapshot_is_literal"] is True
    assert "apy_pct" in meta["mock_apy_units_hazard"]


def test_meta_does_not_pass_best_source_off_as_per_row_truth(tournament):
    """`meta.data_source` — лучший из обслуживших; это сказано вслух."""
    meta = tournament["meta"]
    assert meta["data_source_is_best_of_served"] is True
    assert "per-row" in meta["data_source_note"]
    assert meta["series_tainted_count"] == sum(
        1 for r in tournament["leaderboard"] if r["series_tainted"])
    assert meta["series_tainted_strategies"] == sorted(
        r["id"] for r in tournament["leaderboard"] if r["series_tainted"])
    assert meta["trusted_leaderboard_size"] == len(tournament["trusted_leaderboard"])


def test_silently_unserved_protocols_are_listed_not_hidden(tournament):
    """Протокол без ряда даёт РОВНО 0 % — и обязан быть перечислен поимённо."""
    meta = tournament["meta"]
    listed = set(meta["unserved_protocols"])
    from_rows = {p for r in tournament["leaderboard"] for p in r["unserved_protocols"]}
    assert listed == from_rows
    for proto in listed:
        assert meta["protocol_data_sources"].get(proto) == "none", proto


# ─────────────────────────────────────────────────────────────────────────────
# ОТСУТСТВИЕ РЯДА ≠ НОЛЬ (карточка agent-tournament-trustworthy-real-apy, п.3)
# ─────────────────────────────────────────────────────────────────────────────
# Замер 2026-08-19 своим прогоном (63 стратегии): пометка `series_tainted`
# (16–18.08) НАЗЫВАЛА строку, у которой часть книги не имеет ряда доходности
# вовсе, но ЧИСЛО у неё оставалось — бэктест оценивал такой протокол ровно в
# 0 % годовых (`professional_backtest._build_protocol_daily_apy`:
# `annual_clean = 0.0`), и строка занимала место в рейтинге по этому числу.
# 22 строки из 63; крайний случай `s14_arbitrum_radiant` — 80 % веса книги без
# ряда, место 44 с «3.03 % годовых». Число при этом ЗАНИЖЕНО выдуманным нулём,
# то есть рейтинг врал в обе стороны одновременно.
#
# Ниже — два полюса контроля, снятие ЛЮБОГО красит:
#   * `*_refused_*`     — строка без ряда обязана получить ОТКАЗ с названной
#     причиной и уехать в хвост; краснеет, если вернуть подстановку нуля;
#   * `*_still_ranked`  — строка со 100 % измеренного ряда обязана сохранить
#     своё число и место; краснеет, если начать резать «на всякий случай».


def test_missing_series_is_refused_by_name_not_priced_at_zero():
    """Единица правила: ряда нет ⇒ ОТКАЗ с именем протокола (без прогона)."""
    prov = series_provenance(
        {"aave_v3": 0.5, "ethena_susde": 0.5}, _bee("aave_v3_usdc_eth"), {},
    )
    assert return_metrics_refusal(prov) == "apy_series_missing:ethena_susde"


def test_modeled_series_is_not_refused():
    """Положительный полюс единицы: смоделированный ряд — не отсутствующий.

    `modeled_proxy` остаётся `series_tainted` (вне доверяемого рейтинга), но
    отказа НЕ вызывает: там ряд есть и он не ноль. Краснеет, если отказ
    расширить на всё неизмеренное подряд.
    """
    prov = series_provenance(
        {"aave_v3": 0.5, "euler_v2": 0.5}, _bee("aave_v3_usdc_eth"), {},
    )
    assert prov["series_tainted"] is True
    assert return_metrics_refusal(prov) is None


def test_fully_measured_series_is_not_refused():
    """Положительный полюс: 100 % наблюдения — числу ничего не мешает."""
    prov = series_provenance(
        {"aave_v3": 0.6, "compound_v3": 0.4},
        _bee("aave_v3_usdc_eth", "compound_v3_usdc_eth"), {},
    )
    assert return_metrics_refusal(prov) is None


def test_rows_without_series_carry_no_number_at_all(tournament):
    """Прогон: у строки без ряда все метрики доходности ОТКАЗАНЫ (``None``)."""
    refused = [r for r in tournament["leaderboard"] if r["unserved_protocols"]]
    assert refused, "фикстура обязана содержать хотя бы одну такую строку"
    for r in refused:
        assert r["return_metrics_refused"] is True, r["id"]
        for field in (
            "annual_return_pct", "net_annual_return_pct", "sharpe",
            "sortino", "calmar", "max_dd_pct", "total_return_pct",
            "volatility_pct", "win_rate_pct", "final_equity_usd",
        ):
            assert r[field] is None, (r["id"], field, r[field])
        # Причина названа ПОИМЁННО, а не сведена к «недостаточно данных».
        assert r["return_refusal_reason"].startswith("apy_series_missing:")
        for proto in r["unserved_protocols"]:
            assert proto in r["return_refusal_reason"]
        assert r["rank_unknown"] is True
        assert r["trusted_for_ranking"] is False
        assert r["return_refusal_reason"] in r["untrusted_reasons"]
        # Подпись Sharpe отличает «ряда нет» от «вырожденная волатильность».
        assert r["sharpe_display"] == "n/a (ряд не измерен)"
        # Посчитанное с нулём хранится ОТДЕЛЬНО и под предупреждающим именем.
        assert isinstance(r["zero_filled_metrics"], dict)
        assert isinstance(r["zero_filled_metrics"]["annual_return_pct"], float)


def test_rows_without_series_cannot_outrank_a_measured_row(tournament):
    """Отказ уезжает в хвост: ни одна такая строка не стоит выше строки с числом."""
    lb = tournament["leaderboard"]
    ranks_with_number = [
        r["rank"] for r in lb if not r["return_metrics_refused"]
    ]
    ranks_refused = [r["rank"] for r in lb if r["return_metrics_refused"]]
    assert ranks_refused, "фикстура обязана содержать отказы"
    assert min(ranks_refused) > max(ranks_with_number)
    # И в шапку рейтинга такая строка попасть не может.
    assert all(not r["return_metrics_refused"] for r in tournament["top_5"])


def test_measured_rows_keep_their_number_and_place(tournament):
    """Положительный полюс прогона: измеренные строки не тронуты.

    Краснеет, если отказ начнёт задевать книги, у которых ряд есть.
    """
    kept = [r for r in tournament["leaderboard"] if not r["unserved_protocols"]]
    assert kept
    for r in kept:
        assert r["return_metrics_refused"] is False, r["id"]
        assert isinstance(r["annual_return_pct"], float), r["id"]
        assert r["net_annual_return_pct"] == r["annual_return_pct"]
        assert r["zero_filled_metrics"] is None


def test_meta_counts_refusals_by_name(tournament):
    """Мета считает отказы и называет протоколы без ряда — не только их число."""
    meta = tournament["meta"]
    refused = [r for r in tournament["leaderboard"] if r["return_metrics_refused"]]
    assert meta["return_refused_count"] == len(refused)
    assert meta["return_refused_strategies"] == sorted(r["id"] for r in refused)
    assert meta["series_missing_protocols"] == sorted(
        {p for r in tournament["leaderboard"] for p in r["series_missing_protocols"]}
    )
    assert set(meta["series_missing_protocols"]) == set(meta["unserved_protocols"])
    # «net-of-cost» назван честно: издержка — литеральная константа, не замер.
    assert meta["measured_switching_cost_available"] is False
    assert "TX_COST_BPS" in meta["net_of_cost_basis"]


def test_tournament_stays_advisory_and_touches_no_money_path():
    """Турнир — advisory: он не гейтит исполнение и не двигает капитал.

    Инвариант 9 + `.claude/rules/risk-engine.md`. Проверяется по ИСХОДНИКУ
    обоих производителей рейтинга: появление здесь импорта execution / risk /
    allocator красит тест — и это именно тот случай, когда чинить надо не тест.
    """
    import pathlib

    from spa_core.tournament import tournament_engine

    assert tournament_engine.IS_ADVISORY is True
    root = pathlib.Path(mass_tournament_module.__file__).parent.parent
    forbidden = ("spa_core.execution", "spa_core.risk", "spa_core.allocator")
    for rel in ("backtesting/mass_tournament.py",
                "backtesting/strategy_tournament_runner.py"):
        src = (root / rel).read_text(encoding="utf-8")
        for mod in forbidden:
            assert f"import {mod}" not in src, (rel, mod)
            assert f"from {mod}" not in src, (rel, mod)
