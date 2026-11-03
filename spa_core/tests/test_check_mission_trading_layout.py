"""S4 K9: харнесс вёрстки пульта — чистая часть (сцены) проверяется без Chrome; сам прогон — check_mission_trading_layout."""
from spa_core.tests import _mission_trading_layout


def _mod():
    return _mission_trading_layout


def test_scenes_cover_real_long_missing_and_network_error():
    m = _mod()
    model = {"capital": {"trading_engines": {"blocks": [{"engine": "spa_trading_research", "title": "a",
                                                         "paper_result": {"rows": [{"id": "x"}]}},
                                                        {"engine": "earn_defi", "title": "b"}]}},
             "owner_view": {"sections": {"work": {"goal": {"steps": [{"title": "s", "last_confirmed": "l"}]}}}}}
    sc = m.scenes(model)
    assert set(sc) == {"real", "long_texts", "missing_engine", "network_error"} and sc["network_error"] is None
    assert m.LONG in sc["long_texts"]["capital"]["trading_engines"]["blocks"][0]["title"]
    assert m.LONG in sc["long_texts"]["owner_view"]["sections"]["work"]["goal"]["steps"][0]["title"]
    assert [b["engine"] for b in sc["missing_engine"]["capital"]["trading_engines"]["blocks"]] == ["spa_trading_research"]
    assert model["capital"]["trading_engines"]["blocks"][0]["title"] == "a", "сцены не портят исходную модель"


def test_missing_chrome_is_not_measured(monkeypatch, tmp_path):
    m = _mod()
    monkeypatch.setattr(m, "CHROME", str(tmp_path / "no-chrome"))
    assert m.main(["--model", str(tmp_path / "x.json")]) == 2
