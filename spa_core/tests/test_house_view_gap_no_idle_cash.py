"""Сверка офис↔книга не имеет права звать ПРОСТОЕМ книгу, у которой свободных денег ноль.

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД: `compute_gaps(..., now=NOW)` с
# фиксированным `NOW` и фиксированными возрастами входов; календарь на вердикт не влияет.

**Авария, которую повторяет каждый положительный контроль (замер 2026-09-01, цикл #449).**
Обязательный шаг 0-офис печатал красную строку, а `data/loop_health.json` рядом —
«🔴 РЕЦИДИВ ЖИВОЙ: gap:opportunity_unnamed:spark_susds ×3, карточки СЕЙЧАС НЕТ»:

    возможность spark_susds 4.0121% (evidence L2) доступна книге, не держится и отказ
    НЕ назван ни в одном из ПРОЧИТАННЫХ регистров аллокатора (3 из 4) — безымянный
    простой (дух ADR-055)

А в том же `data/allocation_rationale.json`, в том же разделе `cash`, который сторож
УЖЕ открывал ради `policy_refusals`, стояло: `excess_pct = 0.0`, `unexplained_pct = 0.0`,
`status = "explained"`, `components = [min_cash_buffer 5 % — mandated, not forgone]`.
Книга размещена на 95 % при мандатном буфере 5 %. **Свободных денег НОЛЬ.**

Простоя не существовало. Вход в `spark_susds` (4.01 %) требовал бы ПРОДАЖИ позиции из
книги, дающей 5.42 %, — это вопрос предпочтения, которым ведают тюнер и триггер ADR-060,
а не необъяснённый простой капитала. ADR-055 обязывает объяснять кэш **сверх буфера**;
здесь эта величина измерена и равна нулю, и слово «простой» было ложью о ФАКТЕ.

Класс — тот же, что #394 (третий регистр, `cash.policy_refusals`) и #418 (четвёртый,
`cash.ineligible_rooms`): сторож честно отвечает на СВОЙ вопрос («назван ли отказ?»),
а читается как ответ на нужный («стоят ли деньги без дела?»). Цена измерена: десять
карточек моста этого класса закрыто, три из них про тот же `spark_susds`.

Контроли — в обе стороны, иначе починка неотличима от глушения сигнала:
настоящий простой (`excess_pct > 0`) обязан остаться WARN, а НЕизмеренный простой не
даёт права снять находку (fail-CLOSED).
"""

from __future__ import annotations

import datetime as dt

import pytest

from spa_core.monitoring import house_view_gap as H

NOW = dt.datetime(2026, 9, 1, 5, 39, tzinfo=dt.timezone.utc)
AGES = {"chief_investment": {"input": "chief_investment", "age_s": 16},
        "current_positions": {"input": "current_positions", "age_s": 9830}}
PROTO = "spark_susds"
REGISTRY = {PROTO, "compound_v3", "fluid_usdc", "maple", "morpho_steakhouse"}

#: Дословная запись прод-цикла 2026-09-01 02:55Z (`data/allocation_rationale.json`,
#: раздел `cash`). Числа не округлены и не «типичны» — это тот самый файл.
REAL_CASH = {
    "capital_usd": 100000.0, "cash_pct": 5.0, "buffer_pct": 5.0,
    "excess_pct": 0.0, "explained_pct": 5.0, "unexplained_pct": 0.0,
    "unchecked": [], "status": "explained",
    "components": [{"kind": "min_cash_buffer", "usd": 5000.0, "pct": 5.0,
                    "status": "OK", "forgone_bps_yr": 0.0,
                    "detail": "policy min-cash floor 5% — mandated, not forgone"}],
    "policy_refusals": [{"protocol": "fluid_fusdc",
                         "reason": "tvl_unverified_policy_gate",
                         "usd_removed_from_target": 18947.37,
                         "pct_of_capital": 18.9474}],
}


def chief(apy: float = 4.0121) -> dict:
    return {"house_view": {"overall_posture": "YELLOW",
                           "top_opportunities": [
                               {"evidence_level": "L2",
                                "source": "data/apy_ranking.json (live cycle)",
                                "value": {"protocol": PROTO, "apy_pct": apy}}]}}


def book() -> dict:
    """Книга прод-цикла: 95 % размещено, кэш РОВНО мандатный буфер."""
    return {"capital_usd": 100000.0, "cash_usd": 5000.0,
            "positions": {"compound_v3": {"usd": 40000.0},
                          "fluid_usdc": {"usd": 20000.0},
                          "maple": {"usd": 20000.0},
                          "morpho_steakhouse": {"usd": 15000.0}}}


def rationale(cash=None) -> dict:
    """Форма прод-файла: `ineligible_rooms` в нём НЕТ — читаются 3 регистра из 4."""
    return {"below_median_cap": [],
            "decision_shadow": {"warnings": []},
            "cash": REAL_CASH if cash is None else cash}


def run(rat) -> dict:
    return H.compute_gaps(chief(), book(), rat, set(REGISTRY), {}, NOW, AGES)


def gap_for(report: dict, protocol: str) -> dict:
    found = [g for g in report["gaps"] if g.get("protocol") == protocol]
    assert found, f"находки про {protocol} нет вовсе: {[g['key'] for g in report['gaps']]}"
    assert len(found) == 1, f"про {protocol} находок больше одной: {found}"
    return found[0]


class TestRealProdStateIsNotIdle:
    """Дословное состояние 2026-09-01: WARN про «простой» обязан исчезнуть."""

    def test_real_state_is_not_a_warn(self):
        gap = gap_for(run(rationale()), PROTO)
        assert gap["severity"] == "INFO", (
            "книга размещена на 95 %, свободных сверх буфера 0.00 % — «безымянный "
            f"простой» тут ложь о факте, а не строгость: {gap['message']}")

    def test_real_state_gets_its_own_key(self):
        # Ключ ДРУГОЙ намеренно: мост ADR-066 узнаёт находку по ключу, и смена смысла
        # под старым ключом проехала бы для него незамеченной.
        assert gap_for(run(rationale()), PROTO)["key"] == f"{H.KEY_NO_IDLE_CAPITAL}:{PROTO}"

    def test_finding_does_not_vanish(self):
        # Понижение степени — не молчание: офис называет возможность, которой у книги
        # нет денег взять, и читатель обязан это видеть.
        assert any(g.get("protocol") == PROTO for g in run(rationale())["gaps"])

    def test_message_names_the_measured_idle(self):
        msg = gap_for(run(rationale()), PROTO)["message"]
        assert "0.00 %" in msg, f"измеренный простой не назван числом: {msg}"
        assert "ПРОДАЖИ" in msg, f"не сказано, ЧЕГО потребовал бы вход: {msg}"

    def test_measured_value_travels_in_the_finding(self):
        assert gap_for(run(rationale()), PROTO)["cash_excess_pct"] == 0.0

    def test_read_registers_are_still_named(self):
        # Вторая половина починки #418 не должна пропасть: список опрошенных регистров
        # остаётся в находке, иначе отрицательное утверждение снова станет догадкой.
        assert gap_for(run(rationale()), PROTO)["registers_read"] == [
            "below_median_cap", "cash.policy_refusals", "decision_shadow.warnings"]


class TestGuardIsNotWeakened:
    """Контроль в обратную сторону: настоящий простой обязан остаться WARN."""

    @pytest.mark.parametrize("excess", [12.5, 1.0, 0.5, 0.01])
    def test_real_idle_capital_still_warns(self, excess):
        cash = dict(REAL_CASH, excess_pct=excess, unexplained_pct=excess,
                    status="unexplained")
        gap = gap_for(run(rationale(cash)), PROTO)
        assert gap["severity"] == "WARN", (
            f"свободных сверх буфера {excess} %, отказ не назван — это ровно тот "
            f"случай, ради которого сторож написан: {gap['message']}")
        assert gap["key"] == f"gap:opportunity_unnamed:{PROTO}"

    def test_warn_now_names_the_idle_number(self):
        cash = dict(REAL_CASH, excess_pct=12.5)
        assert "12.50 %" in gap_for(run(rationale(cash)), PROTO)["message"]


class TestUnmeasuredIdleGivesNoRight:
    """Инв. #17 / fail-CLOSED: «не измерено» не есть измеренный ноль."""

    @pytest.mark.parametrize("cash, why", [
        ({"policy_refusals": []}, "поля excess_pct нет вовсе"),
        (dict(REAL_CASH, excess_pct=None), "excess_pct = null"),
        (dict(REAL_CASH, excess_pct="0.0"), "excess_pct строкой, а не числом"),
        (dict(REAL_CASH, excess_pct=True), "bool — не число (и не ноль)"),
        (dict(REAL_CASH, excess_pct=float("nan")), "NaN не сравним ни с чем"),
    ])
    def test_unmeasured_idle_keeps_the_warn(self, cash, why):
        gap = gap_for(run(rationale(cash)), PROTO)
        assert gap["severity"] == "WARN", f"{why}: снимать находку было нечем"
        assert gap["key"] == f"gap:opportunity_unnamed:{PROTO}"

    def test_unmeasured_says_so_out_loud(self):
        gap = gap_for(run(rationale({"policy_refusals": []})), PROTO)
        assert "НЕ ИЗМЕРЕН" in gap["message"], (
            f"молчаливое «не измерено» неотличимо от измеренного нуля: {gap['message']}")

    def test_unmeasured_is_recorded_in_unchecked(self):
        report = run(rationale({"policy_refusals": []}))
        reasons = " ".join(u.get("reason", "") for u in report.get("unchecked", []))
        assert "простой капитала не измерен" in reasons, (
            f"третий исход обязан быть ЗАПИСАН, а не только не-утверждён: {reasons}")

    def test_absent_cash_section_keeps_the_warn(self):
        rat = {"below_median_cap": [], "decision_shadow": {"warnings": []}}
        assert gap_for(run(rat), PROTO)["severity"] == "WARN"


class TestNamedRefusalStillWins:
    """Названный отказ важнее вопроса о простое: порядок веток не переставлен."""

    def test_named_refusal_keeps_its_own_key(self):
        cash = dict(REAL_CASH, policy_refusals=[
            {"protocol": PROTO, "reason": "tvl_unverified_policy_gate",
             "usd_removed_from_target": 40000.0}])
        gap = gap_for(run(rationale(cash)), PROTO)
        assert gap["key"] == f"gap:opportunity_explained:{PROTO}"
        assert gap["severity"] == "INFO"

    def test_held_protocol_produces_no_gap(self):
        rep = H.compute_gaps(
            chief(),
            {"capital_usd": 100000.0, "cash_usd": 5000.0,
             "positions": {PROTO: {"usd": 40000.0}}},
            rationale(), set(REGISTRY), {}, NOW, AGES)
        assert not [g for g in rep["gaps"] if g.get("protocol") == PROTO]


class TestThresholdMatchesTheAllocator:
    """Два числа на одной оси: порог сторожа = порог подопечного."""

    def test_eps_matches_rebalance_economics(self):
        import inspect
        from spa_core.allocator import rebalance_economics as R
        src = inspect.getsource(R)
        assert "excess_pct <= 1e-6" in src, (
            "аллокатор сменил порог нулевого простоя — сторож обязан ехать следом, "
            "иначе два числа на одной оси однажды разойдутся молча")
        assert H.IDLE_EPS_PCT == 1e-6
