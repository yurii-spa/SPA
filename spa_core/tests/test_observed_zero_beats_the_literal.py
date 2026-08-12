"""spa_core/tests/test_observed_zero_beats_the_literal.py — карточка
`inbox-nablyudennyi-nol-podmenyaetsya-literalom`.

Каждый тест здесь — **положительный контроль**: он воспроизводит замер прода
**2026-08-12** и краснеет на неисправленном коде (цепочка ``apy or fallback_apy
or 0.0`` в `APYAggregator.load`).

Что было измерено на живых артефактах в тот день:

* `data/adapter_status.json`: у `stusd` ``live_apy: 0.0`` (наблюдение ЕСТЬ, и оно —
  ноль), ``fallback_apy: 6.0``; у `wusdm` ``live_apy: 0.0``, ``fallback_apy: 5.0``;
* `data/apy_ranking.json`: строки `stusd` **6.0 %** и `wusdm` **5.0 %** — свои
  литералы, выше настоящих 4.82 % у `maple`;
* `data/capital_efficiency.json` (тревога о простое капитала, ADR-076): обе строки
  стоят ВКЛАДЧИКАМИ пригодной комнаты — ``"stusd(+20% @ 6.0%)"``,
  ``"wusdm(+20% @ 5.0%)"``. Это и есть цена подмены: тревога «капитал ленится,
  вот куда его поставить» указывала на пулы, которые НЕ ПЛАТЯТ.

Почему ноль проглатывался: он ложен в булевом смысле, поэтому ``or`` проходил
мимо наблюдения к литералу. `status_reader` ровно об этом и предупреждает
(«observed 0 % is DATA — a pool really can pay nothing»), и нижней границы у
`_valid_pct` нет намеренно.

Замер по остальным потребителям (журнал W33): начисление paper-книг Engine B/C
НЕ изменилось (HY-медиана 8.0 %, LP 8.5 % до и после — `stusd` стоял на самой
границе полосы ``HY_BAND_MIN`` и её медиану не двигал), офис `stablecoin_yield`
и раньше отсеивал эти строки, теперь отсеивает по честной причине.

Время в фикстурах относительное (`_freshness.ts`) — литеральных дат нет
(`.claude/rules/deployment.md`).

Границы: sandbox-файлы и in-memory dict'ы, сети нет, LLM нет, прод-`data/` не
читается и не пишется; RiskPolicy, kill-switch и живой трек не затронуты —
рейтинг advisory.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import spa_core.monitoring.capital_efficiency as ce
from spa_core.adapters.apy_aggregator import (
    APY_SOURCE_FALLBACK,
    APY_SOURCE_LIVE,
    APYAggregator,
)
from spa_core.tests._freshness import ts


# ── фикстура: срез прода 2026-08-12, дословно ────────────────────────────────

def _status_doc() -> dict:
    stamp = ts(hours_ago=0.5)
    return {
        "schema_version": 2,
        "generated_at": stamp,
        "adapters": {
            # наблюдён НОЛЬ + крупный литерал (stusd, дословно)
            "stusd": {
                "display_name": "Angle Staked USDA (stUSD)",
                "apy": 0.0, "live_apy": 0.0, "fallback_apy": 6.0,
                "tvl_usd": 2e8, "tvl_source": "live", "tier": 2,
                "chain": "ethereum", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
            # то же, второй пострадавший (wusdm, дословно)
            "wusdm": {
                "display_name": "Mountain Protocol wUSDM",
                "apy": 0.0, "live_apy": 0.0, "fallback_apy": 5.0,
                "tvl_usd": 2e8, "tvl_source": "live", "tier": 2,
                "chain": "ethereum", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
            # настоящее наблюдение — контроль в обратную сторону (maple, дословно)
            "maple": {
                "display_name": "Maple Finance",
                "apy": 4.8175, "live_apy": 4.8175, "fallback_apy": 4.82,
                "tvl_usd": 2e8, "tvl_source": "live", "tier": 2,
                "chain": "ethereum", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
            # наблюдения НЕТ вовсе — литерал обязан выжить (aerodrome, дословно)
            "aerodrome_usdc_lp": {
                "display_name": "Aerodrome USDC/USDT LP (Base)",
                "apy": 8.5, "live_apy": None, "fallback_apy": 8.5,
                "tvl_usd": 0.0, "tvl_source": "static", "tier": 2,
                "chain": "base", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
        },
    }


def _rows(tmp_path: Path) -> dict[str, dict]:
    (tmp_path / "adapter_status.json").write_text(
        json.dumps(_status_doc()), encoding="utf-8")
    out = tmp_path / "apy_ranking.json"
    APYAggregator.load(tmp_path).save_ranking(out)
    doc = json.loads(out.read_text())
    return {r["protocol"]: r for r in doc["by_apy"]}


# ── производитель: наблюдение побеждает литерал ──────────────────────────────

def test_the_observed_zero_reaches_the_ranking_as_zero(tmp_path):
    """Главный положительный контроль: 6.0 % у `stusd` — выдумка, и её больше нет."""
    row = _rows(tmp_path)["stusd"]
    assert row["apy_pct"] == 0.0
    assert row["apy_source"] == APY_SOURCE_LIVE
    assert row["observed_apy_pct"] == 0.0


def test_both_measured_victims_are_fixed_not_just_the_named_one(tmp_path):
    """Починка класса, а не строки: `wusdm` в карточке лишь упомянут — проверяем и его."""
    rows = _rows(tmp_path)
    assert rows["wusdm"]["apy_pct"] == 0.0
    assert rows["wusdm"]["apy_source"] == APY_SOURCE_LIVE


def test_a_real_observation_is_untouched(tmp_path):
    """Контроль в обратную сторону: ненулевое наблюдение не пострадало."""
    row = _rows(tmp_path)["maple"]
    assert row["apy_pct"] == 4.8175
    assert row["apy_source"] == APY_SOURCE_LIVE


def test_without_an_observation_the_literal_still_stands(tmp_path):
    """Узость починки: нет `live_apy` ⇒ литерал остаётся и остаётся НАЗВАННЫМ.

    Если бы «наблюдение побеждает литерал» задело эту строку, рейтинг обнулился бы
    целиком — ошибка дороже исходной.
    """
    row = _rows(tmp_path)["aerodrome_usdc_lp"]
    assert row["apy_pct"] == 8.5
    assert row["apy_source"] == APY_SOURCE_FALLBACK
    assert row["observed_apy_pct"] is None


def test_the_dead_pool_no_longer_outranks_the_paying_one(tmp_path):
    """Смысл всей починки одной строкой: 4.82 % `maple` выше, чем ничего.

    В проде 12.08 было наоборот — `stusd` со своим литералом 6.0 % стоял ВЫШЕ.
    """
    rows = _rows(tmp_path)
    assert rows["maple"]["apy_pct"] > rows["stusd"]["apy_pct"]
    assert rows["maple"]["apy_pct"] > rows["wusdm"]["apy_pct"]


# ── потребитель: тревога о простое капитала больше не считает фантом ─────────

def _pos(cap, cash, positions):
    return {"capital_usd": cap, "cash_usd": cash,
            "deployed_usd": cap - cash, "positions": positions}


def _assess_with(monkeypatch, tmp_path):
    """Прогоняем ТУ САМУЮ цепь: производитель → рейтинг → тревога о простое."""
    ranking = {"by_apy": list(_rows(tmp_path).values())}
    pos = _pos(100_000, 20_000, [{"protocol": "aave_v3", "usd": 80_000}])
    monkeypatch.setattr(
        ce, "_load",
        lambda p: pos if str(p).endswith("current_positions.json") else ranking)
    # Атрибуция кэша здесь не предмет проверки — без неё работает legacy-вердикт.
    monkeypatch.setattr(ce, "_cash_attribution", lambda: None)
    return ce.assess()


def test_a_pool_that_pays_nothing_is_not_deployable_headroom(monkeypatch, tmp_path):
    """Замер прода 12.08: «stusd(+20% @ 6.0%)» стоял вкладчиком пригодной комнаты.

    Тревога «капитал ленится, вот куда его поставить» указывала на пул, который не
    платит. После починки такой комнаты нет — ни `stusd`, ни `wusdm` не могут
    попасть во вкладчики, потому что 0 % ниже порога `min_apy`.

    Проводка проверяется НАСКВОЗЬ (adapter_status → APYAggregator → capital_efficiency),
    а не по кусочкам: обе половины можно починить порознь и оставить систему сломанной.
    """
    res = _assess_with(monkeypatch, tmp_path)
    contributors = " | ".join(res["headroom_contributors"])
    assert "stusd" not in contributors
    assert "wusdm" not in contributors


def test_the_forgone_yield_alarm_is_no_longer_built_on_a_phantom(monkeypatch, tmp_path):
    """Число тревоги — из наблюдений: лучший пригодный APY = 4.82 % maple, не 6.0 %.

    `best_qualifying_apy_pct` умножается на свободный капитал и печатается как
    «недополученная доходность». Литерал здесь превращался в вымышленный убыток,
    по которому читают и принимают решения.
    """
    res = _assess_with(monkeypatch, tmp_path)
    assert res["best_qualifying_apy_pct"] == 4.8175


def test_the_paying_pool_is_still_named_as_room(monkeypatch, tmp_path):
    """Тревога не «замолчала» — она стала честной: настоящая комната названа.

    Контроль в обратную сторону: если бы починка гасила тревогу целиком, это была
    бы потеря сигнала, а не восстановление честности.
    """
    res = _assess_with(monkeypatch, tmp_path)
    assert "maple" in " | ".join(res["headroom_contributors"])
