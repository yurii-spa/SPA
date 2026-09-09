"""«В отчёте нет блока X» — находка только после того, как производитель отработал.

ЗАКАЗ ЦИКЛА #527, исполненный циклом #528. Класс «форму контроля применили к
ПОВОДУ, а не ко всему классу» закрывали ТРИ раза подряд — ADR-261 (файла нет на
диске), ADR-262 (второй читатель того же), ADR-264 (предмет сменился), — и
каждый раз ровно там, где нашлось. Заказ требовал спросить о классе целиком:
перечислить ВСЕ печати шага 0-офис, зовущие читателя действовать, и измерить у
каждой достижимость третьего исхода «производитель ещё не должен был».

ЛОВУШКА ЗАКАЗА ОБОЙДЕНА БУКВАЛЬНО. «Строка содержит слово находка» населением
не является — находка бывает и верной. Население меряет
`spa_core/tests/_finding_tick_census.py` по ФОРМЕ: печать со значком действия,
стоящая под сторожем «блока нет в отчёте». Замер на `origin/main` 4f793d704:
49 печатей со значком, из них ПЯТНАДЦАТЬ — этого класса, и НИ ОДНА не
спрашивала производителя ни о чём. Пять из пятнадцати при этом ПРОТИВОРЕЧИЛИ
соседней строке того же прогона: `_schema_drift` объявляет те же ключи и
отвечает о них иначе.

Здесь — положительные контроли на все пять дверей вердикта, ратчет населения и
живой дифференциал на настоящей конституции.

Календарь хоста ни на один вердикт здесь не влияет: якорь — литерал
`dt.datetime(2030, 1, 1, 12, 0)`, от него ПРОИЗВОДНЫ обе отметки, и обе уходят
ПАРАМЕТРОМ в проверяемый код (`_block_absent_is_a_finding(..., art_ts=, now=)`,
`_summarize_json(..., now=)`), а время правки исходника производителя задаётся
`os.utime` в песочнице. Ни одна дверь вердикта не спрашивает стенные часы.
"""

# FROZEN-DATE-OK: injected-clock — якорь `dt.datetime(2030, 1, 1, 12, 0)`,
# обе отметки от него производны и передаются параметрами `now=` и `art_ts=`
# в `_block_absent_is_a_finding` / `_summarize_json`; время правки исходника
# производителя ставится `os.utime` в песочнице. Стенных часов нет ни в одной
# сцене — сдвиг календаря вердикта не меняет.

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "consume_office_reports.py"

_spec = importlib.util.spec_from_file_location("_c528_office", SCRIPT)
office = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(office)

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from spa_core.tests import _finding_tick_census as census  # noqa: E402

UTC = dt.timezone.utc

# ── Ратчет населения ────────────────────────────────────────────────────────
#
# Печати класса, у которых значок ВБИТ литералом, — и причина, почему это не
# дефект. База может ТОЛЬКО УМЕНЬШАТЬСЯ (тот же порядок, что у
# `frozen_date_baseline.json`); дописывать сюда, чтобы погасить падение,
# ЗАПРЕЩЕНО — это ровно то, ради чего ратчет существует.
LITERAL_MARK_ALLOWED = {
    "🔴 РЕЦИДИВ": (
        "Утверждение строки — про `recurrences_total` (он ИЗМЕРЕН и не пуст), "
        "а не про отсутствующий рядом `recurrence_liveness`: находка верна "
        "независимо от такта производителя, и третьего исхода у неё нет ПО "
        "ПРИРОДЕ предмета. Соседняя строка того же блока — про сам пропавший "
        "ключ — проведена через `_absent_block`."),
}

# Печати класса, у которых сторож разобрать не удалось. Третий исход самой
# ПЕРЕПИСИ: не выпадать молча, а называться. Тоже только уменьшается.
#
# Ключ — ЛИЧНОСТЬ площадки (функция + текст печати), а НЕ номер строки. Номер —
# координата, которая едет от любой вставки выше по файлу, и освобождение,
# привязанное к ней, краснеет на здоровом коде по причине, не имеющей отношения
# к предмету. Замер #534: проводка ADR-271 дописала в `consume_office_reports.py`
# 16 строк выше по файлу, обе площадки уехали 2386→2402 и 2387→2403, и сторож
# объявил дефектом ДВЕ печати, которых никто не трогал (текст обеих совпадает
# дословно с контрольным деревом того же sha). Тот же класс, что литеральная
# дата и литеральный pid — `.claude/rules/deployment.md`: якорем берётся то, что
# ЯВЛЯЕТСЯ предметом, а не то, что рядом с ним лежало.
UNRESOLVED_GUARD_ALLOWED: dict[tuple[str, str], str] = {
    ("_summarize_json", "латентность : в отчёте нет —"):
        "ключ латентности приходит из цикла (`for key, label in (...)`) — литералом не разбирается",
    ("_summarize_json", "—"):
        "то же место, вторая строка пары",
}


def _sandbox(tmp: Path, artifact: str, *, source_text: str | None = None) -> Path:
    """Дерево с настоящей конституцией и КОПИЕЙ исходника производителя."""
    root = tmp / "tree"
    (root / "architecture").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "architecture" / "manifest.json",
                root / "architecture" / "manifest.json")
    rel = office._PRODUCER[artifact]
    (root / os.path.dirname(rel)).mkdir(parents=True, exist_ok=True)
    if source_text is None:
        shutil.copy(REPO / rel, root / rel)
    else:
        (root / rel).write_text(source_text, encoding="utf-8")
    return root


def _touch(root: Path, artifact: str, when: dt.datetime) -> None:
    rel = office._PRODUCER[artifact]
    os.utime(root / rel, (when.timestamp(), when.timestamp()))


class Doors(unittest.TestCase):
    """Пять дверей вердикта — каждая достижима и говорит СВОИМИ словами."""

    ART = "loop_retro.json"
    KEY = "outcomes_completeness"

    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.now = dt.datetime(2030, 1, 1, 12, 0, tzinfo=UTC)   # инъектированные часы
        self.art_ts = self.now - dt.timedelta(hours=2)

    def _verdict(self, root, *, art_ts=..., now=..., artifact=None, key=None):
        return office._block_absent_is_a_finding(
            artifact or self.ART, key or self.KEY, root=str(root),
            art_ts=self.art_ts if art_ts is ... else art_ts,
            now=self.now if now is ... else now)

    def test_producer_not_declared_is_a_loud_finding(self):
        """Спросить не у кого ⇒ находка с названной причиной, не молчание."""
        found, why = self._verdict(self.tmp, artifact="нет-такого.json")
        self.assertTrue(found)
        self.assertIn("_PRODUCER", why)

    def test_unreadable_source_is_a_loud_finding(self):
        root = _sandbox(self.tmp, self.ART, source_text="def (((")
        found, why = self._verdict(root)
        self.assertTrue(found)
        self.assertIn("не прочитан/не разобран", why)

    def test_key_the_producer_never_writes_is_a_finding(self):
        """Ключа нет в исходнике ⇒ никакой такт его не допишет."""
        root = _sandbox(self.tmp, self.ART, source_text="X = 1\n")
        found, why = self._verdict(root)
        self.assertTrue(found)
        self.assertIn("НЕ ПИШЕТ", why)

    def test_report_newer_than_the_code_is_a_finding(self):
        """Производитель уже отработал с этим кодом и блока не написал."""
        root = _sandbox(self.tmp, self.ART)
        _touch(root, self.ART, self.art_ts - dt.timedelta(hours=1))
        found, why = self._verdict(root)
        self.assertTrue(found)
        self.assertIn("уже отработал", why)

    def test_tick_not_due_is_NOT_a_finding(self):
        """ТРЕТИЙ ИСХОД: следующий прогон допишет блок сам."""
        root = _sandbox(self.tmp, self.ART)
        _touch(root, self.ART, self.art_ts + dt.timedelta(hours=1))
        found, why = self._verdict(root)          # такт 6ч, отчёту 2ч
        self.assertFalse(found)
        self.assertIn("снимет строку сам", why)

    def test_tick_overrun_is_a_finding(self):
        root = _sandbox(self.tmp, self.ART)
        _touch(root, self.ART, self.art_ts + dt.timedelta(hours=1))
        found, why = self._verdict(root, now=self.art_ts + dt.timedelta(hours=9))
        self.assertTrue(found)
        self.assertIn("ПРОСРОЧИЛ", why)

    def test_undatable_report_is_a_loud_finding(self):
        root = _sandbox(self.tmp, self.ART)
        _touch(root, self.ART, self.art_ts + dt.timedelta(hours=1))
        found, why = self._verdict(root, art_ts=None)
        self.assertTrue(found)
        self.assertIn("нечем датировать", why)

    def test_the_verdict_flips_in_BOTH_directions_on_one_scene(self):
        """Дифференциал: одна сцена, два `now` — два разных вердикта."""
        root = _sandbox(self.tmp, self.ART)
        _touch(root, self.ART, self.art_ts + dt.timedelta(hours=1))
        early, _ = self._verdict(root, now=self.art_ts + dt.timedelta(hours=2))
        late, _ = self._verdict(root, now=self.art_ts + dt.timedelta(hours=9))
        self.assertEqual((early, late), (False, True))


class MarkAndWordsAgree(unittest.TestCase):
    """Значок и слова — ОДНО следствие одного вердикта (урок #527)."""

    def test_finding_mark_is_the_only_home_of_the_symbol(self):
        self.assertEqual(office._finding_mark(True), "⚠️")
        self.assertEqual(office._finding_mark(False), "⏳")

    def test_drift_words_derive_their_symbol_from_the_same_place(self):
        for flag in (True, False):
            mark, words = office._drift_words(flag)
            self.assertEqual(mark, office._finding_mark(flag))
            self.assertEqual("НЕ находка" in words, not flag)

    def test_not_a_finding_never_calls_for_a_card(self):
        """Обратная сторона: `⏳` не имеет права звать заводить карточку."""
        tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        now = dt.datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
        art_ts = now - dt.timedelta(hours=2)
        root = _sandbox(tmp, "loop_retro.json")
        _touch(root, "loop_retro.json", art_ts + dt.timedelta(hours=1))
        doc = {"generated_at": art_ts.isoformat()}
        mark, why = office._absent_block("loop_retro.json", doc,
                                         "outcomes_completeness",
                                         root=str(root), now=now)
        self.assertEqual(mark, "⏳")
        self.assertNotIn("находка", why)


class SchemaDriftNamesTheCauseItMeasured(unittest.TestCase):
    """Две РАЗНЫЕ причины расхождения — два разных текста (дефект #528)."""

    def _drift(self, tmp, *, source_text=None, code_before_report: bool):
        art = "loop_retro.json"
        root = _sandbox(tmp, art, source_text=source_text)
        art_ts = dt.datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
        _touch(root, art, art_ts + (dt.timedelta(hours=-1) if code_before_report
                                    else dt.timedelta(hours=1)))
        doc = {"generated_at": art_ts.isoformat(), "findings": []}
        return "\n".join(office._schema_drift(art, doc, root=str(root)))

    def test_producer_that_really_never_writes_it_is_named_so(self):
        tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        text = self._drift(tmp, source_text="X = 1\n", code_before_report=True)
        self.assertIn("СХЕМА РАЗОШЛАСЬ", text)
        self.assertIn("не пишет", text)

    def test_producer_that_DOES_write_it_is_not_accused_of_the_opposite(self):
        """Прежняя редакция обвиняла производителя в том, чего он не делал."""
        tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        text = self._drift(tmp, code_before_report=True)
        self.assertIn("СХЕМА РАЗОШЛАСЬ", text)
        self.assertIn("ПИШЕТ", text)
        self.assertNotIn("не пишет", text)

    def test_old_report_is_still_not_a_finding(self):
        """Прежний исход #248 не тронут: отчёт старее кода — не находка."""
        tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        text = self._drift(tmp, code_before_report=False)
        self.assertIn("СТАРОГО ОБРАЗЦА", text)
        self.assertNotIn("СХЕМА РАЗОШЛАСЬ", text)


class LiveWiring(unittest.TestCase):
    """Проводка мерится у ПОТРЕБИТЕЛЯ — в самой выжимке, а не у помощника."""

    ART = "loop_retro.json"
    KEY = "outcomes_completeness"

    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = _sandbox(self.tmp, self.ART)
        self.art_ts = dt.datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
        _touch(self.root, self.ART, self.art_ts + dt.timedelta(hours=1))
        self.doc = {"generated_at": self.art_ts.isoformat(), "findings": []}

    def _line(self, now):
        lines = office._summarize_json(
            f"data/{self.ART}", self.doc, now=now,
            root=str(self.root), artifact_root=str(self.root))
        found = [l for l in lines if "полнота архива исходов" in l]
        self.assertEqual(len(found), 1, lines)
        return found[0]

    def test_the_office_line_flips_with_the_tick(self):
        early = self._line(self.art_ts + dt.timedelta(hours=2))
        late = self._line(self.art_ts + dt.timedelta(hours=9))
        self.assertIn("⏳", early)
        self.assertIn("⚠️", late)

    def test_the_claim_itself_is_printed_in_BOTH_outcomes(self):
        """Меняется КЛАССИФИКАЦИЯ, а не утверждение (принцип ADR-264)."""
        for hours in (2, 9):
            line = self._line(self.art_ts + dt.timedelta(hours=hours))
            self.assertIn("НЕ ИЗМЕРЕНО", line)
            self.assertIn("outcomes_completeness", line)

    def test_owner_decision_pending_has_a_producer_at_all(self):
        """Дыра #528: у ПЯТИ печатей спросить было не у кого."""
        self.assertIn("owner_decision_pending.json", office._PRODUCER)
        rel = office._PRODUCER["owner_decision_pending.json"]
        keys = office._source_keys(str(REPO / rel))
        self.assertIsNotNone(keys)
        for block in ("origin_queue", "branch_queue", "accepted",
                      "closed_on_origin_open_here", "channel_buttons"):
            self.assertIn(block, keys, block)


class CensusRatchet(unittest.TestCase):
    """Класс спрошен ЦЕЛИКОМ и не имеет права расти молча."""

    def setUp(self):
        self.rows = census.self_clearing_sites(str(SCRIPT))

    def test_the_population_is_not_empty(self):
        """Пустая перепись прошла бы любой ратчет — это не приёмка, а тишина."""
        self.assertGreaterEqual(len(self.rows), 20, self.rows)

    def test_every_resolved_site_routes_its_symbol_through_the_verdict(self):
        offenders = [e for e in self.rows
                     if e.kind == census.LITERAL
                     and not any(k in e.text for k in LITERAL_MARK_ALLOWED)]
        self.assertEqual(offenders, [], (
            "печать со сторожем «блока нет» держит значок ЛИТЕРАЛОМ — третий "
            "исход у неё недостижим по построению. Провести через "
            "`_absent_block`, а не дописывать в базу: " + repr(offenders)))

    def test_every_unresolved_guard_is_named(self):
        unresolved = [e for e in self.rows if e.guard_unresolved]
        unnamed = [(e.func, e.line, e.text) for e in unresolved
                   if (e.func, e.text) not in UNRESOLVED_GUARD_ALLOWED]
        self.assertEqual(unnamed, [], (
            "сторож формой говорит «блока нет», а какого — не разобрано, и "
            "причина не названа: " + repr(unnamed)))

    def test_the_exemption_covers_no_MORE_sites_than_it_names(self):
        """Обратный контроль к перевязке ключа (#534) — и он обязателен.

        Личность площадки прочнее номера строки, но НЕ уникальна: вторая строка
        пары — это «—», текст, который в этом файле ничего не стоит завести
        повторно. Освобождение по (функция, текст) накрыло бы дубль МОЛЧА, и
        сторож замолчал бы ровно от той правки, ради которой написан, — то есть
        перевязка ключа без этой сцены была бы ослаблением, а не починкой.
        Поэтому население класса считается поимённо.
        """
        unresolved = [e for e in self.rows if e.guard_unresolved]
        self.assertEqual(
            len(unresolved), len(UNRESOLVED_GUARD_ALLOWED),
            "освобождённых площадок должно быть ровно столько, сколько названо; "
            "лишняя — это НОВАЯ неразобранная печать, накрытая чужим текстом: "
            + repr([(e.func, e.line, e.text) for e in unresolved]))

    def test_the_census_says_UNMEASURED_instead_of_going_quiet(self):
        """Третий исход самой переписи: не разобрал ⇒ громко."""
        rows = census.census(str(REPO / "docs" / "STATE.md"))
        self.assertEqual([e.kind for e in rows], [census.UNMEASURED])
        self.assertIn("не прочитан/не разобран", rows[0].why)

    # ── Положительные контроли САМОЙ переписи ───────────────────────────
    #
    # Оба написаны по ВЫЖИВШИМ мутантам батареи #528, и оба выживших были
    # настоящим дефектом покрытия, причём в направлении fail-OPEN: перепись
    # начинала считать проведённым то, что проведено не было, — и ратчет
    # выше замолкал, не покраснев ни разу. Тише красной строки, потому
    # опаснее (тот же урок, что дали два выживших мутанта #527).

    def _census_of(self, body: str):
        tmp = Path(__import__("tempfile").mkdtemp(prefix="c528_cens_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = tmp / "subject.py"
        src.write_text(body, encoding="utf-8")
        return {e.line: e for e in census.census(str(src))}

    def test_a_substitution_alone_is_not_wiring(self):
        """ВЫЖИВШИЙ #13: «в строке есть {…}» зачло бы за развилку всё подряд."""
        rows = self._census_of(
            "def f(name, data, out):\n"
            "    blk = data.get('blk')\n"
            "    if blk is None:\n"
            "        out.append(f'   нет блока {name} — {blk}')\n")
        emitted = [e for e in rows.values() if e.absent_key == "blk"]
        self.assertEqual(len(emitted), 1, rows)
        self.assertNotEqual(emitted[0].kind, census.GATED, (
            "подстановка без выдатчика значка проведением НЕ является"))

    def test_a_symbol_taken_from_the_verdict_IS_wiring(self):
        """Обратный контроль к предыдущему: иначе сцена красила бы всё."""
        rows = self._census_of(
            "def f(name, data, out):\n"
            "    blk = data.get('blk')\n"
            "    if blk is None:\n"
            "        mark, why = _absent_block(name, data, 'blk')\n"
            "        out.append(f'   {mark} нет блока — {why}')\n")
        emitted = [e for e in rows.values() if e.absent_key == "blk"]
        self.assertEqual(len(emitted), 1, rows)
        self.assertEqual(emitted[0].kind, census.GATED)

    def test_a_name_bound_twice_is_UNRESOLVED_not_the_last_binding(self):
        """ВЫЖИВШИЙ #15: последнее связывание дало бы уверенно НЕВЕРНЫЙ блок."""
        rows = self._census_of(
            "def f(name, data, out):\n"
            "    d = data.get('alpha')\n"
            "    if not isinstance(d, dict):\n"
            "        out.append('   ⚠️ нет блока alpha')\n"
            "    d = data.get('beta')\n"
            "    if not isinstance(d, dict):\n"
            "        out.append('   ⚠️ нет блока beta')\n")
        keys = sorted({e.absent_key for e in rows.values() if e.absent_key})
        self.assertEqual(keys, [census.UNRESOLVED], rows)

    def test_a_name_bound_once_resolves_to_its_block(self):
        """Обратный контроль: без него предыдущая сцена прошла бы и на «всегда UNRESOLVED»."""
        rows = self._census_of(
            "def f(name, data, out):\n"
            "    d = data.get('alpha')\n"
            "    if not isinstance(d, dict):\n"
            "        out.append('   ⚠️ нет блока alpha')\n")
        keys = sorted({e.absent_key for e in rows.values() if e.absent_key})
        self.assertEqual(keys, ["alpha"], rows)

    # ── Контроли перевязки ключа освобождения (#534) ────────────────────
    #
    # Правка существующего теста допустима только с обоснованием и замером
    # (инв. #16). Обоснование — выше, у самой базы; замер — эти три сцены:
    # освобождение обязано остаться РОВНО таким же строгим, каким было, и
    # отличаться только тем, что переживает вставку строк выше по файлу.

    def _unresolved_of(self, body: str):
        tmp = Path(__import__("tempfile").mkdtemp(prefix="c534_unres_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = tmp / "subject.py"
        src.write_text(body, encoding="utf-8")
        return [e for e in census.self_clearing_sites(str(src))
                if e.guard_unresolved]

    #: Две площадки класса, отличающиеся ТОЛЬКО номером строки: во второй
    #: копии добавлена строка выше. Именно эта разница красила сторожа до #534.
    _TWICE_BOUND = ("def f(name, data, out):\n"
                    "    d = data.get('alpha')\n"
                    "    if not isinstance(d, dict):\n"
                    "        out.append('   ⚠️ нет блока alpha')\n"
                    "    d = data.get('beta')\n"
                    "    if not isinstance(d, dict):\n"
                    "        out.append('   ⚠️ нет блока beta')\n")

    def test_the_identity_of_a_site_survives_an_insertion_above_it(self):
        """Предмет находки #534: та же площадка, сдвинутая вставкой."""
        before = self._unresolved_of(self._TWICE_BOUND)
        after = self._unresolved_of("X = 1\n" + self._TWICE_BOUND)
        self.assertTrue(before, "население пусто — сцена ничего не проверяет")
        self.assertEqual([(e.func, e.text) for e in before],
                         [(e.func, e.text) for e in after],
                         "личность площадки обязана пережить вставку")
        self.assertNotEqual([e.line for e in before], [e.line for e in after],
                            "номера обязаны РАЗОЙТИСЬ — иначе сцена не про то, "
                            "и старый ключ покраснел бы не от чего")

    def test_a_NEW_unresolved_guard_is_still_caught(self):
        """Ратчет не ослаблен: незнакомая площадка класса по-прежнему видна."""
        rows = self._unresolved_of(self._TWICE_BOUND)
        self.assertTrue(rows)
        self.assertEqual(
            [(e.func, e.text) for e in rows
             if (e.func, e.text) in UNRESOLVED_GUARD_ALLOWED], [],
            "выдуманная площадка не имеет права попасть под освобождение")

    def test_the_allowlist_keys_match_the_live_producer_exactly(self):
        """База не имеет права ссылаться на площадку, которой нет.

        Прежний ключ-номер протухал МОЛЧА в обе стороны: строка уезжала — и
        освобождение начинало накрывать соседа, оказавшегося на этом номере.
        """
        live = {(e.func, e.text) for e in self.rows if e.guard_unresolved}
        self.assertEqual(set(UNRESOLVED_GUARD_ALLOWED), live)

    def test_gated_is_measured_by_call_form_not_by_variable_name(self):
        """Переименование переменной проводку не подделает."""
        self.assertIn("_absent_block", census.MARK_SOURCES)
        self.assertIn("_finding_mark", census.MARK_SOURCES)
        gated = [e for e in self.rows if e.kind == census.GATED]
        self.assertGreaterEqual(len(gated), 15, gated)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
