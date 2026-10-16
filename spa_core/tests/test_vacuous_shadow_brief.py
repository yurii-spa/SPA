"""Пустой совет: советник сравнил книгу с самой собой, и у читателя не было
третьего исхода (ADR-765, заказ G764 п. 2 приказа «Portfolio CIO»).

Каждый тест здесь — положительный контроль на НАСТОЯЩИЙ замер 16.10, а не
украшение:

* на лентах `balanced` / `aggressive` **706 и 707 записей из 725** несли
  `target_positions`, побайтно равный `current_positions`: цель приходит от
  `hy_cycle.py` / `lp_cycle.py` как УЖЕ РЕШЁННАЯ книга дня (ADR-531), а на
  повторном прогоне дня решения нет вовсе и целью становится держимое;
* слой отображения печатал при этом `verdict: HOLD`,
  `optimal_apy_pp == current_apy_pp`, `yield_gap_pp: 0.0` при
  `numbers_evidenced: true` — то есть «взвешивать было нечего» читалось как
  «взвесили, разрыв нулевой» (инв. #17: это РАЗНЫЕ исходы);
* `why_now` считал ЗАПИСИ и печатал слово «день»: лента пишется ≈16 раз за
  цикл, и владелец читал **«323-й день подряд»** на ленте возрастом **45 дней**
  (измерено: настоящая серия 14 дн.; у `aggressive` — 346 против 15;
  у `conservative` — «5-й день» против 1).

Дат-литералов в файле нет намеренно: все даты и отметки производны от часов
прогона либо от инъектированного `now` — приёмы №1 и №2
`.claude/rules/deployment.md`. Красная сторона каждой проверки воспроизводит
ДОСОБЫТИЙНУЮ форму выдачи: поля просто снимаются с настоящего ответа, потому
что именно их отсутствие и было дефектом.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import vacuous_advice_census as vac
from spa_core.paper_trading.allocation_rationale import (
    history_filename,
    write_shadow_rationale,
)
from spa_core.paper_trading.cio_brief import brief_from_history, build_books_brief

_PROBE = "shadow_brief_names_the_unweighed_hold"


def _day(offset: int) -> str:
    """Дата цикла, выраженная сдвигом от сегодня — не литералом."""
    return (date.today() - timedelta(days=offset)).isoformat()


def _stamp(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _rec(offset: int, *, gates=None, current=None, target=None,
         verdict="HOLD", reasons=None, hours_ago=1.0, **kw) -> dict:
    rec = {
        "schema": "shadow-hist-v2",
        "decision_id": f"adr060-shadow-{_day(offset)}",
        "cycle_date": _day(offset),
        "generated_at": _stamp(hours_ago),
        "policy_version": "v1.0", "mode": "paper",
        "verdict": verdict,
        "reasons": ["no_material_legs"] if reasons is None else list(reasons),
        "legs": [], "gates": {"has_legs": False} if gates is None else dict(gates),
        "current_positions": {"maple": 25_000.0} if current is None else dict(current),
        "book_apy_pp": 4.0, "target_apy_pp": 4.0, "gain_pp": 0.0,
        "turnover_usd": 0.0, "turnover_frac": 0.0, "cost_usd": 0.0,
    }
    rec["target_positions"] = (dict(rec["current_positions"]) if target is None
                               else dict(target))
    rec.update(kw)
    return rec


def _weighed_rec(offset: int, **kw) -> dict:
    """Запись, где советник ДЕЙСТВИТЕЛЬНО взвешивал альтернативу."""
    return _rec(
        offset,
        gates={"has_legs": True, "gain_above_band": True, "move_turnover_ok": False},
        current={"maple": 25_000.0}, target={"aave_v3": 25_000.0},
        reasons=["move_turnover_over_budget"],
        legs=[{"protocol": "maple", "delta_usd": -25_000.0, "direction": "decrease"},
              {"protocol": "aave_v3", "delta_usd": 25_000.0, "direction": "increase"}],
        turnover_usd=25_000.0, turnover_frac=0.25, cost_usd=50.0,
        gain_pp=1.5, target_apy_pp=5.5, **kw)


# ─────────────────────── разбор одной записи: три исхода ────────────────────


class ClassifyRecord(unittest.TestCase):
    """Цена ошибки тут несимметрична: «не измерено», выданное за «пустой
    совет», есть придуманное наблюдение, а оно опаснее красного вердикта."""

    def test_identical_target_is_named_self_comparison(self):
        outcome, reason = vac.classify_record(_rec(0))
        self.assertEqual((outcome, reason), (vac.SELF_COMPARED, vac.REASON_SELF))

    def test_sub_material_difference_is_named_drift_not_self_comparison(self):
        """17 и 18 записей живых лент отличались на центы начисления — это НЕ
        то же самое, что побайтное равенство, и один исход на два факта
        скрыл бы, что цель не вычисляется вовсе."""
        outcome, reason = vac.classify_record(
            _rec(0, current={"maple": 25_000.0},
                 target={"maple": 25_000.37}))
        self.assertEqual((outcome, reason), (vac.IMMATERIAL_DRIFT, vac.REASON_DRIFT))

    def test_material_legs_are_weighed_with_no_reason(self):
        outcome, reason = vac.classify_record(_weighed_rec(0))
        self.assertEqual((outcome, reason), (vac.WEIGHED, None))

    def test_record_without_gates_is_unmeasured_not_vacuous(self):
        """Схема `shadow-hist-v1` не несёт `gates` вовсе — у `conservative`
        таких записей 24 из 138. Назвать их пустым советом значило бы
        утверждать, что советник ничего не взвесил, тогда как мы не знаем."""
        rec = _rec(0)
        rec.pop("gates")
        outcome, reason = vac.classify_record(rec)
        self.assertEqual((outcome, reason),
                         (vac.RECORD_UNMEASURED, vac.REASON_GATES_UNMEASURED))

    def test_gates_present_without_has_legs_is_unmeasured(self):
        outcome, _ = vac.classify_record(_rec(0, gates={"cooldown_ok": True}))
        self.assertEqual(outcome, vac.RECORD_UNMEASURED)


# ──────────────────────── выдача владельцу: третий исход ────────────────────


class BriefNamesTheOutcome(unittest.TestCase):

    def test_self_comparison_is_declared_by_field_and_named_in_prose(self):
        brief = brief_from_history([_rec(1), _rec(0)])
        self.assertIs(brief["weighed"], False)
        self.assertEqual(brief["not_weighed_reason"], vac.REASON_SELF)
        self.assertIn("совпадает с держимой книгой", brief["why"])

    def test_drift_case_names_its_own_reason(self):
        brief = brief_from_history(
            [_rec(1), _rec(0, current={"maple": 25_000.0},
                           target={"maple": 25_000.37})])
        self.assertEqual(brief["not_weighed_reason"], vac.REASON_DRIFT)

    def test_weighed_record_declares_true_and_names_no_reason(self):
        brief = brief_from_history([_weighed_rec(1), _weighed_rec(0)])
        self.assertIs(brief["weighed"], True)
        self.assertIsNone(brief["not_weighed_reason"])

    def test_missing_gates_declare_unmeasured_not_false(self):
        """ТРЕТИЙ исход у читателя: `None` ≠ `False`. Проверяется `assertIsNone`,
        а не ложность: `False` прошёл бы любую проверку «не истина»."""
        rec = _rec(0)
        rec.pop("gates")
        brief = brief_from_history([_rec(1), rec])
        self.assertIsNone(brief["weighed"])
        self.assertEqual(brief["not_weighed_reason"], vac.REASON_GATES_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", brief["why"])

    def test_numbers_are_not_blanked_by_the_fix(self):
        """Починка ДОБАВЛЯЕТ значение, а не стирает. `gain_pp` у пустой записи
        равен нулю по-настоящему, и подстановка `None` соврала бы в обратную
        сторону — тот же довод уже записан у `_owner_numbers`. Этот тест
        краснеет, если следующая правка решит «честно» погасить три числа §49."""
        brief = brief_from_history([_rec(1), _rec(0)])
        self.assertEqual(brief["yield_gap_pp"], 0.0)
        self.assertIs(brief["numbers_evidenced"], True)
        self.assertEqual(brief["numbers_missing"], [])


class StreakCountsDays(unittest.TestCase):

    def test_many_records_per_day_do_not_inflate_the_day_count(self):
        """Воспроизводит замер дословно: 16 записей в день × 3 дня. Прежняя
        мера напечатала бы «48-й день подряд»."""
        records = [_rec(offset) for offset in (2, 1, 0) for _ in range(16)]
        brief = brief_from_history(records)
        self.assertEqual(brief["unchanged_days"], 3)
        self.assertIn("3-й день", brief["why_now"])
        self.assertNotIn("48", brief["why_now"])

    def test_single_day_many_records_does_not_claim_a_day_streak(self):
        brief = brief_from_history([_rec(0) for _ in range(16)])
        self.assertEqual(brief["unchanged_days"], 1)
        self.assertNotIn("-й день", brief["why_now"])

    def test_record_without_a_date_leaves_the_streak_unmeasured(self):
        """Третий исход у серии: без даты цикла число дней НЕ ИЗМЕРЕНО, и
        подставить туда число записей значило бы вернуть исходный дефект."""
        blind = _rec(0)
        blind.pop("cycle_date")
        brief = brief_from_history([blind, _rec(0)])
        self.assertIsNone(brief["unchanged_days"])
        self.assertIn("не измерено", brief["why_now"].lower())
        self.assertNotIn("-й день", brief["why_now"])

    def test_distinct_days_still_read_as_days(self):
        """Обратная сторона: мера не стала занижать. Пять РАЗНЫХ дней — пять."""
        brief = brief_from_history([_rec(offset) for offset in (4, 3, 2, 1, 0)])
        self.assertEqual(brief["unchanged_days"], 5)
        self.assertIn("5-й день", brief["why_now"])


# ───────────────── причина: цель приходит уже решённой книгой ───────────────


class CauseIsInTheCaller(unittest.TestCase):
    """Почему ног нет ПО ПОСТРОЕНИЮ — закреплено на настоящем писателе, а не
    на пересказе. Это ответ на вопрос карточки
    `inbox-ten-sovetnika-po-perekladke-v-knigah-bal`, и чинить его
    подстановкой цели запрещено: рукавный советник — money-path."""

    def _write(self, root: Path, current: dict, target: dict) -> dict:
        """Пишет настоящим писателем и возвращает ЗАПИСЬ ЛЕНТЫ — именно её
        читают выдача, перепись и приборы; возврат самой функции несёт другую
        форму, и судить по нему значило бы судить не о том, что читают."""
        write_shadow_rationale(
            data_dir=root, current_positions=current, target_positions=target,
            apy_pct={k: 4.0 for k in set(current) | set(target)},
            apy_sources={k: "live" for k in set(current) | set(target)},
            capital_usd=100_000.0, cycle_date=_day(0), run_ts=_stamp(0),
            trades=[], book_id="balanced", write=True)
        lines = (root / history_filename("balanced")).read_text(
            encoding="utf-8").strip().splitlines()
        self.assertTrue(lines, "писатель не оставил ни одной записи в ленте")
        return json.loads(lines[-1])

    def test_handing_the_decided_book_as_target_yields_no_legs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = {"maple": 50_000.0, "fluid_fusdc": 50_000.0}
            rec = self._write(root, book, dict(book))
        self.assertIs(rec["gates"]["has_legs"], False)
        self.assertIn("no_material_legs", rec["reasons"])
        self.assertEqual(vac.classify_record(rec)[1], vac.REASON_SELF)

    def test_an_independent_target_does_produce_legs(self):
        """Обратная сторона того же писателя: при ОТЛИЧНОЙ цели ноги есть —
        значит молчание лент рукавов не свойство писателя, а свойство того,
        что ему передают."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = self._write(root,
                              {"maple": 100_000.0},
                              {"aave_v3": 100_000.0})
        self.assertIs(rec["gates"]["has_legs"], True)
        self.assertTrue(rec["legs"])
        self.assertEqual(vac.classify_record(rec)[0], vac.WEIGHED)


# ───────────────────── перепись ↔ выдача: обе стороны ───────────────────────


def _tape(root: Path, book_id, records) -> None:
    path = root / history_filename(book_id)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in records), encoding="utf-8")


def _one_book_dir(tmp: str, records) -> Path:
    root = Path(tmp)
    _tape(root, None, records)
    return root


class CensusAndProbe(unittest.TestCase):

    def test_green_when_the_real_display_layer_names_the_outcome(self):
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            report = vac.run_census(root)
            self.assertTrue(report["measured"], report.get("reason"))
            self.assertEqual(report["findings"], [])
            verdict, why = ca.PROBES[_PROBE](None, data_dir=str(root))
        self.assertEqual(verdict, ca.SATISFIED, why)

    # ── красная сторона: дособытийная форма выдачи ──────────────────────────

    def _strip(self, *drop):
        """Выдача ровно той формы, что была до починки: настоящий ответ минус
        названные поля. Пересказ формы был бы утверждением о пересказе."""
        def fn(data_dir: Path) -> dict:
            payload = build_books_brief(Path(data_dir))
            for book in payload.values():
                if isinstance(book, dict):
                    for key in drop:
                        book.pop(key, None)
            return payload
        return fn

    def test_red_when_the_vacuity_field_is_absent(self):
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            report = vac.run_census(root, brief_fn=self._strip("weighed"))
            self.assertTrue(report["measured"])
            self.assertEqual([f["finding"] for f in report["findings"]],
                             [vac.F_VACUITY_NOT_NAMED])
            verdict, why = ca.PROBES[_PROBE](
                None, data_dir=str(root), brief_fn=self._strip("weighed"))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)

    def test_red_when_the_streak_field_is_absent(self):
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            report = vac.run_census(root, brief_fn=self._strip("unchanged_days"))
            self.assertEqual([f["finding"] for f in report["findings"]],
                             [vac.F_STREAK_NOT_DECLARED])

    def test_red_when_the_streak_is_counted_in_records(self):
        """Дословный замер: 32 записи на 2 дня. Выдача, объявившая 32,
        краснеет — и это тот самый «323-й день» на 14-дневной серии."""
        def record_count(data_dir: Path) -> dict:
            payload = build_books_brief(Path(data_dir))
            payload["conservative"]["unchanged_days"] = 32
            return payload
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(offset) for offset in (1, 0)
                                       for _ in range(16)])
            report = vac.run_census(root, brief_fn=record_count)
            self.assertEqual([f["finding"] for f in report["findings"]],
                             [vac.F_STREAK_OVERSTATED])
            self.assertIn("лента даёт 2 дн.", report["findings"][0]["detail"])
            verdict, _ = ca.PROBES[_PROBE](None, data_dir=str(root),
                                           brief_fn=record_count)
        self.assertEqual(verdict, ca.NOT_SATISFIED)

    def test_red_when_unmeasured_is_passed_off_as_not_weighed(self):
        """Подмена в сторону оправдания: запись без `gates` подана как
        измеренный пустой совет. Это НЕ та же находка, что отсутствие поля, и
        у неё своё имя."""
        def claims_false(data_dir: Path) -> dict:
            payload = build_books_brief(Path(data_dir))
            payload["conservative"]["weighed"] = False
            payload["conservative"]["not_weighed_reason"] = vac.REASON_SELF
            return payload
        blind = _rec(0)
        blind.pop("gates")
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), blind])
            report = vac.run_census(root, brief_fn=claims_false)
            self.assertEqual([f["finding"] for f in report["findings"]],
                             [vac.F_UNMEASURED_AS_FALSE])

    def test_red_when_prose_says_it_but_the_field_claims_weighed(self):
        """Проба не проходит ПОДСТРОКОЙ (ADR-333): проза может честно сказать
        «материальных ног нет», а поле — объявить взвешенный HOLD, и читают
        поле API и дашборд, а не прозу."""
        def lies_in_the_field(data_dir: Path) -> dict:
            payload = build_books_brief(Path(data_dir))
            payload["conservative"]["weighed"] = True
            payload["conservative"]["not_weighed_reason"] = None
            return payload
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            brief = lies_in_the_field(root)
            self.assertIn("материальных ног нет", brief["conservative"]["how_much"])
            verdict, why = ca.PROBES[_PROBE](None, data_dir=str(root),
                                             brief_fn=lies_in_the_field)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)

    def test_red_when_the_reason_is_dropped_but_the_flag_stays(self):
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            report = vac.run_census(root, brief_fn=self._strip("not_weighed_reason"))
            self.assertEqual([f["finding"] for f in report["findings"]],
                             [vac.F_VACUITY_NOT_NAMED])
            self.assertIn("ПРИЧИНУ не назвала", report["findings"][0]["detail"])

    # ── третий исход самой пробы ────────────────────────────────────────────

    def test_unmeasured_when_no_tape_exists_names_the_tape_as_the_door(self):
        """Третий исход обязан назвать ДВЕРЬ, за которой он случился (ADR-761):
        «лента не прочитана» и «выдача по книге не прочитана» ведут к разным
        починкам, и общего слова «не прочитана» для вердикта мало — мутант,
        снявший раннюю ветку, проходил через позднюю и оставался незамеченным
        (замер мутаций #881: выжил 1 из 13 ровно на этом)."""
        with TemporaryDirectory() as tmp:
            report = vac.run_census(Path(tmp))
            verdict, why = ca.PROBES[_PROBE](None, data_dir=tmp)
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("ни одна лента вердиктов не прочитана", why)
        self.assertEqual(sorted(report["unreadable"]),
                         ["aggressive", "balanced", "conservative"])

    def test_unmeasured_when_the_tape_is_stale(self):
        """Часы — ВХОД: сдвиг `now` вперёд обязан перевести вердикт в «не
        измерено», а не оставить зелёным замер о прошлом. Сдвиг вычислен от
        самих отметок, литеральной даты в фикстуре нет."""
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            fresh, _ = ca.PROBES[_PROBE](None, data_dir=str(root))
            later = datetime.now(timezone.utc) + timedelta(
                hours=ca._VACUOUS_ADVICE_MAX_AGE_H + 2)
            stale, why = ca.PROBES[_PROBE](None, data_dir=str(root), now=later)
        self.assertEqual(fresh, ca.SATISFIED)
        self.assertEqual(stale, ca.UNMEASURED)
        self.assertIn("протухла", why)

    def test_unmeasured_when_the_display_layer_raises(self):
        def explodes(data_dir: Path) -> dict:
            raise RuntimeError("слой отображения упал")
        with TemporaryDirectory() as tmp:
            root = _one_book_dir(tmp, [_rec(1), _rec(0)])
            verdict, why = ca.PROBES[_PROBE](None, data_dir=str(root),
                                             brief_fn=explodes)
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("НЕ измерено", why)

    def test_probe_is_registered_under_its_own_name(self):
        """Проба, потерявшая регистрацию, не меряет ничего: очередь объявляет
        критерий по РЕЕСТРУ, а не по наличию функции в модуле."""
        self.assertIn(_PROBE, ca.PROBES)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ───────────── проводка: у прибора обязан быть СТОЯЧИЙ читатель ─────────────


class Wiring(unittest.TestCase):
    """Почему проводка проверяется тестом, а не доверием.

    Проба приёмки `shadow_brief_names_the_unweighed_hold` зовётся шагом 0-офис
    только по ОТКРЫТЫМ карточкам (`card_acceptance.OPEN_STATUSES`), а карточка
    предмета закрыта тем же циклом #881 — то есть без ступени моста замер
    перестал бы делаться ровно тогда, когда перестал бы быть очевидным. Это
    самый частый дефект этого проекта: «прибор есть, читателя нет». И урок
    ADR-412 рядом: СТРОКА В ПРОМПТЕ НЕ ЕСТЬ ВЫЗОВ — поэтому ниже проверяется
    не объявление состава, а настоящий вызов в теле `main()`.
    """

    def test_card_acceptance_does_not_re_measure_closed_cards(self):
        """Предпосылка всей этой проводки — замером, а не рассуждением."""
        self.assertNotIn("done", ca.OPEN_STATUSES)

    def test_stage_is_declared_in_the_bridge_contract(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("vacuous_advice_census", fb.CENSUS_STAGE)
        entry = fb.CENSUS_PRODUCT["vacuous_advice_census"]
        self.assertEqual(entry["module"], vac.PRODUCER)
        self.assertEqual(entry["artifact"], f"data/{vac.ARTIFACT}")
        self.assertIn(f"data/{vac.ARTIFACT}", fb.PRODUCES)

    def test_stage_is_actually_called_in_main(self):
        """Разбором тела `main()`, а не наличием имени в файле: имя в списке и
        зов — разные утверждения, и именно на этом ADR-412 измерил, что
        автоматического зова не было НИ ОДНОГО."""
        import ast
        src = Path(vac.__file__).resolve().parents[1] / "monitoring" / "findings_bridge.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = {
            ast.unparse(n.func)
            for n in ast.walk(main) if isinstance(n, ast.Call)
        }
        self.assertTrue(any(c.endswith(".run") and "vac_adv" in c for c in called),
                        f"ступень не зовётся в main(); найдены вызовы: "
                        f"{sorted(c for c in called if 'run' in c)[:8]}")

    def test_artifact_is_declared_in_the_constitution_with_a_tact(self):
        root = Path(vac.__file__).resolve().parents[2]
        manifest = json.loads((root / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        decl = [a for a in manifest["artifacts"]
                if a.get("path") == f"data/{vac.ARTIFACT}"]
        self.assertEqual(len(decl), 1, "артефакт объявлен не ровно один раз")
        self.assertEqual(decl[0]["producer"], "com.spa.decision_loop")
        self.assertTrue(decl[0]["slo_hours"] > 0,
                        "без срока годности сторож свежести не способен "
                        "сказать, что ступень замолчала")

    def test_office_step_renders_the_artifact_not_just_opens_it(self):
        """Артефакт, прочитанный ВХОЛОСТУЮ, — тот же дефект, что измеряет сам
        прибор: файл открыт, а в контекст не попадает ни одно число."""
        office = (Path(vac.__file__).resolve().parents[2]
                  / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn(f'"{vac.ARTIFACT}": (', office, "схема артефакта не объявлена")
        self.assertIn(vac.PRODUCER, office, "производитель не назван")
        self.assertIn("from spa_core.monitoring.vacuous_advice_census import format_report",
                      office, "отрисовка не делегирована производителю")

    def test_run_writes_the_artifact_and_names_the_third_outcome(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            blind = vac.run(root, write=True)
            self.assertFalse(blind["measured"])
            self.assertEqual(blind["doc"]["status"], "UNMEASURED")
            self.assertIn("ни одна лента вердиктов не прочитана",
                          str(blind["doc"]["reason"]))
            _tape(root / "data", None, [_rec(1), _rec(0)])
            ok = vac.run(root, write=True)
            self.assertTrue(ok["measured"])
            self.assertEqual(ok["doc"]["status"], "OK")
            self.assertEqual(ok["doc"]["findings"], [])
            # Читается ИМЕННО записанный файл, пока стенд ещё жив: вердикт в
            # памяти не доказывает, что артефакт лёг на диск, — а читает его
            # шаг 0-офис именно с диска.
            written = json.loads(Path(ok["artifact"]).read_text(encoding="utf-8"))
        self.assertEqual(written["generated_by"], vac.PRODUCER)
        self.assertTrue(written["what_it_does_not_prove"],
                        "прибор обязан называть, о чём он НЕ докладывает")

    def test_status_is_finding_when_the_reader_drops_the_field(self):
        """Третий исход и находка — РАЗНЫЕ статусы: `FINDING` требует действия,
        `UNMEASURED` требует починить замер, и слить их значило бы потерять
        различие, ради которого прибор написан."""
        def strip(data_dir: Path) -> dict:
            payload = build_books_brief(Path(data_dir))
            for book in payload.values():
                if isinstance(book, dict):
                    book.pop("weighed", None)
            return payload
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            _tape(root / "data", None, [_rec(1), _rec(0)])
            out = vac.run(root, write=False, brief_fn=strip)
        self.assertEqual(out["doc"]["status"], "FINDING")
        self.assertTrue(out["measured"], "находка не есть «не измерено»")
