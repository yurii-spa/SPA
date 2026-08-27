"""Очередь слепа по СОСТАВУ: карточка есть на origin, файла в дереве нет — цикл #395.

**Каждый тест здесь — воспроизведение настоящей аварии 2026-08-27.** Проверка, никогда не
видевшая живой поломки, — украшение (правило `.claude/rules/deployment.md`).

Что случилось. Протокол велит делать шаг 1 (разбор Inbox) и шаг 2 (инжест решений владельца)
через `scripts/orchestrator_queue.py` **из прод-дерева**. Цикл #393 задал оттуда штатный вопрос
и получил::

    owner-done: 0   ⇒ «инжестить нечего»

Тот же вопрос чистому `origin/main` на ТОМ ЖЕ sha дал **2**. Цикл #395 перемерил шире:
`inbox --status new` — **42** из прод-дерева против **89** с origin. Причина не в статусах:
файлов этих карточек в прод-дереве нет ВООБЩЕ (233 карточки из 714).

Компенсация read-through умела ровно одно — «локальная копия УСТАРЕЛА» (`KIND_STALE`): она
брала местную карточку и подменяла её версией с origin. Карточка, которой в дереве нет,
в этот механизм не попадала — `by_id.get(id)` отдавал `None`, и цикл её молча пропускал.
Один инструмент отвечал по-разному на ОДИН вопрос «что на origin», и разъезд был гарантирован.

Опасна была ФОРМА ответа: инструмент печатал уверенное ЧИСЛО, а не «не измерено». `owner-done: 0`
читается как «очередь разобрана» — молчание, неотличимое от одобрения, ровно тот класс, который
проект ловит у сторожей.

Литеральных дат здесь нет: репозиторий-фикстура строится в `tmp_path`, календарь на эти тесты
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

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    """Крошечный репозиторий с каталогом трекера и веткой-«origin». Без сети."""
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / drift.TRACKER_REL


def _card(kind="inbox", title="карточка", status="new", body="тело"):
    return (f"---\ntrackerStatus:\n  type: {kind}\ntitle: \"{title}\"\n"
            f"status: {status}\n---\n\n{body}\n")


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _list(root: Path, kind: str, status: str, capsys, extra=()):
    args = oq.build_parser().parse_args(
        ["list", "--type", kind, "--status", status, "--json",
         "--tracker-dir", str(_tracker(root)), "--ref", REF, *extra])
    code = oq.cmd_list(args)
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


# --------------------------------------------------------------------------------------
# Авария дословно: решение владельца лежит на origin, файла в прод-дереве нет.
# Шаг 2 отвечал «owner-done: 0» — уверенный ноль вместо «очередь неполна».
# --------------------------------------------------------------------------------------

def test_owner_done_only_on_origin_is_no_longer_answered_as_zero(repo, capsys):
    _write(repo, "own-otvet", _card(kind="owner-decision", title="ответ владельца",
                                    status="owner-done"))
    _commit(repo)
    (_tracker(repo) / "own-otvet.md").unlink()  # ровно состояние прод-дерева 27.08

    code, rows, err = _list(repo, "owner-decision", "owner-done", capsys)

    assert [r["id"] for r in rows] == ["own-otvet"], (
        "шаг 2 снова ответил бы «инжестить нечего» при живом решении владельца на origin")
    assert rows[0]["status"] == "owner-done", "статус обязан читаться с origin"
    assert rows[0]["origin_check"] == oq.VERDICT_HIDDEN
    assert code == 0, "карточка ПРОЧИТАНА — состав измерен, повода для кода 2 нет"
    assert "own-otvet" in err, "находка обязана быть названа и человеку, а не только в JSON"


def test_hidden_inbox_task_reaches_step_1(repo, capsys):
    """Шаг 1 не видел 52 задания из 89. Слепы были ОБА шага, не только второй."""
    _write(repo, "inbox-vidimaya", _card(title="видимая"))
    _write(repo, "inbox-nevidimaya", _card(title="невидимая"))
    _commit(repo)
    (_tracker(repo) / "inbox-nevidimaya.md").unlink()

    _code, rows, _err = _list(repo, "inbox", "new", capsys)

    assert sorted(r["id"] for r in rows) == ["inbox-nevidimaya", "inbox-vidimaya"]


def test_filters_apply_to_hidden_cards_by_their_origin_status(repo, capsys):
    """Дочитанная карточка судится по СВОЕМУ статусу с origin, а не подмешивается всем подряд."""
    _write(repo, "inbox-zakrytaya", _card(title="закрытая", status="done"))
    _write(repo, "inbox-otkrytaya", _card(title="открытая", status="new"))
    _commit(repo)
    (_tracker(repo) / "inbox-zakrytaya.md").unlink()
    (_tracker(repo) / "inbox-otkrytaya.md").unlink()

    _code, rows, _err = _list(repo, "inbox", "new", capsys)

    assert [r["id"] for r in rows] == ["inbox-otkrytaya"], (
        "закрытая на origin карточка выдана как новая — дефект #147 наизнанку")


def test_hidden_card_carries_the_path_it_would_have_and_says_so(repo, capsys):
    """Путь-фантом назван вслух: по нему `set-status` откажет, и это ВЕРНЫЙ ответ."""
    _write(repo, "inbox-nevidimaya", _card())
    _commit(repo)
    (_tracker(repo) / "inbox-nevidimaya.md").unlink()

    _code, rows, _err = _list(repo, "inbox", "new", capsys)

    assert rows[0]["path"] == str(_tracker(repo) / "inbox-nevidimaya.md")
    assert not Path(rows[0]["path"]).exists()
    note = rows[0].get("origin_check_note", "")
    assert "worktree" in note, "сессии обязано быть сказано, ГДЕ эту карточку можно править"


def test_set_status_on_a_hidden_card_refuses_loudly(repo, capsys):
    """Довод прежней редакции («путь-фантом сломал бы set-status») закрыт замером.

    Он не ломает молча: отказ громкий и с ненулевым кодом. Именно это и требуется —
    карточка правится из worktree на origin/main, а не изобретается на месте.
    """
    _write(repo, "inbox-nevidimaya", _card())
    _commit(repo)
    (_tracker(repo) / "inbox-nevidimaya.md").unlink()
    _code, rows, _err = _list(repo, "inbox", "new", capsys)

    args = oq.build_parser().parse_args(["set-status", rows[0]["path"], "done"])
    assert oq.cmd_set_status(args) != 0, "молчаливый успех по несуществующему файлу"


# --------------------------------------------------------------------------------------
# Fail-CLOSED: карточку с origin прочитать не удалось ⇒ СОСТАВ не измерен ⇒ код 2.
# Число здесь врало бы ровно тем способом, ради которого написана вся сверка.
# --------------------------------------------------------------------------------------

def _blind_after_analyze(repo, monkeypatch, marker: str):
    """Ослепить ТОЛЬКО дочитывание карточки, оставив саму сверку измеренной.

    `drift.analyze` читает невидимую карточку сам (`check_tracker_drift.py:294`), и глухая
    подмена `read_origin_card` уронила бы сверку целиком — а это ДРУГАЯ ветка отказа
    («сверка НЕ ИЗМЕРЕНА»), со своим кодом возврата и своим текстом. Поэтому отчёт
    считаем настоящим кодом и замораживаем, а слепоту наводим уже после него.
    """
    report = drift.analyze(_tracker(repo), REF)
    monkeypatch.setattr(drift, "analyze", lambda *a, **k: report)
    real = drift.read_origin_card

    def _boom(root, ref, rel_path):
        if marker in rel_path:
            raise drift.Unmeasured("git show недоступен")
        return real(root, ref, rel_path)

    monkeypatch.setattr(drift, "read_origin_card", _boom)


def test_unreadable_hidden_card_makes_the_list_fail_closed(repo, capsys, monkeypatch):
    _write(repo, "inbox-nevidimaya", _card())
    _write(repo, "inbox-vidimaya", _card(title="видимая"))
    _commit(repo)
    (_tracker(repo) / "inbox-nevidimaya.md").unlink()
    _blind_after_analyze(repo, monkeypatch, "nevidimaya")

    code, rows, err = _list(repo, "inbox", "new", capsys)

    assert code == 2, "состав НЕ измерен, а список выдан уверенным числом"
    assert "inbox-nevidimaya" in err
    assert [r["id"] for r in rows] == ["inbox-vidimaya"], (
        "видимую карточку слепота на соседке выбрасывать не смеет")


def test_fail_closed_does_not_depend_on_the_requested_filter(repo, capsys, monkeypatch):
    """Непрочитанной карточке нечем ответить на `--type/--status` — судить о ней нельзя.

    Иначе код 2 гасился бы просто тем, что спросили про другой тип: слепота осталась бы,
    а сигнал исчез.
    """
    _write(repo, "own-nevidimaya", _card(kind="owner-decision", status="needs-owner"))
    _write(repo, "inbox-vidimaya", _card(title="видимая"))
    _commit(repo)
    (_tracker(repo) / "own-nevidimaya.md").unlink()
    _blind_after_analyze(repo, monkeypatch, "own-nevidimaya")

    code, _rows, _err = _list(repo, "inbox", "new", capsys)

    assert code == 2


# --------------------------------------------------------------------------------------
# Обратный контроль: без аварии никакой добавки быть не должно.
# --------------------------------------------------------------------------------------

def test_tree_matching_origin_gains_nothing_and_stays_green(repo, capsys):
    _write(repo, "inbox-a", _card(title="а"))
    _write(repo, "inbox-b", _card(title="б"))
    _commit(repo)

    code, rows, err = _list(repo, "inbox", "new", capsys)

    assert sorted(r["id"] for r in rows) == ["inbox-a", "inbox-b"]
    assert all(r["origin_check"] == oq.VERDICT_AGREES for r in rows)
    assert code == 0
    assert "РАСХОДИТСЯ" not in err


def test_no_origin_check_reproduces_the_defect_verbatim(repo, capsys):
    """Положительный контроль: со снятой сверкой авария 27.08 возвращается дословно."""
    _write(repo, "own-otvet", _card(kind="owner-decision", status="owner-done"))
    _commit(repo)
    (_tracker(repo) / "own-otvet.md").unlink()

    _code, rows, _err = _list(repo, "owner-decision", "owner-done", capsys,
                              extra=["--no-origin-check"])

    assert rows == [], "фикстура не воспроизводит дефект — тест ничего не доказывает"
