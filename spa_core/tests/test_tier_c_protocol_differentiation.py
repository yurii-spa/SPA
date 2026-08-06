"""
test_tier_c_protocol_differentiation.py — Tier-C честно говорит, относится ли
его число к протоколу (карточка `inbox-tier-c-analitiki-180-modulei-…`, 2026-08-06).

ЧТО БЫЛО ИЗМЕРЕНО на `origin/main` 11abfaf1c тем же дифференциальным
инструментом, что применялся к Tier-A/B (`scripts/audit_protocol_blindness.py
--tier C`, sandbox-чекаут):

    modules=180  counts={'blind_constant': 9, 'unchecked': 103,
                         'failed': 64, 'dormant': 4}
    blind_equivalent=9  sensitive=0

Все девять отвечающих модулей отдали ОДИН И ТОТ ЖЕ score для aave_v3 / maple /
pendle, для повторного прогона, для всех 32 протоколов широкой вселенной
`_protocol_facts` И для протокола `__nonexistent_control_protocol__`, которого
не существует. Живой артефакт `data/analytics_report_full.json` (прогон агента
`com.spa.analytics_tier_c` 2026-08-06T03:00:03Z) при этом публиковал по
восьми протоколам ОДНО число `avg_score = 20.56` — среднее девяти констант
(0,0,0,0,45,0,100,0,40)/9 = 20.555… — в форме «замер по протоколу».

Это класс «утверждение об измерении, которого не было» (#29/#31/#35–#38/#40),
только не в виде «✅ OK», а в виде правдоподобного ЧИСЛА.

Каждый тест ниже — положительный контроль: он краснеет на коде до правки
(поля `protocol_differentiation` / `protocol_specific` там нет вовсе) и
проверяет ОБЕ стороны — что слепота названа слепотой, и что честный
протокол-чувствительный Tier-C НЕ помечается слепым.
"""
from __future__ import annotations

import sys
import types

import pytest

from spa_core.analytics import signal_aggregator as sa


_FAKE_PREFIX = "_fake_tier_c_mod_"

PROTOCOLS = ["aave_v3", "maple", "pendle"]


def _install(name: str, fn):
    """Зарегистрировать синтетический Tier-C модуль spa_core.analytics.<name>."""
    full = "spa_core.analytics." + name
    mod = types.ModuleType(full)
    mod.analyze = fn
    sys.modules[full] = mod
    return {"module": name, "class": None, "tier": "C",
            "category": "background", "weight": 0.0, "protocols": ["all"]}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    for key in [k for k in sys.modules
                if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
        del sys.modules[key]


def _run(monkeypatch, tmp_path, infos, protocols=None):
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    return agg.run_tier_c(protocols or PROTOCOLS, {"source": "test"})


# ── модули-фикстуры ──────────────────────────────────────────────────────────

def _blind_constant(context):
    """Игнорирует ctx['protocol'] — ровно поведение всех 9 живых Tier-C."""
    return {"risk_score": 20.56}


def _protocol_sensitive(context):
    """Читает протокол — честный Tier-C, каким он должен быть."""
    table = {"aave_v3": 10.0, "maple": 55.0, "pendle": 70.0}
    return {"risk_score": table.get(context.get("protocol"), 33.0)}


def _known_protocols_only(context):
    """Код протокол читает, но данные есть только для известного набора."""
    known = {"aave_v3", "maple", "pendle"}
    if context.get("protocol") not in known:
        raise KeyError("unknown protocol")
    return {"risk_score": 42.0}


def _no_context():
    """Не принимает контекст протокола ⇒ UNCHECKED (no-arg fallback удалён)."""
    return {"risk_score": 1.0}


# ── NONE: воспроизведение живой аварии 2026-08-06 ────────────────────────────

def test_all_blind_constants_are_named_NONE(tmp_path, monkeypatch):
    """9 констант → verdict NONE, а не молчаливое число по протоколам."""
    infos = [_install(_FAKE_PREFIX + "blind%d" % i, _blind_constant)
             for i in range(3)]
    out = _run(monkeypatch, tmp_path, infos)
    diff = out["_meta"]["protocol_differentiation"]
    assert diff["verdict"] == "NONE", diff
    assert diff["control_protocol"] == sa.TIER_C_CONTROL_PROTOCOL
    assert diff["control_avg_score"] == 20.56
    assert diff["distinct_avg_scores"] == 1


def test_blind_constants_mark_each_protocol_not_specific(tmp_path, monkeypatch):
    """Потребитель, читающий ТОЛЬКО число, тоже видит правду."""
    infos = [_install(_FAKE_PREFIX + "blind", _blind_constant)]
    out = _run(monkeypatch, tmp_path, infos)
    for proto in PROTOCOLS:
        entry = out["protocols"][proto]
        assert entry["avg_score"] == 20.56          # число не удалено
        assert entry["protocol_specific"] is False  # но помечено


def test_live_20_56_reproduced_from_the_nine_real_scores(tmp_path, monkeypatch):
    """Ровно девять живых констант дают ровно живое 20.56 и вердикт NONE."""
    live_scores = [0.0, 0.0, 0.0, 0.0, 45.0, 0.0, 100.0, 0.0, 40.0]
    infos = []
    for i, s in enumerate(live_scores):
        infos.append(_install(_FAKE_PREFIX + "live%d" % i,
                              (lambda v: lambda ctx: {"risk_score": v})(s)))
    out = _run(monkeypatch, tmp_path, infos,
               protocols=["aave_v3", "compound_v3", "morpho_blue", "yearn_v3",
                          "euler_v2", "maple", "pendle", "spark_susds"])
    assert {p["avg_score"] for p in out["protocols"].values()} == {20.56}
    assert {p["modules_ok"] for p in out["protocols"].values()} == {9}
    assert out["_meta"]["protocol_differentiation"]["verdict"] == "NONE"


# ── OK: честный модуль слепым НЕ объявляется (контроль в обратную сторону) ───

def test_protocol_sensitive_tier_c_is_OK(tmp_path, monkeypatch):
    infos = [_install(_FAKE_PREFIX + "sens", _protocol_sensitive)]
    out = _run(monkeypatch, tmp_path, infos)
    diff = out["_meta"]["protocol_differentiation"]
    assert diff["verdict"] == "OK", diff
    assert diff["distinct_avg_scores"] == 3
    for proto in PROTOCOLS:
        assert out["protocols"][proto]["protocol_specific"] is True


def test_one_blind_module_does_not_mask_a_sensitive_one(tmp_path, monkeypatch):
    """Смесь: пока хоть один модуль различает протоколы — вердикт OK."""
    infos = [_install(_FAKE_PREFIX + "blind", _blind_constant),
             _install(_FAKE_PREFIX + "sens", _protocol_sensitive)]
    out = _run(monkeypatch, tmp_path, infos)
    assert out["_meta"]["protocol_differentiation"]["verdict"] == "OK"


# ── WEAK: код читает протокол, данные не различают ───────────────────────────

def test_known_protocols_only_is_WEAK_not_NONE(tmp_path, monkeypatch):
    """Одинаков на реальных, но на несуществующем падает ⇒ WEAK, не NONE."""
    infos = [_install(_FAKE_PREFIX + "known", _known_protocols_only)]
    out = _run(monkeypatch, tmp_path, infos)
    diff = out["_meta"]["protocol_differentiation"]
    assert diff["verdict"] == "WEAK", diff
    assert diff["control_modules_ok"] == 0
    assert diff["control_avg_score"] is None
    for proto in PROTOCOLS:
        assert out["protocols"][proto]["protocol_specific"] is False


# ── UNCHECKED: fail-CLOSED, «не измерено» не сворачивается в OK ──────────────

def test_no_responding_modules_is_UNCHECKED(tmp_path, monkeypatch):
    infos = [_install(_FAKE_PREFIX + "silent", _no_context)]
    out = _run(monkeypatch, tmp_path, infos)
    diff = out["_meta"]["protocol_differentiation"]
    assert diff["verdict"] == "UNCHECKED", diff
    assert "ни один" in diff["reason"]
    for proto in PROTOCOLS:
        assert out["protocols"][proto]["avg_score"] is None
        assert out["protocols"][proto]["protocol_specific"] is None


def test_single_protocol_is_UNCHECKED_not_NONE(tmp_path, monkeypatch):
    """Один протокол — различать не с чем; это НЕ доказательство слепоты."""
    infos = [_install(_FAKE_PREFIX + "blind", _blind_constant)]
    out = _run(monkeypatch, tmp_path, infos, protocols=["aave_v3"])
    diff = out["_meta"]["protocol_differentiation"]
    assert diff["verdict"] == "UNCHECKED", diff
    assert out["protocols"]["aave_v3"]["protocol_specific"] is None


def test_empty_registry_is_UNCHECKED(tmp_path, monkeypatch):
    out = _run(monkeypatch, tmp_path, [])
    assert out["_meta"]["protocol_differentiation"]["verdict"] == "UNCHECKED"


# ── контрольный прогон не протекает наружу ───────────────────────────────────

def test_control_protocol_never_appears_in_output(tmp_path, monkeypatch):
    """Несуществующий протокол — инструмент замера, не строка отчёта."""
    infos = [_install(_FAKE_PREFIX + "blind", _blind_constant)]
    out = _run(monkeypatch, tmp_path, infos)
    assert sa.TIER_C_CONTROL_PROTOCOL not in out["protocols"]
    assert set(out["protocols"]) == set(PROTOCOLS)


def test_control_run_does_not_pollute_module_status(tmp_path, monkeypatch):
    """module_status обязан описывать РЕАЛЬНЫЕ протоколы.

    Модуль, отвечающий ТОЛЬКО для несуществующего протокола, не должен
    попасть в счётчик "ok" — иначе счётчик пригодности начинает лгать в
    другую сторону.
    """
    def _control_only(context):
        if context.get("protocol") != sa.TIER_C_CONTROL_PROTOCOL:
            raise RuntimeError("no data for real protocol")
        return {"risk_score": 7.0}

    infos = [_install(_FAKE_PREFIX + "ctlonly", _control_only)]
    out = _run(monkeypatch, tmp_path, infos)
    counts = out["_meta"]["module_status"]["counts"]
    assert counts.get("ok", 0) == 0, counts
    assert counts.get("failed") == 1, counts


def test_health_log_has_no_control_protocol_entries(tmp_path, monkeypatch):
    infos = [_install(_FAKE_PREFIX + "blind", _blind_constant)]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    agg.run_tier_c(PROTOCOLS, {"source": "test"})
    # 1 модуль × 3 реальных протокола = 3 записи; контрольный прогон — 0.
    assert len(agg._log) == 3, list(agg._log)


# ── инструмент аудита действительно умеет Tier-C (поправка к карточке) ──────

def test_audit_tool_accepts_tier_c():
    """Карточка утверждала «инструмента для C нет» — это неверно.

    `--tier C` принимался всегда; тест пиннит, что тир остаётся параметром и
    Tier-C не выпадет из инструмента при будущих правках.
    """
    import importlib.util
    import inspect
    from pathlib import Path

    path = (Path(sa.__file__).resolve().parent.parent.parent
            / "scripts" / "audit_protocol_blindness.py")
    # CLI действительно принимает C (читаем исходник, а не гадаем)
    assert '"--tier", default="B", choices=["A", "B", "C"]' \
        in path.read_text(encoding="utf-8")

    spec = importlib.util.spec_from_file_location("_audit_blindness_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # run_audit параметризован тиром, а не зашит на B
    assert "tier" in inspect.signature(mod.run_audit).parameters
