"""Кого действительно ЗОВЁТ исполняемый шаг GitHub Actions — по форме вызова, а не по имени.

# LLM_FORBIDDEN

Решение ARB 23.10 (STUDIO-OS-NEXT-01, этап 8): исполняемый вызов модуля в workflow
— проводка для `test_unwired_guard_modules_ratchet`. Предмет — ВЫЗОВ, поэтому имя
модуля в YAML само по себе не доказывает ничего:

- читается только `run:` шага (не `name:`, не `description` входа, не `uses:`/`with:`,
  не комментарий YAML — его выбрасывает разбор);
- внутри `run:` засчитывается только простая команда, чьё командное слово —
  интерпретатор Python, с `-m <точный.путь.модуля>` или `<точный/путь/модуля.py>`:
  `echo python -m x`, путь к тесту, `pytest`, похожее имя (`x_v2`) — не вызов;
- шаг или джоба с `if:`, равным литеральной лжи (`false`, `${{ false }}`, `0`, `''`),
  — отключены; workflow без триггера — не исполняется;
- непонятное НЕ засчитывается и НЕ замалчивается: `python -c`, тело heredoc, чужая
  оболочка (`shell: pwsh`), незакрытая кавычка, нечитаемый YAML — попадают в
  `unclear` с причиной. Ошибка идёт в сторону «меньше вызовов» ⇒ больше сирот —
  fail-CLOSED, как у остального детектора.

Условный шаг (`if: always()`, `if: github.event_name == 'push'`) — исполняемый:
условие говорит, КОГДА он идёт, а не что он выключен.

Только stdlib + `yaml` (тест-домен, как в `test_prescribed_run_matches_ci.py`).
"""
from __future__ import annotations

import pathlib
import re
import shlex
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

_WORKFLOW_DIR = pathlib.Path(".github") / "workflows"

_PY_WORD = re.compile(r"^python(?:3(?:\.\d+)?)?$")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1")
#: Операторы, делящие строку на простые команды.
_SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", ";;", "!"}
#: Обёртки, после которых командным словом становится следующее слово.
_PREFIX_WORDS = {"env", "time", "exec", "nohup", "command"}
#: Опции интерпретатора, у которых есть отдельный аргумент.
_PY_OPTS_WITH_ARG = {"-X", "-W", "-Q"}
_FALSE_LITERALS = {"false", "0", ""}


class Call(NamedTuple):
    workflow: str
    job: str
    step: str
    kind: str      # "module" | "script"
    target: str    # точный dotted-путь или путь к .py
    conditional: bool


class Unclear(NamedTuple):
    workflow: str
    job: str
    step: str
    reason: str
    text: str


def _is_false_literal(cond) -> bool:
    if cond is False or cond == 0:
        return True
    if not isinstance(cond, str):
        return False
    s = cond.strip()
    m = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", s, re.S)
    if m:
        s = m.group(1).strip()
    return s.lower() in _FALSE_LITERALS


def _shell_ok(*shells) -> Tuple[bool, Optional[str]]:
    for sh in shells:
        if sh is None:
            continue
        word = str(sh).split()[0] if str(sh).split() else ""
        return (word in ("bash", "sh"), str(sh))
    return True, None


def _lines_without_heredocs(script: str) -> Tuple[List[str], List[str]]:
    """Логические строки скрипта (продолжения `\\` склеены) и выброшенные тела heredoc."""
    joined = re.sub(r"\\\r?\n", " ", script)
    out: List[str] = []
    dropped: List[str] = []
    delim: Optional[str] = None
    for line in joined.splitlines():
        if delim is not None:
            if line.strip() == delim:
                delim = None
            else:
                dropped.append(line)
            continue
        out.append(line)
        m = _HEREDOC.search(line.replace("<<<", "   "))
        if m:
            delim = m.group(2)
    return out, dropped


def _simple_commands(line: str) -> List[List[str]]:
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    tokens = list(lex)   # ValueError на незакрытой кавычке — ловит вызывающий
    cmds: List[List[str]] = [[]]
    for tok in tokens:
        if tok in _SEPARATORS or set(tok) <= set(";&|()"):
            cmds.append([])
        else:
            cmds[-1].append(tok)
    return [c for c in cmds if c]


def _logical_commands(lines: List[str], unclear: List["Unclear"], where: Tuple[str, str, str]):
    """Простые команды по логическим строкам; строка с незакрытой кавычкой копится со
    следующими (многострочный аргумент `python -c "..."`). Не закрылась до конца — неясно."""
    buf: Optional[str] = None
    for line in lines:
        buf = line if buf is None else buf + "\n" + line
        try:
            cmds = _simple_commands(buf)
        except ValueError:
            continue
        buf = None
        yield cmds
    if buf is not None:
        unclear.append(Unclear(*where, "незакрытая кавычка до конца шага", buf))


def _python_target(cmd: List[str]) -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """(kind, target) для вызова Python, либо (None, причина-неясности|None)."""
    i = 0
    while i < len(cmd) and (_ASSIGN.match(cmd[i]) or cmd[i] in _PREFIX_WORDS):
        i += 1
    if i >= len(cmd):
        return None, None
    word = cmd[i].rsplit("/", 1)[-1]
    if not _PY_WORD.match(word):
        return None, None
    j = i + 1
    while j < len(cmd):
        a = cmd[j]
        if a == "-m":
            if j + 1 < len(cmd):
                return ("module", cmd[j + 1]), None
            return None, "python -m без модуля"
        if a == "-c":
            return None, "python -c: код строкой не разбирается"
        if a in _PY_OPTS_WITH_ARG:
            j += 2
            continue
        if a.startswith("-m") and len(a) > 2:
            return ("module", a[2:]), None
        if a == "-" or a.startswith("-"):
            if a == "-":
                return None, "python - (скрипт со stdin)"
            j += 1
            continue
        target = a[2:] if a.startswith("./") else a
        return ("script", target), None
    return None, None


def scan_workflows(root: pathlib.Path) -> Tuple[List[Call], List[Unclear]]:
    """Все исполняемые вызовы Python в `.github/workflows/*.y*ml` дерева `root`."""
    import yaml  # noqa: PLC0415 — тест-домен, не рантайм (инв. #4)

    calls: List[Call] = []
    unclear: List[Unclear] = []
    wdir = root / _WORKFLOW_DIR
    if not wdir.is_dir():
        return calls, unclear
    for path in sorted(list(wdir.glob("*.yml")) + list(wdir.glob("*.yaml"))):
        wf = str(path.relative_to(root))
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            unclear.append(Unclear(wf, "", "", f"YAML не прочитан: {type(exc).__name__}", ""))
            continue
        if not isinstance(doc, dict):
            unclear.append(Unclear(wf, "", "", "YAML не словарь", ""))
            continue
        # YAML 1.1 читает ключ `on` как True.
        triggers = doc.get("on", doc.get(True))
        if not triggers:
            continue
        wf_shell = ((doc.get("defaults") or {}).get("run") or {}).get("shell")
        jobs = doc.get("jobs") or {}
        if not isinstance(jobs, dict):
            unclear.append(Unclear(wf, "", "", "jobs не словарь", ""))
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if "if" in job and _is_false_literal(job["if"]):
                continue
            job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell")
            for n, step in enumerate(job.get("steps") or []):
                if not isinstance(step, dict) or "run" not in step:
                    continue
                label = str(step.get("name") or step.get("id") or f"#{n}")
                if "if" in step and _is_false_literal(step["if"]):
                    continue
                conditional = "if" in step or "if" in job
                ok, shell = _shell_ok(step.get("shell"), job_shell, wf_shell)
                script = step["run"]
                if not isinstance(script, str):
                    unclear.append(Unclear(wf, str(job_id), label, "run не строка", repr(script)))
                    continue
                if not ok:
                    unclear.append(Unclear(wf, str(job_id), label, f"оболочка {shell!r} не разбирается", script))
                    continue
                lines, dropped = _lines_without_heredocs(script)
                if dropped:
                    unclear.append(Unclear(wf, str(job_id), label, "тело heredoc не разбирается",
                                           "\n".join(dropped)))
                for cmds in _logical_commands(lines, unclear, (wf, str(job_id), label)):
                    for cmd in cmds:
                        tgt, why = _python_target(cmd)
                        if tgt:
                            calls.append(Call(wf, str(job_id), label, tgt[0], tgt[1], conditional))
                        elif why:
                            unclear.append(Unclear(wf, str(job_id), label, why, " ".join(cmd)))
    return calls, unclear


def module_dotted(rel: str) -> str:
    """`spa_core/monitoring/x.py` → `spa_core.monitoring.x`."""
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")


def invoked_modules(root: pathlib.Path, rels: Set[str]) -> Dict[str, List[Call]]:
    """{rel: [вызовы]} — модули из `rels`, которые зовёт исполняемый шаг ТОЧНЫМ путём."""
    calls, _ = scan_workflows(root)
    by_dotted = {module_dotted(r): r for r in rels}
    out: Dict[str, List[Call]] = {}
    for c in calls:
        rel = by_dotted.get(c.target) if c.kind == "module" else (c.target if c.target in rels else None)
        if rel:
            out.setdefault(rel, []).append(c)
    return out


def unclear_mentions(root: pathlib.Path, stem: str) -> List[Unclear]:
    """Неясные конструкции, в тексте которых встречается имя модуля — чтобы не молчать о них."""
    _, unclear = scan_workflows(root)
    return [u for u in unclear if stem in u.text]
