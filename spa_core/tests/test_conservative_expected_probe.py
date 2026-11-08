"""Контроль пробы приёмки `conservative_expected_apy_published` (ADR-954).

Правило `.claude/rules/acceptance.md`, п. 3: проба регистрируется ТОЛЬКО с
тестом, где она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с
названным звеном, — и где она НЕ проходит подстрокой (ADR-333).
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом, отметка сцены
# ПРОИСХОДИТ от него (`_NOW - timedelta(...)`), и сам `_NOW` уезжает в пробу
# аргументом `now=`: обе стороны сравнения срока закреплены, календарь хоста на
# вердикт не влияет. Подпроцессов проба не поднимает — второй двери к часам нет.
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring.card_acceptance import (
    APY_CENSUS_MAX_AGE_H,
    NOT_SATISFIED,
    PROBES,
    SATISFIED,
    UNMEASURED,
)

_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)

_WHOLE_SECTION = {
    "status": "OK",
    "engine": "conservative_expected_apy",
    "is_advisory": True,
    "blind_axes": [
        {"axis": "tvl_trend", "state": "blind_empty", "detail": "файл есть и ПУСТ"},
        {"axis": "utilization_trend", "state": "blind_no_source", "detail": "файла нет"},
    ],
    "blind_axes_count": 2,
    "haircut_from_blind_axes_pp": 0.5,
    "counts": {"adapters": 3, "expected_measured": 2, "expected_unmeasured": 1},
    "opportunities": [
        {"adapter_id": "a", "conservative_expected_apy_pct": 3.0, "gap_pp": 1.0},
        {"adapter_id": "b", "conservative_expected_apy_pct": 4.0, "gap_pp": 0.9},
        {"adapter_id": "c", "conservative_expected_apy_pct": None,
         "expected_unmeasured": "состав ставки НЕ ИЗМЕРЕН"},
    ],
}


def _ask(tmp_path: Path, monkeypatch, *, section=_WHOLE_SECTION,
         age_h: float = 1.0, stamp=..., sections=...) -> tuple[str, str]:
    """Собрать дерево со своим `data/` и спросить пробу. Часы — ВХОД."""
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir(exist_ok=True)
    doc: dict = {}
    if stamp is ...:
        doc["generated_at"] = (_NOW - timedelta(hours=age_h)).isoformat()
    elif stamp is not None:
        doc["generated_at"] = stamp
    if sections is ...:
        doc["sections"] = {} if section is None else {
            "conservative_expected_apy": section}
    elif sections is not None:
        doc["sections"] = sections
    (tmp_path / "data" / "analytics_summary.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return ca._probe_conservative_expected_apy_published(None, now=_NOW)


class TestWholeContourIsGreen:
    def test_registered_under_its_name(self):
        assert PROBES["conservative_expected_apy_published"] is \
            ca._probe_conservative_expected_apy_published
        # Проба НЕ проходит подстрокой (ADR-333): имя ищется целиком.
        assert "conservative_expected_apy" not in PROBES

    def test_green_on_the_whole_contour(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch)
        assert state == SATISFIED, why
        assert "2 из 3" in why

    def test_a_coincidence_of_displayed_and_expected_is_not_a_failure(
            self, tmp_path, monkeypatch):
        """Совпадение законно (нулевые стимулы, нулевой разброс) — вердикт зелён.

        Обратное запирало бы критерий на сегодняшнем составе данных, а не на
        работе формулы.
        """
        sec = json.loads(json.dumps(_WHOLE_SECTION))
        for row in sec["opportunities"][:2]:
            row["gap_pp"] = 0.0
        assert _ask(tmp_path, monkeypatch, section=sec)[0] == SATISFIED


class TestEveryBrokenLinkIsRedAndNamed:
    def test_no_artifact_at_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
        state, why = ca._probe_conservative_expected_apy_published(None, now=_NOW)
        assert state == UNMEASURED and "нет в этом дереве" in why

    def test_artifact_unparsable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "analytics_summary.json").write_text("{", encoding="utf-8")
        state, why = ca._probe_conservative_expected_apy_published(None, now=_NOW)
        assert state == UNMEASURED and "не разобран" in why

    def test_no_stamp_means_age_unmeasured(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch, stamp=None)
        assert state == UNMEASURED and "generated_at" in why

    def test_stale_artifact_is_unmeasured_not_satisfied(self, tmp_path, monkeypatch):
        """ОДИН и тот же контур, сдвинут только срок ⇒ вердикт меняется."""
        fresh = _ask(tmp_path, monkeypatch, age_h=1.0)
        stale = _ask(tmp_path, monkeypatch, age_h=APY_CENSUS_MAX_AGE_H + 1.0)
        assert fresh[0] == SATISFIED
        assert stale[0] == UNMEASURED and "протух" in stale[1]

    def test_section_absent_is_unmeasured_not_not_satisfied(self, tmp_path,
                                                            monkeypatch):
        """Доставка кода и его работа в проде — ДВА события."""
        state, why = _ask(tmp_path, monkeypatch, section=None)
        assert state == UNMEASURED and "ещё не производил" in why

    def test_section_errored_in_the_cycle(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch,
                          section={"status": "ERROR", "error": "ValueError: x"})
        assert state == UNMEASURED and "упала в цикле" in why

    def test_section_reported_unmeasured_itself(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch,
                          section={"status": "SKIPPED", "verdict": "UNMEASURED",
                                   "unmeasured": ["вход не прочитан"]})
        assert state == UNMEASURED and "вход не прочитан" in why

    def test_counts_missing_is_unmeasured(self, tmp_path, monkeypatch):
        sec = {k: v for k, v in _WHOLE_SECTION.items() if k != "counts"}
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "нулём не является" in why

    def test_zero_opportunities_is_unmeasured_not_clean(self, tmp_path, monkeypatch):
        sec = json.loads(json.dumps(_WHOLE_SECTION))
        sec["counts"]["adapters"] = 0
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "пустого набора" in why

    def test_a_silent_none_is_NOT_SATISFIED_and_names_the_adapter(
            self, tmp_path, monkeypatch):
        """ГЛАВНОЕ звено: пробел БЕЗ названной причины (инв. #17)."""
        sec = json.loads(json.dumps(_WHOLE_SECTION))
        sec["opportunities"][2].pop("expected_unmeasured")
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED
        assert "c" in why and "БЕЗ названной причины" in why

    def test_a_persistence_reason_also_counts_as_named(self, tmp_path, monkeypatch):
        sec = json.loads(json.dumps(_WHOLE_SECTION))
        sec["opportunities"][2].pop("expected_unmeasured")
        sec["opportunities"][2]["persistence_unmeasured"] = "наблюдений 3"
        assert _ask(tmp_path, monkeypatch, section=sec)[0] == SATISFIED

    def test_blind_axes_list_absent_is_unmeasured(self, tmp_path, monkeypatch):
        sec = {k: v for k, v in _WHOLE_SECTION.items() if k != "blind_axes"}
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "ответом об осях не является" in why

    def test_a_mute_blind_axis_is_NOT_SATISFIED(self, tmp_path, monkeypatch):
        sec = json.loads(json.dumps(_WHOLE_SECTION))
        sec["blind_axes"][1].pop("detail")
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED and "utilization_trend" in why

    def test_nothing_measured_at_all_is_NOT_SATISFIED(self, tmp_path, monkeypatch):
        sec = json.loads(json.dumps(_WHOLE_SECTION))
        sec["counts"]["expected_measured"] = 0
        for row in sec["opportunities"]:
            row["conservative_expected_apy_pct"] = None
            row["expected_unmeasured"] = "состав ставки НЕ ИЗМЕРЕН"
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED and "не работает ни на чём" in why
