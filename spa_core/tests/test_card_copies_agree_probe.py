"""Проба «копии карточки сошлись» — и обратная сторона у каждой проверки.

**Авария, которую воспроизводит набор** (замер 04.09, цикл #483; он же жив 18.09,
цикл #629). Стоячий приказ владельца
``inbox-task-portfolio-cio-dynamic-capital-alloc`` в прод-дереве помечен ``done``
(след `new -> done`, 31.08), а на ``origin/main`` стоит ``in-progress`` с
``priority: critical`` и блоком «УКАЗАНИЕ ВЛАДЕЛЬЦА» от 22.08, какого в
прод-копии нет вовсе. Шаг 0a-ГОЛОД читает origin и 655 часов зовёт приказ
голодающим; прибор, читающий прод-копию, считает его выполненным. Два ответа об
одной карточке, и оба выглядят измеренными — то есть «сделано» стояло на копии, а
не на работе.

Проверки идут парами: проба обязана КРАСНЕТЬ на этой форме и обязана НЕ краснеть
на соседних, которые выглядят так же, но ею не являются (закрытие доехало;
закрыто на ref, открыто здесь; порядок отметок не установлен). Отдельная пара — на
третий исход: нет репозитория, нет карточки ⇒ ``unmeasured`` с причиной, и
НИКОГДА не «выполнено».

Литеральных дат нет: отметки относительные (`_freshness.ts`), предмет — ПОРЯДОК
двух отметок, а не календарь.
"""
# LLM_FORBIDDEN
from __future__ import annotations

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
from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED, PROBES, SATISFIED, UNMEASURED, _probe_card_copies_agree,
    validate_spec,
)
from spa_core.tests._freshness import ts  # noqa: E402

REF = "main"
CARD = "inbox-task-cio"


def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(*, status="new", trail=(), body="тело"):
    extra = ""
    if trail:
        extra = "status_trail:\n" + "".join(f'  - "{line}"\n' for line in trail)
    return (f'---\ntrackerStatus:\n  type: inbox\ntitle: "карточка"\nstatus: {status}\n'
            f"{extra}---\n\n{body}\n")


def _trail(stamp, old, new):
    return f"{stamp} {old} -> {new} · queue.set_status"


@pytest.fixture()
def repo(tmp_path):
    """Крошечный репозиторий с каталогом трекера и веткой-«origin». Без сети."""
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _git(root.parent, "init", "-q", "-b", REF, str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / drift.TRACKER_REL


def _diverge(root, name, *, origin_text, tree_text):
    (_tracker(root) / f"{name}.md").write_text(origin_text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "на ref")
    (_tracker(root) / f"{name}.md").write_text(tree_text, encoding="utf-8")


def _probe(root, card=CARD):
    return _probe_card_copies_agree(card, tracker_dir=str(_tracker(root)), ref=REF)


def _closed_here_only(root):
    """Живая форма аварии: закрыто здесь, открыто на ref, наша отметка позже."""
    _diverge(root, CARD,
             origin_text=_card(status="in-progress",
                               trail=[_trail(ts(hours_ago=48), "new", "in-progress")]),
             tree_text=_card(status="done",
                             trail=[_trail(ts(hours_ago=48), "new", "in-progress"),
                                    _trail(ts(hours_ago=2), "in-progress", "done")]))


# ---------------------------------------------------------------------------------
# Авария — проба обязана краснеть
# ---------------------------------------------------------------------------------

def test_closure_that_exists_only_here_is_not_satisfied(repo):
    _closed_here_only(repo)
    verdict, detail = _probe(repo)
    assert verdict == NOT_SATISFIED, detail
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" in detail
    assert "`done`" in detail and "`in-progress`" in detail


def test_the_verdict_names_the_tree_it_measured(repo):
    """Зелёный из worktree не смеет читаться как зелёный в проде — дерево названо."""
    _closed_here_only(repo)
    _, detail = _probe(repo)
    assert str(repo) in detail, detail
    assert REF in detail


# ---------------------------------------------------------------------------------
# Соседи, которые выглядят так же, но аварией не являются — проба НЕ смеет краснеть
# ---------------------------------------------------------------------------------

def test_agreeing_copies_are_satisfied(repo):
    """Обратная сторона: карточка, одинаковая в обеих копиях, зелёная."""
    (_tracker(repo) / f"{CARD}.md").write_text(_card(status="in-progress"),
                                               encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "обе копии равны")
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail


def test_a_delivered_closure_is_satisfied(repo):
    """Закрыто в ОБЕИХ копиях — доставлено, претензии нет."""
    (_tracker(repo) / f"{CARD}.md").write_text(
        _card(status="done", trail=[_trail(ts(hours_ago=2), "in-progress", "done")]),
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "закрытие доехало")
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail


def test_the_mirror_case_is_not_this_defect(repo):
    """Закрыто на ref, открыто здесь — ЗЕРКАЛО, и это не «закрыто только здесь».

    Направление обязано быть измерено: прод-дерево — писатель ответов владельца,
    и «здесь другое» само по себе не решает ничего.
    """
    _diverge(repo, CARD,
             origin_text=_card(status="done",
                               trail=[_trail(ts(hours_ago=2), "in-progress", "done")]),
             tree_text=_card(status="in-progress",
                             trail=[_trail(ts(hours_ago=48), "new", "in-progress")]))
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in detail


def test_an_open_card_diverging_in_body_only_is_not_this_defect(repo):
    """Разошлись тела, но здесь НЕ закрыто — класс другой, и проба молчит."""
    _diverge(repo, CARD,
             origin_text=_card(status="in-progress", body="старое тело",
                               trail=[_trail(ts(hours_ago=48), "new", "in-progress")]),
             tree_text=_card(status="in-progress", body="новое тело",
                             trail=[_trail(ts(hours_ago=2), "new", "in-progress")]))
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail


def test_a_later_mark_on_the_ref_is_not_a_closure_only_here(repo):
    """Закрыто здесь, открыто на ref, но отметка REF ПОЗЖЕ — направление другое.

    Так выглядит поздний ответ владельца: бот пишет в прод-дерево мимо git, и
    «у нас закрыто, а там открыто» само по себе не решает ничего. Без проверки
    порядка проба красила бы именно этот случай — батарея цикла показала, что
    зеркальный сосед выше этот конъюнкт не задевает.
    """
    _diverge(repo, CARD,
             origin_text=_card(status="in-progress",
                               trail=[_trail(ts(hours_ago=2), "new", "in-progress")]),
             tree_text=_card(status="done",
                             trail=[_trail(ts(hours_ago=48), "in-progress", "done")]))
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in detail


def test_two_diverging_terminal_copies_are_not_this_defect(repo):
    """Разные тела, но закрыто в ОБЕИХ копиях — закрытие доехало, претензии нет.

    Конъюнкт «на ref ОТКРЫТО» держится именно здесь: у соседа с равными телами
    расхождения нет вовсе, и он этой ветки не касается.
    """
    _diverge(repo, CARD,
             origin_text=_card(status="ingested", body="старое тело",
                               trail=[_trail(ts(hours_ago=48), "owner-done", "ingested")]),
             tree_text=_card(status="done", body="новое тело",
                             trail=[_trail(ts(hours_ago=2), "in-progress", "done")]))
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" not in detail


# ---------------------------------------------------------------------------------
# Третий исход — «не измерено» никогда не выдаётся за «выполнено»
# ---------------------------------------------------------------------------------

def test_a_card_absent_everywhere_is_unmeasured_not_satisfied(repo):
    """Спрошенной карточки нет ни в дереве, ни на ref ⇒ предмет НЕ ИЗМЕРЕН.

    Репозиторий здесь НАСЕЛЁН намеренно. Первая редакция спрашивала пустой репозиторий
    без единого коммита — сверка падала раньше, чем доходила до ветки «карточки нет»,
    тест проходил по ДРУГОЙ причине, и дифференциальная батарея этого цикла показала
    это: подмена отказа в той ветке на «выполнено» тест НЕ уронила.
    """
    _closed_here_only(repo)
    verdict, detail = _probe(repo, card="inbox-nikogda-ne-bylo")
    assert verdict == UNMEASURED, detail
    assert "НЕ ИЗМЕРЕН" in detail


def test_a_missing_argument_is_unmeasured():
    verdict, detail = _probe_card_copies_agree(None)
    assert verdict == UNMEASURED
    assert "card_copies_agree" in detail


def test_a_directory_without_a_repository_is_unmeasured(tmp_path):
    tracker = tmp_path / "bare" / drift.TRACKER_REL
    tracker.mkdir(parents=True)
    verdict, detail = _probe_card_copies_agree(CARD, tracker_dir=str(tracker), ref=REF)
    assert verdict == UNMEASURED, detail
    assert "НЕ ИЗМЕРЕНО" in detail


def test_an_unreadable_ref_is_unmeasured_not_clean(repo):
    """ref, которого нет, — «не измерено», а НЕ «расхождений не найдено».

    Это положительный контроль fail-OPEN: пустой ответ сверки выглядит как чистый,
    и именно так молчат сторожа, никогда не видевшие поломки.
    """
    _closed_here_only(repo)
    verdict, detail = _probe_card_copies_agree(
        CARD, tracker_dir=str(_tracker(repo)), ref="net-takoi-vetki")
    assert verdict == UNMEASURED, detail
    assert verdict != SATISFIED


# ---------------------------------------------------------------------------------
# Реестр: объявление пробы принимается писателем карточек
# ---------------------------------------------------------------------------------

def test_the_probe_is_registered_and_its_spec_validates():
    assert "card_copies_agree" in PROBES
    assert validate_spec(f"card_copies_agree:{CARD}") is None


def test_an_unregistered_neighbour_name_is_still_refused():
    """Обратная сторона: реестр не стал принимать что попало."""
    assert validate_spec("card_copies_agree_maybe:x") is not None
