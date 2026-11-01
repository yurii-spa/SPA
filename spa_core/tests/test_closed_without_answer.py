"""Закрытая просьба владельца без записанного ответа — разложение по следу (ADR-885).

Каждый тест здесь — положительный контроль на НАСТОЯЩИЙ замер 2026-11-01, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»):

* перепись ADR-863 говорила «ответа не записано ничем» про **50** закрытых заданий
  владельца, и **47** из них несли ответ В ТЕЛЕ — под заголовком, которого не было в
  словаре `ОТВЕТ|ОТВЕЧАЮ|ЗАМЕР|РЕЗУЛЬТАТ|РАЗОБРАНО`. Число было свойством ЧИТАТЕЛЯ;
* тот же прибор на прод-дереве обвиняет **11** карточек, а на worktree от `origin/main`
  — **ни одной**, и расходится вердикт у **6** из 63 общих, ВСЕГДА в сторону обвинения;
* ослеплённый корпус («каталог журнала не открылся») обязан давать НЕ ИЗМЕРЕНО, а не
  «следа нет»: обвинение, выведенное из своего незнания, тише красного теста и потому
  опаснее (инв. #17).

Времени в фикстурах нет вовсе: предмет — СТРУКТУРА тела и наличие ссылок, поэтому
литеральных дат и номеров процессов этой батарее не нужно ни одного (оба класса —
`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.owner_queue import answer_channel as ac
from spa_core.owner_queue import closed_without_answer as cwa

#: Дословное тело карточки, рождённой приёмом и больше никем не тронутой: ровно так
#: выглядит «купить зонт в пятницу» в живой очереди. Работы в ней нет, и мера обязана
#: это сказать.
INTAKE_ONLY = ("## Задание (из Telegram)\n\nкупить зонт в пятницу\n\n---\n"
               "_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении "
               "закрой карточку со ссылкой на порождённую работу (§6.4)._\n")

#: Приёмный штамп критерия — его дописывает `intake._INTAKE_CRITERION_STAMP`.
CRITERION_STAMP = ("\n## Как понять, что готово\n"
                   "Задача выполнена и проверена (детали — обычный цикл).\n")


def write_card(d: Path, name: str, *, body: str, status: str = "done",
               source: str = "voice", extra: str = "", title: str = "просьба") -> Path:
    p = Path(d) / f"inbox-{name}.md"
    p.write_text("---\ntrackerStatus:\n  type: inbox\n"
                 f"title: {title}\nstatus: {status}\nsource: {source}\n{extra}"
                 f"---\n\n{body}", encoding="utf-8")
    return p


def scene(td: Path) -> tuple[Path, Path]:
    """Одноразовое дерево: трекер + журнал. Корпус пуст, пока тест не напишет в него."""
    tr = td / "nimbalyst-local" / "tracker"
    jr = td / "docs" / "journal"
    tr.mkdir(parents=True)
    jr.mkdir(parents=True)
    (jr / "W01.md").write_text("пусто\n", encoding="utf-8")
    return tr, jr


class StructuralSignal(unittest.TestCase):
    """Признак «есть ли в теле запись работы» обязан быть СТРУКТУРНЫМ, не словарным."""

    def test_intake_template_alone_is_not_a_record_of_work(self):
        """Авария наоборот: штамп приёма, засчитанный за работу, оправдал бы пустышку."""
        self.assertEqual([], ac.work_sections(INTAKE_ONLY))
        self.assertEqual([], ac.work_sections(INTAKE_ONLY + CRITERION_STAMP))

    def test_every_heading_the_intake_writers_write_is_declared_as_template(self):
        """Дрейф перечня приёмных заголовков — молчаливый fail-OPEN.

        Перечень `TEMPLATE_HEADINGS` объявлен в одном месте, а ПИШУТ заголовки другие
        модули. Разойдись они — приёмный штамп начал бы читаться как запись работы, и
        число «ответ есть» выросло бы само, без единой правки меры.
        """
        from spa_core.telegram import inbox_intake as ii
        from spa_core.owner_queue import intake as oi

        written = [
            "## Задание (из Telegram)",
            "## Задание (из пульта)",
            "## Расшифровка голосового (whisper)",
            "## Как это приехало",
            ii.UNAPPLIED_ANSWER_HEADING,
            oi._INTAKE_CRITERION_STAMP.splitlines()[0],
        ]
        for heading in written:
            with self.subTest(heading=heading):
                self.assertEqual(
                    [], ac.work_sections(f"{heading}\n\nтекст\n"),
                    f"заголовок приёма «{heading}» засчитан за запись работы")

    def test_the_vocabulary_defect_of_adr_863_is_reproduced_and_closed(self):
        """ДОСЛОВНЫЕ формы из живой очереди, которых словарь ADR-863 не видел."""
        for heading in ("Что сделано (цикл #217)", "Разбор (цикл #166)",
                        "Резолюция (интерактивная сессия с владельцем)",
                        "Исполнено (цикл #310)", "Обработано оркестратором",
                        "Закрыто как дубль якорной задачи", "Сделано (автономный цикл)"):
            with self.subTest(heading=heading):
                got = ac.work_sections(f"{INTAKE_ONLY}\n## {heading}\n\nтекст\n")
                self.assertEqual([heading], got)

    def test_an_unfamiliar_heading_counts_and_is_named(self):
        """Словарь расшириться не может: вопрос задан о СТРУКТУРЕ, а не о слове."""
        got = ac.work_sections(f"{INTAKE_ONLY}\n## Нечто, чего нет ни в одном словаре\n\nх\n")
        self.assertEqual(["Нечто, чего нет ни в одном словаре"], got)

    def test_answer_evidence_names_the_section_it_found(self):
        """«Ответ записан в теле» без указания РАЗДЕЛА — то же обещание, только короче."""
        ev = ac.answer_evidence({"source": "voice", "status": "done"},
                                f"{INTAKE_ONLY}\n## Резолюция\n\nсделано\n")
        self.assertEqual((ac.EV_SECTION, "Резолюция"), ev)
        text = ac.answer_notice_text("просьба", *ev, "inbox-x.md")
        self.assertIn("Резолюция", text)

    def test_answer_evidence_stays_silent_when_only_the_intake_stamp_is_there(self):
        """Сказать «готово», не умея сказать ЧТО, — обещание, а не ответ (ADR-863)."""
        self.assertIsNone(ac.answer_evidence({"source": "voice", "status": "done"},
                                             INTAKE_ONLY + CRITERION_STAMP))


class PopulationIsDeclared(unittest.TestCase):
    """Население объявлено: закрытое задание владельца БЕЗ сильного основания ответа."""

    def test_strong_basis_keeps_the_card_out_of_the_population(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "probe", body=INTAKE_ONLY,
                       extra='verified_by_probe: "x"\n')
            write_card(tr, "carried", body=INTAKE_ONLY,
                       extra="carried_to: nimbalyst-local/tracker/inbox-y.md\n")
            write_card(tr, "live", body=INTAKE_ONLY)
            rep = cwa.measure(tr, repo_root=Path(td))
            self.assertEqual(["inbox-live.md"], [r["card"] for r in rep["rows"]])

    def test_an_open_card_and_a_foreign_source_are_not_the_population(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "open", body=INTAKE_ONLY, status="new")
            write_card(tr, "agent", body=INTAKE_ONLY, source="nimbalyst")
            rep = cwa.measure(tr, repo_root=Path(td))
            self.assertEqual(0, rep["population"], rep["rows"])


class ThreeGroupsAreDistinguished(unittest.TestCase):
    """Три объяснения карточки владельца обязаны получить РАЗНЫЕ исходы."""

    def _three(self, td: Path):
        tr, jr = scene(td)
        write_card(tr, "in-body", body=f"{INTAKE_ONLY}\n## Что сделано\n\nсделано\n")
        write_card(tr, "outside", body=INTAKE_ONLY)
        write_card(tr, "nowhere", body=INTAKE_ONLY)
        (jr / "W02.md").write_text("ответ по inbox-outside лёг сюда\n", encoding="utf-8")
        return tr

    def test_each_explanation_gets_its_own_group(self):
        with tempfile.TemporaryDirectory() as td:
            tr = self._three(Path(td))
            rep = cwa.measure(tr, repo_root=Path(td))
            got = {r["card"]: r["group"] for r in rep["rows"]}
            self.assertEqual({"inbox-in-body.md": cwa.RECORD_IN_BODY,
                              "inbox-outside.md": cwa.RECORD_OUTSIDE,
                              "inbox-nowhere.md": cwa.NO_TRACE}, got)

    def test_the_outside_group_names_where(self):
        """«След есть» без адреса проверить нечем — это утверждение на честном слове."""
        with tempfile.TemporaryDirectory() as td:
            tr = self._three(Path(td))
            rep = cwa.measure(tr, repo_root=Path(td))
            row = next(r for r in rep["rows"] if r["card"] == "inbox-outside.md")
            self.assertEqual(["W02.md"], row["named_by"])

    def test_needs_human_judgement_is_both_groups_without_a_record_in_the_card(self):
        with tempfile.TemporaryDirectory() as td:
            tr = self._three(Path(td))
            rep = cwa.measure(tr, repo_root=Path(td))
            self.assertEqual({"inbox-outside.md", "inbox-nowhere.md"},
                             {r["card"] for r in cwa.needs_human_judgement(rep)})

    def test_no_verdict_about_rubbish_is_ever_produced(self):
        """«Мусор» машиной не решается — модуль отдаёт ФАКТЫ, а не приговор."""
        with tempfile.TemporaryDirectory() as td:
            tr = self._three(Path(td))
            rep = cwa.measure(tr, repo_root=Path(td))
            self.assertNotIn("rubbish", cwa.GROUPS)
            self.assertNotIn("trash", cwa.GROUPS)
            for r in rep["rows"]:
                self.assertIn(r["group"], cwa.GROUPS)


class BlindedCorpusIsUnmeasuredNotAnAccusation(unittest.TestCase):
    """Несущее: обвинение, выведенное из своего незнания, опаснее отсутствующего."""

    def test_missing_corpus_turns_the_accusation_into_the_third_outcome(self):
        with tempfile.TemporaryDirectory() as td:
            tr, jr = scene(Path(td))
            write_card(tr, "nowhere", body=INTAKE_ONLY)
            write_card(tr, "in-body", body=f"{INTAKE_ONLY}\n## Разбор\n\nх\n")
            before = {r["card"]: r["group"] for r in cwa.measure(tr, repo_root=Path(td))["rows"]}
            self.assertEqual(cwa.NO_TRACE, before["inbox-nowhere.md"])

            for p in jr.iterdir():
                p.unlink()
            jr.rmdir()
            rep = cwa.measure(tr, repo_root=Path(td))
            after = {r["card"]: r["group"] for r in rep["rows"]}
            self.assertEqual(cwa.UNMEASURED, after["inbox-nowhere.md"],
                             "непрочитанный корпус выдан за «следа нет» — fail-OPEN "
                             "в сторону обвинения")
            self.assertEqual(cwa.RECORD_IN_BODY, after["inbox-in-body.md"],
                             "след В ТЕЛЕ от корпуса не зависит и пропасть не вправе")
            self.assertIsNotNone(rep["unmeasured_reason"])
            self.assertIn("НЕ ПРОЧИТАН", rep["unmeasured_reason"])

    def test_an_unreadable_corpus_file_is_counted_not_swallowed(self):
        with tempfile.TemporaryDirectory() as td:
            _, jr = scene(Path(td))
            (jr / "W03.md").write_bytes(b"\xff\xfe\x00\x01")
            _, stat = cwa.corpus_references(Path(td))
            self.assertEqual(1, stat["failed"], stat)
            self.assertEqual(1, stat["files"], stat)

    def test_an_unreadable_card_is_its_own_third_outcome(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            p = write_card(tr, "broken", body=INTAKE_ONLY)
            p.chmod(0o000)
            try:
                rep = cwa.measure(tr, repo_root=Path(td))
            finally:
                p.chmod(0o644)
            row = next(r for r in rep["rows"] if r["card"] == "inbox-broken.md")
            self.assertEqual(cwa.UNMEASURED, row["group"])
            self.assertIn("не прочитана", row["reason"])


class WeakSignalsAreNeverAGroup(unittest.TestCase):
    """Признак, оправдывающий ВСЁ население, мерит не предмет, а связность трекера."""

    def test_the_auto_index_never_absolves_a_card(self):
        with tempfile.TemporaryDirectory() as td:
            tr, jr = scene(Path(td))
            write_card(tr, "nowhere", body=INTAKE_ONLY)
            (jr / "_BOARD.md").write_text("- inbox-nowhere\n", encoding="utf-8")
            rep = cwa.measure(tr, repo_root=Path(td))
            row = next(r for r in rep["rows"] if r["card"] == "inbox-nowhere.md")
            self.assertEqual(cwa.NO_TRACE, row["group"],
                             "авто-индекс перечисляет каждую карточку по построению — "
                             "его упоминание оправдало бы любую")
            self.assertEqual(1, rep["corpus"]["excluded"])

    def test_a_neighbour_card_is_a_fact_of_the_row_not_a_group(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "nowhere", body=INTAKE_ONLY)
            (tr / "inbox-neighbour.md").write_text(
                "---\ntrackerStatus:\n  type: inbox\ntitle: сосед\nstatus: new\n"
                "source: nimbalyst\n---\n\nсм. inbox-nowhere\n", encoding="utf-8")
            rep = cwa.measure(tr, repo_root=Path(td))
            row = next(r for r in rep["rows"] if r["card"] == "inbox-nowhere.md")
            self.assertEqual(cwa.NO_TRACE, row["group"])
            self.assertEqual(["inbox-neighbour.md"], row["named_by_neighbour"])

    def test_a_file_naming_only_itself_does_not_absolve_itself(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "selfref", body=f"{INTAKE_ONLY}\nсм. inbox-selfref\n")
            rep = cwa.measure(tr, repo_root=Path(td))
            row = next(r for r in rep["rows"] if r["card"] == "inbox-selfref.md")
            self.assertEqual([], row["named_by_neighbour"])

    def test_a_twin_by_title_is_reported_as_a_fact(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "zont-1", body=INTAKE_ONLY, title="купить зонт в пятницу")
            write_card(tr, "zont-2", body=INTAKE_ONLY, title="купить зонт в пятницу")
            rep = cwa.measure(tr, repo_root=Path(td))
            rows = {r["card"]: r for r in rep["rows"]}
            self.assertEqual(["inbox-zont-2.md"], rows["inbox-zont-1.md"]["twin_title"])
            self.assertEqual(["inbox-zont-1.md"], rows["inbox-zont-2.md"]["twin_title"])


class ExemplarAndProbe(unittest.TestCase):
    """Проба приёмки мерит ИСХОД живой меры, и красна на КАЖДОМ порванном звене."""

    def test_the_exemplar_distinguishes_on_the_real_measure(self):
        d = cwa.drive_exemplar()
        self.assertEqual(cwa.DRIVE_DISTINGUISHES, d.get("kind"), d)
        self.assertEqual(cwa.UNMEASURED, d["without_corpus"]["inbox-no_trace.md"])

    def test_the_probe_is_green_on_the_whole_contour(self):
        from spa_core.monitoring import card_acceptance as ca
        verdict, why = ca.run_probe("closed_owner_requests_split_by_the_trace")
        self.assertEqual(ca.SATISFIED, verdict, why)
        self.assertIn("ослеплённый корпус", why)
        # Число без дерева и без размера корпуса здесь наблюдением не является: тот же
        # прибор на прод-дереве обвиняет 11 карточек, а на worktree от origin/main — ни
        # одной. Дыру нашёл мутационный прогон, а не разбор.
        for token in ("трекер", "корпус"):
            self.assertIn(token, why,
                          "проба печатает число, не назвав дерево и корпус")

    def test_the_probe_reds_when_the_intake_stamp_is_counted_as_work(self):
        """Порванное звено: перечень приёмных заголовков опустел.

        Это ПЕРВАЯ половина структурного вопроса, и у неё своя сцена: слепота в сторону
        «работы нет нигде» (вторая половина) красит пробу другой строкой, поэтому один
        контроль на двоих оставлял дыру — её нашёл мутационный прогон.
        """
        from spa_core.monitoring import card_acceptance as ca

        orig = ac.work_sections
        try:
            ac.work_sections = lambda body: (  # type: ignore[assignment]
                [h.strip("# ") for h in (body or "").splitlines() if h.startswith("##")])
            verdict, why = ca.run_probe("closed_owner_requests_split_by_the_trace")
        finally:
            ac.work_sections = orig  # type: ignore[assignment]
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("приёмный штамп засчитан", why)

    def test_the_probe_passes_the_exemplars_third_outcome_through(self):
        """Порванное звено: «эталон не собрался» выдано за «не выполнено».

        Третий исход, превращённый в провал, — та же подмена, что и наоборот: оба
        исхода требуют РАЗНЫХ действий (починить сцену vs доделать работу).
        """
        from spa_core.monitoring import card_acceptance as ca

        orig = cwa.drive_exemplar
        try:
            cwa.drive_exemplar = lambda: {  # type: ignore[assignment]
                "kind": cwa.DRIVE_UNMEASURED, "reason": "сцена не собралась (контроль)"}
            verdict, why = ca.run_probe("closed_owner_requests_split_by_the_trace")
        finally:
            cwa.drive_exemplar = orig  # type: ignore[assignment]
        self.assertEqual(ca.UNMEASURED, verdict, why)
        self.assertIn("эталон не собрался", why)

    def test_the_probe_reds_when_the_structural_signal_becomes_a_vocabulary(self):
        """Порванное звено: словарь вернулся на место структурного признака."""
        import re

        from spa_core.monitoring import card_acceptance as ca

        narrow = re.compile(r"(?mi)^\#{2,}\s*(?:[^\n]*\b)?(ОТВЕТ|ЗАМЕР)\b")
        orig = ac.work_sections
        try:
            ac.work_sections = lambda body: (  # type: ignore[assignment]
                ["словарь"] if body and narrow.search(body) else [])
            verdict, why = ca.run_probe("closed_owner_requests_split_by_the_trace")
        finally:
            ac.work_sections = orig  # type: ignore[assignment]
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("СЛОВАРЬ", why,
                      "вердикт верный, а ИМЯ порванного звена — нет: ослепление "
                      "признака обязано назвать признак, а не эталон")

    def test_the_probe_reds_when_the_blinded_corpus_still_accuses(self):
        """Порванное звено: «следа нет» выведено из непрочитанного корпуса."""
        from spa_core.monitoring import card_acceptance as ca

        orig = cwa.classify

        def accusing(card_path, *, refs, body=None):
            return orig(card_path, refs=refs if refs is not None else {}, body=body)

        try:
            cwa.classify = accusing  # type: ignore[assignment]
            verdict, why = ca.run_probe("closed_owner_requests_split_by_the_trace")
        finally:
            cwa.classify = orig  # type: ignore[assignment]
        self.assertEqual(ca.NOT_SATISFIED, verdict, why)
        self.assertIn("РОВНО одним", why)

    def test_the_probe_is_unmeasured_when_the_module_is_absent(self):
        """Третий исход СВОЙ: модуль не ввозится ⇒ `unmeasured`, не «не выполнено».

        Ослепление делается в ДВА хода, и это не формальность: ``from package import
        name`` берёт УЖЕ ПРИВЯЗАННЫЙ атрибут пакета и в ``sys.modules`` не смотрит
        вовсе — первая редакция теста подменяла только ``sys.modules`` и честно
        показала, что ничего не ослепила.
        """
        import sys

        from spa_core.monitoring import card_acceptance as ca
        from spa_core import owner_queue as oq

        name = "spa_core.owner_queue.closed_without_answer"
        saved_mod = sys.modules.pop(name)
        saved_attr = oq.closed_without_answer
        delattr(oq, "closed_without_answer")
        sys.modules[name] = None  # type: ignore[assignment]
        try:
            verdict, why = ca.run_probe("closed_owner_requests_split_by_the_trace")
        finally:
            sys.modules[name] = saved_mod
            oq.closed_without_answer = saved_attr
        self.assertEqual(ca.UNMEASURED, verdict, why)
        self.assertIn("не ввозится", why)


class AntiStormIsPreserved(unittest.TestCase):
    """Расширение признака НЕ рассылает владельцу историю (ADR-863, граница — МЕТКА)."""

    def test_a_historical_card_with_a_record_in_the_body_is_not_sent(self):
        from spa_core.owner_queue import cockpit_loop as cl

        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "historical", body=f"{INTAKE_ONLY}\n## Что сделано\n\nх\n")
            ob = Path(td) / "outbox.json"
            ob.write_text(json.dumps({"schema": 1, "pending": []}), encoding="utf-8")
            self.assertEqual([], cl.sweep_notices(tracker_dir=tr, outbox_path=ob),
                             "рассылка о работе недельной давности — шум, а не ответ")
            self.assertEqual([], json.loads(ob.read_text(encoding="utf-8"))["pending"])

    def test_the_verdict_about_a_historical_card_stays_unmeasured(self):
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            p = write_card(tr, "historical", body=f"{INTAKE_ONLY}\n## Разбор\n\nх\n")
            ob = Path(td) / "outbox.json"
            ob.write_text(json.dumps({"schema": 1, "pending": []}), encoding="utf-8")
            ok, why = ac.delivery_verdict(p, outbox_path=ob)
            self.assertIsNone(ok, why)
            self.assertIn("НЕ ИЗМЕРЕНО", why)


class CommandLine(unittest.TestCase):
    def test_the_report_prints_the_tree_and_the_corpus_next_to_the_number(self):
        """Число без дерева здесь наблюдением не является (замер 6 из 63 расхождений)."""
        with tempfile.TemporaryDirectory() as td:
            tr, _ = scene(Path(td))
            write_card(tr, "nowhere", body=INTAKE_ONLY)
            rep = cwa.measure(tr, repo_root=Path(td))
            self.assertEqual(str(Path(td)), rep["repo_root"])
            self.assertEqual(1, rep["corpus"]["files"])
            self.assertTrue(rep["corpus"]["read"])

    def test_a_missing_tracker_directory_is_unmeasured_with_a_named_reason(self):
        with tempfile.TemporaryDirectory() as td:
            rep = cwa.measure(Path(td) / "нет-такого")
            self.assertIsNone(rep["population"])
            self.assertIn("каталога трекера нет", rep["unmeasured_reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
