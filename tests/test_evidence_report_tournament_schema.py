"""
Цикл #373 (2026-08-24) — секция «турнир стратегий» отчёта о доказательной базе
читает СХЕМУ ПРОИЗВОДИТЕЛЯ, а не выдуманную.

Почему тест такой, какой он есть
================================

`data/tournament_ranking.json` пишут ДВА разных производителя, и они расходятся
и в ключах, и в ЕДИНИЦЕ измерения доходности:

  * ``MultiStrategyRunner.export_results`` →
        {"strategies": [{rank, strategy_id, composite_score,
                         net_apy,          # ДОЛЯ: 0.042 == 4.2 % (так сказал производитель)
                         is_active, days_running}]}
    — именно это лежит в живом файле сегодня;
  * ``TournamentEvaluator.save_ranking`` →
        {"ranking": [{strategy_id, rank, composite_score,
                      metrics: {name, status, realized_apy_pct,  # ПРОЦЕНТ
                                days_observed, ...}}]}
    — имя и статус ВЛОЖЕНЫ в ``metrics``.

До 24.08 `_section2` читал верхнеуровневые ``name`` / ``apy_target`` / ``status``,
которых не пишет НИ ОДИН из двух, и печатал пустое имя, «N/A» и «unknown» в каждой
строке при ЛЮБЫХ настоящих данных. Соседний набор `tests/test_evidence_report.py`
всё это время был зелёным, потому что его фикстура `MINIMAL_TOURNAMENT` —
написанная от руки ТРЕТЬЯ схема, которую тоже не пишет ни один производитель.
Тест сверял копию с копией.

Поэтому здесь документы строятся ПРОИЗВОДИТЕЛЯМИ (`export_results` и
`StrategyResult.to_dict`), а не литералами: если завтра схема производителя
изменится, эти тесты покраснеют, а не продолжат сверять копию с копией.

Положительный контроль
======================
Каждая проверка краснеет на неисправленном модуле:
  * `test_live_producer_rows_are_named` — старый код печатал пустое имя;
  * `test_fraction_apy_is_not_printed_as_zero_percent` — старый код печатал «N/A»,
    а наивная починка (net_apy в процентный слот) напечатала бы «0.04%» вместо
    «4.21%» — занижение в 100 раз;
  * `test_evaluator_nested_metrics_are_read` — старый код не заглядывал в ``metrics``;
  * `test_avg_apy_fallback_reads_producer_keys` — старый код читал ``apy_realized``,
    которого не пишет никто, и запасная ветка была мертва.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
for _p in (_REPO_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import generate_evidence_report as ger  # noqa: E402

from spa_core.paper_trading.multi_strategy_runner import MultiStrategyRunner  # noqa: E402
from spa_core.paper_trading.strategy_registry import (  # noqa: E402
    S0_CONSERVATIVE_T1,
    S1_BALANCED,
)
from spa_core.paper_trading.tournament_evaluator import (  # noqa: E402
    StrategyMetrics,
    StrategyResult,
)


# --------------------------------------------------------------------------- #
# Документы строят САМИ производители — не литералы
# --------------------------------------------------------------------------- #

def _runner_document(tmp_path) -> dict:
    """Настоящий артефакт MultiStrategyRunner (ключ "strategies", net_apy = доля)."""
    runner = MultiStrategyRunner([S0_CONSERVATIVE_T1, S1_BALANCED])
    # Детерминированная карта APY — сеть здесь не нужна и не допускается.
    runner.run_day({"aave_v3": 4.2, "morpho_blue": 6.5, "compound_v3": 3.9})
    out = tmp_path / "tournament_ranking.json"
    runner.export_results(out)
    with open(out, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _evaluator_document() -> dict:
    """
    Настоящий артефакт TournamentEvaluator: сериализация делается его же
    ``StrategyResult.to_dict`` / ``StrategyMetrics.to_dict`` — имя и статус
    оказываются вложенными ровно так, как их пишет производитель.
    """
    metrics = StrategyMetrics(
        strategy_id="S7",
        name="Pendle PT Conservative",
        status="target_met",
        days_observed=12,
        current_equity=100_830.0,
        total_return_pct=0.83,
        realized_apy_pct=7.25,          # ПРОЦЕНТ — так объявлено у производителя
        target_apy_min=6.0,
        target_apy_max=9.0,
        sharpe_ratio=0.96,
        calmar_ratio=6.47,
        ulcer_index=1.3,
        rachev_ratio=None,
        max_drawdown_pct=0.004,
        drawdown_pct=0.0,
        sharpe_ci_lower=None,
        sharpe_ci_upper=None,
        apy_vs_baseline_bps=180.0,
        is_statistically_significant=True,
    )
    result = StrategyResult(
        strategy_id="S7",
        rank=1,
        composite_score=0.81,
        metrics=metrics,
        should_kill=False,
        should_promote=True,
    )
    return {"source": "tournament_evaluator", "ranking": [result.to_dict()]}


# --------------------------------------------------------------------------- #
# 1. Живой производитель: строки названы, а не пусты
# --------------------------------------------------------------------------- #

def test_live_producer_rows_are_named(tmp_path):
    """Каждая строка таблицы несёт идентификатор стратегии производителя."""
    doc = _runner_document(tmp_path)
    ids = [s["strategy_id"] for s in doc["strategies"]]
    assert ids, "производитель не вернул ни одной стратегии — тест бессмысленен"

    out = ger._section2(doc)

    for sid in ids[:5]:
        assert sid in out, f"строка стратегии {sid} не названа: {out}"
    # Старый код давал ровно это: пустое имя, N/A, unknown.
    assert "N/A" not in out
    assert "unknown" not in out


def test_live_producer_days_and_status_are_real(tmp_path):
    """``days_running`` и ``is_active`` доезжают до таблицы, а не подменяются нулём."""
    doc = _runner_document(tmp_path)
    top = doc["strategies"][0]

    out = ger._section2(doc)
    row = [ln for ln in out.splitlines() if top["strategy_id"] in ln][0]

    assert str(top["days_running"]) in row
    assert ("active" if top["is_active"] else "inactive") in row


# --------------------------------------------------------------------------- #
# 2. Единица измерения — по КЛЮЧУ, не по величине числа (контроль на 100×)
# --------------------------------------------------------------------------- #

def test_fraction_apy_is_not_printed_as_zero_percent(tmp_path):
    """
    ``net_apy`` — доля. 0.0421 обязано печататься как 4.21 %, а НЕ как 0.04 %.

    Это положительный контроль на ловушку «починить, подставив net_apy в
    процентный слот»: она занизила бы доходность в 100 раз.
    """
    doc = _runner_document(tmp_path)
    doc["strategies"][0]["net_apy"] = 0.0421      # ключ производителя, значение — доля

    out = ger._section2(doc)

    assert "4.21%" in out, f"доля не переведена в проценты: {out}"
    assert "0.04%" not in out, f"доля напечатана как процент — занижение в 100 раз: {out}"


def test_apy_column_names_which_number_it_carries(tmp_path):
    """Колонка APY обязана называть род числа: net у одного производителя, target у другого."""
    runner_out = ger._section2(_runner_document(tmp_path))
    assert "realized net APY" in runner_out

    evaluator_out = ger._section2(_evaluator_document())
    assert "realized APY" in evaluator_out


# --------------------------------------------------------------------------- #
# 3. Второй производитель: имя и статус вложены в metrics
# --------------------------------------------------------------------------- #

def test_evaluator_nested_metrics_are_read():
    """Имя/статус/APY/дни лежат в ``metrics`` — читатель обязан туда заглянуть."""
    out = ger._section2(_evaluator_document())

    assert "Pendle PT Conservative" in out
    assert "target_met" in out
    assert "7.25%" in out          # realized_apy_pct — уже проценты, без домножения
    assert "12" in out             # days_observed


# --------------------------------------------------------------------------- #
# 4. Отсутствующее поле — прочерк, а не выдуманное значение
# --------------------------------------------------------------------------- #

def test_absent_fields_render_as_dash_not_fabricated():
    """
    Производитель может не дать поля. Тогда в таблице стоит «—»: ни нуля дней,
    ни «unknown»-статуса, которых никто не наблюдал.
    """
    doc = {"strategies": [{"rank": 1, "strategy_id": "S9"}]}

    out = ger._section2(doc)
    row = [ln for ln in out.splitlines() if "S9" in ln][0]

    assert "—" in row, f"отсутствующие поля подменены выдуманными: {row}"
    assert "unknown" not in row
    assert "no APY reported by the producer" in out


def test_empty_document_says_so():
    """Пустой документ — честное «данных ещё нет», а не таблица из прочерков."""
    assert "No strategy data available yet." in ger._section2({})
    assert "No strategy data available yet." in ger._section2({"strategies": []})


# --------------------------------------------------------------------------- #
# 5. Запасная ветка средней доходности читает ключи производителя
# --------------------------------------------------------------------------- #

def test_avg_apy_fallback_reads_producer_keys(tmp_path):
    """
    Когда доказанных дней нет, средний APY берётся у победителя турнира.
    Ветка читала ``apy_realized`` — ключ, которого не пишет ни один производитель,
    — и потому всегда возвращала None.
    """
    doc = _runner_document(tmp_path)
    doc["strategies"][0]["net_apy"] = 0.0421

    empty_evidence = {"days": []}
    value = ger._compute_avg_apy(empty_evidence, doc)

    assert value is not None, "запасная ветка по-прежнему мертва"
    assert value == pytest.approx(4.21, abs=1e-6)


def test_avg_apy_prefers_evidenced_days_over_tournament(tmp_path):
    """
    Обратная сторона: пока есть доказанные дни, турнир в средний APY НЕ лезет.
    Иначе починка запасной ветки тихо подменила бы главное число отчёта.
    """
    doc = _runner_document(tmp_path)
    doc["strategies"][0]["net_apy"] = 0.99      # 99 % — заведомо не наш трек

    evidence = {
        "evidenced_anchor": "2026-06-22",
        "days": [
            {"date": "2026-06-22", "apy_pct": 5.0, "equity_value": 100_000.0, "evidenced": True},
            {"date": "2026-06-23", "apy_pct": 7.0, "equity_value": 100_010.0, "evidenced": True},
        ],
    }
    assert ger._compute_avg_apy(evidence, doc) == pytest.approx(6.0)
