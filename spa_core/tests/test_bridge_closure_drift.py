"""Карточка моста закрыта в проде, а на `origin/main` открыта — `bridge_closure_drift`.

КАЖДЫЙ тест — положительный контроль реальной аварии, измеренной циклом #480
(2026-09-04) и записанной карточкой `inbox-zakrytie-kartochki-mosta-ne-vozvraschaet`:

    ключ `gap:analyst_red:red_team` — `status: closed`, `last_seen: 2026-08-11`;
    карточка `inbox-nahodka-petli-analitik-red-team-critical`
    в прод-дереве `done`, на `origin/main` `new` (создана 2026-08-10).

Находка была снята 11 августа. Цикл #480 взял её как ОТКРЫТУЮ работу моста
(мандат велит брать такие первыми), прочитал тело, поднял два gitignored-артефакта
и только тогда установил, что работа сделана 25 дней назад.

Что здесь проверяется помимо самой находки
------------------------------------------------------------------------------
1. **Обе стороны** (требование карточки, п. 4): открыта наверху ⇒ краснеет;
   закрыта наверху ⇒ молчит. Сторож, звонящий на верном состоянии, глохнет.
2. **Третий исход.** `data/` в worktree нет ПО ПОСТРОЕНИЮ, а `origin/main` не
   разрешается в песочнице без репозитория — «находок 0» там было бы fail-OPEN,
   тише красной строки и потому опаснее (класс #465).
3. **НАСТОЯЩАЯ форма вызова.** Зелень на подставленном `origin_lookup` ничего не
   значит сама по себе: ровно так работа #474 держала 16 зелёных проверок, тогда
   как в живом вызове сверка шла дерева с самим собой и не срабатывала ни разу
   (#475). Поэтому `run()` прогоняется через настоящий git-репозиторий.

Дат в фикстурах нет: вердикт этого модуля от календаря не зависит ни одной веткой.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from spa_core.monitoring import bridge_closure_drift as bcd
from spa_core.owner_queue.origin_view import Unmeasured

# Авария #480 дословно: ключ находки и карточка, которую мост закрыл в проде.
INCIDENT_KEY = "gap:analyst_red:red_team"
INCIDENT_CARD_ID = "inbox-nahodka-petli-analitik-red-team-critical"
INCIDENT_CARD = f"/Users/yuriikulieshov/Documents/SPA_Claude/nimbalyst-local/tracker/{INCIDENT_CARD_ID}.md"

REF_SHA = "0" * 40

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "consume_office_reports.py"


def _office():
    """Шаг 0-офис как модуль — той же загрузкой, что и `test_consume_office_reports`."""
    spec = importlib.util.spec_from_file_location("_consume_office_reports_bcd", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OFFICE = _office()


def _closed(card: str = INCIDENT_CARD) -> dict:
    """Запись моста, которую он ЗАКРЫЛ САМ (findings_bridge: status = "closed")."""
    return {"status": "closed", "card": card, "closed_at": "2026-08-11T07:03:01+00:00"}


def _lookup(statuses: dict[str, str], sha: str = REF_SHA):
    """Сверка с ref, отвечающая заданными статусами. Ключа нет ⇒ карточки нет на ref."""
    def lookup(card_ids):
        return {cid: st for cid, st in statuses.items() if cid in card_ids}, sha
    return lookup


# ===========================================================================
# 1. Сама авария и её обратная сторона
# ===========================================================================
def test_card_closed_in_prod_but_open_on_origin_is_named() -> None:
    """#480 дословно: мост закрыл карточку здесь, наверху она `new`."""
    report = bcd.scan({INCIDENT_KEY: _closed()}, _lookup({INCIDENT_CARD_ID: "new"}))

    assert report["verdict"] == bcd.VERDICT_FINDINGS
    assert [r["card_id"] for r in report["open_on_origin"]] == [INCIDENT_CARD_ID], (
        "находка обязана быть названа ПОИМЁННО: число без имён — строка, "
        "по которой действовать нечем")
    row = report["open_on_origin"][0]
    assert row["key"] == INCIDENT_KEY
    assert row["origin_status"] == "new"
    assert row["closed_at"] == "2026-08-11T07:03:01+00:00"
    assert report["ref_sha"] == REF_SHA, "с ЧЕМ сверено — часть измерения"


def test_card_closed_on_both_sides_is_silent() -> None:
    """Обратный контроль (карточка, п. 4): сторож, звонящий на верном состоянии, глохнет."""
    report = bcd.scan({INCIDENT_KEY: _closed()}, _lookup({INCIDENT_CARD_ID: "done"}))

    assert report["verdict"] == bcd.VERDICT_OK
    assert report["open_on_origin"] == []
    assert report["agreed"] == 1


@pytest.mark.parametrize("status", sorted(bcd.CLOSED_ON_ORIGIN))
def test_every_terminal_status_counts_as_closed_upstairs(status: str) -> None:
    """`ingested` и `owner-done` закрывают карточку не хуже `done` — иначе сторож
    покраснел бы на разобранной по протоколу карточке владельца."""
    report = bcd.scan({INCIDENT_KEY: _closed()}, _lookup({INCIDENT_CARD_ID: status}))

    assert report["verdict"] == bcd.VERDICT_OK, status


def test_owner_accepted_is_not_a_closure() -> None:
    """Владелец ответил, но работа впереди — карточка наверху ОТКРЫТА (то же
    решение, что у `build_tracker_board.TERMINAL_STATUSES`)."""
    report = bcd.scan({INCIDENT_KEY: _closed()}, _lookup({INCIDENT_CARD_ID: "owner-accepted"}))

    assert report["verdict"] == bcd.VERDICT_FINDINGS


def test_terminal_set_matches_the_board() -> None:
    """Копия правила «что значит закрыта» здесь СОЗНАТЕЛЬНА — но молча разойтись
    со вторым писателем она не вправе: две разошедшиеся копии одного правила и
    есть дефект, ради которого сторож написан."""
    from scripts.build_tracker_board import TERMINAL_STATUSES

    assert bcd.CLOSED_ON_ORIGIN == frozenset(TERMINAL_STATUSES)


# ===========================================================================
# 2. Границы предмета — расширить их значило бы краснеть на верном состоянии
# ===========================================================================
def test_resolved_untouched_is_not_the_subject() -> None:
    """Карточку взял ЧЕЛОВЕК, мост её не закрывал — открытый статус наверху законен."""
    state = {INCIDENT_KEY: {"status": "resolved_untouched", "card": INCIDENT_CARD}}

    report = bcd.scan(state, _lookup({INCIDENT_CARD_ID: "in-progress"}))

    assert report["verdict"] == bcd.VERDICT_OK
    assert report["checked"] == 0


def test_card_absent_on_origin_is_named_separately_not_as_a_finding() -> None:
    """Направление РОЖДЕНИЯ (карточка, рождённая в проде) закрыто своей карточкой.
    Сложить два списка в одно число значило бы предъявить циклу работу, которой нет."""
    report = bcd.scan({INCIDENT_KEY: _closed()}, _lookup({}))

    assert report["verdict"] == bcd.VERDICT_OK
    assert report["open_on_origin"] == []
    assert [r["card_id"] for r in report["absent_on_origin"]] == [INCIDENT_CARD_ID], (
        "не находка — но и не молчание: строка обязана существовать")


def test_finding_without_a_card_is_not_measured_as_agreement() -> None:
    """Запись без карточки сверять не с чем — она не вправе увеличивать `agreed`."""
    report = bcd.scan({INCIDENT_KEY: {"status": "closed"}}, _lookup({}))

    assert report["checked"] == 0
    assert report["agreed"] == 0


# ===========================================================================
# 3. Третий исход: «не измерено» — не «расхождений нет»
# ===========================================================================
def test_unread_state_is_unmeasured_not_zero_findings() -> None:
    """В worktree `data/` нет ПО ПОСТРОЕНИЮ. Ноль находок оттуда — fail-OPEN."""
    report = bcd.scan({}, _lookup({}), state_read=False)

    assert report["verdict"] == bcd.VERDICT_UNMEASURED
    assert report["unmeasured_reason"], "у «не измерено» обязана быть причина словами"
    assert report["open_on_origin"] == []


def test_missing_lookup_is_unmeasured_not_zero_findings() -> None:
    """Вызывающий сверку не дал — сказать «расхождений нет» о таком входе нельзя."""
    report = bcd.scan({INCIDENT_KEY: _closed()}, None)

    assert report["verdict"] == bcd.VERDICT_UNMEASURED
    assert report["unmeasured_reason"]


def test_failed_ref_comparison_is_unmeasured_with_the_reason() -> None:
    """Ref не разрешается (песочница без репозитория) — причина обязана доехать."""
    def broken(_card_ids):
        raise Unmeasured("ref `origin/main` в этом репозитории не разрешается")

    report = bcd.scan({INCIDENT_KEY: _closed()}, broken)

    assert report["verdict"] == bcd.VERDICT_UNMEASURED
    assert "не разрешается" in report["unmeasured_reason"]


def test_measured_emptiness_is_ok_and_distinguishable_from_unmeasured() -> None:
    """Состояние ПРОЧИТАНО, закрытых мостом карточек в нём нет. Это `ok` — и оно
    обязано отличаться от `unmeasured`, иначе исходов снова два, а не три."""
    report = bcd.scan({}, _lookup({}))

    assert report["verdict"] == bcd.VERDICT_OK
    assert report["unmeasured_reason"] is None


# ===========================================================================
# 4. НАСТОЯЩАЯ форма вызова — против вакуумной зелени (#474/#475)
# ===========================================================================
def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card_text(status: str) -> str:
    return (f'---\ntrackerStatus:\n  type: inbox\ntitle: "находка петли"\n'
            f"status: {status}\n---\n\nтело\n")


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """Настоящий крошечный репозиторий с `refs/remotes/origin/main`. Сети не касается."""
    root = tmp_path / "tree"
    tracker = root / bcd.TRACKER_REL
    tracker.mkdir(parents=True)
    (root / "data").mkdir()
    _git(tmp_path, "init", "-q", "-b", "main", str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "test")
    return root


def _publish(root: Path, card_id: str, status: str) -> None:
    """Положить карточку в версию `origin/main` — ту самую, что читает сторож."""
    (root / bcd.TRACKER_REL / f"{card_id}.md").write_text(_card_text(status), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


def _bridge_state(root: Path, entries: dict) -> None:
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "findings_bridge_state.json").write_text(
        json.dumps({"findings": entries}), encoding="utf-8")


def test_real_call_form_finds_the_incident(tree: Path) -> None:
    """Живой вызов `run(root)` — без подставленного lookup. Именно этой проверки
    не было у #474, и вакуум держался за фикстурой шестнадцатью зелёными тестами."""
    _publish(tree, INCIDENT_CARD_ID, "new")
    _bridge_state(tree, {INCIDENT_KEY: _closed(
        str(tree / bcd.TRACKER_REL / f"{INCIDENT_CARD_ID}.md"))})

    report = bcd.run(str(tree))

    assert report["verdict"] == bcd.VERDICT_FINDINGS
    assert [r["card_id"] for r in report["open_on_origin"]] == [INCIDENT_CARD_ID]
    assert len(report["ref_sha"]) == 40, "sha локальной копии ref обязан быть назван"


def test_real_call_form_is_silent_when_origin_agrees(tree: Path) -> None:
    """Обратный контроль в той же настоящей форме: сверка не выдумывает находок."""
    _publish(tree, INCIDENT_CARD_ID, "done")
    _bridge_state(tree, {INCIDENT_KEY: _closed(
        str(tree / bcd.TRACKER_REL / f"{INCIDENT_CARD_ID}.md"))})

    report = bcd.run(str(tree))

    assert report["verdict"] == bcd.VERDICT_OK
    assert report["agreed"] == 1


def test_real_call_form_without_a_bridge_state_says_unmeasured(tree: Path) -> None:
    """Дерево без `data/findings_bridge_state.json` — это НЕ «расхождений нет»."""
    _publish(tree, INCIDENT_CARD_ID, "new")

    report = bcd.run(str(tree))

    assert report["verdict"] == bcd.VERDICT_UNMEASURED
    assert report["unmeasured_reason"]


def test_real_call_form_outside_a_repository_says_unmeasured(tmp_path: Path) -> None:
    """Песочница без git: сверять не с чем — и это сказано вслух, а не нулём."""
    (tmp_path / bcd.TRACKER_REL).mkdir(parents=True)
    _bridge_state(tmp_path, {INCIDENT_KEY: _closed()})

    report = bcd.run(str(tmp_path))

    assert report["verdict"] == bcd.VERDICT_UNMEASURED


# ===========================================================================
# 5. Проводка: сторож, до читателя не доехавший, — украшение
# ===========================================================================
def test_loop_health_carries_the_verdict(tree: Path) -> None:
    """`loop_health.run()` кладёт вердикт в `data/loop_health.json` — тот самый
    артефакт, который обязательный шаг 0-офис читает каждый цикл."""
    from spa_core.monitoring import loop_health

    _publish(tree, INCIDENT_CARD_ID, "new")
    card_path = str(tree / bcd.TRACKER_REL / f"{INCIDENT_CARD_ID}.md")
    _bridge_state(tree, {INCIDENT_KEY: _closed(card_path)})

    report = loop_health.run(root=str(tree))

    assert report["closure_drift"]["verdict"] == bcd.VERDICT_FINDINGS
    on_disk = json.loads((tree / "data" / "loop_health.json").read_text(encoding="utf-8"))
    assert [r["card_id"] for r in on_disk["closure_drift"]["open_on_origin"]] == [INCIDENT_CARD_ID]


def test_loop_health_without_state_does_not_report_zero_drift(tree: Path) -> None:
    """Прежняя запись (`except: state = {}`) стирала разницу между «состояния нет»
    и «оно пустое», и сверка по такому входу отвечала бы «расхождений 0»."""
    from spa_core.monitoring import loop_health

    report = loop_health.run(root=str(tree))

    assert report["closure_drift"]["verdict"] == bcd.VERDICT_UNMEASURED


def test_office_step_prints_the_finding() -> None:
    """Шаг 0-офис обязан НАЗВАТЬ находку, а не проглотить её в «прочитано N»."""
    doc = {"cards_fate": {"new": 0, "in_progress": 0, "done_by_human": 0,
                          "auto_closed": 1, "other_status": 0, "unreadable": 0},
           "open_cards": 0, "recurrences_total": 0,
           "latency_finding_to_card": {"median_h": None, "max_h": None, "n": 0},
           "latency_card_to_close": {"median_h": None, "max_h": None, "n": 0},
           "closure_drift": {"verdict": "findings", "unmeasured_reason": None,
                             "ref_sha": REF_SHA, "checked": 1, "agreed": 0,
                             "absent_on_origin": [],
                             "open_on_origin": [{"key": INCIDENT_KEY,
                                                 "card_id": INCIDENT_CARD_ID,
                                                 "origin_status": "new",
                                                 "closed_at": "2026-08-11T07:03:01+00:00"}]}}

    out = "\n".join(OFFICE._summarize_json("data/loop_health.json", doc))

    assert INCIDENT_CARD_ID in out, "имя карточки — то единственное, чем можно действовать"
    assert "ЗАКРЫТО В ПРОДЕ" in out


def test_office_step_says_unmeasured_out_loud() -> None:
    """«Не измерено» обязано быть слышно: молчание читается как «расхождений нет»."""
    doc = {"cards_fate": {"new": 0, "in_progress": 0, "done_by_human": 0,
                          "auto_closed": 0, "other_status": 0, "unreadable": 0},
           "open_cards": 0, "recurrences_total": 0,
           "latency_finding_to_card": {"median_h": None, "max_h": None, "n": 0},
           "latency_card_to_close": {"median_h": None, "max_h": None, "n": 0},
           "closure_drift": {"verdict": "unmeasured",
                             "unmeasured_reason": "состояние моста не прочитано",
                             "ref_sha": None, "checked": 0, "agreed": 0,
                             "open_on_origin": [], "absent_on_origin": []}}

    out = "\n".join(OFFICE._summarize_json("data/loop_health.json", doc))

    assert "НЕ ИЗМЕРЕНО" in out
    assert "состояние моста не прочитано" in out


def test_office_step_stays_silent_about_a_missing_block() -> None:
    """Отчёт БЕЗ блока `closure_drift` эта ветка НЕ комментирует — и это решение,
    а не пропуск. На отсутствие ключа отвечает объявленная схема
    (`_READ_SCHEMA` + `_PRODUCER`), и отвечает точнее: она различает
    «производитель ключа не пишет» (расхождение) и «артефакт произведён РАНЬШЕ
    доставки ключа» (не находка). Своя строка здесь означала бы красное на
    здоровом контуре каждый цикл до следующего такта производителя — ровно та
    ложная тревога, которую сняли в #248, и она покраснила бы два соседних
    теста-снимка прода в `test_consume_office_reports.py`.
    """
    doc = {"cards_fate": {"new": 0, "in_progress": 0, "done_by_human": 0,
                          "auto_closed": 0, "other_status": 0, "unreadable": 0},
           "open_cards": 0, "recurrences_total": 0, "note": "",
           "latency_finding_to_card": {"median_h": None, "max_h": None, "n": 0},
           "latency_card_to_close": {"median_h": None, "max_h": None, "n": 0}}

    out = "\n".join(OFFICE._summarize_json("data/loop_health.json", doc))

    assert "origin/main" not in out, (
        "своя строка о пропавшем ключе — ложная тревога на здоровом контуре")
    assert "закрытия моста" not in out


def test_declared_schema_names_the_new_key() -> None:
    """Ключ обязан быть ОБЪЯВЛЕН читателем: именно объявление и делает его
    отсутствие измеримым (см. тест выше — молчание ветки опирается на него)."""
    assert "closure_drift" in OFFICE._READ_SCHEMA["loop_health.json"]
