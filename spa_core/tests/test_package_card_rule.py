"""The site's ONE card rule (landing/src/lib/package_card.js, ADR-537) judged by the reader's clock.

# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — every case passes its own "now" into cardModel (_run); no wall clock

The module is loaded in node the way the snapshot-view test loads its adapter: imports stripped,
the shelf / constitution / bands injected from the files the site builds from. No ``node`` ⇒
НЕ ИЗМЕРЕНО with the reason (invariant #17), never a pass.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "landing/src/lib"

_HARNESS = r"""
import { readFileSync } from 'node:fs';
import path from 'node:path';
const root = process.argv[2];
const J = (p) => JSON.parse(readFileSync(path.join(root, p), 'utf8'));
const strip = (src) => src.split('\n').filter((l) => !/^\s*import\s/.test(l)).join('\n')
  .replace(/export\s+default\s+NUMBERS;?/, '').replace(/export\s+(function|const)/g, '$1');
const NUMBERS = J('landing/src/data/site_numbers.json');
const sn = new Function('NUMBERS', strip(readFileSync(path.join(root, 'landing/src/lib/site_numbers.js'), 'utf8'))
  + '\nreturn { value, pct, usd, headlineApy, book, threshold };')(NUMBERS);
const card = new Function('NUMBERS', 'value', 'figPct', 'figUsd', 'headlineApy', 'book', 'threshold', 'C', 'TIER_BANDS',
  strip(readFileSync(path.join(root, 'landing/src/lib/package_card.js'), 'utf8'))
  + '\nreturn { effective, cardModel, researchTarget, researchTail };')(
  NUMBERS, sn.value, sn.pct, sn.usd, sn.headlineApy, sn.book, sn.threshold,
  J('landing/src/lib/constitution.json'), J('landing/src/lib/tier_bands.json'));
const cases = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const out = cases.map(([key, rec, now, lang, ci]) => card.cardModel(key, rec, Date.parse(now), lang, ci));
console.log(JSON.stringify(out));
"""


def _run(cases):
    node = shutil.which("node")
    if node is None:
        pytest.fail("НЕ ИЗМЕРЕНО — `node` не найден, правило карточки нечем исполнить")
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / "h.mjs"
        h.write_text(_HARNESS, encoding="utf-8")
        c = Path(tmp) / "c.json"
        c.write_text(json.dumps(cases), encoding="utf-8")
        out = subprocess.run([node, str(h), str(ROOT), str(c)], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.fail(f"НЕ ИЗМЕРЕНО — правило не загрузилось: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


NOW = "2026-01-15T13:00:00Z"            # one hour after the run below; fresh until 14:30
LATE = "2026-01-15T18:00:00Z"           # six hours after the run; past stale_at
DAY_LATER = "2026-01-16T13:00:00Z"


def _case(key, rec, now, lang, ci=None):
    return [key, rec, now, lang, ci]


def _rec(work="RUNNING", data="HEALTHY", stale_at="2026-01-15T14:30:00Z", history="WARMUP", n=1):
    return {"running_version": "aggressive-susde-loop-v1", "mechanic_short_en": "loop", "mechanic_short_ru": "петля",
            "work": {"state": work, "last_run_at": "2026-01-15T12:00:00+00:00"},
            "data": {"state": data}, "decision": {"state": "HOLD", "position_en": "x", "position_ru": "x"},
            "history": {"state": history, "valid_periods": n, "reportable_after": 30, "first_period": "2026-01-15"},
            "mode": {"state": "PAPER_ONLY", "live": "REFUSED"},
            "freshness": {"stale_at": stale_at, "last_successful_run_at": "2026-01-15T12:00:00.123456+00:00"}}


def test_fresh_running_record_is_green_and_expired_one_turns_yellow_by_the_readers_clock():
    fresh, late, late_ru = _run([_case("aggressive", _rec(), NOW, "en"),
                                 _case("aggressive", _rec(), LATE, "en"),
                                 _case("aggressive", _rec(), LATE, "ru")])
    assert fresh["work"]["tone"] == "ok" and fresh["data"]["state"] == "HEALTHY"
    assert late["expired"] and late["work"]["state"] == "UNKNOWN" and late["work"]["tone"] == "warn"
    assert late["data"]["state"] == "STALE" and "6.0 h" in late["data"]["reason"]
    assert late_ru["data"]["reason"] == "последнему наблюдению 6,0 ч"


def test_a_record_without_a_freshness_timestamp_is_never_green():
    (m,) = _run([_case("balanced", _rec(stale_at=None), NOW, "en")])
    assert m["work"]["state"] == "UNKNOWN" and m["work"]["tone"] == "warn"


def test_running_with_stale_or_incomplete_data_is_yellow_not_green():
    a, b = _run([_case("balanced", _rec(data="DEGRADED"), NOW, "en"),
                 _case("balanced", _rec(data="STALE"), NOW, "ru")])
    assert a["work"]["label"] == "Paper · running" and a["work"]["tone"] == "warn"
    assert b["work"]["tone"] == "warn" and b["data"]["tone"] == "warn"


def test_a_confirmed_failure_stays_red_after_expiry_and_a_refusal_is_yellow():
    (m,) = _run([_case("aggressive", _rec(work="FAILED"), DAY_LATER, "en")])
    assert m["work"]["state"] == "FAILED" and m["work"]["tone"] == "bad"
    assert m["live"]["tone"] == "warn" and m["live"]["label"] == "Real capital: refused"


def test_warmup_shows_no_number_and_reportable_conservative_takes_the_shelf_rate():
    shelf = json.loads((ROOT / "landing/src/data/site_numbers.json").read_text(encoding="utf-8"))
    warm, rep = _run([_case("balanced", _rec(), NOW, "en"),
                      _case("conservative", _rec(history="REPORTABLE", n=101), NOW, "en")])
    assert warm["result"]["measured"] is False and "%" not in warm["result"]["main"]
    assert "not published" in warm["risk"]["drawdown"]
    apy = shelf["headline"]["apy"]["value"]
    assert rep["result"]["main"] == f"{apy:.1f}%", "the card prints the shelf's number, not its own"
    assert "not a loss limit" in rep["risk"]["drawdown"]
    assert rep["target"] and "not" not in rep["target"]


def test_a_research_target_always_travels_with_its_tail_and_tiers_and_code_are_shown():
    rec = _rec()
    rec["composition"] = {"state": "MEASURED", "summary_en": "T2: maple · T3: susde", "summary_ru": "T2: maple · T3: susde"}
    ci = {"state": "IN_SYNC", "origin_commit": "40d9cdf66827", "checked_at": NOW}
    agg, cons, no_ci = _run([_case("aggressive", rec, NOW, "en", ci), _case("conservative", _rec(), NOW, "ru", ci),
                             _case("balanced", _rec(), NOW, "ru")])
    bands = json.loads((ROOT / "landing/src/lib/tier_bands.json").read_text(encoding="utf-8"))
    assert agg["target"] and agg["tail"] == bands["aggressive"]["tail_en"], "no target without its tail"
    assert cons["tail"] is None, "Conservative shows its measured drawdown instead"
    assert agg["tiers"] == "T2: maple · T3: susde" and cons["tiers"] == "не измерено"
    assert "40d9cdf66827" in agg["freshness"]["code"] and "не измерена" in no_ci["freshness"]["code"]


def test_the_home_calculator_takes_its_scenario_rate_from_the_band_not_a_literal():
    src = (ROOT / "landing/src/pages/index.astro").read_text(encoding="utf-8")
    assert "a*0.20" not in src and "a*0.2" not in src, "the July literal must not come back"
    assert "data-scenario-pct={aggTargetPct" in src and "researchTarget('aggressive'" in src
    assert "Scenario, not a result" in src and "Сценарий, а не результат" in src


def test_a_paused_book_is_never_green_on_the_card():
    (m,) = _run([_case("aggressive", _rec(work="PAUSED"), NOW, "en")])
    assert m["work"]["state"] == "PAUSED" and m["work"]["tone"] == "warn"
