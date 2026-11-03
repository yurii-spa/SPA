"""S3 E6.6: аудит сохранности forward-истории — положительный контроль на синтетической сцене.

Чистая сцена ⇒ ожидаемое = наблюдённому; удалённое наблюдение, ``late`` и запись задним числом называются."""
import sqlite3

from spa_core.tests.test_trading_research_replay import H, SPOT, T0, _copy_without_triggers
from spa_core.trading_research import evidence as ev
from spa_core.trading_research import forward as fw
from spa_core.trading_research import forward_audit as fa
from spa_core.trading_research import market_data as md
from spa_core.trading_research.strategies import by_id


def _scene(tmp_path, cid, n=700, reg=300):
    """Тик КАЖДЫЙ час, как у живого сервиса: наблюдение пишется в свой тик, а не догоняющей пачкой."""
    m = md.connect(tmp_path / "market.db")
    px = 30_000.0
    for i in range(n):
        o, px = px, px * (1.0005 if i % 13 < 7 else 0.9995)
        m.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                  ("BTCUSDT", "1h", T0 + i * H, o, max(o, px), min(o, px), px, 1.0, "test", T0))
    m.commit()
    cand = by_id()[cid]
    e = ev.connect(tmp_path / "evidence.db")
    ev.register(e, cand.id, cand.def_hash, cand.definition(), now_ms=T0 + reg * H, code_version="test")
    allbars = md.load_1h(m, "BTCUSDT")
    for k in range(reg + 1, n + 1):
        bars = allbars[:k]
        fw.advance_candidate(e, cand, bars, cand.signal(bars), registered_at_ms=T0 + reg * H,
                             now_ms=T0 + k * H + 5 * 60_000, funding=[], fts=[], code_version="test", release=None)
    e.commit()
    e.close()
    m.close()
    return tmp_path / "market.db", tmp_path / "evidence.db"

AS_OF = T0 + 700 * H + 30 * 60_000          # 700 часов истории, «сейчас» — в середине следующего часа


def test_clean_scene_has_every_expected_observation(tmp_path):
    m, e = _scene(tmp_path, SPOT)
    s = fa.summarize(fa.audit(e, m, as_of_ms=AS_OF))
    t = s["totals"]
    assert t["expected"] == t["observed"] > 0
    assert t["late"] == t["gap_flagged"] == t["recorded_after_deadline"] == 0
    assert s["days_with_missing_observations"] == [] and s["market_missing_hours"] == {}


def test_missing_late_and_backdated_observations_are_named(tmp_path):
    m, e = _scene(tmp_path, SPOT)
    c = _copy_without_triggers(e, tmp_path / "e2.db", "observations")
    seqs = [r[0] for r in c.execute("SELECT seq FROM observations ORDER BY seq DESC LIMIT 3")]
    c.execute("DELETE FROM observations WHERE seq=?", (seqs[0],))
    c.execute("UPDATE observations SET late=1 WHERE seq=?", (seqs[1],))
    c.execute("UPDATE observations SET signal_ts_ms = bar_close_time + 5*3600000 WHERE seq=?", (seqs[2],))
    c.commit()
    mc = _copy_without_triggers(m, tmp_path / "m2.db", "candles")
    mc.execute("DELETE FROM candles WHERE open_time=?", (T0 + 690 * H,))
    mc.commit()
    s = fa.summarize(fa.audit(tmp_path / "e2.db", tmp_path / "m2.db", as_of_ms=AS_OF))
    t = {k: s["totals"][k] + s["totals"]["tail_" + k] for k in ("expected", "observed", "late", "recorded_after_deadline")}
    assert t["expected"] - t["observed"] == 1                 # 7 завершённых суток + хвост — вместе
    assert t["late"] == 1 and t["recorded_after_deadline"] == 1
    assert len(s["days_with_missing_observations"]) == 1
    assert sum(v["hours_expected"] - v["hours_present"] for v in s["market_missing_hours"].values()) == 1


def test_observed_days_differ_from_calendar_days_when_a_day_is_empty(tmp_path):
    m, e = _scene(tmp_path, SPOT)
    full = fa.observed_days(e, SPOT)
    c = _copy_without_triggers(e, tmp_path / "e2.db", "observations")
    c.execute("DELETE FROM observations WHERE (bar_close_time - 1) / 86400000 = "
              "(SELECT (MIN(bar_close_time) - 1) / 86400000 + 2 FROM observations)")
    c.commit()
    assert fa.observed_days(tmp_path / "e2.db", SPOT) == full - 1
    assert sqlite3.connect(tmp_path / "e2.db").execute("SELECT COUNT(*) FROM observations").fetchone()[0] > 0
