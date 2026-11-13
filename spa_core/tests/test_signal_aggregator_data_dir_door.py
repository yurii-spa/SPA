"""Дверь `data_dir` у бегуна аналитик (ADR-1003, цикл #1122).

Предмет. Замер ADR-1002: прод-вызывающие строят `SignalAggregator(data_dir=ddir)`
(`cycle_runner.py`, `cycle_gates.py`), а модулям отдавали `context={"cycle_ts": …}` —
каталог бегуна до модуля не доходил; 53 модуля реестра спрашивают
`context.get("data_dir")` и без него пишут в своё умолчание, под песочницей — в
прод-дерево. С ADR-1003 бегун кладёт `ctx["data_dir"] = str(self.data_dir)` ОДНОЙ
дверью (`SignalAggregator._context_for_modules`), через которую ходят обе двери запуска
(`_run_module`, `_run_module_silent`).

Что закреплено и в какую сторону:
* модуль видит каталог, с которым построен бегун (песочница ⇒ песочница);
* бегун по умолчанию называет `DATA_DIR` этого файла — тот же каталог, в который разрешаются
  все `DATA_DIR`/`_DATA_DIR` пакета аналитики (замер #1122: 21 из 21), поэтому байты
  штатного цикла не двигаются;
* каталог бегуна ВЫИГРЫВАЕТ у ключа вызывающего: один прогон — один адрес записи;
* значение — `str`, контекст вызывающего не мутируется, прочие ключи (`cycle_ts`) доезжают;
* тихая дверь Tier-C (`_run_module_silent`) и настоящий пул Tier-A идут через ту же дверь;
* контроль в обратную сторону: с дверью, превращённой в тождество, ключа у модуля НЕТ —
  то есть сцены различают дверь, а не проходят подстрокой (ADR-333).

Прод-`data/` не трогается: бегун строится на одноразовых каталогах, модули — синтетические
(`sys.modules`), ни один из них не пишет на диск.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

from spa_core.analytics import signal_aggregator as sa
from spa_core.analytics import _module_registry as registry

_FAKE_PREFIX = "_fake_door_mod_"


def _install_capturing_module(name: str, seen: List[Dict[str, Any]], tier: str = "B") -> Dict[str, Any]:
    """Синтетический модуль реестра: `analyze(context)` запоминает контекст и отдаёт score."""
    full = "spa_core.analytics." + name
    mod = types.ModuleType(full)

    def analyze(context):  # noqa: ANN001 — форма входа бегуна
        seen.append(dict(context))
        return {"risk_score": 42.0}

    mod.analyze = analyze  # type: ignore[attr-defined]
    sys.modules[full] = mod
    return {"module": name, "class": None, "tier": tier,
            "category": "test", "weight": 0.5, "protocols": ["all"]}


@pytest.fixture(autouse=True)
def _cleanup_fake_modules():
    yield
    for key in [k for k in sys.modules if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
        del sys.modules[key]


# ─────────────────────────── дверь: песочница доезжает ───────────────────────────

def test_module_sees_the_runner_sandbox_as_data_dir(tmp_path):
    seen: List[Dict[str, Any]] = []
    info = _install_capturing_module(_FAKE_PREFIX + "a", seen)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    score, ok = agg._run_module(info, "aave_v3", {"cycle_ts": "2026-11-13T00:00:00Z"})
    assert ok and score == 42.0
    assert len(seen) == 1
    ctx = seen[0]
    assert ctx["data_dir"] == str(tmp_path)
    assert ctx["protocol"] == "aave_v3"
    assert ctx["cycle_ts"] == "2026-11-13T00:00:00Z", "прочие ключи вызывающего обязаны доехать"


def test_default_runner_names_the_prod_default_so_prod_bytes_do_not_move():
    seen: List[Dict[str, Any]] = []
    info = _install_capturing_module(_FAKE_PREFIX + "b", seen)
    agg = sa.SignalAggregator()
    agg._run_module(info, "aave_v3", {})
    got = Path(seen[0]["data_dir"]).resolve()
    assert got == Path(sa.DATA_DIR).resolve()
    # Тот же каталог, в который разрешается умолчание модулей-читателей (замер #1122: 21/21).
    from spa_core.analytics import _apy_series  # помощник, к которому ходят читатели двери (`_apy_series`)
    assert Path(_apy_series.DATA_DIR).resolve() == got


def test_runner_wins_over_a_caller_context_data_dir(tmp_path):
    seen: List[Dict[str, Any]] = []
    info = _install_capturing_module(_FAKE_PREFIX + "c", seen)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    agg._run_module(info, "aave_v3", {"data_dir": "/somewhere/else"})
    assert seen[0]["data_dir"] == str(tmp_path), "у прогона ОДИН адрес записи — каталог бегуна"


def test_value_is_a_json_safe_str_and_the_callers_context_is_not_mutated(tmp_path):
    seen: List[Dict[str, Any]] = []
    info = _install_capturing_module(_FAKE_PREFIX + "d", seen)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    caller_ctx: Dict[str, Any] = {"cycle_ts": "t"}
    agg._run_module(info, "aave_v3", caller_ctx)
    assert type(seen[0]["data_dir"]) is str
    assert caller_ctx == {"cycle_ts": "t"}, "контекст вызывающего — не мутируется"
    assert "protocol" not in caller_ctx and "data_dir" not in caller_ctx


# ─────────────────────────── обе двери запуска ходят в одну ───────────────────────────

def test_silent_runner_uses_the_same_door(tmp_path):
    seen: List[Dict[str, Any]] = []
    info = _install_capturing_module(_FAKE_PREFIX + "e", seen, tier="C")
    agg = sa.SignalAggregator(data_dir=tmp_path)
    score, ok = agg._run_module_silent(info, sa.TIER_C_CONTROL_PROTOCOL, {"cycle_ts": "t"})
    assert ok and score == 42.0
    assert seen[0]["data_dir"] == str(tmp_path)
    assert seen[0]["protocol"] == sa.TIER_C_CONTROL_PROTOCOL
    assert agg._module_status == {}, "тихая дверь по-прежнему не пишет в module_status"


def test_tier_a_pool_passes_the_door_to_every_module(tmp_path, monkeypatch):
    seen: List[Dict[str, Any]] = []
    infos = [_install_capturing_module(_FAKE_PREFIX + f"pool{i}", seen, tier="A") for i in range(3)]
    monkeypatch.setattr(registry, "get_tier_modules", lambda tier: list(infos) if tier == "A" else [])
    agg = sa.SignalAggregator(data_dir=tmp_path)
    out = agg.run_tier_a(["aave_v3", "morpho_blue"], {"cycle_ts": "t"})
    assert set(out.get("protocols", {})) == {"aave_v3", "morpho_blue"}
    assert len(seen) == 6, "3 модуля × 2 протокола — каждый вызов через пул"
    assert {c["data_dir"] for c in seen} == {str(tmp_path)}
    assert {c["protocol"] for c in seen} == {"aave_v3", "morpho_blue"}


# ─────────────────────────── контроль в обратную сторону ───────────────────────────

def test_with_the_door_made_identity_no_runner_hands_the_key_over(tmp_path, monkeypatch):
    """Сцены различают ДВЕРЬ: отключи её — и ключа нет ни у громкой, ни у тихой двери запуска.

    Это и доказательство единственности двери: будь второй путь, через который `data_dir`
    попадает в контекст, одна из двух дверей запуска продолжила бы отдавать ключ.
    """
    monkeypatch.setattr(sa.SignalAggregator, "_context_for_modules", lambda self, c: dict(c))
    seen: List[Dict[str, Any]] = []
    info = _install_capturing_module(_FAKE_PREFIX + "f", seen)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    agg._run_module(info, "aave_v3", {"cycle_ts": "t"})
    agg._run_module_silent(info, "aave_v3", {"cycle_ts": "t"})
    assert len(seen) == 2
    assert all("data_dir" not in c for c in seen)
    assert all(c["protocol"] == "aave_v3" for c in seen), "protocol кладёт адаптер, не дверь"


def test_the_door_is_the_only_writer_of_the_key_in_the_runner_source():
    """AST бегуна: ключ `data_dir` в контекст кладёт ровно ОДНО место — `_context_for_modules`."""
    import ast
    src = Path(sa.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    writers: List[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "data_dir"):
                        writers.append(fn.name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("setdefault", "update"):
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "data_dir":
                    writers.append(fn.name)
                if any(kw.arg == "data_dir" for kw in node.keywords):
                    writers.append(fn.name)
    assert writers == ["_context_for_modules"], writers
