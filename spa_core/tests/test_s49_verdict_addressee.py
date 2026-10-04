"""Адресат вердикта §49 — `spa_core/monitoring/s49_verdict_addressee.py` (заказ G95 п. 3).

КАЖДЫЙ тест — положительный контроль измеренной дыры **2026-10-04**: сводка §49
печатала `НЕ ВЫПОЛНЕНО 9` и ни у одной из девяти строк не говорила, КТО вправе
это починить. Для `Economics` вопрос владельцу стоял в очереди с 27.09
(`own-optimum-proigryvaet-resheniyu-nichego-ne-d`, `needs-owner`), а читатель
сводки видел тот же значок отказа, что у недоделки агента.

Сцена каждого теста — настоящий крошечный git-репозиторий с настоящей очередью:
проверяется ЭФФЕКТ на git и на каноническом разборе карточки, а не подменённая
заглушка. Ветка создаётся `git init -b`, то есть ИМЯ ВХОДИТ ВО ВХОД сцены
(`.claude/rules/deployment.md`, «GIT-ОКРУЖЕНИЕ в тестах»): без этого вердикт
зависел бы от `init.defaultBranch` хоста. Литеральных дат в файле нет вовсе —
от календаря этот модуль не зависит ни одной веткой.

Сцена ОБЪЯВЛЯЕТ, что даёт именно ту породу, которую обещает: каждый тест,
утверждающий «красно на порванном звене», сначала доказывает, что на ЦЕЛОМ
контуре зелено (`.claude/rules/acceptance.md`, п. 3 — иначе «красно» тавтологично).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spa_core.monitoring import s49_verdict_addressee as mod
from spa_core.owner_queue import origin_view

#: Имя ветки-очереди. ВХОД сцены, а не умолчание хоста.
REF = "queue-main"

#: Население §49 в тестах — короткое и с ИМЕНЕМ ИЗ ДВУХ СЛОВ среди них: имя с
#: пробелом есть в настоящем §49 («Marginal return», «Pre-trade safety»), и
#: разделитель перечня обязан его не разрезать.
POPULATION = ["Economics", "Marginal return", "Risk"]


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(*, status="needs-owner", ctype="owner-decision", declares=None,
          title="вопрос владельцу", block_form=False):
    """Текст карточки. `declares=None` — поля нет вовсе (штатное молчание)."""
    lines = ["---", "trackerStatus:", f"  type: {ctype}", f'title: "{title}"',
             f"status: {status}"]
    if block_form:
        lines.append(f"{mod.FIELD}:")
        for name in (declares or []):
            lines.append(f"  - {name}")
    elif declares is not None:
        lines.append(f"{mod.FIELD}: {', '.join(declares)}")
    lines += ["---", "", "## Что случилось и почему это важно", "", "тело", ""]
    return "\n".join(lines)


@pytest.fixture()
def scene(tmp_path):
    """Репозиторий с очередью. Возвращает помощника сцены; сети не касается."""
    root = tmp_path / "repo"
    tracker = root / origin_view.TRACKER_REL
    tracker.mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")

    class Scene:
        def __init__(self):
            self.root = root
            self.tracker = tracker

        def write(self, card_id: str, text: str) -> Path:
            path = tracker / f"{card_id}.md"
            path.write_text(text, encoding="utf-8")
            return path

        def commit(self, message="scene"):
            _run(root, "add", "-A")
            _run(root, "commit", "-q", "-m", message)

        def measure(self, population=None, ref=REF):
            return mod.measure(population or POPULATION,
                               tracker_dir=self.tracker, ref=ref)

    sc = Scene()
    # Предпосылка сцены ДОКАЗЫВАЕТСЯ, а не предполагается: очередь обязана быть
    # непустой на ref, иначе прибор честно откажет «пустая очередь зелена сама
    # собой» и любой вердикт ниже оказался бы про отказ, а не про адресата.
    sc.write("own-scene-anchor", _card(title="якорь сцены"))
    sc.commit("якорь сцены")
    assert sc.measure()["cards_declaring_on_ref"] == 0, (
        "якорь сцены не должен объявлять поле — иначе положительные тесты ниже "
        "мерили бы его, а не свою карточку")
    return sc


def _row(report, criterion):
    (row,) = [r for r in report["rows"] if r["criterion"] == criterion]
    return row


class TestWholeContour:
    """Целый контур: объявление на ref у открытой владельческой карточки."""

    def test_open_owner_card_on_ref_names_the_addressee(self, scene):
        scene.write("own-economics", _card(declares=["Economics"],
                                           title="оптимум проигрывает «держим»"))
        scene.commit()
        row = _row(scene.measure(), "Economics")
        assert row["kind"] == mod.OWNER_OPEN
        # Назван ИМЕНЕМ: «адресат есть» без имени нечем проверить.
        assert [c["card"] for c in row["cards"]] == ["own-economics"]
        assert row["cards"][0]["status"] == "needs-owner"
        assert row["cards"][0]["title"] == "оптимум проигрывает «держим»"

    def test_a_criterion_nobody_declares_is_NONE_and_counted(self, scene):
        scene.write("own-economics", _card(declares=["Economics"]))
        scene.commit()
        report = scene.measure()
        assert _row(report, "Risk")["kind"] == mod.NONE
        # Отсутствие адресата обязано быть ЧИСЛОМ: отсутствующий столбец читается
        # как «адресат есть у всех», и ровно это заказ и называет дырой.
        assert report["counts"] == {mod.OWNER_OPEN: 1, mod.OWNER_CLOSED: 0,
                                    mod.TREE_ONLY: 0, mod.OUTSIDE_QUEUE: 0,
                                    mod.NONE: 2}

    def test_one_card_may_address_several_criteria(self, scene):
        scene.write("own-both", _card(declares=["Economics", "Marginal return"]))
        scene.commit()
        report = scene.measure()
        assert _row(report, "Economics")["kind"] == mod.OWNER_OPEN
        # Имя из двух слов разделитель не разрезал — иначе «Marginal return»
        # распался бы и критерий остался бы без адресата молча.
        assert _row(report, "Marginal return")["kind"] == mod.OWNER_OPEN
        assert _row(report, "Risk")["kind"] == mod.NONE


class TestEachBrokenLinkIsRed:
    """На каждом порванном звене — СВОЙ исход, и звено названо."""

    def test_closed_card_is_not_an_addressee_and_is_not_silence(self, scene):
        scene.write("own-economics", _card(declares=["Economics"], status="ingested"))
        scene.commit()
        row = _row(scene.measure(), "Economics")
        # Главное здесь — что это НЕ `NONE`: «вопрос отвечен, а вердикт всё ещё
        # отказ» чинится иначе, чем «вопрос не задан».
        assert row["kind"] == mod.OWNER_CLOSED
        assert row["kind"] != mod.NONE
        assert [c["card"] for c in row["cards"]] == ["own-economics"]
        assert row["cards"][0]["open"] is False

    def test_owner_accepted_is_still_open(self, scene):
        """`owner-accepted` — НЕтерминальный: владелец ответил, работа впереди."""
        scene.write("own-economics", _card(declares=["Economics"],
                                           status="owner-accepted"))
        scene.commit()
        assert _row(scene.measure(), "Economics")["kind"] == mod.OWNER_OPEN

    def test_declaration_only_in_the_working_tree_is_not_delivered(self, scene):
        scene.write("own-economics", _card(declares=["Economics"]))  # НЕ коммитим
        report = scene.measure()
        row = _row(report, "Economics")
        assert row["kind"] == mod.TREE_ONLY
        assert report["cards_declaring_on_ref"] == 0
        assert report["cards_declaring_in_tree"] == 1
        # Доставленное и недоставленное обязаны быть различимы: иначе объявление,
        # лежащее в worktree, читалось бы как названный владельцу адресат.
        assert row["kind"] != mod.OWNER_OPEN

    def test_an_undelivered_draft_does_not_vanish_behind_a_named_addressee(self, scene):
        scene.write("own-economics", _card(declares=["Economics"]))
        scene.commit()
        scene.write("own-economics-draft", _card(declares=["Economics"]))  # в дереве
        row = _row(scene.measure(), "Economics")
        assert row["kind"] == mod.OWNER_OPEN
        # Находка о недоставленном черновике печатается РЯДОМ, а не исчезает от
        # того, что адресат уже назван другой карточкой.
        assert row["tree_only_extra"] == ["own-economics-draft"]

    def test_an_edited_but_already_pushed_card_is_not_called_undelivered(self, scene):
        scene.write("own-economics", _card(declares=["Economics"]))
        scene.commit()
        scene.write("own-economics", _card(declares=["Economics"],
                                           title="заголовок правлен в дереве"))
        row = _row(scene.measure(), "Economics")
        # Сравниваются ИМЕНА карточек, а не их число и не их текст: правка уже
        # лежащей на ref карточки недоставленным объявлением не является, и
        # называть её так значило бы жечь находку на штатном состоянии.
        assert row["tree_only_extra"] == []

    def test_a_non_owner_card_is_a_declaration_outside_the_owner_queue(self, scene):
        scene.write("inbox-economics", _card(declares=["Economics"], ctype="inbox",
                                             status="in-progress"))
        scene.commit()
        row = _row(scene.measure(), "Economics")
        assert row["kind"] == mod.OUTSIDE_QUEUE
        # «За кем решение» ответа тут нет: статус задачи агента на вопрос
        # «ждёт ли владелец» не отвечает вовсе.
        assert row["kind"] not in (mod.OWNER_OPEN, mod.OWNER_CLOSED)


class TestTheSilentlyDroppedForm:
    """Блочная форма объявления — тот же класс, против которого прибор написан."""

    def test_block_form_is_a_named_problem_not_silence(self, scene):
        scene.write("own-economics", _card(declares=["Economics"], block_form=True))
        scene.commit()
        report = scene.measure()
        # Канонический разбор frontmatter список отбрасывает. Если бы прибор
        # просто спросил поле, объявление исчезло бы БЕЗ ЕДИНОГО СЛОВА и критерий
        # прочитался бы как «адресата нет» — ровно подмена «не измерено» ответом.
        assert _row(report, "Economics")["kind"] == mod.NONE
        assert any("own-economics" in p and "БЛОЧНОЙ" in p
                   for p in report["problems"]), report["problems"]

    def test_the_canonical_parser_really_does_drop_the_block_form(self, scene):
        """Предпосылка предыдущего теста — ЗАМЕР, а не предание."""
        from spa_core.owner_queue.queue import load_card_text
        card = load_card_text(_card(declares=["Economics"], block_form=True), "own-x.md")
        assert mod.FIELD not in card.fields
        flat = load_card_text(_card(declares=["Economics"]), "own-x.md")
        assert flat.fields[mod.FIELD] == "Economics"

    def test_an_empty_flat_declaration_is_a_named_problem(self, scene):
        scene.write("own-economics", _card(declares=[]))
        scene.commit()
        report = scene.measure()
        assert any("own-economics" in p for p in report["problems"]), report["problems"]


class TestStatusVocabulary:
    def test_a_status_outside_the_vocabulary_is_not_read_as_closed(self, scene):
        scene.write("own-economics", _card(declares=["Economics"], status="closed"))
        scene.commit()
        row = _row(scene.measure(), "Economics")
        # «closed» — опечатка, делающая карточку невидимой любому фильтру.
        # Прочесть её как ЗАКРЫТУЮ значило бы молча снять вопрос владельца.
        assert row["unknown_status"], row
        assert row["unknown_status"][0]["open"] is None
        assert row["kind"] != mod.OWNER_OPEN

    def test_open_and_closed_are_read_from_ONE_declaration(self):
        """Словарность не переписана здесь копией: копий у неё быть не должно."""
        from spa_core.owner_queue.queue import CARD_STATUSES, _OPEN_STATUSES
        assert _OPEN_STATUSES <= CARD_STATUSES
        assert "needs-owner" in _OPEN_STATUSES and "ingested" not in _OPEN_STATUSES


class TestMatchIsByNameNotBySubstring:
    def test_a_prefix_of_a_criterion_name_does_not_match_it(self, scene):
        scene.write("own-almost", _card(declares=["Econom"]))
        scene.commit()
        report = scene.measure()
        # Совпадение подстрокой и было бы догадкой (ADR-333): «Econom» адресатом
        # «Economics» не является, и объявление обязано уехать в МИМО населения.
        assert _row(report, "Economics")["kind"] == mod.NONE
        assert report["orphan_declarations"] == {"Econom": ["own-almost"]}

    def test_a_criterion_absent_from_the_population_is_reported_as_orphan(self, scene):
        scene.write("own-ghost", _card(declares=["Forecast accuracy"]))
        scene.commit()
        report = scene.measure()
        assert report["orphan_declarations"] == {"Forecast accuracy": ["own-ghost"]}
        # Молчание о таком объявлении означало бы, что критерий считается
        # адресованным где-то не здесь.
        assert all(r["kind"] == mod.NONE for r in report["rows"])


class TestThirdOutcome:
    def test_an_empty_queue_on_ref_is_unmeasured_not_zero(self, tmp_path):
        root = tmp_path / "repo"
        tracker = root / origin_view.TRACKER_REL
        tracker.mkdir(parents=True)
        _run(root.parent, "init", "-q", "-b", REF, str(root))
        _run(root, "config", "user.email", "t@example.com")
        _run(root, "config", "user.name", "test")
        (root / "README.md").write_text("x\n", encoding="utf-8")
        _run(root, "add", "-A")
        _run(root, "commit", "-q", "-m", "без очереди")
        with pytest.raises(mod.Unmeasured) as exc:
            mod.measure(POPULATION, tracker_dir=tracker, ref=REF)
        # Пустое население зелено по построению — дословно урок ADR-553.
        assert "НИ ОДНОЙ карточки" in str(exc.value)

    def test_a_tree_that_is_not_a_repository_is_unmeasured(self, tmp_path):
        tracker = tmp_path / origin_view.TRACKER_REL
        tracker.mkdir(parents=True)
        with pytest.raises(mod.Unmeasured):
            mod.measure(POPULATION, tracker_dir=tracker, ref=REF)

    def test_an_unresolvable_ref_is_unmeasured(self, scene):
        with pytest.raises(mod.Unmeasured) as exc:
            scene.measure(ref="no-such-ref")
        assert "no-such-ref" in str(exc.value)

    def test_a_separator_inside_a_criterion_name_is_refused(self, scene):
        with pytest.raises(mod.Unmeasured) as exc:
            scene.measure(population=["Econom,ics"])
        assert mod.SEPARATOR in str(exc.value)

    def test_the_real_population_carries_no_separator(self):
        """Условие разделителя — ЗАМЕР настоящего §49, а не допущение."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import cio_acceptance_rollup as rollup
        card = (Path(__file__).resolve().parents[2] / rollup.CARD_REL)
        names = rollup.parse_s49_criteria(card.read_text(encoding="utf-8"))
        assert names, "население §49 не прочитано — условие не проверено"
        assert not [n for n in names if mod.SEPARATOR in n]


class TestTheQueueIsReadWithoutTheNetwork:
    def test_measure_never_fetches(self, scene, monkeypatch):
        """Ответ про ТУ копию ref, что уже лежит локально. `fetch` — не наш вызов."""
        seen: list[list[str]] = []
        real = subprocess.run

        def spy(args, *a, **kw):
            seen.append(list(args))
            return real(args, *a, **kw)

        monkeypatch.setattr(subprocess, "run", spy)
        scene.write("own-economics", _card(declares=["Economics"]))
        scene.commit()
        scene.measure()
        assert seen, "ни одного вызова git не состоялось — сцена не та"
        assert not [a for a in seen if "fetch" in a], seen
