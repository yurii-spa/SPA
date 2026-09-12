#!/usr/bin/env python3
"""Приёмка стража «доставка уносит имя, которого автор не видел» (заказ #570, ADR-346).

Положительный контроль здесь — НЕ синтетика: это байты настоящей аварии 12.09,
взятые из истории репозитория по blob-sha. Коммит `6322d0d56` унёс из моста находок
двадцать строк проводки ADR-343, доставленной 42 минутами раньше, и ни один сторож не
сказал об этом ни слова. Обратный контроль — тоже настоящие байты: объявленный ОТКАТ
`4bea832d1`, где автор удалял ОСОЗНАННО и страж обязан молчать.

Предпосылку (доступность истории) тест обеспечивает сам и, если не смог, падает
ГРОМКО: «не измерено», выданное за «прошло», — ровно тот дефект, против которого
написан и заказ, и инвариант #17. Скипа здесь нет намеренно.

Ни один существующий тест этим файлом не правится, не скипается и не сужается (инв. #16).
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

from spa_core.monitoring import delivery_name_loss as dnl
from spa_core.monitoring.delivery_name_loss import (
    DELETED_BY_AUTHOR, NEVER_SEEN_BY_AUTHOR, UNMEASURED,
    classify_loss, refusal_text, significant_names)

REPO = Path(__file__).resolve().parents[2]

#: Байты аварии 12.09 (blob-sha из истории; см. ADR-346).
BASE_BLOB = "0d5a06240c220fa3e0643089bb5402a929a82a38"    # база автора, b1d15bc8e
REMOTE_BLOB = "8488794815c62c181eadc523f121b65b4476ea1f"  # origin в момент пуша, e116ae03c
LOCAL_BLOB = "6f0928f6bc3b94684738a61dfdf07e84175f1a46"   # что ушло коммитом 6322d0d56


def blob(sha: str) -> bytes:
    """Байты объекта из истории. Не достались ⇒ ГРОМКОЕ падение, не скип."""
    r = subprocess.run(["git", "cat-file", "blob", sha],
                       cwd=REPO, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise AssertionError(
            f"предпосылка теста НЕ ОБЕСПЕЧЕНА: blob {sha[:8]} не прочитан из истории "
            f"({r.stderr.decode(errors='replace')[:200]}). Это «не измерено», а не "
            f"«прошло»: молчать об этом тест не имеет права.")
    return r.stdout


# ──────────────────── положительный контроль: авария 12.09 ────────────────────

class TheAccidentOfTheTwelfth(unittest.TestCase):
    """Байт-в-байт та доставка, ради которой страж и написан."""

    def test_the_push_that_lost_the_wiring_is_named_never_seen(self):
        verdict = classify_loss(blob(BASE_BLOB), blob(LOCAL_BLOB), blob(REMOTE_BLOB))
        self.assertEqual(verdict["status"], NEVER_SEEN_BY_AUTHOR)
        self.assertIn("haystack_origin_census", verdict[NEVER_SEEN_BY_AUTHOR])

    def test_nothing_is_charged_to_the_author_as_a_deliberate_deletion(self):
        """Автор не удалял — приписать ему удаление значило бы соврать о причине."""
        verdict = classify_loss(blob(BASE_BLOB), blob(LOCAL_BLOB), blob(REMOTE_BLOB))
        self.assertEqual(verdict[DELETED_BY_AUTHOR], [])

    def test_the_refusal_names_the_lost_thing_and_not_only_the_file(self):
        """Прежняя нота печатала ИМЯ ФАЙЛА и причину расхождения — и ни одного байта."""
        text = refusal_text("spa_core/monitoring/findings_bridge.py",
                            classify_loss(blob(BASE_BLOB), blob(LOCAL_BLOB),
                                          blob(REMOTE_BLOB)))
        self.assertIn("haystack_origin_census", text)

    def test_a_line_level_measure_would_have_stayed_silent_on_locals(self):
        """Единица — ЗНАЧИМОЕ имя, а не любой идентификатор.

        Первый замер заказа брал любой идентификатор и дал 90 исчезновений за
        неделю, почти сплошь локальные переменные. Сторож с таким населением
        кричит шесть раз в день, и его выключают.
        """
        names = significant_names(blob(REMOTE_BLOB))
        self.assertIn("haystack_origin_census", names)
        self.assertNotIn("_hoc", names)   # локальная переменная той же ступени


# ──────────────────── обратный контроль: осознанное удаление ────────────────────

class ADeliberateRemovalStaysSilent(unittest.TestCase):
    """Настоящий объявленный ОТКАТ `4bea832d1` (ADR-331). Страж обязан молчать."""

    def _revert_pair(self):
        path = "spa_core/paper_trading/pool_alias_gate.py"
        before = subprocess.run(["git", "show", f"4bea832d1^:{path}"],
                                cwd=REPO, capture_output=True)
        after = subprocess.run(["git", "show", f"4bea832d1:{path}"],
                               cwd=REPO, capture_output=True)
        if before.returncode != 0 or after.returncode != 0:
            raise AssertionError(
                "предпосылка теста НЕ ОБЕСПЕЧЕНА: коммит 4bea832d1 не прочитан из "
                "истории — это «не измерено», а не «прошло».")
        return before.stdout, after.stdout

    def test_names_the_author_did_see_are_not_a_finding(self):
        before, after = self._revert_pair()
        # Автор сидел на свежем origin: база И ЕСТЬ remote.
        verdict = classify_loss(before, after, before)
        self.assertEqual(verdict[NEVER_SEEN_BY_AUTHOR], [])
        self.assertEqual(verdict["status"], DELETED_BY_AUTHOR)

    def test_and_the_guard_prints_nothing_for_it(self):
        before, after = self._revert_pair()
        self.assertEqual(
            refusal_text("spa_core/paper_trading/pool_alias_gate.py",
                         classify_loss(before, after, before)), "")


# ──────────────────── третий исход ────────────────────

class TheThirdOutcome(unittest.TestCase):
    """«Не измерено» не складывается с долями и никогда не читается как «чисто»."""

    def test_an_unmeasurable_base_is_not_clean(self):
        remote = b"import alpha\nX = 1\n"
        local = b"X = 1\n"
        verdict = classify_loss(None, local, remote)
        self.assertEqual(verdict["status"], UNMEASURED)
        self.assertIn("alpha", verdict["lost_unattributed"])
        self.assertEqual(verdict[NEVER_SEEN_BY_AUTHOR], [])
        self.assertEqual(verdict[DELETED_BY_AUTHOR], [])

    def test_an_unmeasurable_base_still_says_what_is_going_under_the_knife(self):
        note = refusal_text("x.py", classify_loss(None, b"X = 1\n",
                                                  b"import alpha\nX = 1\n"))
        self.assertIn("alpha", note)
        self.assertIn("НЕЧЕМ", note)

    def test_an_unparsable_file_is_unmeasured_not_empty(self):
        """Пустое множество значило бы «имён нет» — это другое утверждение."""
        self.assertIsNone(significant_names(b"def broken(\n"))
        self.assertIsNone(significant_names(None))

    def test_an_unparsable_remote_refuses_to_judge(self):
        verdict = classify_loss(b"X = 1\n", b"X = 1\n", b"def broken(\n")
        self.assertEqual(verdict["status"], UNMEASURED)


# ──────────────────── единица смысла ────────────────────

class WhatCountsAsASignificantName(unittest.TestCase):

    def test_imports_defs_and_module_bindings_count(self):
        names = significant_names(
            b"import alpha\nfrom beta import gamma\n"
            b"REGISTRY = ('a/one.json', 'a/two.json')\n"
            b"MAP = {'k': 1}\n"
            b"def delta():\n    local_thing = 1\n    return local_thing\n")
        for expected in ("alpha", "gamma", "REGISTRY", "MAP", "delta",
                         "a/one.json", "a/two.json", "k"):
            self.assertIn(expected, names)

    def test_locals_do_not_count(self):
        names = significant_names(b"def delta():\n    local_thing = 1\n    return local_thing\n")
        self.assertNotIn("local_thing", names)

    def test_an_import_inside_a_function_still_counts(self):
        """Ступень моста из аварии живёт внутри `main()` — иначе её не опознать."""
        names = significant_names(b"def main():\n    from pkg import subject\n    return subject\n")
        self.assertIn("subject", names)


# ──────────────────── проводка у двери доставки ────────────────────

class TheGuardIsWiredIntoTheDoor(unittest.TestCase):
    """Утверждения СТРУКТУРНЫЕ (разбор AST), а не по подстроке — урок ADR-338/341."""

    def _pusher(self) -> ast.Module:
        return ast.parse((REPO / "push_to_github.py").read_text(encoding="utf-8"))

    def _func(self, name: str):
        for node in ast.walk(self._pusher()):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"в пушере нет функции {name}")

    def test_guard_overwrite_calls_the_name_loss_guard(self):
        calls = [n.func.id for n in ast.walk(self._func("guard_overwrite"))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn("guard_name_loss", calls)

    def test_push_file_passes_the_flag_and_catches_the_refusal(self):
        fn = self._func("push_file")
        self.assertIn("allow_name_loss", {a.arg for a in fn.args.args})
        handlers = [h.type.id for h in ast.walk(fn)
                    if isinstance(h, ast.ExceptHandler) and isinstance(h.type, ast.Name)]
        self.assertIn("NameLossRefused", handlers)

    def test_allow_overwrite_alone_does_not_silence_the_refusal(self):
        """Два РАЗНЫХ согласия: перезаписать remote ≠ потерять невиданное."""
        fn = self._func("guard_name_loss")
        args = {a.arg for a in fn.args.args}
        self.assertIn("allow_name_loss", args)
        self.assertNotIn("allow_overwrite", args)

    def test_the_safe_state_does_not_pay_for_the_network(self):
        """При base == remote потеря невозможна ПО ПОСТРОЕНИЮ; замер не нужен.

        Утверждение СТРУКТУРНОЕ: сравниваются позиции узлов в теле функции, а не
        смещения подстрок в тексте файла. Подстрочная редакция этой проверки
        пережила мутацию «страж переехал перед веткой SAFE» — ровно тот дефект,
        о котором ADR-338.
        """
        body = self._func("guard_overwrite").body
        safe_at = next(i for i, n in enumerate(body)
                       if isinstance(n, ast.If)
                       and any(isinstance(c, ast.Name) and c.id == "DIVERGENCE_SAFE"
                               for c in ast.walk(n.test)))
        call_at = next(i for i, n in enumerate(body)
                       if isinstance(n, ast.Assign)
                       and isinstance(n.value, ast.Call)
                       and isinstance(n.value.func, ast.Name)
                       and n.value.func.id == "guard_name_loss")
        self.assertLess(safe_at, call_at, "страж имён обязан стоять ПОСЛЕ ветки SAFE")


# ──────────────────── поведение стража, а не его форма ────────────────────

class TheGuardActuallyRefuses(unittest.TestCase):
    """Проводку мало объявить — отказ обязан СРАБАТЫВАТЬ.

    Первая редакция этого файла проверяла только сигнатуру, и батарея мутаций
    показала это сразу: снятие `raise` из стража пережило все 21 тест.
    """

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_pusher_c570", REPO / "push_to_github.py")
        self.ptg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ptg)

    def _call(self, repo_path="spa_core/monitoring/findings_bridge.py", **kw):
        """Зов стража с байтами аварии; сеть подменена содержимым remote."""
        from unittest import mock
        with mock.patch.object(self.ptg, "get_file_content",
                               return_value=blob(REMOTE_BLOB)):
            return self.ptg.guard_name_loss(
                "pat", "repo", "main", repo_path,
                blob(BASE_BLOB), blob(LOCAL_BLOB), "deadbeef", **kw)

    def test_it_raises_on_a_name_the_author_never_saw(self):
        with self.assertRaises(self.ptg.NameLossRefused) as ctx:
            self._call()
        self.assertIn("haystack_origin_census", str(ctx.exception))

    def test_the_named_consent_lets_it_through_and_still_prints(self):
        note = self._call(allow_name_loss=True)
        self.assertIn("haystack_origin_census", note)

    def test_a_file_that_is_not_python_is_not_this_guards_business(self):
        """Единица здесь — имена Python. Документы меряют РАЗДЕЛАМИ, и это их дело."""
        self.assertEqual(self._call(repo_path="docs/STATE.md"), "")

    def test_a_file_absent_on_remote_has_nothing_to_lose(self):
        from unittest import mock
        with mock.patch.object(self.ptg, "get_file_content",
                               return_value=blob(REMOTE_BLOB)):
            self.assertEqual(
                self.ptg.guard_name_loss("pat", "repo", "main", "x.py",
                                         blob(BASE_BLOB), blob(LOCAL_BLOB), None), "")

    def test_no_base_is_named_unmeasured_without_paying_for_the_network(self):
        """Без базы прибор ответа не даст — значит и сеть за него платить не должна.

        Замер 12.09: без этой ветки КАЖДЫЙ пуш `.py` из хост-репо (autopush,
        дневной цикл, кастодиан сайта — у всех база неизмерима) делал лишний GET,
        и сторож живых фидов в наборе это назвал.
        """
        from unittest import mock
        with mock.patch.object(self.ptg, "get_file_content") as fetch:
            note = self.ptg.guard_name_loss(
                "pat", "repo", "main", "spa_core/monitoring/findings_bridge.py",
                None, blob(LOCAL_BLOB), "deadbeef")
        fetch.assert_not_called()
        self.assertIn("НЕ ИЗМЕРЕНА", note)
        self.assertIn("не «чисто»", note)

    def test_a_dead_network_is_unmeasured_not_clean(self):
        """Сеть моргнула — это «нечем померить», а не «терять нечего» (инв. #17)."""
        from unittest import mock
        with mock.patch.object(self.ptg, "get_file_content",
                               side_effect=OSError("сеть отвалилась")):
            note = self.ptg.guard_name_loss(
                "pat", "repo", "main", "spa_core/monitoring/findings_bridge.py",
                blob(BASE_BLOB), blob(LOCAL_BLOB), "deadbeef")
        self.assertIn("НЕ ИЗМЕРЕНА", note)
        self.assertIn("не «чисто»", note)

    def test_a_dead_network_does_not_abort_the_delivery(self):
        """Отказ сети НЕ поднимает NameLossRefused: доставку страж не валит."""
        from unittest import mock
        with mock.patch.object(self.ptg, "get_file_content",
                               side_effect=OSError("сеть отвалилась")):
            self.ptg.guard_name_loss(
                "pat", "repo", "main", "spa_core/monitoring/findings_bridge.py",
                blob(BASE_BLOB), blob(LOCAL_BLOB), "deadbeef")

    def test_a_deliberate_deletion_raises_nothing(self):
        """Обратный контроль поведения: автор видел имя — страж пропускает молча."""
        from unittest import mock
        remote = b"import alpha\nX = 1\n"
        with mock.patch.object(self.ptg, "get_file_content", return_value=remote):
            self.assertEqual(
                self.ptg.guard_name_loss("pat", "repo", "main", "x.py",
                                         remote, b"X = 1\n", "deadbeef"), "")


# ──────────────────── восстановленная проводка ADR-343 ────────────────────

class TheWiringLostOnTheTwelfthIsBack(unittest.TestCase):
    """Проводка восстановлена ИЗ ИСТОРИИ; тест сторожит все четыре её места."""

    def setUp(self):
        self.src = (REPO / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
            encoding="utf-8")
        self.tree = ast.parse(self.src)

    def _module_constant(self, name: str):
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node.value
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id == name:
                return node.value
        raise AssertionError(f"в мосте нет константы {name}")

    def test_produces_names_the_artifact(self):
        entries = [e.value for e in self._module_constant("PRODUCES").elts
                   if isinstance(e, ast.Constant)]
        self.assertIn("data/haystack_origin_census.json", entries)

    def test_the_census_stage_runs_it(self):
        entries = [e.value for e in self._module_constant("CENSUS_STAGE").elts
                   if isinstance(e, ast.Constant)]
        self.assertIn("haystack_origin_census", entries)

    def test_the_product_map_knows_its_module_and_artifact(self):
        node = self._module_constant("CENSUS_PRODUCT")
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        self.assertIn("haystack_origin_census", keys)
        value = node.values[keys.index("haystack_origin_census")]
        pairs = {k.value: v.value for k, v in zip(value.keys, value.values)
                 if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)}
        self.assertEqual(pairs["module"], "spa_core/monitoring/haystack_origin_census.py")
        self.assertEqual(pairs["artifact"], "data/haystack_origin_census.json")

    def test_main_actually_calls_the_instrument(self):
        """Запись в реестре — ещё не исполнение: ступень обязана ЗВАТЬ прибор."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                imported = [a.name for n in ast.walk(node)
                            if isinstance(n, ast.ImportFrom) for a in n.names]
                self.assertIn("haystack_origin_census", imported)
                return
        raise AssertionError("в мосте нет main()")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ShellWrappersAreCoveredToo(unittest.TestCase):
    """ADR-351 — расширение стража на оболочку, воспроизведённое по настоящей аварии.

    Страж смотрел ТОЛЬКО на ``.py``, и ровно поэтому пуш `5fb2ab5a` (мой) молча
    откатил правку ADR-347 в `scripts/agent_orchestrator.sh`: имя `STARVE_LIB` было
    на remote и исчезло в пушенной копии. Второй случай класса за сутки и первый —
    в оболочке; питоновский страж, построенный утром против первого, на второй не
    смотрел вовсе.

    Сцены синтетические, но форма — дословно та: правка кладётся поверх копии,
    взятой РАНЬШЕ, и уносит имя, которого автор не видел.
    """

    REMOTE = (
        '#!/bin/bash\n'
        'REPO_ROOT="/x"\n'
        'STARVE_LIB="$REPO_ROOT/scripts/lib/starvation_verdict.sh"\n'
        'STARVE_PY="$REPO_ROOT/scripts/check_owner_order_starvation.py"\n'
        'ts() { date -u; }\n'
    ).encode()
    #: База автора — та же обёртка ДО появления `STARVE_LIB`.
    STALE_BASE = (
        '#!/bin/bash\n'
        'REPO_ROOT="/x"\n'
        'STARVE_PY="$REPO_ROOT/scripts/check_owner_order_starvation.py"\n'
        'ts() { date -u; }\n'
    ).encode()

    def test_a_name_the_author_never_saw_is_a_refusal(self):
        local = self.STALE_BASE + b'MY_STEP="added"\n'
        v = dnl.classify_loss(self.STALE_BASE, local, self.REMOTE,
                              path="scripts/agent_orchestrator.sh")
        self.assertEqual(v["status"], dnl.NEVER_SEEN_BY_AUTHOR)
        self.assertEqual(v[dnl.NEVER_SEEN_BY_AUTHOR], ["STARVE_LIB"])
        self.assertIn("STARVE_LIB", dnl.refusal_text("scripts/agent_orchestrator.sh", v))

    def test_a_name_the_author_did_see_is_named_but_not_a_refusal(self):
        """Обратная сторона: осознанное удаление своего же имени отказом не является."""
        local = self.REMOTE.replace(b'ts() { date -u; }\n', b'')
        v = dnl.classify_loss(self.REMOTE, local, self.REMOTE,
                              path="scripts/agent_orchestrator.sh")
        self.assertEqual(v["status"], dnl.DELETED_BY_AUTHOR)
        self.assertEqual(v[dnl.DELETED_BY_AUTHOR], ["ts"])
        self.assertEqual(dnl.refusal_text("scripts/agent_orchestrator.sh", v), "")

    def test_a_wrapper_that_loses_nothing_is_clean(self):
        local = self.REMOTE + b'EXTRA="ok"\n'
        v = dnl.classify_loss(self.REMOTE, local, self.REMOTE,
                              path="scripts/agent_orchestrator.sh")
        self.assertEqual(v["status"], "clean")

    def test_shell_names_cover_both_assignment_and_function_forms(self):
        names = dnl.significant_names(
            b'A=1\nexport B=2\nc() { :; }\nfunction d { :; }\n# E=nope in a comment is still E\n',
            path="x.sh")
        self.assertLessEqual({"A", "B", "c", "d"}, names)

    def test_undecodable_bytes_are_not_measured_rather_than_empty(self):
        """Инв. #17: «не прочитано» и «имён нет» — разные исходы."""
        self.assertIsNone(dnl.significant_names(b"\xff\xfe\x00binary", path="x.sh"))

    def test_a_python_path_still_uses_the_python_reader(self):
        """Расширение не имеет права поменять смысл прежних вызовов."""
        self.assertEqual(dnl.significant_names(b"def f():\n    pass\n", path="x.py"), {"f"})
        self.assertIsNone(dnl.significant_names(b"def f(:\n", path="x.py"))
