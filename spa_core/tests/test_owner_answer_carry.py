"""След решения владельца обязан доехать до git — иначе аудита решения не существует.

**Каждый тест здесь воспроизводит настоящую потерю, измеренную 09.08 (цикл #178).**
Проверка, никогда не видевшая живой поломки, — украшение
(правило `.claude/rules/deployment.md`).

Что случилось. Ответ владельца рождается и умирает в ОДНОМ дереве:

1. владелец жмёт кнопку в Телеграме;
2. бот пишет `owner_choice` / `owner_answered_at` / `owner_answer_via` /
   `owner_answered_by` в ХОСТ-дерево — единственное, которое он знает;
3. решение разбирает цикл в ИЗОЛИРОВАННОМ worktree от `origin/main`, где этих полей нет
   ВООБЩЕ, и пушит оттуда `status: ingested`;
4. хост-копию не обновляет никто.

Живой замер на двух карточках — `own-rnd-duty-is-concentration-adr055` (вариант A, 08.08
18:33Z) и `owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst` (вариант 1, 08.08
21:11Z): на `origin/main` у ОБЕИХ нет ни `owner_choice`, ни `owner_answered_at` —
инжестирующая сессия переписывает раздел своей прозой. Машинно проверяемый след «что
именно выбрал владелец и когда» существовал только в рабочей копии одной машины, вне git.
Один `git checkout` — и следа нет.

Вторая потеря, следствие первой: хост-копия остаётся `owner-done` навсегда, и обязательный
шаг 2 протокола каждый раз выдаёт уже разобранные решения как свежие.

**Что закреплено здесь.** Перенос следа перед `ingested` (`carry_owner_answer`), его отказ
при ДВУХ разных ответах владельца, и доизмерение вердикта до ДОКАЗАННОГО, когда след
совпал по обе стороны. Обратные контроли — на месте: свежий ответ владельца не гасится,
а «скорее всего разобрано» без следа так и остаётся «скорее всего».

Литеральных дат нет: всё состояние задаётся содержимым фикстур, календарь на эти тесты
не влияет (правило про фиксированные даты — `.claude/rules/deployment.md`).
"""

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
import orchestrator_queue as oq  # noqa: E402

from spa_core.owner_queue import owner_answer as oa  # noqa: E402

REF = "main"

CHOICE = "A"
STAMP = "2026-01-01T18:33:00+00:00"      # момент нажатия — часть следа, не «сегодня»


# ── фикстуры: карточка решения и крошечный репозиторий с «origin» ────────────

def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _owner_card(status="needs-owner", body="вопрос владельцу", extra="") -> str:
    return (f"---\ntrackerStatus:\n  type: owner-decision\n"
            f"title: \"вопрос владельцу\"\nstatus: {status}\n{extra}---\n\n{body}\n")


def _answered_by_bot(choice=CHOICE, stamp=STAMP) -> str:
    """РОВНО то, что пишет `record_owner_answer` в хост-дерево при нажатии кнопки."""
    return _owner_card(
        status="owner-done",
        body="## Решение владельца\n\n**Вариант A** — да",
        extra=(f"owner_choice: {choice}\nowner_answered_at: {stamp}\n"
               f"owner_answer_via: telegram\nowner_answered_by: 12345\n"),
    )


@pytest.fixture()
def trees(tmp_path):
    """Два дерева одной карточки: `host` (куда пишет бот) и `wt` (worktree цикла)."""
    host = tmp_path / "host" / drift.TRACKER_REL
    wt = tmp_path / "wt" / drift.TRACKER_REL
    host.mkdir(parents=True)
    wt.mkdir(parents=True)
    (host / "owner-decision-x.md").write_text(_answered_by_bot(), encoding="utf-8")
    # В worktree от origin/main полей ответа нет ВООБЩЕ — это и есть исходное состояние.
    (wt / "owner-decision-x.md").write_text(_owner_card(), encoding="utf-8")
    return host, wt


def _fields(path: Path) -> dict:
    return oa.read_answer_fields(path.read_text(encoding="utf-8"))


# ── авария №1: след решения не доезжает до git ───────────────────────────────

def test_answer_trace_is_carried_into_the_copy_that_goes_to_git(trees):
    """ЯДРО ДЕФЕКТА. Так потеряны следы двух решений владельца от 08.08."""
    host, wt = trees
    card = wt / "owner-decision-x.md"
    assert _fields(card) == {}, "предусловие: в worktree следа ответа нет"

    report = oa.carry_owner_answer(card, extra_dirs=[host])

    assert report["verdict"] == oa.CARRY_CARRIED
    got = _fields(card)
    assert got["owner_choice"] == CHOICE
    assert got["owner_answered_at"] == STAMP
    assert got["owner_answer_via"] == "telegram"
    assert got["owner_answered_by"] == "12345"


def test_carry_keeps_the_rest_of_the_card_byte_for_byte(trees):
    """Перенос добавляет след — и НИЧЕГО больше. Тело карточки не его дело."""
    host, wt = trees
    card = wt / "owner-decision-x.md"
    before = card.read_text(encoding="utf-8")

    oa.carry_owner_answer(card, extra_dirs=[host])

    after = card.read_text(encoding="utf-8")
    added = [ln for ln in after.splitlines() if ln not in before.splitlines()]
    assert all(ln.split(":")[0] in oa.OWNER_ANSWER_FIELDS for ln in added), (
        f"перенос тронул что-то кроме полей следа: {added}"
    )
    assert "## Решение владельца" not in after, (
        "тело карточки пишут бот и сессия — склеивать два рассказа об одном решении нельзя"
    )


def test_ingesting_via_the_cli_carries_the_trace_before_closing(trees, capsys):
    """Путь, которым ходит протокол: `set-status <карточка> ingested`.

    Ровно эта команда предписана шагом 2. Перенос обязан случиться ВНУТРИ неё — надежда,
    что каждая следующая сессия вспомнит сделать это руками, уже подвела дважды.
    """
    host, wt = trees
    card = wt / "owner-decision-x.md"
    rc = oq.main(["set-status", str(card), "ingested", "--answer-from", str(host)])

    assert rc == 0
    text = card.read_text(encoding="utf-8")
    assert "status: ingested" in text
    assert _fields(card)["owner_choice"] == CHOICE, (
        "карточка закрыта, а след решения владельца в git так и не уехал"
    )
    assert "след решения владельца перенесён" in capsys.readouterr().err


def test_missing_trace_everywhere_is_said_out_loud_not_swallowed(tmp_path, capsys):
    """Следа нет нигде — это НАЗЫВАЕТСЯ. Молчание читалось бы как «перенесли»."""
    d = tmp_path / drift.TRACKER_REL
    d.mkdir(parents=True)
    card = d / "owner-decision-x.md"
    card.write_text(_owner_card(), encoding="utf-8")

    rc = oq.main(["set-status", str(card), "ingested"])

    assert rc == 0, "отсутствие следа не повод запереть очередь — но и не повод молчать"
    err = capsys.readouterr().err
    assert "нет НИ В ОДНОЙ" in err and "owner_choice" in err


def test_two_different_owner_answers_refuse_to_close_the_card(trees, capsys):
    """fail-CLOSED. Две копии — два РАЗНЫХ ответа: выбрать сторону молча запрещено."""
    host, wt = trees
    other = wt.parent.parent / "other" / drift.TRACKER_REL
    other.mkdir(parents=True)
    (other / "owner-decision-x.md").write_text(
        _answered_by_bot(choice="B", stamp="2026-01-02T09:00:00+00:00"), encoding="utf-8")
    card = wt / "owner-decision-x.md"

    rc = oq.main(["set-status", str(card), "ingested",
                  "--answer-from", str(host), "--answer-from", str(other)])

    assert rc == 2
    assert "status: needs-owner" in card.read_text(encoding="utf-8"), (
        "карточку закрыли, не зная, какой ответ владельца верен — решение потеряно"
    )
    assert "РАЗНЫЕ ответы владельца" in capsys.readouterr().err


def test_carry_never_overwrites_an_answer_already_recorded_here(trees):
    """Свой уже записанный след главнее чужого: перенос не переписывает решение."""
    host, wt = trees
    card = wt / "owner-decision-x.md"
    card.write_text(_answered_by_bot(), encoding="utf-8")
    before = card.read_text(encoding="utf-8")

    report = oa.carry_owner_answer(card, extra_dirs=[host])

    assert report["verdict"] == oa.CARRY_ALREADY_PRESENT
    assert card.read_text(encoding="utf-8") == before


def test_inbox_card_is_not_touched_by_the_carry(tmp_path, capsys):
    """Перенос — про решения владельца. У обычной задачи следа ответа нет и быть не должно."""
    d = tmp_path / drift.TRACKER_REL
    d.mkdir(parents=True)
    card = d / "inbox-x.md"
    card.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: t\nstatus: new\n---\n\nтело\n",
                    encoding="utf-8")

    rc = oq.main(["set-status", str(card), "ingested"])

    assert rc == 0
    assert "owner_choice" not in card.read_text(encoding="utf-8")
    assert "нет НИ В ОДНОЙ" not in capsys.readouterr().err


def test_main_worktree_is_searched_without_being_told(tmp_path):
    """Автопоиск: бот пишет в ГЛАВНОЕ рабочее дерево, и знать про это должен инструмент.

    Без этого перенос работал бы только там, где сессия вспомнила про `--answer-from`, —
    то есть держался бы на той же внимательности, которая уже дважды отказала.
    """
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    (root / drift.TRACKER_REL / "owner-decision-x.md").write_text(
        _answered_by_bot(), encoding="utf-8")          # хост-дерево: ответ владельца
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "c")

    wt = tmp_path / "wt"
    _run(root, "worktree", "add", "-q", "--detach", str(wt))
    card = wt / drift.TRACKER_REL / "owner-decision-x.md"
    card.write_text(_owner_card(), encoding="utf-8")   # worktree цикла: следа нет

    report = oa.carry_owner_answer(card)               # без единого --answer-from

    assert report["verdict"] == oa.CARRY_CARRIED
    assert _fields(card)["owner_choice"] == CHOICE


# ── авария №2: разобранное решение выдаётся шагу 2 как свежее ────────────────

def _repo_with_ingested_answer(tmp_path, *, trace_reaches_origin: bool):
    """Состояние прод-дерева 09.08: дерево `owner-done`, origin `ingested`.

    `trace_reaches_origin` — единственная переменная: доехал ли след решения до git.
    Это ровно то, что чинит перенос, и ровно то, что отличает «доказано» от «наверное».
    """
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    card = root / drift.TRACKER_REL / "owner-decision-x.md"

    card.write_text(_owner_card(), encoding="utf-8")               # вопрос уехал на origin
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "вопрос")

    ingested_extra = (f"owner_choice: {CHOICE}\nowner_answered_at: {STAMP}\n"
                      if trace_reaches_origin else "")
    card.write_text(_owner_card(status="ingested", body="## разобрано сессией",
                                extra=ingested_extra), encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "инжест")

    card.write_text(_answered_by_bot(), encoding="utf-8")          # хост-копия бота остаётся
    return root


def _step2_json(root, capsys) -> list[dict]:
    """Дословно команда шага 2 протокола."""
    oq.main(["list", "--type", "owner-decision", "--status", "owner-done",
             "--tracker-dir", str(root / drift.TRACKER_REL), "--ref", REF, "--json"])
    return json.loads(capsys.readouterr().out)


def test_step2_stops_handing_out_a_decision_whose_trace_is_proven_in_git(tmp_path, capsys):
    """Со следом в git «скорее всего разобрано» становится ДОКАЗАНО — и шаг 2 молчит.

    Живьём 09.08 шаг 2 выдал две уже разобранные карточки как свежие, и цикл #178 начал
    разбирать их заново.
    """
    root = _repo_with_ingested_answer(tmp_path, trace_reaches_origin=True)
    assert _step2_json(root, capsys) == [], (
        "решение с доказанным следом в git снова выдано шагу 2 как свежее"
    )


def test_proven_verdict_is_named_in_the_machine_contract(tmp_path, capsys):
    """Карточка не исчезает бесследно: вердикт виден в JSON того же дерева."""
    root = _repo_with_ingested_answer(tmp_path, trace_reaches_origin=True)
    oq.main(["list", "--type", "owner-decision",
             "--tracker-dir", str(root / drift.TRACKER_REL), "--ref", REF, "--json"])
    out = capsys.readouterr()
    cards = json.loads(out.out)

    assert [c["origin_check"] for c in cards] == [oq.VERDICT_ANSWER_INGESTED_PROVEN]
    assert cards[0]["status"] == "ingested", "статус обязан быть прочитан с origin"
    assert "ДОКАЗАННО РАЗОБРАН" in out.err, "человек у терминала видит то же, что и `| jq`"


def test_without_the_trace_in_git_the_verdict_stays_a_guess(tmp_path, capsys):
    """ГЛАВНЫЙ ОБРАТНЫЙ КОНТРОЛЬ.

    Без следа в git карточка обязана остаться в списке с прежним «скорее всего» — иначе
    «починка» вида «выбрасывать всё расходящееся» была бы зелёной и съедала бы настоящий
    повторный ответ владельца. Это ровно поведение, которое закрепил цикл #178.
    """
    root = _repo_with_ingested_answer(tmp_path, trace_reaches_origin=False)
    cards = _step2_json(root, capsys)

    assert [c["id"] for c in cards] == ["owner-decision-x"]
    assert cards[0]["origin_check"] == oq.VERDICT_MAYBE_INGESTED


def test_empty_trace_on_both_sides_is_not_a_match(tmp_path, capsys):
    """Пустое совпадает с пустым — но доказательством это не является.

    Без этой оговорки «доказано» срабатывало бы на КАЖДОЙ карточке без полей ответа, то
    есть ровно на том состоянии, ради которого перенос и написан.
    """
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    card = root / drift.TRACKER_REL / "owner-decision-x.md"
    card.write_text(_owner_card(), encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "вопрос")
    card.write_text(_owner_card(status="ingested", body="## разобрано"), encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "инжест")
    # хост-копия: владелец закрыл карточку РУКАМИ, следа полей нет ни там, ни там
    card.write_text(_owner_card(status="owner-done", body="## разобрано\n\nответ руками"),
                    encoding="utf-8")

    cards = _step2_json(root, capsys)

    assert [c["id"] for c in cards] == ["owner-decision-x"]
    assert cards[0]["origin_check"] == oq.VERDICT_MAYBE_INGESTED


def test_a_genuinely_fresh_owner_answer_is_never_marked_proven(tmp_path, capsys):
    """Свежий ответ владельца, которого на origin ещё нет, не имеет права погаснуть."""
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    card = root / drift.TRACKER_REL / "owner-decision-x.md"
    card.write_text(_owner_card(), encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "вопрос")
    card.write_text(_answered_by_bot(), encoding="utf-8")   # владелец только что ответил

    cards = _step2_json(root, capsys)

    assert [c["id"] for c in cards] == ["owner-decision-x"], (
        "свежий ответ владельца пропал из очереди — решение потеряно"
    )
    assert cards[0]["origin_check"] != oq.VERDICT_ANSWER_INGESTED_PROVEN
