"""Заказ владельца G144 п. 1 (хвост ADR-643/ADR-526), решение ADR-644.

ТРЕТИЙ из перечня непрочитанных производителей находок, названных ADR-526
поимённо, и предпоследний в нём: `data/tracker_status_sentinel.json`.

Предмет. `com.spa.tracker_status_sentinel` написан против аварии 09.08
(карточка `inbox-statusy-kartochek-vladeltsa-perepisalis`): три карточки
owner-gate сменили `status:` сами, живой вопрос владельцу стал `ingested` — то
есть ЗАКРЫЛСЯ БЕЗ ОТВЕТА ВЛАДЕЛЬЦА и исчез из очереди `needs-owner`. Сторож с
тех пор исправно пишет отчёт, и внутри цикла его не читал НИКТО: находка
доезжала только тревогой и ненулевым кодом возврата агента.

Каждый тест — либо положительный контроль формы, ИЗМЕРЕННОЙ у производителя
(`run()` в `spa_core/monitoring/tracker_status_sentinel.py`), либо контроль в
обратную сторону с поимённо порванным звеном. Проверки идут по ИСХОДУ, а не
подстрокой (ADR-333): где сравнивается текст, там рядом сверяется и ЧИСЛО,
различающее сцены, — иначе подмена имени ключа осталась бы невидимой (#786).

Сцены здесь СПЕЦИАЛЬНО уложены так, чтобы быть негодными без проверяемого
звена (заказ G144 п. 3, найденный замером самого же #799): тяжёлая находка
лежит в списке ПОСЛЕДНЕЙ в том самом алфавитном порядке, в котором её кладёт
производитель, поэтому поднять её на первую строку может ТОЛЬКО сортировка.

Литеральных дат нет: часы приходят входом `now=`, отметки сцены вычислены от
якоря.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ARTIFACT = "data/tracker_status_sentinel.json"
BASENAME = ARTIFACT.rsplit("/", 1)[-1]
PRODUCER_AGENT = "com.spa.tracker_status_sentinel"
PRODUCER_SRC = "spa_core/monitoring/tracker_status_sentinel.py"
CYCLE_CONSUMER = "orchestrator_protocol"

# Якорь сцены.
# FROZEN-DATE-OK: injected-clock — ветка выжимки принимает часы
# входом `_summarize_json(..., now=NOW)`, все отметки документов сцены вычислены
# ОТ ЭТОГО ЯКОРЯ, стенных часов в батарее нет ни одних. Якорь намеренно уведён
# от стенных часов на месяцы: совпадение с сегодняшним днём делало бы батарею
# зелёной и тогда, когда ветка часы НЕ принимает.
NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location(
        "_office_probe_tss", REPO / "scripts" / "consume_office_reports.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _calm(**over):
    """Документ в форме, ИЗМЕРЕННОЙ у производителя, состояние «всё объяснено».

    Это ЖИВОЙ замер 08.10 с прод-дерева, а не выдуманная форма: 762 карточки,
    ни одного перехода, находка пуста ЧЕСТНЫМ НУЛЁМ.
    """
    doc = {
        "generated_at": (NOW - dt.timedelta(hours=0.06)).isoformat(),
        "root": "/Users/yuriikulieshov/Documents/SPA_Claude",
        "verdict": "OK",
        "cards_seen": 762,
        "transitions": 0,
        "unattributed": [],
        "attributed": [],
        "critical": 0,
        "warn": 0,
        "unchecked": [],
        "appeared": [],
        "vanished": [],
        "previous_snapshot_at": (NOW - dt.timedelta(hours=1.06)).isoformat(),
    }
    doc.update(over)
    return doc


#: Находка, ради которой заказ назвал артефакт: вопрос владельцу ушёл из
#: `needs-owner` МИМО ПИСАТЕЛЯ. Форма взята у производителя (`attribute()` +
#: `_severity()`), включая оба ключа объяснения `reason`/`detail`.
_OWNER_QUESTION_LOST = {
    "card": "own-site-numbers-owner-gat-3.md",
    "from": "needs-owner",
    "to": "ingested",
    "attributed": False,
    "reason": "no_record",
    "detail": ("в журнале аудита нет ни одной записи об этом переходе, "
               "и след перехода в самой карточке его не объясняет"),
    "severity": "CRITICAL",
}

#: Вторая тяжесть: переход никем не объяснён, но вопрос владельца не терялся.
#: Имя карточки начинается на `agent-` НАМЕРЕННО — алфавитно оно встаёт РАНЬШЕ
#: `own-…`, то есть производитель (он сортирует по имени карточки) положит
#: WARN ПЕРВЫМ, а CRITICAL — последним. Без сортировки по тяжести ветка
#: напечатала бы именно этот порядок, и тест про порядок был бы зелен
#: независимо от звена, которое проверяет (класс «негодной сцены», G144 п. 3).
_SUSPICIOUS = {
    "card": "agent-rates-desk-capacity.md",
    "from": "backlog",
    "to": "in-progress",
    "attributed": False,
    "reason": "chain_mismatch",
    "detail": ("журнал объясняет переход 'new' -> 'backlog', "
               "а в трекере произошёл 'backlog' -> 'in-progress'"),
    "writer": "queue.set_status · pid 48213 · ['orchestrator_queue.py', 'set-status']",
    "severity": "WARN",
}


def _findings(**over):
    """Обе тяжести сразу, в ТОМ ЖЕ порядке, в каком их кладёт производитель."""
    doc = _calm()
    doc.update({
        "verdict": "FINDINGS",
        "transitions": 2,
        "unattributed": [_SUSPICIOUS, _OWNER_QUESTION_LOST],
        "critical": 1,
        "warn": 1,
    })
    doc.update(over)
    return doc


def _no_previous_snapshot(**over):
    """ТРЕТИЙ ИСХОД производителя, и у ЭТОГО сторожа он основной.

    Форма взята из самого производителя: нет предыдущего снимка ⇒ переходы
    измерить не с чем ВООБЩЕ, `unchecked` непуст и вердикт поднимается до
    `UNCHECKED` (fail-CLOSED). `critical: 0` в этом состоянии значит
    «не смотрели», а не «чисто».
    """
    doc = _calm()
    doc.update({
        "verdict": "UNCHECKED",
        "unchecked": ["предыдущего снимка нет — переходы измерить не с чем "
                      "(первый прогон)"],
        "previous_snapshot_at": None,
    })
    doc.update(over)
    return doc


def _lines(doc):
    return _office()._summarize_json(ARTIFACT, doc, now=NOW, root=str(REPO))


def _head(doc):
    return next(ln for ln in _lines(doc) if "вердикт:" in ln)


def _manifest():
    return json.loads((REPO / "architecture" / "manifest.json").read_text())


def _row(manifest=None):
    man = manifest or _manifest()
    return next((a for a in man.get("artifacts") or []
                 if a.get("path") == ARTIFACT), None)


class TheOfficeActuallyReadsTheSentinel(unittest.TestCase):
    """Объявить артефакт и не уметь его разобрать = `ПРОЧИТАН ВХОЛОСТУЮ`."""

    def test_the_branch_exists_so_the_read_is_not_hollow(self):
        o = _office()
        self.assertIn(BASENAME, o._READ_SCHEMA,
                      "без объявления схемы расхождение с производителем "
                      "не измеряется вовсе")
        lines = _lines(_calm())
        # ОБРАТНАЯ СТОРОНА, порванное звено названо: ТОТ ЖЕ документ, поданный
        # под именем без ветки, обязан дать `РАЗОБРАТЬ НЕЧЕМ` — ровно тот
        # `ВХОЛОСТУЮ`, который #797 нашёл на соседнем
        # `artifact_stamp_clock_doors.json`.
        #
        # СРАВНИВАТЬ ЧИСЛО СТРОК ЗДЕСЬ НЕЛЬЗЯ, и это замер, а не осторожность:
        # на спокойном документе и ветка, и заглушка дают РОВНО ДВЕ строки
        # (голова + одна), поэтому `len(lines) > len(hollow)` было зелено от
        # сложения двух разных исходов. Мерить надо ИСХОД.
        hollow = _office()._summarize_json(
            "data/__no_such_branch_exists__.json", _calm(), now=NOW, root=str(REPO))
        self.assertTrue(any("РАЗОБРАТЬ НЕЧЕМ" in ln for ln in hollow),
                        "сцена негодна: заглушка не дала исхода «вхолостую», "
                        "и сравнивать ветку не с чем")
        self.assertFalse(any("РАЗОБРАТЬ НЕЧЕМ" in ln for ln in lines),
                         "артефакт объявлен, а разобрать его нечем — "
                         "чтение вхолостую")
        self.assertTrue(any("карточек" in ln for ln in lines))

    def test_the_verdict_line_carries_both_denominators_and_both_severities(self):
        """«критических 1» без знаменателей не имеет масштаба.

        Их ДВА, и они отвечают на разные вопросы: `переходов` даёт масштаб
        находке, `карточек` отличает тихий трекер от непрочитанного каталога.
        """
        head = _head(_findings())
        for token in ("карточек 762", "переходов 2", "критических 1",
                      "подозрительных 1", "не измерено 0"):
            self.assertIn(token, head, f"в вердикте нет {token!r}")

    def test_a_missing_counter_is_the_third_outcome_not_a_zero(self):
        """Ключа нет ⇒ «НЕ ИЗМЕРЕНО», а не ноль (инв. #17, fail-CLOSED)."""
        o = _office()
        doc = _calm()
        doc.pop("cards_seen")
        doc.pop("critical")
        head = _head(doc)
        self.assertIn(f"карточек {o._UNMEASURED}", head)
        self.assertIn(f"критических {o._UNMEASURED}", head)
        self.assertNotIn("карточек 0", head)
        self.assertNotIn("критических 0", head)
        # СЦЕНА РАЗЛИЧАЕТ: на спокойном документе те же места несут ЧИСЛА.
        calm = _head(_calm())
        self.assertIn("карточек 762", calm)
        self.assertNotEqual(head, calm)


class TheThreeOutcomesStayDistinguishable(unittest.TestCase):
    """Инв. #17: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО."""

    def test_an_unmeasured_run_is_not_reported_as_a_clean_tracker(self):
        """Главный дефект класса: `critical: 0` без предыдущего снимка.

        Оба документа несут `critical: 0` и `warn: 0`. Различить их можно
        ТОЛЬКО по `unchecked` — если ветка его не читает, «не смотрели»
        печатается теми же словами, что «чисто».
        """
        o = _office()
        lines = _lines(_no_previous_snapshot())
        head = next(ln for ln in lines if "вердикт:" in ln)
        self.assertIn(o._UNMEASURED, head)
        self.assertNotIn("все переходы объяснены", head)
        self.assertIn("не измерено 1", head)
        # Причина НАЗВАНА, а не только посчитана: счётчик без имени не
        # разобрать, а разбирать обязан цикл.
        self.assertTrue(any("предыдущего снимка нет" in ln for ln in lines))
        # И сцены ЧИСЛЕННО различимы — иначе подмена имени ключа невидима.
        calm = _head(_calm())
        self.assertIn("не измерено 0", calm)
        self.assertEqual(_no_previous_snapshot()["critical"], _calm()["critical"],
                         "сцена негодна: документы различаются не только "
                         "третьим исходом, и тест прошёл бы по другой причине")

    def test_a_measured_zero_still_reads_as_everything_explained(self):
        head = _head(_calm())
        self.assertIn("все переходы объяснены", head)
        self.assertNotIn(_office()._UNMEASURED, head)

    def test_an_unparsed_producer_verdict_is_its_own_outcome(self):
        """Чужое слово в `verdict` — не «OK» и не находка, а третий исход."""
        o = _office()
        head = _head(_calm(verdict="ЧТО-ТО НОВОЕ"))
        self.assertIn(o._UNMEASURED, head)
        self.assertNotIn("все переходы объяснены", head)

    def test_the_unchecked_list_says_that_it_was_truncated(self):
        """Умолчание об усечении превратило бы перечень в «вот и всё»."""
        doc = _no_previous_snapshot(
            unchecked=[f"нечитаемая карточка — card-{i}.md: boom" for i in range(7)])
        self.assertTrue(any("ещё 3 неизмеренных не напечатано" in ln
                            for ln in _lines(doc)))


class TheFindingItselfReachesTheCycle(unittest.TestCase):
    def test_the_lost_owner_question_is_named_by_card_and_transition(self):
        """Счётчик без имён не разобрать — печатаются карточка и переход."""
        lines = _lines(_findings())
        line = next(ln for ln in lines if _OWNER_QUESTION_LOST["card"] in ln)
        self.assertIn("CRITICAL", line)
        self.assertIn("needs-owner -> ingested", line)
        self.assertIn("НЕАТРИБУТИРОВАН", line)

    def test_the_heaviest_finding_is_printed_before_the_merely_suspicious(self):
        """Порядок — порядок ТЯЖЕСТИ, а не порядок списка производителя.

        СЦЕНА ОБЯЗАНА РАЗЛИЧАТЬ (класс G144 п. 3): производитель сортирует
        находки ПО ИМЕНИ КАРТОЧКИ, и в этой сцене WARN (`agent-…`) стоит
        алфавитно РАНЬШЕ CRITICAL (`own-…`), то есть лежит в списке первым.
        Поднять тяжёлую находку на первую строку может только сортировка —
        снятие её даёт обратный порядок и красный тест.
        """
        doc = _findings()
        self.assertEqual(doc["unattributed"][0]["severity"], "WARN",
                         "сцена негодна: тяжёлая находка и так лежит первой, "
                         "тест был бы зелен независимо от сортировки")
        # Строка ВЕРДИКТА исключена намеренно: слово «НЕАТРИБУТИРОВАННЫЕ» стоит
        # и в ней, поэтому фильтр по подстроке ловил её первой и тест падал на
        # собственной неряшливости, а не на порядке (замер этого цикла).
        found = [ln for ln in _lines(doc)
                 if "НЕАТРИБУТИРОВАН (" in ln and "вердикт:" not in ln]
        self.assertEqual(len(found), 2, "сцена негодна: находок напечатано "
                                        "не две, и порядок сравнивать не с чем")
        self.assertIn("CRITICAL", found[0])
        self.assertIn(_OWNER_QUESTION_LOST["card"], found[0])
        self.assertIn("WARN", found[1])

    def test_the_nearest_audit_record_is_named_when_the_producer_has_one(self):
        """`chain_mismatch` без ближайшей записи не разобрать: это ЕДИНСТВЕННЫЙ
        след писателя, и без него находка читается как «кто-то когда-то»."""
        lines = _lines(_findings())
        self.assertTrue(any("ближайшая запись журнала" in ln
                            and "pid 48213" in ln for ln in lines))

    def test_a_card_that_vanished_entirely_reaches_the_cycle(self):
        """Производитель не считает пропажу ни в `transitions`, ни в находках,
        а его собственная печать `vanished` не выводит ВОВСЕ — значит эта ветка
        единственный путь, которым полное исчезновение вопроса владельцу
        доезжает до читателя."""
        doc = _calm(vanished=["own-kill-switch-porogi.md"])
        lines = _lines(doc)
        self.assertTrue(any("ПРОПАЛА КАРТОЧКА ЦЕЛИКОМ" in ln
                            and "own-kill-switch-porogi.md" in ln for ln in lines))
        # Контроль сцены: на спокойном документе такой строки нет, иначе тест
        # был бы зелен независимо от чтения `vanished`.
        self.assertFalse(any("ПРОПАЛА КАРТОЧКА" in ln for ln in _lines(_calm())))

    def test_a_long_vanished_list_says_that_it_was_truncated(self):
        doc = _calm(vanished=[f"own-card-{i}.md" for i in range(9)])
        self.assertTrue(any("ещё 3 пропавших не напечатано" in ln
                            for ln in _lines(doc)))

    def test_a_long_finding_list_says_that_it_was_truncated(self):
        doc = _findings(unattributed=[dict(_SUSPICIOUS, card=f"agent-{i}.md")
                                      for i in range(8)], warn=8, critical=0)
        self.assertTrue(any("ещё 2 находок не напечатано" in ln
                            for ln in _lines(doc)))


class TheAgeIsMeasuredNotFalselyUnmeasured(unittest.TestCase):
    def test_the_producer_writes_generated_at_so_no_second_home_is_declared(self):
        """Строки `_TS_FIELD` здесь нет, и это ЗАМЕР, а не забывчивость.

        Производитель пишет `generated_at` — ровно то поле, которое
        `_produced_at` берёт умолчанием. Строка была бы ВТОРЫМ ДОМОМ той же
        величины (урок ADR-513): два объявления об одном поле расходятся молча,
        а выигрыша нет. Проверяем ИСХОД — возраст измерен, — а не наличие
        строки.
        """
        o = _office()
        self.assertNotIn(BASENAME, o._TS_FIELD,
                         "объявлен второй дом отметки времени, которую "
                         "читатель и так берёт умолчанием")
        head = _lines(_calm())[0]
        self.assertIn("возраст", head)
        self.assertNotIn(o._UNMEASURED, head)

    def test_the_producers_timestamp_key_is_really_the_default_one(self):
        """Контроль самой претензии выше: умолчание и поле производителя — одно
        и то же имя. Разойдись они — возраст был бы «НЕ ИЗМЕРЕН» по построению,
        и отсутствие строки `_TS_FIELD` стало бы дефектом, а не бережливостью.
        """
        o = _office()
        self.assertEqual(o._produced_at(BASENAME, _calm()),
                         _calm()["generated_at"])
        # ОБРАТНАЯ СТОРОНА, звено названо: производитель переименовал поле ⇒
        # возраст обязан стать третьим исходом, а не подставиться нулём.
        # Сверяется формулировка читателя («возраст НЕ ИЗМЕРЕН», мужской род),
        # а не константа `_UNMEASURED` — она про счётчики, и подстановка её
        # здесь роняла бы тест на падеже, а не на исходе (замер этого цикла).
        doc = _calm()
        doc["ts"] = doc.pop("generated_at")
        head = o._summarize_json(ARTIFACT, doc, now=NOW, root=str(REPO))[0]
        self.assertIn("возраст НЕ ИЗМЕРЕН", head)
        self.assertNotIn("возраст 0", head)


class TheSchemaWasMeasuredAtTheProducer(unittest.TestCase):
    """Перечень вымерен у производителя, а не списан с живого файла."""

    def test_every_declared_key_is_actually_written_by_the_producer(self):
        o = _office()
        declared = set(o._READ_SCHEMA[BASENAME])
        tree = ast.parse((REPO / PRODUCER_SRC).read_text())
        written = {k.value for node in ast.walk(tree)
                   if isinstance(node, ast.Dict)
                   for k in node.keys
                   if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        missing = sorted(declared - written)
        self.assertEqual(missing, [],
                         f"объявлено как читаемое, но производитель не пишет: {missing}")

    def test_the_producer_is_declared_so_divergence_is_measurable(self):
        """Без `_PRODUCER` расхождение схемы стало бы «НЕ ИЗМЕРЕНО»."""
        o = _office()
        self.assertEqual(o._PRODUCER.get(BASENAME), PRODUCER_SRC)
        # Рвать надо КЛЮЧ, а не значение: `critical: None` — ключ на месте, и
        # расхождения схемы тут нет по определению (это другой вопрос —
        # вырожденное значение, его ловит тест про третий исход).
        torn = _calm()
        torn.pop("critical")
        gap = o._schema_drift(BASENAME, torn, root=str(REPO))
        self.assertTrue(gap, "порванная схема не дала ни одной строки")
        self.assertFalse(any(o._UNMEASURED in ln for ln in gap),
                         "производитель объявлен, а расхождение всё равно "
                         "объявлено неизмеренным")


class TheConstitutionDeclaresTheCycleAsConsumer(unittest.TestCase):
    def test_the_row_exists_active_and_names_the_cycle(self):
        row = _row()
        self.assertIsNotNone(row, "строки artifacts[] нет — вердикт переписи "
                                  "не станет read_by_the_cycle")
        self.assertEqual(row["status"], "active")
        self.assertIn(CYCLE_CONSUMER, row["consumers"])
        self.assertEqual(row["producer"], PRODUCER_AGENT)

    def test_the_slo_is_taken_from_the_producer_not_chosen(self):
        """Второй дом порога — урок ADR-513: расхождение двух объявлений об
        ОДНОМ файле молчит. Здесь оно особенно соблазнительно: такт агента 1 ч,
        а объявленный срок годности 168 ч, и «очевидное» число было бы НЕ ТЕМ.
        """
        man = _manifest()
        agent = next(a for a in man["agents"] if a.get("label") == PRODUCER_AGENT)
        produced = next(p for p in agent["produces"]
                        if p.get("artifact") == ARTIFACT)
        self.assertEqual(_row(man)["slo_hours"], produced["slo_hours"])


class TheCensusVerdictActuallyMoves(unittest.TestCase):
    """Приёмка по ИСХОДУ: перепись обязана перестать звать находку непрочитанной."""

    #: Сцена ОБЕСПЕЧИВАЕТ СВОЮ ПРЕДПОСЫЛКУ, а не берёт её у хоста. Нога
    #: писателя у переписи спрашивается ПЕРВОЙ и спрашивается у НАБЛЮДЕНИЯ:
    #: без свежего артефакта в каталоге данных вердикт будет `writer_silent`,
    #: и о читателе перепись не скажет НИЧЕГО. Живое прод-`data/` для этого
    #: брать нельзя — из worktree его нет по построению, и тест судил бы о
    #: чужой машине.
    def _measure(self, manifest):
        import tempfile
        from spa_core.monitoring import finding_reader_census as frc
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            (data / BASENAME).write_text(json.dumps(_findings()))
            res = frc.measure(REPO, data_dir=data, manifest=manifest, now=NOW)
        rows = res.get("rows") or []
        row = next((r for r in rows if r.get("artifact") == ARTIFACT), None)
        # Громкий отказ вместо тихого «не тот исход»: предпосылку надо
        # проверять, а не предполагать (урок #752–#754 про негодную сцену).
        if row is not None and str(row.get("verdict")).startswith("writer_"):
            raise AssertionError(
                f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: перепись считает писателя "
                f"молчащим ({row.get('verdict')}) и о читателе не судит вовсе")
        return row

    def test_the_pair_is_now_read_by_the_cycle(self):
        row = self._measure(_manifest())
        self.assertIsNotNone(row, "пары нет в населении — производитель не "
                                  "объявляет артефакт в produces")
        self.assertEqual(row.get("verdict"), "read_by_the_cycle")

    def test_the_shape_is_the_acute_one_that_the_order_named(self):
        """Форма ОСТРАЯ — артефакт НЕСЁТ НАХОДКИ, а не просто состояние.
        Ровно этим признаком ADR-526 отобрал перечень из пяти."""
        self.assertEqual(self._measure(_manifest()).get("shape"),
                         "finding_key_present")

    def test_tearing_the_artifacts_row_drops_it_to_the_weaker_outcome(self):
        """ОБРАТНАЯ СТОРОНА, звено названо: строка `artifacts[]` удалена.

        Ожидание здесь ИЗМЕРЕНО, а не выведено: в доставляемом дереве ветка
        выжимки САМА является читателем в коде, поэтому снятие одного
        объявления возвращает пару не в острую форму, а в соседнюю, слабее.
        Разница существенная: ADR-526 говорит, что объявление не есть чтение,
        но верно и обратное — чтение в коде не есть объявление, и выдавать
        «цикл читает» за него нельзя. Острую форму возвращает только ДВОЙНОЙ
        разрыв (следующий тест).
        """
        man = _manifest()
        man["artifacts"] = [a for a in man["artifacts"] if a.get("path") != ARTIFACT]
        self.assertEqual(self._measure(man).get("verdict"),
                         "read_in_code_by_another_module")

    def test_tearing_both_the_row_and_the_branch_returns_the_acute_form(self):
        """Двойной разрыв: нет ни объявления, ни читателя в коде ⇒ находка
        снова непрочитана. Это и есть то состояние, которое заказ застал."""
        import shutil
        import tempfile
        from spa_core.monitoring import finding_reader_census as frc
        man = _manifest()
        man["artifacts"] = [a for a in man["artifacts"] if a.get("path") != ARTIFACT]
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "tree"
            # Одноразовая копия дерева БЕЗ ветки выжимки: живое дерево не
            # трогается, а предмет замера — именно отсутствие читателя.
            shutil.copytree(REPO / "spa_core", tree / "spa_core",
                            ignore=shutil.ignore_patterns("tests", "__pycache__"))
            (tree / "scripts").mkdir(parents=True)
            (tree / "data").mkdir()
            (tree / "data" / BASENAME).write_text(json.dumps(_findings()))
            (tree / "scripts" / "consume_office_reports.py").write_text(
                "# ветка выжимки намеренно отсутствует в этой копии\n")
            res = frc.measure(tree, data_dir=tree / "data", manifest=man, now=NOW)
        row = next((r for r in (res.get("rows") or [])
                    if r.get("artifact") == ARTIFACT), None)
        self.assertIsNotNone(row)
        self.assertEqual(row.get("verdict"), "no_reader_found")
        self.assertEqual(row.get("shape"), "finding_key_present")

    def test_tearing_the_cycle_from_consumers_returns_it_too(self):
        """Строка есть, а цикла в `consumers` нет — объявление не о том
        читателе. Проверка по ИСХОДУ, не по наличию строки."""
        man = _manifest()
        _row(man)["consumers"] = []
        self.assertNotEqual(self._measure(man).get("verdict"), "read_by_the_cycle")

    def test_a_retired_row_does_not_count_as_a_reader(self):
        man = _manifest()
        _row(man)["status"] = "retired"
        self.assertNotEqual(self._measure(man).get("verdict"), "read_by_the_cycle")


if __name__ == "__main__":
    unittest.main()
