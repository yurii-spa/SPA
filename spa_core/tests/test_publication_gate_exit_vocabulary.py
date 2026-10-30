"""ADR-869 — у ворот публикации ТРИ исхода, у их читателя было ДВА (инв. #17).

Авария, которую воспроизводит этот файл, случилась на живом прогоне шага 1е 30.10.2026:
`scripts/publish_site_numbers.py` вышел кодом **2**, протокол оркестратора читает `2` как
«НЕ ИЗМЕРЕНО (источник не прочитан) ⇒ карточка», а правдой было ровно обратное — витрина
СОБРАНА, ворота её ИЗМЕРИЛИ и отказали названными находками, карточка владельцу уже
открыта. Цикл, исполняющий протокол буквально, завёл бы карточку о непрочитанном
источнике, которого не было, и настоящее состояние осталось бы невидимым.

Причина лежала в ЧИТАТЕЛЕ, а не в воротах: `scripts/verify_publication.py` объявляет три
исхода (0 PASS · 1 FAIL · 2 NOT MEASURED) и честно их отдаёт, а
`safe_site_push.main` сводил оба ненулевых в один код 2 — и на НЕизмерении заводил
владельцу карточку, то есть просил подписать витрину, которой никто не проверял. Починка
того же дефекта УЖЕ СТОЯЛА в соседней ветке той же функции (owner-гейт: «код 2 без отчёта,
называющего файлы, — не вердикт GATED … одобрять нечего ⇒ владельца не спрашиваем»); одна
ветка её не получила.

Контроль — в ОБЕ стороны и по ИСХОДУ, а не по подстроке: каждая проверка ниже красна на
состоянии до ADR-869 (оба исхода дают 2, карточка заводится в обоих) и зелена после.
Литеральных якорей времени в файле нет, поэтому и освобождения `FROZEN-DATE-OK` нет.
"""
from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Scene(unittest.TestCase):
    """Сцена: витрина на диске + перехваченный маршрутизатор карточки владельцу.

    Настоящие ворота здесь НЕ зовутся: предмет этих проверок — ЧИТАТЕЛЬ исхода, и подмена
    `_verify_publication` называет каждый исход прямо, вместо того чтобы подбирать входы,
    которые его случайно вызовут.
    """

    def setUp(self):
        self.ssp = _load("ssp_vocab", "scripts/safe_site_push.py")
        d = pathlib.Path(tempfile.mkdtemp(prefix="adr869_"))
        self.addCleanup(__import__("shutil").rmtree, d, ignore_errors=True)
        self.shelf = d / "landing" / "src" / "data" / "site_numbers.json"
        self.shelf.parent.mkdir(parents=True)
        self.shelf.write_text('{"published_at": "2026-10-07"}', encoding="utf-8")
        self.owner_asked: list = []
        self.ssp._route_to_owner_card = lambda *a, **k: self.owner_asked.append(k or True)

    def _push_with_gate(self, outcome: int, res: dict) -> int:
        self.ssp._verify_publication = lambda shelf: (outcome, res)
        return self.ssp.main(["--files", str(self.shelf), "-m", "x"])

    FAIL = (1, {"outcome": 1, "reason": None,
                "findings": ["a public rate changed without an approval"]})
    NOT_MEASURED = (2, {"outcome": 2, "findings": [],
                        "reason": "verify_publication did not answer (TimeoutExpired)"})


class TheReaderKeepsTheGatesThreeOutcomesApart(_Scene):

    def test_a_refusal_with_named_findings_is_the_owners_business(self):
        self.assertEqual(self._push_with_gate(*self.FAIL), 2)
        self.assertTrue(self.owner_asked, "вердикт FAIL назвал находки — карточка обязана быть")

    def test_a_gate_that_did_not_answer_is_not_the_owners_business(self):
        """Ядро аварии: до ADR-869 здесь было 2 и карточка — как у FAIL."""
        self.assertEqual(self._push_with_gate(*self.NOT_MEASURED), 1)
        self.assertEqual(self.owner_asked, [],
                         "одобрять нечего: ворота НЕ ОТВЕТИЛИ, находок нет")

    def test_the_two_refusals_are_distinguishable_by_code_alone(self):
        """Различимость — предмет сама по себе: читатель кода не видит ни stderr, ни карточек."""
        fail = self._push_with_gate(*self.FAIL)
        self.setUp()
        unmeasured = self._push_with_gate(*self.NOT_MEASURED)
        self.assertNotEqual(fail, unmeasured, (fail, unmeasured))
        self.assertNotIn(0, (fail, unmeasured), "ни один отказ не смеет выглядеть успехом")


class TheNotMeasuredLiteralDoesNotDriftFromTheGate(unittest.TestCase):
    """Ворота зовутся ПОДПРОЦЕССОМ, поэтому их словарь у читателя — литерал.

    Литерал без сторожа и есть тихая подмена: разойдись он с воротами, «не измерено» снова
    стало бы неотличимо от «отказано», и ни один тест об этом бы не сказал.
    """

    def test_the_readers_constant_is_the_gates_own_value(self):
        ssp = _load("ssp_vocab_const", "scripts/safe_site_push.py")
        vp = _load("vp_vocab_const", "scripts/verify_publication.py")
        self.assertEqual(ssp._GATE_NOT_MEASURED, vp.NOT_MEASURED)
        self.assertNotEqual(vp.NOT_MEASURED, vp.FAIL)
        self.assertNotEqual(vp.NOT_MEASURED, vp.PASS)

    def test_a_gate_that_crashes_is_reported_as_not_measured_not_as_a_refusal(self):
        """Третий исход рождается у самой двери: подпроцесс, не ответивший, — не FAIL.

        Подменяется ССЫЛКА модуля (`ssp.subprocess`), а НЕ `subprocess.run` внутри самого
        `subprocess`: второе переписало бы общий на весь прогон модуль, и соседи упали бы от
        этой сцены, а не от своего предмета. Измерено прямо здесь — первая редакция уронила
        шесть тестов `test_publication_gate_probe.py`, зелёных в одиночку.
        """
        import types
        ssp = _load("ssp_vocab_crash", "scripts/safe_site_push.py")
        ssp._find_publication_approval = lambda shelf: None

        def _boom(*a, **k):
            raise TimeoutError("gate hung")

        ssp.subprocess = types.SimpleNamespace(run=_boom)
        outcome, res = ssp._verify_publication(pathlib.Path("/nonexistent/shelf.json"))
        self.assertEqual(outcome, ssp._GATE_NOT_MEASURED)
        self.assertEqual(res["findings"], [], "не измерено — это ОТСУТСТВИЕ находок, не находка")

    def test_an_answer_without_an_outcome_field_is_not_measured_and_never_a_pass(self):
        """Найдено мутацией ADR-869 (выживший мутант №5, настоящая дыра, не эквивалент).

        Ворота отвечают JSON-ом через подпроцесс. Ответ БЕЗ поля `outcome` — сломанный
        прибор, не вердикт; умолчание `0` на этом месте было бы fail-OPEN у двери,
        решающей судьбу публичных чисел: витрина уехала бы в live оттого, что ворота
        напечатали не то. Три исхода (инв. #17) различимы и здесь.
        """
        import types
        ssp = _load("ssp_vocab_noout", "scripts/safe_site_push.py")
        ssp._find_publication_approval = lambda shelf: None
        for said, label in (('{"findings": []}', "поля outcome нет"),
                            ('{"outcome": null}', "поле есть, значения нет")):
            with self.subTest(label=label):
                ssp.subprocess = types.SimpleNamespace(
                    run=lambda *a, **k: types.SimpleNamespace(stdout=said, stderr="",
                                                              returncode=0))
                outcome, _res = ssp._verify_publication(pathlib.Path("/nonexistent/shelf.json"))
                self.assertEqual(outcome, ssp._GATE_NOT_MEASURED,
                                 f"{label}: сломанный ответ ворот прочитан как вердикт")


class TheStepSpeaksOneVocabulary(unittest.TestCase):
    """Шаг 1е объявляет свой словарь (0/2/3/4) — и теперь он ПРАВДА.

    До ADR-869 код доставки уезжал наружу дословно, из-за чего `2` значило и «источник не
    прочитан», и «собрано, ждёт владельца». Проверяется ИСХОД перевода на каждом коде
    доставки, который `safe_site_push` действительно отдаёт, плюс незнакомый код.
    """

    DELIVERY_TO_STEP = {0: 0, 1: 2, 2: 4}
    UNDECLARED = 10

    def setUp(self):
        self.psn = _load("psn_vocab", "scripts/publish_site_numbers.py")
        self.bsn = _load("bsn_vocab", "scripts/build_site_numbers.py")
        d = pathlib.Path(tempfile.mkdtemp(prefix="adr869_step_"))
        self.addCleanup(__import__("shutil").rmtree, d, ignore_errors=True)
        self.shelf = d / "site_numbers.json"
        self.shelf.write_text("{}", encoding="utf-8")

    def _run(self, *, raise_=None, outcome=None, delivery=None):
        shelf, bsn_mod = self.shelf, self.bsn

        class FakeBSN:
            NotMeasured = bsn_mod.NotMeasured
            SequencingViolation = bsn_mod.SequencingViolation

            def run(self, **kw):
                if raise_ is not None:
                    raise raise_
                return outcome

        class FakeSSP:
            def main(self, argv):
                return delivery

        return self.psn.run(bsn=FakeBSN(), ssp=FakeSSP() if delivery is not None else None)

    def _built(self):
        return {"published": True, "artifact": self.shelf}

    def test_every_delivery_code_lands_on_its_declared_meaning(self):
        for delivery, step in self.DELIVERY_TO_STEP.items():
            with self.subTest(delivery=delivery):
                self.assertEqual(self._run(outcome=self._built(), delivery=delivery), step)

    def test_an_owner_card_is_never_reported_as_an_unread_source(self):
        """Ровно живая авария 30.10: доставка 2 обязана стать 4, а не 2."""
        self.assertEqual(self._run(outcome=self._built(), delivery=2), 4)

    def test_an_unread_source_keeps_its_own_code(self):
        self.assertEqual(self._run(raise_=self.bsn.NotMeasured("source unreadable")), 2)

    def test_not_measured_at_the_source_and_at_the_gate_share_one_code_but_not_with_the_owner(self):
        """Оба «не измерено» — код 2; «ждёт владельца» — код 4. Классы не смешиваются."""
        at_source = self._run(raise_=self.bsn.NotMeasured("source unreadable"))
        at_gate = self._run(outcome=self._built(), delivery=1)
        waiting = self._run(outcome=self._built(), delivery=2)
        self.assertEqual(at_source, at_gate)
        self.assertNotEqual(at_source, waiting)

    def test_an_undeclared_delivery_code_is_named_and_passed_through(self):
        """«Назван» — часть утверждения, поэтому и меряется: немой третий исход
        неотличим от объявленного, и снятая печать выжила бы молча."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._run(outcome=self._built(), delivery=self.UNDECLARED)
        self.assertEqual(rc, self.UNDECLARED)
        self.assertNotIn(self.UNDECLARED, self.psn._PUSH_CODE,
                         "сцена перестала быть сценой: код стал объявленным")
        said = buf.getvalue()
        self.assertIn(str(self.UNDECLARED), said, f"незнакомый код не НАЗВАН: {said!r}")
        self.assertIn("НЕ ОБЪЯВЛЕН", said, f"исход не назван третьим: {said!r}")

    def test_a_declared_delivery_code_names_both_codes_it_translates(self):
        """Перевод, который молчит, нечем поверить: читатель видит только итоговый код."""
        import contextlib
        import io
        for delivery, step in self.DELIVERY_TO_STEP.items():
            with self.subTest(delivery=delivery):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self._run(outcome=self._built(), delivery=delivery)
                said = buf.getvalue()
                self.assertRegex(said, rf"код доставки {delivery}\b")
                self.assertRegex(said, rf"код шага {step}\b")

    def test_the_declared_vocabulary_is_the_one_the_docstring_names(self):
        """Словарь кода и словарь документа — одно утверждение, а не два."""
        doc = self.psn.__doc__ or ""
        for code in sorted({*self._PSN_CODES(), *self.DELIVERY_TO_STEP.values()}):
            self.assertIn(str(code), doc, f"код шага {code} в документе не объявлен")

    def _PSN_CODES(self):
        return {step for step, _why in self.psn._PUSH_CODE.values()}


class TheDryRunStillPublishesNothing(unittest.TestCase):
    """Перевод кода не смеет НАЧАТЬ доставлять: отрицательный контроль на побочный эффект.

    Класс НЕ наследует сцену шага намеренно: наследование перезапустило бы её проверки
    вторым экземпляром, и одна находка считалась бы дважды.
    """

    setUp = TheStepSpeaksOneVocabulary.setUp
    _built = TheStepSpeaksOneVocabulary._built

    def test_dry_run_never_calls_the_delivery(self):
        called: list = []

        class Loud:
            def main(self, argv):
                called.append(argv)
                return 0

        shelf, bsn_mod, built = self.shelf, self.bsn, self._built()

        class FakeBSN:
            NotMeasured = bsn_mod.NotMeasured
            SequencingViolation = bsn_mod.SequencingViolation

            def run(self, **kw):
                return built

        self.assertEqual(self.psn.run(bsn=FakeBSN(), ssp=Loud(), dry_run=True), 0)
        self.assertEqual(called, [], "DRY-RUN позвал доставку")


if __name__ == "__main__":
    unittest.main()
