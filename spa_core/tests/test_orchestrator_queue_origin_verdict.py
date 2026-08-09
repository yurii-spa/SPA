"""Вердикт сверки с origin обязан ехать в stdout — его читает шаг 2 протокола.

**Каждый тест здесь воспроизводит настоящую аварию цикла #178 (2026-08-09).**
Проверка, никогда не видевшая живой поломки, — украшение
(правило `.claude/rules/deployment.md`).

Что случилось. Шаг 2 протокола (`docs/ORCHESTRATOR_PROTOCOL.md`, «инжест решений
владельца») предписан ДОСЛОВНО так:

    python3 scripts/orchestrator_queue.py list --type owner-decision --status owner-done --json

То есть контракт шага — **stdout**. Сторож сверки с origin (#147) к тому моменту уже
умел находить расхождение хост-дерева с `origin/main`, но всё, что он знал, он говорил
в **stderr-прозой**. Сессия, разбирающая JSON (а протокол велит именно это), о вердикте
не узнавала НИКОГДА.

Живой замер 09.08 на прод-дереве `~/Documents/SPA_Claude`: команда шага 2 вернула
**две** карточки `owner-done` —

* `own-rnd-duty-is-concentration-adr055`
* `owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst`

— и обе на `origin/main` давно `ingested`. Обе решения разобраны, ADR написаны, работа
сделана и доставлена. Цикл #178 начал разбирать их заново и остановился только потому,
что сверил статусы руками.

**Почему это не пройдёт само.** Ответ владельца пишет Telegram-бот в ХОСТ-дерево
(`owner_choice` + `owner_answered_at` + блок «## Решение владельца»). Инжест делает цикл
в изолированном worktree и пушит на origin. Хост-копию не обновляет НИКТО — она остаётся
`owner-done` навсегда. Значит список фальшивых «решений владельца» только растёт.

**Что чинится.** У каждой карточки в JSON появляется поле `origin_check`; отсутствие
сверки — `unmeasured`, а не молчаливое «ок». Для `diverged`-карточки в статусе
`owner-done` вердикт ДОИЗМЕРЯЕТСЯ по статусу той же карточки на origin — прежде на этом
месте стояло глухое «кто новее НЕ измерено».

**Чего сторож НЕ делает.** Он не выбрасывает карточку из списка: `owner-done` в дереве
при `ingested` на origin — это «скорее всего уже разобрано», а не доказательство. Решает
сессия. Fail-CLOSED к прежнему поведению: не смог измерить ⇒ `unmeasured`, не «agrees».
Обратный контроль на это есть ниже (`test_..._is_not_dropped_from_the_list`,
`test_..._unreadable_origin_is_unmeasured_not_agrees`).

Литеральных дат здесь нет: всё состояние задаётся содержимым фикстур, календарь на эти
тесты не влияет (правило про фиксированные даты — `.claude/rules/deployment.md`).
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

REF = "main"


# ── крошечный репозиторий с «origin» в той же ветке; сети нет ────────────────

def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / drift.TRACKER_REL


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _owner_card(status="owner-done", body="тело", extra=""):
    """Карточка решения владельца. `extra` — то, что дописывает Telegram-бот."""
    return (f"---\ntrackerStatus:\n  type: owner-decision\n"
            f"title: \"вопрос владельцу\"\nstatus: {status}\n{extra}---\n\n{body}\n")


def _list_json(repo_root, status="owner-done", extra_argv=()):
    """Ровно та команда, которую предписывает шаг 2 протокола."""
    argv = ["list", "--type", "owner-decision", "--status", status,
            "--tracker-dir", str(_tracker(repo_root)), "--ref", REF, "--json", *extra_argv]
    args = oq.build_parser().parse_args(argv)
    oq.cmd_list(args)


def _capture(capsys) -> list[dict]:
    return json.loads(capsys.readouterr().out)


def _bot_answered(root, name, choice="A"):
    """Воспроизводит РЕАЛЬНУЮ последовательность 08–09.08.

    1. вопрос уезжает на origin (`needs-owner`);
    2. бот пишет ответ владельца в ХОСТ-дерево (`owner-done` + метаданные ответа);
    3. цикл инжестит в worktree и пушит на origin (`ingested`), хост-копию не трогая.

    На выходе — дерево с `owner-done` и origin с `ingested`, то есть ровно то состояние,
    в котором прод-дерево находилось 09.08.
    """
    _write(root, name, _owner_card(status="needs-owner"))
    _commit(root)
    answered = _owner_card(
        status="owner-done",
        body="## Решение владельца\n\n**Вариант A**",
        extra=f"owner_choice: {choice}\nowner_answered_at: 2026-01-01T00:00:00+00:00\n",
    )
    # то, что пушит цикл после инжеста (текст перезаписан агентом — это `diverged`)
    _write(root, name, _owner_card(status="ingested",
                                   body="## ОТВЕТ ВЛАДЕЛЬЦА: вариант A — разобрано"))
    _commit(root)
    # хост-дерево остаётся с ботовой версией: её никто не обновляет
    _write(root, name, answered)


# ── авария №1: уже разобранное решение выдаётся как свежее ───────────────────

def test_already_ingested_answer_is_named_in_the_json(repo, capsys):
    """ЯДРО ДЕФЕКТА. Два таких прилетели шагу 2 живьём 09.08."""
    _bot_answered(repo, "owner-decision-x")
    _list_json(repo)
    cards = _capture(capsys)

    assert len(cards) == 1, "карточка должна остаться в списке — сторож называет, а не прячет"
    assert cards[0]["origin_check"] == oq.VERDICT_MAYBE_INGESTED, (
        "шаг 2 читает JSON: вердикт обязан быть ТАМ, а не только в stderr-прозе"
    )
    assert cards[0]["origin_status"] == "ingested"


def test_already_ingested_answer_is_not_dropped_from_the_list(repo, capsys):
    """Обратный контроль: «скорее всего разобрано» ≠ доказательство. Решает сессия.

    Без этого теста «починка» вида «молча выбросить такие карточки» была бы зелёной —
    и съедала бы настоящий повторный ответ владельца.
    """
    _bot_answered(repo, "owner-decision-x")
    _list_json(repo)
    assert [c["id"] for c in _capture(capsys)] == ["owner-decision-x"]


def test_stderr_names_the_already_ingested_card_by_name(repo, capsys):
    """Человек у терминала обязан увидеть то же, что и `| jq`."""
    _bot_answered(repo, "owner-decision-x")
    _list_json(repo)
    err = capsys.readouterr().err
    assert "ОТВЕТ ВЛАДЕЛЬЦА УЖЕ РАЗОБРАН" in err
    assert "owner-decision-x" in err


def test_human_readable_list_shows_the_verdict_too(repo, capsys):
    """Без `--json` вердикт тоже виден: два выхода не имеют права расходиться."""
    _bot_answered(repo, "owner-decision-x")
    args = oq.build_parser().parse_args(
        ["list", "--type", "owner-decision", "--status", "owner-done",
         "--tracker-dir", str(_tracker(repo)), "--ref", REF])
    oq.cmd_list(args)
    assert oq.VERDICT_MAYBE_INGESTED in capsys.readouterr().out


# ── контроль в обратную сторону: настоящий свежий ответ не гасится ───────────

def test_genuinely_fresh_owner_answer_is_not_marked_ingested(repo, capsys):
    """САМЫЙ ВАЖНЫЙ обратный контроль.

    Если бы сторож метил «уже разобрано» по одному лишь факту расхождения, он гасил бы
    ровно то, ради чего существует очередь, — свежий ответ владельца.
    """
    _write(repo, "owner-decision-x", _owner_card(status="needs-owner"))
    _commit(repo)
    # владелец только что ответил; на origin карточка ВСЁ ЕЩЁ ждёт ответа
    _write(repo, "owner-decision-x",
           _owner_card(status="owner-done", body="## Решение владельца\n\n**Вариант B**",
                       extra="owner_choice: B\n"))
    _list_json(repo)
    cards = _capture(capsys)

    assert len(cards) == 1
    assert cards[0]["origin_check"] != oq.VERDICT_MAYBE_INGESTED, (
        "свежий ответ владельца объявлен уже разобранным — очередь молча теряет решение"
    )


def test_card_agreeing_with_origin_is_marked_agrees(repo, capsys):
    """Нет расхождения — нет и тревоги. Иначе поле обесценится шумом."""
    _write(repo, "owner-decision-x", _owner_card(status="owner-done"))
    _commit(repo)
    _list_json(repo)
    assert _capture(capsys)[0]["origin_check"] == oq.VERDICT_AGREES


# ── fail-CLOSED: неизмеренное обязано выглядеть неизмеренным ─────────────────

def test_disabled_origin_check_is_unmeasured_not_agrees(repo, capsys):
    """`--no-origin-check` — это «не измерено», а не «сверено и совпало».

    Положительный контроль исходного дефекта: со снятой сверкой поле обязано честно
    сказать, что сверки не было.
    """
    _bot_answered(repo, "owner-decision-x")
    _list_json(repo, extra_argv=("--no-origin-check",))
    cards = _capture(capsys)
    assert cards[0]["origin_check"] == oq.VERDICT_UNMEASURED


def test_every_card_carries_the_field_even_when_guard_cannot_run(repo, capsys, monkeypatch):
    """Отсутствие поля читалось бы как «ок». Поле есть ВСЕГДА.

    Сторож не должен ронять очередь (сверка — довесок), но и молчать не имеет права.
    """
    _bot_answered(repo, "owner-decision-x")
    monkeypatch.setattr(drift, "analyze",
                        lambda *a, **k: (_ for _ in ()).throw(drift.Unmeasured("нет ref")))
    _list_json(repo)
    cards = _capture(capsys)
    assert cards and cards[0]["origin_check"] == oq.VERDICT_UNMEASURED


def test_unreadable_origin_version_is_unmeasured_not_agrees(repo, capsys, monkeypatch):
    """Расхождение есть, а доизмерить его нечем ⇒ «не измерено», не «совпало».

    Ломаем чтение origin ТОЛЬКО для доизмерения, уже после `analyze` — сам `analyze`
    тоже читает карточки с origin, и глобальная поломка увела бы тест в соседнюю ветку
    (это проверяет `test_every_card_carries_the_field_even_when_guard_cannot_run`).
    """
    _bot_answered(repo, "owner-decision-x")
    real_analyze, real_read = drift.analyze, drift.read_origin_card
    state = {"analyzed": False}

    def _analyze(*a, **k):
        report = real_analyze(*a, **k)
        state["analyzed"] = True
        return report

    def _read(*a, **k):
        if state["analyzed"]:
            raise drift.Unmeasured("нет блоба")
        return real_read(*a, **k)

    monkeypatch.setattr(drift, "analyze", _analyze)
    monkeypatch.setattr(drift, "read_origin_card", _read)

    _list_json(repo)
    cards = _capture(capsys)
    assert cards[0]["origin_check"] == oq.VERDICT_DIVERGED, (
        "не смогли доизмерить — обязаны сказать это, а не отчитаться «совпало»"
    )
    assert "прочитать не удалось" in cards[0].get("origin_check_note", "")


# ── соседние виды расхождений тоже обязаны называться ────────────────────────

def test_stale_card_read_from_origin_says_so(repo, capsys):
    """Карточка перечитана с origin — это тоже факт для машинного контракта."""
    _write(repo, "owner-decision-x", _owner_card(status="owner-done"))
    _commit(repo)
    stale = (_tracker(repo) / "owner-decision-x.md").read_text(encoding="utf-8")
    _write(repo, "owner-decision-x", _owner_card(status="ingested"))
    _commit(repo)
    _write(repo, "owner-decision-x", stale)          # дерево отстало ДОСЛОВНО

    _list_json(repo, status="ingested")
    cards = _capture(capsys)
    assert cards[0]["origin_check"] == oq.VERDICT_STALE, (
        "статус взят с origin, а машинный контракт об этом молчит"
    )


def test_card_missing_on_origin_is_marked_undelivered(repo, capsys):
    """Карточка, которой на origin нет, — недоставленная. Живьём так теряли вопросы владельцу."""
    _write(repo, "owner-decision-seed", _owner_card(status="ingested"))
    _commit(repo)
    _write(repo, "owner-decision-new", _owner_card(status="owner-done"))  # не коммитили

    _list_json(repo)
    cards = _capture(capsys)
    assert [c["id"] for c in cards] == ["owner-decision-new"]
    assert cards[0]["origin_check"] == oq.VERDICT_UNDELIVERED
