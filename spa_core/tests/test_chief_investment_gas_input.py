"""Девятый вход CIO — режим цены газа (ADR-183, план читателей карточки активации).

Агент com.spa.gas_price_agent активирован 31.08 и писал в data/gas_price_history.json,
у которого не было НИ ОДНОГО читателя — ровно класс ADR-170 «сторож, который говорит
только в файл, — это файл». Вливание — существующим read_feed-контуром (как книги,
test_chief_investment_books_input.py).

Два теста важнее остальных: (1) режим газа НЕ поднимает постуру — газ-агент advisory,
де-риск не задерживается при любом газе (ADR-168), и утечка «дорого» в постуру стала бы
гейтом через чёрный ход; (2) протухший файл ⇒ UNKNOWN — вчерашний газ хуже честного
«не знаю».
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os

from spa_core.investment_os.agents.chief_investment import ChiefInvestmentAgent
from spa_core.investment_os.harness import UNKNOWN


def _layout(tmp_path):
    data = tmp_path / "data"
    ios = data / "investment_os"
    ios.mkdir(parents=True)
    return data, ios


def _seed_analysts(ios, **artifacts):
    for name, payload in artifacts.items():
        (ios / f"{name}.json").write_text(json.dumps(payload))


def _seed_gas(data, regime="expensive", source="live"):
    entry = {"source": source, "sources_ok": 4, "sources_total": 5}
    if source == "live":
        entry.update({"gwei": 0.126, "regime": regime, "usd_per_leg": 0.078,
                      "advice": "..."})
    else:
        entry["regime"] = "unmeasured"
    (data / "gas_price_history.json").write_text(json.dumps({
        "generated_at": "generated-at-is-inert-here-freshness-is-judged-by-mtime", "advisory": True,
        "eth_usd": {"source": "live", "usd": 2481.0},
        "chains": {"ethereum": entry},
        "history": {},
    }))


def test_gas_regime_reaches_the_house_view(tmp_path):
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    _seed_gas(data, regime="expensive")
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    gas = out["house_view"]["gas"]
    assert isinstance(gas, dict)
    assert gas["chains"]["ethereum"]["regime"] == "expensive"
    assert gas["eth_usd"] == 2481.0
    assert out["coverage"]["gas_input"] == "available"


def test_expensive_gas_does_not_raise_the_posture(tmp_path):
    # «Дорого» — совет по дискреционным ходам, не угроза: постура не меняется.
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    base = ChiefInvestmentAgent(data_dir=ios).analyze()
    _seed_gas(data, regime="expensive")
    with_gas = ChiefInvestmentAgent(data_dir=ios).analyze()
    assert with_gas["house_view"]["overall_posture"] == \
        base["house_view"]["overall_posture"]


def test_missing_gas_file_is_unknown_not_a_crash(tmp_path):
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    assert out["house_view"]["gas"] == UNKNOWN
    assert out["coverage"]["gas_input"] == "unknown"


def test_stale_gas_file_is_unknown_not_yesterdays_number(tmp_path):
    # Протухание судится по mtime файла против max_age 1.5 ч (3 такта агента).
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    _seed_gas(data)
    p = data / "gas_price_history.json"
    old = p.stat().st_mtime - 3 * 3600
    os.utime(p, (old, old))
    out = ChiefInvestmentAgent(data_dir=ios).analyze()
    assert out["house_view"]["gas"] == UNKNOWN


def test_gas_does_not_inflate_analyst_coverage(tmp_path):
    # Покрытие считает семь продукт-агентов; у газа нет артефакта-посредника.
    data, ios = _layout(tmp_path)
    _seed_analysts(ios, market_regime={"combined_posture": "STABLE"})
    n_before = ChiefInvestmentAgent(data_dir=ios).analyze()["coverage"]["n_analysts"]
    _seed_gas(data)
    n_after = ChiefInvestmentAgent(data_dir=ios).analyze()["coverage"]["n_analysts"]
    assert n_after == n_before == 1
