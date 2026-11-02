"""S5 (E8.2/E8.3/E8.5) — три сквозных сценария на БЕЗОПАСНОМ стенде через настоящие интерфейсы S1/S2.

Каждый сценарий: цель → план исполнителя (контракт ролей) → проверка плана → попытка исполнить БЕЗ допуска
(обязан отказать) → допуск роли ``agent`` от ``operator-test`` (НЕ владелец) → исполнитель отдельным процессом →
SIGKILL на границе ``applied`` → холодное продолжение НОВЫМ процессом только из файлов прогона → машинный исход →
шаг своей роли (регрессия / эксперимент) → итог словами для владельца. Меряется: время до результата, вызовы
модели, вмешательства владельца, отказы, повторные эффекты, остатки процессов.

Сценарии (выбраны и записаны ДО прогона, E8.2):
  A — продуктовая задача: на стенде копия текста DeFi Checkup без объяснения риска «заблокированный вывод»;
      цель — добавить объяснение; проверка — текст в файле.
  B — дефект: функция ``apy_to_decimal`` принимает проценты как доли (5 → 500 %); тест-свидетель воспроизводит
      ошибку ДО; исполнитель пишет исправление; роль проверки гоняет регрессию ПОСЛЕ.
  C — paper-исследование: исполнитель пишет предрегистрацию (гипотеза, контроль, бюджет 1 попытка, критерий);
      её хеш фиксируется ДО эксперимента; детерминированный эксперимент на синтетическом ряду против HOLD;
      результат и объяснение сохраняются рядом.

Провайдер — ``fixture_test_adapter`` (ТЕСТОВЫЙ: ответы плана заданы сценарием). Результаты подписаны
``synthetic: true``; реальный провайдер здесь не вызывается (квота подписки — отдельное решение), и это
не выдаётся за живую автономию. Рабочие данные и процессы не трогаются: всё — в новом каталоге ``--base``.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.studio_os import executor as ex
from spa_core.studio_os import goal_graph as gg
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.tests import _child_pytest as _cp

REPO = Path(__file__).resolve().parents[2]
TTL_S = 3


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def _policy(run):
    p = Path(run) / "admission_policy.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    # порог диска не предмет сцены (тот же довод, что у S2: исход не должен зависеть от диска раннера)
    p.write_text(json.dumps({"registry_dir": str(Path(run) / "leases"), "min_free_disk_gb": 0}))
    return p


def _spawn(run, stand, gv, worker, stop_at=None):
    cmd = [sys.executable, "-m", "spa_core.studio_os.executor", "run", "--run-dir", str(run), "--stand", str(stand),
           "--graph-version", gv, "--worker", worker, "--ttl-s", str(TTL_S), "--admission-policy", str(_policy(run))]
    if stop_at:
        cmd += ["--stop-at", stop_at]
    return subprocess.Popen(cmd, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)


def _plan(tasks):
    return json.dumps({"tasks": tasks}, ensure_ascii=False)


CHECKUP = "docs/checkup_risks.md"
RISK_TEXT = "Заблокированный вывод: протокол может временно запретить вывод средств"
BUG = "lib/apy.py"
PREREG = "research/prereg.json"
RESULT = "research/result.json"

SCENARIOS = {
    "A_product": {
        "files": {CHECKUP: "# Риски DeFi Checkup\n\n- Смарт-контракт: ошибка в коде протокола.\n"},
        "goal": "Добавь в объяснение рисков DeFi Checkup пункт о заблокированном выводе средств.",
        "outcome": f"в {CHECKUP} есть объяснение риска заблокированного вывода",
        "scope": ["docs/"],
        "plan": _plan([{"id": "risk_text", "outcome": "пункт о заблокированном выводе добавлен",
                        "operations": [{"op": "write_file", "path": CHECKUP, "content":
                                        "# Риски DeFi Checkup\n\n- Смарт-контракт: ошибка в коде протокола.\n"
                                        f"- {RISK_TEXT} (пауза, очередь на вывод, нехватка ликвидности).\n"}],
                        "check": {"kind": "file_contains", "path": CHECKUP, "text": RISK_TEXT},
                        "depends_on": []}]),
    },
    "B_defect": {
        "files": {BUG: "def apy_to_decimal(apy_pct):\n    return apy_pct  # ДЕФЕКТ: проценты отдаются как доля\n",
                  "lib/test_apy.py": ("import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
                                      "from apy import apy_to_decimal\n\n\ndef test_percent_is_converted():\n"
                                      "    assert abs(apy_to_decimal(5.0) - 0.05) < 1e-12\n")},
        "goal": "Исправь apy_to_decimal: 5 (процентов) должно давать 0.05, а не 5.",
        "outcome": "регрессионный тест lib/test_apy.py проходит",
        "scope": ["lib/"],
        "plan": _plan([{"id": "fix", "outcome": "проценты делятся на 100",
                        "operations": [{"op": "write_file", "path": BUG, "content":
                                        "def apy_to_decimal(apy_pct):\n    return apy_pct / 100.0\n"}],
                        "check": {"kind": "file_contains", "path": BUG, "text": "apy_pct / 100.0"},
                        "depends_on": []}]),
    },
    "C_research": {
        "files": {"research/README.md": "Стенд paper-исследования S5.\n"},
        "goal": "Предрегистрируй проверку: правило «выше 20-дневной средней» лучше HOLD после издержек.",
        "outcome": f"в {PREREG} есть гипотеза, контроль, бюджет попыток и критерий успеха",
        "scope": ["research/"],
        "plan": _plan([{"id": "prereg", "outcome": "предрегистрация записана",
                        "operations": [{"op": "write_file", "path": PREREG, "content": json.dumps({
                            "hypothesis": "SMA20 long/flat лучше HOLD после издержек 15 bps/сторона",
                            "control": "HOLD", "configs": ["sma20"], "attempt_budget": 1,
                            "success": "excess_after_costs > 0 на всём ряду", "data": "synthetic_walk_seed_5"},
                            ensure_ascii=False)}],
                        "check": {"kind": "file_contains", "path": PREREG, "text": "attempt_budget"},
                        "depends_on": []}]),
    },
}


def _role_step(name, stand):
    """Шаг своей роли ПОСЛЕ машинного исхода (не исполнитель): регрессия / эксперимент."""
    if name == "B_defect":
        r = subprocess.run(_cp.child_pytest_argv(stand / "lib" / "test_apy.py", "-q", "-p", "no:cacheprovider"),
                           cwd=str(stand), capture_output=True, text=True, timeout=120)
        return {"role": "reviewer", "regression_rc": r.returncode, "summary": (r.stdout.strip().splitlines() or [""])[-1]}
    if name == "C_research":
        prereg = (stand / PREREG).read_bytes()
        import random
        rnd = random.Random(5)
        px = [100.0]
        for _ in range(500):
            px.append(px[-1] * (1 + rnd.gauss(0.0002, 0.02)))
        eq, pos, cost = 1.0, 0, 0.0015
        for t in range(20, len(px) - 1):
            sma = sum(px[t - 20:t]) / 20
            want = 1 if px[t] > sma else 0
            if want != pos:
                eq *= (1 - cost)
                pos = want
            if pos:
                eq *= px[t + 1] / px[t]
        hold = px[-1] / px[20] * (1 - cost)
        res = {"prereg_sha256": hashlib.sha256(prereg).hexdigest(), "attempts_used": 1,
               "strategy_net": round(eq - 1, 4), "hold_net": round(hold - 1, 4),
               "excess_after_costs": round(eq - hold, 4), "synthetic": True}
        res["verdict"] = "гипотеза подтверждена" if res["excess_after_costs"] > 0 else "гипотеза НЕ подтверждена"
        (stand / RESULT).write_text(json.dumps(res, ensure_ascii=False, indent=1))
        return {"role": "researcher", **res}
    return {"role": "none"}


def _owner_text(name, rec):
    if name == "A_product":
        return "Пункт о заблокированном выводе добавлен в объяснение рисков (стенд, не опубликовано)."
    if name == "B_defect":
        return ("Исправлена конвертация APY: тест падал до исправления и проходит после."
                if rec["role"].get("regression_rc") == 0 else "Исправление не прошло регрессию.")
    return (f"Исследование проведено по предрегистрации (1 попытка из 1): {rec['role'].get('verdict')}; "
            f"разница с HOLD после издержек {rec['role'].get('excess_after_costs')}. Данные синтетические.")


def run_one(base: Path, name: str) -> dict:
    sc = SCENARIOS[name]
    t0 = time.time()
    rec = {"scenario": name, "synthetic": True, "provider_id": "fixture_test_adapter", "steps": []}
    stand, run_dir = base / name / "stand", base / name / "run"
    stand.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], stand)
    _git(["config", "user.email", "s5@stand"], stand)
    _git(["config", "user.name", "s5"], stand)
    for rel, text in sc["files"].items():
        (stand / rel).parent.mkdir(parents=True, exist_ok=True)
        (stand / rel).write_text(text, encoding="utf-8")
    (stand / ".git" / "info" / "exclude").write_text(".studio_stand\n")
    _git(["add", "-A"], stand)
    _git(["commit", "-q", "-m", "base"], stand)
    (stand / ".studio_stand").write_text("")
    if name == "B_defect":                                    # дефект подтверждён ДО исправления
        r = subprocess.run(_cp.child_pytest_argv(stand / "lib" / "test_apy.py", "-q", "-p", "no:cacheprovider"),
                           cwd=str(stand), capture_output=True, text=True, timeout=120)
        rec["defect_reproduced"] = r.returncode != 0
    now0 = datetime.now(timezone.utc)
    goal = gg.goal_record(sc["goal"], source="s5-stand", transport_id=f"s5-{name}", owner="operator-test",
                          outcome=sc["outcome"], at=_iso(now0))
    prop = ex.propose(goal, run_dir=run_dir, scope=sc["scope"], context="стенд S5", provider_id="fixture_test_adapter",
                      adapters={"fixture": ad.fixture({"*": sc["plan"]})}, worker="executor-1", now=_iso(now0),
                      ttl_s=900)
    graph = prop["graph"]
    tid = graph["order"][0]
    rec["steps"].append({"step": "plan", "graph_version": graph["version"], "tasks": list(graph["tasks"])})
    # отказ без допуска: исполнитель не вправе выдать допуск себе сам
    p0 = _spawn(run_dir, stand, graph["version"], "executor-1")
    o0, e0 = p0.communicate(timeout=60)
    state0 = gg.task_state(run_dir, graph["version"], tid)
    why0 = (o0.decode() + e0.decode())[-400:]
    # отказ засчитывается, только если он ПРО ДОПУСК: отказ по чужой причине (admission, диск) — не то свойство
    rec["unapproved"] = {"rc": p0.returncode, "state": state0, "why": why0,
                         "refused": state0 == "new" and '"await_approval"' in why0}
    time.sleep(TTL_S + 0.3)                                   # захват отказавшего процесса истекает
    appr = gg.approve_task(graph, tid, approver="operator-test", role="agent", at=_iso(now0),
                           expires_at=_iso(now0 + timedelta(hours=2)))
    (run_dir / f"approval-{tid}.json").write_text(json.dumps(appr))
    # исполнение → SIGKILL на границе applied
    p1 = _spawn(run_dir, stand, graph["version"], "executor-1", stop_at="applied")
    end = time.time() + 60
    while time.time() < end and not list(run_dir.glob("at_applied-*")) and p1.poll() is None:
        time.sleep(0.05)
    try:
        os.killpg(p1.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    p1.wait(timeout=10)
    p1.communicate()
    rec["killed_at"] = gg.task_state(run_dir, graph["version"], tid)
    # холодное продолжение: новый процесс, только файлы прогона
    time.sleep(TTL_S + 0.3)
    p2 = _spawn(run_dir, stand, graph["version"], "executor-2")
    o2, e2 = p2.communicate(timeout=120)
    rows = gg._journal(run_dir)
    states = [r["state"] for r in rows if r.get("graph_version") == graph["version"] and "state" in r]
    rec["resume"] = {"rc": p2.returncode, "states": states, "done": gg.done_tasks(run_dir, graph["version"]) == [tid],
                     "out": (o2.decode() if p2.returncode == 0 else e2.decode())[-240:]}
    rec["no_double_effect"] = (states.count("applied") == 1
                               and sum(1 for x in states if str(x).startswith("checked:")) == 1)
    rec["model_calls"] = len([r for r in rows if r.get("phase") == "call_started"])
    rec["model_calls_limit"] = ex.MAX_CALLS
    rec["role"] = _role_step(name, stand) if rec["resume"]["done"] else {"role": "skipped"}
    rec["owner_interventions"] = 0           # допуск выдан тестовой ролью agent; владелец не вызывался
    rec["time_to_result_s"] = round(time.time() - t0, 2)
    rec["owner_text"] = _owner_text(name, rec)
    ok = (rec["unapproved"]["refused"] and rec["resume"]["done"] and rec["no_double_effect"]
          and rec["model_calls"] <= ex.MAX_CALLS
          and (name != "B_defect" or (rec.get("defect_reproduced") and rec["role"].get("regression_rc") == 0))
          and (name != "C_research" or rec["role"].get("prereg_sha256")))
    rec["verdict"] = "OK" if ok else "FAILED"
    return rec


def run(base: Path) -> dict:
    base = Path(base).resolve()
    out = {"scenarios": {n: run_one(base, n) for n in SCENARIOS}, "synthetic": True,
           "note": "стенд + тестовый провайдер; живые критерии E8.4 (наблюдение канарейки) — отдельно"}
    out["verdict"] = "OK" if all(s["verdict"] == "OK" for s in out["scenarios"].values()) else "FAILED"
    (base / "s5_record.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out


if __name__ == "__main__":
    import argparse
    a = argparse.ArgumentParser()
    a.add_argument("--base", required=True)
    ns = a.parse_args()
    if Path(ns.base).exists():
        sys.exit("--base уже существует — сцена пишет только в новый каталог")
    r = run(Path(ns.base))
    print(json.dumps({n: {k: s[k] for k in ("verdict", "time_to_result_s", "model_calls", "no_double_effect")}
                      for n, s in r["scenarios"].items()}, ensure_ascii=False, indent=1))
    sys.exit(0 if r["verdict"] == "OK" else 1)
