"""
Положительный контроль разметки `unsourced` — В ОБЕ СТОРОНЫ.

Карточка `agent-tier-b-20-unsourced-modules-need-sources` требует поднимать
модуль ИСТОЧНИКОМ, а не правкой разметки. Замер цикла (2026-08-18) на всех 36
записях `_protocol_key_coverage.UNSOURCED_DETAIL` дал три группы, и у каждой
свой способ соврать. Этот файл ловит обе лжи:

* **прямая** — модуль, у которого источник ЕСТЬ
  (`protocol_defi_stable_yield_consistency_scorer` берёт реальный дневной ряд
  APY из `_apy_series`), обязан выдавать РАЗЛИЧАЮЩИЕСЯ значения по протоколам.
  Константа, притворяющаяся измерением, хуже отказа — и краснеет здесь;
* **обратная** — тот же модуль без ряда обязан ОТКАЗАТЬ (None → `dormant` в
  агрегаторе), а не подставить структурный дефолт;
* **ловушка покрытия** — ни один ключ из `missing_keys` нельзя завести в
  `generic_profile_for` КОНСТАНТОЙ, чтобы поднять покрытие до 1.0. Именно так
  выглядит `tvl_trend_7d_pct`: он есть в `facts_for`, но равен 0.0 у всех
  протоколов базы (`data/tvl_trend_report.json` пуст), и проводка отмыла бы
  заглушку в измерение;
* **слишком мягкий ярлык** — пять модулей набора отвечают ЧИСЛОМ для
  НЕСУЩЕСТВУЮЩЕГО протокола (замер: 100.0 / 42.0 / 0.0 / 0.0 / 70.0 одинаково
  для `aave_v3` и для `__no_such_protocol__`). Пока они так делают, они обязаны
  оставаться исключёнными из composite ЛЮБОЙ разметкой; починятся (перестанут
  отвечать) — тест пройдёт и без разметки.

Офлайн, детерминированно: ряды синтетические в `tmp_path`, живой `data/` не
читается и не пишется (проверено замером — модули набора в `data/` не пишут).
"""
import importlib
import json

import pytest

from spa_core.analytics import _apy_series as apy_series
from spa_core.analytics import _module_registry as registry
from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics._protocol_key_coverage import UNSOURCED_DETAIL
from spa_core.analytics.signal_aggregator import _ModuleAdapter

try:
    from spa_core.analytics._protocol_blindness import (
        MISCOERCED_MODULES, PROTOCOL_BLIND_MODULES)
except Exception:  # pragma: no cover
    MISCOERCED_MODULES = frozenset()
    PROTOCOL_BLIND_MODULES = frozenset()

try:
    from spa_core.analytics._protocol_key_coverage import UNSOURCED_MODULES
except Exception:  # pragma: no cover
    UNSOURCED_MODULES = frozenset()


# Модуль группы «источник ЕСТЬ»: все пять его недостающих ключей выводятся из
# реальных источников (apy_history ← _apy_series; yield_source/has_rate_lock/
# lock_duration_days/protocol_name ← _protocol_facts).
SOURCED_MODULE = "protocol_defi_stable_yield_consistency_scorer"

# Модули, отвечающие числом для несуществующего протокола (замер 2026-08-18).
CONSTANT_FOR_NONEXISTENT = [
    "defi_protocol_cdp_stability_fee_analyzer",
    "defi_protocol_lending_market_health_scorer",
    "defi_protocol_vault_instant_exit_nav_discount_analyzer",
    "protocol_defi_position_health_monitor",
    "protocol_defi_yield_bearing_stablecoin_risk_analyzer",
]

NONEXISTENT_PROTOCOL = "__no_such_protocol_control__"


@pytest.fixture(autouse=True)
def _fresh_cache():
    apy_series.clear_cache()
    yield
    apy_series.clear_cache()


@pytest.fixture()
def series_dir(tmp_path):
    """Синтетический data_dir: три РАЗНЫХ по форме ряда + один с недобором."""
    hist = tmp_path / "historical_apy"
    hist.mkdir()

    def rows(start, step, jitter=0.0, n=40):
        out = []
        for d in range(n):
            day = ("2026-06-%02d" % (d + 1)) if d < 30 else ("2026-07-%02d" % (d - 29))
            wobble = jitter if d % 2 else -jitter
            out.append({"date": day, "apy": round(start + step * d + wobble, 4)})
        return out

    # ровный ряд, шумный ряд, падающий ряд — три разных consistency
    (hist / "aave_v3_usdc.json").write_text(
        json.dumps(rows(4.0, 0.0, jitter=0.0)), encoding="utf-8")
    (hist / "compound_v3_usdc.json").write_text(
        json.dumps(rows(4.0, 0.0, jitter=1.5)), encoding="utf-8")
    (hist / "morpho_blue_usdc.json").write_text(
        json.dumps(rows(6.0, -0.08, jitter=0.4)), encoding="utf-8")
    # недобор истории: 2 точки < min_days=5 движка
    (hist / "yearn_v3_usdc.json").write_text(json.dumps([
        {"date": "2026-07-09", "apy": 3.0},
        {"date": "2026-07-10", "apy": 3.1},
    ]), encoding="utf-8")
    return tmp_path


def _adapter(module_name):
    info = [m for m in registry.get_tier_modules("B")
            if m.get("module") == module_name]
    assert info, f"{module_name} нет в реестре Tier-B"
    return _ModuleAdapter(info[0])


def _run(module_name, protocol, data_dir=None):
    ctx = {"cycle_ts": "2026-08-18T00:00:00Z"}
    if data_dir is not None:
        ctx["data_dir"] = str(data_dir)
    return _adapter(module_name).run(protocol, ctx)


# ── прямая сторона: источник есть → значения РАЗЛИЧАЮТСЯ ─────────────────────

def test_sourced_module_differentiates_on_real_series(series_dir):
    """Модуль с настоящим источником обязан РАЗЛИЧАТЬ протоколы.

    Краснеет, если ветка контекста перестанет читать ряд и начнёт отдавать
    структурную константу: три разных по форме ряда дадут один и тот же скор.
    """
    scores = {}
    for proto in ("aave_v3", "compound_v3", "morpho"):
        score, status, detail = _run(SOURCED_MODULE, proto, series_dir)
        assert status == "ok", f"{proto}: status={status} detail={detail}"
        assert score is not None and 0.0 <= score <= 100.0
        scores[proto] = round(float(score), 6)
    assert len(set(scores.values())) >= 2, (
        "значения не различаются между протоколами — это константа, "
        f"притворяющаяся измерением: {scores}")


# ── обратная сторона: источника нет → ОТКАЗ, а не дефолт ────────────────────

@pytest.mark.parametrize("protocol,why", [
    ("yearn_v3", "истории меньше min_days — недобор"),
    ("pendle", "ряда для протокола нет вовсе"),
    (NONEXISTENT_PROTOCOL, "протокола нет в базе фактов"),
])
def test_sourced_module_refuses_without_series(protocol, why, series_dir):
    """Без ряда — None/не-ok, никакой подстановки структурного APY.

    Краснеет, если кто-то добавит fallback «возьмём apy_pct из профиля»:
    модуль начнёт отвечать числом там, где данных нет.
    """
    score, status, _detail = _run(SOURCED_MODULE, protocol, series_dir)
    assert score is None and status != "ok", (
        f"{protocol} ({why}): модуль ответил score={score} status={status} — "
        "это тихий успех вместо честного отказа")


# ── ловушка покрытия: константу в профиль не заводить ───────────────────────

def _missing_keys_all():
    return {k for d in UNSOURCED_DETAIL.values() for k in d["missing_keys"]}


def test_unsourced_key_never_enters_profile_as_constant():
    """Ключ из `missing_keys`, заведённый в профиль, обязан РАЗЛИЧАТЬСЯ.

    Правило карточки «дописать факт можно ТОЛЬКО назвав источник» проверяется
    следствием, которое видно замером: источник даёт разные значения разным
    протоколам. Одинаковое значение у всех — заглушка, поднимающая покрытие
    до 1.0 и выводящая модуль из разметки обманом.
    """
    protocols = pf.known_protocols()
    assert len(protocols) >= 10
    exposed = {}
    for proto in protocols:
        prof = pf.generic_profile_for(proto)
        if prof is None:
            continue
        for key in _missing_keys_all() & set(prof):
            exposed.setdefault(key, set()).add(repr(prof[key]))
    constants = {k: sorted(v)[0] for k, v in exposed.items() if len(v) == 1}
    assert not constants, (
        "в generic_profile_for заведены ключи разметки с ОДНИМ значением на "
        f"все {len(protocols)} протоколов — измерения тут нет: {constants}")


def test_tvl_trend_stub_is_not_promoted_into_profile():
    """Именованная ловушка: `tvl_trend_7d_pct` = 0.0 у всех протоколов базы.

    Пока значение одинаково у всех, «прокинуть его в generic_profile_for»
    (пятиминутная правка, закрывающая `protocol_tvl_filter`) означает выдать
    заглушку за измерение. Появится настоящий источник истории TVL — значения
    начнут различаться, и тест разрешит проводку сам.
    """
    key = "tvl_trend_7d_pct"
    values = set()
    for proto in pf.known_protocols():
        facts = pf.facts_for(proto)
        if facts is not None and key in facts:
            values.add(repr(facts[key]))
    stub = len(values) == 1
    exposed = key in (pf.generic_profile_for("aave_v3") or {})
    assert not (stub and exposed), (
        f"{key} одинаков у всех протоколов ({values}) и при этом проведён "
        "в профиль — заглушка выдана за измерение")


# ── слишком мягкий ярлык: константа для несуществующего протокола ───────────

@pytest.mark.parametrize("module_name", CONSTANT_FOR_NONEXISTENT)
def test_constant_for_nonexistent_protocol_stays_out_of_composite(module_name):
    """Модуль, отвечающий числом для НЕСУЩЕСТВУЮЩЕГО протокола, не может
    попасть в composite.

    Такой ответ доказывает, что фактов протокола модуль не читает вовсе.
    Две стороны: починится (перестанет отвечать) — assert'а про разметку не
    будет вовсе; останется как есть, но кто-то уберёт его из разметки —
    красный.
    """
    score, _status, _detail = _run(module_name, NONEXISTENT_PROTOCOL)
    if score is None:
        return  # модуль починен — отвечать за несуществующий протокол нечем
    excluded = (UNSOURCED_MODULES | PROTOCOL_BLIND_MODULES | MISCOERCED_MODULES)
    assert module_name in excluded, (
        f"{module_name} отвечает score={score} для несуществующего протокола "
        "и при этом НЕ исключён из composite ни одной разметкой")
