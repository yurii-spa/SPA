"""Тесты замера §45 ТЗ CIO «Architecture constraints».

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: он воспроизводит дефект, который
эта проба реально имела в цикле #513 и который был найден ЗАМЕРОМ, а не
перечитыванием. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Дефекты, закреплённые здесь:

1. **Упоминание принимали за исполнение.** Первая редакция считала дверью к
   LLM любой модуль, где рядом живут вызов ``subprocess`` и строка про LLM.
   Она назвала дверьми два невиновных модуля дерева: ``fill_agent_passports``
   (там ``"CLAUDE_BIN"`` — ИСКОМАЯ строка чужого паспорта, а зовётся git) и
   ``telegram_watcher`` (там ``ANTHROPIC_API_KEY`` — слово внутри текста
   ОШИБКИ про Keychain, а зовётся ``security``). Ложная дверь не краснеет
   никогда: она молча раздувает счёт и выглядит как работа.
2. **Достижимость выдавали за управление.** Из ``spa_core/monitoring/`` LLM
   достижим — и это НЕ находка: все пути идут в канал уведомления владельца,
   то есть в explanation layer, который владелец разрешает.
3. **«Сторож есть» вместо «сторож видит».** Слепота действующей проверки
   меряется ЗАМЕРОМ на копии дерева, а не рассуждением; отсутствие самой
   проверки — самостоятельный ТРЕТИЙ исход, а не ноль нарушений.
4. **Докстрока — тоже литерал.** Модуль, ОПИСЫВАЮЩИЙ подпись транзакции,
   попадал в подписанты, потому что литералы брались вместе с докстроками.
"""
# FROZEN-DATE-OK: injected-clock — единственная отметка времени отчёта приходит
# аргументом `run(now=_FROZEN)`; ни одна проверка ниже не спрашивает стенные часы.
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import cio_architecture_constraints as mod

_FROZEN = dt.datetime(2026, 9, 7, 12, 0, 0, tzinfo=dt.timezone.utc)
_REPO = mod.REPO_ROOT


def _resp(src: str) -> set[str]:
    return mod.module_responsibilities(ast.parse(src))


def _door(src: str) -> str:
    return mod.llm_door(ast.parse(src))


class TestMentionIsNotExecution(unittest.TestCase):
    """Дефект 1 и 4: слово о работе ≠ работа."""

    def test_docstring_naming_the_rpc_is_not_a_signer(self):
        src = ('"""Разбор аварии: узел отдал eth_sendRawTransaction дважды.\n\n'
               'SPA_PRIVATE_KEY при этом не читался.\n"""\n'
               "def note():\n    return 1\n")
        self.assertNotIn("sign", _resp(src))

    def test_docstring_that_IS_the_literal_is_still_not_a_signer(self):
        """Единственная сцена, которой ``_docstring_ids`` вообще управляет.

        ⚠️ Замер 07.09 (цикл #514), а не рассуждение: снятие исключения
        докстрок (``docs = set()``) на живом дереве **не меняет ничего** —
        2070 разобранных модулей, вердикт разошёлся у 0, двери у 0. Причина в
        том, что признаки сверяются ТОЧНЫМ совпадением множеств, а докстрока
        целиком никогда не равна ``eth_sendRawTransaction``. Поэтому тест выше
        (докстрока СОДЕРЖИТ имя RPC) проходит и без исключения докстрок — он
        закрепляет точное сравнение, но не сам сторож.

        Здесь докстрока РАВНА литералу — и только на такой сцене исключение
        докстрок решает исход. Это положительный контроль на КОНТРАКТ сторожа,
        а не воспроизведение живой аварии, и сказано это вслух, чтобы никто не
        прочитал его как «дефект 4 повторяется в проде».
        """
        src = '"""eth_sendRawTransaction"""\n\n\ndef note():\n    return 1\n'
        self.assertNotIn("sign", _resp(src))
        self.assertIn("sign", _resp('x = "eth_sendRawTransaction"\n'))

    def test_comment_naming_the_rpc_is_not_a_signer(self):
        src = ("# отправка идёт через eth_sendRawTransaction, но не здесь\n"
               "def note():\n    return 1\n")
        self.assertNotIn("sign", _resp(src))

    def test_code_literal_of_the_rpc_is_a_signer(self):
        src = ('def send(tx):\n    return rpc("eth_sendRawTransaction", tx)\n')
        self.assertIn("sign", _resp(src))

    def test_search_needle_is_not_a_door(self):
        """Живой образец: `fill_agent_passports` ищет строку, а зовёт git."""
        src = ("import subprocess\n\n\n"
               "def passport(txt):\n"
               '    if "CLAUDE_BIN" in txt:\n'
               "        return True\n"
               '    return subprocess.run(["git", "log"])\n')
        self.assertEqual("", _door(src))

    def test_error_message_naming_the_sdk_is_not_a_door(self):
        """Живой образец: `telegram_watcher` зовёт `security`, а не LLM."""
        src = ("import subprocess\n\n\n"
               "def read(service):\n"
               "    try:\n"
               '        return subprocess.run(["security", "find-generic-password",\n'
               '                               "-s", service, "-w"])\n'
               "    except Exception:\n"
               '        raise SystemExit("ANTHROPIC_API_KEY / TELEGRAM_BOT_TOKEN '
               'not found in Keychain")\n')
        self.assertEqual("", _door(src))

    def test_binary_reaching_argv_is_a_door(self):
        src = ("import subprocess\n\n\n"
               "def ask(q):\n"
               '    return subprocess.run(["/usr/local/bin/claude", "-p", q])\n')
        self.assertEqual("subprocess", _door(src))

    def test_binary_bound_through_env_is_a_door(self):
        """Так устроена НАСТОЯЩАЯ дверь дерева (`ask_router._CLAUDE`)."""
        src = ("import os\nimport subprocess\n\n"
               '_C = os.environ.get("SPA_CLAUDE_BIN") or "/abs/path/claude"\n\n\n'
               "def ask(q):\n"
               '    return subprocess.run([_C, "-p", q])\n')
        self.assertEqual("subprocess", _door(src))

    def test_sdk_import_is_a_door(self):
        self.assertEqual("sdk", _door("import anthropic\n"))
        self.assertEqual("sdk", _door("from openai import OpenAI\n"))


class TestResponsibilitySignatures(unittest.TestCase):
    """Признак каждой из пяти ответственностей меряет то, что назван мерить."""

    def test_rate_function_returning_a_literal_is_not_a_computation(self):
        src = "def get_apy(name):\n    return 4.5\n"
        self.assertNotIn("apy", _resp(src))

    def test_rate_function_returning_an_expression_is_a_computation(self):
        src = "def get_apy(raw):\n    return raw['rate'] * 100.0\n"
        self.assertIn("apy", _resp(src))

    def test_building_the_verdict_is_a_risk_decision(self):
        src = "def evaluate(t):\n    return {'approved': True, 'target': t}\n"
        self.assertIn("risk_decision", _resp(src))

    def test_reading_someone_elses_verdict_is_not_a_risk_decision(self):
        src = "def act(v):\n    if v['approved']:\n        return 1\n    return 0\n"
        self.assertNotIn("risk_decision", _resp(src))

    def test_gas_rpc_literal_is_gas(self):
        src = 'def gas():\n    return rpc("eth_gasPrice")\n'
        self.assertIn("gas", _resp(src))

    def test_own_network_door_is_market_read(self):
        src = ("import urllib.request\n\n\n"
               'def fetch():\n    return urllib.request.urlopen("https://x/y")\n')
        self.assertIn("market_read", _resp(src))


class TestPositiveControlRefusesABlindProbe(unittest.TestCase):
    """Контроль — условие ВСЕГО отчёта, а не украшение рядом с ним."""

    def test_synthetic_monolith_is_recognised_on_all_five(self):
        got = mod.module_responsibilities(ast.parse(mod._CONTROL_MONOLITH))
        self.assertEqual({k for k, _, _ in mod.RESPONSIBILITIES}, got)

    def test_verdict_refused_when_probe_is_blind_to_the_known_door(self):
        """Проба, ослепшая на настоящей двери, не имеет права закрывать §45."""
        real = mod.scan_tree

        def blind(root):
            out = real(root)
            out["doors"].pop("spa_core/telegram/ask_router.py", None)
            return out

        mod.scan_tree = blind
        try:
            doc = mod.run(root=_REPO, write=False, now=_FROZEN)
        finally:
            mod.scan_tree = real
        self.assertEqual(mod.UNCHECKED, doc["overall"])
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual([], doc["findings"])
        self.assertTrue(any("контроль" in u for u in doc["unchecked"]))

    def test_verdict_refused_when_mentions_are_counted_as_execution(self):
        """Обратный контроль: раздувший счёт ложными не выпускает счёт вовсе."""
        real = mod.scan_tree

        def loose(root):
            out = real(root)
            out["doors"]["spa_core/monitoring/owner_decision_pending.py"] = "subprocess"
            return out

        mod.scan_tree = loose
        try:
            doc = mod.run(root=_REPO, write=False, now=_FROZEN)
        finally:
            mod.scan_tree = real
        self.assertEqual(mod.UNCHECKED, doc["overall"])
        self.assertIn("owner_decision_pending", doc["control"]["reason"])

    def test_mention_only_specimen_of_the_live_tree_stays_clean(self):
        """Тот самый образец, ради которого докстроки исключены из литералов."""
        scan = mod.scan_tree(_REPO)
        rel = "spa_core/monitoring/owner_decision_pending.py"
        self.assertTrue(os.path.isfile(os.path.join(_REPO, rel)))
        self.assertEqual("", scan["doors"].get(rel, ""))
        self.assertNotIn("sign", scan["responsibilities"].get(rel, []))

    def test_live_tree_door_is_recognised(self):
        scan = mod.scan_tree(_REPO)
        self.assertEqual("subprocess",
                         scan["doors"].get("spa_core/telegram/ask_router.py"))

    def test_empty_tree_is_loud_unchecked_not_clean(self):
        """⚠️ Вердикт проверяется вместе с ПРИЧИНОЙ — иначе тест не о ветке.

        Замер 07.09 (цикл #514): на пустом дереве ветка «ни один модуль не
        разобран» и ветка «положительный контроль не пройден» дают ОДНУ И ТУ ЖЕ
        тройку — ``overall=UNCHECKED``, ``findings=[]``, ``unchecked`` непустой.
        Поэтому снятие первой ветки (``if not scan["parsed"]`` → ``if False``)
        не красило тест: управление просто доходило до К2, который на пустом
        дереве не находит известной двери и тоже отказывает. Тест утверждал
        верное о неверной ветке — класс «мерить, КАКАЯ ветка сработала».

        Причина здесь и есть предмет: сказать «мерить нечем» и «проба слепа» —
        разные диагнозы, и чинят их по-разному.
        """
        with tempfile.TemporaryDirectory() as tmp:
            doc = mod.run(root=tmp, write=False, now=_FROZEN)
        self.assertEqual(mod.UNCHECKED, doc["overall"])
        self.assertEqual([], doc["findings"])
        self.assertTrue(doc["unchecked"])
        self.assertEqual("дерево не разобрано", doc["control"]["reason"])
        self.assertIn("ни один модуль рантайма не разобран", doc["unchecked"][0])

    def test_the_two_unchecked_branches_do_not_share_a_reason(self):
        """Обратная половина: ветки обязаны быть РАЗЛИЧИМЫ по причине.

        Без этого теста «причина названа» держится на одной строке в одном
        месте: достаточно сделать причины одинаковыми, и тест выше снова
        станет верным утверждением о любой из двух веток.
        """
        blind = mod._positive_control(
            _REPO, {"doors": {}, "responsibilities": {}, "parsed": 1,
                    "unparsed": []})
        self.assertFalse(blind[0])
        self.assertNotEqual("дерево не разобрано", blind[1])
        self.assertIn("К2", blind[1])


class TestGuardBlindness(unittest.TestCase):
    """Дефект 3: «сторож есть» и «сторож видит» — разные утверждения."""

    def test_sdk_seen_and_subprocess_not(self):
        got = mod.lint_blindness(_REPO)
        self.assertTrue(got["measured"], got.get("reason"))
        self.assertTrue(got["scenes"]["sdk_import"]["seen"])
        self.assertFalse(got["scenes"]["subprocess_binary"]["seen"])
        self.assertTrue(got["blind_to_subprocess"])

    def test_missing_tool_is_a_third_outcome_not_zero_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = mod.lint_blindness(tmp)
        self.assertFalse(got["measured"])
        self.assertIn("lint_llm_forbidden", got["reason"])
        self.assertNotIn("blind_to_subprocess", got)

    def test_broken_control_scene_blocks_the_finding(self):
        """Сторож, не поймавший даже SDK, запущен неверно — счёт не читать."""
        real = mod.lint_blindness
        mod.lint_blindness = lambda root: {
            "measured": True, "reason": "", "control_ok": False,
            "blind_to_subprocess": True,
            "scenes": {"sdk_import": {"violations": 0, "seen": False},
                       "subprocess_binary": {"violations": 0, "seen": False}}}
        try:
            doc = mod.run(root=_REPO, write=False, now=_FROZEN)
        finally:
            mod.lint_blindness = real
        codes = {f["code"] for f in doc["findings"]}
        self.assertNotIn("guard_blind_to_real_door", codes)
        self.assertTrue(any("контрольная сцена" in u for u in doc["unchecked"]))

    def test_lint_probe_writes_nothing_into_the_tree(self):
        before = sorted(os.listdir(os.path.join(_REPO, "spa_core", "risk")))
        mod.lint_blindness(_REPO)
        self.assertEqual(before,
                         sorted(os.listdir(os.path.join(_REPO, "spa_core", "risk"))))


class TestLiveVerdict(unittest.TestCase):
    """Что проба говорит о ЖИВОМ дереве — якорь против молчаливого регресса."""

    @classmethod
    def setUpClass(cls):
        cls.doc = mod.run(root=_REPO, write=False, now=_FROZEN)

    def test_control_passed(self):
        self.assertTrue(self.doc["control"]["passed"],
                        self.doc["control"]["reason"])

    def test_time_is_an_input_not_the_wall_clock(self):
        self.assertEqual(_FROZEN.isoformat(), self.doc["generated_at"])

    def test_execution_adapters_are_named_as_the_concentration(self):
        named = {m["module"] for m in self.doc["concentration"]["modules"]
                 if m["count"] >= 4}
        self.assertIn("spa_core/execution/aave_v3_adapter.py", named)
        self.assertIn("spa_core/execution/compound_v3_adapter.py", named)
        self.assertGreaterEqual(self.doc["concentration"]["max"], 4)

    def test_reach_through_the_explanation_channel_is_not_a_finding(self):
        """Дефект 2: достижимость LLM из monitoring — измерение, не нарушение."""
        codes = {f["code"] for f in self.doc["findings"]}
        self.assertNotIn("llm_on_control_path", codes)
        mon = self.doc["llm"]["by_layer"]["6-monitoring"]
        self.assertGreater(mon["modules_reaching"], 0)
        self.assertTrue(mon["through_explanation_channel"])

    def test_money_path_layers_do_not_reach_the_llm(self):
        for layer in ("1-data", "2-optimizer", "3-risk-policy",
                      "4-execution-planner", "5-execution"):
            self.assertEqual(
                0, self.doc["llm"]["by_layer"][layer]["modules_reaching"], layer)

    def test_guard_blindness_is_reported_as_critical(self):
        codes = {f["code"] for f in self.doc["findings"]}
        self.assertIn("guard_blind_to_real_door", codes)

    def test_report_is_json_serialisable_and_declares_its_signatures(self):
        json.dumps(self.doc, ensure_ascii=False)
        keys = {r["key"] for r in self.doc["responsibilities_declared"]}
        self.assertEqual({k for k, _, _ in mod.RESPONSIBILITIES}, keys)
        for row in self.doc["responsibilities_declared"]:
            self.assertTrue(row["measured_as"].strip())


class TestExplanationChannelFilter(unittest.TestCase):
    """Фильтр «через канал объяснения» — сторож, лишний при сегодняшнем дереве.

    ⚠️ Замер 07.09 (цикл #514): у ВСЕХ пяти денежных слоёв
    ``modules_reaching == 0``, поэтому список нарушителей пуст с фильтром и
    без него, и снятие фильтра не красило ни одного теста набора. Соседний
    тест `test_money_path_layers_do_not_reach_the_llm` закрепляет как раз
    сегодняшний ноль — то есть ровно ту причину, по которой фильтр не
    проверялся. Проверить его можно только состоянием, которого в дереве нет:
    денежный слой, который LLM ДОСТИГАЕТ.

    Это не гипотеза «а вдруг»: если такое состояние однажды наступит, от этого
    фильтра зависит, назовут ли его находкой или простят как канал уведомления.
    """

    def test_money_layer_reaching_off_channel_is_named(self):
        named = mod.control_layers_reaching_llm({
            "3-risk-policy": {"modules_reaching": 1,
                              "through_explanation_channel": False}})
        self.assertEqual(["3-risk-policy"], named)

    def test_money_layer_reaching_through_the_channel_is_forgiven(self):
        named = mod.control_layers_reaching_llm({
            "3-risk-policy": {"modules_reaching": 1,
                              "through_explanation_channel": True}})
        self.assertEqual([], named)

    def test_monitoring_is_excluded_even_off_channel(self):
        """Монитор — разрешённый владельцем explanation layer, не нарушитель."""
        named = mod.control_layers_reaching_llm({
            "6-monitoring": {"modules_reaching": 7,
                             "through_explanation_channel": False}})
        self.assertEqual([], named)

    def test_layer_that_reaches_nothing_is_not_named(self):
        named = mod.control_layers_reaching_llm({
            "5-execution": {"modules_reaching": 0,
                            "through_explanation_channel": False}})
        self.assertEqual([], named)

    def test_run_uses_this_function_and_not_its_own_copy(self):
        """Проводка: ослепим функцию — вердикт `run` обязан пойти за ней.

        Без этого теста фильтр можно было бы починить в функции и оставить
        вторую копию условия внутри ``run``; тесты выше остались бы зелёными.
        """
        real = mod.control_layers_reaching_llm
        try:
            mod.control_layers_reaching_llm = lambda _by_layer: ["3-risk-policy"]
            doc = mod.run(root=_REPO, write=False, now=_FROZEN)
        finally:
            mod.control_layers_reaching_llm = real
        codes = {f["code"] for f in doc["findings"]}
        self.assertIn("llm_on_control_path", codes)
        self.assertNotIn("llm_reach_explanation_only", codes)


class TestWiring(unittest.TestCase):
    """Артефакт без объявленного производителя и читателя не проверяется вовсе."""

    def test_office_step_declares_schema_and_producer(self):
        import importlib.util
        path = os.path.join(_REPO, "scripts", "consume_office_reports.py")
        spec = importlib.util.spec_from_file_location("_office_probe", path)
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        name = os.path.basename(mod.REPORT_REL)
        self.assertIn(name, office._READ_SCHEMA)
        self.assertEqual("spa_core/monitoring/cio_architecture_constraints.py",
                         office._PRODUCER.get(name))

    def test_producer_announces_the_artifact(self):
        """Дыра, которую цикл #512 оставил соседу: манифест знал, код молчал."""
        from spa_core.monitoring import findings_bridge
        self.assertIn(mod.REPORT_REL, findings_bridge.PRODUCES)

    def test_manifest_declares_the_artifact_in_both_homes(self):
        with open(os.path.join(_REPO, "architecture", "manifest.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        paths = {a["path"] for a in manifest.get("artifacts", [])}
        self.assertIn(mod.REPORT_REL, paths)
        produced = set()
        for agent in manifest.get("agents", []):
            for art in agent.get("produces", []) or []:
                produced.add(art.get("artifact"))
        self.assertIn(mod.REPORT_REL, produced)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
