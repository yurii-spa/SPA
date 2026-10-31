"""Три критерия go-live спрашивают ПИСАТЕЛЯ, а не присутствие файла (ADR-878).

Решение ВЛАДЕЛЬЦА 31.10, вариант 1 — карточка
`inbox-tri-kriteriya-go-live-perepisat-na-nasto`, находка ADR-876.

У каждой проверки здесь есть ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: тест, который воспроизводит
дефект дословно и краснеет (`.claude/rules/deployment.md` § «Проверка сторожа
сторожей»). Три двери — три порванных звена, и каждое НАЗЫВАЕТСЯ: мера, не
увидевшая возврата одной двери к присутствию, объявляла бы починенными все три по
зелени двух.

Часы инъектированы во ВСЕ тесты: литеральных дат в файле нет вовсе, окна свежести
считаются от переданного `now`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.analytics import golive_readiness_report as grr
from spa_core.golive import checklist
from spa_core.monitoring import golive_producer_criteria as m

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
# FROZEN-DATE-OK: injected-clock — это ЯКОРЬ, который передаётся дверям аргументом
# `now=`; ни одна проверка файла не спрашивает стенные часы, поэтому календарь
# сдвинуть вердикт не может.


# ── 1. мера различает направления на НАСТОЯЩИХ дверях ────────────────────────

def test_the_measure_says_measured_on_the_real_doors():
    report = m.drive_both_directions(now=NOW)
    assert report["kind"] == m.DRIVE_OK, report.get("reason")
    assert report["same_answers"] == []


def test_the_live_scene_awards_every_writer_point_and_the_dead_scene_none():
    report = m.drive_both_directions(now=NOW)
    assert (report["live"]["writer_points"], report["dead"]["writer_points"]) == (6.0, 0.0)


def test_the_dead_scene_is_not_an_empty_scene():
    """Мёртвая сцена несёт ВСЕ git-tracked исходники — иначе мерилось бы другое.

    Именно на этом была зелёной прежняя батарея: она удаляла ИСХОДНИК и видела
    −2 балла, то есть подтверждала присутствие, а не наблюдение.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        m._scene(root, writer_alive=False, now=NOW)
        missing = [rel for rel in m._TRACKED_SOURCES if not (root / rel).exists()]
        assert missing == [], missing
        assert not (root / "data" / "t1_verification.json").exists()
        assert not (root / "data" / "promotion_decisions.json").exists()


# ── 2. положительные контроли: КАЖДАЯ дверь, вернувшаяся к присутствию ────────

def _presence_based_data_sources(self, now=None):
    """Дверь №1 дословно до ADR-878: баллы за присутствие исходников."""
    score = 4.0  # два балла CLEAN-источников сцена даёт одинаково
    for rel in ("spa_core/utils/defillama.py",
                "spa_core/analytics/t1_data_verifier.py",
                "spa_core/analytics/strategy_promoter.py"):
        if (self.base_dir / rel).exists():
            score += 2.0
    return grr.CategoryScore("data_sources", score, 10.0, [], [])


def test_the_measure_catches_data_sources_returning_to_presence(monkeypatch):
    monkeypatch.setattr(grr.GoLiveReadinessReport, "assess_data_sources",
                        _presence_based_data_sources)
    report = m.drive_both_directions(now=NOW)
    assert report["kind"] == m.DRIVE_BLIND, report
    assert any("баллы за писателя не упали" in s for s in report["same_answers"]), \
        report["same_answers"]


def test_the_measure_catches_wallet_returning_to_the_sentinel(monkeypatch):
    """Дверь №2 дословно до ADR-878: метка читается как подпись владельца."""
    def _sentinel_is_a_signature(data_dir=None):
        base = Path(data_dir) if data_dir else Path(".")
        if (base / "wallet_ready_approved.json").exists() or \
                (base / "wallet_ready.sentinel").exists():
            return {"name": "Wallet Ready", "status": "PASS", "value": "verified",
                    "threshold": "manual_setup", "note": "confirmed by owner"}
        return {"name": "Wallet Ready", "status": "PENDING", "value": "not_verified",
                "threshold": "manual_setup", "note": ""}
    monkeypatch.setattr(checklist, "check_wallet_ready", _sentinel_is_a_signature)
    report = m.drive_both_directions(now=NOW)
    assert report["kind"] == m.DRIVE_BLIND, report
    assert any("вердикт кошелька не различает" in s for s in report["same_answers"]), \
        report["same_answers"]


def test_the_measure_catches_check_files_returning_to_presence(tmp_path, monkeypatch):
    """Дверь №3 дословно до ADR-878: `n_pass` за присутствие И РАЗМЕР.

    Подменяется САМ ФАЙЛ двери (её мера ввозит его по пути), поэтому контроль
    меряет проводку, а не копию логики рядом.
    """
    stand_in = tmp_path / "cycle_dry_run.py"
    stand_in.write_text(
        "import os\n"
        "ROOT = '.'\n"
        "REQUIRED = ['data/golive_status.json', 'data/paper_evidence.json',\n"
        "            'data/tournament_ranking.json', 'data/adapter_status.json']\n"
        "def check_files(now=None):\n"
        "    n = sum(1 for r in REQUIRED if os.path.isfile(os.path.join(ROOT, r))\n"
        "            and os.path.getsize(os.path.join(ROOT, r)) > 0)\n"
        "    return n, len(REQUIRED) - n, 0\n",
        encoding="utf-8")
    original = m._measure_scene

    def _measure_with_stand_in(root, *, now):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_cdr_stand_in", str(stand_in))
        cdr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cdr)
        cdr.ROOT = str(root)
        base = original(root, now=now)
        p, f, u = cdr.check_files(now=now)
        base.update({"files_pass": p, "files_fail": f, "files_unmeasured": u})
        return base

    monkeypatch.setattr(m, "_measure_scene", _measure_with_stand_in)
    report = m.drive_both_directions(now=NOW)
    assert report["kind"] == m.DRIVE_BLIND, report
    assert any("судятся присутствием" in s for s in report["same_answers"]), \
        report["same_answers"]


def test_an_unraisable_scene_is_unmeasured_and_never_blind(monkeypatch):
    """Третий исход СВОЙ: «сцену не поднял» ≠ «мера слепа»."""
    def _boom(root, *, writer_alive, now):
        raise OSError("сцену выложить не вышло (контроль)")
    monkeypatch.setattr(m, "_scene", _boom)
    report = m.drive_both_directions(now=NOW)
    assert report["kind"] == m.DRIVE_UNMEASURED
    assert "сцену выложить не вышло" in report["reason"]


# ── 3. третий исход у КАЖДОЙ двери (инвариант #17) ───────────────────────────

def _live_tree(root: Path) -> None:
    m._scene(root, writer_alive=True, now=NOW)


def test_data_sources_names_an_unreadable_artifact_as_unmeasured(tmp_path):
    _live_tree(tmp_path)
    (tmp_path / "data" / "t1_verification.json").write_text("{битый", encoding="utf-8")
    cat = grr.GoLiveReadinessReport(base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    assert len(cat.items_unmeasured) == 1, cat.items_unmeasured
    assert "НЕ ИЗМЕРЕНО" in cat.items_unmeasured[0]
    # «нечем судить» баллов НЕ даёт и в «не выполнено» не прячется
    assert cat.score == 8.0
    assert not any("Верификатор T1" in i for i in cat.items_pending)


def test_data_sources_tells_a_missing_writer_from_an_unreadable_one(tmp_path):
    """Два РАЗНЫХ исхода, и они не склеены: писателя нет · судить нечем."""
    _live_tree(tmp_path)
    (tmp_path / "data" / "t1_verification.json").unlink()
    absent = grr.GoLiveReadinessReport(
        base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    (tmp_path / "data" / "t1_verification.json").write_text("{", encoding="utf-8")
    broken = grr.GoLiveReadinessReport(
        base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    assert (len(absent.items_unmeasured), len(broken.items_unmeasured)) == (0, 1)
    assert any("прогона НЕ БЫЛО" in i for i in absent.items_pending)
    assert absent.score == broken.score == 8.0


def test_data_sources_withholds_the_point_from_a_stale_verifier_run(tmp_path):
    _live_tree(tmp_path)
    old = (NOW - timedelta(hours=grr.SOURCE_OBSERVATION_WINDOW_H + 1.0)).isoformat()
    (tmp_path / "data" / "t1_verification.json").write_text(
        json.dumps({"verified_at": old}), encoding="utf-8")
    cat = grr.GoLiveReadinessReport(base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    assert cat.score == 8.0
    assert any("вне окна" in i for i in cat.items_pending), cat.items_pending


def test_data_sources_clock_is_an_input_not_the_wall(tmp_path):
    """Тот же диск, РАЗНЫЕ часы — разный ответ. Так доказывается инъекция."""
    _live_tree(tmp_path)
    inside = grr.GoLiveReadinessReport(
        base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    later = grr.GoLiveReadinessReport(base_dir=str(tmp_path)).assess_data_sources(
        now=NOW + timedelta(hours=grr.SOURCE_OBSERVATION_WINDOW_H + 2.0))
    assert inside.score > later.score, (inside.score, later.score)


def test_wallet_refuses_an_approval_without_a_signature(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "wallet_ready_approved.json").write_text(
        json.dumps({"approved": True}), encoding="utf-8")
    verdict = checklist.check_wallet_ready(data_dir=str(data))
    assert (verdict["status"], verdict["value"]) == ("WARN", "unmeasured")
    assert "approved_by" in verdict["note"]


def test_wallet_accepts_a_recorded_signature(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "wallet_ready_approved.json").write_text(
        json.dumps({"approved": True, "approved_by": "@yurii",
                    "approved_at": NOW.isoformat()}), encoding="utf-8")
    verdict = checklist.check_wallet_ready(data_dir=str(data))
    assert (verdict["status"], verdict["value"]) == ("PASS", "approved")


def test_wallet_tells_a_bare_mark_from_nothing_at_all(tmp_path):
    """Три исхода различимы: подпись · метка без подписи · ничего."""
    data = tmp_path / "data"
    data.mkdir(parents=True)
    nothing = checklist.check_wallet_ready(data_dir=str(data))
    (data / "wallet_ready.sentinel").write_text(NOW.isoformat(), encoding="utf-8")
    mark = checklist.check_wallet_ready(data_dir=str(data))
    assert nothing["status"] == "PENDING" and nothing["value"] == "not_verified"
    assert mark["status"] == "WARN" and mark["value"] == "mark_without_signature"
    assert mark["status"] != "PASS", "метка подписаться за владельца не вправе (инв. #14)"


def test_check_files_calls_a_stampless_artifact_unmeasured(tmp_path):
    cdr = _load_cycle_dry_run(tmp_path)
    _live_tree(tmp_path)
    (tmp_path / "data" / "golive_status.json").write_text(
        json.dumps({"ready": False}), encoding="utf-8")   # отметки нет вовсе
    n_pass, n_fail, n_unmeasured = cdr.check_files(now=NOW)
    assert (n_pass, n_fail, n_unmeasured) == (3, 0, 1)


def test_check_files_refuses_a_stamp_from_the_future(tmp_path):
    cdr = _load_cycle_dry_run(tmp_path)
    _live_tree(tmp_path)
    (tmp_path / "data" / "golive_status.json").write_text(
        json.dumps({"timestamp": (NOW + timedelta(hours=9)).isoformat()}),
        encoding="utf-8")
    n_pass, n_fail, n_unmeasured = cdr.check_files(now=NOW)
    assert (n_pass, n_fail, n_unmeasured) == (3, 1, 0)


def test_check_files_size_alone_no_longer_passes(tmp_path):
    """Дословный предмет находки: непустой файл БЕЗ живого писателя не PASS."""
    cdr = _load_cycle_dry_run(tmp_path)
    m._scene(tmp_path, writer_alive=False, now=NOW)
    sizes = [(tmp_path / rel).stat().st_size for rel in cdr.WRITER_STAMP]
    assert all(s > 0 for s in sizes), sizes      # размер есть у каждого
    assert cdr.check_files(now=NOW)[0] == 0      # а PASS нет ни у одного


def _load_cycle_dry_run(root: Path):
    import importlib.util
    here = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_cdr_test", str(here / "scripts" / "cycle_dry_run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = str(root)
    return module


# ── 4. две дыры, найденные мутационным прогоном (#996) ───────────────────────
#
# Обе НАСТОЯЩИЕ, не эквивалентные: мутант менял НАБЛЮДАЕМЫЙ выход, и ни одно имя
# батареи не падало. Добавлены по вердикту прибора, а не «на всякий случай».

def test_data_sources_names_a_present_artifact_without_a_stamp(tmp_path):
    """Артефакт ЕСТЬ и разбирается, а отметки в нём НЕТ — это НЕ свежий прогон.

    Мутант `_age_hours`: вместо `None` возвращать `0.0`. Тогда артефакт без
    `verified_at` читается как «прогон минуту назад» и получает балл — отсутствие
    наблюдения выдано за самое свежее из возможных (инв. #17). Соседний тест про
    НЕЧИТАЕМЫЙ артефакт эту дверь не проходит: он отказывает раньше, в
    `_read_artifact`.
    """
    _live_tree(tmp_path)
    (tmp_path / "data" / "t1_verification.json").write_text(
        json.dumps({"results": [], "all_pass": True}), encoding="utf-8")
    cat = grr.GoLiveReadinessReport(base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    assert cat.score == 8.0, cat.items_done
    assert any("verified_at" in i for i in cat.items_unmeasured), cat.items_unmeasured


def test_data_sources_names_a_stampless_feed_row_without_awarding_it(tmp_path):
    """Та же дыра на оси фида: `live_apy_fresh` без `live_apy_as_of` — не балл."""
    _live_tree(tmp_path)
    (tmp_path / "data" / "adapter_status.json").write_text(json.dumps({
        "generated_at": NOW.isoformat(), "feed_reachable": True,
        "adapters": {"aave_v3": {"live_apy": 5.39, "live_apy_fresh": True}},
    }), encoding="utf-8")
    cat = grr.GoLiveReadinessReport(base_dir=str(tmp_path)).assess_data_sources(now=NOW)
    assert cat.score == 8.0, cat.items_done
    assert any("ни одного адаптера" in i for i in cat.items_pending), cat.items_pending


def test_cycle_dry_run_main_returns_two_when_something_is_unmeasured(tmp_path,
                                                                     monkeypatch):
    """Код возврата различает ТРИ исхода, а не два (ADR-878, инв. #17).

    Мутант: `return 2 if f_unmeasured else 0` → `return 0`. Выжил, потому что
    `main()` не звал НИКТО: «не измерено» становилось неотличимо от чистого
    прогона у ЕДИНСТВЕННОГО читателя, который у этого скрипта есть, — кода
    возврата. Соседние проверки меряют `check_files`, а не её читателя.
    """
    cdr = _load_cycle_dry_run(tmp_path)
    monkeypatch.setattr(cdr, "check_adapters", lambda: (1, 0))
    monkeypatch.setattr(cdr, "check_strategies", lambda: (1, 0))
    monkeypatch.setattr(cdr, "check_evidence_tracker", lambda: (1, 0))

    monkeypatch.setattr(cdr, "check_files", lambda now=None: (3, 0, 1))
    assert cdr.main() == 2, "«не измерено» обязано отличаться от чистого прогона"

    monkeypatch.setattr(cdr, "check_files", lambda now=None: (4, 0, 0))
    assert cdr.main() == 0

    monkeypatch.setattr(cdr, "check_files", lambda now=None: (3, 1, 0))
    assert cdr.main() == 1, "FAIL обязан остаться единицей"
