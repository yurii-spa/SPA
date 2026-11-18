"""Отсрочка «ещё не производился» обязана быть ОГРАНИЧЕНА (ADR-1053).

# LLM_FORBIDDEN

Предмет — не форма вердикта, а его ДОСТИЖИМОСТЬ. `artifact_absence` объявлял
исход `NOT_YET` «не вечным», потому что его закрывает следующий прогон бегуна;
но будет ли этот прогон, вердикт не спрашивал НИ РАЗУ. Условие отсрочки
(`ran < born`) выполняется тем **вернее**, чем дольше бегун молчит, — то есть
молчание само продлевает своё оправдание, и печатается это словами «это НЕ
находка».

Живой замер 18.11 (цикл #1191), воспроизведённый сценой A ниже: бегун ступеней
моста молчал **481.2 ч** при объявленном горизонте артефакта **192 ч**, а шаг
0-офис печатал про `data/acceptance_tree_lineage.json` «⏳ ЕЩЁ НЕ ПРОИЗВОДИЛСЯ
(это НЕ находка) … Ответ будет на следующем прогоне бегуна». Цена названа
замером, а не предположена: тот артефакт и есть вердикт о дереве-приёмке §49
(решение владельца ADR-509), и дерево отстало на 790 коммитов с ИЗМЕНИВШИМИСЯ
носителями мерки §49.

Каждая проверка здесь — контроль на ОДНО звено, и у главной есть контроль в
обратную сторону (сцена B): без вопроса о горизонте та же сцена ОПРАВДЫВАЕТСЯ.
Без него «находка есть» не означало бы, что находку делает именно новый вопрос.

Время — ВХОД: `now=NOW`, все отметки сцены производятся от того же `NOW`
(`os.utime`, `isoformat`). Литеральной даты в файле нет.
# FROZEN-DATE-OK: injected-clock — якорь `NOW` связан с именем, передаётся
# `aa.verdict(..., now=NOW)`, и отметки отчёта/модуля считаются от него же.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import artifact_absence as aa

#: Якорь сцены. От него производятся ВСЕ отметки — и mtime, и отчёт бегуна.
NOW = dt.datetime(2026, 11, 18, 9, 0, tzinfo=dt.timezone.utc)

#: Живой замер 18.11, воспроизводимый дословно.
RUNNER_SILENT_H = 481.2      # бегун ступеней моста молчал столько
DECLARED_HORIZON_H = 192.0   # `slo_hours` артефакта в манифесте
BORN_H = 128.4               # столько несущий вызов лежал в дереве

#: Свежий бегун: зазор, на котором отсрочка ЗАКОННА (замер 02.10, ADR-536).
RUNNER_FRESH_H = 4.22


def _stage_pair() -> tuple[str, str, str]:
    """Настоящая пара «ступень → модуль → артефакт» из живого реестра моста.

    Выдуманная пара не нашлась бы в объявлении, и вердикт отвечал бы «не
    объявлен» — то есть о ДРУГОМ вопросе.
    """
    from spa_core.monitoring import findings_bridge as fb
    for stage, spec in fb.CENSUS_PRODUCT.items():
        return stage, spec["module"], spec["artifact"]
    raise AssertionError("реестр ступеней моста пуст — предпосылка НЕ ОБЕСПЕЧЕНА")


class _Scene(unittest.TestCase):
    """Одноразовое дерево: производитель есть, артефакта нет, бегун молчит."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="spa_deferral_horizon_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.stage, self.module_rel, self.artifact_rel = _stage_pair()
        (self.root / "data").mkdir(parents=True, exist_ok=True)

    def producer(self, *, born_hours_ago: float = BORN_H) -> None:
        p = self.root / self.module_rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# производитель\n", encoding="utf-8")
        born = (NOW - dt.timedelta(hours=born_hours_ago)).timestamp()
        os.utime(p, (born, born))

    def runner(self, *, silent_hours: float) -> None:
        doc = {"run_started_at": (NOW - dt.timedelta(hours=silent_hours)).isoformat()}
        (self.root / aa.RUNNER_REPORT_REL).write_text(
            json.dumps(doc), encoding="utf-8")

    def manifest(self, *, slo_hours=DECLARED_HORIZON_H) -> None:
        """Реестр артефактов сцены. Горизонт объявляется ЗДЕСЬ, а не в коде."""
        path = self.root / aa.MANIFEST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"artifacts": [{"path": self.artifact_rel, "slo_hours": slo_hours}]}
        path.write_text(json.dumps(body), encoding="utf-8")

    def verdict(self, **kw):
        return aa.verdict(self.artifact_rel, root=str(self.root), now=NOW, **kw)


class TheLiveReplayOf1811(_Scene):
    """(A) Дословное воспроизведение живого замера 18.11."""

    def test_a_runner_silent_past_the_horizon_is_a_finding(self):
        self.producer()
        self.runner(silent_hours=RUNNER_SILENT_H)
        self.manifest()
        v = self.verdict()
        self.assertEqual(
            v.kind, aa.DEFERRAL_OUTLIVED_THE_RUNNER,
            f"исход {v.kind!r}: отсрочка опирается на бегуна, молчащего "
            f"{RUNNER_SILENT_H}ч при горизонте {DECLARED_HORIZON_H}ч")
        self.assertTrue(v.is_finding, "это обязано ОБЯЗЫВАТЬ, а не печататься "
                                      "словами «не находка»")
        self.assertEqual(v.horizon_h, DECLARED_HORIZON_H)
        self.assertAlmostEqual(v.runner_age_h, RUNNER_SILENT_H, places=1)
        self.assertIn("481.2", v.reason)
        self.assertIn("192", v.reason)

    def test_without_the_horizon_question_the_same_scene_is_excused(self):
        """Контроль в ОБРАТНУЮ сторону: находку делает именно новый вопрос.

        Горизонт объявляется неограниченным — ровно поведение ДО ADR-1053, — и
        та же сцена обязана вернуться к «⏳ ещё не производился». Без этого
        контроля зелень сцены A не отличалась бы от сторожа, который краснеет
        на чём угодно.
        """
        self.producer()
        self.runner(silent_hours=RUNNER_SILENT_H)
        self.manifest()
        v = self.verdict(horizon_of=lambda _rel: 10 ** 9)
        self.assertEqual(v.kind, aa.NOT_YET,
                         "при неограниченном горизонте прежнее поведение обязано "
                         "сохраниться дословно")
        self.assertFalse(v.is_finding)


class TheDeferralStillWorksWhenItIsLegitimate(_Scene):
    """(B) Исправная проводка, ждущая такта, находкой стать НЕ должна."""

    def test_a_runner_inside_the_horizon_still_defers(self):
        self.producer(born_hours_ago=3.17)
        self.runner(silent_hours=RUNNER_FRESH_H)
        self.manifest()
        v = self.verdict()
        self.assertEqual(v.kind, aa.NOT_YET,
                         "бегун работал 4.22ч назад при горизонте 192ч — такт "
                         "ещё не пропущен, и обвинять его значит вернуть "
                         "аварию 02.10 (ADR-536)")
        self.assertFalse(v.is_finding)
        self.assertEqual(v.horizon_h, DECLARED_HORIZON_H)

    def test_equality_with_the_horizon_is_not_a_finding(self):
        """Граница названа: просрочка это БОЛЬШЕ горизонта, а не «ровно».

        Ровно горизонт означает «срок, объявленный самим артефактом, ещё не
        вышел». Сдвинуть границу на равенство значило бы ужесточить мерку, не
        объявив этого.
        """
        self.producer()
        self.runner(silent_hours=DECLARED_HORIZON_H)
        self.manifest()
        self.assertEqual(self.verdict().kind, aa.NOT_YET)

    def test_one_hour_past_the_horizon_is_a_finding(self):
        self.producer()
        self.runner(silent_hours=DECLARED_HORIZON_H + 1.0)
        self.manifest()
        self.assertEqual(self.verdict().kind, aa.DEFERRAL_OUTLIVED_THE_RUNNER)


class AnUndeclaredHorizonIsTheThirdOutcome(_Scene):
    """(C) Нет срока ⇒ «позже» неопровержимо. Третий исход, не молчание."""

    def test_a_missing_manifest_is_unmeasured_and_a_finding(self):
        self.producer()
        self.runner(silent_hours=RUNNER_SILENT_H)
        # манифест НЕ выкладывается
        v = self.verdict()
        self.assertEqual(v.kind, aa.UNMEASURED_NO_HORIZON,
                         f"исход {v.kind!r}: горизонта нет, и отсрочку "
                         f"ограничить нечем")
        self.assertTrue(v.is_finding, "инв. #17: «не измерено» обязано остаться "
                                      "находкой, а не отсрочкой")
        self.assertIn(aa.MANIFEST_REL, v.reason)
        self.assertIn(aa.UNMEASURED, v.reason)

    def test_a_door_answering_none_is_the_same_outcome(self):
        # Свежий бегун ⇒ приход кода обязан быть ПОЗЖЕ его прогона, иначе
        # сцена уедет с дороги отсрочки вовсе (условие ветки — `ran < born`).
        self.producer(born_hours_ago=3.17)
        self.runner(silent_hours=RUNNER_FRESH_H)
        self.manifest()
        v = self.verdict(horizon_of=lambda _rel: None)
        self.assertEqual(v.kind, aa.UNMEASURED_NO_HORIZON,
                         "дверь ответила «не объявлен» — и свежесть бегуна "
                         "этого не лечит: ограничить отсрочку по-прежнему нечем")
        self.assertTrue(v.is_finding)

    def test_the_three_outcomes_are_distinguishable_by_value(self):
        """Инв. #17 целиком: измерено · измерено и в пределах · не измерено.

        Все три сцены стоя́т НА ДОРОГЕ ОТСРОЧКИ (`ran < born`) и отличаются
        ТОЛЬКО горизонтом. Сцена, съехавшая с этой дороги, дала бы третий
        исход по чужой причине, и равенство трёх значений ничего бы не значило.
        """
        self.manifest()
        self.producer(born_hours_ago=3.17)
        self.runner(silent_hours=RUNNER_FRESH_H)
        inside = self.verdict()
        unmeasured = self.verdict(horizon_of=lambda _rel: None)
        self.producer(born_hours_ago=BORN_H)
        self.runner(silent_hours=RUNNER_SILENT_H)
        outside = self.verdict()
        for name, v in (("в пределах", inside), ("просрочен", outside),
                        ("без горизонта", unmeasured)):
            self.assertIsNotNone(v.runner_age_h,
                                 f"сцена «{name}» съехала с дороги отсрочки "
                                 f"(исход {v.kind!r}) — сравнивать нечего")
        kinds = {inside.kind, outside.kind, unmeasured.kind}
        self.assertEqual(len(kinds), 3,
                         f"исходы склеились: {inside.kind!r} · {outside.kind!r} "
                         f"· {unmeasured.kind!r} — различить их значением нечем")
        self.assertEqual([inside.is_finding, outside.is_finding,
                          unmeasured.is_finding], [False, True, True],
                         "обязывает действовать не то, что измерено и в "
                         "пределах, а просрочка и ненаблюдаемость")


class TheOfficeNamesItAndItsNextStep(_Scene):
    """(D) Находка без читателя внутри цикла — не находка.

    Шаг 0-офис — СКРИПТ, грузится по пути (тот же приём, что у соседней
    батареи ADR-812): проверяется ЖИВОЙ читатель, а не копия его логики.
    """

    @staticmethod
    def _office():
        import importlib.util
        path = (Path(__file__).resolve().parents[2] / "scripts"
                / "consume_office_reports.py")
        spec = importlib.util.spec_from_file_location("_office_c1191", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_office_turns_it_into_a_finding_with_a_next_step(self):
        self.producer()
        self.runner(silent_hours=RUNNER_SILENT_H)
        self.manifest()
        is_finding, lines = self._office()._absent_verdict(
            self.artifact_rel, root=str(self.root), data_dir=None, now=NOW)
        text = "\n".join(lines)
        self.assertTrue(is_finding, text)
        self.assertNotIn("ЕЩЁ НЕ ПРОИЗВОДИЛСЯ", text,
                         "офис всё ещё печатает отсрочку — читателю сказали "
                         "«не находка» о вечном молчании")
        self.assertIn("ждать такта бессмысленно", text,
                      "следующий шаг не назван: у этой находки он ДРУГОЙ — "
                      "поднять бегуна либо вывести ступень карточкой")

    def test_the_office_still_defers_when_the_runner_is_alive(self):
        self.producer(born_hours_ago=3.17)
        self.runner(silent_hours=RUNNER_FRESH_H)
        self.manifest()
        is_finding, lines = self._office()._absent_verdict(
            self.artifact_rel, root=str(self.root), data_dir=None, now=NOW)
        text = "\n".join(lines)
        self.assertFalse(is_finding, text)
        self.assertIn("ЕЩЁ НЕ ПРОИЗВОДИЛСЯ", text)


class TheHorizonIsReadNotChosen(unittest.TestCase):
    """(E) Предел берётся из ОБЪЯВЛЕНИЯ, и дверь к нему одна."""

    def test_the_door_reads_a_real_declared_horizon(self):
        """Контроль «не вакуумно»: дверь запускается на БОЕВОМ манифесте."""
        root = str(Path(__file__).resolve().parents[2])
        _stage, _module, artifact = _stage_pair()
        got = aa.declared_horizon_hours(artifact, root=root)
        self.assertIsNotNone(
            got, f"у живого артефакта {artifact} горизонт не прочитан — дверь "
                 f"отвечает «не объявлен» на объявленном, и тогда весь класс "
                 f"уйдёт в НЕ ИЗМЕРЕНО")
        self.assertGreater(got, 0)

    def test_an_unknown_path_has_no_horizon(self):
        root = str(Path(__file__).resolve().parents[2])
        self.assertIsNone(
            aa.declared_horizon_hours("data/net-takogo-artefakta.json", root=root))

    def test_a_value_that_is_not_a_positive_number_is_not_a_horizon(self):
        """Опечатка в объявлении обязана читаться как «не объявлен».

        `True` — подножка Python (`isinstance(True, int)`), строка «192» — форма
        объявления, которой реестр не несёт, ноль и минус — срок, которого не
        бывает. Любое из них, прочитанное как горизонт, молча превратило бы
        находку в отсрочку либо наоборот.
        """
        with tempfile.TemporaryDirectory() as box:
            path = Path(box) / aa.MANIFEST_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            for bad in (True, "192", 0, -1, None, [192]):
                path.write_text(json.dumps(
                    {"artifacts": [{"path": "data/x.json", "slo_hours": bad}]}),
                    encoding="utf-8")
                self.assertIsNone(
                    aa.declared_horizon_hours("data/x.json", root=box),
                    f"значение {bad!r} прочитано как горизонт")

    def test_an_unreadable_registry_has_no_horizon(self):
        with tempfile.TemporaryDirectory() as box:
            path = Path(box) / aa.MANIFEST_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{не json", encoding="utf-8")
            self.assertIsNone(aa.declared_horizon_hours("data/x.json", root=box))


class TheModuleNoLongerClaimsTheDeferralIsNotEternal(unittest.TestCase):
    """(F) Шапка модуля утверждала обратное — и это утверждение опровергнуто.

    Проверка узкая намеренно: она про ОДНУ снятую фразу, а не про стиль
    документации. Вернись она — вернётся и обещание, которого механизм не
    держит, а код при этом останется исправным, то есть расхождение будет
    молчаливым.
    """

    #: Фраза, которую шапка УТВЕРЖДАЛА до ADR-1053.
    CLAIM = "Третий исход **не вечен**"
    #: Слова, которыми она теперь ЦИТИРУЕТСЯ как снятая.
    QUOTE_MARK = "Здесь стояло: «"

    def test_the_claim_survives_only_as_a_quotation_of_the_superseded_text(self):
        """Проверять ОТСУТСТВИЕ фразы было бы неверно — её цитирует поправка.

        Первая редакция этой проверки требовала, чтобы фразы в файле не было
        ВОВСЕ, и покраснела на собственной поправке: та начинается словами
        «Здесь стояло: …» и приводит снятое утверждение дословно. Это тот же
        класс, что заполнитель, попавший в прошлую строку журнала: предмет —
        не наличие символов, а то, УТВЕРЖДАЕТСЯ ли фраза или ЦИТИРУЕТСЯ.
        """
        src = Path(aa.__file__).read_text(encoding="utf-8")
        self.assertEqual(src.count(self.CLAIM), 1,
                         "снятое утверждение встречается не один раз — одна из "
                         "копий снова утверждает, а не цитирует")
        at = src.index(self.CLAIM)
        head = src[max(0, at - 200):at]
        self.assertIn(self.QUOTE_MARK, head,
                      "фраза стои́т НЕ внутри цитаты — шапка снова обещает, что "
                      "отсрочка закроется сама, а замер 18.11 показал обратное "
                      "(бегун молчал 481.2ч при объявленном горизонте 192ч)")
        self.assertIn("ADR-1053", src)
        self.assertIn("481.2", src, "живой замер, опровергший утверждение, в "
                                    "шапке не назван — поправка без замера есть "
                                    "предпочтение, а не находка")


if __name__ == "__main__":
    unittest.main()
