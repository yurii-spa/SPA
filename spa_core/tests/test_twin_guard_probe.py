#!/usr/bin/env python3
"""Контроль пробы приёмки `twin_guard_survives_the_intake_stamp` (ADR-866).

Правило приёмки, п. 3: новая проба регистрируется ТОЛЬКО с тестом, где она зелёная на
ЦЕЛОМ контуре и красная на КАЖДОМ порванном звене — с названным звеном
(`.claude/rules/acceptance.md`). Проба, никогда не видевшая настоящей поломки, —
украшение.

Каждое звено здесь рвётся так, как оно реально ломается:

* **дверь возвращается к ИЗМЕНЯЕМОМУ ключу** — ровно авария #981 (дверь до ADR-866
  сверяла полное тело, которое дописывает сам приём);
* **защита становится глухотой** — обратная авария: дверь склеивает всё одноимённое и
  съедает разные задания владельца;
* **третий исход схлопывается** в «близнеца нет» — молчание, выданное за ответ (инв. #17);
* **наследник рождается без ключа** — размножение не остановится и на следующем повторе;
* **читатель (шаг 0a) НЕ ИЗМЕРЕН** либо отвечает одно и то же на обе сцены — проба,
  принявшая такой ответ, подтверждала бы сама себя (ADR-333).

Литеральных дат и pid в файле нет: ни у ключа близнеца, ни у оси повтора нет понятия
свежести, и ни одного процесса проба не спрашивает.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue import queue as Q

PROBE_NAME = "twin_guard_survives_the_intake_stamp"


def _run():
    return ca.PROBES[PROBE_NAME](None)


def test_the_probe_is_registered_under_its_name():
    assert PROBE_NAME in ca.PROBES


def test_green_on_the_whole_contour():
    """Целый контур: настоящая дверь, настоящий шаг 0a, настоящая живая очередь."""
    verdict, why = _run()
    assert verdict == ca.SATISFIED, why
    assert "ось повтора шага 0a 0" in why


# ---------------------------------------------------------------------------
# Звено 1: дверь снова судит по ИЗМЕНЯЕМОМУ телу (авария #981 дословно)
# ---------------------------------------------------------------------------

def _door_before_adr_866(d: Path, base: str, tracker_type: str, body: str):
    """Дверь ДО ADR-866: ключ не читается вовсе, сверяется ПОЛНОЕ ТЕЛО."""
    wanted = (body or "").strip()
    for cand in [d / f"{base}.md"] + sorted(d.glob(f"{base}-[0-9]*.md")):
        if not cand.exists():
            continue
        try:
            card = Q.load_card(cand)
        except Exception:  # noqa: BLE001
            continue
        if (card.status or "") not in Q._OPEN_STATUSES:
            continue
        if (card.body or "").strip() == wanted:
            return Q.TwinVerdict(Q.TWIN_BY_BODY, cand, "сверено тело")
    return Q.TwinVerdict(Q.TWIN_NONE, None, "близнеца нет")


def test_red_when_the_door_goes_back_to_the_mutable_body(monkeypatch):
    monkeypatch.setattr(Q, "_open_twin", _door_before_adr_866)
    verdict, why = _run()
    assert verdict == ca.NOT_SATISFIED, why
    assert "ИЗМЕНЯЕМЫЙ" in why and "вторую" in why


# ---------------------------------------------------------------------------
# Звено 2: защита стала глухотой — склеивает всё одноимённое
# ---------------------------------------------------------------------------

def test_red_when_the_guard_becomes_deafness(monkeypatch):
    def swallow_everything(d: Path, base: str, tracker_type: str, body: str):
        for cand in [d / f"{base}.md"] + sorted(d.glob(f"{base}-[0-9]*.md")):
            if cand.exists():
                return Q.TwinVerdict(Q.TWIN_BY_KEY, cand, "склеено по заголовку")
        return Q.TwinVerdict(Q.TWIN_NONE, None, "")

    monkeypatch.setattr(Q, "_open_twin", swallow_everything)
    verdict, why = _run()
    assert verdict == ca.NOT_SATISFIED, why
    assert "глухотой" in why


# ---------------------------------------------------------------------------
# Звено 3: третий исход схлопнут в «близнеца нет»
# ---------------------------------------------------------------------------

def test_red_when_the_third_outcome_is_collapsed(monkeypatch):
    real = Q._open_twin

    def hide_unmeasured(d: Path, base: str, tracker_type: str, body: str):
        v = real(d, base, tracker_type, body)
        if v.kind == Q.TWIN_UNMEASURED and v.path is None:
            return Q.TwinVerdict(Q.TWIN_NONE, None, v.reason)
        return v

    monkeypatch.setattr(Q, "_open_twin", hide_unmeasured)
    verdict, why = _run()
    assert verdict == ca.NOT_SATISFIED, why
    assert "НЕ ИЗМЕРЕНО" in why and "род" in why


# ---------------------------------------------------------------------------
# Звено 4: наследник неизмеренного близнеца рождается БЕЗ ключа
# ---------------------------------------------------------------------------

def test_red_when_the_heir_is_born_without_a_key(monkeypatch):
    """Ключ не пишется там, где он только и мог бы остановить размножение.

    Звено рвётся НАРОЧНО узко — лишь в сцене старого населения: порви его везде, и
    первым покраснело бы звено 1, то есть этот контроль ничего бы не показал.
    """
    real_create = Q.create_card

    def strip_key_in_legacy(*a, **k):
        path = real_create(*a, **k)
        if Path(k.get("tracker_dir", "")).name == "legacy":
            text = path.read_text(encoding="utf-8")
            text = "\n".join(l for l in text.splitlines()
                             if not l.startswith(f"{Q.TWIN_KEY_FIELD}:")) + "\n"
            path.write_text(text, encoding="utf-8")
        return path

    monkeypatch.setattr(Q, "create_card", strip_key_in_legacy)
    verdict, why = _run()
    assert verdict == ca.NOT_SATISFIED, why
    assert "ключа не несёт" in why


# ---------------------------------------------------------------------------
# Звено 5: читатель (шаг 0a) НЕ ИЗМЕРЕН — третий исход пробы, а не «не выполнено»
# ---------------------------------------------------------------------------

def test_unmeasured_when_the_step_0a_reader_cannot_be_raised(monkeypatch, tmp_path):
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    verdict, why = _run()
    assert verdict == ca.UNMEASURED, why
    assert "ось повтора" in why and "НЕ ИЗМЕРЕНА" in why


def _stub_reader(tmp_path: Path, expr: str) -> None:
    """Подложить ВМЕСТО шага 0a заглушку, печатающую назначенное число."""
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "check_owner_order_starvation.py").write_text(
        "import argparse, json, pathlib, sys\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--tracker-dir'); ap.add_argument('--ref')\n"
        "ap.add_argument('--no-write', action='store_true')\n"
        "ap.add_argument('--json', action='store_true')\n"
        "a = ap.parse_args()\n"
        "n = len(list(pathlib.Path(a.tracker_dir).glob('inbox-*.md')))\n"
        f"print(json.dumps({{'repeated_cards': {expr}}}))\n",
        encoding="utf-8")


def test_red_when_the_axis_answers_the_same_on_both_scenes(monkeypatch, tmp_path):
    """Ось, отвечающая одно и то же, критерий поверить не может."""
    _stub_reader(tmp_path, "0")
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    verdict, why = _run()
    assert verdict == ca.NOT_SATISFIED, why
    assert "одно и то же" in why


def test_red_when_the_axis_still_counts_a_repeat_for_the_merged_request(monkeypatch,
                                                                       tmp_path):
    """Сцены различены, но слитая просьба всё равно считается повтором."""
    _stub_reader(tmp_path, "n + 1")
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    verdict, why = _run()
    assert verdict == ca.NOT_SATISFIED, why
    assert "ось повтора шага 0a" in why and "первой" in why


# ---------------------------------------------------------------------------
# Звено 6: проводки ADR-866 в двери нет вовсе — третий исход, а не «не выполнено»
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["twin_key", "twin_verdict", "TWIN_UNMEASURED",
                                     "TWIN_KEY_FIELD"])
def test_unmeasured_when_the_door_has_no_wiring(monkeypatch, missing):
    monkeypatch.delattr(Q, missing)
    verdict, why = _run()
    assert verdict == ca.UNMEASURED, why
    assert missing in why


def test_the_verdict_is_not_confirmed_by_a_substring_of_its_own_print(monkeypatch):
    """ADR-333: печать, собранная из того же числа, подтверждением не является.

    Контроль устроен так: заглушка печатает ПРАВИЛЬНЫЕ слова, но НЕ публикует ключ
    `repeated_cards`. Проба обязана ответить «НЕ ИЗМЕРЕНО», а не принять слова.
    """
    real = ca.PROBES[PROBE_NAME]
    import subprocess as sp
    real_run = sp.run

    def wordy(cmd, **k):
        if "check_owner_order_starvation.py" in " ".join(map(str, cmd)):
            class R:
                returncode = 0
                stdout = json.dumps({"repeats": "повторов не найдено, ось повтора 0"})
                stderr = ""
            return R()
        return real_run(cmd, **k)

    monkeypatch.setattr(sp, "run", wordy)
    verdict, why = real(None)
    assert verdict == ca.UNMEASURED, why
    assert "repeated_cards" in why
