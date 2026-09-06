"""Сторож воспроизводимости расчёта: каждый тест — воспроизведение ИЗМЕРЕННОГО.

Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`). Поломка, которую видел этот набор, случилась в
цикле #501 06.09 и была НЕ в аллокаторе, а в первой (наивной) форме самой
проверки:

    тюнер, 12 процессов, разные PYTHONHASHSEED
    хеш всего ответа: 12 из 12 РАЗНЫХ            → «расчёт не воспроизводим»
    единственное различие: поле `timestamp`, 237634 мкс против 306049
    после исключения ОДНОГО поля: 100 из 100 — ОДИН хеш

То есть честная проверка ответила бы владельцу «нет» на вопрос, ответ на который
«да», и следующая сессия чинила бы исправный код. Класс — «мера отвечает на СВОЙ
вопрос, а не на нужный». Тесты ниже держат обе стороны: часы не смеют краснить
(``timestamp``), а всё, что часами НЕ объявлено, обязано краснеть — включая
вложенное поле с «датным» видом (``feed_coverage.as_of``), которое на самом
деле кусок ВХОДА и глушить его нельзя.

Время — ВХОД (``now=``); дочерние процессы не поднимаются нигде, кроме
``TestSubprocessWiring``, где предмет и есть проводка.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import decision_reproducibility as dr
from spa_core.tests._freshness import now_utc


def _subject(key="allocator", clock=("timestamp",)):
    return dr.Subject(key=key, title=f"{key} (фикстура)", clock_fields=clock,
                      code="raise SystemExit('фикстурный субъект не исполняется')")


def _snapshot(dirpath: Path) -> Path:
    """Минимальный непустой снимок: сборщик песочницы требует хотя бы один *.json."""
    (dirpath / "adapter_orchestrator_status.json").write_text(
        json.dumps({"adapters": [{"protocol": "aave_v3", "apy_pct": 5.26,
                                  "tvl_usd": 58_548_694.0, "status": "ok"}]}),
        encoding="utf-8")
    return dirpath


def _runner_returning(docs):
    """Раннер, отдающий заранее заданные ответы по одному на прогон."""
    seq = list(docs)

    def _run(subject, sandbox, root, seed, timeout):
        return 0, json.dumps(seq.pop(0)), ""
    return _run


# ── Замер 06.09: ответы, различающиеся ТОЛЬКО стеной ────────────────────────
# Числа — из наблюдённого прогона тюнера того дня, не выдуманные.
_WALL_A = "2026-09-06T08:18:22.237634+00:00"
_WALL_B = "2026-09-06T08:18:22.306049+00:00"


def _answer(wall, weights=None, as_of="2026-09-06T06:00:12.755771+00:00"):
    return {
        "timestamp": wall,
        "target_weights": weights or {"aave_v3": 0.144454, "compound_v3": 0.337275},
        "expected_apy_pct": 6.1753,
        "feed_coverage": {"live_pct": 100.0, "as_of": {"aave_v3": as_of}},
    }


class TestTheIncidentOfCycle501(unittest.TestCase):
    """Положительный контроль на аварию, которую пережила сама проверка."""

    def _run(self, docs, subject):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            return dr.run(root=td, data_dir=str(data), runs=len(docs), write=False,
                          now=now_utc(), subjects=(subject,),
                          runner=_runner_returning(docs))

    def test_answers_differing_only_by_the_wall_clock_are_reproducible(self):
        """Дословный замер 06.09: два ответа, различие — только `timestamp`."""
        rep = self._run([_answer(_WALL_A), _answer(_WALL_B)], _subject())
        self.assertEqual(rep["overall"], "OK", rep["findings"])
        self.assertEqual(rep["measurements"][0]["distinct_outputs"], 1)

    def test_without_the_declaration_the_same_pair_reads_as_NOT_reproducible(self):
        """Та же пара БЕЗ объявления часов — ровно тот ложный CRITICAL.

        Это не «тест ради теста»: он доказывает, что зелёный вердикт выше
        добыт объявлением, а не тем, что фикстуры случайно совпали. Убери
        ``strip_clock`` из ``_measure`` — покраснеет он, а не первый.
        """
        rep = self._run([_answer(_WALL_A), _answer(_WALL_B)], _subject(clock=()))
        self.assertEqual(rep["overall"], "CRITICAL")
        diffs = " ".join(rep["measurements"][0]["differences"])
        self.assertIn("timestamp", diffs)


class TestARealDivergenceIsNamed(unittest.TestCase):
    """Расхождение расчёта обязано краснеть — и называть ПОЛЕ, а не «хеши разные»."""

    def _run(self, docs, subject=None):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            return dr.run(root=td, data_dir=str(data), runs=len(docs), write=False,
                          now=now_utc(), subjects=(subject or _subject(),),
                          runner=_runner_returning(docs))

    def test_different_weights_are_critical(self):
        rep = self._run([
            _answer(_WALL_A),
            _answer(_WALL_B, weights={"aave_v3": 0.144454, "compound_v3": 0.4}),
        ])
        self.assertEqual(rep["overall"], "CRITICAL")
        self.assertEqual(rep["counts"]["critical"], 1)

    def test_the_differing_field_is_named_in_the_report(self):
        rep = self._run([
            _answer(_WALL_A),
            _answer(_WALL_B, weights={"aave_v3": 0.144454, "compound_v3": 0.4}),
        ])
        diffs = " ".join(rep["measurements"][0]["differences"])
        self.assertIn("target_weights", diffs)
        self.assertNotIn("expected_apy_pct", diffs, "поле, которое НЕ менялось")

    def test_a_nested_date_looking_field_is_still_compared(self):
        """``feed_coverage.as_of`` — ВХОД, а не часы; регулярка съела бы его.

        Замер: аллокатор кладёт в ответ карту «протокол → отметка наблюдения».
        Глуши её — и прогон на ПОДМЕНЁННОМ снимке читался бы как «тот же ответ»,
        то есть сторож стал бы слеп ровно к тому, ради чего написан.
        """
        rep = self._run([
            _answer(_WALL_A, as_of="2026-09-06T06:00:12.755771+00:00"),
            _answer(_WALL_B, as_of="2026-09-05T06:00:12.755771+00:00"),
        ])
        self.assertEqual(rep["overall"], "CRITICAL")
        self.assertIn("feed_coverage", " ".join(rep["measurements"][0]["differences"]))

    def test_over_declaring_a_field_as_a_clock_is_named_out_loud(self):
        """Объявить часами то, что часами не является, — тихое слепое пятно.

        Здесь ``target_weights`` объявлен часами, и различие в нём перестаёт
        краснеть. Сторож обязан хотя бы НАЗВАТЬ это: поле, объявленное часами и
        ни разу не дрогнувшее, — либо лишнее объявление, либо производитель
        перестал штамповать время.
        """
        rep = self._run(
            [_answer(_WALL_A), _answer(_WALL_A, weights={"aave_v3": 0.9})],
            _subject(clock=("timestamp", "target_weights")),
        )
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("stale_clock_declaration", kinds)
        named = [f["message"] for f in rep["findings"]
                 if f["kind"] == "stale_clock_declaration"]
        self.assertTrue(any("timestamp" in m for m in named),
                        "неподвижное объявление обязано быть названо поимённо")


class TestTheThirdOutcome(unittest.TestCase):
    """«Не измерено» — самостоятельный вердикт, а не тихое OK и не скип."""

    def _run(self, runs=2, runner=None, snapshot=True, subject=None):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            if snapshot:
                _snapshot(data)
            return dr.run(root=td, data_dir=str(data), runs=runs, write=False,
                          now=now_utc(), subjects=(subject or _subject(),),
                          runner=runner or _runner_returning([_answer(_WALL_A)] * runs))

    def test_a_single_run_cannot_prove_reproducibility(self):
        rep = self._run(runs=1)
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIn("runs=1", " ".join(rep["unchecked"]))

    def test_a_failing_child_process_is_unchecked_not_ok(self):
        def _boom(subject, sandbox, root, seed, timeout):
            return 1, "", "ModuleNotFoundError: No module named 'spa_core'"
        rep = self._run(runner=_boom)
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIn("ModuleNotFoundError", " ".join(rep["unchecked"]))

    def test_unparseable_output_is_unchecked_not_ok(self):
        def _junk(subject, sandbox, root, seed, timeout):
            return 0, "Traceback (most recent call last):", ""
        rep = self._run(runner=_junk)
        self.assertEqual(rep["overall"], "UNCHECKED")

    def test_a_raising_runner_is_unchecked_not_a_crash(self):
        def _raise(subject, sandbox, root, seed, timeout):
            raise TimeoutError("прогон не уложился в 180 с")
        rep = self._run(runner=_raise)
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIn("TimeoutError", " ".join(rep["unchecked"]))

    def test_an_empty_snapshot_is_unchecked_not_ok(self):
        rep = self._run(snapshot=False)
        self.assertEqual(rep["overall"], "UNCHECKED")
        self.assertIn("снимок пуст", " ".join(rep["unchecked"]))

    def test_unchecked_outranks_critical_in_the_overall_verdict(self):
        """Один субъект расходится, второй не измерен ⇒ общий вердикт UNCHECKED.

        Иначе «не измерено» пряталось бы за красным — и читатель, починив
        красное, считал бы вопрос закрытым.
        """
        def _mixed(subject, sandbox, root, seed, timeout):
            if subject.key == "broken":
                return 1, "", "упал"
            return 0, json.dumps(_answer(_WALL_A, weights={"x": float(seed)})), ""
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            rep = dr.run(root=td, data_dir=str(data), runs=2, write=False,
                         now=now_utc(),
                         subjects=(_subject("diverging"), _subject("broken")),
                         runner=_mixed)
        self.assertEqual(rep["counts"]["critical"], 1)
        self.assertEqual(rep["counts"]["unchecked"], 1)
        self.assertEqual(rep["overall"], "UNCHECKED")

    def test_unchecked_is_never_reported_as_a_measured_zero(self):
        """У непроверенного субъекта нет числа «разных ответов» — там `None`."""
        def _boom(subject, sandbox, root, seed, timeout):
            return 1, "", "упал"
        rep = self._run(runner=_boom)
        self.assertIsNone(rep["measurements"][0]["distinct_outputs"])
        self.assertIsNotNone(rep["measurements"][0]["reason"])


class TestSandboxSafety(unittest.TestCase):
    """Замер не имеет права трогать то, что меряет."""

    def test_the_sandbox_is_a_copy_not_a_hardlink(self):
        """Ссылка мгновенна, но ``open(..., "w")`` пишет СКВОЗЬ неё в живой файл.

        Сторож, способный испортить сторожимое, — не экономия.
        """
        with TemporaryDirectory() as td:
            src = Path(td) / "data"
            src.mkdir()
            _snapshot(src)
            dest = Path(td) / "sb"
            dr._build_sandbox(str(src), str(dest))
            a = os.stat(src / "adapter_orchestrator_status.json")
            b = os.stat(dest / "adapter_orchestrator_status.json")
            self.assertNotEqual(a.st_ino, b.st_ino)
            (dest / "adapter_orchestrator_status.json").write_text("{}", encoding="utf-8")
            self.assertNotEqual(
                (src / "adapter_orchestrator_status.json").read_text(encoding="utf-8"),
                "{}", "запись в песочницу дошла до исходного снимка")

    def test_run_leaves_the_measured_data_dir_byte_identical(self):
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            before = dr._digest(str(data))
            dr.run(root=td, data_dir=str(data), runs=2, write=False, now=now_utc(),
                   subjects=(_subject(),),
                   runner=_runner_returning([_answer(_WALL_A), _answer(_WALL_B)]))
            self.assertEqual(before, dr._digest(str(data)))

    def test_a_subject_writing_under_save_false_is_named(self):
        """Оба субъекта заявлены read-only; запись под ``save=False`` — находка."""
        def _writes(subject, sandbox, root, seed, timeout):
            with open(os.path.join(sandbox, "tuner_suggestion.json"), "w") as fh:
                fh.write(json.dumps({"seed": seed}))
            return 0, json.dumps(_answer(_WALL_A)), ""
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            (data / "tuner_suggestion.json").write_text("{}", encoding="utf-8")
            rep = dr.run(root=td, data_dir=str(data), runs=2, write=False,
                         now=now_utc(), subjects=(_subject(),), runner=_writes)
        kinds = {f["kind"] for f in rep["findings"]}
        self.assertIn("side_effect", kinds)
        # По находке на КАЖДЫЙ прогон, а не одна на субъект: запись на втором
        # прогоне и запись на обоих — разные состояния, и сворачивать их в одну
        # строку значило бы потерять «сколько раз». Прогонов здесь 2.
        self.assertEqual(rep["counts"]["warn"], 2)
        self.assertIn("tuner_suggestion.json",
                      " ".join(f["message"] for f in rep["findings"]))


class TestSubprocessWiring(unittest.TestCase):
    """Предмет — сама проводка: раннер обязан поднять ОТДЕЛЬНЫЙ процесс.

    Мутация проводки (снять ``PYTHONHASHSEED``, снять ``SPA_DATA_DIR``, звать
    в текущем процессе) обязана краснеть ЗДЕСЬ — иначе весь набор выше проверял
    бы фикстуры, а не механизм.
    """

    def test_the_child_is_a_separate_process_with_the_seed_and_sandbox_wired(self):
        code = ("import os, json, sys; sys.stdout.write(json.dumps({"
                "'pid': os.getpid(), 'seed': os.environ.get('PYTHONHASHSEED'),"
                "'sandbox': os.environ.get('SPA_DATA_DIR')}))")
        subject = dr.Subject(key="probe", title="проводка", clock_fields=(), code=code)
        with TemporaryDirectory() as td:
            rc, out, err = dr._default_runner(subject, td, dr.REPO_ROOT, 7, 60.0)
        self.assertEqual(rc, 0, err)
        doc = json.loads(out)
        self.assertNotEqual(doc["pid"], os.getpid(), "субъект исполнился В ЭТОМ процессе")
        self.assertEqual(doc["seed"], "7")
        self.assertEqual(doc["sandbox"], td)

    def test_different_runs_get_different_hash_seeds(self):
        """Одинаковая соль у всех прогонов сделала бы замер вакуумным.

        Порядок обхода множеств в CPython зависит от соли, и живой дневной цикл
        её не пришпиливает. Прогон, повторённый с ТОЙ ЖЕ солью, отвечает на
        вопрос «детерминирован ли Python», а не на вопрос владельца.
        """
        seen = []

        def _record(subject, sandbox, root, seed, timeout):
            seen.append(seed)
            return 0, json.dumps(_answer(_WALL_A)), ""
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            dr.run(root=td, data_dir=str(data), runs=4, write=False, now=now_utc(),
                   subjects=(_subject(),), runner=_record)
        self.assertEqual(len(set(seen)), 4, f"соли повторились: {seen}")


class TestDeclarationsMatchTheProducers(unittest.TestCase):
    """Объявление часов обязано соответствовать КОДУ производителя, а не памяти."""

    def test_every_subject_declares_a_clock_field_its_producer_actually_stamps(self):
        producers = {
            "allocator": "spa_core/allocator/allocator.py",
            "tuner": "spa_core/tuner/allocation_tuner.py",
        }
        root = Path(dr.REPO_ROOT)
        for s in dr.SUBJECTS:
            with self.subTest(subject=s.key):
                self.assertTrue(s.clock_fields, "субъект без объявленных часов")
                src = (root / producers[s.key]).read_text(encoding="utf-8")
                self.assertIn("datetime.now(timezone.utc)", src,
                              "производитель больше не штампует время — "
                              "объявление часов устарело")

    def test_the_report_records_how_many_runs_were_actually_made(self):
        """«3» никогда не должно читаться как «100» — число прогонов в отчёте."""
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True, exist_ok=True)
            _snapshot(data)
            rep = dr.run(root=td, data_dir=str(data), runs=3, write=False,
                         now=now_utc(), subjects=(_subject(),),
                         runner=_runner_returning([_answer(_WALL_A)] * 3))
        self.assertEqual(rep["runs"], 3)
        self.assertEqual(rep["measurements"][0]["runs_completed"], 3)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
