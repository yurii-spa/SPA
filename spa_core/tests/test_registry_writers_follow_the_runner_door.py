"""Два читателя-писателя реестра пишут ЖУРНАЛ в каталог бегуна, а не мимо ключа (ADR-1004, цикл #1123).

Предмет. ADR-1003 поставил дверь у бегуна (`ctx["data_dir"] = str(self.data_dir)`), и замер § 3.2
назвал двоих, у кого ключ ДОЕЗЖАЛ, а запись всё равно шла в умолчание модуля:

* `protocol_defi_yield_duration_mismatch_analyzer` — контекст биндится в `protocols`, а каталог
  читался у параметра `config`; контекстная ветка звала себя с `config=None` ⇒ журнал
  `yield_duration_mismatch_log.json` ложился в `data/` ДЕРЕВА (под песочницей — в прод);
* `yield_volatility_surface_analyzer` — ряд читался из `ctx["data_dir"]` верно, а `_log_result`
  знал только умолчание модуля и `SPA_DATA_DIR` ⇒ при данных журнал
  `yield_volatility_surface_log.json` ушёл бы мимо каталога бегуна.

Что закреплено и в какую сторону (контроль в ОБЕ стороны, ADR-333 — не подстрокой):
* контекстный вызов с ключом ⇒ журнал в каталоге ключа, умолчание модуля НЕ тронуто;
* тот же вызов через НАСТОЯЩИЙ бегун `SignalAggregator(data_dir=…)._run_module` ⇒ журнал в
  каталоге бегуна (исход, а не структура: сцена не читает исходник);
* контекст БЕЗ ключа ⇒ прежнее умолчание модуля (легаси-форма не меняется);
* `config["data_dir"]` сильнее собственного умолчания модуля и сильнее `SPA_DATA_DIR`.

Прод-`data/` не трогается: умолчания обоих модулей подменяются на одноразовые каталоги
(`_DEFAULT_DATA_DIR` · `_LOG_PATH`/`_LOG_PATH_AT_IMPORT`), бегун строится на tmp.
Дат-литералов нет: ряд APY датируется от сегодняшнего дня назад (ряд нужен лишь длиной ≥ 7).
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from spa_core.analytics import _module_registry as registry
from spa_core.analytics import protocol_defi_yield_duration_mismatch_analyzer as ydm
from spa_core.analytics import signal_aggregator as sa
from spa_core.analytics import yield_volatility_surface_analyzer as yvs

PROTOCOL = "aave_v3"
YDM_LOG = ydm.ProtocolDeFiYieldDurationMismatchAnalyzer.LOG_FILE
YVS_LOG = yvs._LOG_FILE


# ─── сцена ────────────────────────────────────────────────────────────────────

def _seed_apy_series(data_dir: Path, days: int = 12) -> None:
    """Дневной ряд aave_v3 в historical_apy/ — ровно то, что читает `_apy_series`."""
    hist = data_dir / "historical_apy"
    hist.mkdir(parents=True, exist_ok=True)
    today = date.today()
    rows = [{"date": (today - timedelta(days=i)).isoformat(), "apy": 3.0 + 0.01 * i}
            for i in range(days, 0, -1)]
    (hist / "aave_v3_usdc.json").write_text(json.dumps(rows), encoding="utf-8")


@pytest.fixture
def module_defaults(tmp_path, monkeypatch):
    """Умолчания ОБОИХ модулей — на одноразовый каталог; возвращает его."""
    default = tmp_path / "module_default"
    default.mkdir()
    monkeypatch.setattr(ydm, "_DEFAULT_DATA_DIR", str(default))
    monkeypatch.setattr(yvs, "_LOG_PATH", str(default / YVS_LOG))
    monkeypatch.setattr(yvs, "_LOG_PATH_AT_IMPORT", str(default / YVS_LOG))
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    return default


def _runner_dir(tmp_path: Path) -> Path:
    d = tmp_path / "runner_sandbox"
    d.mkdir()
    _seed_apy_series(d)
    return d


def _info(module: str) -> dict:
    info = registry.get_module_info(module)
    assert info is not None, module
    return info


def _entries(path: Path) -> list:
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(doc, list) and doc, path
    return doc


# ─── protocol_defi_yield_duration_mismatch_analyzer ──────────────────────────

class TestYieldDurationMismatchWriter:
    def test_context_with_the_runner_key_writes_the_log_into_the_runner_dir(self, tmp_path, module_defaults):
        runner = _runner_dir(tmp_path)
        out = ydm.ProtocolDeFiYieldDurationMismatchAnalyzer().analyze(
            {"protocol": PROTOCOL, "data_dir": str(runner), "cycle_ts": "t"})
        assert isinstance(out, dict) and "risk_score" in out
        _entries(runner / YDM_LOG)
        assert not (module_defaults / YDM_LOG).exists(), "журнал ушёл в умолчание модуля — мимо ключа"

    def test_the_real_runner_lands_the_log_in_its_own_data_dir(self, tmp_path, module_defaults):
        runner = _runner_dir(tmp_path)
        agg = sa.SignalAggregator(data_dir=runner)
        score, ok = agg._run_module(_info("protocol_defi_yield_duration_mismatch_analyzer"), PROTOCOL,
                                    {"cycle_ts": "t"})
        assert ok and isinstance(score, float)
        _entries(runner / YDM_LOG)
        assert not (module_defaults / YDM_LOG).exists()

    def test_context_without_the_key_keeps_the_module_default(self, tmp_path, module_defaults):
        out = ydm.ProtocolDeFiYieldDurationMismatchAnalyzer().analyze({"protocol": PROTOCOL})
        assert isinstance(out, dict)
        _entries(module_defaults / YDM_LOG)

    def test_config_key_beats_the_instance_default_and_a_legacy_call_keeps_it(self, tmp_path, module_defaults):
        own = tmp_path / "own"
        own.mkdir()
        via_config = tmp_path / "via_config"
        via_config.mkdir()
        proto = [{"name": "X", "protocol": "X", "asset_avg_maturity_days": 20,
                  "liability_avg_redemption_days": 1, "liquid_reserve_pct": 60}]
        analyzer = ydm.ProtocolDeFiYieldDurationMismatchAnalyzer(data_dir=str(own))
        analyzer.analyze(proto, {"data_dir": str(via_config)})
        _entries(via_config / YDM_LOG)
        assert not (own / YDM_LOG).exists()
        analyzer.analyze(proto)                      # легаси-форма: своё умолчание
        _entries(own / YDM_LOG)

    def test_unknown_protocol_stays_dormant_and_writes_nothing(self, tmp_path, module_defaults):
        runner = _runner_dir(tmp_path)
        out = ydm.ProtocolDeFiYieldDurationMismatchAnalyzer().analyze(
            {"protocol": "no_such_protocol_xyz", "data_dir": str(runner)})
        assert out is None
        assert not (runner / YDM_LOG).exists() and not (module_defaults / YDM_LOG).exists()


# ─── yield_volatility_surface_analyzer ───────────────────────────────────────

class TestYieldVolatilitySurfaceWriter:
    def test_context_with_the_runner_key_reads_the_series_and_writes_the_log_there(self, tmp_path, module_defaults):
        runner = _runner_dir(tmp_path)
        out = yvs.analyze({"protocol": PROTOCOL, "data_dir": str(runner), "cycle_ts": "t"})
        assert isinstance(out, dict) and "risk_score" in out
        _entries(runner / YVS_LOG)
        assert not (module_defaults / YVS_LOG).exists(), "журнал ушёл в умолчание модуля — мимо ключа"

    def test_the_real_runner_lands_the_log_in_its_own_data_dir(self, tmp_path, module_defaults):
        runner = _runner_dir(tmp_path)
        agg = sa.SignalAggregator(data_dir=runner)
        score, ok = agg._run_module(_info("yield_volatility_surface_analyzer"), PROTOCOL, {"cycle_ts": "t"})
        assert ok and isinstance(score, float)
        _entries(runner / YVS_LOG)
        assert not (module_defaults / YVS_LOG).exists()

    def test_without_a_series_in_the_runner_dir_it_is_dormant_and_writes_nowhere(self, tmp_path, module_defaults):
        empty = tmp_path / "empty_sandbox"
        empty.mkdir()
        assert yvs.analyze({"protocol": PROTOCOL, "data_dir": str(empty)}) is None
        assert not (empty / YVS_LOG).exists() and not (module_defaults / YVS_LOG).exists()

    def test_legacy_call_without_config_keeps_the_module_default(self, tmp_path, module_defaults):
        yvs.analyze([{"protocol": "Aave", "asset": "USDC",
                      "apy_7d_samples": [3.0] * 7, "apy_30d_samples": [3.0] * 30, "apy_90d_samples": [3.0] * 90}])
        _entries(module_defaults / YVS_LOG)

    def test_config_key_beats_SPA_DATA_DIR_which_beats_the_module_default(self, tmp_path, module_defaults, monkeypatch):
        env_dir = tmp_path / "env_dir"
        env_dir.mkdir()
        via_config = tmp_path / "via_config"
        via_config.mkdir()
        monkeypatch.setenv("SPA_DATA_DIR", str(env_dir))
        assert Path(yvs._log_path_for(str(via_config))) == via_config / YVS_LOG
        assert Path(yvs._log_path_for(None)) == env_dir / YVS_LOG
        monkeypatch.delenv("SPA_DATA_DIR")
        assert Path(yvs._log_path_for(None)) == module_defaults / YVS_LOG


# ─── контроль в обратную сторону ─────────────────────────────────────────────

class TestTheDoorIsWhatDiscriminates:
    """Сцены различают ДВЕРЬ, а не проходят подстрокой: с дверью «контекст → config»,
    превращённой в `None`, тот же контекстный вызов пишет мимо ключа — и сцена это ловит."""

    def test_with_the_context_door_made_none_the_mismatch_log_falls_back_to_the_default(self, tmp_path, module_defaults, monkeypatch):
        monkeypatch.setattr(ydm, "_config_from_context", lambda _ctx: None)
        runner = _runner_dir(tmp_path)
        ydm.ProtocolDeFiYieldDurationMismatchAnalyzer().analyze({"protocol": PROTOCOL, "data_dir": str(runner)})
        assert not (runner / YDM_LOG).exists()
        _entries(module_defaults / YDM_LOG)

    def test_with_the_context_door_made_none_the_surface_log_falls_back_to_the_default(self, tmp_path, module_defaults, monkeypatch):
        monkeypatch.setattr(yvs, "_config_from_context", lambda _ctx: None)
        runner = _runner_dir(tmp_path)
        yvs.analyze({"protocol": PROTOCOL, "data_dir": str(runner)})
        assert not (runner / YVS_LOG).exists()
        _entries(module_defaults / YVS_LOG)

    def test_both_modules_resolve_the_runner_key_through_one_door_each(self):
        for mod in (ydm, yvs):
            assert mod._config_from_context({"data_dir": "/x"}) == {"data_dir": "/x"}
            assert mod._config_from_context({"protocol": PROTOCOL}) is None
            assert mod._config_from_context([{"protocol": PROTOCOL}]) is None
