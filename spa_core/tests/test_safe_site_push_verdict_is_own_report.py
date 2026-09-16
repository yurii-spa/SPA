#!/usr/bin/env python3
"""Вопрос владельцу об одобрении рождается ТОЛЬКО из отчёта этого запуска, и только
когда в нём есть что одобрять.

Замер (карточка `owner-decision-sait-pravka-avtonomnaya-pravka-zadela-ow`, переслана
владельцем 16.09): заголовок «Сайт: правка — …» вместо имени файла и ПУСТОЕ поле
`approves:`. Такая карточка — вопрос ни о чём: `check_owner_gate._approved_scope` снимает
нарушения только по scope из этого поля, и «Одобрить» владельца не разрешило бы ни одного
файла. Причина: пушер брал вердикт из КОДА ВОЗВРАТА (2 = GATED), а список файлов — из
ОБЩЕГО `data/owner_gate_check.json`, который пишет каждый прогон гейта в дереве. Две двери
к одному исходу, обе воспроизведены ниже:

  1. код 2 от argparse (usage-error старого гейта), отчёт при этом не пишется вовсе;
  2. код 2 честный, но общий файл к моменту чтения переписан чужим CLEAN-прогоном.

Ни один тест здесь не трогает живой трекер, живое `data/` и Телеграм: карточка и
уведомление перехватываются, гейт — либо подставной скрипт в tmp, либо настоящий, но
пишущий отчёт в tmp.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_REAL_GUARD = _REPO / "scripts" / "check_owner_gate.py"

_GATED_FILE = "landing/src/pages/packages.astro"
_VIOLATION = {"klass": "E", "file": _GATED_FILE, "line": 1,
              "rule": "honesty.token.removed", "matched_text": "RESEARCH", "change": "removed"}


@pytest.fixture()
def ssp():
    path = _REPO / "scripts" / "safe_site_push.py"
    spec = importlib.util.spec_from_file_location("safe_site_push_verdict_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_guard(tmp_path: Path) -> Path:
    """Подставной гейт. Режим — через env FAKE_GUARD_MODE:

    * ``gated-with-report`` — честный GATED: пишет отчёт с одним нарушением ТУДА, куда
      просили (`--report-path`), и выходит с кодом 2;
    * ``exit2-no-report`` — форма usage-error: код 2, не написано ничего.

    Общий `data/owner_gate_check.json` подставной гейт НЕ трогает — его «чужое» содержимое
    кладёт сам тест.
    """
    guard = tmp_path / "fake_guard.py"
    guard.write_text(textwrap.dedent(f"""
        import argparse, json, os, sys
        ap = argparse.ArgumentParser()
        ap.add_argument("--diff-mode"); ap.add_argument("--files", nargs="*")
        ap.add_argument("--commit-message"); ap.add_argument("--report", action="store_true")
        ap.add_argument("--report-path")
        a = ap.parse_args()
        mode = os.environ["FAKE_GUARD_MODE"]
        if mode == "gated-with-report":
            with open(a.report_path, "w", encoding="utf-8") as fh:
                json.dump({{"ok": False, "gated_count": 1,
                           "violations": [{json.dumps(_VIOLATION, ensure_ascii=False)}]}}, fh)
            sys.exit(2)
        if mode == "exit2-no-report":
            sys.exit(2)
        raise SystemExit(f"unknown FAKE_GUARD_MODE {{mode}}")
    """), encoding="utf-8")
    return guard


def _stage(ssp, monkeypatch, tmp_path: Path, mode: str):
    """Пушер поверх одноразового «репо» с ЧУЖИМ CLEAN-отчётом в общем файле."""
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "owner_gate_check.json").write_text(json.dumps(
        {"ok": True, "gated_count": 0, "violations": [],
         "site_paths": ["landing/src/data/track_snapshot.json"]}), encoding="utf-8")
    monkeypatch.setattr(ssp, "_REPO_ROOT", repo)
    monkeypatch.setattr(ssp, "_GUARD", _fake_guard(tmp_path))
    monkeypatch.setenv("FAKE_GUARD_MODE", mode)

    created: list[dict] = []
    notified: list[list] = []
    real_run = subprocess.run

    def selective_run(cmd, *a, **k):
        # Подставной гейт исполняется по-настоящему; всё остальное (notify) — перехват.
        if any(str(c).endswith("fake_guard.py") for c in cmd):
            return real_run(cmd, *a, **k)
        notified.append(list(cmd))

        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(ssp.subprocess, "run", selective_run)
    monkeypatch.setattr("spa_core.owner_queue.queue.create_card",
                        lambda **kw: created.append(kw) or (tmp_path / "own-probe.md"))
    monkeypatch.setattr(ssp, "_open_card_with_fingerprint", lambda fp: None)
    return created, notified


# ── дверь 2: общий файл переписан чужим прогоном ─────────────────────────────


def test_the_verdict_comes_from_this_runs_report_not_from_the_shared_file(
        ssp, monkeypatch, tmp_path):
    """Положительный контроль живого случая. Общий файл говорит CLEAN (чужой прогон по
    снимку трека), гейт ЭТОГО запуска говорит GATED по packages.astro. До правки пушер
    читал общий файл: карточка «Сайт: правка — …» с пустым `approves:`.
    """
    created, notified = _stage(ssp, monkeypatch, tmp_path, "gated-with-report")

    rc = ssp.main(["--files", _GATED_FILE, "--message", "packages: правка статусов"])

    assert rc == 2, "честный GATED остаётся кодом 2"
    assert len(created) == 1, "вопрос владельцу обязан родиться"
    card = created[0]
    assert card["extra_fields"] == {"approves": _GATED_FILE}, \
        "scope одобрения — файл из отчёта ЭТОГО запуска, а не пустота из чужого"
    assert "packages.astro" in card["title"]
    assert "Сайт: правка —" not in card["title"], "заголовок не должен притворяться"
    assert "honesty.token.removed" in card["body"]
    assert len(notified) == 1, "владельца уведомили ровно один раз"


# ── дверь 1: код 2 без отчёта (usage-error старого гейта / крах до записи) ──


def test_exit_2_without_a_report_is_not_a_question_to_the_owner(ssp, monkeypatch, tmp_path):
    """Код 2, а отчёт этого запуска не написан. Общий файл при этом есть и CLEAN — до
    правки ровно это давало карточку с пустым scope. Теперь: не GATED, а ошибка
    инструмента — код 1, пуша нет, вопроса владельцу нет (одобрять нечего).
    """
    created, notified = _stage(ssp, monkeypatch, tmp_path, "exit2-no-report")

    rc = ssp.main(["--files", _GATED_FILE, "--message", "packages: правка статусов"])

    assert rc == 1, "код 2 без вердикта — ошибка инструмента, fail-CLOSED"
    assert created == [], "карточка «одобри ноль файлов» не должна родиться"
    assert notified == [], "и владельцу нечего слать"


def test_a_usage_error_of_the_real_guard_is_not_the_gated_code(tmp_path):
    """Сам гейт: неизвестный флаг — код 1, не 2. Замер до правки: argparse выходил с 2,
    неотличимо от GATED. `--report-path` в tmp, чтобы прогон не трогал общий файл.
    """
    r = subprocess.run(
        [sys.executable, str(_REAL_GUARD), "--diff-mode", "files",
         "--files", "landing/src/pages/__no_such_file__.astro",
         "--report-path", str(tmp_path / "r.json"), "--bogus-flag"],
        cwd=str(_REPO), capture_output=True, text=True,
    )
    assert r.returncode == 1, r.stderr
    assert "unrecognized arguments" in r.stderr
    assert not (tmp_path / "r.json").exists(), "usage-error не пишет отчёта"


def test_the_real_guard_writes_this_runs_report_where_asked(tmp_path):
    """`--report-path` без `--report`: отчёт ложится ровно туда, куда просили, и несёт
    ключ `violations` — то, из чего пушер строит scope. Общий `data/` не трогается.
    """
    own = tmp_path / "own" / "r.json"
    r = subprocess.run(
        [sys.executable, str(_REAL_GUARD), "--diff-mode", "files",
         "--files", "landing/src/pages/__no_such_file__.astro",
         "--report-path", str(own)],
        cwd=str(_REPO), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(own.read_text(encoding="utf-8"))
    assert report["model"] == "owner_gate_check"
    assert isinstance(report["violations"], list)


# ── сам генератор карточки: пустой scope ⇒ карточки нет ─────────────────────


@pytest.mark.parametrize("report", [
    {},
    {"violations": []},
    {"violations": [{"klass": "E", "rule": "honesty.token.removed"}]},   # без `file`
    {"violations": "not-a-list"},
])
def test_route_to_owner_card_refuses_an_empty_scope(ssp, monkeypatch, tmp_path, report):
    """Единственная точка рождения карточки отказывает, когда одобрять нечего —
    независимо от того, кто и как её позвал.
    """
    created = []
    notified = []
    monkeypatch.setattr("spa_core.owner_queue.queue.create_card",
                        lambda **kw: created.append(kw) or (tmp_path / "own.md"))
    monkeypatch.setattr(ssp.subprocess, "run", lambda *a, **k: notified.append(a))
    monkeypatch.setattr(ssp, "_open_card_with_fingerprint", lambda fp: None)

    assert ssp._route_to_owner_card([_GATED_FILE], report, "m") is False
    assert created == [] and notified == []


def test_route_to_owner_card_with_a_real_scope_still_asks(ssp, monkeypatch, tmp_path):
    """Обратный контроль: отказ не стал глухотой — настоящее нарушение по-прежнему
    рождает вопрос с непустым scope.
    """
    created = []
    monkeypatch.setattr("spa_core.owner_queue.queue.create_card",
                        lambda **kw: created.append(kw) or (tmp_path / "own.md"))
    monkeypatch.setattr(ssp.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(ssp, "_open_card_with_fingerprint", lambda fp: None)

    assert ssp._route_to_owner_card([_GATED_FILE], {"violations": [_VIOLATION]}, "m") is True
    assert created[0]["extra_fields"] == {"approves": _GATED_FILE}


def test_gated_files_is_the_scope_and_ignores_junk(ssp):
    assert ssp._gated_files({"violations": [_VIOLATION, {"file": _GATED_FILE, "rule": "x"},
                                            {"rule": "no-file"}, "junk"]}) == [_GATED_FILE]
    assert ssp._gated_files({"violations": None}) == []
    assert ssp._gated_files(None) == []
