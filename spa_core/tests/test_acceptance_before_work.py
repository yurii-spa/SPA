"""Положительные контроли правила приёмки (`.claude/rules/acceptance.md`, п. 1–2):
inbox-карточка уходит из приёма только с машинным критерием, и проба карточки в работе
не заменяется. Каждый тест — способ, которым очередь могла бы пропустить самосертификацию.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spa_core.owner_queue import queue as q

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLI = os.path.join(_REPO, "scripts", "orchestrator_queue.py")


def _card(tmp, name, *, kind="inbox", status="new", probe=None, finding_key=None):
    fm = ["trackerStatus:", f"  type: {kind}", f'title: "проверочная {name}"', f"status: {status}"]
    if probe:
        fm.append(f"acceptance_probe: {probe}")
    if finding_key:
        fm.append(f'finding_key: "{finding_key}"')
    path = os.path.join(tmp, f"{name}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n" + "\n".join(fm) + "\n---\n\n## тело\n")
    return path


class TakingIntoWork(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def test_inbox_without_criterion_is_refused(self):
        path = _card(self.tmp, "inbox-bez-kriteriya")
        with self.assertRaises(q.AcceptanceCriterionMissing) as cm:
            q.set_status(path, "in-progress")
        self.assertIn("orchestrator_queue.py probe", str(cm.exception))
        self.assertIn("status: new", open(path, encoding="utf-8").read())   # карточка не тронута

    def test_inbox_with_probe_goes_into_work(self):
        path = _card(self.tmp, "inbox-s-proboi", probe="tier_promotion_loop_closed")
        q.set_status(path, "in-progress")
        self.assertIn("status: in-progress", open(path, encoding="utf-8").read())

    def test_bridge_card_with_finding_key_goes_into_work(self):
        path = _card(self.tmp, "inbox-ot-mosta", finding_key="tier_promote:x")
        q.set_status(path, "in-progress")
        self.assertIn("status: in-progress", open(path, encoding="utf-8").read())

    def test_intake_moves_are_free(self):
        path = _card(self.tmp, "inbox-v-bekloge")
        q.set_status(path, "backlog")
        q.set_status(path, "new")

    def test_closing_without_criterion_is_refused_too(self):
        # `new -> done` в обход работы — та же самосертификация.
        path = _card(self.tmp, "inbox-srazu-done")
        with self.assertRaises(q.AcceptanceCriterionMissing):
            q.set_status(path, "done")

    def test_baseline_card_is_exempt(self):
        path = _card(self.tmp, "inbox-staraya")
        with mock.patch.object(q, "_inbox_acceptance_baseline", lambda: {"inbox-staraya.md"}):
            q.set_status(path, "in-progress")
        self.assertIn("status: in-progress", open(path, encoding="utf-8").read())

    def test_non_inbox_types_are_not_the_subject(self):
        path = _card(self.tmp, "agent-zadacha", kind="agent-task")
        q.set_status(path, "in-progress")

    def test_unreadable_baseline_is_loud_not_a_silent_refusal(self):
        path = _card(self.tmp, "inbox-baza-propala")
        import io
        err = io.StringIO()
        with mock.patch.object(q, "_inbox_acceptance_baseline", lambda: None), \
                mock.patch("sys.stderr", err):
            q.set_status(path, "in-progress")
        self.assertIn("НЕ ИЗМЕРЕНО", err.getvalue())

    def test_cli_refuses_with_exit_2(self):
        path = _card(self.tmp, "inbox-cli")
        r = subprocess.run([sys.executable, _CLI, "set-status", path, "in-progress"],
                           capture_output=True, text=True, timeout=120, cwd=_REPO)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)
        self.assertIn("status: new", open(path, encoding="utf-8").read())


class ProbeIsFrozenInWork(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def test_changing_the_probe_of_a_card_in_work_is_refused(self):
        path = _card(self.tmp, "inbox-v-rabote", status="in-progress", probe="tier_promotion_loop_closed")
        with self.assertRaises(q.AcceptanceCriterionLocked):
            q.set_acceptance_probe(path, "lead_channel_wiring_ok")
        self.assertIn("acceptance_probe: tier_promotion_loop_closed", open(path, encoding="utf-8").read())

    def test_same_probe_restated_is_not_a_change(self):
        path = _card(self.tmp, "inbox-ta-zhe", status="in-progress", probe="tier_promotion_loop_closed")
        q.set_acceptance_probe(path, "tier_promotion_loop_closed")

    def test_adding_a_probe_to_a_baseline_card_in_work_is_allowed(self):
        path = _card(self.tmp, "inbox-bez-proby-v-rabote", status="in-progress")
        q.set_acceptance_probe(path, "tier_promotion_loop_closed")
        self.assertIn("acceptance_probe: tier_promotion_loop_closed", open(path, encoding="utf-8").read())

    def test_probe_of_a_card_in_intake_may_change(self):
        path = _card(self.tmp, "inbox-eshche-nichya", probe="tier_promotion_loop_closed")
        q.set_acceptance_probe(path, "lead_channel_wiring_ok")

    def test_cli_refuses_with_exit_2(self):
        path = _card(self.tmp, "inbox-cli-lock", status="blocked", probe="tier_promotion_loop_closed")
        r = subprocess.run([sys.executable, _CLI, "probe", path, "lead_channel_wiring_ok"],
                           capture_output=True, text=True, timeout=120, cwd=_REPO)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)


if __name__ == "__main__":
    unittest.main()


class ACarrierIsRetiredNotTakenIntoWork(unittest.TestCase):
    """ADR-375: приём гасит НОСИТЕЛЬ, назвав предмет, куда уехало содержимое.

    Правило машинной приёмки написано про «карточку БЕРУТ В РАБОТУ без мерки». Приём
    заданий делает другое: идея уезжает в заметку, вопрос — в карточку владельцу, а
    сама inbox-карточка гасится как отработавший носитель. Требовать у носителя пробу
    не к чему: его приёмка ровно одна — содержимое теперь лежит ВОТ ЗДЕСЬ.

    **Освобождение обязано быть ЗАРАБОТАННЫМ, а не флагом-доверием.** Первая редакция
    приняла бы `carried_to` по имени, без проверки, — и мутация, снявшая проверку
    существования, ничего не покрасила: то есть отличить заработанное освобождение от
    опт-аута было нечем. Эти два теста и есть та разница.
    """

    def _card(self, tmp: Path) -> Path:
        p = tmp / "inbox-nositel.md"
        p.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: \"н\"\nstatus: new\n---\n\nтекст\n",
                     encoding="utf-8")
        return p

    def test_a_named_but_MISSING_target_does_not_free_the_carrier(self):
        """Имя без файла — обещание, а не приёмка."""
        import tempfile
        from spa_core.owner_queue.queue import set_status, AcceptanceCriterionMissing
        with tempfile.TemporaryDirectory() as tmp:
            card = self._card(Path(tmp))
            with self.assertRaises(AcceptanceCriterionMissing) as ctx:
                set_status(card, "done", carried_to=Path(tmp) / "ничего-нет.md")
            self.assertIn("carried_to", str(ctx.exception))

    def test_an_existing_target_frees_the_carrier(self):
        """Обратная сторона: предмет существует — носитель гасится."""
        import tempfile
        from spa_core.owner_queue.queue import set_status, load_card
        with tempfile.TemporaryDirectory() as tmp:
            card = self._card(Path(tmp))
            target = Path(tmp) / "docs-ideas-zametka.md"
            target.write_text("# идея\n", encoding="utf-8")
            set_status(card, "done", carried_to=target)
            self.assertEqual(load_card(card).status, "done")

    def test_without_carried_to_the_rule_still_refuses(self):
        """Контроль на сам механизм: без носителя правило обязано работать как прежде."""
        import tempfile
        from spa_core.owner_queue.queue import set_status, AcceptanceCriterionMissing
        with tempfile.TemporaryDirectory() as tmp:
            card = self._card(Path(tmp))
            with self.assertRaises(AcceptanceCriterionMissing):
                set_status(card, "done")


class CarriedReleaseIsOneCondition(unittest.TestCase):
    """ADR-501: у освобождения носителя ОДНА копия условия — и у каждой стороны контроль.

    Замер цикла #717, ради которого написан класс: `set_status` считал путь от **CWD**,
    а храповик приёмки — от **корня репозитория**. Один и тот же законный `carried_to`
    очередь принимала из корня репо и ОТКАЗЫВАЛА из любого другого каталога, тогда как
    сторож освобождал всегда. Это расхождение ВТОРОГО РОДА (исполнитель и сторож
    проверяют разное), и именно оно названо в карточке
    `inbox-hrapovik-priemki-krasen-na-ispravnom-sos` как оставшаяся работа.

    Каждая сторона условия закреплена в ОБЕ стороны: сторона без отрицательного
    контроля — украшение, потому что снявшая её мутация ничего не покрасит.
    """

    def _scene(self, tmp: Path):
        """Одноразовое дерево: корень, трекер, каталог идей."""
        (tmp / "nimbalyst-local" / "tracker").mkdir(parents=True)
        (tmp / "docs" / "ideas").mkdir(parents=True)
        card = tmp / "nimbalyst-local" / "tracker" / "inbox-nositel.md"
        card.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: \"н\"\nstatus: new\n---\n\nтекст\n",
                        encoding="utf-8")
        return card

    def _release(self, target, card, tmp):
        from spa_core.owner_queue.queue import carried_release
        return carried_release(target, card, repo_root=tmp,
                               tracker_dir=tmp / "nimbalyst-local" / "tracker")

    def test_the_verdict_does_not_depend_on_the_CURRENT_DIRECTORY(self):
        """ТОТ САМЫЙ дефект: вердикт обязан быть один из любого каталога.

        Прежняя редакция исполнителя звала `Path(carried_to).exists()` — то есть
        спрашивала у CWD. Карточки двигают из worktree и из песочницы, и путь в
        карточке обязан значить одно и то же отовсюду.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            (tmp / "nimbalyst-local" / "tracker" / "inbox-cel.md").write_text("цель", encoding="utf-8")
            rel = "nimbalyst-local/tracker/inbox-cel.md"
            verdicts = []
            cwd_before = os.getcwd()
            try:
                for where in (tmp, Path(tempfile.mkdtemp())):
                    os.chdir(where)
                    verdicts.append(self._release(rel, card, tmp)[0] is not None)
            finally:
                os.chdir(cwd_before)
            self.assertEqual(verdicts, [True, True],
                             "вердикт освобождения зависит от текущего каталога — "
                             "это ровно расхождение, измеренное циклом #717")

    def test_the_guard_and_the_executor_read_THE_SAME_code(self):
        """Не «оба зелёные», а буквально одна функция: своей копии нет ни у кого."""
        import inspect
        from spa_core.owner_queue import queue as q
        import spa_core.tests.test_inbox_acceptance_ratchet as ratchet
        self.assertIs(ratchet.carried_release, q.carried_release)
        self.assertIn("carried_release(", inspect.getsource(q.set_status),
                      "исполнитель завёл свою редакцию условия — это возврат к двум копиям")

    def test_a_card_may_not_free_ITSELF(self):
        """Тавтология освобождением не является: иначе это опт-аут с нулевой ценой."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            path, why = self._release(card, card, tmp)
            self.assertIsNone(path, "карточка освободила сама себя")
            self.assertIn("саму карточку", why)

    def test_an_arbitrary_existing_file_is_NOT_a_release(self):
        """Обратная сторона мира носителя: иначе `carried_to: README.md` гасит что угодно."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            (tmp / "README.md").write_text("не предмет носителя", encoding="utf-8")
            path, why = self._release("README.md", card, tmp)
            self.assertIsNone(path, "любой существующий файл освободил носителя — "
                                    "это универсальный глушитель храповика")
            self.assertIn("вне мира носителя", why)

    def test_an_IDEA_NOTE_frees_the_carrier(self):
        """`docs/ideas/` — законный предмет: туда гасит носителя сам `intake`.

        Условие «цель обязана быть карточкой трекера» (как оно записано в карточке)
        отказало бы этому пути. Поэтому оно ИЗМЕРЕНО и отклонено, а не переписано.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            (tmp / "docs" / "ideas" / "2026-09-28-mysl.md").write_text("# идея", encoding="utf-8")
            path, _ = self._release("docs/ideas/2026-09-28-mysl.md", card, tmp)
            self.assertIsNotNone(path, "законное освобождение идеей отклонено — "
                                       "это сломало бы ветку kind=='idea' у intake")

    def test_a_DIRECTORY_is_not_a_subject(self):
        """Каталог существует, но содержимое носителя в него не уезжает."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            path, why = self._release("docs/ideas", card, tmp)
            self.assertIsNone(path)
            self.assertIn("каталог", why)

    def test_every_refusal_NAMES_THE_LINK_that_actually_failed(self):
        """Отказ обязан назвать ИМЕННО ТО звено, которое не сошлось.

        Сначала здесь проверялось лишь «причина непустая», и батарея мутаций показала
        цену такой проверки: три мутанта из семи ВЫЖИЛИ. Снятая проверка существования
        и снятая проверка пустоты обе проваливались дальше, в ветку `is_file()`, и
        пропавший предмет объявлялся «каталогом». Вердикт при этом оставался верным —
        а причина лгала, и чинить по ней было нечего. Это тот же класс «зелёный ответ
        на СВОЙ вопрос», только на тексте отказа.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            (tmp / "README.md").write_text("не предмет", encoding="utf-8")
            (tmp / "nimbalyst-local" / "tracker" / "_BOARD.json").write_text("{}", encoding="utf-8")
            cases = [
                (None,                                  "не объявлен"),
                ("",                                    "пуст"),
                ("нет-такого.md",                       "такого файла нет"),
                ("docs/ideas",                          "каталог"),
                ("README.md",                           "вне мира носителя"),
                ("nimbalyst-local/tracker/_BOARD.json", "не `.md`"),
                (str(card),                             "саму карточку"),
            ]
            for target, expect in cases:
                path, why = self._release(target, card, tmp)
                self.assertIsNone(path, f"{target!r} освободил носителя")
                self.assertIn(expect, why,
                              f"отказ по {target!r} назвал НЕ ТО звено: {why!r}")

    def test_the_seam_REACHES_the_executor_not_just_the_condition(self):
        """Половина проводки — та же бомба (урок #453).

        Шов `repo_root` у самого условия ничего не стоит, если `set_status` его не
        передаёт: приём заданий кладёт заметку-идею в СВОЙ корень, и носитель получал
        бы отказ всюду, кроме боевого дерева. Ровно это и покраснело у `test_owner_intake`
        в цикле #717, когда шов дошёл до условия и не дошёл до исполнителя.
        """
        import tempfile
        from spa_core.owner_queue.queue import set_status, load_card, AcceptanceCriterionMissing
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            card = self._scene(tmp)
            note = tmp / "docs" / "ideas" / "2026-09-28-mysl.md"
            note.write_text("# идея", encoding="utf-8")
            # без объявленного корня заметка лежит вне мира носителя — отказ
            with self.assertRaises(AcceptanceCriterionMissing):
                set_status(card, "done", carried_to=note)
            # с объявленным — освобождение заработано
            set_status(card, "done", carried_to=note, repo_root=tmp)
            self.assertEqual(load_card(card).status, "done")
