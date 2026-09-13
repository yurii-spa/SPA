"""Сторож приёмки G1 приказа «Portfolio CIO»: доля капитала на наблюдённых числах.

Каждый тест — положительный контроль: воспроизводит ЗАМЕРЕННУЮ аварию и краснеет, если
прибор перестанет её видеть. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Время сюда не входит вовсе: прибор судит о провенансе, а не о свежести, — поэтому ни
литеральных дат, ни часов в фикстурах нет по построению.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

import capital_observability_census as census  # noqa: E402


def _book(positions, apy_sources, tvl_sources, **extra):
    doc = {
        "generated_at": "SNAPSHOT",
        "positions": dict(positions),
        "deployed_usd": float(sum(positions.values())),
        "feed_coverage": {"apy_sources": dict(apy_sources),
                          "tvl_sources": dict(tvl_sources)},
    }
    doc.update(extra)
    return doc


def _status(entries):
    return {"schema_version": 2, "adapters": dict(entries)}


class _Fixture:
    """Каталог данных с двумя артефактами. Пишет ровно то, что просят."""

    def __init__(self, tmp, book=None, status=None):
        self.dir = Path(tmp)
        if book is not None:
            (self.dir / "current_positions.json").write_text(
                json.dumps(book, ensure_ascii=False), encoding="utf-8")
        if status is not None:
            (self.dir / "adapter_status.json").write_text(
                json.dumps(status, ensure_ascii=False), encoding="utf-8")


class CapitalWeightingTests(unittest.TestCase):
    """Метрика §5 требует долю ДОЛЛАРОВ, а не долю протоколов."""

    def test_share_is_weighted_by_money_not_by_protocol_count(self):
        # Два протокола, один наблюдён — по счёту протоколов это 50 % при ЛЮБЫХ суммах.
        # По деньгам — 90 % или 10 % в зависимости от того, ГДЕ лежит капитал. Прибор,
        # считающий протоколы, вернёт 50 % в обоих случаях и этот тест покраснеет.
        shares = []
        for big, small in (("live_one", "literal_one"), ("literal_one", "live_one")):
            with TemporaryDirectory() as tmp:
                _Fixture(tmp, book=_book(
                    {big: 90_000.0, small: 10_000.0},
                    {"live_one": "live", "literal_one": "static"},
                    {"live_one": "live", "literal_one": "live"}))
                shares.append(census.measure(tmp)["axes"]["apy"]["observed_pct"])
        self.assertEqual([90.0, 10.0], shares)

    def test_zero_dollar_position_is_not_a_funded_protocol(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"held": 50_000.0, "exited": 0.0},
                {"held": "live"}, {"held": "live"}))
            r = census.measure(tmp)
        # `exited` профинансирован нулём: он не деньги и не дыра в провенансе.
        self.assertEqual(1, r["protocols"])
        self.assertEqual(100.0, r["axes"]["apy"]["observed_pct"])
        self.assertEqual([], r["axes"]["apy"]["provenance_undeclared"])


class TwoAxesTests(unittest.TestCase):
    """Ось APY зелена, ось TVL красна — и наоборот. Одна ось за обе не отвечает."""

    def test_apy_observed_while_tvl_stands_on_a_literal(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"aave_v3": 40_000.0}, {"aave_v3": "live"}, {"aave_v3": "static"}))
            r = census.measure(tmp)
        self.assertEqual(100.0, r["axes"]["apy"]["observed_pct"])
        self.assertEqual(0.0, r["axes"]["tvl"]["observed_pct"])
        self.assertEqual("aave_v3", r["axes"]["tvl"]["on_literal"][0]["protocol"])

    def test_tvl_observed_while_apy_stands_on_a_literal(self):
        # Авария ADR-063 (02.08): двенадцать адаптеров отдавали DEFAULT_APY_PCT, а
        # провайдер штамповал его `live`. Здесь литерал объявлен честно — и всё равно
        # обязан вычитаться из доли.
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"spark_susds": 20_000.0}, {"spark_susds": "fallback"},
                {"spark_susds": "live"}))
            r = census.measure(tmp)
        self.assertEqual(0.0, r["axes"]["apy"]["observed_pct"])
        self.assertEqual(100.0, r["axes"]["tvl"]["observed_pct"])


class ProvenanceStrictnessTests(unittest.TestCase):
    def test_only_the_word_live_counts_as_an_observation(self):
        for declared in ("static", "fallback", "advisory", "hint", "", "live-ish", None):
            with self.subTest(declared=declared):
                with TemporaryDirectory() as tmp:
                    _Fixture(tmp, book=_book(
                        {"p": 10_000.0}, {"p": declared}, {"p": "live"}))
                    self.assertEqual(0.0, census.measure(tmp)["axes"]["apy"]["observed_pct"])

    def test_case_and_padding_do_not_change_the_verdict(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book({"p": 10_000.0}, {"p": " LIVE "}, {"p": "live"}))
            self.assertEqual(100.0, census.measure(tmp)["axes"]["apy"]["observed_pct"])

    def test_undeclared_provenance_is_not_observed_and_is_named_apart(self):
        # Авария ADR-126: деньги стоят, а строки про них в карте нет вовсе. Молчаливое
        # «раз не сказано — значит живое» и есть fail-OPEN, который прибор обязан закрыть.
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"ghost": 30_000.0, "known": 70_000.0},
                {"known": "live"}, {"known": "live", "ghost": "live"}))
            r = census.measure(tmp)
        self.assertEqual(70.0, r["axes"]["apy"]["observed_pct"])
        self.assertEqual([], r["axes"]["apy"]["on_literal"])
        self.assertEqual("ghost", r["axes"]["apy"]["provenance_undeclared"][0]["protocol"])

    def test_a_populated_value_is_not_evidence_of_an_observation(self):
        # `apy` эхом повторяет fallback, когда наблюдения нет. Прибор, заглянувший в
        # значение вместо провенанса, зазеленеет здесь.
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"p": 10_000.0}, {"p": "static"}, {"p": "static"},
                positions_detail={"p": {"usd": 10_000.0, "apy_pct": 7.5}},
                tuner_expected_apy=7.5))
            r = census.measure(tmp)
        self.assertEqual(0.0, r["axes"]["apy"]["observed_pct"])
        self.assertEqual(0.0, r["axes"]["tvl"]["observed_pct"])


class MeasuredZeroIsNotUnmeasuredTests(unittest.TestCase):
    def test_a_book_entirely_on_literals_is_a_measured_zero(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"a": 50_000.0, "b": 50_000.0},
                {"a": "static", "b": "static"}, {"a": "static", "b": "static"}))
            r = census.measure(tmp)          # НЕ поднимает NotMeasured
        self.assertEqual(0.0, r["axes"]["apy"]["observed_pct"])
        self.assertEqual(0.0, r["axes"]["apy"]["observed_usd"])
        self.assertEqual(2, len(r["axes"]["apy"]["on_literal"]))


class ThirdOutcomeTests(unittest.TestCase):
    """Инвариант #17: «не измерено» отдельным исходом, с названной причиной."""

    def _refuses(self, *, book=None, status=None, needle=""):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=book, status=status)
            with self.assertRaises(census.NotMeasured) as ctx:
                census.measure(tmp)
        self.assertIn(needle, str(ctx.exception))

    def test_missing_data_dir(self):
        with self.assertRaises(census.NotMeasured) as ctx:
            census.measure("/nonexistent/spa-data-dir")
        self.assertIn("каталога данных нет", str(ctx.exception))

    def test_missing_book(self):
        self._refuses(needle="файла нет")

    def test_unparsable_book(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "current_positions.json").write_text("{не json", encoding="utf-8")
            with self.assertRaises(census.NotMeasured) as ctx:
                census.measure(tmp)
        self.assertIn("не разобран", str(ctx.exception))

    def test_missing_positions_map(self):
        self._refuses(book={"generated_at": "S", "feed_coverage": {}},
                      needle="нет карты `positions`")

    def test_missing_feed_coverage(self):
        self._refuses(book={"generated_at": "S", "positions": {"p": 1.0}},
                      needle="нет `feed_coverage`")

    def test_missing_one_axis_map(self):
        self._refuses(
            book={"generated_at": "S", "positions": {"p": 1.0},
                  "feed_coverage": {"apy_sources": {"p": "live"}}},
            needle="нет карты `tvl_sources`")

    def test_empty_book_is_unmeasured_not_zero_and_not_hundred(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book({}, {}, {}))
            with self.assertRaises(census.NotMeasured) as ctx:
                census.measure(tmp)
        msg = str(ctx.exception)
        self.assertIn("книга пуста", msg)
        self.assertIn("НЕ 0 %", msg)
        self.assertIn("НЕ 100 %", msg)

    def test_non_numeric_position_refuses_instead_of_guessing(self):
        self._refuses(
            book={"generated_at": "S", "positions": {"p": "40000"},
                  "feed_coverage": {"apy_sources": {}, "tvl_sources": {}}},
            needle="знаменатель НЕ ИЗМЕРЕН")

    def test_second_artifact_absence_does_not_masquerade_as_agreement(self):
        # Главный замер состоялся, а сверка — нет. Молчание здесь читалось бы как «спора
        # нет», то есть «не измерено» выдавалось бы за «чисто».
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book({"p": 10_000.0}, {"p": "live"}, {"p": "live"}))
            r = census.measure(tmp)
        self.assertEqual(100.0, r["axes"]["apy"]["observed_pct"])
        self.assertFalse(r["second_artifact"]["read"])
        self.assertIn("файла нет", r["second_artifact"]["reason"])
        self.assertTrue(census._findings(r))       # код 1, не 0


class SecondArtifactTests(unittest.TestCase):
    """Замер 12.09: два артефакта об одних деньгах спорят в один и тот же цикл."""

    def test_literal_in_the_report_artifact_while_the_surface_observed(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"aave_v3": 5_000.0}, {"aave_v3": "live"},
                                {"aave_v3": "live"},
                                feed_coverage_extra=None),
                     status=_status({"aave_v3": {"live_apy": 3.5, "tvl_source": "static",
                                                 "tvl_usd": 12_000_000_000.0}}))
            # tvl_usd поверхности живёт в feed_coverage — допишем его как это делает аллокатор
            path = Path(tmp) / "current_positions.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["feed_coverage"]["tvl_usd"] = {"aave_v3": 206_107_174.0}
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            r = census.measure(tmp)
        rows = [d for d in r["second_artifact"]["disagreements"] if d["axis"] == "tvl"]
        self.assertEqual(1, len(rows))
        self.assertEqual("second_artifact_blind", rows[0]["kind"])
        self.assertEqual(12_000_000_000.0, rows[0]["second_value"])
        self.assertEqual(206_107_174.0, rows[0]["surface_value"])

    def test_surface_blind_while_the_second_artifact_observed(self):
        # Обратное направление — то, ради чего писали status_reader: наблюдение лежало
        # в файле НЕПРОЧИТАННЫМ, а ранжировали литералом.
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"p": 10_000.0}, {"p": "static"}, {"p": "live"}),
                     status=_status({"p": {"live_apy": 4.2, "tvl_source": "live",
                                           "tvl_usd": 1.0}}))
            r = census.measure(tmp)
        rows = [d for d in r["second_artifact"]["disagreements"] if d["axis"] == "apy"]
        self.assertEqual(["decision_surface_blind"], [x["kind"] for x in rows])

    def test_null_live_apy_in_the_second_artifact_is_a_literal_not_an_observation(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"pendle": 20_000.0}, {"pendle": "live"}, {"pendle": "live"}),
                     status=_status({"pendle": {"apy": 8.0, "live_apy": None,
                                                "tvl_source": "live"}}))
            r = census.measure(tmp)
        rows = [d for d in r["second_artifact"]["disagreements"] if d["axis"] == "apy"]
        self.assertEqual(["second_artifact_blind"], [x["kind"] for x in rows])

    def test_funded_protocol_absent_from_the_second_artifact_is_named(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"p": 10_000.0}, {"p": "live"}, {"p": "live"}),
                     status=_status({"other": {"live_apy": 1.0, "tvl_source": "live"}}))
            r = census.measure(tmp)
        self.assertEqual(["absent_from_second_artifact"],
                         [d["kind"] for d in r["second_artifact"]["disagreements"]])

    def test_agreement_produces_no_disagreement_rows(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"p": 10_000.0}, {"p": "live"}, {"p": "live"}),
                     status=_status({"p": {"live_apy": 4.0, "tvl_source": "live"}}))
            r = census.measure(tmp)
        self.assertEqual([], r["second_artifact"]["disagreements"])
        self.assertFalse(census._findings(r))


class InternalDisagreementTests(unittest.TestCase):
    def test_two_fields_of_one_file_disagreeing_is_named(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book(
                {"p": 10_000.0}, {"p": "static"}, {"p": "live"},
                positions_detail={"p": {"usd": 10_000.0, "apy_source": "live"}}))
            r = census.measure(tmp)
        self.assertEqual(1, len(r["internal_disagreements"]))
        self.assertEqual("p", r["internal_disagreements"][0]["protocol"])

    def test_declared_deployed_that_contradicts_the_positions_is_named(self):
        with TemporaryDirectory() as tmp:
            book = _book({"p": 10_000.0}, {"p": "live"}, {"p": "live"})
            book["deployed_usd"] = 95_000.0
            _Fixture(tmp, book=book)
            r = census.measure(tmp)
        self.assertFalse(r["deployed_matches_declaration"])
        self.assertTrue(census._findings(r))


class ExitCodeTests(unittest.TestCase):
    SCRIPT = _ROOT / "scripts" / "capital_observability_census.py"

    def _run(self, data_dir):
        return subprocess.run([sys.executable, str(self.SCRIPT), "--data-dir", str(data_dir)],
                              capture_output=True, text=True)

    def test_clean_is_zero(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"p": 10_000.0}, {"p": "live"}, {"p": "live"}),
                     status=_status({"p": {"live_apy": 4.0, "tvl_source": "live"}}))
            p = self._run(tmp)
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn("обе оси 100 %", p.stdout)

    def test_finding_is_one(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp,
                     book=_book({"p": 10_000.0}, {"p": "static"}, {"p": "live"}),
                     status=_status({"p": {"live_apy": None, "tvl_source": "live"}}))
            p = self._run(tmp)
        self.assertEqual(1, p.returncode, p.stdout + p.stderr)
        self.assertIn("НА ЛИТЕРАЛЕ", p.stdout)

    def test_unmeasured_is_two_and_says_so(self):
        p = self._run("/nonexistent/spa-data-dir")
        self.assertEqual(2, p.returncode)
        self.assertIn("НЕ ИЗМЕРЕНО", p.stdout)

    def test_json_output_carries_both_axes(self):
        with TemporaryDirectory() as tmp:
            _Fixture(tmp, book=_book({"p": 10_000.0}, {"p": "live"}, {"p": "live"}))
            p = subprocess.run([sys.executable, str(self.SCRIPT), "--data-dir", tmp, "--json"],
                               capture_output=True, text=True)
        payload = json.loads(p.stdout.split("Доля капитала")[0])
        self.assertEqual({"apy", "tvl"}, set(payload["axes"]))


if __name__ == "__main__":
    unittest.main()
