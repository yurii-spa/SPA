"""S3 E6.2 / TRP-01: пересчёт одного forward-наблюдения по снимку и явные отказы.

Сцена — СИНТЕТИЧЕСКАЯ (своя история свечей и настоящий forward ``advance_candidate`` движка): она проверяет
отказы. Реальный результат на снимке рабочих данных — в evidence S3 (138/138 последних и 300/300 случайных
наблюдений). Ни одна база рабочего дерева не открывается."""
import math
import shutil
import sqlite3

import pytest

from spa_core.trading_research import evidence as ev
from spa_core.trading_research import forward as fw
from spa_core.trading_research import market_data as md
from spa_core.trading_research import replay as R
from spa_core.trading_research.strategies import by_id

H = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % H)   # синтетическое время сцены: каждый бар и now выводятся из T0
SPOT = "ma_cross@v1:BTC:1h:spot_long:98ea5fbfb4"
PERP = "ma_cross@v1:BTC:1h:perp_ls_1x:5325e16301"


def _scene(tmp_path, cid, n=700):
    mpath, epath = tmp_path / "market.db", tmp_path / "evidence.db"
    m = md.connect(mpath)
    px = 30_000.0
    for i in range(n):
        o = px
        px = px * (1 + 0.004 * math.sin(i / 7.0) + 0.002 * math.cos(i / 3.1))
        m.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                  ("BTCUSDT", "1h", T0 + i * H, o, max(o, px) * 1.001, min(o, px) * 0.999, px, 1.0, "test", T0))
    for k in range(0, n, 8):
        m.execute("INSERT INTO funding VALUES (?,?,?,?)", ("BTCUSDT", T0 + k * H, 0.0001, T0))
    m.commit()
    cand = by_id()[cid]
    e = ev.connect(epath)
    ev.register(e, cand.id, cand.def_hash, cand.definition(), now_ms=T0 + 300 * H, code_version="test")
    bars = md.aggregate(md.load_1h(m, "BTCUSDT"), "1h")
    funding = md.funding_series(m, "BTCUSDT")
    added = fw.advance_candidate(e, cand, bars, cand.signal(bars), registered_at_ms=T0 + 300 * H,
                                 now_ms=T0 + n * H, funding=funding, fts=[x[0] for x in funding],
                                 code_version="test", release=None)
    e.commit()
    e.close()
    m.close()
    assert added > 100
    return mpath, epath


@pytest.mark.parametrize("cid", [SPOT, PERP])
def test_every_observation_of_the_scene_replays_ok(tmp_path, cid):
    mpath, epath = _scene(tmp_path, cid)
    seqs = [r[0] for r in sqlite3.connect(epath).execute("SELECT seq FROM observations WHERE candidate_id=?", (cid,))]
    res = [R.replay_observation(mpath, epath, cid, seq=s) for s in seqs]
    assert {r["status"] for r in res} == {R.OK}, [r for r in res if r["status"] != R.OK][:2]
    assert any(r["chain"]["action"] != "HOLD" for r in res)          # цепочка проходит через сделки, не только HOLD


def test_replay_opens_snapshots_read_only(tmp_path):
    mpath, epath = _scene(tmp_path, SPOT)
    before = (mpath.read_bytes(), epath.read_bytes())
    R.replay_observation(mpath, epath, SPOT)
    assert (mpath.read_bytes(), epath.read_bytes()) == before


def _copy_without_triggers(src, dst, table):
    shutil.copy(src, dst)
    c = sqlite3.connect(dst)
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall():
        c.execute(f"DROP TRIGGER {name}")
    c.commit()
    return c


def test_tampered_input_candle_is_a_named_mismatch(tmp_path):
    mpath, epath = _scene(tmp_path, SPOT)
    last = sqlite3.connect(epath).execute("SELECT seq, bar_open_time FROM observations ORDER BY seq DESC LIMIT 1").fetchone()
    c = _copy_without_triggers(mpath, tmp_path / "m2.db", "candles")
    c.execute("UPDATE candles SET close = close * 1.01 WHERE open_time = ?", (last[1] - 5 * H,))
    c.commit()
    r = R.replay_observation(tmp_path / "m2.db", epath, SPOT, seq=last[0])
    assert r["status"] == R.MISMATCH and "data_ref" in r["why"]


def test_missing_input_bar_is_incomplete_not_guessed(tmp_path):
    mpath, epath = _scene(tmp_path, SPOT)
    last = sqlite3.connect(epath).execute("SELECT seq, bar_open_time FROM observations ORDER BY seq DESC LIMIT 1").fetchone()
    c = _copy_without_triggers(mpath, tmp_path / "m2.db", "candles")
    c.execute("DELETE FROM candles WHERE open_time = ?", (last[1],))
    c.commit()
    r = R.replay_observation(tmp_path / "m2.db", epath, SPOT, seq=last[0])
    assert r["status"] == R.INCOMPLETE and "нет в снимке" in r["why"]


def test_tampered_recorded_result_is_a_named_mismatch(tmp_path):
    mpath, epath = _scene(tmp_path, SPOT)
    seq = sqlite3.connect(epath).execute("SELECT seq FROM observations ORDER BY seq DESC LIMIT 1").fetchone()[0]
    c = _copy_without_triggers(epath, tmp_path / "e2.db", "observations")
    c.execute("UPDATE observations SET equity = equity * 1.5 WHERE seq = ?", (seq,))
    c.commit()
    r = R.replay_observation(mpath, tmp_path / "e2.db", SPOT, seq=seq)
    assert r["status"] == R.MISMATCH and "equity" in r["diffs"]


def test_changed_candidate_definition_is_a_different_version(tmp_path):
    mpath, epath = _scene(tmp_path, SPOT)
    c = _copy_without_triggers(epath, tmp_path / "e2.db", "candidates")
    c.execute("UPDATE candidates SET def_hash = 'other' WHERE candidate_id = ?", (SPOT,))
    c.commit()
    r = R.replay_observation(mpath, tmp_path / "e2.db", SPOT)
    assert r["status"] == R.MISMATCH and "другая версия" in r["why"]


def test_unknown_candidate_or_no_observation_is_incomplete(tmp_path):
    mpath, epath = _scene(tmp_path, SPOT)
    assert R.replay_observation(mpath, epath, "nope@v1:BTC:1h:spot_long:0")["status"] == R.INCOMPLETE
    assert R.replay_observation(mpath, epath, SPOT, seq=10**9)["status"] == R.INCOMPLETE
