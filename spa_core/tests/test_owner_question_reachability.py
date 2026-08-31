# LLM_FORBIDDEN
"""spa_core/tests/test_owner_question_reachability.py — «виден» ≠ «дойдёт».

**Авария 30–31.08.2026 (цикл #437, карточка `inbox-vopros-vladeltsa-zhiv-na-origin-a-v-dere`).**
Сторож очереди владельца печатал «очередь полна: невидимых дереву вопросов нет» и
`origin_queue: {count: 0, hidden: []}`. Живой пример того же дня —
`own-dashboard-razdaval-repozitorii-v-set`:

* на `origin/main` (коммит `5fd2db03a`, 30.08 22:06Z) карточка в `needs-owner` и несёт
  **новый** вопрос владельцу — что должен показывать агентский сервер;
* в прод-дереве лежала **версия от 21:51Z** — старый вопрос, в терминальном статусе.

Сторож посчитал вопрос ВИДИМЫМ, потому что файл с таким именем в дереве есть. Но
содержимое разное, статус разный, а кнопка владельца пишет ответ именно в прод-копию —
то есть ответ на новый вопрос лёг бы под текстом старого.

Это ровно тот класс, что ведётся в `STATE.md` отдельным разделом: сторож честно
отвечает на СВОЙ вопрос («есть ли файл с таким именем?») и читается как ответ на нужный
(«дойдёт ли живой вопрос до владельца и туда ли попадёт его ответ?»).

Фикстуры — настоящие крошечные git-репозитории, без сети. Дат в них нет вовсе: вердикт
достижимости от календаря не зависит ни одной веткой.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spa_core.monitoring.owner_decision_pending import check_pending_owner_decisions
from spa_core.owner_queue import origin_view
from spa_core.owner_queue.origin_view import (
    REACH_ABSENT,
    REACH_DIFFERS,
    REACH_STALE_ANSWER,
    Unmeasured,
    hidden_cards,
    unreachable_cards,
)

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(title="вопрос владельцу", status="needs-owner", ctype="owner-decision",
          body="тело вопроса", extra=""):
    return (f"---\ntrackerStatus:\n  type: {ctype}\ntitle: \"{title}\"\n"
            f"status: {status}\n{extra}---\n\n{body}\n")


@pytest.fixture()
def repo(tmp_path):
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


def _kinds(cards):
    return {(c.card_id, c.kind) for c in cards}


# ===========================================================================
# Положительный контроль: форма 30–31.08
# ===========================================================================
class TestTheLiveQuestionMustActuallyReachTheOwner:

    def test_a_terminal_tree_copy_of_a_live_question_is_a_finding(self, repo):
        """Ядро аварии: на ref живой вопрос, в дереве — терминальная СТАРАЯ копия.

        Прежний сторож звал это «видимым»: файл с таким именем есть.
        """
        _write(repo, "own-dashboard", _card(title="Что должен показывать сервер",
                                            body="НОВЫЙ вопрос владельцу"))
        _commit(repo)
        _write(repo, "own-dashboard", _card(title="Прежний вопрос", status="ingested",
                                            body="СТАРЫЙ, уже закрытый вопрос"))

        cards, sha = unreachable_cards(_tracker(repo), ref=REF,
                                       tracker_type="owner-decision",
                                       status="needs-owner")

        assert _kinds(cards) == {("own-dashboard", REACH_DIFFERS)}
        assert cards[0].tree_status == "ingested"
        assert cards[0].origin_status == "needs-owner"
        assert "не тот текст" in cards[0].detail
        assert len(sha) == 40, "sha локальной копии ref обязан быть назван"

    def test_the_old_guard_calls_the_same_state_visible(self, repo):
        """Тот же вход — и прежний вопрос «есть ли файл» даёт ПУСТО.

        Этот тест и есть доказательство, что находка новая, а не переименованная:
        два сторожа на одном состоянии расходятся.
        """
        _write(repo, "own-dashboard", _card(body="НОВЫЙ вопрос"))
        _commit(repo)
        _write(repo, "own-dashboard", _card(status="ingested", body="СТАРЫЙ вопрос"))

        assert hidden_cards(_tracker(repo), ref=REF)[0] == []
        assert unreachable_cards(_tracker(repo), ref=REF)[0] != []

    def test_a_differing_body_alone_is_enough(self, repo):
        """Статус может совпадать: владелец всё равно читает НЕ ТОТ текст."""
        _write(repo, "own-q", _card(body="новая редакция вопроса"))
        _commit(repo)
        _write(repo, "own-q", _card(body="прежняя редакция вопроса"))

        cards, _ = unreachable_cards(_tracker(repo), ref=REF)
        assert _kinds(cards) == {("own-q", REACH_DIFFERS)}

    def test_an_absent_file_is_still_found(self, repo):
        """Прежний исход (`own-34`, 17.08) не потерян — он стал ОДНИМ из трёх."""
        _write(repo, "own-34", _card(title="Стоп-кран включён"))
        _commit(repo)
        (_tracker(repo) / "own-34.md").unlink()

        cards, _ = unreachable_cards(_tracker(repo), ref=REF)
        assert _kinds(cards) == {("own-34", REACH_ABSENT)}
        assert "невидим вовсе" in cards[0].detail


class TestIdenticalCopiesAreNeverANoise:
    """Обратный контроль: иначе сторож зальёт очередь шумом, и его перестанут читать."""

    def test_byte_identical_copy_is_not_a_finding(self, repo):
        _write(repo, "own-q", _card())
        _commit(repo)

        assert unreachable_cards(_tracker(repo), ref=REF)[0] == []

    def test_filters_are_applied_to_the_ref_version(self, repo):
        """Вопрос закрыт НА REF ⇒ он не живой, и расхождение дерева тут ни при чём."""
        _write(repo, "own-q", _card(status="ingested"))
        _commit(repo)
        _write(repo, "own-q", _card(status="ingested", body="иначе"))

        cards, _ = unreachable_cards(_tracker(repo), ref=REF,
                                     tracker_type="owner-decision",
                                     status="needs-owner")
        assert cards == []

    def test_another_tracker_type_is_not_an_owner_question(self, repo):
        _write(repo, "inbox-x", _card(ctype="inbox", status="new"))
        _commit(repo)
        (_tracker(repo) / "inbox-x.md").unlink()

        cards, _ = unreachable_cards(_tracker(repo), ref=REF,
                                     tracker_type="owner-decision",
                                     status="needs-owner")
        assert cards == []

    def test_an_empty_queue_on_the_ref_is_not_a_finding(self, repo):
        _write(repo, "_BOARD", "доска, не карточка\n")
        _commit(repo)
        assert unreachable_cards(_tracker(repo), ref=REF)[0] == []


class TestAnAnswerThatOutlivedItsQuestionIsNamed:
    """Пункт 3 карточки: решено НЕ молча.

    Механизма увода такого поля в регистр вытеснения ЗДЕСЬ НЕТ, и это решение, а не
    забывчивость: замер `origin/main` 63a2f501a дал живых вопросов **7**, несущих
    непустой `owner_choice` — **0**. Строить перенос на популяции из нуля значило бы
    угадывать форму, которой в природе нет (тот же fail-CLOSED, что в ADR-188).
    Сторож эту форму НАЗЫВАЕТ — молчать о ней он больше не может.
    """

    def test_a_live_question_carrying_an_answer_is_named(self, repo):
        _write(repo, "own-q", _card(extra='owner_choice: 1\n'))
        _commit(repo)

        cards, _ = unreachable_cards(_tracker(repo), ref=REF)
        assert (("own-q", REACH_STALE_ANSWER)) in _kinds(cards)
        named = next(c for c in cards if c.kind == REACH_STALE_ANSWER)
        assert "пережило вопрос" in named.detail

    def test_an_empty_scalar_is_not_an_answer(self, repo):
        """Обратный контроль по ТОЙ ЖЕ оси: `owner_choice: ""` — «ещё не отвечал»."""
        _write(repo, "own-q", _card(extra='owner_choice: ""\n'))
        _commit(repo)

        cards, _ = unreachable_cards(_tracker(repo), ref=REF)
        assert REACH_STALE_ANSWER not in {c.kind for c in cards}

    def test_the_two_outcomes_do_not_swallow_each_other(self, repo):
        """Карточка может нести ОБА исхода — и оба обязаны быть названы.

        Слепить их значило бы потерять один: чинятся они разными действиями.
        """
        _write(repo, "own-q", _card(extra='owner_choice: 1\n', body="новый вопрос"))
        _commit(repo)
        _write(repo, "own-q", _card(extra='owner_choice: 1\n', body="старый вопрос"))

        cards, _ = unreachable_cards(_tracker(repo), ref=REF)
        assert {c.kind for c in cards} == {REACH_STALE_ANSWER, REACH_DIFFERS}


class TestUnmeasuredIsNotClean:
    """Третий исход обязателен: «не измерено» ≠ «невидимых нет» (fail-CLOSED)."""

    def test_an_unresolvable_ref_raises_rather_than_returning_empty(self, repo):
        _write(repo, "own-q", _card())
        _commit(repo)
        with pytest.raises(Unmeasured):
            unreachable_cards(_tracker(repo), ref="origin/never-fetched")

    def test_a_tree_outside_a_repo_raises(self, tmp_path):
        with pytest.raises(Unmeasured):
            unreachable_cards(tmp_path / "nowhere")


class TestTheGuardAndTheOfficeStepSayIt:
    """Находка обязана доехать до ЧИТАТЕЛЯ, а не остаться в структуре отчёта."""

    def _tree(self, repo, monkeypatch):
        data = repo / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "telegram_owner_decisions.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(
            "spa_core.monitoring.owner_decision_pending.ORIGIN_REF", REF)
        return data

    def test_the_report_names_the_outcome_not_just_a_count(self, repo, monkeypatch):
        data = self._tree(repo, monkeypatch)
        _write(repo, "own-dashboard", _card(body="НОВЫЙ вопрос"))
        _commit(repo)
        _write(repo, "own-dashboard", _card(status="ingested", body="СТАРЫЙ вопрос"))

        doc = check_pending_owner_decisions(data_dir=data, tracker_dir=_tracker(repo))
        gap = doc["origin_queue"]

        assert gap["measured"] is True
        assert gap["count"] == 1
        assert gap["hidden"][0]["kind"] == REACH_DIFFERS
        assert gap["hidden"][0]["tree_status"] == "ingested"
        assert any("в дереве ДРУГОЙ текст" in i for i in doc["issues"]), doc["issues"]

    def test_the_office_step_prints_the_outcome_per_card(self, repo, monkeypatch):
        import sys
        data = self._tree(repo, monkeypatch)
        _write(repo, "own-dashboard", _card(body="НОВЫЙ вопрос"))
        _commit(repo)
        _write(repo, "own-dashboard", _card(status="ingested", body="СТАРЫЙ вопрос"))
        doc = check_pending_owner_decisions(data_dir=data, tracker_dir=_tracker(repo))

        scripts = str(Path(__file__).resolve().parents[2] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import consume_office_reports as office

        text = "\n".join(office._summarize_json("owner_decision_pending.json", doc))  # noqa: SLF001
        assert "очередь дерева НЕПОЛНА" in text
        assert "own-dashboard" in text
        assert "в дереве ДРУГОЙ текст" in text

    def test_a_reachable_queue_is_not_claimed_complete_by_filename(self, repo, monkeypatch):
        """Обратный контроль читателя: совпавшее дерево — по-прежнему тишина."""
        import sys
        data = self._tree(repo, monkeypatch)
        _write(repo, "own-q", _card())
        _commit(repo)
        doc = check_pending_owner_decisions(data_dir=data, tracker_dir=_tracker(repo))

        scripts = str(Path(__file__).resolve().parents[2] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import consume_office_reports as office

        text = "\n".join(office._summarize_json("owner_decision_pending.json", doc))  # noqa: SLF001
        assert "очередь полна" in text
        assert "НЕПОЛНА" not in text
