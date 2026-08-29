"""«Не измерено» обязано означать «не измерено» — и рецидив обязан стареть (цикл #421).

Карточка `inbox-puls-petli-adr-066-prochitan-vpervye-3-r`, обе половины приёмки.

**Половина 1 — четыре карточки «со статусом НЕ ИЗМЕРЕНО».** Замер 29.08 на живом
`data/findings_bridge_state.json`: все четыре читались прекрасно и несли статус
`ingested` (это карточки `owner-decision`, разобранные по протоколу) — а `compute`
складывал в `unreadable` ВСЁ, что не `new`/`in-progress`/`done`. Обязательный шаг
0-офис четвёртые сутки печатал «⚠️ статус 4 карточк(и) моста НЕ ИЗМЕРЕНО … files-first
очередь не отдала статус» и звал разбирать слепое пятно, которого не было; заодно
четверть выборки (4 из 27) выпадала из знаменателя всех долей. Направление ошибки
обратно обычному — здесь измеренное объявлено неизмеренным, — но класс тот же:
утверждение о мере, которой не делали.

**Половина 2 — рецидив не стареет никогда.** `recurrences` только растёт. Замер 29.08:
из четырёх «вернувшихся» две (`aave_v3`, `fluid_fusdc`) закрыты и не появлялись с
25–26.08, а строка кричала о всех четырёх в НАСТОЯЩЕМ времени. Строка, верная всегда,
сигналом быть перестаёт — этого карточка и опасалась дословно.

**Как читать этот файл.** Тесты помечены явно, потому что «краснеет на старом коде» и
«сторожит починку от перегиба» — РАЗНЫЕ работы, и путать их значит принимать украшение
за контроль:

* `# ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ` — краснеет на `origin/main` ПО СУЩЕСТВУ (старый код даёт
  другой вердикт), либо на новом поле, которого там нет; замерено на закреплённом sha;
* `# ОБРАТНЫЙ КОНТРОЛЬ` — зелёный и ДО, и ПОСЛЕ. Он сторожит не дефект, а перегиб
  починки, и потому нарочно написан так, чтобы исполняться на обеих версиях
  (`.get(..., 0)` вместо прямого ключа): контроль, который на старом коде падает с
  `KeyError`, о перегибе не говорит ничего.

Время — вход (`now=`), литеральных дат нет (правило `.claude/rules/deployment.md`).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.monitoring.loop_health import compute

_NOW = dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock
_HOUR = dt.timedelta(hours=1)


def _f(*, status="carded", card=None, recurrences=0, last_seen=None):
    return {"first_seen": None, "carded_at": None, "closed_at": None,
            "recurrences": recurrences, "status": status, "card": card,
            "last_seen": last_seen}


def _state(**findings):
    return {"findings": findings}


class UnreadableMeansUnreadable(unittest.TestCase):
    """Статус ПРОЧИТАН, но не из перечисления ⇒ это НЕ «не измерено»."""

    def test_ingested_card_is_not_counted_as_unmeasured(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: живая авария 29.08 дословно —
        # четыре карточки моста в статусе `ingested` числились слепым пятном.
        st = _state(**{f"B1:zombie:com.spa.a{i}": _f(card=f"/t/own-{i}.md") for i in range(4)})
        r = compute(st, lambda card: "ingested", _NOW)
        self.assertEqual(r["cards_fate"]["unreadable"], 0,
                         "измеренный статус объявлен слепым пятном")
        self.assertEqual(r["cards_fate"]["other_status"], 4)

    def test_each_out_of_enumeration_card_is_named_with_its_status(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: число без имён — строка, по которой действовать нечем.
        st = _state(**{"B1:zombie:com.spa.digest_weekly": _f(card="/t/own-digest.md")})
        r = compute(st, lambda card: "ingested", _NOW)
        self.assertEqual(r["cards_other_status"],
                         [{"key": "B1:zombie:com.spa.digest_weekly",
                           "card": "/t/own-digest.md", "status": "ingested"}])

    def test_a_card_that_really_gives_no_status_is_still_unreadable(self):
        # ОБРАТНЫЙ КОНТРОЛЬ: настоящее «не измерено» починка гасить не смеет.
        st = _state(**{"B1:zombie:com.spa.x": _f(card="/t/gone.md")})
        r = compute(st, lambda card: None, _NOW)
        self.assertEqual(r["cards_fate"]["unreadable"], 1)
        self.assertEqual(r["cards_fate"].get("other_status", 0), 0)

    def test_the_unreadable_card_is_also_named(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: до правки имён не было ни у одного исхода.
        st = _state(**{"B1:zombie:com.spa.x": _f(card="/t/gone.md")})
        r = compute(st, lambda card: None, _NOW)
        self.assertEqual(r["cards_unreadable"],
                         [{"key": "B1:zombie:com.spa.x", "card": "/t/gone.md"}])

    def test_the_three_known_statuses_keep_their_own_buckets(self):
        # ОБРАТНЫЙ КОНТРОЛЬ: новый исход не должен подъедать старые.
        st = _state(a=_f(card="/t/a.md"), b=_f(card="/t/b.md"), c=_f(card="/t/c.md"))
        by = {"/t/a.md": "new", "/t/b.md": "in-progress", "/t/c.md": "done"}
        r = compute(st, by.get, _NOW)
        fate = r["cards_fate"]
        self.assertEqual((fate["new"], fate["in_progress"], fate["done_by_human"]), (1, 1, 1))
        self.assertEqual((fate.get("other_status", 0), fate["unreadable"]), (0, 0))
        self.assertEqual(r.get("cards_other_status", []), [])

    def test_every_carded_finding_lands_in_exactly_one_bucket(self):
        # ОБРАТНЫЙ КОНТРОЛЬ: знаменатель обязан сходиться и до, и после —
        # доли петли считаются от полной выборки, и лишний бакет не смеет её раздвоить.
        st = _state(a=_f(card="/t/a.md"), b=_f(card="/t/b.md", status="closed"),
                    c=_f(card="/t/c.md"), d=_f(card=None))
        r = compute(st, {"/t/a.md": "ingested"}.get, _NOW)
        self.assertEqual(sum(r["cards_fate"].values()), 3, "карточка потерялась или сосчитана дважды")


class RecurrenceMustAge(unittest.TestCase):
    """Настоящее время — только для находок, которые СЕЙЧАС на доске."""

    def _live_and_historical(self):
        return _state(**{
            "gap:opportunity_unnamed:spark_susds": _f(
                recurrences=2, status="carded", card="/t/live.md",
                last_seen=(_NOW - 13 * _HOUR).isoformat()),
            "gap:opportunity_unnamed:aave_v3": _f(
                recurrences=1, status="closed", card="/t/old.md",
                last_seen=(_NOW - 4 * 24 * _HOUR).isoformat()),
            "gap:opportunity_unnamed:fluid_fusdc": _f(
                recurrences=1, status="closed", card="/t/old2.md",
                last_seen=(_NOW - 3 * 24 * _HOUR).isoformat()),
        })

    def test_live_recurrence_is_separated_from_historical(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: живой замер 29.08 дословно —
        # 4 рецидива = 2 живых + 2 закрытых и молчащих, а строка кричала о четырёх.
        r = compute(self._live_and_historical(), lambda c: "new", _NOW)
        self.assertEqual(r["recurrences_total"], 4, "общая сумма не должна меняться")
        self.assertEqual(r["recurrence_liveness"]["live"], 2)
        self.assertEqual(r["recurrence_liveness"]["historical"], 2)

    def test_historical_block_says_WHEN_it_last_happened(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: без даты «исторический» — такое же общее место, как сумма.
        r = compute(self._live_and_historical(), lambda c: "new", _NOW)
        self.assertEqual(r["recurrence_liveness"]["historical_last_seen"],
                         (_NOW - 3 * 24 * _HOUR).isoformat())

    def test_each_recurring_finding_carries_its_own_liveness_and_last_seen(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: сводка без разбивки не даёт разобрать ни одну строку.
        r = compute(self._live_and_historical(), lambda c: "new", _NOW)
        by_key = {x["key"]: x for x in r["recurring_findings"]}
        self.assertTrue(by_key["gap:opportunity_unnamed:spark_susds"]["live"])
        self.assertFalse(by_key["gap:opportunity_unnamed:aave_v3"]["live"])
        self.assertEqual(by_key["gap:opportunity_unnamed:aave_v3"]["last_seen"],
                         (_NOW - 4 * 24 * _HOUR).isoformat())

    def test_all_historical_means_nothing_is_live(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: счётчик ненулевой, а на доске пусто —
        # именно эта пара делала строку 0-офиса верной всегда, то есть бесполезной.
        st = _state(**{"gap:opportunity_unnamed:aave_v3": _f(
            recurrences=3, status="closed", card="/t/old.md",
            last_seen=(_NOW - 9 * 24 * _HOUR).isoformat())})
        r = compute(st, lambda c: "new", _NOW)
        self.assertEqual(r["recurrences_total"], 3)
        self.assertEqual(r["recurrence_liveness"], {
            "live": 0, "historical": 3,
            "historical_last_seen": (_NOW - 9 * 24 * _HOUR).isoformat()})

    def test_a_live_recurrence_is_never_silenced(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ по НОВОМУ полю, обратный по направлению: старение
        # не смеет проглотить сегодняшний рецидив. На origin падает за отсутствием поля.
        st = _state(**{"gap:opportunity_unnamed:spark_susds": _f(
            recurrences=2, status="carded", card="/t/live.md",
            last_seen=_NOW.isoformat())})
        r = compute(st, lambda c: "new", _NOW)
        self.assertEqual(r["recurrence_liveness"]["live"], 2)
        self.assertEqual(r["recurrence_liveness"]["historical"], 0)
        self.assertIsNone(r["recurrence_liveness"]["historical_last_seen"])

    def test_no_recurrence_at_all_stays_silent(self):
        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ по новому полю: измеренный ноль обязан быть записан.
        r = compute(_state(a=_f(card="/t/a.md")), lambda c: "new", _NOW)
        self.assertEqual(r["recurrences_total"], 0)
        self.assertEqual(r["recurrence_liveness"], {"live": 0, "historical": 0,
                                                    "historical_last_seen": None})
