"""Шов «дневной лимит убытка → снимок на диске → отчёт владельцу».

Карточка `inbox-stroka-risk-gate-dnevnogo-limita-ubytka`: витрина вердикта
`DailyLimitsChecker` жила в отключённом скрипте. Витрину перенесли, и её
проверяет `test_daily_report_daily_limits_line.py` — но там ОБЕ стороны шва
пишет тест: снимок собирается руками (`_snapshot(...)`), настоящий гейт не
участвует. Такой набор зелен и при рассогласовании форматов.

Рассогласование — не гипотеза. `spa_core/paper_trading/rebalance_trigger.py`
(RT-03) читает `result["checks"]` как СЛОВАРЬ с ключом `triggered`, а
`DailyLimitsChecker.check` возвращает СПИСОК со `status`; потребитель молча не
срабатывает никогда. Ровно этого сорта поломку тесты на самодельных снимках не
видят.

Здесь снимок пишет НАСТОЯЩИЙ гейт (`check` + `save_result`), а читает
настоящий отчёт. Три состояния, ради которых защита существует:

1. убыток сверх лимита — вердикт доезжает до владельца словами и числом;
2. спокойный день — проходит тихо, без ложной тревоги, но С числом;
3. дневной P&L НЕ ВЫЧИСЛИМ — названо «не измерено», а не выдано за «убытка нет».

Третий пункт фиксирует ровно тот разрыв, который сейчас есть в гейте и НЕ
чинится этим тестом: `check()` при DL-01 = SKIP отдаёт `gate="PASS"` (см.
`test_gate_verdict_alone_cannot_tell_unknown_from_clean`) — то есть цикл в этом
состоянии торгует. Отличить «не знаю» от «чисто» можно СЕГОДНЯ только по
полю `checks[DL-01].status`, и этот тест держит единственную живую тропу, по
которой знание доходит до человека. Смена гейта — money-path, заведена
карточка владельцу.

Время — вход: `now` отчёта берётся от тех же часов, что и `checked_at` снимка,
литеральных дат в файле нет, календарь тест не красит.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.reporting.daily_telegram_report import (
    RISK_LIMITS_FILENAME,
    build_report_data,
    format_daily_message,
)
from spa_core.risk.daily_limits import DailyLimitsChecker

# Аллокация и APY заведомо внутри порогов DL-03/04/05 — предметом теста является
# ТОЛЬКО DL-01, соседние проверки не должны подкрашивать вердикт.
_ALLOC = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "euler_v2": 25_000.0}
_APY = {"aave_v3": 4.0, "compound_v3": 4.2, "euler_v2": 5.0}


def _seam(tmp_path, equity_history):
    """Прогнать НАСТОЯЩИЙ гейт, записать снимок, отдать отчёт владельцу."""
    checker = DailyLimitsChecker()
    result = checker.check(equity_history, _ALLOC, _APY)
    checker.save_result(result, tmp_path)
    now = datetime.now(timezone.utc)
    data = build_report_data(now.strftime("%Y-%m-%d"), data_dir=tmp_path, now=now)
    return result, data, format_daily_message(data)


# ── 1. Превышение дневного лимита ловится и доезжает до владельца ────────────


def test_daily_loss_over_limit_halts_and_reaches_the_owner(tmp_path):
    """−3 % за день (порог 2 %): HALT в гейте И строка HALT в сообщении."""
    result, data, text = _seam(
        tmp_path, [{"close_equity": 100_000.0}, {"close_equity": 97_000.0}]
    )

    assert result["gate"] == "HALT", result
    assert any("DL-01" in r for r in result["halt_reasons"]), result

    assert data["daily_limits"]["gate"] == "HALT", data["daily_limits"]
    assert "Daily limits: HALT" in text, text
    assert "DL-01 Daily Loss" in text, text
    assert "3.00%" in text, text


# ── 2. Нормальный день проходит молча ───────────────────────────────────────


def test_calm_day_passes_quietly_but_with_the_number(tmp_path):
    """Прибыльный день: ни HALT, ни WARN — и всё-таки измеренное число."""
    result, data, text = _seam(
        tmp_path, [{"close_equity": 100_000.0}, {"close_equity": 100_020.0}]
    )

    assert result["gate"] == "PASS", result
    assert result["halt_reasons"] == [] and result["warn_reasons"] == [], result

    assert data["daily_limits"]["gate"] == "PASS"
    assert data["daily_limits"]["dl01"]["status"] == "PASS"
    assert "Daily limits (DL-01..05): PASS" in text, text
    assert "daily change +0.02%" in text, text
    assert "HALT" not in text, text


# ── 3. Невычислимый P&L — отказ, а не тишина ────────────────────────────────


def test_uncomputable_pnl_is_named_not_measured_never_a_clean_zero(tmp_path):
    """Бары без значения эквити: DL-01 = SKIP, и это ВИДНО человеку.

    Проверяется отрицанием того, что было бы враньём: числа «0.00 %» в строке
    дневного лимита быть не должно — убытка не «нет», он НЕ ИЗМЕРЕН.
    """
    for name, history in {
        "истории нет вовсе": [],
        "единственный бар": [{"close_equity": 100_000.0}],
        "бары без ключа эквити": [{"nav": 100_000.0}, {"nav": 90_000.0}],
        "предыдущее закрытие = 0": [{"close_equity": 0.0}, {"close_equity": 50_000.0}],
    }.items():
        target = tmp_path / name
        target.mkdir()
        result, data, text = _seam(target, history)

        dl01 = next(c for c in result["checks"] if c["id"] == "DL-01")
        assert dl01["status"] == "SKIP", f"{name}: {dl01}"
        assert dl01["value"] is None, f"{name}: {dl01}"

        assert data["daily_limits"]["dl01"]["status"] == "SKIP", name
        assert "daily loss: not measured (SKIP)" in text, f"{name}\n{text}"
        assert "daily loss 0.00%" not in text, f"{name}\n{text}"


def test_gate_verdict_alone_cannot_tell_unknown_from_clean(tmp_path):
    """ЗАМЕР текущего разрыва, а не одобрение его.

    Слово `gate` для «P&L не вычислим» и для «убытка нет» СЕГОДНЯ одно и то же
    (`PASS`), поэтому потребитель, читающий только `gate`, не отличает одно от
    другого — цикл в этом состоянии торгует. Тест держит замер и краснеет, если
    поведение изменится: изменение — money-path и требует решения владельца
    (карточка `owner-decision-dnevnoy-limit-ubytka-schitaet-neizvestn.md`), а не молчаливой
    правки.

    Если гейт научат отказывать, ЭТОТ тест обязан покраснеть первым и быть
    переписан вместе с ADR — так замер не превращается в разрешение.
    """
    unknown, _, _ = _seam(tmp_path / "u", [{"close_equity": 100_000.0}])
    (tmp_path / "c").mkdir(exist_ok=True)
    clean, _, _ = _seam(
        tmp_path / "c", [{"close_equity": 100_000.0}, {"close_equity": 100_020.0}]
    )

    assert unknown["gate"] == clean["gate"] == "PASS"
    assert unknown["halt_reasons"] == clean["halt_reasons"] == []
    assert unknown["warn_reasons"] == clean["warn_reasons"] == []
    # ...и единственное, что их различает, — статус самой проверки.
    u01 = next(c for c in unknown["checks"] if c["id"] == "DL-01")["status"]
    c01 = next(c for c in clean["checks"] if c["id"] == "DL-01")["status"]
    assert (u01, c01) == ("SKIP", "PASS")


# ── Шов: формат, который пишет гейт, должен читаться потребителем ───────────


def test_snapshot_on_disk_matches_what_the_report_reads(tmp_path):
    """Файл на диске — тот самый контракт, по которому живёт витрина."""
    _seam(tmp_path, [{"close_equity": 100_000.0}, {"close_equity": 99_990.0}])
    doc = json.loads((tmp_path / RISK_LIMITS_FILENAME).read_text(encoding="utf-8"))

    assert isinstance(doc.get("checks"), list), "витрина читает checks как список"
    assert {c["id"] for c in doc["checks"]} >= {"DL-01", "DL-02"}
    assert isinstance(doc.get("checked_at"), str) and doc["checked_at"]
    assert doc["gate"] in ("PASS", "WARN", "HALT")
