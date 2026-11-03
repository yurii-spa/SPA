"""E6.6 (подготовка): отдельная forward-серия spot_frac со своей датой — на синтетической рыночной базе в одноразовом
каталоге. Живой движок, его ledger и боевой каталог не трогаются."""
import json
import math
import sqlite3
from pathlib import Path

import pytest

from spa_core.trading_research import forward_series as fs
from spa_core.trading_research import market_data as md

H, D = 3_600_000, 86_400_000
DAY0 = 1_700_006_400_000 - (1_700_006_400_000 % D)     # полночь UTC; FROZEN-DATE-OK: injected-clock — tick(now_ms=…) от DAY0
CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "docs" / "research_contracts"
                       / "series-spot-frac-k075-band05.json").read_text(encoding="utf-8"))


def _market(path: Path, days: int):
    conn = md.connect(path)
    rows = []
    for h in range(days * 24):
        p = 100.0 * (1 + 0.004 * h / 24) * (1 + 0.05 * math.sin(h / 240))
        rows.append(("BTCUSDT", "1h", DAY0 + h * H, p, p * 1.001, p * 0.999, p * 1.0005, 1.0, "synthetic", DAY0))
    conn.executemany("INSERT INTO candles (symbol, tf, open_time, open, high, low, close, volume, source, fetched_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


@pytest.fixture
def scene(tmp_path):
    db = tmp_path / "market.db"
    _market(db, 260)
    return tmp_path / "series", db


def test_registration_is_its_own_date_and_no_bar_before_it_is_written(scene):
    sdir, db = scene
    reg_ms = DAY0 + 240 * D + 5 * H
    assert fs.tick(sdir, CONTRACT, db, now_ms=reg_ms)["state"] == "REGISTERED"
    r = fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 245 * D + 30 * 60_000)
    rows = [x for x in fs.read_ledger(sdir) if x["kind"] == "bar"]
    assert r["new_bars"] == len(rows) == 4                     # дни 241..244 закрыты; день 240 открылся ДО регистрации
    assert all(x["bar_open_ms"] >= reg_ms for x in rows)
    assert fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 245 * D + 40 * 60_000)["new_bars"] == 0   # идемпотентно
    a = fs.audit(sdir, now_ms=DAY0 + 245 * D + 40 * 60_000)
    assert a["state"] == "OK" and a["expected"] == a["observed"] == 4 and a["gaps"] == 0


def test_late_record_is_marked_not_hidden(scene):
    sdir, db = scene
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 240 * D + 5 * H)
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 243 * D + 10 * H)          # дни 241, 242 записаны позже close + 2 ч
    rows = [x for x in fs.read_ledger(sdir) if x["kind"] == "bar"]
    assert [x["late"] for x in rows] == [True, True]


def test_a_revised_past_candle_is_refused_not_rewritten(scene):
    sdir, db = scene
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 240 * D + 5 * H)
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 244 * D + H)
    before = (sdir / fs.LEDGER).read_bytes()
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER IF EXISTS candles_no_update")             # сцена: пересмотр свечи источником
    for t in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]:
        conn.execute(f"DROP TRIGGER {t}")
    conn.execute("UPDATE candles SET close = close * 1.10 WHERE open_time = ?", (DAY0 + 241 * D + 23 * H,))
    conn.commit()
    conn.close()
    with pytest.raises(fs.SeriesRefused, match="REFUSED_HISTORY_MISMATCH"):
        fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 245 * D + H)
    assert (sdir / fs.LEDGER).read_bytes() == before                    # журнал не тронут


def test_changed_parameters_are_a_new_series_not_an_edit(scene):
    sdir, db = scene
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 240 * D + 5 * H)
    with pytest.raises(fs.SeriesRefused, match="новая серия"):
        fs.tick(sdir, {**CONTRACT, "k": 0.5}, db, now_ms=DAY0 + 242 * D)


def test_a_tampered_ledger_is_refused_and_audit_names_it(scene):
    sdir, db = scene
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 240 * D + 5 * H)
    fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 243 * D + H)
    lines = (sdir / fs.LEDGER).read_text().splitlines()
    row = json.loads(lines[1])
    row["equity"] = row["equity"] * 2
    lines[1] = json.dumps(row, sort_keys=True)
    (sdir / fs.LEDGER).write_text("\n".join(lines) + "\n")
    with pytest.raises(fs.SeriesRefused, match="повреждён"):
        fs.tick(sdir, CONTRACT, db, now_ms=DAY0 + 244 * D + H)
    assert fs.audit(sdir, now_ms=DAY0 + 244 * D + H)["state"] == "BROKEN"
    assert fs.audit(sdir.parent / "nothing", now_ms=DAY0)["state"] == "UNKNOWN"
