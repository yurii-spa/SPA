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


def _head_away_from_ref(root):
    """Увести `HEAD` от `ref`, НЕ тронув копию карточки — форма прод-дерева.

    ЗАЧЕМ ЭТО НУЖНО (ADR-504, заказ G38 п. 1). Пока `HEAD` И ЕСТЬ `ref`, а файл
    карточки не правлен, копия сверяется САМА С СОБОЙ: ни один из пяти классов
    расхождения физически не может сработать, и «копии сошлись» выходит при любом
    предмете. Тест, построенный так, зелен ПО ПОСТРОЕНИЮ, а не по тому, что
    проверяет. Прод-дерево от `origin/main` отстаёт по построению — там сверка
    содержательна, и здесь воспроизводится именно это: посторонний коммит уводит
    `HEAD`, копия карточки на обеих сторонах остаётся ПОБАЙТОВО равной.
    """
    _git(root, "checkout", "-q", "--detach")
    (root / "posadka.txt").write_text("не карточка\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "посторонний коммит: HEAD уходит от ref")


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
    """Обратная сторона: карточка, одинаковая в обеих копиях, зелёная.

    ИЗМЕНЕНО ЦИКЛОМ #722 (инв. #16: правка намеренная, названа и обоснована).
    Прежняя редакция коммитила карточку и на этом останавливалась, то есть
    оставляла `HEAD` РАВНЫМ `ref` при неправленом файле, — а это ровно та
    тавтология, ради которой написан ADR-504: зелёный выходил ПО ПОСТРОЕНИЮ, при
    любой логике согласия, и подмена вердикта пробы тест бы не уронила. Теперь
    `HEAD` уведён от `ref` (`_head_away_from_ref`), копия карточки остаётся
    побайтово равной, и утверждение «согласие даёт зелёный» стало проверяемым.
    Это УСИЛЕНИЕ теста, а не ослабление: он перестал проходить по чужой причине.
    """
    (_tracker(repo) / f"{CARD}.md").write_text(_card(status="in-progress"),
                                               encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "обе копии равны")
    _head_away_from_ref(repo)
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail
    assert "копии сошлись" in detail, detail
    assert "ТАВТОЛОГИЧНА" not in detail, detail


def test_a_delivered_closure_is_satisfied(repo):
    """Закрыто в ОБЕИХ копиях — доставлено, претензии нет.

    ИЗМЕНЕНО ЦИКЛОМ #722 по той же причине и с тем же обоснованием, что у соседа
    выше: `HEAD` равнялся `ref` при неправленом файле, и зелёный был свойством
    ДЕРЕВА, а не наблюдением о доставленном закрытии (ADR-504).
    """
    (_tracker(repo) / f"{CARD}.md").write_text(
        _card(status="done", trail=[_trail(ts(hours_ago=2), "in-progress", "done")]),
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "закрытие доехало")
    _head_away_from_ref(repo)
    verdict, detail = _probe(repo)
    assert verdict == SATISFIED, detail
    assert "ТАВТОЛОГИЧНА" not in detail, detail


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


# ---------------------------------------------------------------------------------
# ТАВТОЛОГИЯ СВЕРКИ (ADR-504, заказ G38 п. 1) — пустая находка бывает свойством
# ДЕРЕВА, а не наблюдением о карточке. Каждое утверждение с обратной стороной.
# ---------------------------------------------------------------------------------

def test_a_tautological_comparison_is_unmeasured_not_satisfied(repo):
    """ЖИВОЙ ЗАМЕР 29.09: `HEAD` == `ref`, файл не правлен ⇒ НЕ ИЗМЕРЕНО.

    Положительный контроль настоящей аварии. Из worktree на чистом `fd3a509a5`
    проба отвечала `satisfied` «копии сошлись» про стоячий приказ владельца, чьи
    копии в проде расходятся: сверять было нечего, и зелёный был гарантирован
    независимо от предмета. Прежняя редакция называла эту опасность прозой в
    docstring и печатала дерево с ref в `detail`, но вердиктом оставляла
    «выполнено» — названная в тексте ловушка вердиктом не становится (инв. #17).
    """
    (_tracker(repo) / f"{CARD}.md").write_text(_card(status="in-progress"),
                                               encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "одна копия — сверять нечего")
    verdict, detail = _probe(repo)
    assert verdict == UNMEASURED, detail
    assert verdict != SATISFIED
    assert "ТАВТОЛОГИЧНА" in detail, detail
    assert "САМА С СОБОЙ" in detail, detail


def test_a_dirty_card_copy_at_the_same_commit_is_measured(repo):
    """Обратная сторона №1: `HEAD` == `ref`, но файл карточки правлен ⇒ сверка идёт.

    Отказ обязан быть УЗКИМ. Если бы тавтологией считался сам факт `HEAD == ref`,
    проба перестала бы мерить ровно ту форму, ради которой написана: прод-дерево
    пишет карточки мимо git, и правленый файл при том же коммите — это и есть
    живое расхождение.
    """
    _closed_here_only(repo)          # коммит на ref + правка в дереве
    head = _git(repo, "rev-parse", "HEAD").strip()
    ref = _git(repo, "rev-parse", REF).strip()
    assert head == ref, "предпосылка теста: коммит один и тот же"
    verdict, detail = _probe(repo)
    assert verdict == NOT_SATISFIED, detail
    assert "ЗАКРЫТО ТОЛЬКО ЗДЕСЬ" in detail, detail


def test_the_tautology_is_asked_per_card_not_per_directory(repo):
    """Обратная сторона №2 — ГРАНУЛЯРНОСТЬ. Чужая правка в каталоге не лечит тавтологию.

    Положительный контроль решения «спрашивать про ФАЙЛ, а не про КАТАЛОГ». Здесь
    спрошенная карточка чиста при `HEAD == ref` (её сверка тавтологична), а рядом
    в каталоге лежит правленая ДРУГАЯ карточка. Мерка по каталогу ответила бы
    «сравнение содержательно» и вернула бы тот самый зелёный, ради которого всё
    написано; покарточная — отказывает. Не покрасней этот тест, разница между двумя
    гранулярностями была бы неразличима.
    """
    (_tracker(repo) / f"{CARD}.md").write_text(_card(status="in-progress"),
                                               encoding="utf-8")
    (_tracker(repo) / "inbox-sosed.md").write_text(_card(status="new"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "две карточки на ref")
    (_tracker(repo) / "inbox-sosed.md").write_text(_card(status="done"), encoding="utf-8")
    verdict, detail = _probe(repo)
    assert verdict == UNMEASURED, detail
    assert "ТАВТОЛОГИЧНА" in detail, detail


def test_a_real_finding_is_never_swallowed_by_the_refusal(repo):
    """ПОРЯДОК действий: есть находка ⇒ про тавтологию не спрашивают вовсе.

    Сверка, давшая находку, доказала свою содержательность собой. Спроси мы
    тавтологию РАНЬШЕ находки, отказ съел бы живую аварию — и проба стала бы
    молчать именно там, где обязана кричать.
    """
    _closed_here_only(repo)
    verdict, detail = _probe(repo)
    assert verdict == NOT_SATISFIED, detail
    assert "ТАВТОЛОГИЧНА" not in detail, detail


def test_an_unreadable_head_is_unmeasured_not_meaningful():
    """Третий исход у самой мерки тавтологии: `git` не ответил ⇒ НЕ УСТАНОВЛЕНО.

    `git`, который не ответил, не есть разрешение считать сверку содержательной:
    иначе мерка тавтологии сама обзавелась бы fail-OPEN — «не спросили» стало бы
    неотличимо от «спросили и сверка содержательна».
    """
    from spa_core.monitoring import card_acceptance as ca

    taut, why = ca._tracker_comparison_tautological("/nety/takogo/dereva", "x.md", "")
    assert taut is None, why
    assert "не прочитан" in why, why


def test_an_unreadable_head_refuses_the_probe_too(repo, monkeypatch):
    """Та же непрочитанность, доведённая ДО ВЕРДИКТА пробы, а не только до мерки.

    «Половина инъекции» — та же бомба: мерка может честно вернуть `None`, а проба
    всё равно ответить «сошлись», если ветку никто не проводил.
    """
    from spa_core.monitoring import card_acceptance as ca

    (_tracker(repo) / f"{CARD}.md").write_text(_card(status="in-progress"),
                                               encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "на ref")
    monkeypatch.setattr(ca, "_tracker_comparison_tautological",
                        lambda *a, **k: (None, "прибор молчит"))
    verdict, detail = _probe(repo)
    assert verdict == UNMEASURED, detail
    assert "НЕ УСТАНОВЛЕНА" in detail, detail


# ---------------------------------------------------------------------------------
# Контракт самой мерки тавтологии. ЗАЧЕМ ОТДЕЛЬНО: через пробу эти ветки НЕ
# достижимы, и это ИЗМЕРЕНО, а не предположено. Батарея мутаций цикла #722 дала
# на них трёх выживших, потому что у спрошенной карточки «файл правлен» влечёт
# находку, а находка отменяет вопрос о тавтологии вовсе. Мерка — модульная функция
# со своим объявленным контрактом, и он проверяется у неё, а не у потребителя.
# ---------------------------------------------------------------------------------

def _taut(root, card_path, ref_sha):
    from spa_core.monitoring import card_acceptance as ca
    return ca._tracker_comparison_tautological(str(root), str(card_path), ref_sha)


def test_the_measure_calls_a_dirty_card_copy_meaningful(repo):
    """Файл правлен при том же коммите ⇒ сверка СОДЕРЖАТЕЛЬНА (не тавтология)."""
    card = _tracker(repo) / f"{CARD}.md"
    card.write_text(_card(status="in-progress"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "на ref")
    head = _git(repo, "rev-parse", "HEAD").strip()
    card.write_text(_card(status="done"), encoding="utf-8")
    taut, why = _taut(repo, card, head)
    assert taut is False, why
    assert "содержательно" in why, why


def test_the_measure_calls_a_clean_card_copy_at_the_same_commit_tautological(repo):
    """Обратная сторона: тот же коммит и НЕ правленый файл ⇒ тавтология."""
    card = _tracker(repo) / f"{CARD}.md"
    card.write_text(_card(status="in-progress"), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "на ref")
    head = _git(repo, "rev-parse", "HEAD").strip()
    taut, why = _taut(repo, card, head)
    assert taut is True, why
    assert "САМА С СОБОЙ" in why, why


def test_the_measure_refuses_when_head_is_unreadable(tmp_path):
    """HEAD не прочитан ПРИ ИЗВЕСТНОМ sha ref ⇒ `None`, а не «содержательно».

    Ветка отдельная от «sha ref не прочитан»: с пустым `ref_sha` мерка выходит
    раньше, и батарея показала это — мутант в ветке ref был убит, а в ветке HEAD
    выжил, то есть до неё не доходил ни один тест.
    """
    taut, why = _taut(tmp_path / "net-dereva", "x.md", "0" * 40)
    assert taut is None, why
    assert "HEAD дерева не прочитан" in why, why


def test_the_measure_refuses_when_the_file_state_is_unreadable(repo, monkeypatch):
    """`git status` не ответил ⇒ `None`. Молчание двери не есть «файл чист».

    Дверь к ОС здесь одна — `_git`, — и подменяется она ЦЕЛИКОМ: `rev-parse`
    отвечает, `status` молчит. Без этой ветки «не спросили» было бы неотличимо от
    «спросили и правок нет», то есть от тавтологии со зелёным вердиктом.
    """
    from spa_core.monitoring import card_acceptance as ca

    sha = "a" * 40

    def fake_git(args, *, repo_root, timeout=20.0):
        if args[:1] == ["rev-parse"]:
            return sha + "\n"
        return None

    monkeypatch.setattr(ca, "_git", fake_git)
    taut, why = _taut(repo, _tracker(repo) / f"{CARD}.md", sha)
    assert taut is None, why
    assert "не прочитано" in why, why
