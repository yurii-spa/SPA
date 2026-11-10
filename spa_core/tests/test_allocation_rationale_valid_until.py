"""§28 ТЗ «Portfolio CIO», шаг после ADR-972 (G961 п. 2): у ЗАПИСИ решения есть срок.

``valid_until = generated_at + decision_ttl_s`` — запись, не ворота. Три исхода различимы:
срок вычислен · ручки/рождения нет ⇒ ``None`` · поле читается прибором §28 как ``expiry``.
Литеральных дат нет: момент — вход.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from spa_core.analytics import decision_expiry_census as DX
from spa_core.paper_trading import allocation_rationale as AR

BOOK = {"aave_v3": 40_000.0, "maple": 20_000.0}
APY = {"aave_v3": 3.5, "maple": 5.1}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _record(doc: dict) -> dict:
    return AR.build_history_record(doc, apy_pct=APY, apy_sources={k: "live" for k in APY},
                                   current_positions=BOOK, target_positions=BOOK,
                                   capital_usd=100_000.0)


def test_valid_until_is_birth_plus_the_owner_ttl():
    now = _now()
    rec = _record({"generated_at": now.isoformat(), "params": {"decision_ttl_s": 600.0},
                   "cycle_date": now.date().isoformat()})
    assert rec["valid_until"] == (now + dt.timedelta(seconds=600)).isoformat()
    assert rec["decision_id"] == f"adr060-shadow-{now.date().isoformat()}"


def test_missing_dial_gives_none_not_forever():
    now = _now()
    assert _record({"generated_at": now.isoformat(), "params": {}})["valid_until"] is None
    assert _record({"generated_at": now.isoformat(),
                    "params": {"decision_ttl_s": "soon"}})["valid_until"] is None
    assert _record({"generated_at": now.isoformat(),
                    "params": {"decision_ttl_s": -5}})["valid_until"] is None


def test_unparsable_birth_gives_none():
    assert _record({"generated_at": "yesterday", "params": {"decision_ttl_s": 600}})["valid_until"] is None
    assert _record({"params": {"decision_ttl_s": 600}})["valid_until"] is None


def test_shadow_writer_carries_the_dials_and_the_record_derives_its_expiry(tmp_path):
    now = _now()
    doc = AR.write_shadow_rationale(
        data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK, apy_pct=APY,
        apy_sources={k: "live" for k in APY}, tvl_usd={k: 1e9 for k in APY},
        capital_usd=100_000.0, cycle_date=now.date().isoformat(), run_ts=now.isoformat(),
        now=now, write=False)
    assert doc["params"]["decision_ttl_s"] == 600.0
    assert doc["params"]["input_freshness_tolerance_s"] == 60.0
    rec = _record(doc)
    assert rec["valid_until"] == (now + dt.timedelta(seconds=600)).isoformat()


def test_section_28_reader_sees_the_field_as_an_expiry(tmp_path):
    now = _now()
    rec = _record({"generated_at": now.isoformat(), "params": {"decision_ttl_s": 600.0},
                   "cycle_date": now.date().isoformat()})
    assert DX._role_of("valid_until") == "expiry"
    d = tmp_path / "data"
    d.mkdir()
    (d / DX._s25.CARRIER_ARTIFACT[DX.RECORD_CARRIER]).write_text(json.dumps(rec) + "\n",
                                                                  encoding="utf-8")
    r = DX.measure_record_time_fields(str(d), DX.REPO_ROOT)
    assert r["expiry_fields"] == ["valid_until"]
    assert r["owner_example_present"] is True


def test_live_record_on_the_prod_tree_is_named_not_assumed():
    """Живая запись несёт `valid_until` только с первого прогона цикла ПОСЛЕ доставки —
    тест печатает факт, а не требует его: прод-данных из worktree нет по построению."""
    prod = os.environ.get("SPA_PROD_DATA_DIR")
    if not prod:
        return  # нет входа — нечего мерить; это не `skip`, вопрос к прод-данным задаёт прибор §28
    r = DX.measure_record_time_fields(prod, DX.REPO_ROOT)
    assert r["expiry_fields"] is not None
