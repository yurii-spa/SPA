"""Очередь владельца в версии `origin/main` — `spa_core/owner_queue/origin_view.py`.

КАЖДЫЙ тест — положительный контроль реальной аварии **17.08.2026** (цикл #270):

    прод-дерево держало 416 карточек, `origin/main` — 481;
    109 карточек прод-дереву не были видны ВООБЩЕ,
    и среди них — живой вопрос владельцу `own-34` в статусе `needs-owner`.

Сторож `owner_decision_pending`, читающий очередь с диска, доложил при этом
`undelivered_count: 0`: вопрос был невидим в обе стороны — файла нет, в журнале
отправок тоже нет, потому что его ни разу не отправляли.

Все фикстуры — настоящие крошечные git-репозитории (без сети): проверяется ЭФФЕКТ
на git, а не подменённая заглушка. Дат в фикстурах нет вовсе — вердикт этого модуля
от календаря не зависит ни одной веткой.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.owner_queue.origin_view import (
    OriginCard,
    Unmeasured,
    hidden_cards,
    read_cards,
    repo_root_of,
    snapshot,
)

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(title="карточка", status="needs-owner", ctype="owner-decision", body="тело"):
    return (f"---\ntrackerStatus:\n  type: {ctype}\ntitle: \"{title}\"\n"
            f"status: {status}\n---\n\n{body}\n")


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с каталогом очереди и веткой-«origin». Сети не касается."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
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
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


# ===========================================================================
# Ядро аварии: карточка есть на ref, файла в дереве нет
# ===========================================================================
def test_a_question_only_on_the_ref_is_found_not_silently_absent(repo):
    _write(repo, "own-34", _card(title="Стоп-кран включён"))
    _commit(repo)
    (_tracker(repo) / "own-34.md").unlink()          # дерево «отстало», как прод 17.08

    cards, sha = hidden_cards(_tracker(repo), ref=REF)

    assert [c.card_id for c in cards] == ["own-34"]
    assert cards[0].status == "needs-owner"
    assert cards[0].tracker_type == "owner-decision"
    assert cards[0].title == "Стоп-кран включён"
    assert len(sha) == 40, "sha локальной копии ref обязан быть назван"


def test_a_card_present_in_the_tree_is_not_reported_hidden(repo):
    """Обратный контроль: синхронное дерево не должно рождать находок."""
    _write(repo, "own-34", _card())
    _commit(repo)

    cards, _ = hidden_cards(_tracker(repo), ref=REF)

    assert cards == []


def test_filters_judge_the_version_on_the_ref(repo):
    """У невидимой дереву карточки другой версии не существует по определению."""
    _write(repo, "own-answered", _card(status="owner-done"))
    _write(repo, "own-open", _card(status="needs-owner"))
    _write(repo, "inbox-task", _card(status="needs-owner", ctype="inbox"))
    _commit(repo)
    for name in ("own-answered", "own-open", "inbox-task"):
        (_tracker(repo) / f"{name}.md").unlink()

    cards, _ = hidden_cards(_tracker(repo), ref=REF,
                            tracker_type="owner-decision", status="needs-owner")

    assert [c.card_id for c in cards] == ["own-open"], (
        "закрытая карточка и не-вопрос не должны попадать в вопросы владельца")


def test_a_card_whose_type_comes_from_its_filename_is_still_resolved(repo):
    """Разбор — общий (`resolve_tracker_type`), а не своя копия правила (#143–#145)."""
    _write(repo, "owner-decision-bez-tipa",
           "---\ntitle: \"без объявленного типа\"\nstatus: needs-owner\n---\n\nтело\n")
    _commit(repo)
    (_tracker(repo) / "owner-decision-bez-tipa.md").unlink()

    cards, _ = hidden_cards(_tracker(repo), ref=REF,
                            tracker_type="owner-decision", status="needs-owner")

    assert [c.card_id for c in cards] == ["owner-decision-bez-tipa"]


# ===========================================================================
# Fail-CLOSED: «не измерено» никогда не притворяется «расхождений нет»
# ===========================================================================
def test_a_missing_ref_is_unmeasured_not_an_empty_answer(repo):
    _write(repo, "own-34", _card())
    _commit(repo)

    with pytest.raises(Unmeasured) as exc:
        hidden_cards(_tracker(repo), ref="origin/never-fetched")

    assert "не разрешается" in str(exc.value)


def test_a_missing_tracker_dir_is_unmeasured_not_an_empty_answer(repo):
    _write(repo, "own-34", _card())
    _commit(repo)
    for p in _tracker(repo).glob("*.md"):
        p.unlink()
    _tracker(repo).rmdir()

    with pytest.raises(Unmeasured):
        hidden_cards(_tracker(repo), ref=REF)


def test_a_path_outside_a_repository_is_unmeasured(tmp_path):
    lone = tmp_path / "nimbalyst-local" / "tracker"
    lone.mkdir(parents=True)

    with pytest.raises(Unmeasured):
        hidden_cards(lone, ref=REF)


def test_repo_root_of_refuses_a_non_repository(tmp_path):
    with pytest.raises(Unmeasured):
        repo_root_of(tmp_path)


# ===========================================================================
# Плумбинг: пакетное чтение обязано попадать в границы каждой карточки
# ===========================================================================
def test_the_batch_reader_keeps_multibyte_cards_apart(repo):
    """Границы blob'ов считаются в БАЙТАХ.

    Положительный контроль поверх кириллицы: считай мы длину в символах, вторая
    карточка съехала бы внутрь первой и разбор либо упал, либо выдал чужой статус.
    """
    _write(repo, "own-a", _card(title="Первая карточка с кириллицей", status="needs-owner"))
    _write(repo, "own-b", _card(title="Вторая — тоже кириллица, длиннее",
                                status="owner-done", body="ещё немного текста"))
    _write(repo, "own-c", _card(title="Третья", status="ingested"))
    _commit(repo)
    for name in ("own-a", "own-b", "own-c"):
        (_tracker(repo) / f"{name}.md").unlink()

    cards, _ = hidden_cards(_tracker(repo), ref=REF)

    assert [(c.card_id, c.status) for c in cards] == [
        ("own-a", "needs-owner"), ("own-b", "owner-done"), ("own-c", "ingested")]


def test_an_empty_batch_starts_no_process(repo, monkeypatch):
    def _boom(*a, **kw):  # pragma: no cover — сработавший вызов и есть провал теста
        raise AssertionError("пустой пакет не должен запускать git")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert read_cards(repo, {}) == []


def test_the_board_index_is_not_a_card(repo):
    _write(repo, "_BOARD", "# доска\n")
    _write(repo, "own-34", _card())
    _commit(repo)
    (_tracker(repo) / "_BOARD.md").unlink()
    (_tracker(repo) / "own-34.md").unlink()

    cards, _ = hidden_cards(_tracker(repo), ref=REF)

    assert [c.card_id for c in cards] == ["own-34"], (
        "производный индекс расходится всегда и карточкой не является")


def test_snapshot_returns_blob_shas_for_the_ref(repo):
    _write(repo, "own-34", _card())
    _commit(repo)
    root = repo_root_of(_tracker(repo))

    snap = snapshot(root, REF, origin_view.TRACKER_REL)

    assert set(snap) == {"own-34"}
    expected = _run(repo, "rev-parse", f"{REF}:{origin_view.TRACKER_REL}/own-34.md").strip()
    assert snap["own-34"] == expected


# ===========================================================================
# Сторож не ходит в сеть — иначе «сверено с origin» стало бы ещё и медленным
# ===========================================================================
def test_the_view_never_touches_the_network(repo, monkeypatch):
    """Тот же страж, что у `check_tracker_drift`, — но за СВОИМИ вызовами git.

    Плумбинг у двух модулей свой (это осознанный выбор, см. шапку `origin_view`),
    поэтому и страж обязан быть свой: иначе часть вызовов git оказалась бы вне
    надзора и проверка ослабла бы молча.
    """
    _write(repo, "own-34", _card())
    _commit(repo)
    (_tracker(repo) / "own-34.md").unlink()

    forbidden = {"fetch", "pull", "clone", "ls-remote", "remote", "push"}
    seen: list[list[str]] = []
    real = subprocess.run

    def _spy(argv, *a, **kw):
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "git":
            seen.append(list(argv))
            assert not (set(argv) & forbidden), f"сеть: {argv}"
        return real(argv, *a, **kw)

    monkeypatch.setattr(subprocess, "run", _spy)
    cards, _ = hidden_cards(_tracker(repo), ref=REF)

    assert [c.card_id for c in cards] == ["own-34"]
    assert seen, "тест обязан был увидеть хотя бы один вызов git — иначе он ничего не сторожит"


def test_an_origin_card_is_a_plain_value(repo):
    """Возврат — данные, а не объект с диском внутри: читателю негде ошибиться деревом."""
    card = OriginCard(card_id="own-34", tracker_type="owner-decision",
                      status="needs-owner", title="x")
    assert (card.card_id, card.status) == ("own-34", "needs-owner")
    with pytest.raises(Exception):
        card.status = "owner-done"  # type: ignore[misc]
