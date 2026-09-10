"""Приёмка прибора «почему у ноги нет живой ставки» (заказ #543, ADR-300).

Каждый тест — положительный контроль на конкретное свойство, а не украшение:
набор писался так, чтобы мутация по координате в
`spa_core/monitoring/unevidenced_leg_causes.py` красила хотя бы один тест.

Четыре свойства закрыты отдельно и намеренно, потому что именно на них прибор
такого рода врёт молча:

1. **порядок разбора класса** — сперва книги дня, потом провенанс. Обратный
   порядок отнёс бы ногу ВНЕ книг к перебою эвиденса, то есть ровно к той
   причине, которую заказ велел проверить;
2. **выдача идёт по ПАРЕ (день, нога), а не по ключу** — одна нога бывает разных
   классов в разные дни, и выдача по ключу приписала бы классу чужие дни;
3. **третий исход обязателен** — запись без `apy_unevidenced` не разводит второй
   класс с третьим, и такая пара идёт в отдельный счёт, а не в правдоподобный;
4. **ловушка заказа** — `adapter_status.json` не читается вовсе, `hit_rate` не
   считается вовсе.

FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром
`now=` в `measure`/`run` (константа `FIXED_NOW` ниже и второй литерал в
`test_clock_is_an_input` передаются туда же), поэтому ни одно утверждение набора
не зависит от календаря. Даты в фикстурах (`2026-08-01` и соседи) — ИМЕНА строк
журнала: по ним `load_history` сортирует и разрешает повтор дня, свойством
свежести они не являются.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят
# параметром: FIXED_NOW (и второй литерал в ClockIsAnInput) передаются в
# measure(..., now=) и run(..., now=), поэтому ни одно утверждение набора не
# зависит от календаря. Даты в фикстурах (`2026-08-01` и соседи) — ИМЕНА строк
# журнала решений: по ним load_history сортирует и разрешает повтор дня,
# свойством свежести они не являются.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.monitoring import unevidenced_leg_causes as ulc
from spa_core.paper_trading import shadow_trigger_eval as ste

#: Часы прибора — вход, а не окружение (правило `.claude/rules/deployment.md`).
FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

#: Нога, которую фикстуры двигают и не оценивают.
LEG = "spark_susds"
#: Вторая такая же — нужна сценам, где ОДНОЙ ноги недостаточно, чтобы отличить
#: выдачу по паре от выдачи по ключу.
LEG_2 = "sfrax"
#: Нога, оценённая ВСЕГДА: она держит «день выпал ровно из-за названной ноги».
ANCHOR = "aave_v3"


def _day(date: str, *, current: dict | None = None, target: dict | None = None,
         apys: dict | None = None, unevidenced: list | None = None,
         drop_unevidenced_key: bool = False) -> dict:
    """Одна строка журнала решений в форме настоящего писателя."""
    row = {
        "cycle_date": date,
        "verdict": "HOLD",
        "schema": "shadow-hist-v2",
        "capital_usd": 100_000.0,
        "cost_usd": 50.0,
        "turnover_usd": 20_000.0,
        "current_positions": current if current is not None else {ANCHOR: 20_000.0},
        "target_positions": target if target is not None else {LEG: 20_000.0},
        "apy_evidenced_pct": apys if apys is not None else {},
        "apy_unevidenced": list(unevidenced or []),
    }
    if drop_unevidenced_key:
        row.pop("apy_unevidenced")
    return row


def _write(data_dir: Path, rows: list[dict]) -> None:
    (data_dir / "allocation_rationale_history.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _forward_absent(date: str) -> dict:
    """forward-день, где LEG вне книг: класс `absent_from_forward_books`."""
    return _day(date, current={ANCHOR: 20_000.0}, target={ANCHOR: 20_000.0},
                apys={ANCHOR: 4.0})


def _forward_not_live(date: str, leg: str = LEG) -> dict:
    """forward-день, где нога В книгах, но провенанс не `live`."""
    return _day(date, current={ANCHOR: 20_000.0, leg: 10_000.0},
                target={ANCHOR: 20_000.0, leg: 10_000.0},
                apys={ANCHOR: 4.0}, unevidenced=[leg])


def _forward_live_null(date: str) -> dict:
    """forward-день, где нога в книгах, провенанс живой, а ставки нет."""
    return _day(date, current={ANCHOR: 20_000.0, LEG: 10_000.0},
                target={ANCHOR: 20_000.0, LEG: 10_000.0},
                apys={ANCHOR: 4.0}, unevidenced=[])


def _decision(date: str = "2026-08-01") -> dict:
    """День решения: двигает ANCHOR → LEG, оба попадают в `deltas`."""
    return _day(date, current={ANCHOR: 20_000.0}, target={LEG: 20_000.0},
                apys={ANCHOR: 4.0, LEG: 5.0}, unevidenced=[])


def _tail(start_day: int, count: int) -> list[dict]:
    """Хвост полностью оценённых дней — чтобы окно горизонта было полным."""
    return [_day(f"2026-08-{d:02d}", current={ANCHOR: 20_000.0},
                 target={ANCHOR: 20_000.0}, apys={ANCHOR: 4.0})
            for d in range(start_day, start_day + count)]


class ClassificationReadsTheRecord(unittest.TestCase):
    """Класс причины читается из записи — и в том порядке, в каком отсекает писатель."""

    def test_leg_outside_the_books_is_absent_not_an_evidence_outage(self):
        """Порядок разбора: книги ПЕРЕД провенансом.

        Сцена намеренно противоречивая: ногу нет в книгах, а в `apy_unevidenced`
        она названа. Спроси прибор о провенансе первым — он отнёс бы её к
        перебою эвиденса, то есть подтвердил бы ту самую причину, которую заказ
        послал проверять.
        """
        frec = _day("2026-08-02", current={ANCHOR: 1.0}, target={ANCHOR: 1.0},
                    apys={ANCHOR: 4.0}, unevidenced=[LEG])
        self.assertEqual(ulc.classify_pair(frec, LEG), ulc.CLASS_ABSENT)

    def test_leg_in_books_and_named_unevidenced_is_an_evidence_outage(self):
        self.assertEqual(ulc.classify_pair(_forward_not_live("2026-08-02"), LEG),
                         ulc.CLASS_NOT_LIVE)

    def test_leg_in_books_with_live_provenance_and_no_value_is_its_own_class(self):
        self.assertEqual(ulc.classify_pair(_forward_live_null("2026-08-02"), LEG),
                         ulc.CLASS_LIVE_NULL)

    def test_record_without_the_census_key_is_unattributable_not_a_guess(self):
        """Третий исход: старая схема не разводит перебой от пустого значения."""
        frec = _day("2026-08-02", current={ANCHOR: 1.0, LEG: 1.0},
                    target={ANCHOR: 1.0, LEG: 1.0}, apys={ANCHOR: 4.0},
                    drop_unevidenced_key=True)
        self.assertEqual(ulc.classify_pair(frec, LEG), ulc.CLASS_UNATTRIBUTABLE)


class GrantIsPairWise(unittest.TestCase):
    """Выдача идёт по паре (день, нога). По ключу она приписала бы классу чужие дни."""

    def _scene(self, data_dir: Path) -> dict:
        """Сцена, где ответ по ключу и ответ по паре РАЗЛИЧАЮТСЯ.

        forward №1: LEG вне книг (absent), LEG_2 оценён.
        forward №2: LEG в книгах без провенанса (not_live), LEG_2 вне книг (absent).

        Выдача по ПАРЕ класса `not_live` = {(день2, LEG)}: ни один forward-день
        не покрыт целиком ⇒ день НЕ поднимается. Выдача по КЛЮЧУ = {LEG}
        покрыла бы forward №1 целиком и подняла бы день — ответ разошёлся бы на
        целый день из шести.
        """
        decision = _day("2026-08-01", current={ANCHOR: 20_000.0},
                        target={LEG: 10_000.0, LEG_2: 10_000.0},
                        apys={ANCHOR: 4.0}, unevidenced=[])
        f1 = _day("2026-08-02", current={ANCHOR: 20_000.0, LEG_2: 10_000.0},
                  target={ANCHOR: 20_000.0, LEG_2: 10_000.0},
                  apys={ANCHOR: 4.0, LEG_2: 5.0}, unevidenced=[])
        f2 = _day("2026-08-03", current={ANCHOR: 20_000.0, LEG: 10_000.0},
                  target={ANCHOR: 20_000.0, LEG: 10_000.0},
                  apys={ANCHOR: 4.0}, unevidenced=[LEG])
        _write(data_dir, [decision, f1, f2] + _tail(4, 7))
        return ulc.measure(data_dir, now=FIXED_NOW)

    def test_evidence_outage_alone_does_not_recover_the_day(self):
        """Ноль здесь обязан быть ИЗМЕРЕННЫМ, а не следствием отказа.

        Утверждать `days_recovered == 0` мало: при разошедшихся выводах день
        тоже не попадает в список — и мутация «выдавать по КЛЮЧУ» пережила бы
        проверку, разведя выводы вместо того, чтобы соврать числом (замер #544:
        она и пережила первую редакцию этого теста). Поэтому согласие выводов
        утверждается ЯВНО и рядом.
        """
        with TemporaryDirectory() as td:
            doc = self._scene(Path(td))
            self.assertEqual(doc["population"]["days_unchecked_by_unpriced_legs"], 1)
            self.assertTrue(doc["derivation_cross_check"]["passed"],
                            "выводы разошлись — ноль ниже не измерен, а получен отказом")
            self.assertNotEqual(doc["status"], ulc.STATUS_UNMEASURED)
            self.assertEqual(
                doc["scenarios"][ulc.CLASS_NOT_LIVE]["days_recovered"], 0,
                "выдача по КЛЮЧУ подняла бы этот день — значит выдача не по паре")

    def test_partial_cover_of_a_forward_day_is_not_a_cover(self):
        """Подмножество, а не пересечение: сцена с ДВУМЯ ногами в один день.

        При одной блокирующей ноге на forward-день «подмножество» и
        «непустое пересечение» неотличимы, и ослабление условия проходит
        незамеченным (тот же класс, что мутация #543). Здесь у forward-дня
        08-03 неоценённых ног ДВЕ, а выдаётся ОДНА.
        """
        with TemporaryDirectory() as td:
            doc = self._scene(Path(td))
            deltas = ste._deltas(json.loads(
                (Path(td) / "allocation_rationale_history.jsonl")
                .read_text(encoding="utf-8").splitlines()[0]))
            f2 = json.loads((Path(td) / "allocation_rationale_history.jsonl")
                            .read_text(encoding="utf-8").splitlines()[2])
            self.assertEqual(len(ulc._missing_legs(deltas, f2)), 2,
                             "сцена перестала быть сценой: ног в forward-дне не две")
            self.assertFalse(ulc._structural_recovers(
                deltas, [f2], 7, {("2026-08-03", LEG)}),
                "частичное покрытие ног принято за полное")
            self.assertTrue(doc["derivation_cross_check"]["passed"])

    def test_the_same_scene_is_recovered_when_everything_is_granted(self):
        """Обратная половина: сцена не «не поднимается никогда»."""
        with TemporaryDirectory() as td:
            doc = self._scene(Path(td))
            self.assertEqual(doc["scenarios"]["ALL"]["days_recovered"], 1)


class HorizonIsRespected(unittest.TestCase):
    """Структурный вывод не смеет смотреть дальше, чем смотрит оценщик."""

    def test_a_leg_priced_only_beyond_the_horizon_does_not_recover_the_day(self):
        """Сцена: семь forward-дней слепы, восьмой — зрячий, но он ЗА окном.

        Сними прибор срез `[:horizon]` — структурный вывод нашёл бы восьмой
        день и объявил день восстановимым, тогда как `_evaluate_verdict` его не
        видит вовсе. Ошибка была бы не в числе, а в ОКНЕ.
        """
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + [_day("2026-08-09", current={ANCHOR: 20_000.0, LEG: 10_000.0},
                           target={ANCHOR: 20_000.0, LEG: 10_000.0},
                           apys={ANCHOR: 4.0, LEG: 5.0}, unevidenced=[])]
                   + _tail(10, 2))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertTrue(doc["derivation_cross_check"]["passed"])
            self.assertNotEqual(doc["status"], ulc.STATUS_UNMEASURED)
            deltas = ste._deltas(_decision())
            forward = [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)] + [
                _day("2026-08-09", current={ANCHOR: 20_000.0, LEG: 10_000.0},
                     target={ANCHOR: 20_000.0, LEG: 10_000.0},
                     apys={ANCHOR: 4.0, LEG: 5.0}, unevidenced=[])]
            self.assertFalse(
                ulc._structural_recovers(deltas, forward, 7, set()),
                "структурный вывод заглянул за горизонт оценщика")
            self.assertTrue(
                ulc._structural_recovers(deltas, forward, 8, set()),
                "обратная половина: за расширенным окном день и правда виден")


class ControlsRefuseInsteadOfReporting(unittest.TestCase):
    """Каждый контроль обязан УМЕТЬ не сработать — иначе он украшение."""

    def _blocking_journal(self, data_dir: Path) -> None:
        _write(data_dir, [_decision()]
               + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
               + _tail(9, 3))

    def test_baseline_scene_is_measured(self):
        """Опора для трёх тестов ниже: без мутаций сцена ИЗМЕРЯЕТСЯ."""
        with TemporaryDirectory() as td:
            self._blocking_journal(Path(td))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["status"], ulc.STATUS_CRITICAL)
            self.assertTrue(doc["parity_control"]["passed"])
            self.assertTrue(doc["all_causes_closure"]["passed"])
            self.assertTrue(doc["derivation_cross_check"]["passed"])

    def test_a_broken_reading_of_the_pricing_rule_refuses(self):
        """Паритет: своё прочтение разошлось с настоящим `_day_gain_usd`."""
        with TemporaryDirectory() as td:
            self._blocking_journal(Path(td))
            with mock.patch.object(ulc, "_missing_legs", return_value=[]):
                doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["status"], ulc.STATUS_UNMEASURED)
            self.assertFalse(doc["parity_control"]["passed"])
            self.assertNotIn("class_counts", doc,
                             "числа по классам не смеют печататься после отказа")

    def test_evidence_outage_alone_can_recover_a_day_so_a_zero_is_honest(self):
        """НАСТОЯЩИЙ контроль способности — на данных, а не мутацией.

        В живом журнале класс «перебой эвиденса» поднимает мало дней. Чтобы этот
        малый счёт был ответом, а не немотой прибора, нужна сцена, где он
        поднимает день ОДИН: не подними он и здесь — ноль на живых данных
        означал бы «прибор не умеет», а не «причина не та».
        """
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_not_live(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["class_counts"][ulc.CLASS_NOT_LIVE], 7)
            self.assertEqual(doc["scenarios"][ulc.CLASS_NOT_LIVE]["days_recovered"], 1)
            self.assertEqual(doc["scenarios"][ulc.CLASS_ABSENT]["days_recovered"], 0)

    def test_a_grant_that_grants_nothing_is_caught_by_the_cross_check(self):
        """Обезвреженная выдача ловится сверкой выводов — раньше замыкания.

        Порядок назван намеренно: структурный вывод выдачи не зовёт, реплей
        зовёт, поэтому обезвреженный `grant_pricing_pairs` разводит два вывода.
        Замыкание при этом не считается вовсе — и это верно: после расхождения
        числа недействительны, а печатать их «на всякий случай» значило бы
        предъявить измеренное там, где измерения не было.
        """
        with TemporaryDirectory() as td:
            self._blocking_journal(Path(td))
            with mock.patch.object(ulc, "grant_pricing_pairs",
                                   side_effect=lambda fw, granted: list(fw)):
                doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["status"], ulc.STATUS_UNMEASURED)
            self.assertFalse(doc["derivation_cross_check"]["passed"])
            self.assertNotIn("all_causes_closure", doc)

    def test_the_closure_says_out_loud_what_it_does_not_prove(self):
        """Замыкание не смеет называться контролем способности."""
        with TemporaryDirectory() as td:
            self._blocking_journal(Path(td))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertTrue(doc["all_causes_closure"]["passed"])
            self.assertIn("НЕ контроль способности",
                          doc["all_causes_closure"]["what_it_does_not_prove"])

    def test_two_derivations_disagreeing_refuses(self):
        with TemporaryDirectory() as td:
            self._blocking_journal(Path(td))
            with mock.patch.object(ulc, "_structural_recovers", return_value=True):
                doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["status"], ulc.STATUS_UNMEASURED)
            self.assertFalse(doc["derivation_cross_check"]["passed"])
            self.assertNotIn("all_causes_closure", doc)

    def test_an_empty_journal_refuses_with_a_named_reason(self):
        with TemporaryDirectory() as td:
            (Path(td) / "allocation_rationale_history.jsonl").write_text("", encoding="utf-8")
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["status"], ulc.STATUS_UNMEASURED)
            self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))


class PopulationIsNotBorrowed(unittest.TestCase):
    """Доля обязана считаться на СВОЁМ населении."""

    def test_a_day_without_forward_data_is_counted_apart(self):
        """Последний день окна теряет вердикт не из-за ставки — и не в население."""
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + [_day("2026-08-09", current={ANCHOR: 20_000.0},
                           target={LEG: 20_000.0}, apys={ANCHOR: 4.0})])
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertIn("2026-08-09", doc["population"]["beyond_list"])
            self.assertNotIn("2026-08-09", doc["population"]["days_list"])

    def test_the_corroborating_census_spans_the_whole_journal(self):
        """Опора считается по всем дням, а не только по блокирующим.

        Сцена: единственная нога-день без ставки внутри книг лежит в дне, который
        НИКОГО не блокирует. Считай прибор опору по населению блокирующих дней —
        он вернул бы ноль.
        """
        with TemporaryDirectory() as td:
            rows = ([_decision()]
                    + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                    + [_forward_not_live("2026-08-09")] + _tail(10, 2))
            _write(Path(td), rows)
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            census = doc["in_books_unpriced_census"]
            self.assertGreaterEqual(census["leg_days_unpriced"], 1)
            self.assertTrue(any(x.endswith(f":{LEG}") and x.startswith("2026-08-09")
                                for x in census["unpriced_examples"]))


class NamedTrapsOfTheOrder(unittest.TestCase):
    """Ловушки, названные заказом заранее, — закреплены тестом, а не обещанием."""

    def test_the_module_never_opens_adapter_status(self):
        """Провенанс принадлежит ЗНАЧЕНИЮ; этот файл его не несёт вовсе.

        Мерится ПУТЬ, а не слово: имя файла законно стои́т в прозе
        `does_not_report` — тем она и ценна, что называет невзятую дорогу вслух.
        Запрещено другое — литерал, которым файл можно ОТКРЫТЬ. Проверка идёт по
        AST, поэтому покраснеет и на `Path(data_dir) / "adapter_status.json"`, и
        на склейке через переменную-имя.
        """
        import ast

        tree = ast.parse(Path(ulc.__file__).read_text(encoding="utf-8"))
        openable = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value.startswith("adapter_status")]
        self.assertEqual(openable, [],
                         "прибор потянулся к файлу, который не несёт провенанса "
                         f"ЗНАЧЕНИЯ: {openable}")

    def test_hit_rate_is_never_computed_anywhere_in_the_artifact(self):
        """Ловушка ADR-300: доля после расширения посчитана на другом населении.

        Запрещено ЧИСЛО, а не слово: назвать чужой критерий в прозе находки
        («ADR-300 отнёс недоизмеренность hit_rate к…») — это ссылка на
        утверждение, которое прибор опровергает, и запрещать её значило бы
        запретить сам ответ. Поэтому ищется КЛЮЧ по всему дереву артефакта: под
        сентинелом посчитанная доля жила бы именно ключом.
        """
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)

            def keys(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        yield k
                        yield from keys(v)
                elif isinstance(o, list):
                    for v in o:
                        yield from keys(v)

            self.assertNotIn("hit_rate", set(keys(doc)))

    def test_the_sentinel_grants_the_right_to_be_judged_and_no_yield(self):
        frec = _forward_absent("2026-08-02")
        granted = ulc.grant_pricing_pairs([frec], {("2026-08-02", LEG)})
        self.assertEqual(granted[0]["apy_evidenced_pct"][LEG], 0.0)
        self.assertEqual(ulc._PRICING_SENTINEL_PCT, 0.0)
        gain, missing = ste._day_gain_usd({LEG: 20_000.0},
                                          granted[0]["apy_evidenced_pct"])
        self.assertEqual(missing, [])
        self.assertEqual(gain, 0.0, "сентинел внёс в benefit не ноль")

    def test_perturbation_does_not_touch_the_baseline_record(self):
        """Копия глубокая: иначе паритет сравнивал бы возмущённое с возмущённым."""
        frec = _forward_absent("2026-08-02")
        ulc.grant_pricing_pairs([frec], {("2026-08-02", LEG)})
        self.assertNotIn(LEG, frec["apy_evidenced_pct"])

    def test_the_report_calls_its_day_counts_a_ceiling(self):
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertTrue(any("ПОТОЛОК" in f for f in doc["findings"]),
                            "число под сентинелом подано как обещание, а не как "
                            "верхняя граница")

    def test_the_unreported_subclass_is_declared_out_loud(self):
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertIn("adapter_status.json", doc["does_not_report"])


class AnswerIsPerDayAndByName(unittest.TestCase):
    """Прямое требование заказа: по дням и по причинам поимённо, не одной долей."""

    def test_each_blocking_day_is_listed_with_its_legs_and_classes(self):
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(len(doc["per_day"]), 1)
            row = doc["per_day"][0]
            self.assertEqual(row["decision_date"], "2026-08-01")
            self.assertIn(LEG, row["legs"])
            self.assertEqual(row["classes"], [ulc.CLASS_ABSENT])
            self.assertTrue(any(f.startswith("[ПО ДНЯМ]") for f in doc["findings"]))

    def test_every_blocking_pair_names_both_dates(self):
        """Пара — это (день решения, forward-день, нога); дня решения мало."""
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertTrue(doc["attribution"])
            for pair in doc["attribution"]:
                self.assertIn("decision_date", pair)
                self.assertIn("forward_date", pair)
                self.assertIn(pair["class"], ulc.ALL_CLASSES)

    def test_classify_pair_is_total_over_malformed_records_too(self):
        """Разбиение держится ТОТАЛЬНОСТЬЮ разборщика, а не сложением в отчёте.

        Равенство `сумма классов == число пар` при работающем разборщике верно
        ПО ПОСТРОЕНИЮ (замер #544: мутация «контроль всегда зелёный» пережила
        первую редакцию этого теста, и правильно сделала). Настоящее свойство —
        что `classify_pair` возвращает класс из набора на ЛЮБОМ входе, включая
        покорёженную запись: вернись он `None`, пара пропала бы молча.
        """
        wrecks = [
            {},
            {"current_positions": None, "target_positions": None},
            {"current_positions": {LEG: 1.0}, "apy_unevidenced": None},
            {"current_positions": {LEG: 1.0}, "apy_unevidenced": [LEG]},
            {"target_positions": {LEG: 1.0}, "apy_unevidenced": []},
            {"current_positions": "не словарь", "apy_unevidenced": []},
        ]
        for rec in wrecks:
            with self.subTest(rec=rec):
                self.assertIn(ulc.classify_pair(rec, LEG), ulc.ALL_CLASSES)

    def test_the_partition_closure_says_out_loud_what_it_does_not_prove(self):
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertTrue(doc["partition_closure"]["passed"])
            self.assertEqual(sum(doc["class_counts"].values()), doc["pairs_total"])
            self.assertIn("по построению",
                          doc["partition_closure"]["what_it_does_not_prove"])

    def test_a_journal_with_no_blocking_day_says_so_instead_of_dividing_by_zero(self):
        with TemporaryDirectory() as td:
            _write(Path(td), _tail(1, 10))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["status"], ulc.STATUS_OK)
            self.assertEqual(doc["population"]["days_unchecked_by_unpriced_legs"], 0)

    def test_an_unattributable_pair_never_hides_inside_a_plausible_class(self):
        with TemporaryDirectory() as td:
            _write(Path(td), [_decision()]
                   + [_day(f"2026-08-{d:02d}",
                           current={ANCHOR: 20_000.0, LEG: 10_000.0},
                           target={ANCHOR: 20_000.0, LEG: 10_000.0},
                           apys={ANCHOR: 4.0}, drop_unevidenced_key=True)
                      for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.measure(Path(td), now=FIXED_NOW)
            self.assertEqual(doc["class_counts"][ulc.CLASS_UNATTRIBUTABLE], 7)
            self.assertEqual(doc["class_counts"][ulc.CLASS_NOT_LIVE], 0)
            self.assertEqual(doc["status"], ulc.STATUS_WARNING)
            self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))


class ClockIsAnInput(unittest.TestCase):
    def test_clock_is_an_input(self):
        other = datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        with TemporaryDirectory() as td:
            _write(Path(td), _tail(1, 4))
            self.assertEqual(ulc.measure(Path(td), now=other)["generated_at"],
                             other.isoformat())


class WiredAtBirth(unittest.TestCase):
    """Прибор без читателя — не прибор (правило «новый скрипт проводится при рождении»).

    Каждая точка проводки проверяется ОТДЕЛЬНО и по СТРУКТУРЕ, а не поиском
    подстроки по файлу: имя прибора встречается в файле несколько раз, поэтому
    «строка есть где-то» зеленеет и после снятия конкретной записи (замер #544 —
    так пережили первую редакцию пять мутаций проводки из пяти).
    """

    ROOT = Path(__file__).resolve().parents[2]
    ARTIFACT = f"data/{ulc.OUTPUT_FILENAME}"

    def test_the_bridge_declares_the_artifact_among_its_products(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn(self.ARTIFACT, fb.PRODUCES)

    def test_the_bridge_maps_the_artifact_to_its_producing_module(self):
        from spa_core.monitoring import findings_bridge as fb
        entry = fb.CENSUS_PRODUCT.get("unevidenced_leg_causes")
        self.assertIsNotNone(entry, "производителя нет в карте моста")
        self.assertEqual(entry["artifact"], self.ARTIFACT)
        self.assertEqual(entry["module"],
                         "spa_core/monitoring/unevidenced_leg_causes.py")

    def test_the_bridge_names_it_in_the_census_stage(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("unevidenced_leg_causes", fb.CENSUS_STAGE)

    def test_the_office_step_knows_the_schema_and_the_producer(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_cor_probe", self.ROOT / "scripts/consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIn(ulc.OUTPUT_FILENAME, mod._READ_SCHEMA)
        for key in ("attribution", "per_day", "class_counts", "parity_control"):
            self.assertIn(key, mod._READ_SCHEMA[ulc.OUTPUT_FILENAME],
                          "заказ требовал ответ ПОИМЁННО — ключ обязан быть в схеме")
        self.assertEqual(mod._PRODUCER.get(ulc.OUTPUT_FILENAME),
                         "spa_core/monitoring/unevidenced_leg_causes.py")

    def test_the_office_step_actually_renders_the_artifact(self):
        """Ветка отрисовки — не строка в файле, а исполняемый путь.

        Снятие ветки не меняет ни схемы, ни карты производителя; поймать его
        можно только вызвав дispatcher и посмотрев, вернул ли он строки прибора.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_cor_probe2", self.ROOT / "scripts/consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            _write(data, [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.run(root=td, now=FIXED_NOW, write=False)
            lines = mod._summarize_json(
                str(data / ulc.OUTPUT_FILENAME), doc, now=FIXED_NOW)
        text = "\n".join(lines)
        self.assertIn("заказ #543", text,
                      "шаг 0-офис не отрисовал прибор — строки чужие или пустые")

    def test_the_artifact_home_is_both_manifest_entries(self):
        """Дом артефакта — ДВЕ записи: реестр `artifacts[]` И паспорт агента.

        Снятие любой из них по отдельности обязано краснить: проверка «имя
        встречается в манифесте» зеленела бы, пока цела вторая.
        """
        doc = json.loads((self.ROOT / "architecture/manifest.json").read_text(
            encoding="utf-8"))
        art = [a for a in doc["artifacts"] if a.get("path") == self.ARTIFACT]
        self.assertEqual(len(art), 1, "нет записи в реестре artifacts[]")
        self.assertEqual(art[0]["producer"], "com.spa.decision_loop")

        agent = next(a for a in doc["agents"]
                     if a.get("label") == "com.spa.decision_loop")
        produced = [p for p in agent["produces"] if p.get("artifact") == self.ARTIFACT]
        self.assertEqual(len(produced), 1, "нет записи в produces[] паспорта агента")

    def test_run_returns_the_shape_the_bridge_expects(self):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            _write(data, [_decision()]
                   + [_forward_absent(f"2026-08-{d:02d}") for d in range(2, 9)]
                   + _tail(9, 3))
            doc = ulc.run(root=td, now=FIXED_NOW, write=False)
            self.assertIn("overall", doc)
            for key in ("critical", "warn", "info", "unchecked"):
                self.assertIn(key, doc["counts"])
            self.assertEqual(doc["counts"]["critical"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
