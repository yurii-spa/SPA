"""Проводка производителя записи §49 `No regression` (ADR-790).

Предмет. `scripts/refresh_no_regression_census.py` написан 17.10 (ADR-770) как
ПРОИЗВОДИТЕЛЬ записи для критерия владельца §49 `No regression` — и до 23.10 его не
вызывал НИКТО. Замер на чистой вершине `origin/main 2530cb1ec`:

* храповик сирот `test_unwired_scripts_ratchet` красен, и одно из четырёх имён —
  этот производитель («новые скрипты с точкой входа, которых никто не вызывает»);
* `producer` артефакта `data/no_regression_census.json` в конституции — `null`;
  поэтому `test_office_subject_drift_producer_tick` краснел ровно одной строкой:
  «такт НЕ ИЗМЕРИМ у 1 из 137 артефактов офиса»;
* сам артефакт в боевом дереве — **152.1 ч** при пределе пробы **192 ч**, то есть
  критерию владельца оставалось **39.9 ч** до молчаливого `unmeasured`. Это уже
  случалось: 17.10 запись от 28.09 пролежала 448.9 ч.

**Проводки не было ПО ПОСТРОЕНИЮ, а не по забывчивости** — и это главное, что
закрепляют тесты ниже. Отчёт обязан жить в БОЕВОМ дереве (иначе его не прочитает ни
проба, ни шаг 0-офис), а прогон населения в боевом дереве ЗАПРЕЩЁН (тесты пишут в
живое `data/`, `.claude/rules/deployment.md` п. 4). Оба адреса были ОДНИМ входом
`--repo-root`, и единственным возможным писателем оставалась рука цикла. ADR-790
разводит их третьим входом (`run_tree` / `--make-tree`).

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ одного порванного звена, и звено названо
в его docstring. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).

Все часы и все стороны сравнения — ВХОДЫ, и это ЕДИНСТВЕННЫЙ литеральный якорь файла:
:data:`NOW`. От него производны ОБЕ стороны каждого сравнения возраста — и «когда написан
отчёт» (`_report(age_h)` считает отметку от `NOW`), и «сколько сейчас» (`now=NOW` уезжает
входом в пробу). Поэтому сдвиг календаря не меняет здесь ни одного вердикта.

# FROZEN-DATE-OK: injected-clock — якорь `NOW` уезжает входом `now=` в
# `_probe_no_regression_record_is_produced_without_a_hand`, а отметки отчётов-сцен
# считаются от него же (`_report` = NOW − timedelta); обе стороны сравнения закреплены
# одним якорем, стенных часов в файле нет ни у одного вердикта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import card_acceptance as ca  # noqa: E402
from spa_core.monitoring import findings_bridge as fb  # noqa: E402
from spa_core.tests._unwired import unwired_scripts  # noqa: E402

PRODUCER_REL = os.path.join("scripts", "refresh_no_regression_census.py")
ARTIFACT = "data/no_regression_census.json"

#: Момент замера — ВХОД сцены. Ни одна дата здесь не literal: обе стороны
#: сравнения («когда написан отчёт» и «сколько сейчас») производны от него.
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def _manifest(producer="com.spa.decision_loop", slo=192):
    """Конституция-сцена: ровно тот артефакт, о котором идёт речь."""
    return {"artifacts": [{"path": ARTIFACT, "producer": producer,
                           "slo_hours": slo, "consumers": ["orchestrator_protocol"]}]}


def _report(age_h: float):
    """Отчёт-сцена заданного ВОЗРАСТА относительно :data:`NOW`."""
    return {"generated_at": (NOW - timedelta(hours=age_h)).isoformat(),
            "measured": True, "verdict": "OK"}


class _CP:
    """Исход подпроцесса — подделка ровно той формы, что читает ступень."""

    def __init__(self, code, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


def _spy(code, stdout=""):
    """Дверь к подпроцессу ВХОДОМ: тест не смеет гонять настоящее население."""
    seen: list = []

    def run(cmd, **kw):
        seen.append(list(cmd))
        return _CP(code, stdout)

    run.seen = seen  # type: ignore[attr-defined]
    return run


class ProducerIsCalled(unittest.TestCase):
    """Звено 1: ЗОВ. До ADR-790 его не было ни одного — ни ступенью, ни строкой."""

    def test_the_bridge_step_calls_exactly_this_producer(self):
        spy = _spy(0)
        out = fb.no_regression_step(str(_REPO), runner=spy)
        self.assertTrue(spy.seen, "ступень не позвала производителя ни разу — проводки нет")
        cmd = " ".join(spy.seen[0])
        for token in (PRODUCER_REL, "--if-due", "--make-tree", str(_REPO)):
            self.assertIn(token, cmd, f"зов ступени не несёт {token!r}: {cmd!r}")
        self.assertEqual(out["status"], "ok")

    def test_the_three_outcomes_of_the_step_are_distinguishable(self):
        """Инв. #17: «не измерено» не смеет выглядеть как «регрессий нет»."""
        self.assertEqual(
            {c: fb.no_regression_step(str(_REPO), runner=_spy(c))["status"]
             for c in (0, 1, 2)},
            {0: "ok", 1: "regression", 2: "unmeasured"})

    def test_a_producer_that_is_not_on_disk_is_the_third_outcome(self):
        """Порванное звено: производителя нет. Это НЕ «регрессий нет»."""
        empty = tempfile.mkdtemp(prefix="nrw_noproducer_")
        try:
            out = fb.no_regression_step(empty, runner=_spy(0))
        finally:
            os.rmdir(empty)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("нет на диске", out["reason"])

    def test_a_producer_killed_by_the_timeout_is_the_third_outcome(self):
        """Порванное звено: прогон снят по сроку. Вердикта нет ни у кого."""
        def boom(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)

        out = fb.no_regression_step(str(_REPO), runner=boom)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("по сроку", out["reason"])

    def test_a_producer_that_does_not_start_at_all_is_the_third_outcome(self):
        """Порванное звено: python не поднялся. Третий исход, а не ноль."""
        def boom(cmd, **kw):
            raise OSError("Exec format error")

        out = fb.no_regression_step(str(_REPO), runner=boom)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("не запущен", out["reason"])

    def test_the_step_line_never_dresses_unmeasured_as_a_verdict(self):
        """Строка ступени — её читает человек в логе агента, и форма тут есть смысл."""
        self.assertIn("НЕ ИЗМЕРЕНО", fb.no_regression_line(
            {"status": "unmeasured", "reason": "почему-то"}))
        self.assertNotIn("НЕ ИЗМЕРЕНО", fb.no_regression_line(
            {"status": "ok", "code": 0, "ran": True, "reason": "x"}))

    def test_the_step_is_wired_from_the_bridge_main_not_only_defined(self):
        """Звено, которое и было порвано: функция СУЩЕСТВУЕТ, а ЗОВА нет.

        **Храповик сирот на этот вопрос не отвечает, и это ИЗМЕРЕНО, а не
        предположено.** Первый мутационный прогон ADR-790 (14 мутаций) оставил
        выжившей ровно одну — «ЗОВ снят из моста», — и причина в устройстве
        храповика: он считает проводкой ЛЮБОЕ упоминание имени скрипта в
        неtest-файле (`_unwired.wiring_patterns`), а в мосте имя живёт ещё и
        строковой константой `NO_REGRESSION_PRODUCER`. Снятие зова имя не убирает ⇒
        храповик остаётся зелёным по этому имени. Вторая половина той же причины:
        его главная проверка КРАСНА на чистой вершине по ЧУЖИМ трём именам, то
        есть убить мутанта она не способна по построению.

        Поэтому зов меряется AST: узел `Call` с именем ступени ВНУТРИ `main()`. Это
        тот же приём, которым проект мерит замкнутые перечни читателей
        (`test_delivery_bytes_pin.py`) и притязание `injected-clock`
        (`spa_core/tests/_injected_clock.py`) — подстрокой он не проходит.
        """
        import ast
        tree = ast.parse((_REPO / "spa_core" / "monitoring" / "findings_bridge.py")
                         .read_text(encoding="utf-8"))
        main = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
        self.assertIsNotNone(main, "в мосте нет `main()` — разобрать зов нечем")
        called = {n.func.id for n in ast.walk(main)  # type: ignore[arg-type]
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("no_regression_step", called,
                      "ступень определена, но `main()` её НЕ ЗОВЁТ — ровно состояние "
                      "до ADR-790; имя в константе проводкой не является")
        # Вторая нога того же звена: храповик сирот тоже не смеет называть
        # производителя. Она слабее первой (см. docstring) и стои́т рядом, а не
        # вместо неё.
        self.assertNotIn("refresh_no_regression_census", unwired_scripts(_REPO),
                         "производитель снова без вызывающего — проводка потеряна")


class TactIsDecidedByTheFile(unittest.TestCase):
    """Звено 2: СРОК. Решать его обязан ФАЙЛ, иначе «раз в 120 ч» держится на зове."""

    def setUp(self):
        self.scene = pathlib.Path(tempfile.mkdtemp(prefix="nrw_scene_"))
        # Имя ветки — ВХОД, а не умолчание хоста: `git init` без `-b` даёт `main`
        # на Маке и `master` на `ubuntu-latest` (`.claude/rules/deployment.md`).
        cp = subprocess.run(["git", "init", "-b", "main", str(self.scene)],
                            capture_output=True, text=True)
        if cp.returncode != 0:
            self.fail(f"предпосылка НЕ ОБЕСПЕЧЕНА: git init → {cp.returncode}: "
                      f"{(cp.stderr or cp.stdout).strip()[:200]}")
        (self.scene / "data").mkdir(parents=True, exist_ok=True)
        self.tree = self.scene / "run_tree"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.scene, ignore_errors=True)

    def _say(self, age_h: float):
        (self.scene / ARTIFACT).write_text(json.dumps(_report(age_h)), encoding="utf-8")

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, str(_REPO / PRODUCER_REL), "--if-due", "--make-tree",
             "--repo-root", str(self.scene), "--run-tree", str(self.tree),
             "--records-root", str(self.scene), *extra],
            capture_output=True, text=True, timeout=300)

    def test_inside_the_tact_no_tree_is_built_at_all(self):
        """Порванное звено: ступень платит за ответ, который лежал на диске."""
        self._say(1.0)
        cp = self._run()
        self.assertEqual(cp.returncode, 0, (cp.stdout + cp.stderr)[-400:])
        self.assertIn("не срок", cp.stdout)
        self.assertFalse(self.tree.exists(),
                         "внутри такта дерево прогона собрано — срок решает зов, не файл")

    def test_past_the_tact_it_really_goes_for_the_tree(self):
        """Порванное звено: ветка срока ведёт в никуда и молча выходит нулём.

        В сцене нет `origin/main`, поэтому дерево не собирается — и это ПРАВИЛЬНЫЙ
        третий исход с кодом 2, а не «регрессий нет» с кодом 0.
        """
        self._say(500.0)
        cp = self._run()
        self.assertEqual(cp.returncode, 2, (cp.stdout + cp.stderr)[-400:])
        self.assertIn("НЕ ИЗМЕРЕНО", cp.stdout)
        self.assertIn("одноразовое дерево прогона не собралось", cp.stdout)

    def test_an_artifact_whose_age_is_unmeasured_does_not_read_as_fresh(self):
        """Порванное звено: отчёта нет ⇒ возраст `None` ⇒ «ноль часов» было бы ложью."""
        (self.scene / ARTIFACT).write_text("{ не json", encoding="utf-8")
        cp = self._run()
        self.assertEqual(cp.returncode, 2, (cp.stdout + cp.stderr)[-400:])
        self.assertNotIn("не срок", cp.stdout,
                         "неизмеренный возраст прочитан как «внутри такта» — fail-OPEN")


class RunTreeAndReportTreeAreDifferentAddresses(unittest.TestCase):
    """Звено 3: ДВА АДРЕСА. Отказ «дерево боевое» обязан спрашиваться у дерева ПРОГОНА."""

    @staticmethod
    def _producer_module():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_nrc_addr", str(_REPO / PRODUCER_REL))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        # Регистрация ДО `exec_module`: иначе модуль с `@dataclass` не ввозится
        # вовсе (урок цикла #911).
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_a_prod_RUN_tree_is_refused_even_when_the_report_tree_is_not(self):
        """Порванное звено: отказ спрашивают у дерева ОТЧЁТА.

        Тогда прогон в боевом дереве проходил бы молча — ровно авария 2026-08-24
        (`.claude/rules/deployment.md` п. 4). Отказ наступает ДО `pytest`, поэтому
        тест ничего не гоняет.
        """
        mod = self._producer_module()
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
        scene = pathlib.Path(tempfile.mkdtemp(prefix="nrw_report_"))
        try:
            with self.assertRaises(mod.NotMeasured) as caught:
                mod.refresh(scene, run_tree=pathlib.Path(DEFAULT_LIVE_ROOT))
            self.assertIn("БОЕВОЕ", str(caught.exception))
        finally:
            import shutil
            shutil.rmtree(scene, ignore_errors=True)

    def test_a_prod_REPORT_tree_is_NOT_refused_when_the_run_tree_is_disposable(self):
        """Вторая половина того же звена, без которой первая ничего не стоит.

        Отчёт ОБЯЗАН жить в боевом дереве. Если отказ срабатывает и на него,
        проводка снова невозможна по построению — то есть ADR-790 отменён. Отказ,
        который наступает здесь, должен быть ДРУГИМ: населения в пустой сцене нет.
        """
        mod = self._producer_module()
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
        scene = pathlib.Path(tempfile.mkdtemp(prefix="nrw_runtree_"))
        try:
            with self.assertRaises(mod.NotMeasured) as caught:
                mod.refresh(pathlib.Path(DEFAULT_LIVE_ROOT), run_tree=scene)
            self.assertNotIn("БОЕВОЕ", str(caught.exception),
                             "боевое дерево ОТЧЁТА отказано — проводка снова невозможна")
            self.assertIn("не найдены", str(caught.exception))
        finally:
            import shutil
            shutil.rmtree(scene, ignore_errors=True)

    def test_the_prod_refusal_asks_the_run_tree_and_not_the_report_tree(self):
        """Авария, которую это звено держит: 2026-08-24, 116 файлов `data/` в проде.

        Прогон населения в боевом дереве запрещён НАВСЕГДА. Но отчёт обязан жить
        именно там — и до ADR-790 из этих двух правд не было выхода.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_nrc_probe", str(_REPO / PRODUCER_REL))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # до exec_module: @dataclass иначе не ввезётся
        spec.loader.exec_module(mod)

        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
        live = pathlib.Path(DEFAULT_LIVE_ROOT)

        # дерево ПРОГОНА боевое ⇒ отказ (звено цело)
        with self.assertRaises(mod.NotMeasured) as caught:
            mod._refuse_if_prod_tree(live, allow=False)
        self.assertIn("БОЕВОЕ", str(caught.exception))

        # а ВХОДОВ у `refresh` теперь три, и дерево прогона среди них
        import inspect
        self.assertIn("run_tree", inspect.signature(mod.refresh).parameters,
                      "третьего входа нет — проводка снова невозможна по построению")

    def test_a_tree_this_run_did_not_build_is_never_dropped(self):
        """Порванное звено: уборка ЧУЖОГО дерева. Снимать можно только своё."""
        src = (_REPO / PRODUCER_REL).read_text(encoding="utf-8")
        self.assertIn("made: Path | None = run_tree if args.make_tree else None", src)
        self.assertIn("if built is not None and made is not None:", src)


class TheProbeMeasuresTheOutcome(unittest.TestCase):
    """Звено 4: ПРОБА. Она обязана зеленеть на целом контуре и краснеть на каждом разрыве."""

    def _probe(self, **kw):
        kw.setdefault("now", NOW)
        kw.setdefault("repo_root", str(_REPO))
        kw.setdefault("manifest", _manifest())
        kw.setdefault("live_report", _report(10.0))
        return ca._probe_no_regression_record_is_produced_without_a_hand(None, **kw)

    def test_green_on_a_whole_contour(self):
        st, why = self._probe()
        self.assertEqual(st, ca.SATISFIED, why)
        self.assertIn("ПОЗВАН ступенью моста", why)

    def test_red_when_the_constitution_does_not_name_the_producer(self):
        """РОВНО то состояние, в котором артефакт жил до ADR-790 (`producer: null`)."""
        st, why = self._probe(manifest=_manifest(producer=None))
        self.assertEqual(st, ca.NOT_SATISFIED, why)
        self.assertIn("producer", why)

    def test_red_when_the_live_artifact_is_older_than_its_own_slo(self):
        """Порванное звено: производитель объявлен, а записи нет. Это находка."""
        st, why = self._probe(live_report=_report(500.0))
        self.assertEqual(st, ca.NOT_SATISFIED, why)
        self.assertIn("старше своего SLO", why)

    def test_unmeasured_when_the_artifact_is_not_declared_in_the_constitution(self):
        st, why = self._probe(manifest={"artifacts": []})
        self.assertEqual(st, ca.UNMEASURED, why)

    def test_unmeasured_when_the_producer_is_not_on_disk(self):
        """«Инструмента нет» — самостоятельный третий исход, а не ноль и не скип."""
        st, why = self._probe(producer_rel=os.path.join("scripts", "нет-такого.py"))
        self.assertEqual(st, ca.UNMEASURED, why)
        self.assertIn("нет на диске", why)

    def test_unmeasured_when_the_live_artifact_has_no_readable_stamp(self):
        st, why = self._probe(live_report={"generated_at": "вчера"})
        self.assertEqual(st, ca.UNMEASURED, why)

    def test_the_probe_refuses_an_argument_instead_of_ignoring_it(self):
        st, _ = self._probe()
        self.assertEqual(st, ca.SATISFIED)
        st2, why2 = ca._probe_no_regression_record_is_produced_without_a_hand(
            "что-нибудь", now=NOW, repo_root=str(_REPO))
        self.assertEqual(st2, ca.UNMEASURED, why2)

    def test_the_probe_is_registered_in_the_closed_registry(self):
        """Проба без регистрации — та же сирота: объявить её карточке нечем."""
        self.assertIn("no_regression_record_is_produced_without_a_hand", ca.PROBES)


class TheConstitutionAgreesWithTheCode(unittest.TestCase):
    """Звено 5: ОБЪЯВЛЕНИЕ. Назвать производителем агента, который его не зовёт, нельзя."""

    def setUp(self):
        self.entry = next(
            (a for a in json.loads(
                (_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8")
            )["artifacts"] if a.get("path") == ARTIFACT), None)
        self.assertIsNotNone(self.entry, f"{ARTIFACT} в конституции не объявлен")

    def test_the_named_producer_is_the_agent_that_actually_runs_the_step(self):
        """Порванное звено: ярлык агента поставлен, а ступень живёт у другого.

        Класс ADR-412: объявление проводки, которой нет. Поэтому ярлык сверяется с
        ОБЁРТКОЙ агента — она и есть то, что запускает launchd.
        """
        agent = (self.entry or {}).get("producer")
        self.assertEqual(agent, "com.spa.decision_loop")
        wrapper = _REPO / "scripts" / "agent_decision_loop.sh"
        self.assertTrue(wrapper.is_file(), f"обёртки агента нет: {wrapper}")
        self.assertIn("findings_bridge", wrapper.read_text(encoding="utf-8"),
                      "обёртка названного агента не поднимает мост — ярлык ложный")

    def test_the_producer_tact_stays_below_the_probe_limit(self):
        """Порванное звено: равные пороги. Критерий протухал бы ровно в момент срока."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_nrc_tact", str(_REPO / PRODUCER_REL))
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        self.assertLess(mod.DEFAULT_MAX_AGE_H, ca._NO_REGRESSION_MAX_AGE_H)
        self.assertEqual((self.entry or {}).get("slo_hours"),
                         ca._NO_REGRESSION_MAX_AGE_H,
                         "SLO артефакта и предел пробы отвечают на ОДИН вопрос — "
                         "«ещё ли запись годна для вердикта»; расхождение здесь "
                         "означало бы две мерки у одного критерия")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
