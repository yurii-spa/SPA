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

from spa_core.backtesting.mass_tournament import (
    MEASURED_SERIES_SOURCES,
    MOCK_APY,
    MassTournament,
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
