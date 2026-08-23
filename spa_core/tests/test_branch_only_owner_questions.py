"""Вопрос владельцу, живущий ТОЛЬКО на ветке — третье плечо класса «вопрос невидим».

КАЖДЫЙ тест — положительный контроль реальной аварии **23.08.2026** (цикл #351):

    на 36 удалённых ветках лежало **18** карточек `owner-decision` в статусе
    `needs-owner`, которых на `origin/main` не было ни минуты;
    среди них `own-2026-08-22-snyat-changelog-so-saita` — вопрос ВНУТРИ открытого
    PR #35, просящий подпись владельца, без которой этот же PR не вливают.

Сторож `owner_decision_pending` при этом печатал шагом 0-офис
«очередь полна: невидимых дереву вопросов нет» — утверждение о полноте, замера под
которым не существовало: он сверяет дерево с `origin/main` и больше ни с чем, а
отправитель (`resend.open_questions`, #330) — дерево плюс `origin/main`. Карточка на
ветке невидима обеим сверкам, то есть вопрос нельзя ни задать, ни закрыть.

Обратный контроль здесь не украшение: `owner-decision-test-prizrak-ne-rozhdaetsya`
лежит на двух ВЛИТЫХ ветках и на `main` его нет — но он там БЫЛ и снят намеренно
(коммит `029627b46`). Потерянный вопрос и намеренно снятый обязаны различаться, и
различает их измерение (история пути на базовом ref), а не эвристика.

Все фикстуры — настоящие крошечные git-репозитории без сети (ветки создаются
`git update-ref refs/remotes/origin/*`): проверяется ЭФФЕКТ на git, а не подменённая
заглушка. Литеральных дат в фикстурах нет — вердикт модуля от календаря не зависит.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.owner_queue.origin_view import Unmeasured, branch_only_cards

BASE = "origin/main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(title="карточка", status="needs-owner", ctype="owner-decision", body="тело"):
    return (f"---\ntrackerStatus:\n  type: {ctype}\ntitle: \"{title}\"\n"
            f"status: {status}\n---\n\n{body}\n")


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с очередью и локальной веткой `work`, из которой лепим remote-ref."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", "main", str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / origin_view.TRACKER_REL


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    # `--allow-empty`: базу без карточек тоже надо уметь опубликовать — «очередь
    # пуста» это законное состояние, а не повод остаться без базового коммита.
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "--allow-empty", "-m", msg)


def _publish(root: Path, remote_branch: str, local: str = "HEAD"):
    """Сделать текущий коммит удалённой веткой. Сети не касается — только update-ref."""
    sha = _run(root, "rev-parse", local).strip()
    _run(root, "update-ref", f"refs/remotes/{remote_branch}", sha)


def _base_with(root: Path, **cards: str) -> None:
    """Опубликовать `origin/main` с названными карточками; дерево оставить пустым."""
    for name, text in cards.items():
        _write(root, name, text)
    _commit(root, "base")
    _publish(root, "origin/main")
    for name in cards:
        (_tracker(root) / f"{name}.md").unlink()
    _tracker(root).mkdir(parents=True, exist_ok=True)


def _branch_with(root: Path, branch: str, **cards: str) -> None:
    """Опубликовать ветку поверх текущей базы; дерево вернуть в исходное состояние."""
    for name, text in cards.items():
        _write(root, name, text)
    _commit(root, f"branch {branch}")
    _publish(root, f"origin/{branch}")
    _run(root, "reset", "-q", "--hard", "HEAD~1")
    for name in cards:
        path = _tracker(root) / f"{name}.md"
        if path.exists():
            path.unlink()
    # git снимает опустевший каталог вместе с последним файлом, а каталог очереди —
    # вход самой сверки: без него замер честно скажет «не измерено», и тест будет
    # проверять фикстуру вместо предмета.
    _tracker(root).mkdir(parents=True, exist_ok=True)


def _scan(root: Path, **kw):
    return branch_only_cards(_tracker(root), base_ref=BASE, **kw)


# ===========================================================================
# 1. Ядро аварии: вопрос есть только на ветке
# ===========================================================================
def test_a_question_living_only_on_a_branch_is_found(repo):
    """PR #35: `needs-owner` внутри ветки, и ни очередь, ни отправитель его не видят."""
    _base_with(repo, **{"own-staryi": _card(title="давний вопрос")})
    _branch_with(repo, "claude/changelog-to-attic",
                 **{"own-2026-08-22-snyat-changelog-so-saita":
                    _card(title="Снять журнал изменений с сайта")})

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert [c.card_id for c in scan.cards] == ["own-2026-08-22-snyat-changelog-so-saita"]
    found = scan.cards[0]
    assert found.branches == ("origin/claude/changelog-to-attic",), (
        "ветку обязаны НАЗВАТЬ: без неё находку нечем поднять")
    assert found.ever_on_base is False, "карточки не было на базе ни минуты — это потеря"
    assert found.title == "Снять журнал изменений с сайта"
    assert len(scan.base_sha) == 40, "sha базы обязан быть назван"
    assert scan.unreadable == ()


def test_a_card_present_on_the_base_is_not_a_branch_finding(repo):
    """Обратный контроль: плечо «есть на origin» меряет сосед, дублировать нельзя."""
    _base_with(repo, **{"own-34": _card()})
    _branch_with(repo, "claude/x", **{"own-34": _card()})

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert scan.cards == ()


def test_a_card_present_in_the_working_tree_is_not_a_branch_finding(repo):
    """Обратный контроль: карточка в живом дереве владельцу ДОСТИЖИМА."""
    _base_with(repo)
    _branch_with(repo, "claude/x", **{"own-v-dereve": _card()})
    _write(repo, "own-v-dereve", _card())          # сессия положила её в живое дерево

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert scan.cards == ()


# ===========================================================================
# 2. Потеряно ≠ снято намеренно (тест-зонд `owner-decision-test-prizrak…`)
# ===========================================================================
def test_a_card_deliberately_removed_from_the_base_is_not_a_loss(repo):
    """Зонд был на `main` и убран коммитом — находкой он быть не имеет права."""
    _base_with(repo, **{"owner-decision-test-prizrak-ne-rozhdaetsya": _card(title="тест")})
    _branch_with(repo, "claude/ghost-cards-live-tracker",
                 **{"owner-decision-test-prizrak-ne-rozhdaetsya": _card(title="тест")})
    # тот же коммит на базе, что 029627b46: зонд убран из очереди владельца
    _run(repo, "rm", "-q", str(_tracker(repo) / "owner-decision-test-prizrak-ne-rozhdaetsya.md"))
    _commit(repo, "cleanup: тест-зонд убран из очереди владельца")
    _publish(repo, "origin/main")
    _tracker(repo).mkdir(parents=True, exist_ok=True)

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert [c.card_id for c in scan.cards] == ["owner-decision-test-prizrak-ne-rozhdaetsya"]
    assert scan.cards[0].ever_on_base is True, (
        "карточка БЫЛА на базе и снята намеренно — это не потерянный вопрос")


def test_a_never_seen_card_and_a_removed_one_are_told_apart(repo):
    """Оба факта в одном замере: различать их обязан сам замер, а не читатель."""
    _write(repo, "own-snyataya", _card(title="снятая"))
    _commit(repo, "карточка заведена")
    (_tracker(repo) / "own-snyataya.md").unlink()
    _commit(repo, "снятие: наш зонд убран из очереди владельца")
    _publish(repo, "origin/main")
    _branch_with(repo, "claude/x",
                 **{"own-snyataya": _card(title="снятая"),
                    "own-poteryannaya": _card(title="потерянная")})

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    verdict = {c.card_id: c.ever_on_base for c in scan.cards}
    assert verdict == {"own-snyataya": True, "own-poteryannaya": False}


# ===========================================================================
# 3. Фильтры и дедуп
# ===========================================================================
def test_only_open_owner_questions_are_counted(repo):
    """Закрытая карточка и не-вопрос в счёт вопросов владельца не идут."""
    _base_with(repo)
    _branch_with(repo, "claude/x",
                 **{"own-otvechennaya": _card(status="owner-done"),
                    "own-otkrytaya": _card(status="needs-owner"),
                    "inbox-zadacha": _card(status="needs-owner", ctype="inbox")})

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert [c.card_id for c in scan.cards] == ["own-otkrytaya"]


def test_the_same_card_on_two_branches_is_named_once_with_both(repo):
    """Ветка-потомок несёт карточку предка: два имени одной потери — не две потери."""
    _base_with(repo)
    _branch_with(repo, "claude/a", **{"own-obschaya": _card()})
    _branch_with(repo, "claude/b", **{"own-obschaya": _card()})

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert len(scan.cards) == 1
    assert scan.cards[0].branches == ("origin/claude/a", "origin/claude/b")


def test_the_base_itself_is_never_scanned_as_a_branch(repo):
    """Иначе база сверялась бы с собой и давала вечный ноль, неотличимый от честного."""
    _base_with(repo, **{"own-34": _card()})

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert BASE not in scan.branches_read
    assert scan.cards == ()


# ===========================================================================
# 4. Fail-CLOSED: «не прочитано» обязано быть НАЗВАНО, а не пропущено
# ===========================================================================
def test_an_unreadable_branch_is_named_not_silently_skipped(repo):
    """Молча пропущенная ветка — это fail-OPEN внутри fail-CLOSED-сверки.

    Битая ссылка — не выдумка: неполный `fetch` и оборванная выкачка оставляют
    ref, указывающий в никуда, и `ls-tree` по нему возвращает код. Замер по
    остальным веткам обязан состояться, а эта — быть НАЗВАНА.
    """
    _base_with(repo)
    _branch_with(repo, "claude/celaya", **{"own-celaya": _card()})
    broken = repo / ".git" / "refs" / "remotes" / "origin" / "claude" / "bitaya"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("0" * 39 + "1\n", encoding="utf-8")

    scan = _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert [c.card_id for c in scan.cards] == ["own-celaya"], (
        "нечитаемая ветка не отменяет замер по остальным")
    assert [b for b, _ in scan.unreadable] == ["origin/claude/bitaya"]
    assert "origin/claude/bitaya" not in scan.branches_read


def test_a_tree_outside_a_repository_is_unmeasured_not_clean(tmp_path):
    """Пустой ответ здесь означал бы «на ветках вопросов нет» — ровно наоборот."""
    tracker = tmp_path / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)

    with pytest.raises(Unmeasured):
        branch_only_cards(tracker, base_ref=BASE)


def test_the_scan_never_goes_to_the_network(repo, monkeypatch):
    """Сторож в сеть не ходит: ответ — про локальные копии ветвей, и это свойство."""
    seen: list[list[str]] = []
    real = origin_view._git

    def spy(root, args, stdin_text=None):
        seen.append(list(args))
        return real(root, args, stdin_text)

    monkeypatch.setattr(origin_view, "_git", spy)
    _base_with(repo)
    _branch_with(repo, "claude/x", **{"own-x": _card()})
    seen.clear()

    _scan(repo, tracker_type="owner-decision", status="needs-owner")

    assert seen, "замер обязан был звать git — иначе тест бессмысленен"
    forbidden = {"fetch", "pull", "remote", "ls-remote", "clone"}
    assert not [a for a in seen if a and a[0] in forbidden], (
        f"замер ушёл в сеть: {[a for a in seen if a and a[0] in forbidden]}")


# ===========================================================================
# 5. Сторож: блок в отчёте и строка шага 0-офис
# ===========================================================================
def _report(repo, tmp_path):
    from spa_core.monitoring.owner_decision_pending import check_pending_owner_decisions

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return check_pending_owner_decisions(data_dir=data, tracker_dir=_tracker(repo))


def _office_lines(doc):
    from scripts.consume_office_reports import _summarize_json

    return "\n".join(_summarize_json("owner_decision_pending.json", doc))


def test_the_monitor_names_the_branch_only_question(repo, tmp_path):
    _base_with(repo)
    _branch_with(repo, "claude/changelog-to-attic",
                 **{"own-2026-08-22-snyat-changelog-so-saita": _card()})

    doc = _report(repo, tmp_path)

    assert doc["branch_queue_count"] == 1
    block = doc["branch_queue"]
    assert block["measured"] is True
    assert block["cards"][0]["card_id"] == "own-2026-08-22-snyat-changelog-so-saita"
    assert block["cards"][0]["branches"] == ["origin/claude/changelog-to-attic"]
    assert block["branches_read"] == 1


def test_zero_and_unmeasured_are_different_facts_in_the_report(repo, tmp_path):
    """Ноль находок и «померить не смогли» обязаны быть различимы в самом отчёте."""
    _base_with(repo)
    clean = _report(repo, tmp_path)
    assert clean["branch_queue_count"] == 0
    assert clean["branch_queue"]["measured"] is True

    from spa_core.monitoring.owner_decision_pending import _scan_branch_queue

    blind = _scan_branch_queue(tmp_path / "net-takogo-kataloga")
    assert blind["measured"] is False
    assert blind.get("reason"), "причина обязана быть названа СЛОВАМИ"
    assert "count" not in blind, "у неизмеренного не бывает числа находок"


def test_every_unmeasured_path_refuses_to_name_a_count(repo, tmp_path, monkeypatch):
    """Все три двери в «не измерено» обязаны выглядеть одинаково честно.

    Проверяется каждый вид отказа, а не один: сверка сказала `Unmeasured` ·
    упало неожиданное · упало `ImportError` (та же форма, что при отсутствии
    модуля). Достаточно ОДНОГО пути, который вернёт `count: 0`, чтобы сломанный
    обход выглядел как чистая очередь.
    """
    from spa_core.monitoring import owner_decision_pending as odp
    from spa_core.owner_queue import origin_view as ov

    def _assert_honest(block, label):
        assert block["measured"] is False, label
        assert block.get("reason"), f"{label}: причина обязана быть названа СЛОВАМИ"
        assert "count" not in block, f"{label}: у неизмеренного не бывает числа находок"

    for label, boom in (("Unmeasured", ov.Unmeasured("ветки не прочитаны")),
                        ("неожиданное", RuntimeError("git внезапно упал"))):
        def explode(*a, _boom=boom, **kw):
            raise _boom

        monkeypatch.setattr(ov, "branch_only_cards", explode)
        _assert_honest(odp._scan_branch_queue(_tracker(repo)), label)

    # Третья дверь — САМ импорт. Достаётся она только порчей `sys.modules`:
    # в здоровой установке модуль импортируется, и подмена функции эту ветку не
    # трогает вовсе (мутация «вернуть count: 0» здесь пережила прогон, пока
    # проверка шла подменой функции).
    monkeypatch.setitem(sys.modules, "spa_core.owner_queue.origin_view", None)
    _assert_honest(odp._scan_branch_queue(_tracker(repo)), "импорт недоступен")


def test_branch_findings_do_not_raise_the_report_status(repo, tmp_path):
    """Прецедент H7/H10/ADR-084: звонить владельцу о НАШЕЙ недоставке — тот же спам.

    Проверка в ОБЕ стороны: находка на ветке статус не поднимает, а находка соседа
    (`origin_queue`) — поднимает. Иначе тест доказывал бы лишь, что статус не растёт
    никогда.
    """
    _base_with(repo)
    _branch_with(repo, "claude/x", **{"own-poteryannyi": _card()})

    quiet = _report(repo, tmp_path)
    assert quiet["branch_queue_count"] == 1
    assert quiet["status"] == "OK", (
        "находка на ветке едет в отчёт и шаг 0-офис, а не в чат владельца")

    _base_with(repo, **{"own-na-origin": _card()})    # карточка на базе, файла в дереве нет
    loud = _report(repo, tmp_path)
    assert loud["status"] == "WARNING", (
        "обратный контроль: соседнее плечо статус ПОДНИМАЕТ — значит тест выше "
        "измеряет молчание именно этого плеча")


def test_office_step_names_the_lost_question(repo, tmp_path):
    _base_with(repo)
    _branch_with(repo, "claude/changelog-to-attic",
                 **{"own-2026-08-22-snyat-changelog-so-saita": _card()})

    text = _office_lines(_report(repo, tmp_path))

    assert "ТОЛЬКО НА ВЕТКЕ" in text
    assert "own-2026-08-22-snyat-changelog-so-saita" in text
    assert "origin/claude/changelog-to-attic" in text


def test_office_step_prints_the_line_even_with_nothing_found(repo, tmp_path):
    """Молчание читалось бы как «на ветках вопросов нет» — ровно та немота, что лечим."""
    _base_with(repo)

    text = _office_lines(_report(repo, tmp_path))

    assert "живущих только на ветке, нет" in text
    assert "веток прочитано" in text


def test_office_step_reads_an_old_report_as_unmeasured(repo, tmp_path):
    """Отчёт старого образца не имеет права выглядеть как «на ветках чисто»."""
    doc = _report(repo, tmp_path)
    doc.pop("branch_queue")

    text = _office_lines(doc)

    assert "вопросы на ВЕТКАХ НЕ ИЗМЕРЕНЫ" in text
    assert "отчёт старого образца" in text
