"""Сторож класса: ограничения тюнера ЗЕРКАЛЯТ RiskPolicy v1.0, а не копируют её.

Почему сторож нужен именно классовый, а не «на одно число». Сегодня уже дважды
находили один и тот же дефект — второе определение одного правила, живущее рядом
с первым (`house_view_gap` держал вторую копию определения «назван ли отказ»; три
реестра адаптеров носили одно имя). Тюнер был третьим случаем: литералы в
`TunerConstraints` разъехались с политикой в обе стороны, и одна сторона была
ОПАСНОЙ — плоский `per_protocol_max = 0.25` применялся и к T2, где политика
держит 20 %. Замер 2026-08-18 на пятиадаптерной книге: тюнер предлагал `maple`
(T2) на 23.81 %, а `policy_enforcer` тот же портфель ОТКЛОНЯЛ
(`per_protocol_max_pct CRITICAL 23.81 <= 20.0`).

Поэтому тесты ниже проверяют СВЯЗЬ, а не значения:

* прямой контроль — каждое поле-порог тюнера равно соответствующему полю
  `RiskConfig`; таблица связей одна и обходится циклом, так что новый литерал
  в тюнере (или сдвиг порога в политике без сдвига зеркала) красит тест;
* обратный контроль — сегодняшние согласованные значения проходят, и
  предложение тюнера принимается тем самым `policy_enforcer`, который раньше
  его отклонял;
* направление — конструкторы, намеренно отходящие от политики
  (`portfolio_rebalancer._DEFAULT_CONSTRAINTS`), могут быть только СТРОЖЕ.

RiskPolicy v1.0 здесь не меняется ни строкой: тест читает её, а не задаёт.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.risk.policy import RiskConfig
from spa_core.risk.policy_enforcer import validate_positions
from spa_core.tuner.allocation_tuner import AllocationTuner, TunerConstraints
from spa_core.tuner.portfolio_rebalancer import _DEFAULT_CONSTRAINTS


# ─── Таблица связей: поле тюнера ↔ поле RiskConfig ───────────────────────────
# Единственное место, где это соответствие записано. Добавили порог в тюнер —
# добавьте строку сюда либо докажите тестом, что аналога в политике нет.
_MIRRORED = {
    "t2_max":              "max_total_t2_allocation",
    "t3_max":              "max_total_t3_allocation",
    "per_protocol_max":    "max_single_protocol",
    "per_protocol_max_t1": "max_concentration_t1",
    "per_protocol_max_t2": "max_concentration_t2",
    "tvl_floor_usd":       "min_tvl_usd",
    "max_protocols":       "max_protocols",
    "cash_min":            "min_cash_pct",
    "apy_min":             "min_apy_for_new_position",
    "apy_max":             "max_apy_for_new_position",
}

# Поля тюнера, у которых аналога в политике НЕТ — перечислены поимённо, чтобы
# «просто добавить новое поле и забыть» было невозможно.
_TUNER_OWN = {"min_protocols", "t1_min"}


def _cfg() -> RiskConfig:
    return RiskConfig()


# ─── 1. Прямой контроль: зеркало точное ──────────────────────────────────────

@pytest.mark.parametrize("tuner_field,policy_field", sorted(_MIRRORED.items()))
def test_tuner_default_mirrors_riskpolicy(tuner_field, policy_field):
    """Дефолт тюнера равен порогу политики — без второй копии числа."""
    c = TunerConstraints()
    assert float(getattr(c, tuner_field)) == pytest.approx(
        float(getattr(_cfg(), policy_field))
    ), (
        "TunerConstraints.{} разъехался с RiskConfig.{}: {} vs {}".format(
            tuner_field, policy_field,
            getattr(c, tuner_field), getattr(_cfg(), policy_field),
        )
    )


def test_every_constraint_field_is_classified():
    """Каждое поле constraints — либо зеркало политики, либо явно своё.

    Сторож КЛАССА: новое поле-порог, добавленное литералом, красит тест, даже
    если сегодня оно случайно совпадает с политикой.
    """
    fields = set(TunerConstraints().__dataclass_fields__)
    unclassified = fields - set(_MIRRORED) - _TUNER_OWN
    assert not unclassified, (
        "Поля без классификации (зеркало политики или собственное?): "
        + ", ".join(sorted(unclassified))
    )


def test_no_t1_floor_because_policy_has_none():
    """T1-пола в политике нет ⇒ тюнер не имеет права его выдумывать.

    `policy_enforcer._T1_MIN_PCT = 0.0` с той же мотивировкой (2026-07-08).
    """
    cfg = _cfg()
    assert not [f for f in cfg.__dataclass_fields__
                if "t1_min" in f or "min_t1" in f], (
        "В RiskConfig появился T1-пол — зеркало тюнера надо обновить, "
        "а не оставлять 0.0"
    )
    assert TunerConstraints().t1_min == 0.0


def test_tier_cap_follows_policy_tiering():
    """`cap_for` повторяет тирование политики: T1 → T1-cap, всё прочее → T2-cap."""
    cfg, c = _cfg(), TunerConstraints()
    assert c.cap_for("T1") == pytest.approx(
        min(float(cfg.max_concentration_t1), float(cfg.max_single_protocol)))
    for tier in ("T2", "T3", "", None, "unknown"):
        assert c.cap_for(tier) == pytest.approx(
            min(float(cfg.max_concentration_t2), float(cfg.max_single_protocol))), (
            "тир {} должен идти под T2-cap политики".format(tier)
        )


# ─── 2. Обратный контроль: согласованные значения проходят ───────────────────

_BOOK = [
    {"id": "aave_v3",     "apy": 3.13, "tvl_usd": 209_000_000.0,   "tier": "T1"},
    {"id": "compound_v3", "apy": 3.18, "tvl_usd": 48_000_000.0,    "tier": "T1"},
    {"id": "yearn_v3",    "apy": 3.18, "tvl_usd": 26_000_000.0,    "tier": "T2"},
    {"id": "euler_v2",    "apy": 2.77, "tvl_usd": 16_000_000.0,    "tier": "T2"},
    {"id": "maple",       "apy": 4.72, "tvl_usd": 3_114_000_000.0, "tier": "T2"},
]
# Все адаптеры книги — Ethereum L1; карта передаётся явно, чтобы тест не зависел
# от живого data/adapter_registry.json.
_CHAIN_MAP = {a["id"]: "ethereum" for a in _BOOK}


# Правила гейта, которые тюнер НЕ зеркалит и зеркалить пока не может: у него в
# контракте входа (`{id, apy, tvl_usd, tier}`) нет сети, а в снимке оркестратора
# нет поля `chain`. Пробел НАЗВАН здесь и вынесен владельцу карточкой
# own-2026-08-18-tyuner-ne-znaet-o-setevykh-potolkakh — не спрятан. Любое
# ДРУГОЕ нарушение красит тест.
_UNMIRRORED_GATE_RULES = frozenset({
    "single_chain_max_pct", "l2_total_max_pct", "base_chain_max_pct",
})


@pytest.mark.parametrize("constraints", [None, _DEFAULT_CONSTRAINTS],
                         ids=["tuner_defaults", "rebalancer_defaults"])
def test_tuner_suggestion_breaks_no_mirrored_gate_rule(constraints):
    """Предложение тюнера не нарушает ни одного зеркалимого правила гейта.

    Именно это краснело до фикса: `maple` (T2) шёл на 23.81 %, enforcer
    отвечал `per_protocol_max_pct CRITICAL 23.81 <= 20.0` — тюнер предлагал
    раскладку, которую гейт заворачивает.
    """
    result = AllocationTuner(constraints=constraints).optimize(_BOOK, n_candidates=500)
    capital = 100_000.0
    positions = {k: round(w * capital, 2)
                 for k, w in result.optimal_weights.items() if w > 1e-6}
    cash = capital - sum(positions.values())

    verdict = validate_positions(positions, capital,
                                 cash_usd=cash, chain_map=_CHAIN_MAP)
    unexpected = [v for v in verdict.violations
                  if v.rule not in _UNMIRRORED_GATE_RULES]
    assert not unexpected, "гейт отклонил предложение тюнера: " + "; ".join(
        "{} {} (actual={}, expected={})".format(v.rule, v.severity, v.actual, v.expected)
        for v in unexpected
    )


def test_unmirrored_gate_rules_are_still_exactly_the_known_gap():
    """Список НЕзеркалимых правил не имеет права тихо расти.

    Появилось новое правило гейта, которое тюнер не знает, — его надо либо
    зеркалить, либо осознанно внести сюда карточкой владельцу.
    """
    from spa_core.risk.policy_enforcer import RULES
    chain_rules = {r for r in RULES if r.endswith("_chain_max_pct")
                   or r == "l2_total_max_pct"}
    assert chain_rules == set(_UNMIRRORED_GATE_RULES), (
        "набор сетевых правил гейта изменился: {}".format(
            sorted(chain_rules ^ set(_UNMIRRORED_GATE_RULES)))
    )


def test_per_protocol_weights_respect_policy_tier_caps():
    """Ни один вес не выше тирового потолка ПОЛИТИКИ (числа читаются из неё)."""
    cfg = _cfg()
    tiers = {a["id"]: a["tier"] for a in _BOOK}
    result = AllocationTuner().optimize(_BOOK, n_candidates=500)
    for pid, w in result.optimal_weights.items():
        cap = (float(cfg.max_concentration_t1) if tiers[pid] == "T1"
               else float(cfg.max_concentration_t2))
        cap = min(cap, float(cfg.max_single_protocol))
        assert w <= cap + 1e-6, "{}: {:.4f} > policy cap {:.4f}".format(pid, w, cap)


def test_eligibility_filter_uses_policy_floor_and_bounds():
    """TVL-floor и границы APY — ровно политики, без собственных значений."""
    cfg = _cfg()
    floor = float(cfg.min_tvl_usd)
    lo, hi = float(cfg.min_apy_for_new_position), float(cfg.max_apy_for_new_position)
    probes = [
        {"id": "just_below_floor", "apy": 5.0, "tvl_usd": floor - 1.0, "tier": "T1"},
        {"id": "at_floor",         "apy": 5.0, "tvl_usd": floor,       "tier": "T1"},
        {"id": "apy_too_low",      "apy": lo - 0.01, "tvl_usd": floor * 10, "tier": "T1"},
        {"id": "apy_too_high",     "apy": hi + 0.01, "tvl_usd": floor * 10, "tier": "T2"},
        {"id": "apy_at_max",       "apy": hi,        "tvl_usd": floor * 10, "tier": "T2"},
    ]
    eligible = {a["id"] for a in AllocationTuner()._eligible_adapters(probes)}
    assert eligible == {"at_floor", "apy_at_max"}, eligible


# ─── 3. Направление отклонений: только строже, никогда слабее ────────────────

def test_rebalancer_constraints_are_never_looser_than_policy():
    """Запас ребалансера допустим только в сторону отказа.

    Ослабление (потолок выше политики / кэш ниже) означало бы, что тюнер
    предлагает то, чего гейт не пропустит, — красить немедленно.
    """
    cfg, c = _cfg(), _DEFAULT_CONSTRAINTS
    assert c.per_protocol_max <= float(cfg.max_single_protocol) + 1e-12
    assert c.per_protocol_max_t1 <= float(cfg.max_concentration_t1) + 1e-12
    assert c.per_protocol_max_t2 <= float(cfg.max_concentration_t2) + 1e-12
    assert c.t2_max <= float(cfg.max_total_t2_allocation) + 1e-12
    assert c.t3_max <= float(cfg.max_total_t3_allocation) + 1e-12
    assert c.max_protocols <= int(cfg.max_protocols)
    assert c.cash_min >= float(cfg.min_cash_pct) - 1e-12
    assert c.tvl_floor_usd >= float(cfg.min_tvl_usd) - 1e-12
    assert c.apy_min >= float(cfg.min_apy_for_new_position) - 1e-12
    assert c.apy_max <= float(cfg.max_apy_for_new_position) + 1e-12


def test_riskpolicy_version_untouched():
    """Зеркалирование не имеет права двигать саму политику."""
    assert _cfg().version == "v1.0"
