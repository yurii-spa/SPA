"""spa_core/tests/test_office_opportunities_are_observations.py — карточка ADR-076.2.

Каждый тест здесь — **положительный контроль**: он воспроизводит замер прода
2026-08-09, когда список «возможностей» инвест-офиса состоял из ЛИТЕРАЛОВ, и
краснеет на неисправленном коде.

Что было измерено на живых артефактах в тот день:

* `data/adapter_status.json`: у `aerodrome_usdc_lp` ``live_apy: null``,
  ``tvl_usd: 0.0``, ``tvl_source: "static"`` — фид мёртв целиком; ``apy: 8.5``
  лишь повторяет ``fallback_apy: 8.5``;
* `data/apy_ranking.json`: строка `aerodrome_usdc_lp` с ``apy_pct: 8.5`` стоит
  ВТОРОЙ по risk-adjusted;
* `data/investment_os/chief_investment.json`: все ТРИ верхние возможности
  house_view (`aerodrome_usdc_lp` 8.5 %, `pendle` 8.0 %, `pendle-pt` 8.0 %) —
  литералы, с меткой доказанности L3 и источником «live cycle · DeFiLlama-derived»,
  тогда как 22 адаптера с настоящими наблюдениями стояли ниже. Оркестратор читает
  этот файл каждый цикл (`scripts/consume_office_reports.py`).

Отдельная находка того же замера, тоже закреплённая здесь: цепочка
``apy or fallback_apy`` глотает наблюдённый **ноль** (ложен в булевом смысле) и
подставляет литерал — `stusd` наблюдён 0.0 %, а напечатан 6.0 %.

Время в фикстурах — относительное (`_freshness.ts`), литеральных дат нет: свежесть
рейтинга судится по mtime, и фиксированная дата здесь была бы бомбой замедленного
действия (`.claude/rules/deployment.md`).

Границы: чистые sandbox-файлы, сети нет, LLM нет, прод-`data/` не читается и не пишется.

ИЗМЕНЕНО НАМЕРЕННО (инв. #16, цикл #451; обоснование — в журнале `docs/journal/2026-W36.md`).
Ожидаемое ИМЯ протокола в трёх проверках изменено `pendle-pt` → `pendle_pt_susde`. Это не
ослабление: проверяемое ПОВЕДЕНИЕ то же (legacy-блок без `live_apy` уходит как `unchecked`,
литерал 8.0 % в возможности не попадает и отказ назван), сменился ровно идентификатор строки.
Производитель канонизирует объявленный блоком `protocol_key` через `adapters.tier_map._ALIASES`
(`_canonical_key`, введён 29.08 намеренно: дубль `pendle-pt` с литералом 8.0 % входил вторым
экземпляром протокола в расчёты ТРЁХ потребителей `by_apy`, давая 33 строки при 30 протоколах).
Тест отстал от этой починки и краснел на `origin/main` **два цикла подряд** (#450, #451),
причём одна из трёх проверок (`"pendle-pt" not in picks`) успела стать ВАКУУМНОЙ — искомого
имени в списке не было уже никогда, и утверждение перестало проверять что-либо. Переименование
её ВОССТАНАВЛИВАЕТ. Входная фикстура (`protocol_key: "pendle-pt"`) намеренно НЕ тронута: именно
её канонизация и является предметом.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

from spa_core.adapters.apy_aggregator import (
    APY_SOURCE_FALLBACK,
    APY_SOURCE_FALLBACK_OVER_OBSERVED,
    APY_SOURCE_LIVE,
    APY_SOURCE_UNCHECKED,
    APYAggregator,
)
from spa_core.investment_os.agents.chief_investment import ChiefInvestmentAgent
from spa_core.investment_os.agents.stablecoin_yield import StablecoinYieldAgent
from spa_core.investment_os.harness import UNKNOWN
from spa_core.tests._freshness import ts


# ── фикстура: срез прода 2026-08-09, четыре разных провенанса ────────────────

def _status_doc() -> dict:
    """`adapter_status.json` формы прода: по одному представителю каждого класса."""
    stamp = ts(hours_ago=0.5)
    return {
        "schema_version": 2,
        "generated_at": stamp,
        "adapters": {
            # 1. фид мёртв целиком — число это fallback_apy (aerodrome, дословно)
            "aerodrome_usdc_lp": {
                "display_name": "Aerodrome Finance USDC/USDT LP (Base)",
                "apy": 8.5, "live_apy": None, "live_apy_fresh": False,
                "fallback_apy": 8.5, "tvl_usd": 0.0, "tvl_source": "static",
                "tier": 2, "chain": "base", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
            # 2. настоящее наблюдение + живой TVL (moonwell_base, дословно)
            "moonwell_base": {
                "display_name": "Moonwell Finance Base",
                "apy": 8.4035, "live_apy": 8.4035, "live_apy_fresh": True,
                "fallback_apy": 5.5, "tvl_usd": 1352202.0, "tvl_source": "live",
                "tier": 2, "chain": "base", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
            # 3. наблюдён НОЛЬ, напечатан литерал (stusd, дословно)
            "stusd": {
                "display_name": "Angle Staked USDA (stUSD)",
                "apy": 0.0, "live_apy": 0.0, "live_apy_fresh": False,
                "fallback_apy": 6.0, "tvl_usd": 2e8, "tvl_source": "static",
                "tier": 2, "chain": "ethereum", "per_protocol_cap": 0.2,
                "active": True, "last_updated": stamp,
            },
        },
        # 4. legacy-блок верхнего уровня: поля live_apy нет, провенанс не измерить
        "pendle_pt": {"apy": 8.0, "tier": "T2", "chain": "ethereum",
                      "protocol_key": "pendle-pt"},
    }


def _ranking(tmp_path: Path) -> Path:
    """Рейтинг, собранный производителем из этой фикстуры (как в проде)."""
    (tmp_path / "adapter_status.json").write_text(
        json.dumps(_status_doc()), encoding="utf-8")
    path = tmp_path / "apy_ranking.json"
    APYAggregator.load(tmp_path).save_ranking(path)
    return path


def _row(path: Path, protocol: str) -> dict:
    """Строка рейтинга по КАНОНИЧЕСКОМУ имени протокола.

    ``next`` без ``default`` бросал голый ``StopIteration``, и внутри генератора
    он превращался в ``RuntimeError: generator raised StopIteration`` — падение,
    которое не называет НИ искомого имени, НИ того, что реально лежит в файле.
    Именно так выглядела авария 29.08 (канонизация ключей переименовала строку):
    три теста покраснели, и ни один не сказал, какое имя теперь у строки.
    """
    doc = json.loads(path.read_text())
    rows = doc["by_risk_adjusted"]
    for r in rows:
        if r["protocol"] == protocol:
            return r
    raise AssertionError(
        f"в by_risk_adjusted нет строки {protocol!r}; есть: "
        f"{sorted(r['protocol'] for r in rows)}. Если производитель переименовал "
        f"протокол намеренно (см. _canonical_key), обнови ОЖИДАНИЕ, а не проверку")


# ── производитель: провенанс каждой строки ───────────────────────────────────

def test_dead_feed_row_is_labelled_a_literal_not_an_observation(tmp_path):
    """aerodrome: живого APY нет ⇒ строка обязана назваться fallback, а не молчать."""
    row = _row(_ranking(tmp_path), "aerodrome_usdc_lp")
    assert row["apy_pct"] == 8.5                      # значение НЕ подменяем
    assert row["apy_source"] == APY_SOURCE_FALLBACK   # но и за наблюдение не выдаём
    assert row["observed_apy_pct"] is None
    assert row["tvl_source"] == "static"              # $0 «размера» — тоже не замер


def test_real_observation_is_labelled_live(tmp_path):
    row = _row(_ranking(tmp_path), "moonwell_base")
    assert row["apy_source"] == APY_SOURCE_LIVE
    assert row["observed_apy_pct"] == 8.4035
    assert row["tvl_source"] == "live"


def test_observed_zero_is_not_laundered_into_its_literal(tmp_path):
    """Наблюдённый ноль доезжает до строки СВОИМ значением, а не литералом.

    ИЗМЕНЕНО НАМЕРЕННО (карточка `inbox-nablyudennyi-nol-podmenyaetsya-literalom`,
    инв. #16 — обоснование здесь, запись в `docs/journal/2026-W33.md`).

    Прежняя редакция закрепляла ПРОМЕЖУТОЧНОЕ состояние: подмена лишь называлась
    меткой (``apy_pct == 6.0`` + ``fallback_over_observed``), а само значение
    намеренно не чинилось — цикл #174 отложил это в отдельную задачу, потому что
    число читают paper-книги. Эта карточка и есть та задача; замер по каждому
    потребителю сделан (журнал W33), поэтому контракт усилён, а не ослаблен:
    теперь проверяется, что ноль доезжает ЗНАЧЕНИЕМ.

    Положительный контроль: вернуть цепочку ``apy or fallback_apy or 0.0`` —
    тест краснеет на первой же строке.
    """
    row = _row(_ranking(tmp_path), "stusd")
    assert row["apy_pct"] == 0.0                   # наблюдение, а не литерал 6.0
    assert row["apy_source"] == APY_SOURCE_LIVE    # и это честно названо
    assert row["observed_apy_pct"] == 0.0
    # Литерал не «спрятался» в производную величину: risk-adjusted тоже нулевой.
    assert row["risk_adjusted_apy"] == 0.0


def test_the_literal_wins_only_where_there_is_no_observation(tmp_path):
    """Обратная сторона: без наблюдения литерал остаётся — и остаётся НАЗВАННЫМ.

    Починка обязана быть узкой. Если бы «наблюдение побеждает литерал» задело
    строку, где наблюдения нет вовсе, мы бы обнулили живой рейтинг целиком —
    ошибка дороже исходной. aerodrome: ``live_apy: null`` ⇒ 8.5 остаётся.
    """
    row = _row(_ranking(tmp_path), "aerodrome_usdc_lp")
    assert row["apy_pct"] == 8.5
    assert row["apy_source"] == APY_SOURCE_FALLBACK
    assert row["observed_apy_pct"] is None


def test_the_substitution_class_still_has_a_judge(tmp_path):
    """Наш производитель подмену больше не порождает — но классификатор ЖИВ.

    Сторож, потерявший единственный известный источник улова, не становится
    ненужным: файл рейтинга на диске мог быть собран версией ДО этой починки
    (самолечится за один цикл), и всё это время подмена обязана называться, а не
    приниматься за наблюдение. Судим напрямую, минуя производителя.
    """
    from spa_core.adapters.apy_aggregator import _apy_provenance

    stale_row = {"live_apy": 0.0, "apy": 0.0, "fallback_apy": 6.0}
    assert _apy_provenance(stale_row, 6.0) == (APY_SOURCE_FALLBACK_OVER_OBSERVED, 0.0)
    assert _apy_provenance(stale_row, 0.0) == (APY_SOURCE_LIVE, 0.0)


def test_legacy_toplevel_block_is_unchecked_not_live(tmp_path):
    """У legacy-блока нет `live_apy` ⇒ честный ответ «не измерено», не «наблюдение»."""
    row = _row(_ranking(tmp_path), "pendle_pt_susde")
    assert row["apy_source"] == APY_SOURCE_UNCHECKED


def test_only_the_laundered_number_moves(tmp_path):
    """Двинулось РОВНО одно число — то, которое было подменено. Остальные нетронуты.

    ИЗМЕНЕНО НАМЕРЕННО (инв. #16; было `test_provenance_does_not_move_a_single_number`,
    обоснование — в журнале `docs/journal/2026-W33.md`).

    Прежняя редакция закрепляла аддитивность цикла #174 («ни одно число не
    двинулось») — верное свойство ДЛЯ ТОЙ правки, которая только расставляла метки.
    Эта карточка двигает число намеренно и ровно одно. Проверка не снята, а
    ПЕРЕНАЦЕЛЕНА: она по-прежнему ловит расползание правки на чужие строки —
    ровно тот риск, ради которого писалась (paper-книги, отчёты, capital_efficiency
    читают этот же файл). Ослаблением это не является: множество «что не должно
    двигаться» уменьшилось на один заведомо ложный элемент, а требование к
    остальным трём осталось точным до знака.
    """
    doc = json.loads(_ranking(tmp_path).read_text())
    assert {r["protocol"]: r["apy_pct"] for r in doc["by_risk_adjusted"]} == {
        "aerodrome_usdc_lp": 8.5, "moonwell_base": 8.4035,
        "stusd": 0.0,            # ← единственное изменение: было 6.0 (литерал)
        "pendle_pt_susde": 8.0,
    }
    assert {r["protocol"]: r["risk_adjusted_apy"] for r in doc["by_risk_adjusted"]} == {
        "aerodrome_usdc_lp": 6.5385, "moonwell_base": 6.4642,
        "stusd": 0.0,            # ← было 4.6154, производная от того же литерала
        "pendle_pt_susde": 6.1538,
    }


# ── потребитель: что офис печатает как возможность ───────────────────────────

def test_office_refuses_to_publish_a_literal_as_an_opportunity(tmp_path):
    """Главный положительный контроль: 8.5 % aerodrome НЕ возможность."""
    out = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path).analyze()
    picks = [p["value"]["protocol"] for p in out["top_stablecoin_yields"]]
    assert "aerodrome_usdc_lp" not in picks
    assert "pendle_pt_susde" not in picks
    assert "stusd" not in picks
    # ушло НЕ молча — причина каждого отказа названа
    excluded = " | ".join(out["excluded_unobserved"])
    assert "aerodrome_usdc_lp(8.5%): apy_not_observed" in excluded
    # stusd уходит по СВОЕЙ причине: раньше его отсеивала подмена (чужие 6.0 %),
    # теперь он приходит с честным нулём и отсеивается за то, что не платит.
    # Причина сменилась вместе с починкой производителя — молчаливо он не исчез
    # ни на секунду, и это ровно то, что здесь проверяется.
    assert "stusd(0.0%): observed_non_positive (pool pays 0.0%)" in excluded
    assert "pendle_pt_susde(8.0%): apy_provenance_unchecked" in excluded


def test_the_observed_pool_is_what_the_office_actually_recommends(tmp_path):
    """Отказ не оставляет офис пустым: наверх выходит настоящее наблюдение."""
    out = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert [p["value"]["protocol"] for p in out["top_stablecoin_yields"]] == ["moonwell_base"]
    assert out["n_observed_conservative"] == 1
    assert out["n_considered_conservative"] == 4      # рассмотрены все четыре


def test_nothing_vanishes_silently(tmp_path):
    """Каждая рассмотренная строка либо возможность, либо названа в отказах."""
    out = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path).analyze()
    assert (len(out["top_stablecoin_yields"]) + len(out["excluded_unobserved"])
            == out["n_considered_conservative"])


def test_ranking_without_provenance_refuses_instead_of_assuming(tmp_path):
    """Рейтинг старой версии ⇒ «не измерено» и отказ, а не «наверное живое».

    Fail-CLOSED в сторону честности: цена ошибки здесь — выдуманная возможность,
    по которой читают. Состояние самолечится за один цикл (файл переписывается),
    и всё это время причина названа, а не скрыта.
    """
    path = _ranking(tmp_path)
    doc = json.loads(path.read_text())
    for key in ("by_apy", "by_risk_adjusted"):
        for row in doc[key]:
            for field in ("apy_source", "observed_apy_pct", "tvl_source"):
                row.pop(field, None)
    path.write_text(json.dumps(doc), encoding="utf-8")

    out = StablecoinYieldAgent(ranking_path=path, data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN
    assert out["top_stablecoin_yields"] == []
    assert out["excluded_unobserved"]
    assert all("apy_provenance_unchecked" in e for e in out["excluded_unobserved"])


# ── проводка: то, что реально читает оркестратор ─────────────────────────────

def test_house_view_the_orchestrator_reads_carries_no_literal(tmp_path):
    """Проверяем ЦЕПЬ до конца: chief_investment.json — файл, который читают.

    Части можно починить по отдельности и оставить систему сломанной: house_view
    берёт возможности готовыми из артефакта аналитика. Тест идёт тем же путём,
    что и прод (аналитик пишет артефакт → chief его читает), поэтому обрыв
    проводки покраснеет здесь, а не «в проде через месяц».
    """
    io_dir = tmp_path / "investment_os"
    io_dir.mkdir()
    StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=io_dir).run()

    house = ChiefInvestmentAgent(data_dir=io_dir).analyze()["house_view"]
    protos = [o["value"]["protocol"] for o in house["top_opportunities"]]
    assert protos == ["moonwell_base"]
    assert "aerodrome_usdc_lp" not in json.dumps(house["top_opportunities"])
