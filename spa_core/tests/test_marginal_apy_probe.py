"""Контроль пробы приёмки `marginal_apy_ladder_published` (ADR-955, §12 ТЗ).

Правило `.claude/rules/acceptance.md`, п. 3: проба регистрируется ТОЛЬКО с
тестом, где она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с
названным звеном, — и где она НЕ проходит подстрокой (ADR-333).
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом, отметка сцены
# ПРОИСХОДИТ от него (`_NOW - timedelta(...)`), и сам `_NOW` уезжает в пробу
# аргументом `now=`: обе стороны сравнения срока закреплены, календарь хоста на
# вердикт не влияет. Подпроцессов проба не поднимает — второй двери к часам нет.
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring.card_acceptance import (
    APY_CENSUS_MAX_AGE_H,
    NOT_SATISFIED,
    PROBES,
    SATISFIED,
    UNMEASURED,
)

_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)

_AXES = [
    {"axis": a, "owner_words": a, "state": "empty",
     "detail": f"{a}: файл есть и ПУСТ", "why": "писателя нет"}
    for a in ("tvl_dilution", "utilization", "capacity", "deposit_caps",
              "liquidity", "withdrawal_depth")
] + [
    {"axis": "reward_dilution", "owner_words": "reward dilution",
     "state": "credited", "detail": "привязано, свежо и читается",
     "why": "единственная измеримая ось семёрки"},
]

_WHOLE_SECTION = {
    "status": "OK",
    "engine": "marginal_apy_ladder",
    "is_advisory": True,
    "declared": {"rungs_usd": [5000.0, 10000.0, 20000.0, 40000.0]},
    "axes": _AXES,
    "axes_credited": 1,
    "counts": {"opportunities": 3, "ladder_measured": 2,
               "ladder_unmeasured": 1, "axes_with_fixture_subject": 3},
    "opportunities": [
        {"adapter_id": "a", "rungs": [{"amount_usd": 5000.0,
                                       "apy_upper_pct": 5.0,
                                       "apy_lower_pct": 4.9}]},
        {"adapter_id": "b", "rungs": [{"amount_usd": 5000.0,
                                       "apy_upper_pct": 3.0,
                                       "apy_lower_pct": 2.9}]},
        {"adapter_id": "c", "unmeasured": "TVL не живой — запрет ADR-053"},
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
            "marginal_apy_ladder": section}
    elif sections is not None:
        doc["sections"] = sections
    (tmp_path / "data" / "analytics_summary.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return ca._probe_marginal_apy_ladder_published(None, now=_NOW)


def _broken(**over) -> dict:
    sec = copy.deepcopy(_WHOLE_SECTION)
    sec.update(over)
    return sec


class TestWholeContourIsGreen:
    def test_registered_under_its_name(self):
        assert PROBES["marginal_apy_ladder_published"] is \
            ca._probe_marginal_apy_ladder_published
        # НЕ проходит подстрокой (ADR-333): имя ищется целиком.
        assert "marginal_apy_ladder" not in PROBES
        assert "marginal_apy" not in PROBES

    def test_green_on_the_whole_contour(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch)
        assert state == SATISFIED, why
        assert "2 из 3" in why
        assert "учтено 1 из 7" in why
        assert "ВЫДУМАН у 3" in why


class TestEachBrokenLinkIsRed:
    """Одно порванное звено за раз, и имя звена — в названии теста."""

    def test_link__no_artifact_at_all(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
        (tmp_path / "data").mkdir(exist_ok=True)
        state, why = ca._probe_marginal_apy_ladder_published(None, now=_NOW)
        assert state == UNMEASURED and "нет в этом дереве" in why

    def test_link__artifact_unparseable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "data" / "analytics_summary.json").write_text("{битый",
                                                                  encoding="utf-8")
        state, why = ca._probe_marginal_apy_ladder_published(None, now=_NOW)
        assert state == UNMEASURED and "не разобран" in why

    def test_link__no_generated_at(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch, stamp=None)
        assert state == UNMEASURED and "возраст не измерен" in why

    def test_link__stale_artifact_is_UNMEASURED_not_green(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch, age_h=APY_CENSUS_MAX_AGE_H + 1)
        assert state == UNMEASURED and "протух" in why

    def test_link__section_absent_is_UNMEASURED_not_NOT_SATISFIED(self, tmp_path,
                                                                  monkeypatch):
        # Доставка кода и его работа в проде — ДВА события.
        state, why = _ask(tmp_path, monkeypatch, section=None)
        assert state == UNMEASURED and "ещё не производил" in why

    def test_link__section_errored_in_the_cycle(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch,
                          section={"status": "ERROR", "error": "boom"})
        assert state == UNMEASURED and "boom" in why

    def test_link__section_reports_itself_unmeasured(self, tmp_path, monkeypatch):
        state, why = _ask(tmp_path, monkeypatch,
                          section={"status": "SKIPPED", "verdict": "UNMEASURED",
                                   "unmeasured": ["adapter_status.json не прочитан"]})
        assert state == UNMEASURED and "adapter_status.json" in why

    def test_link__counts_missing(self, tmp_path, monkeypatch):
        sec = _broken()
        del sec["counts"]
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "нулём не является" in why

    def test_link__zero_opportunities_is_UNMEASURED(self, tmp_path, monkeypatch):
        sec = _broken(counts={"opportunities": 0, "ladder_measured": 0,
                              "axes_with_fixture_subject": 0})
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "ни одной возможности" in why

    def test_link__SILENT_gap_is_NOT_SATISFIED(self, tmp_path, monkeypatch):
        # Возможность без лестницы И без причины — молчаливый пропуск (инв. #17).
        sec = _broken()
        sec["opportunities"][2] = {"adapter_id": "c"}
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED
        assert "БЕЗ названной причины" in why and "c" in why

    def test_link__axes_list_absent(self, tmp_path, monkeypatch):
        sec = _broken()
        del sec["axes"]
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "семь" in why

    def test_link__SIX_axes_instead_of_seven(self, tmp_path, monkeypatch):
        sec = _broken(axes=_AXES[:-1])
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "семь" in why

    def test_link__an_axis_without_a_state_is_NOT_SATISFIED(self, tmp_path,
                                                            monkeypatch):
        sec = _broken()
        sec["axes"] = copy.deepcopy(_AXES)
        sec["axes"][0] = {"axis": "tvl_dilution", "detail": "", "why": "x"}
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED and "tvl_dilution" in why

    def test_link__an_axis_without_a_reason_in_WORDS_is_NOT_SATISFIED(
            self, tmp_path, monkeypatch):
        sec = _broken()
        sec["axes"] = copy.deepcopy(_AXES)
        sec["axes"][1]["why"] = ""
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED and "utilization" in why

    def test_link__rungs_not_declared(self, tmp_path, monkeypatch):
        sec = _broken(declared={"rungs_usd": [5000.0]})
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == UNMEASURED and "без названного размера" in why

    def test_link__nothing_measured_is_NOT_SATISFIED(self, tmp_path, monkeypatch):
        sec = _broken(counts={"opportunities": 3, "ladder_measured": 0,
                              "ladder_unmeasured": 3,
                              "axes_with_fixture_subject": 3})
        sec["opportunities"] = [{"adapter_id": n, "unmeasured": "нет живого TVL"}
                                for n in ("a", "b", "c")]
        state, why = _ask(tmp_path, monkeypatch, section=sec)
        assert state == NOT_SATISFIED and "ни одной лестницы" in why


class TestWhatTheProbeDeliberatelyDoesNotDemand:
    def test_one_credited_axis_of_seven_is_still_GREEN(self, tmp_path, monkeypatch):
        """Доля учтённых осей лежит у ПИСАТЕЛЕЙ данных, не у читателя формулы:
        порог здесь запер бы приёмку на чужой работе."""
        sec = _broken(axes_credited=1)
        state, _ = _ask(tmp_path, monkeypatch, section=sec)
        assert state == SATISFIED

    def test_zero_credited_axes_is_still_GREEN_if_each_is_NAMED(self, tmp_path,
                                                                monkeypatch):
        sec = _broken(axes_credited=0)
        sec["axes"] = [dict(a, state="empty") for a in _AXES]
        state, _ = _ask(tmp_path, monkeypatch, section=sec)
        assert state == SATISFIED

    def test_the_neighbour_section_alone_does_NOT_satisfy_this_probe(
            self, tmp_path, monkeypatch):
        # Секция §10/§11 на месте, своей — нет: подстроки имени не хватает.
        state, why = _ask(tmp_path, monkeypatch, sections={
            "conservative_expected_apy": {"status": "OK"}})
        assert state == UNMEASURED and "ещё не производил" in why
