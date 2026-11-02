# LLM_FORBIDDEN
"""Шард вернул 1, не назвав ни одного имени — ЧЕТЫРЕ рода, а ветка была на два (ADR-899).

**Авария, по которой написан файл (замер 2026-11-02, цикл #1012, заказ G894 п. 3).**
Контрольный прогон `41410492012` (`539bccdd4`) объявлен `INCOMPLETE` из-за одной строки
про шард 11: «pytest сказал «упало», а ни одного упавшего имени в записи нет». Разбор
артефакта шарда (`ctl-shard-11`, blob того же прогона) говорит другое:

* `junit.xml`: `tests=11261 failures=0 errors=0 skipped=107` — ни одного провала;
* `stream.jsonl`: запись конца есть, `status: 0`, `finished: 11261`, незакрытых 0;
* лог джобы: `10988 passed, 107 skipped, 166 subtests passed in 1254.27s` — ЗЕЛЕНО;
* `exit.json`: `{"exit": 1, "attempts": [{"attempt": 0, "exit": 1, "session_end": true}]}`.

Код выхода 1 при зелёной сессии поднял СЕССИОННЫЙ СТОРОЖ — `tracked_write_guard`
(хук `pytest_sessionfinish`, `trylast`), назвавший семь модулей, поменявших git-tracked
`data/*.json` вне своей базы. То есть шард был ИЗМЕРЕН полностью, а свод объявил его
незавершённым — и из-за этого цикл #1011 объявил НЕ ДОКАЗАННОЙ дельту, которую мерил.

**Это НЕ род ADR-892.** Там сессия умирала (код 3, `TypeError` в отрисовке провала) и
имён не существовало. Здесь сессия дошла до конца, имён нет потому, что их НЕТ, и оба
её собственных свидетельства (junit и потоковая запись) СОГЛАСНЫ между собой.

**Вторая половина замера — почему это не «редкий случай».** Отказ сторожа виден своду
только тогда, когда шард в остальном зелён; на шарде с настоящими провалами ветка
`code == 1 and shard_fails == 0` не срабатывает вовсе. Замер трёх прогонов подряд:

| прогон | shard-ов с отказом сторожа (по логам) | сколько назвал отчёт |
|---|---|---|
| 41399055995 (`42eb1dedf`) | ≥1 (скрыт провалами) | 0 |
| 41410492012 (`539bccdd4`) | ≥1 | 0 (назван НЕВЕРНО — «незавершён») |
| 41435243848 (`8f34a8894`) | **12 из 12** (68 нарушений) | **0** |

То есть сессионный сторож отказывал в каждом прогоне, а свод не назвал его НИ РАЗУ.

**Что проверяет этот файл.** Дверь `exit_without_names` на всех четырёх исходах, оба
направления у свода (род сторожа ⇒ RED и шард ПОЛНЫЙ · остальные три ⇒ INCOMPLETE с
названной причиной), запрет на ослабление (прогон, где упал ТОЛЬКО сторож, не имеет
права быть GREEN) и ЖИВУЮ сцену: настоящий `tracked_write_guard` + настоящий писатель
записи в одноразовом git-репозитории. Живая сцена отвечает на вопрос, которого
рукодельный словарь не задаёт вовсе — «существует ли этот род на самом деле».
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ci_control.py"


def _load_ci_control():
    spec = importlib.util.spec_from_file_location("_ci_control_guard_axis", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load_ci_control()

#: Дословная запись конца сессии шарда 11 прогона 41410492012 и его `exit.json`.
#: Байты взяты из артефакта `ctl-shard-11`, а не сочинены: контроль на выдуманной
#: форме доказывал бы согласие прибора с моим представлением о записи.
INCIDENT_END = {"e": "end", "finished": 11261, "started": 11095, "status": 0,
                "t": 1793608186.779}
INCIDENT_EXIT = {"exit": 1, "attempts": [{"attempt": 0, "exit": 1, "session_end": True,
                                          "requested": None}],
                 "crashes": [], "resumed": False, "remaining": None}


def _rec(*, present=True, end=INCIDENT_END, unfinished=()) -> dict:
    """Ровно те поля записи, которые читает дверь (форма `cc.load_stream`)."""
    return {"present": present, "end": None if end is None else dict(end),
            "unfinished": list(unfinished)}


class TheDoorHasFourAnswersNotTwo(unittest.TestCase):
    """У вопроса «вернул 1, имён нет — почему» четыре исхода, и каждый НАЗВАН."""

    def test_a_finished_green_session_means_a_session_guard_raised_the_code(self):
        kind, why = cc.exit_without_names(_rec())
        self.assertEqual(kind, cc.GUARD_EXIT)
        self.assertIn("сторож", why)

    def test_pytest_itself_saying_failed_without_names_stays_a_loss(self):
        kind, why = cc.exit_without_names(_rec(end={**INCIDENT_END, "status": 1}))
        self.assertEqual(kind, cc.NAMES_LOST)
        self.assertIn("status 1", why)

    def test_a_session_that_never_finished_is_the_adr_892_kind(self):
        kind, why = cc.exit_without_names(_rec(end=None))
        self.assertEqual(kind, cc.SESSION_BROKEN)
        self.assertIn("не дошёл до конца", why)

    def test_no_stream_record_at_all_is_unmeasured_with_a_named_reason(self):
        kind, why = cc.exit_without_names(_rec(present=False))
        self.assertEqual(kind, cc.EXIT_UNMEASURED)
        self.assertIn("потоковой записи нет", why)

    def test_an_end_record_older_than_the_status_field_is_unmeasured(self):
        for value in ({}, {"status": None}, {"status": "0"}, {"status": True}):
            with self.subTest(end=value):
                kind, why = cc.exit_without_names(_rec(end=value))
                self.assertEqual(kind, cc.EXIT_UNMEASURED, why)
                self.assertIn("status", why)

    def test_green_status_with_tests_left_open_is_unmeasured_not_a_guard(self):
        """Запись противоречит себе ⇒ fail-CLOSED, а не «сторож поднял»."""
        kind, why = cc.exit_without_names(_rec(unfinished=["t.py::a"]))
        self.assertEqual(kind, cc.EXIT_UNMEASURED)
        self.assertIn("не кончились", why)

    def test_every_answer_carries_a_reason_and_the_roster_is_closed(self):
        seen = {cc.exit_without_names(r)[0] for r in (
            _rec(), _rec(end={**INCIDENT_END, "status": 1}), _rec(end=None),
            _rec(present=False), _rec(unfinished=["x"]))}
        self.assertEqual(seen, {cc.GUARD_EXIT, cc.NAMES_LOST, cc.SESSION_BROKEN,
                                cc.EXIT_UNMEASURED})
        for r in (_rec(), _rec(end=None), _rec(present=False)):
            self.assertTrue(cc.exit_without_names(r)[1].strip())


# ── живая сцена: настоящий сторож, настоящий писатель записи ─────────────────

def _git(root: Path, *args: str) -> None:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, f"git {args}: {out.stderr}"


def _scene(tmp: Path, *, dirty: bool) -> Path:
    """Одноразовый git-репозиторий, в котором тест ПИШЕТ в git-tracked `data/`.

    Имя ветки объявляется входом (`git init -b main`) — § GIT-ОКРУЖЕНИЕ правила
    доставки: без `-b` имя берётся у конфига ХОСТА, и сцена жила бы по-разному на
    Маке и на `ubuntu-latest`.
    """
    root = tmp / ("dirty" if dirty else "clean")
    (root / "tests").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "data" / "probe.json").write_text('{"v": 0}\n', encoding="utf-8")
    (root / "conftest.py").write_text(textwrap.dedent(f"""
        import importlib.util
        from pathlib import Path
        _p = Path({str(_REPO_ROOT / "spa_core" / "tests" / "tracked_write_guard.py")!r})
        _s = importlib.util.spec_from_file_location("_twg_live", _p)
        _m = importlib.util.module_from_spec(_s)
        _s.loader.exec_module(_m)

        def pytest_configure(config):
            _m.install(config)
    """), encoding="utf-8")
    body = "def test_green(): assert True\n"
    if dirty:
        body += textwrap.dedent("""
            def test_writes_a_tracked_file():
                import json, pathlib
                p = pathlib.Path(__file__).resolve().parents[1] / "data" / "probe.json"
                p.write_text(json.dumps({"v": 1}) + "\\n", encoding="utf-8")
                assert p.exists()
        """)
    (root / "tests" / "test_probe.py").write_text(body, encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "scene@example.invalid")
    _git(root, "config", "user.name", "scene")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "scene")
    return root


def _run(root: Path, args: list[str], env_extra: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT), "SPA_ENV": "ci",
           "PYTHONHASHSEED": "0", **env_extra}
    for name in ("SPA_PYTEST_STREAM", "SPA_PYTEST_MANIFEST"):
        if name not in env_extra:
            env.pop(name, None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--rootdir", str(root), "-q",
         "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=300)


class TheKindExistsOnALiveRun(unittest.TestCase):
    """Род не выдуман: настоящий сторож поднимает код над ЗЕЛЁНОЙ сессией."""

    def test_the_guard_raises_the_exit_code_while_pytest_reports_no_failure(self):
        tmp = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory())).resolve()
        root = _scene(tmp, dirty=True)
        stream = root / "stream.jsonl"
        proc = _run(root, ["tests", "-p", "spa_core.ci.pytest_stream_record"],
                    {"SPA_PYTEST_STREAM": str(stream)})
        tail = (proc.stdout + proc.stderr)[-1200:]
        self.assertIn("tests changed git-tracked state", tail, tail)
        self.assertIn("НОВОЕ (вне базы)", tail, tail)
        self.assertNotIn("failed", tail, tail)            # ни одного провала теста
        self.assertEqual(proc.returncode, 1, tail)        # и всё-таки код 1
        rec = cc.load_stream(str(stream))
        self.assertEqual(rec["end"]["status"], 0, rec["end"])
        self.assertEqual(sorted(set(rec["outcomes"].values())), [cc.PASSED])
        self.assertEqual(cc.exit_without_names(rec)[0], cc.GUARD_EXIT)

    def test_the_same_scene_without_a_write_exits_zero(self):
        """Обратная сторона: сторожу не на что отказывать — код 0, рода нет."""
        tmp = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory())).resolve()
        root = _scene(tmp, dirty=False)
        stream = root / "stream.jsonl"
        proc = _run(root, ["tests", "-p", "spa_core.ci.pytest_stream_record"],
                    {"SPA_PYTEST_STREAM": str(stream)})
        tail = (proc.stdout + proc.stderr)[-800:]
        self.assertEqual(proc.returncode, 0, tail)
        self.assertNotIn("tests changed git-tracked state", tail, tail)
        self.assertEqual(cc.load_stream(str(stream))["end"]["status"], 0)


# ── свод: оба направления ────────────────────────────────────────────────────

class TheSweepCallsTheShardMeasured(unittest.TestCase):
    """Сцена свода собирается ЖИВЫМИ плагинами, а не рукописным словарём.

    Урок #944/#945: контроль на рукодельной записи меряет СВОЁ представление о форме.
    Поэтому население, план и записи шарда здесь делают те же модули, что в CI, и
    правится ровно одно число — код в `exit.json`, то есть тот самый вход, который
    в аварии разошёлся с записью.
    """

    def _built(self, tmp: Path, *, exit_code: int, end_status=0, drop_end=False,
               drop_stream=False):
        root = tmp / "scene"
        (root / "tests").mkdir(parents=True)
        (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (root / "tests" / "test_g.py").write_text("def test_a(): assert True\n"
                                                  "def test_b(): assert True\n",
                                                  encoding="utf-8")
        ctl = root / "ctl"
        proc = _run(root, ["tests", "--collect-only",
                           "-p", "spa_core.ci.pytest_collect_manifest"],
                    {"SPA_PYTEST_MANIFEST": str(ctl / "collected.jsonl")})
        self.assertIn(proc.returncode, (0, 1), proc.stdout[-600:])
        weights = tmp / "w.json"
        weights.write_text(json.dumps({"files": {}, "per_test_fallback_s": 1.0}),
                           encoding="utf-8")
        self.assertEqual(cc.main(["plan", "--collected", str(ctl / "collected.jsonl"),
                                  "--weights", str(weights), "--shards", "1",
                                  "--budget-min", "60", "--sha", "deadbeef",
                                  "--roots", "tests", "--out-dir", str(ctl)]), 0)
        manifest = json.loads((ctl / "manifest.json").read_text(encoding="utf-8"))
        shards = root / "shards"
        out = shards / f"{cc.SHARD_DIR_PREFIX}0"
        out.mkdir(parents=True)
        (out / cc.SHARD_FILE).write_text(json.dumps({"shard": 0}), encoding="utf-8")
        files = (ctl / "shard-0.txt").read_text(encoding="utf-8").split()
        rc = _run(root, [*files, "-p", "spa_core.ci.pytest_stream_record",
                         "-p", "spa_core.ci.pytest_collect_manifest"],
                  {"SPA_PYTEST_STREAM": str(out / cc.STREAM_FILE),
                   "SPA_PYTEST_MANIFEST": str(out / cc.COLLECTED_FILE)}).returncode
        self.assertEqual(rc, 0)                       # сцена зелена ПО ПОСТРОЕНИЮ
        if drop_stream:
            (out / cc.STREAM_FILE).unlink()
        else:
            lines = [json.loads(x) for x in
                     (out / cc.STREAM_FILE).read_text(encoding="utf-8").splitlines() if x]
            kept = []
            for ev in lines:
                if ev.get("e") == "end":
                    if drop_end:
                        continue
                    ev = {**ev, "status": end_status}
                kept.append(ev)
            (out / cc.STREAM_FILE).write_text(
                "\n".join(json.dumps(x) for x in kept) + "\n", encoding="utf-8")
        (out / cc.EXIT_FILE).write_text(
            json.dumps({**INCIDENT_EXIT, "exit": exit_code,
                        "attempts": [{"attempt": 0, "exit": exit_code,
                                      "session_end": True, "requested": None}]}),
            encoding="utf-8")
        return manifest, shards

    def _tmp(self) -> Path:
        # `.resolve()` обязателен: на macOS `/var` есть ссылка на `/private/var`, и
        # pytest, считая nodeid от такого корня, отдаёт `test_g.py` вместо
        # `tests/test_g.py` — сцена перестаёт собираться по СВОЕМУ же плану.
        return Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory())).resolve()

    def test_a_guard_raised_exit_is_red_and_the_shard_counts_as_complete(self):
        manifest, shards = self._built(self._tmp(), exit_code=1)
        r = cc.aggregate(manifest, shards, "failure")
        self.assertEqual(r["incomplete"], [])
        self.assertEqual(r["verdict"], cc.RED)             # отказ сторожа ≠ «ничего»
        self.assertEqual(r["totals"]["shards_complete"], r["totals"]["shards_planned"])
        self.assertEqual(r["totals"]["failed"], 0)
        self.assertEqual(r["guard_exits"]["n"], 1)
        self.assertEqual(r["guard_exits"]["shards"][0]["shard"], 0)
        self.assertEqual(r["shards"][0]["exit_without_names"], cc.GUARD_EXIT)
        self.assertIn("сторож", cc.render_md(r))

    def test_removing_the_channel_from_the_verdict_would_be_a_weakening(self):
        """Прогон, где упал ТОЛЬКО сторож, не имеет права быть GREEN (инв. #16)."""
        manifest, shards = self._built(self._tmp(), exit_code=1)
        r = cc.aggregate(manifest, shards, "failure")
        self.assertFalse(r["failures"])
        self.assertFalse(r["collect_errors"])
        self.assertNotEqual(r["verdict"], cc.GREEN)

    def test_the_same_code_without_the_green_record_stays_incomplete(self):
        """Другое направление: pytest сам сказал «упало» — прежний вердикт цел."""
        manifest, shards = self._built(self._tmp(), exit_code=1, end_status=1)
        r = cc.aggregate(manifest, shards, "failure")
        self.assertEqual(r["verdict"], cc.INCOMPLETE)
        self.assertEqual(r["guard_exits"]["n"], 0)
        self.assertIn("ни одного упавшего имени", " ".join(
            x["reason"] for x in r["incomplete"]))
        self.assertIn("status 1", " ".join(x["reason"] for x in r["incomplete"]))

    def test_a_session_that_never_finished_stays_incomplete(self):
        manifest, shards = self._built(self._tmp(), exit_code=1, drop_end=True)
        r = cc.aggregate(manifest, shards, "failure")
        self.assertEqual(r["verdict"], cc.INCOMPLETE)
        self.assertEqual(r["guard_exits"]["n"], 0)

    def test_a_shard_without_a_record_stays_incomplete(self):
        manifest, shards = self._built(self._tmp(), exit_code=1, drop_stream=True)
        r = cc.aggregate(manifest, shards, "failure")
        self.assertEqual(r["verdict"], cc.INCOMPLETE)
        self.assertEqual(r["guard_exits"]["n"], 0)

    def test_an_honest_zero_exit_names_no_kind_at_all(self):
        manifest, shards = self._built(self._tmp(), exit_code=0)
        r = cc.aggregate(manifest, shards, "success")
        self.assertEqual(r["verdict"], cc.GREEN, r["incomplete"])
        self.assertEqual(r["guard_exits"]["n"], 0)
        self.assertNotIn("exit_without_names", r["shards"][0])


class TheReportDeclaresTheChannel(unittest.TestCase):
    def test_the_channel_has_its_own_schema_so_an_older_report_is_not_a_zero(self):
        """Отчёт БЕЗ блока обязан читаться как «старше канала», а не как ноль."""
        self.assertTrue(cc.GUARD_EXIT_SCHEMA)
        self.assertNotEqual(cc.GUARD_EXIT_SCHEMA, cc.REPORT_SCHEMA)
        self.assertEqual(cc.render_md({"verdict": cc.RED, "incomplete": [],
                                       "guard_exits": {}}).count("сторож"), 0)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
