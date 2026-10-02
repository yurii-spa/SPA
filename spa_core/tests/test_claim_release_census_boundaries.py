#!/usr/bin/env python3
"""Границы и адресат — четыре мутации, ПЕРЕЖИВШИЕ батарею прибора (замер цикла #750).

Прибор `claim_release_census` (заказ G88 п. 2, ADR-536) построен циклом #749, который
умер, не доставив. Цикл #750 поднял его работу и **перемерил её своим прогоном**, а не
поверил отчёту: мутационный замер по формам, найденным разбором прибора, дал
**применено 7 · убито 3 · выжило 4** при зелёном контроле шума — то есть унаследованное
утверждение «мутации 23/23, выживших нет» на ЭТИХ координатах не держится.

Выжившие — не равносильные подмены, а отсутствующие сцены. Каждый тест ниже убивает
ровно одну из них и назван её именем:

====  ====================================  =========================================
ось   выжившая мутация                      чего не хватало сцене
====  ====================================  =========================================
D     `age_hours >= ttl` → `> ttl`          держателя РОВНО на сроке
D     `value > ttl` → `>= ttl`              задержки, равной сроку
A     `stamp <= row["ts"]` → `<`            освобождения в ТУ ЖЕ секунду, что захват
C     снято `who != row["identity"]`        карточки, закрытой ТЕМ ЖЕ держателем
====  ====================================  =========================================

Три первых — границы (ошибка на единицу), и цена у них прямая: заголовочные числа
лестницы и её цена смещаются на население границы. Четвёртая — не граница, а СМЫСЛ:
число 450 («карточка объявлена закрытой ДРУГОЙ личностью») есть главный вывод ADR-536,
и без этой сцены оно не отличалось бы от «закрытой кем угодно, включая держателя».

Время и живость — ВХОДЫ (сцена и её двери к ОС взяты у самой батареи прибора).
FROZEN-DATE-OK: injected-clock — якорь `_NOW` импортируется из батареи прибора, все
отметки происходят от него вычитанием (`_stamp`), и он же уезжает аргументом `now=`
в `build_report`; живость подменяется `ps=`/`cmd_probe=`.
"""
from __future__ import annotations

import unittest

from spa_core.tests.test_claim_release_census import (
    _NOW, _Scene, _cmd_session, _ps_alive, _ps_dead, _record, _stamp)


class LadderBoundaryIsInclusive(_Scene):
    """Ось D: держатель РОВНО на сроке обязан попадать в «закрыл бы»."""

    #: Ступень лестницы, на которой ставится сцена. Берётся У ПРИБОРА, а не
    #: литералом: литерал разошёлся бы с лестницей молча (ADR-220).
    def _ttl(self):
        from spa_core.monitoring import claim_release_census as crc
        return sorted(crc.TTL_LADDER_HOURS)[0]

    def test_a_holder_exactly_at_the_ttl_is_counted_as_closed(self):
        ttl = self._ttl()
        rows = [_record("own-boundary", "claim", hours_ago=ttl, pid=4242)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        step = next(s for s in rep["expiry_ladder"]["ladder"]
                    if s["ttl_hours"] == ttl)
        self.assertEqual(
            step["all_open"]["would_close_dead_holder"], 1,
            "захват возрастом РОВНО в срок не закрылся бы — порог исключающий, "
            "и мутация `>=` → `>` переживает батарею (замер #750)")

    def test_a_holder_just_under_the_ttl_is_not_counted(self):
        """Обратная сторона: правка не смеет закрывать то, что не дожило до срока."""
        ttl = self._ttl()
        rows = [_record("own-boundary", "claim", hours_ago=ttl - 0.5, pid=4242)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        step = next(s for s in rep["expiry_ladder"]["ladder"]
                    if s["ttl_hours"] == ttl)
        self.assertEqual(step["all_open"]["would_close_dead_holder"], 0)


class TheLadderPriceBoundaryIsStrict(_Scene):
    """Ось D, цена: задержка, РАВНАЯ сроку, работу ещё не обрывает.

    Асимметрия с тестом выше намеренная и названа: «старше срока» закрывается
    (`>=`), а «оборвал бы» считается строго (`>`), иначе работа, уложившаяся
    ровно в срок, числилась бы оборванной. Два порога — два разных вопроса.
    """

    def _ttl(self):
        from spa_core.monitoring import claim_release_census as crc
        return sorted(crc.TTL_LADDER_HOURS)[0]

    def test_work_that_closed_exactly_at_the_ttl_was_not_cut(self):
        ttl = self._ttl()
        rows = [_record("own-price", "claim", hours_ago=ttl + 1.0, pid=11),
                _record("own-price", "done", hours_ago=1.0, pid=11)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        step = next(s for s in rep["expiry_ladder"]["ladder"]
                    if s["ttl_hours"] == ttl)
        latency = (_NOW - _NOW).total_seconds()  # сцена: задержка = ttl ровно
        del latency
        self.assertEqual(
            step["would_have_cut_self_closing_work"], 0,
            "работа, закрывшаяся РОВНО в срок, объявлена оборванной — мутация "
            "`>` → `>=` переживает батарею (замер #750)")

    def test_work_that_closed_after_the_ttl_is_counted_as_cut(self):
        ttl = self._ttl()
        rows = [_record("own-price", "claim", hours_ago=ttl + 2.0, pid=11),
                _record("own-price", "done", hours_ago=0.5, pid=11)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        step = next(s for s in rep["expiry_ladder"]["ladder"]
                    if s["ttl_hours"] == ttl)
        self.assertEqual(step["would_have_cut_self_closing_work"], 1)


class ReleaseInTheSameSecondStillReleasesItsOwnClaim(_Scene):
    """Ось A: `done` с ТОЙ ЖЕ отметкой, что захват, снимает свой захват.

    Журнал пишется с секундной точностью, и «взял и сразу закрыл» ложится в одну
    секунду штатно. Если порог исключающий, такое освобождение попадает в
    «не сняло ничего» — то есть в НАХОДКУ, которой нет.
    """

    def test_equal_timestamps_count_as_releasing_own_claim(self):
        rows = [_record("own-same-second", "claim", hours_ago=3.0, pid=7),
                _record("own-same-second", "done", hours_ago=3.0, pid=7)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        writers = rep["writers"]
        self.assertEqual(
            writers["released_own_prior_claim"], 1,
            "освобождение в ту же секунду не признано снятием своего захвата — "
            "мутация `<=` → `<` переживает батарею (замер #750)")
        self.assertEqual(writers["released_nothing"], 0)

    def test_a_release_before_any_claim_still_releases_nothing(self):
        """Обратная сторона: порог не смеет стать «всегда своё»."""
        rows = [_record("own-earlier", "done", hours_ago=5.0, pid=7),
                _record("own-earlier", "claim", hours_ago=1.0, pid=7)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        self.assertEqual(rep["writers"]["released_nothing"], 1)
        self.assertEqual(rep["writers"]["released_own_prior_claim"], 0)


class TheCardMustBeClosedByANOTHERIdentity(_Scene):
    """Ось C: закрытие ТЕМ ЖЕ держателем — не «закрыта другой личностью».

    Это главный вывод ADR-536 (450 из 557), и держится он ровно на условии
    `who != row["identity"]`. Сцены на него в батарее не было: мутация, снимающая
    условие, переживала все 29 тестов (замер #750).
    """

    def test_same_identity_closing_the_card_is_not_counted_as_elsewhere(self):
        # Держатель объявил карточку закрытой ПОЗЖЕ своего же захвата, но у него
        # есть ВТОРОЙ, более ранний захват — поэтому захват остаётся открытым, а
        # «закрыта другой личностью» обязано остаться нулём.
        rows = [_record("own-self-close", "claim", hours_ago=9.0, pid=5),
                _record("own-self-close", "claim", hours_ago=8.0, pid=5),
                _record("own-self-close", "done", hours_ago=7.0, pid=5)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        self.assertEqual(
            rep["open_claims"]["card_declared_done_by_another_identity"], 0,
            "закрытие СВОИМ держателем зачтено как «закрыта другой личностью» — "
            "мутация, снимающая `who != identity`, переживает батарею (#750)")

    def test_a_different_identity_closing_the_card_IS_counted(self):
        """Обратная сторона — тот самый класс 450: закрыл ДРУГОЙ."""
        rows = [_record("own-other-close", "claim", hours_ago=9.0,
                        label="cycle-A", pid=5),
                _record("own-other-close", "done", hours_ago=7.0,
                        label="cycle-B", pid=6)]
        rep = self._report(rows, ps=_ps_dead, cmd_probe=_cmd_session)
        self.assertEqual(
            rep["open_claims"]["card_declared_done_by_another_identity"], 1,
            "класс, ради которого написан ADR-536, сценой не воспроизводится")

    def test_the_two_sides_are_distinguishable_on_one_scene(self):
        """Дифференциально: один и тот же журнал, разная ЛИЧНОСТЬ закрывшего."""
        own = [_record("own-diff", "claim", hours_ago=9.0, label="cycle-A", pid=5),
               _record("own-diff", "claim", hours_ago=8.0, label="cycle-A", pid=5),
               _record("own-diff", "done", hours_ago=7.0, label="cycle-A", pid=5)]
        other = [_record("own-diff", "claim", hours_ago=9.0, label="cycle-A", pid=5),
                 _record("own-diff", "claim", hours_ago=8.0, label="cycle-A", pid=5),
                 _record("own-diff", "done", hours_ago=7.0, label="cycle-B", pid=6)]
        by_own = self._report(own, ps=_ps_dead, cmd_probe=_cmd_session)
        by_other = self._report(other, ps=_ps_dead, cmd_probe=_cmd_session)
        self.assertNotEqual(
            by_own["open_claims"]["card_declared_done_by_another_identity"],
            by_other["open_claims"]["card_declared_done_by_another_identity"],
            "личность закрывшего на вердикт не влияет ⇒ сцена не воспроизводит "
            "предмет, и зелень тестов выше ничего не значит")


class LiveHolderIsStillNeverEvicted(_Scene):
    """Страховка к границам: ни одна из правок не смеет выгонять ЖИВОГО.

    Ось D объявляет «выгнал бы живого 0» на живом журнале, и это утверждение
    держит не арифметика, а разделение исходов. Граница — ровно то место, где
    такое утверждение ломается тише всего.
    """

    def test_a_live_holder_exactly_at_the_ttl_is_counted_as_live_not_dead(self):
        from spa_core.monitoring import claim_release_census as crc
        ttl = sorted(crc.TTL_LADDER_HOURS)[0]
        rows = [_record("own-live", "claim", hours_ago=ttl, pid=9191)]
        rep = self._report(rows, ps=_ps_alive, cmd_probe=_cmd_session)
        step = next(s for s in rep["expiry_ladder"]["ladder"]
                    if s["ttl_hours"] == ttl)
        self.assertEqual(step["all_open"]["would_evict_live_holder"], 1,
                         "живой держатель на границе обязан быть ВИДЕН как живой")
        self.assertEqual(step["all_open"]["would_close_dead_holder"], 0,
                         "живой держатель зачтён в мёртвых — исходы слиплись")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TheIdentityConditionInAxisCIsProvablyRedundant(_Scene):
    """Пятая мутация выжила — и она РАВНОСИЛЬНА, что доказано предпосылкой.

    Замер #750 (после добавления сцен выше): применено 7 · убито 6 · выжило 1.
    Выжившая — снятие `who != row["identity"]` в оси C. Соблазн закрыть её ещё
    одной сценой здесь ЛОЖЕН: сцены не существует, потому что состояние, которое
    условие отсекает, НЕДОСТИЖИМО.

    Доказательство — предпосылка, а не рассуждение. `measure_latency` относит
    захват в `open_claims` ровно тогда, когда у пары `(личность, карточка)` НЕТ
    освобождения с отметкой `>= ts` захвата. Значит у любого открытого захвата
    каждое освобождение этой карточки с `stamp >= ts` принадлежит ДРУГОЙ личности
    по построению, и условие отсечь не может ничего.

    Инвариант проверяется ИСХОДОМ на сцене, где есть все четыре формы сразу:
    своё закрытие, чужое закрытие, повторный захват и захват без закрытия. Если
    однажды определение «открытого» изменится, этот тест покраснеет первым — и
    тогда условие перестанет быть лишним, а равносильность — верной.
    """

    def _population(self, rows):
        from spa_core.monitoring import claim_release_census as crc
        pop = crc.split_population(rows, guard=self.kin["guard"],
                                   sibling=self.kin["sibling"])
        lat = crc.measure_latency(pop["claims"], pop["releases"])
        return pop, lat

    def test_no_open_claim_has_a_same_identity_release_at_or_after_it(self):
        rows = [
            # своё закрытие (пара сходится — в open_claims не попадёт)
            _record("own-a", "claim", hours_ago=9.0, label="cycle-A", pid=1),
            _record("own-a", "done", hours_ago=8.0, label="cycle-A", pid=1),
            # чужое закрытие (захват остаётся открытым — класс 450)
            _record("own-b", "claim", hours_ago=9.0, label="cycle-A", pid=1),
            _record("own-b", "done", hours_ago=7.0, label="cycle-B", pid=2),
            # повторный захват той же личностью после своего же закрытия
            _record("own-a", "claim", hours_ago=6.0, label="cycle-A", pid=1),
            # захват, который не закрывал никто
            _record("own-c", "claim", hours_ago=5.0, label="cycle-C", pid=3),
        ]
        pop, lat = self._population(rows)
        self.assertTrue(lat["measured"], "сцена не дала ни одной сошедшейся пары")
        open_rows = lat["open_claims"]
        self.assertTrue(open_rows, "сцена не дала ни одного открытого захвата")

        by_card = {}
        for row in pop["releases"]:
            by_card.setdefault(row["card"], []).append((row["ts"], row["identity"]))

        for row in open_rows:
            for stamp, who in by_card.get(row["card"], ()):
                if stamp >= row["ts"]:
                    self.assertNotEqual(
                        who, row["identity"],
                        "у ОТКРЫТОГО захвата нашлось освобождение СВОЕЙ личности "
                        "не раньше него — предпосылка равносильности сломана, и "
                        "условие `who != identity` снова нужно")

    def test_the_scene_really_contains_both_closing_identities(self):
        """Контроль самой предпосылки: сцена обязана быть АСИММЕТРИЧНОЙ.

        Урок #749: симметричная сцена (1 против 1) пропустила перевёрнутый отбор.
        Если бы здесь не было ОБОИХ видов закрытия, инвариант выше держался бы
        тривиально и ничего не доказывал.
        """
        rows = [
            _record("own-a", "claim", hours_ago=9.0, label="cycle-A", pid=1),
            _record("own-a", "done", hours_ago=8.0, label="cycle-A", pid=1),
            _record("own-b", "claim", hours_ago=9.0, label="cycle-A", pid=1),
            _record("own-b", "done", hours_ago=7.0, label="cycle-B", pid=2),
        ]
        pop, lat = self._population(rows)
        identities = {row["identity"] for row in pop["releases"]}
        self.assertGreaterEqual(len(identities), 2,
                                "в сцене одна закрывающая личность — инвариант "
                                "держался бы тривиально")
        self.assertEqual(len(lat["open_claims"]), 1,
                         "сцена не оставила ровно один открытый захват")
