"""ADR-808 — критерий §49 `Auditability` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Замер 25.10 по живому дереву (`data/s49_tally_tact.json`, снят 07:20:49Z):
из тринадцати критериев §49 приказа «Portfolio CIO» у `Auditability` в графе
пробы стоял **`null`**, вердикт — **`unmeasured`**, а такт входа — **`unbound`**
(«мерой этого критерия не объявлен НИ ОДИН артефакт конституции»).

При этом ОБА прибора, мерящие дословные слова владельца, работают с 06.09, их
артефакты свежи (4,4 ч при объявленном пределе 7 ч) и печатают `CRITICAL`:

* снимок — `decision_audit_trail` (§43): полностью объяснимых перекладок
  **0 из 46**;
* объяснение — `cio_explainability` (§44): произносится **3 факта из 8**, и во
  фразе владельцу стоя́т внутренние токены — ровно та форма, которую он назвал
  плохой.

То есть критерий владельца был ИЗМЕРЕН дважды и НЕ ИМЕЛ ЧИТАТЕЛЯ ровно там, где
считается его вердикт. Тот же класс, что у `Costs` (ADR-513) и `Determinism`
(ADR-515) — с той разницей, что у этих двух привязки не лежало даже прозой.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `auditability_decision_carries_snapshot_and_explanation` зелена на целом
  контуре и красна на КАЖДОМ порванном звене — с названным звеном И названной
  половиной;
* **половин ДВЕ, и у них разные населения.** Критерий владельца — конъюнкция
  «snapshot И explanation»; поэтому `NOT_SATISFIED` одной половины даёт
  `not_satisfied` независимо от второй (находка есть утверждение
  СУЩЕСТВОВАНИЯ), а `UNMEASURED` одной при `SATISFIED` другой даёт `unmeasured`
  с НАЗВАННОЙ половиной. Класс `TestTheConjunctionIsNotCollapsed` держит обе
  стороны этого правила;
* **пустое население — третий исход, а не зелёный.** «Каждая перекладка
  восстановима» при нуле перекладок и «для каждой recommendation объяснение
  полно» при нуле recommendation верны ПО ПОСТРОЕНИЮ и ответом не являются;
* **положительный контроль §44 — предпосылка вердикта.** Его провал означает,
  что детекторы сломаны, и тогда «молчит» не значит ничего: `unmeasured`;
* переносится поле `criterion.status` прибора, а НЕ его `overall`. `overall` —
  лестница ТЯЖЕСТИ, где третий исход стои́т выше `CRITICAL` намеренно; для
  вердикта критерия это прятало бы ИЗМЕРЕННОЕ красное за «не измерено», то есть
  инвариант #17 наизнанку;
* своего порога у пробы НЕТ ни одного: срок годности каждого артефакта читается
  из `architecture/manifest.json` одним читателем (`declared_slo_hours`);
* прибор, не объявивший себя мерой СВОЕЙ половины, ⇒ `unmeasured`; якорь
  читается как НАЧАЛО строки, а не как вхождение подстроки (ADR-333) — и якоря у
  половин РАЗНЫЕ, иначе прибор о снимке мог бы подписаться мерой объяснения;
* неизвестный вердикт прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `repo_root`, `data_dir` и `now` ДОХОДЯТ до исхода пробы — ВСЕ двери, а не одна
  («половина инъекции», `.claude/rules/deployment.md`);
* проба НЕ ПИШЕТ ни одного артефакта: она читает.

Порядок контроля НЕ произволен: сначала доказывается, что НАСТОЯЩИЕ приборы
несут вердикт половины в своём отчёте и что сцена даёт именно их породы
(`TestTheRealInstrumentsCarryTheHalfVerdict`), и только потом — что проба на них
отвечает. Без первого шага «красно на порванном звене» тавтологично.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся
и в сцену, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается,
живое `data/` не читается: материал пишется в одноразовый каталог.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import cio_explainability as E
from spa_core.monitoring import decision_audit_trail as D
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "auditability_decision_carries_snapshot_and_explanation"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Auditability"

#: Живой замер 25.10, который и породил ADR-808: перекладок 46, восстановимых 0.
_LIVE_MOVES = 46
#: Живой замер 25.10 по книге conservative: произносится 3 факта из 8.
_LIVE_SPOKEN = 3
#: Внутренние токены, стоявшие во фразе владельцу в тот же замер.
_LIVE_TOKENS = ["gain_below_band", "payback_too_long"]


class _Scene(unittest.TestCase):
    """Одноразовое дерево: конституция в `architecture/`, артефакты в `data/`.

    Сцена — это АРТЕФАКТЫ, а правило вердикта берётся у НАСТОЯЩИХ приборов
    (`criterion_verdict`). Подменять правило было бы бессмысленно: проверялась бы
    копия, а не мера.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        (self.root / "architecture").mkdir()
        # Якорь считается ЗДЕСЬ, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        self.build()

    # ── сцена ───────────────────────────────────────────────────────────────

    def _ts(self, hours_ago: float) -> str:
        return (self.now - timedelta(hours=hours_ago)).isoformat()

    def build(self, *, moves: int = 1, answerable: int | None = None,
              spoken: int | None = None, tokens: list | None = None,
              books_with_rec: int = 1, control_passed: bool = True,
              snapshot_age_h: float = 1.0, explanation_age_h: float = 1.0,
              snapshot_slo: float | None = 7.0,
              explanation_slo: float | None = 7.0,
              snapshot_stamp: str | None = None,
              drop: tuple = (), facts_total: int | None = 8) -> None:
        """Целый контур по умолчанию; каждый аргумент рвёт ОДНО звено."""
        answerable = moves if answerable is None else answerable
        spoken = facts_total if spoken is None else spoken

        arts = []
        if snapshot_slo is not None:
            arts.append({"path": D.REPORT_REL, "slo_hours": snapshot_slo,
                         "status": "active"})
        if explanation_slo is not None:
            arts.append({"path": E.REPORT_REL, "slo_hours": explanation_slo,
                         "status": "active"})
        self._write(self.root / "architecture" / "manifest.json",
                    {"artifacts": arts, "agents": []})

        # Сцена ПЕРЕСОБИРАЕТСЯ, а не дописывается: `build` зовётся повторно, и
        # оставленный прошлым зовом файл сделал бы «звено порвано» ложью.
        for rel in (D.REPORT_REL, E.REPORT_REL):
            stale = self.data_dir / Path(rel).name
            if stale.exists():
                stale.unlink()

        if "snapshot" not in drop:
            self._write(self.data_dir / Path(D.REPORT_REL).name, {
                "generated_at": (snapshot_stamp if snapshot_stamp is not None
                                 else self._ts(snapshot_age_h)),
                "overall": "CRITICAL" if answerable < moves else "OK",
                "population": {"moves": moves, "fully_answerable": answerable,
                               "trail_events": moves * 4,
                               "owner_horizon_days": D.OWNER_HORIZON_DAYS},
                "owner_fields": {key: {"owner_wording": wording,
                                       "counts": {D.PRESENT: answerable,
                                                  D.PARTIAL: 0,
                                                  D.ABSENT: moves - answerable,
                                                  D.UNMEASURED: 0}}
                                 for key, wording in D.OWNER_FIELDS},
                "findings": [], "unchecked": [],
            })

        if "explanation" not in drop:
            books = []
            for index in range(3):
                has_rec = index < books_with_rec
                books.append({
                    "book": ("conservative", "balanced", "aggressive")[index],
                    "has_recommendation": has_rec,
                    "tally": {E.SPOKEN: spoken, E.SILENT: 0, E.ABSENT: 0,
                              E.UNCHECKED: 0} if has_rec else
                             {E.SPOKEN: 0, E.SILENT: 0, E.ABSENT: 0,
                              E.UNCHECKED: 0},
                    "machine_tokens": list(tokens or []) if has_rec else [],
                })
            doc = {
                "generated_at": self._ts(explanation_age_h),
                "overall": "CRITICAL",
                "control": {"passed": control_passed, "spoken": 8, "expected": 8,
                            "reason": "" if control_passed else
                                      "пример владельца дал 5 из 8"},
                "books": books,
                "findings": [], "unchecked": [],
            }
            if facts_total is not None:
                doc["facts_total"] = facts_total
            self._write(self.data_dir / Path(E.REPORT_REL).name, doc)

    @staticmethod
    def _write(path: Path, doc) -> None:
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # ── прогон ──────────────────────────────────────────────────────────────

    def probe(self, *, now=None, data_dir=None, repo_root=None) -> tuple:
        """Проба зовётся ПО ИМЕНИ ИЗ РЕЕСТРА — иначе контроль проверял бы функцию,
        а не то, что реестр отдаёт именно её."""
        fn = ca.PROBES[PROBE_NAME]
        return fn(None, now=now or self.now,
                  data_dir=data_dir or str(self.data_dir),
                  repo_root=repo_root or str(self.root))


class TestTheRealInstrumentsCarryTheHalfVerdict(unittest.TestCase):
    """СНАЧАЛА — что настоящие приборы вообще выносят вердикт своей половины.

    Без этого шага всё остальное тавтологично: проба могла бы быть красной от
    чего угодно, а не от того, что критерий владельца не выполнен.
    """

    def test_each_instrument_declares_ITS_OWN_half_anchor(self):
        self.assertTrue(D.CRITERION.startswith("§49 Auditability (половина «snapshot»)"))
        self.assertTrue(
            E.CRITERION.startswith("§49 Auditability (половина «explanation»)"))

    def test_the_two_anchors_are_NOT_interchangeable(self):
        """Прибор о снимке не вправе подписаться мерой объяснения, и наоборот."""
        halves = dict((half, anchor) for half, _m, anchor in ca.AUDITABILITY_HALVES)
        self.assertFalse(D.CRITERION.startswith(halves["explanation"]))
        self.assertFalse(E.CRITERION.startswith(halves["snapshot"]))

    # Две ОТДЕЛЬНЫЕ пробы, а не одна с `subTest`, и это не стиль: утверждение под
    # `subTest` падает ИМЕНЕМ `SUBFAILED`, которого мутационный прибор по дельте не
    # видит (ADR-761, замер #876) — носитель claim оказался бы невидим, и мутация
    # «вердикт больше не кладётся в отчёт» ВЫЖИЛА бы при зелёной батарее. Это и
    # произошло на первом прогоне мутаций ADR-808: 3/16 и 8/16 выжили ровно так.
    def test_run_puts_the_SNAPSHOT_half_verdict_INTO_the_report(self):
        """Вердикт обязан жить в САМОМ отчёте: читатель его переносит (ADR-220).

        Дерево одноразовое и ПУСТОЕ — живое `data/` не открывается. Прибор на нём
        честно отвечает «не измерено», и это ровно тот исход, который
        проверяется: блок есть, и он не притворяется зелёным.
        """
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            doc = D.run(root=tmp, write=False)
        self.assertIn("criterion", doc, "вердикт половины «snapshot» не в отчёте")
        self.assertEqual(doc["criterion"]["status"], D.CRITERION_UNMEASURED,
                         doc["criterion"]["reason"])
        self.assertTrue(doc["criterion"]["reason"])

    def test_run_puts_the_EXPLANATION_half_verdict_INTO_the_report(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            doc = E.run(root=tmp, data_dir=str(Path(tmp) / "data"), write=False)
        self.assertIn("criterion", doc, "вердикт половины «explanation» не в отчёте")
        self.assertEqual(doc["criterion"]["status"], E.CRITERION_UNMEASURED,
                         doc["criterion"]["reason"])
        self.assertTrue(doc["criterion"]["reason"])

    def test_an_empty_population_is_NOT_satisfied_by_construction(self):
        """Ноль перекладок и ноль recommendation — третий исход, а не зелёный."""
        snap = D.criterion_verdict({"population": {"moves": 0,
                                                   "fully_answerable": 0}})
        self.assertEqual(snap["status"], D.CRITERION_UNMEASURED)
        self.assertIn("ПО ПОСТРОЕНИЮ", snap["reason"])
        expl = E.criterion_verdict({
            "control": {"passed": True, "spoken": 8, "expected": 8},
            "facts_total": 8, "books": [{"book": "conservative",
                                         "has_recommendation": False}]})
        self.assertEqual(expl["status"], E.CRITERION_UNMEASURED)
        self.assertIn("ПО ПОСТРОЕНИЮ", expl["reason"])


class TestTheWholeContourAndEveryBrokenLink(_Scene):
    def test_the_whole_contour_is_SATISFIED(self):
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_the_live_measurement_of_25_10_is_reproduced_as_NOT_SATISFIED(self):
        """Обе половины в том виде, в каком их застал замер 25.10."""
        self.build(moves=_LIVE_MOVES, answerable=0,
                   spoken=_LIVE_SPOKEN, tokens=_LIVE_TOKENS)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn(f"восстановимы 0 перекладок из {_LIVE_MOVES}", detail)
        self.assertIn(f"произносится {_LIVE_SPOKEN} из 8", detail)
        self.assertIn(_LIVE_TOKENS[0], detail)

    def test_an_unanswerable_move_is_NOT_SATISFIED_and_the_FIELDS_are_named(self):
        self.build(moves=4, answerable=3)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("восстановимы 3 перекладок из 4", detail)
        self.assertIn("market snapshot", detail)

    def test_a_silent_fact_is_NOT_SATISFIED_and_the_BOOK_is_named(self):
        self.build(spoken=7)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("conservative: произносится 7 из 8", detail)

    def test_a_machine_token_is_NOT_SATISFIED_even_when_all_facts_are_spoken(self):
        """Владелец назвал плохую форму дословно — полнота её не выкупает."""
        self.build(tokens=["utility_score_0_7234"])
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("названная владельцем плохой", detail)
        self.assertIn("utility_score_0_7234", detail)

    def test_zero_moves_is_UNMEASURED_not_green(self):
        self.build(moves=0)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("перекладок в трейле НЕ НАЙДЕНО", detail)

    def test_zero_recommendations_is_UNMEASURED_not_green(self):
        self.build(books_with_rec=0)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не несёт recommendation", detail)

    def test_a_failed_positive_control_is_UNMEASURED_not_silent(self):
        self.build(control_passed=False)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("положительный контроль НЕ ПРОШЁЛ", detail)

    def test_a_missing_denominator_is_UNMEASURED(self):
        self.build(facts_total=None)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("facts_total", detail)

    # Ниже — ПО ОДНОЙ пробе на половину, без `subTest`, и причина та же, что у
    # соседа выше: падение под `subTest` приходит именем `SUBFAILED`, которого
    # мутационный прибор по дельте не видит (ADR-761). Носитель claim обязан быть
    # виден, иначе «мутация убита» неотличимо от «её никто не ловит».
    def test_a_missing_SNAPSHOT_artifact_is_UNMEASURED_with_the_half_named(self):
        self.build(drop=("snapshot",))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("артефакт половины «snapshot»", detail)

    def test_a_missing_EXPLANATION_artifact_is_UNMEASURED_with_the_half_named(self):
        self.build(drop=("explanation",))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("артефакт половины «explanation»", detail)

    def test_a_STALE_snapshot_artifact_is_UNMEASURED_not_green(self):
        """Вчерашний ответ прибора за сегодняшний не выдаётся."""
        self.build(snapshot_age_h=24.0 * 9)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("артефакт половины «snapshot» протух", detail)

    def test_a_STALE_explanation_artifact_is_UNMEASURED_not_green(self):
        self.build(explanation_age_h=24.0 * 9)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("артефакт половины «explanation» протух", detail)

    def test_a_snapshot_threshold_without_a_home_is_UNMEASURED_not_invented(self):
        self.build(snapshot_slo=None)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("срок годности взять неоткуда", detail)

    def test_an_explanation_threshold_without_a_home_is_UNMEASURED_not_invented(self):
        self.build(explanation_slo=None)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("срок годности взять неоткуда", detail)

    def test_an_unparsable_stamp_is_UNMEASURED(self):
        self.build(snapshot_stamp="позавчера")
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("возраст НЕ ИЗМЕРЕН", detail)

    def test_the_blind_spots_are_NAMED_in_every_verdict(self):
        for kwargs in ({}, {"answerable": 0}, {"moves": 0}, {"spoken": 1}):
            with self.subTest(build=kwargs):
                self.build(**kwargs)
                _, detail = self.probe()
                self.assertIn("мера НЕ отвечает", detail)
                self.assertIn("money-path", detail)

    def test_an_argument_is_refused(self):
        verdict, detail = ca.PROBES[PROBE_NAME]("какой-то файл")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не принимает аргумента", detail)


class TestTheConjunctionIsNotCollapsed(_Scene):
    """«snapshot И explanation» — и обе стороны этого правила закреплены."""

    def test_a_MEASURED_failure_survives_an_UNMEASURED_half_alongside(self):
        """Находка не тонет в «не измерено» — инвариант #17 наизнанку.

        Половина «snapshot» ИЗМЕРЕНА невыполненной, половина «explanation» не
        измерена вовсе. Вердикт обязан остаться `not_satisfied`: иначе красное
        владельца исчезало бы из сводки тише, чем от любой правки кода.
        """
        self.build(moves=4, answerable=0, drop=("explanation",))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("конъюнкция", detail)
        self.assertIn("восстановимы 0 перекладок из 4", detail)

    def test_an_UNMEASURED_half_beside_a_SATISFIED_one_is_UNMEASURED(self):
        """Обратная сторона: полнота одной половины за критерий не отвечает."""
        self.build(drop=("snapshot",))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("член неизвестен", detail)
        self.assertIn("«snapshot»", detail)

    def test_EACH_half_alone_can_sink_the_criterion(self):
        """Ни одна половина не декоративна: каждая в одиночку даёт красное."""
        for kwargs, needle in (({"answerable": 0, "moves": 2}, "перекладок из 2"),
                               ({"spoken": 2}, "произносится 2 из 8")):
            with self.subTest(build=kwargs):
                self.build(**kwargs)
                verdict, detail = self.probe()
                self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
                self.assertIn(needle, detail)

    def test_the_probe_does_not_read_overall_at_all(self):
        """Прямой контроль проводки: `overall` подменён на «OK», вердикт не дрогнул."""
        self.build(moves=4, answerable=0)
        path = self.data_dir / Path(D.REPORT_REL).name
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["overall"] = "OK"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)


class TestTheDeclarationIsCheckedByAnchorNotBySubstring(_Scene):
    def _with_module(self, name, stub):
        saved = sys.modules.get(name)
        sys.modules[name] = stub
        self.addCleanup(
            lambda: sys.modules.__setitem__(name, saved) if saved is not None
            else sys.modules.pop(name, None))

    # Без `subTest` намеренно: именно здесь живёт единственный носитель claim
    # «якорь читается как НАЧАЛО строки» (ADR-333), а падение под `subTest`
    # приходит именем `SUBFAILED`, невидимым мутационному прибору (ADR-761) —
    # на первом прогоне мутаций ADR-808 мутация 11/16 именно так и ВЫЖИЛА.
    def _declaring(self, index, text):
        _half, name, anchor = ca.AUDITABILITY_HALVES[index]

        class _Stub:
            CRITERION = text(anchor)
        self._with_module(name, _Stub())
        return self.probe()

    def test_a_SNAPSHOT_instrument_that_declares_nothing_is_UNMEASURED(self):
        verdict, detail = self._declaring(0, lambda _a: "")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_an_EXPLANATION_instrument_that_declares_nothing_is_UNMEASURED(self):
        verdict, detail = self._declaring(1, lambda _a: "")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_SNAPSHOT_anchor_must_START_the_declaration_not_merely_occur(self):
        """Ровно та мутация, которую «есть ли подстрока» пропускает.

        Заметка, где якорь стои́т В СЕРЕДИНЕ, ссылается на критерий, а не
        объявляет себя его мерой.
        """
        verdict, detail = self._declaring(
            0, lambda a: f"подробности про {a} смотри в соседнем ADR")
        self.assertEqual(verdict, ca.UNMEASURED,
                         "якорь прочитан подстрокой: ссылка принята за объявление")
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_EXPLANATION_anchor_must_START_the_declaration_not_merely_occur(self):
        verdict, detail = self._declaring(
            1, lambda a: f"подробности про {a} смотри в соседнем ADR")
        self.assertEqual(verdict, ca.UNMEASURED,
                         "якорь прочитан подстрокой: ссылка принята за объявление")
        self.assertIn("не объявляет себя мерой", detail)

    def test_a_half_that_names_no_artifact_address_is_UNMEASURED(self):
        _half, name, anchor = ca.AUDITABILITY_HALVES[0]

        class _Stub:
            CRITERION = anchor + " — и адреса артефакта нет"
            REPORT_REL = ""
        self._with_module(name, _Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не называет адрес своего артефакта", detail)


class TestFailClosedOnAnythingUnknown(_Scene):
    def _stub(self, half_name, module_name, anchor, *, block, raises=False):
        real = sys.modules[module_name]
        outer = self

        class _Stub:
            CRITERION = anchor + " (заглушка контроля)"
            REPORT_REL = real.REPORT_REL
            CRITERION_SATISFIED = real.CRITERION_SATISFIED
            CRITERION_NOT_SATISFIED = real.CRITERION_NOT_SATISFIED
            CRITERION_UNMEASURED = real.CRITERION_UNMEASURED

            @staticmethod
            def criterion_verdict(doc):
                if raises:
                    raise RuntimeError("прибор упал")
                return block

        saved = sys.modules.get(module_name)
        sys.modules[module_name] = _Stub()
        outer.addCleanup(
            lambda: sys.modules.__setitem__(module_name, saved)
            if saved is not None else sys.modules.pop(module_name, None))

    def test_an_unknown_criterion_status_is_UNMEASURED_not_satisfied(self):
        half, name, anchor = ca.AUDITABILITY_HALVES[0]
        self._stub(half, name, anchor,
                   block={"status": "ЧТО-ТО НОВОЕ", "reason": "…"})
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не переносится", detail)

    def test_a_verdict_that_is_not_an_object_is_UNMEASURED(self):
        half, name, anchor = ca.AUDITABILITY_HALVES[1]
        self._stub(half, name, anchor, block="satisfied")
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объект", detail)

    def test_an_instrument_that_falls_over_is_UNMEASURED(self):
        half, name, anchor = ca.AUDITABILITY_HALVES[0]
        self._stub(half, name, anchor, block=None, raises=True)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("прибор упал", detail)


class TestEveryDoorIsInjected(_Scene):
    """Не «есть ли параметр», а доходит ли он ДО ИСХОДА пробы."""

    def test_the_clock_reaches_the_outcome(self):
        """Тот же материал при сдвинутых часах даёт ДРУГОЙ вердикт."""
        self.assertEqual(self.probe()[0], ca.SATISFIED)
        verdict, detail = self.probe(now=self.now + timedelta(days=30))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_data_dir_reaches_the_outcome(self):
        empty = self.root / "empty"
        empty.mkdir()
        verdict, detail = self.probe(data_dir=str(empty))
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не прочитан", detail)

    def test_repo_root_reaches_the_outcome(self):
        """Конституция живёт в `repo_root`: без неё порог теряет дом."""
        (self.root / "architecture" / "manifest.json").unlink()
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("срок годности", detail)


class TestTheProbeOnlyReads(_Scene):
    def test_the_probe_writes_no_artifact(self):
        before = sorted(p.name for p in self.data_dir.iterdir())
        self.probe()
        self.assertEqual(before, sorted(p.name for p in self.data_dir.iterdir()),
                         "проба тронула каталог артефактов — она уже не только читает")


class TestTheRegistryWiringIsReal(_Scene):
    def test_run_probe_by_name_reaches_the_same_verdict(self):
        """Реестр обязан отдавать ИМЕННО эту пробу и проводить оба дерева.

        Часы `run_probe` не принимает, поэтому сцена выбрана такая, чей ответ от
        сегодняшних часов не зависит: порванное звено, а не срок годности.
        """
        self.build(drop=("snapshot", "explanation"))
        verdict, detail = ca.run_probe(PROBE_NAME, repo_root=str(self.root),
                                       data_dir=str(self.data_dir))
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не прочитан", detail)

    def test_both_tree_inputs_are_DECLARED_by_the_probe(self):
        """Вход, не объявленный пробой, `run_probe` ей не передаёт вовсе."""
        self.assertEqual({"repo_root", "data_dir"},
                         set(ca.probe_tree_inputs(PROBE_NAME)))


class TestTheProbeIsRegisteredAndDeclared(unittest.TestCase):
    def test_it_is_in_the_registry_under_this_exact_name(self):
        self.assertIn(PROBE_NAME, ca.PROBES)

    def test_it_declares_THIS_criterion(self):
        fn = ca._probe_auditability_decision_carries_snapshot_and_explanation
        self.assertEqual(CRITERION, fn.s49_criterion)
        self.assertEqual([PROBE_NAME],
                         ca.probes_by_s49_criterion().get(CRITERION))

    def test_the_declaration_points_INTO_the_population_of_the_live_order(self):
        """Объявление, указывающее мимо §49, есть находка, а не тихий ноль."""
        rollup = _load_rollup()
        card = Path(ca.REPO_ROOT) / rollup.CARD_REL
        if not card.exists():                       # pragma: no cover
            self.skipTest(f"карточка приказа не найдена: {card}")
        names = rollup.parse_s49_criteria(card.read_text(encoding="utf-8"))
        self.assertIn(CRITERION, names)

    def test_the_constitution_binds_the_criterion_to_BOTH_halves(self):
        """Такт входа критерия берётся из конституции, а не выбирается.

        Без привязки `s49_tally_tact` честно отвечает `unbound` — «такт этого
        критерия взять неоткуда», и ADR-808 закрывает ровно это.
        """
        from spa_core.monitoring import s49_criterion_price as price
        parsed = price.parse_bindings(price.read_manifest(str(ca.REPO_ROOT)))
        entries = parsed["bindings"].get(CRITERION) or []
        self.assertEqual({D.REPORT_REL, E.REPORT_REL},
                         {e["path"] for e in entries})
        for entry in entries:
            with self.subTest(path=entry["path"]):
                # Форма — каноническая: `paren`/`quoted` оставляли бы читателя
                # угадывать, и ровно на этом стоял урок ADR-513.
                self.assertEqual(price.CANONICAL_FORM, entry["form"])
                self.assertIsNotNone(entry["slo_hours"])

    def test_the_binding_adds_no_UNPARSED_mention_of_the_section(self):
        """§49, не подошедший ни к одной форме, делает критерий НЕ ИЗМЕРЕННЫМ."""
        from spa_core.monitoring import s49_criterion_price as price
        parsed = price.parse_bindings(price.read_manifest(str(ca.REPO_ROOT)))
        mine = [u for u in parsed["unparsed"]
                if u["path"] in (D.REPORT_REL, E.REPORT_REL)]
        self.assertEqual([], mine, f"неразобранное упоминание §49: {mine}")


def _load_rollup():
    import importlib.util
    path = Path(ca.REPO_ROOT) / "scripts" / "cio_acceptance_rollup.py"
    spec = importlib.util.spec_from_file_location("_cio_rollup_for_auditability", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
