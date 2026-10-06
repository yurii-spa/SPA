"""`owner_queue.first_delivery.carry_to_origin` — обратное направление (C5, ADR-580).

Замер A5_owner_control.md: Telegram-интейк и писатель ответа владельца пишут в
ПРОД-дерево, а `first_delivery.py` до этой правки умел только origin -> прод. Карточка
`owner-decision-utochnenie-po-zametke-prikaz-vladeltsa-u` существовала только в проде;
17 закрытий владельца (`owner-done`/`owner-accepted`) видны только в проде, origin
показывает `ingested`.

Фикстуры — настоящие крошечные git-репозитории (как в `test_origin_view.py`): "origin"
— закоммиченное состояние, "прод" — живая рабочая копия того же дерева, которую правка
теста меняет БЕЗ коммита (то есть прод расходится с закоммиченным `ref`, как в жизни
прод расходится с origin). Каждый тест — положительный контроль одного звена решётки.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spa_core.owner_queue.first_delivery import (
    RANK_INGESTED,
    RANK_NEEDS_OWNER,
    RANK_OWNER_ANSWERED,
    RANK_OWNER_CLOSED,
    carry_to_origin,
    carrier_summary_line,
    lattice_rank,
)

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    # Пустой якорный коммит: ветка `main` обязана существовать С САМОГО НАЧАЛА, иначе
    # тест на «карточки нет на origin вовсе» неотличим от «ветки нет вовсе».
    _run(root, "commit", "--allow-empty", "-q", "-m", "init")
    return root


def _tracker(root: Path) -> Path:
    return root / "nimbalyst-local" / "tracker"


def _card(title="вопрос", status="needs-owner", ctype="owner-decision",
         extra: str = "", body="тело") -> str:
    return (f"---\ntrackerStatus:\n  type: {ctype}\ntitle: \"{title}\"\n"
            f"status: {status}\n{extra}---\n\n{body}\n")


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


# ── lattice_rank ──────────────────────────────────────────────────────────────────
class TestLatticeRank:

    def test_needs_owner_plain_is_the_bottom(self):
        assert lattice_rank(_card(status="needs-owner")) == RANK_NEEDS_OWNER

    def test_needs_owner_with_an_answer_field_outranks_plain_needs_owner(self):
        text = _card(status="needs-owner", extra='owner_choice: "вариант 1"\n')
        assert lattice_rank(text) == RANK_OWNER_ANSWERED
        assert RANK_OWNER_ANSWERED > RANK_NEEDS_OWNER

    def test_ingested_outranks_owner_answered(self):
        assert lattice_rank(_card(status="ingested")) == RANK_INGESTED
        assert RANK_INGESTED > RANK_OWNER_ANSWERED

    def test_owner_done_and_owner_accepted_are_the_top(self):
        assert lattice_rank(_card(status="owner-done")) == RANK_OWNER_CLOSED
        assert lattice_rank(_card(status="owner-accepted")) == RANK_OWNER_CLOSED

    def test_a_status_outside_the_lattice_is_unordered_not_guessed(self):
        assert lattice_rank(_card(status="blocked")) is None
        assert lattice_rank(_card(status="in-progress")) is None

    def test_an_unparsable_card_is_unordered(self):
        assert lattice_rank("не карточка вовсе") is None


# ── carry_to_origin: add ─────────────────────────────────────────────────────────
def test_a_card_absent_on_origin_is_an_add(repo):
    # Якорный коммит фикстуры уже поставил `main` без карточек — origin пуст.
    _write(repo, "own-prod-only", _card(title="Только в проде"))

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.measured
    assert [i.card_id for i in plan.items] == ["own-prod-only"]
    assert plan.items[0].action == "add"
    assert "Только в проде" in plan.items[0].new_content
    assert not plan.conflicts


# ── carry_to_origin: update (прод продвинулся) ───────────────────────────────────
def test_a_prod_status_advance_is_an_update(repo):
    _write(repo, "owner-decision-x", _card(status="needs-owner"))
    _commit(repo)
    # Прод отвечен (владелец нажал кнопку в Telegram) — origin ещё не знает.
    _write(repo, "owner-decision-x",
           _card(status="owner-done", extra='owner_choice: "да"\nclosed_by: "owner"\n'))

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.measured
    assert [i.card_id for i in plan.items] == ["owner-decision-x"]
    item = plan.items[0]
    assert item.action == "update"
    assert item.prod_rank == RANK_OWNER_CLOSED
    assert item.origin_rank == RANK_NEEDS_OWNER
    assert "owner-done" in item.new_content
    assert not plan.conflicts


def test_owner_answered_but_not_yet_ingested_is_still_an_update(repo):
    """Ответ в карточке есть (`owner_choice`), статус ещё `needs-owner` — след не
    успел доехать до смены статуса. Это промежуточный ранг, не «ничего не изменилось»."""
    _write(repo, "own-answered", _card(status="needs-owner"))
    _commit(repo)
    _write(repo, "own-answered",
           _card(status="needs-owner", extra='owner_choice: "вариант 2"\n'))

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert [i.card_id for i in plan.items] == ["own-answered"]
    assert plan.items[0].prod_rank == RANK_OWNER_ANSWERED


# ── carry_to_origin: НИКОГДА не переносит назад ──────────────────────────────────
def test_prod_behind_origin_is_neither_carried_nor_flagged_as_conflict(repo):
    """Origin уже дальше (`ingested`), а прод всё ещё `needs-owner` (например, прод
    не видел собственную доставленную правку). Перенос НАЗАД запрещён (C5) — и это
    НЕ конфликт: порядок измерен, он просто не в сторону прода."""
    _write(repo, "owner-decision-y", _card(status="ingested"))
    _commit(repo)
    _write(repo, "owner-decision-y", _card(status="needs-owner"))

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.items == []
    assert plan.conflicts == []


# ── carry_to_origin: конфликты — НЕ угадывает ────────────────────────────────────
def test_same_rank_different_content_is_a_conflict(repo):
    _write(repo, "owner-decision-z", _card(status="owner-done", title="A"))
    _commit(repo)
    _write(repo, "owner-decision-z", _card(status="owner-accepted", title="A"))

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.items == []
    assert [c.card_id for c in plan.conflicts] == ["owner-decision-z"]
    assert "НЕ ИЗМЕРЕНО" in plan.conflicts[0].reason


def test_a_status_outside_the_lattice_is_a_conflict_not_a_guess(repo):
    _write(repo, "owner-decision-w", _card(status="needs-owner"))
    _commit(repo)
    _write(repo, "owner-decision-w", _card(status="blocked"))

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.items == []
    assert [c.card_id for c in plan.conflicts] == ["owner-decision-w"]
    assert "вне решётки" in plan.conflicts[0].reason


def test_identical_content_is_unchanged_not_a_conflict(repo):
    _write(repo, "owner-decision-same", _card(status="needs-owner"))
    _commit(repo)

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.items == []
    assert plan.conflicts == []
    assert plan.unchanged == ["owner-decision-same"]


# ── fail-CLOSED: «не измерено» ≠ «переносить нечего» ─────────────────────────────
def test_a_missing_tracker_dir_is_unmeasured_not_empty(tmp_path):
    plan = carry_to_origin(tmp_path / "no-such-dir", ref=REF)
    assert plan.measured is False
    assert plan.items == []
    assert "не измерено" in carrier_summary_line(plan) or plan.reason


def test_an_unresolvable_ref_is_unmeasured(repo):
    _write(repo, "own-a", _card())
    _commit(repo)

    plan = carry_to_origin(_tracker(repo), ref="origin/does-not-exist")

    assert plan.measured is False
    assert plan.reason


# ── никогда не пишет ни в прод, ни в origin ──────────────────────────────────────
def test_the_carrier_never_writes_the_prod_tree_or_origin(repo):
    _write(repo, "own-only-prod", _card(title="Карточка"))
    before_status = _run(repo, "status", "--porcelain")
    before_log = _run(repo, "log", "--oneline", REF)

    carry_to_origin(_tracker(repo), ref=REF)

    after_status = _run(repo, "status", "--porcelain")
    after_log = _run(repo, "log", "--oneline", REF)
    assert after_status == before_status, "carry_to_origin не имеет права трогать рабочее дерево"
    assert after_log == before_log, "carry_to_origin не имеет права коммитить/пушить"


# ── только что ПЛАН: карточки без owner-decision/own- не трогает ────────────────
def test_non_owner_queue_cards_are_ignored(repo):
    _write(repo, "inbox-chinit-storozh",
           "---\ntrackerStatus:\n  type: inbox\nstatus: new\n---\n\nтело\n")
    _commit(repo)

    plan = carry_to_origin(_tracker(repo), ref=REF)

    assert plan.scanned == 0
    assert plan.items == []
