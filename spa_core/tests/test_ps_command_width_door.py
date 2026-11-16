# LLM_FORBIDDEN
# FROZEN-DATE-OK: ps-lstart-material — литерал `Mon Nov 16 12:04:06 2026` в этом файле
# есть ТЕКСТ колонки `lstart` поддельного вывода `ps`, то есть МАТЕРИАЛ разбора, а не
# часы: со стенным временем он не сравнивается ни в одном утверждении (`now()`,
# `time.time()`, `datetime.now()` в файле не зовутся ни разу), и дверь к ОС подменена
# целиком — `ps` и `os.kill` не зовутся. Прежняя причина звалась `injected-clock` и была
# ЛОЖНОЙ по мерке сторожа претензии: инъекция означает «якорь передан ВХОДОМ в вызов», а
# здесь якорь не передаётся никуда — он лежит в строке, которую сцена отдаёт прибору как
# вывод `ps`. Замер цикла #1171: `test_injected_clock_claim` краснел на `main` именно
# этим именем (прогон 43875366133, вне объявленных родов, то есть внутри вилки дефектов).
"""Дверь «ЛИЧНОСТЬ ПРОЦЕССА, прочитанная ТЕКСТОМ колонки `ps`» (ADR-1031).

`.claude/rules/deployment.md` § «ОКНО МУТАЦИОННОГО ПРИБОРА» п. 6 уже запрещает спрашивать
живость процесса грепом по колонкам: такой вопрос отвечает «как сегодня выглядит вывод
`ps`», а не «жив ли процесс». Замер цикла #1170 нашёл ТУ ЖЕ дверь с другой стороны — не в
греп-форме, а в ШИРИНЕ вывода:

* GNU-`ps` (procps-ng, `ubuntu-latest`) обрезает строку по ширине экрана, а без терминала
  берёт 80 колонок;
* улика контрольного прогона **43859165098** (вершина `3c9c4fa90`): владельцем окна
  числился номер 4599, и команда приехала как
  ``/opt/hostedtoolcache/Python/3.11.18/x64/bin/python /tmp`` — вместе с отметкой `lstart`
  это РОВНО 80 символов, то есть путь обрублен посреди каталога;
* `_TOOL_IN_COMMAND` в обрубке прибора не находил, и `owner_liveness` отвечал
  ``unmeasured`` — про ЖИВОГО СВОЕГО ЖЕ ребёнка;
* BSD-`ps` (Мак) не обрезает ни с терминалом, ни без (замер 16.11: 205 символов при
  `COLUMNS=80`), поэтому дома дефект невидим.

Цена двери измерена: **7** тестов двух файлов красны в CI и зелены на Маке, и все семь
были объявлены членами рода «окружение раннера», то есть ВЫЧИТАЛИСЬ из вилки дефектов
контрольного прогона. Объявить их окружением значило бы вычесть живой дефект (ADR-1030).

Контроли ниже — в ОБЕ стороны и на НАСТОЯЩЕМ коде прибора: полная команда ⇒ `alive`,
та же команда, обрезанная ровно так, как её отдаёт GNU-`ps` ⇒ `unmeasured`. Разница
между сценами — РОВНО ширина, ничего больше.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

#: Якорь сцены. Обе отметки ниже вычислены ОТ НЕГО, стенные часы не спрашиваются.
NOW = datetime(2026, 11, 16, 12, 4, 12, tzinfo=timezone.utc)

#: Ширина, которую берёт GNU-`ps` без терминала. Это НЕ наше число: оно измерено у
#: улики прогона 43859165098 — строка пришла длиной ровно 80.
GNU_PS_WIDTH = 80

#: Дословная команда дочернего прибора на раннере, ДО обрезания.
FULL_COMMAND = (
    "/opt/hostedtoolcache/Python/3.11.18/x64/bin/python "
    "/tmp/pytest-of-runner/pytest-0/test_the_probe_is_green0/stand/scripts/"
    "delta_mutation_run.py --spec /tmp/pytest-of-runner/pytest-0/"
    "test_the_probe_is_green0/stand/spec.json --repo-root /tmp/pytest-of-runner/"
    "pytest-0/test_the_probe_is_green0/stand")


def _instrument():
    """НАСТОЯЩИЙ прибор, а не его пересказ: контроль на пересказе ничего не держит."""
    path = _REPO / "scripts" / "delta_mutation_run.py"
    spec = importlib.util.spec_from_file_location("spa_dmr_width_probe", path)
    mod = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    sys.modules["spa_dmr_width_probe"] = mod
    spec.loader.exec_module(mod)                         # type: ignore[union-attr]
    return mod


class TheOwnerVerdictMustNotBeAPropertyOfPsWidth(unittest.TestCase):
    """Один вход — ширина прочитанной команды — и вердикт обязан разойтись."""

    def setUp(self) -> None:
        self.m = _instrument()
        self.opened = NOW
        # Владелец СТАРТОВАЛ не позже открытия окна: иначе прибор справедливо зовёт
        # номер переработанным и до вопроса о команде не доходит вовсе.
        self.started = NOW - timedelta(seconds=6)
        self.record = {"pid": 4599, "run_label": "delta-mutation-4599",
                       "hostname": socket.gethostname(),
                       "opened_at": self.opened.isoformat()}

    def _verdict(self, command: str | None) -> dict:
        def probe(_pid: int) -> dict:
            return {"exists": True, "started_at": self.started,
                    "command": command, "why": None}
        return self.m.owner_liveness(self.record, probe=probe, caller_pid=os.getpid())

    # ── предпосылка сцены: обрезание обязано ОТРЕЗАТЬ имя прибора ─────────────

    def test_the_scene_actually_truncates_the_tool_name_away(self) -> None:
        """Без этого контроля сцена была бы верна по построению и ничего не доказывала."""
        stamp = self.started.strftime("%a %b %d %H:%M:%S %Y")
        cut = (stamp + " " + FULL_COMMAND)[:GNU_PS_WIDTH]
        _, truncated = self.m._parse_ps_line(cut)
        self.assertIn("delta_mutation_run.py", FULL_COMMAND,
                      "полная команда обязана называть прибор — иначе сцена не про то")
        self.assertNotIn(
            "delta_mutation_run.py", truncated or "",
            "обрезанная команда ВСЁ ЕЩЁ называет прибор: сцена не воспроизводит улику "
            f"прогона 43859165098, в которой осталось лишь {GNU_PS_WIDTH} символов")

    # ── собственно расхождение вердикта от ОДНОГО входа ───────────────────────

    def test_a_full_command_reads_the_live_owner_as_alive(self) -> None:
        got = self._verdict(FULL_COMMAND)
        self.assertEqual(got["verdict"], self.m.OWNER_ALIVE, got["detail"])

    def test_a_command_truncated_to_the_gnu_ps_width_loses_the_owner(self) -> None:
        """Положительный контроль НАСТОЯЩЕЙ аварии: вердикт о ЖИВОМ своём ребёнке.

        `unmeasured` сам по себе верен (fail-CLOSED, инв. #17) — неверно, что прибор
        доходит до него, имея на руках всё нужное: это он сам усёк свой же вопрос.
        """
        stamp = self.started.strftime("%a %b %d %H:%M:%S %Y")
        cut = (stamp + " " + FULL_COMMAND)[:GNU_PS_WIDTH]
        _, truncated = self.m._parse_ps_line(cut)
        got = self._verdict(truncated)
        self.assertEqual(got["verdict"], self.m.OWNER_UNMEASURED, got["detail"])
        self.assertIn("в его команде не назван", got["detail"])

    def test_the_two_scenes_differ_in_width_and_nothing_else(self) -> None:
        """Обратная сторона: если бы сцены отличались ещё чем-то, расхождение было бы
        о другом. Обе получают ОДИН `started_at`, ОДНУ запись и один номер."""
        stamp = self.started.strftime("%a %b %d %H:%M:%S %Y")
        cut = (stamp + " " + FULL_COMMAND)[:GNU_PS_WIDTH]
        _, truncated = self.m._parse_ps_line(cut)
        self.assertTrue(FULL_COMMAND.startswith(truncated or "@"),
                        "обрезанная команда обязана быть ПРЕФИКСОМ полной — иначе это "
                        "другая строка, а не та же при другой ширине")
        self.assertNotEqual(self._verdict(FULL_COMMAND)["verdict"],
                            self._verdict(truncated)["verdict"])


class TheInstrumentAsksPsWithoutATruncatingWidth(unittest.TestCase):
    """Шов: прибор обязан СПРАШИВАТЬ широко, а не надеяться на ширину хоста."""

    def test_the_ps_call_disables_width_truncation(self) -> None:
        """Меряется ИСХОД зова, а не слово в исходнике: подменяем единственную дверь к
        ОС (`subprocess.run` внутри модуля прибора) и смотрим НА ARGV, которое уехало."""
        m = _instrument()
        seen: list[list[str]] = []

        class _Done:
            returncode = 0
            stdout = "Mon Nov 16 12:04:06 2026 python /x/delta_mutation_run.py --spec s"
            stderr = ""

        def fake_run(argv, **kwargs):
            seen.append(list(argv))
            return _Done()

        real_run, real_kill = m.subprocess.run, m.os.kill
        m.subprocess.run = fake_run
        m.os.kill = lambda *_a, **_k: None
        try:
            m._process_probe(4599)
        finally:
            m.subprocess.run, m.os.kill = real_run, real_kill

        self.assertEqual(len(seen), 1, f"прибор позвал `ps` {len(seen)} раз(а): {seen}")
        argv = seen[0]
        self.assertEqual(argv[0], "ps", argv)
        self.assertTrue(
            any(a in ("-ww", "-www") or (a.startswith("-w") and a.count("w") >= 2)
                for a in argv),
            "зов `ps` не отключает обрезание по ширине (нет `-ww`): на GNU-`ps` команда "
            f"приедет обрезанной до {GNU_PS_WIDTH} колонок, и личность владельца окна "
            f"станет свойством ширины вывода, а не процесса. argv: {argv}")

    def test_the_widened_call_still_answers_on_this_host(self) -> None:
        """Обратная сторона шва: `-ww` обязан быть ПРИНЯТ живым `ps`, а не отвергнут.

        Флаг, которого платформа не знает, превратил бы починку в «личность НЕ ИЗМЕРЕНА»
        на каждом вопросе — отказ тише красного теста и потому опаснее.
        """
        m = _instrument()
        seen = m._process_probe(os.getpid())
        self.assertTrue(seen.get("exists"), seen)
        self.assertIsNotNone(
            seen.get("command"),
            f"живой `ps` не отдал команду СВОЕГО процесса: {seen.get('why')!r}")
        self.assertIsInstance(
            seen.get("started_at"), datetime,
            f"живой `ps` не отдал дату старта своего процесса: {seen.get('why')!r}")


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
