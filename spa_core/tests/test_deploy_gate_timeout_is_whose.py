# LLM_FORBIDDEN
"""`scripts/check_agent_before_deploy.sh`: «снято МОИМ сроком» ≠ «агент завис» (ADR-1061).

ЗАМЕР, ВОСПРОИЗВЕДЁННЫЙ ЗДЕСЬ (2026-11-19, цикл #1203). Гейт перед деплоем судил
прогон агента СВОИМ сроком (`RUN_TIMEOUT`, умолчание 180с) и при его истечении
печатал `FAIL … was killed (hang)`. Для `com.spa.decision_loop` это было неверно в
ОПАСНУЮ сторону:

| ось | число |
|---|---|
| собственный бюджет агента (`StartInterval` в его плисте) | **21600 с** |
| последний ЗАВЕРШЁННЫЙ прогон его программы | **8937.8 с** (`data/findings_bridge_report.json`, 29.10: `run_started_at` 07:49:13Z → `generated_at` 10:18:11Z, ступень переписей пройдена ЦЕЛИКОМ, `skipped` пусто) |
| срок, которым гейт его судил | **180 с** (умолчание) и **7800 с** (как его звали 03.11) |

То есть гейт снимал прогон задолго до его конца и объявлял «зависание» о программе,
которая провабельно укладывается в собственный бюджет с запасом в 2.4 раза. Цена:
служба осталась ВЫКЛЮЧЕННОЙ, мост находок 497 ч стоял БЕЗ ПИСАТЕЛЯ, и CRITICAL шага
0-офис не доставались никому.

КАЖДЫЙ тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на НАСТОЯЩЕМ приборе, и контроли идут в
ОБЕ стороны, иначе утверждение «теперь не hang» проходило бы вакуумно:

* срок гейта НИЖЕ бюджета агента ⇒ **НЕ ИЗМЕРЕНО** (код 2), оба числа названы,
  слова «hang» нет — на непочиненном гейте здесь был код 1 и «hang»;
* срок гейта НЕ НИЖЕ бюджета ⇒ **прежний FAIL «hang»** (код 1) с обоими числами:
  сужение строгое, а не отмена проверки;
* бюджет НЕ ОБЪЯВЛЕН (календарное расписание) ⇒ **прежний FAIL «hang»**: опровержения
  нет, и вердикт остального флота не тронут;
* у самой двери различимы ПЯТЬ исходов, и «плиста нет» не выдаётся за ответ.

Гейт здесь НИЧЕГО НЕ ЗАГРУЖАЕТ: `CHECK_ONLY=1` + `SPA_GATE_REPO_ROOT` (одноразовое
дерево), как у соседей `test_deploy_gate_long_lived.py` / `test_deploy_gate_exit78.py`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "check_agent_before_deploy.sh"
_PROBE = _REPO / "scripts" / "agent_static_probe.sh"

#: Плист БЕЗ `KeepAlive`-true и С интервалом — обычный run-once агент, то есть
#: ровно тот путь, на котором живёт предмет. `{budget}` — его СОБСТВЕННЫЙ бюджет.
_INTERVAL_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.{name}</string>
  <key>KeepAlive</key><false/>
  <key>StartInterval</key><integer>{budget}</integer>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>{wrapper}</string>
  </array>
  <key>StandardOutPath</key><string>{out}</string>
  <key>StandardErrorPath</key><string>{err}</string>
</dict></plist>
"""

#: Календарное расписание: бюджета в СЕКУНДАХ агент не объявляет вовсе. Вердикт о
#: нём обязан остаться ПРЕЖНИМ — опровергнуть зависание нечем.
_CALENDAR_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.{name}</string>
  <key>KeepAlive</key><false/>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer></dict>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>{wrapper}</string>
  </array>
  <key>StandardOutPath</key><string>{out}</string>
  <key>StandardErrorPath</key><string>{err}</string>
</dict></plist>
"""

#: Обёртка, которая НЕ успевает к сроку гейта — предмет сцены. Спит заметно дольше
#: любого `RUN_TIMEOUT`, который даёт тест, и ничего не делает: предмет здесь не её
#: работа, а то, КАК гейт назовёт её снятие.
_SLOW_WRAPPER = "#!/bin/bash\nsleep 25\n"


def _run_gate(root: Path, name: str, run_timeout: int) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "CHECK_ONLY": "1",                 # НИЧЕГО не загружает
        "SPA_GATE_REPO_ROOT": str(root),
        "SPA_PROBE_PYTHON": sys.executable,
        "RUN_TIMEOUT": str(run_timeout),
        "KICKSTART_TIMEOUT": "5",
    })
    return subprocess.run(["/bin/bash", str(_GATE), name],
                          capture_output=True, text=True, env=env,
                          timeout=180, cwd=str(root))


class _Scene:
    """Одноразовое дерево с одним агентом (боевое дерево не трогается никогда)."""

    def __init__(self, tmp: str, name: str, template: str, budget: int | None):
        self.root = Path(tmp)
        self.name = name
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        self.wrapper = self.root / "scripts" / f"agent_{name}.sh"
        self.wrapper.write_text(_SLOW_WRAPPER, encoding="utf-8")
        self.wrapper.chmod(0o755)
        self.plist = self.root / "scripts" / f"com.spa.{name}.plist"
        fields = dict(name=name, wrapper=str(self.wrapper),
                      out=str(self.root / "logs" / f"{name}.out"),
                      err=str(self.root / "logs" / f"{name}.err"))
        if budget is not None:
            fields["budget"] = budget
        self.plist.write_text(template.format(**fields), encoding="utf-8")


class TheGateNamesWhoseDeadlineCutTheRun(unittest.TestCase):
    """Три сцены на НАСТОЯЩЕМ гейте, и вердикты ПРОТИВОПОЛОЖНЫЕ."""

    def test_gate_limit_below_the_agents_own_budget_is_UNMEASURED_not_a_hang(self):
        with tempfile.TemporaryDirectory() as tmp:
            sc = _Scene(tmp, "slowagent", _INTERVAL_PLIST, budget=3600)
            cp = _run_gate(sc.root, sc.name, run_timeout=3)
        out = cp.stdout + cp.stderr
        self.assertEqual(cp.returncode, 2, f"ожидался третий исход (код 2):\n{out}")
        self.assertIn("UNMEASURED", out, out)
        # Оба числа НАЗВАНЫ — иначе читатель не узнает, чей срок сработал.
        self.assertIn("3600", out, out)
        self.assertRegex(out, r"\b3с\b|\b3 с\b|гейта 3", out)
        # Слово, которое было неверным: его здесь быть НЕ ДОЛЖНО.
        self.assertNotIn("(hang", out, f"гейт всё ещё называет это зависанием:\n{out}")
        self.assertNotIn("NOT loading", cp.stdout, "вердикт обязан идти в stderr")

    def test_gate_limit_at_or_above_the_budget_stays_a_hang(self):
        """Обратная половина: сужение строгое, проверка НЕ отменена."""
        with tempfile.TemporaryDirectory() as tmp:
            sc = _Scene(tmp, "slowagent", _INTERVAL_PLIST, budget=2)
            cp = _run_gate(sc.root, sc.name, run_timeout=5)
        out = cp.stdout + cp.stderr
        self.assertEqual(cp.returncode, 1, f"ожидался прежний FAIL:\n{out}")
        self.assertIn("hang", out, out)
        self.assertNotIn("UNMEASURED", out, out)
        self.assertIn("2", out, out)

    def test_an_agent_that_declares_no_budget_keeps_the_old_verdict(self):
        """Календарный агент бюджета в секундах не объявляет ⇒ вердикт ПРЕЖНИЙ."""
        with tempfile.TemporaryDirectory() as tmp:
            sc = _Scene(tmp, "calagent", _CALENDAR_PLIST, budget=None)
            cp = _run_gate(sc.root, sc.name, run_timeout=3)
        out = cp.stdout + cp.stderr
        self.assertEqual(cp.returncode, 1, f"ожидался прежний FAIL:\n{out}")
        self.assertIn("hang", out, out)
        self.assertNotIn("UNMEASURED", out, out)
        self.assertIn("НЕ ОБЪЯВЛЕН", out, out)


class TheVerdictDoorDistinguishesEveryOutcome(unittest.TestCase):
    """Дверь зовётся как ПРИБОР, а не пересказывается: пять исходов, пять ответов."""

    def _ask(self, limit: str, plist: Path) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/bash", str(_PROBE), "--timeout-verdict",
                               limit, str(plist)],
                              capture_output=True, text=True, timeout=60)

    def _plist(self, tmp: str, body: str) -> Path:
        p = Path(tmp) / "x.plist"
        p.write_text(body, encoding="utf-8")
        return p

    def test_five_outcomes_are_distinguishable(self):
        with tempfile.TemporaryDirectory() as tmp:
            interval = self._plist(tmp, _INTERVAL_PLIST.format(
                name="t", budget=21600, wrapper="/bin/true",
                out="/tmp/a", err="/tmp/b"))
            cal = Path(tmp) / "cal.plist"
            cal.write_text(_CALENDAR_PLIST.format(
                name="t", wrapper="/bin/true", out="/tmp/a", err="/tmp/b"),
                encoding="utf-8")

            cp = self._ask("180", interval)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertTrue(cp.stdout.startswith("unmeasured\t"), cp.stdout)
            self.assertIn("21600", cp.stdout)

            cp = self._ask("21600", interval)
            self.assertTrue(cp.stdout.startswith("hang\t"), cp.stdout)

            cp = self._ask("99999", interval)
            self.assertTrue(cp.stdout.startswith("hang\t"), cp.stdout)

            cp = self._ask("180", cal)
            self.assertTrue(cp.stdout.startswith("hang\t"), cp.stdout)
            self.assertIn("НЕ ОБЪЯВЛЕН", cp.stdout)

            # Мусор в сроке гейта НЕ покупает «не измерено»: иначе сторожа можно
            # было бы погасить переменной окружения.
            cp = self._ask("abc", interval)
            self.assertTrue(cp.stdout.startswith("hang\t"), cp.stdout)

            # Плиста нет ⇒ бюджет НЕ ПРОЧИТАН. Ни одной строки вердикта, код 2:
            # пустота не имеет права совпасть с ответом.
            cp = self._ask("180", Path(tmp) / "missing.plist")
            self.assertEqual(cp.returncode, 2, cp.stdout)
            self.assertNotIn("hang", cp.stdout)
            self.assertNotIn("unmeasured", cp.stdout)

    def test_plist_int_never_reports_an_absent_key_as_zero(self):
        """Отсутствие числа — НЕ ноль (инв. #17): ноль сделал бы зависанием всё."""
        with tempfile.TemporaryDirectory() as tmp:
            cal = Path(tmp) / "cal.plist"
            cal.write_text(_CALENDAR_PLIST.format(
                name="t", wrapper="/bin/true", out="/tmp/a", err="/tmp/b"),
                encoding="utf-8")
            cp = subprocess.run(["/bin/bash", str(_PROBE), "--plist-int",
                                 "StartInterval", str(cal)],
                                capture_output=True, text=True, timeout=60)
            self.assertEqual(cp.stdout.strip(), "", cp.stdout)
            self.assertNotEqual(cp.stdout.strip(), "0")


class TheComparisonHasExactlyOneCopy(unittest.TestCase):
    """Своей копии правила «чей это срок» у гейта быть не должно.

    Разойдись две копии — гейт пускал бы через себя ровно те прогоны, из-за
    которых правило и понадобилось (тот же довод, что у `read_delivery_bytes`
    и `board_status_map`).
    """

    def test_the_gate_does_not_parse_StartInterval_itself(self):
        lines = _GATE.read_text(encoding="utf-8").splitlines()
        offenders = [
            (i + 1, ln) for i, ln in enumerate(lines)
            if "StartInterval" in ln and not ln.lstrip().startswith("#")
        ]
        self.assertEqual(offenders, [],
                         f"гейт читает бюджет сам, мимо двери: {offenders}")

    def test_the_gate_asks_the_door_exactly_once(self):
        # Считаются ЗОВЫ, а не вхождения подстроки: имя двери названо и в
        # комментарии рядом, и считать его зовом значило бы мерить прозу.
        calls = [ln for ln in _GATE.read_text(encoding="utf-8").splitlines()
                 if "--timeout-verdict" in ln and not ln.lstrip().startswith("#")]
        self.assertEqual(len(calls), 1,
                         f"дверь зовётся не один раз — копии разойдутся: {calls}")

    def test_the_third_outcome_has_its_own_exit_code(self):
        text = _GATE.read_text(encoding="utf-8")
        # `re.M`: предмет — ОТДЕЛЬНАЯ строка определения, а без флага `^`
        # привязался бы к началу файла и проверка проходила бы вакуумно.
        self.assertTrue(re.search(r"^unmeasured\(\)\s*\{.*exit 2", text, re.M),
                        "у третьего исхода нет своего кода возврата")


if __name__ == "__main__":
    unittest.main()
