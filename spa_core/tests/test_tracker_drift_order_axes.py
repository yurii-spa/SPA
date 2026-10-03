"""Две оси порядка копий карточки (`check_tracker_drift`) — ADR-544, цикл #757.

**Положительный контроль — настоящая авария, а не выдумка.** Карточка
`owner-decision-gde-granitsa-reshai-sam-i-sprosi-menya`: копия прод-дерева стои́т в
`owner-done`, копия на `origin/main` — в `ingested`. Ось времени объявляла **`tree_newer`**,
опираясь на разницу отметок в **135 микросекунд**, — а это не два события, а ОДНО (ответ
владельца), записанное двумя писателями: прод-копия несёт строку `status_trail`
(``…422107``), origin-копия её потеряла и несёт только `owner_answered_at` (``…421972``).

Цена вердикта не теоретическая: сессия, прочитавшая «моя копия новее», запишет `owner-done`
поверх `ingested` и раскроет записанное решение владельца — графа переходов у `set_status`
нет. На этом прочтении уже построена ложная находка
`inbox-dvenadtsat-otvetov-vladeltsa-stoyat-v-ow` («12 ответов владельца не доехали до
канона»); все двенадцать на origin `ingested`.

Замер на живом трекере 2026-10-03: из 157 разошедшихся пар оси разошлись на **8** (все
восемь — ложный `tree_newer`), и ось следа решила ещё **19**, которых ось времени не брала.

Литеральные отметки в фикстурах — ПРЕДМЕТ проверки (сравнение двух отметок между собой),
а не окружение: календарь на эти тесты не влияет, обе стороны закреплены в тексте фикстуры.
"""
# FROZEN-DATE-OK: отметки времени здесь — предмет сравнения (две копии одной карточки),
# обе стороны закреплены в фикстуре; стенные часы в этих тестах не участвуют.

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (str(_REPO_ROOT), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift  # noqa: E402
from spa_core.owner_queue.status_audit import TRAIL_CAP  # noqa: E402

REF = "main"

# --- дословные две копии карточки аварии -------------------------------------------------

INCIDENT_TREE = """---
trackerStatus:
  type: owner-decision
title: "Где проходит граница"
status: owner-done
owner_choice: 1
owner_answered_at: 2026-09-09T15:02:18.421972+00:00
status_trail:
  - "2026-09-09T15:02:18.422107+00:00 needs-owner -> owner-done · owner_answer.record_owner_answer"
---

тело
"""

INCIDENT_ORIGIN = """---
trackerStatus:
  type: owner-decision
title: "Где проходит граница"
status: ingested
owner_choice: 1
owner_answered_at: 2026-09-09T15:02:18.421972+00:00
---

тело
"""


def _card(status: str, trail: list[str] | None = None, answered: str | None = None) -> str:
    fm = ["---", "trackerStatus:", "  type: owner-decision", 'title: "к"', f"status: {status}"]
    if answered:
        fm.append(f"owner_answered_at: {answered}")
    if trail:
        fm.append("status_trail:")
        fm += [f'  - "{t}"' for t in trail]
    fm += ["---", "", "тело", ""]
    return "\n".join(fm)


# =========================================================================================
# ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария воспроизводится, и новая мера её снимает
# =========================================================================================

def test_the_incident_pair_is_a_confident_wrong_verdict_on_the_time_axis_alone():
    """Ось времени ОДНА — ровно тот ложный `tree_newer`, ради которого написан ADR-544.

    Этот тест обязан остаться зелёным: он фиксирует НАЛИЧИЕ дефекта у старой оси. Если он
    покраснеет, значит ось времени изменили, и соседний тест ниже измеряет уже не то.
    """
    verdict, why = drift.mark_order(INCIDENT_TREE, INCIDENT_ORIGIN)
    assert verdict == drift.ORDER_TREE_NEWER
    assert "422107" in why and "421972" in why, "причина обязана назвать обе отметки"


def test_the_incident_pair_is_no_longer_a_verdict_once_both_axes_speak():
    """Та же пара через `combined_order` ⇒ НЕ ИЗМЕРЕНО, и названы ОБА прочтения."""
    verdict, why = drift.combined_order(
        INCIDENT_TREE, INCIDENT_ORIGIN, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED, (
        "пара аварии обязана перестать быть вердиктом: 135 мкс между двумя писателями "
        "одного события — не старшинство")
    assert drift.ORDER_TREE_NEWER in why, "прочтение оси времени обязано остаться названным"
    assert drift.ORDER_ORIGIN_NEWER in why, "прочтение оси следа обязано быть названным"
    assert "РАСХОДЯТСЯ" in why


def test_the_incident_card_never_held_the_origin_status():
    """Причина, по которой ось следа права на этой паре, названа машинно, а не в прозе."""
    verdict, why = drift.trail_order(INCIDENT_TREE, "owner-done", "ingested")
    assert verdict == drift.ORDER_ORIGIN_NEWER
    assert "ingested" in why


# =========================================================================================
# ОСЬ СЛЕДА: зелёная на целом контуре, красная на КАЖДОМ порванном звене
# =========================================================================================

def test_trail_axis_decides_origin_ahead_on_a_whole_circuit():
    text = _card("owner-done", ['2026-09-09T15:02:18+00:00 needs-owner -> owner-done · x'])
    assert drift.trail_order(text, "owner-done", "ingested")[0] == drift.ORDER_ORIGIN_NEWER


def test_broken_link_empty_trail_is_unmeasured():
    text = _card("owner-done")
    verdict, why = drift.trail_order(text, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED
    assert "следа переходов" in why


def test_broken_link_trail_tail_disagrees_with_the_file_is_unmeasured():
    """Главное звено: статус двигал писатель, записи не оставивший.

    Без этой проверки ось судила бы по ОТСУТСТВИЮ в заведомо дырявом журнале — то есть
    выдавала бы «дерево там не было» там, где она попросту не знает.
    """
    text = _card("owner-done", ['2026-09-09T15:02:18+00:00 needs-owner -> in-progress · x'])
    verdict, why = drift.trail_order(text, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED
    assert "не объясняет текущий статус" in why


def test_broken_link_full_trail_window_is_unmeasured():
    """Окно следа усечено по построению ⇒ «статуса нет в следе» перестаёт быть доказательством."""
    trail = [f'2026-09-0{i % 9 + 1}T00:00:00+00:00 a{i} -> a{i + 1} · x' for i in range(TRAIL_CAP)]
    trail[-1] = '2026-09-09T00:00:00+00:00 a -> owner-done · x'
    text = _card("owner-done", trail)
    verdict, why = drift.trail_order(text, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED
    assert "окно следа заполнено" in why


def test_broken_link_tree_has_held_the_origin_status_is_unmeasured():
    """Дерево БЫЛО в статусе origin и ушло — отсутствием такое не судится, дерево может быть впереди."""
    text = _card("owner-done", [
        '2026-09-09T10:00:00+00:00 needs-owner -> ingested · x',
        '2026-09-09T11:00:00+00:00 ingested -> owner-done · x',
    ])
    verdict, why = drift.trail_order(text, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED
    assert "БЫЛА в статусе" in why


def test_broken_link_origin_status_recorded_only_as_a_transition_SOURCE():
    """Статус origin встречается в следе ТОЛЬКО как источник перехода — и этого довольно.

    Дыра сцены, найденная мутацией (#757): во всех прочих сценах статус origin попадал в
    след и как назначение, поэтому мутант, забывший про `old`, выживал. Окно следа
    усечено с НАЧАЛА (``TRAIL_CAP``), поэтому «только источник» — не выдуманный случай,
    а штатная форма: самый ранний сохранившийся переход помнит своё `old` и ничьё `new`.
    """
    text = _card("owner-done", ['2026-09-09T11:00:00+00:00 ingested -> owner-done · x'])
    verdict, why = drift.trail_order(text, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED, (
        "дерево УШЛО из 'ingested' — оно вполне может быть впереди origin")
    assert "БЫЛА в статусе" in why


def test_broken_link_missing_status_is_unmeasured():
    text = _card("owner-done", ['2026-09-09T15:02:18+00:00 needs-owner -> owner-done · x'])
    assert drift.trail_order(text, "", "ingested")[0] == drift.ORDER_UNMEASURED
    assert drift.trail_order(text, "owner-done", "")[0] == drift.ORDER_UNMEASURED


def test_equal_statuses_are_not_an_order():
    text = _card("ingested", ['2026-09-09T15:02:18+00:00 a -> ingested · x'])
    verdict, why = drift.trail_order(text, "ingested", "ingested")
    assert verdict == drift.ORDER_UNMEASURED
    assert "совпадают" in why


def test_trail_axis_is_one_sided_by_construction_and_says_so():
    """Ось НИКОГДА не заключает `tree_newer` — это свойство, а не случайность набора.

    Симметричный вывод потребовал бы полного следа ПРОТИВОПОЛОЖНОЙ копии, которого у меры
    нет; та же ловушка «у ref следа нет ⇒ он старше» уже названа в `mark_order`.
    """
    scenes = [
        (_card("ingested", ['2026-09-09T12:00:00+00:00 owner-done -> ingested · x']),
         "ingested", "owner-done"),
        (_card("done", ['2026-09-09T12:00:00+00:00 in-progress -> done · x']), "done", "new"),
    ]
    for text, t, o in scenes:
        assert drift.trail_order(text, t, o)[0] != drift.ORDER_TREE_NEWER


# =========================================================================================
# СВЕДЕНИЕ ДВУХ ОСЕЙ
# =========================================================================================

def test_combined_keeps_the_time_verdict_when_the_trail_is_silent():
    tree = _card("owner-done", answered="2026-09-09T10:00:00+00:00")       # следа нет
    origin = _card("ingested", answered="2026-09-09T12:00:00+00:00")
    verdict, why = drift.combined_order(tree, origin, "owner-done", "ingested")
    assert verdict == drift.ORDER_ORIGIN_NEWER
    assert "по отметкам" in why


def test_combined_takes_the_trail_verdict_when_the_timestamps_are_silent():
    """19 живых пар держатся ровно на этой ветке: отметок нет ни у кого, след решает."""
    tree = _card("in-progress", ['2026-08-31T20:00:00+00:00 new -> in-progress · x'])
    origin = _card("done")
    by_time, _ = drift.mark_order(tree, origin)
    assert by_time == drift.ORDER_UNMEASURED, "предпосылка сцены: ось времени здесь молчит"
    verdict, why = drift.combined_order(tree, origin, "in-progress", "done")
    assert verdict == drift.ORDER_ORIGIN_NEWER
    assert "по следу переходов" in why


def test_combined_reports_agreement_when_both_axes_agree():
    tree = _card("in-progress", ['2026-08-31T10:00:00+00:00 new -> in-progress · x'])
    origin = _card("done", answered="2026-09-02T10:00:00+00:00")
    assert drift.mark_order(tree, origin)[0] == drift.ORDER_ORIGIN_NEWER
    assert drift.trail_order(tree, "in-progress", "done")[0] == drift.ORDER_ORIGIN_NEWER
    verdict, why = drift.combined_order(tree, origin, "in-progress", "done")
    assert verdict == drift.ORDER_ORIGIN_NEWER
    assert "обе оси согласны" in why


def test_combined_is_unmeasured_when_both_are_silent_and_names_both_reasons():
    tree = _card("owner-done")
    origin = _card("ingested")
    verdict, why = drift.combined_order(tree, origin, "owner-done", "ingested")
    assert verdict == drift.ORDER_UNMEASURED
    assert "отметки:" in why and "след:" in why, "обе причины обязаны быть названы"


# =========================================================================================
# ПРОВОДКА: вердикт обязан доехать до находки, и СТАТУСЫ обязаны прийти настоящие
# =========================================================================================

def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    # `-b` обязателен: без него имя ветки берётся у хоста (`init.defaultBranch`),
    # и сцена зелена на Маке и красна на ubuntu-latest (`.claude/rules/deployment.md`).
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def test_wiring_the_incident_pair_reaches_the_finding_as_unmeasured(repo):
    """Контур целиком: две копии аварии в настоящем репозитории ⇒ находка несёт «не измерено».

    Мутант, подставивший в `combined_order` не те статусы (или вернувший старый
    `mark_order`), краснит этот тест: вердикт станет `tree_newer`.
    """
    tracker = repo / drift.TRACKER_REL
    name = "owner-decision-gde-granitsa.md"
    (tracker / name).write_text(INCIDENT_ORIGIN, encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "origin: инжест записан")
    (tracker / name).write_text(INCIDENT_TREE, encoding="utf-8")

    report = drift.analyze(tracker, REF)
    diverged = [f for f in report.findings if f.kind == drift.KIND_DIVERGED]
    assert [f.card_id for f in diverged] == ["owner-decision-gde-granitsa"]
    f = diverged[0]
    assert (f.tree_status, f.origin_status) == ("owner-done", "ingested"), (
        "статусы обязаны прийти в меру настоящими — на них и держится вторая ось")
    assert f.order == drift.ORDER_UNMEASURED
    assert drift.ORDER_TREE_NEWER in f.order_detail


def test_wiring_the_order_verdict_survives_the_json_report(repo):
    """Вердикт обязан дойти до ПОТРЕБИТЕЛЯ: находка в `--json`, а не только в объекте."""
    tracker = repo / drift.TRACKER_REL
    name = "owner-decision-gde-granitsa.md"
    (tracker / name).write_text(INCIDENT_ORIGIN, encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "origin")
    (tracker / name).write_text(INCIDENT_TREE, encoding="utf-8")

    res = subprocess.run(
        [sys.executable, str(_SCRIPTS / "check_tracker_drift.py"),
         "--tracker-dir", str(tracker), "--ref", REF, "--json"],
        capture_output=True, text=True, cwd=str(repo))
    assert res.returncode == 1, f"находка ⇒ код 1; получено {res.returncode}: {res.stderr[-400:]}"
    payload = json.loads(res.stdout)
    rows = [x for x in payload["findings"] if x["kind"] == drift.KIND_DIVERGED]
    assert len(rows) == 1
    assert rows[0]["order"] == drift.ORDER_UNMEASURED
