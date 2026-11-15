#!/usr/bin/env python3
"""НАСЕЛЕНИЕ КЛАССА «вердикт закреплён за ХОЗЯИНОМ»: сколько утверждений набора судят о коде,
закрепив ответ ОДНОЙ машины о гонке за GIL.

Карточка `inbox-proverka-slepoty-predela-zakrepila-otvet` п. 4. Предмет назван замером, а не
догадкой: `test_observer_margin_control.py::…::test_the_REAL_runner_is_blind_to_a_busy_module`
закрепил литералом `BUSY_LIMIT_BLIND` и был КРАСЕН на CI с момента доставки
(`'BUSY_LIMIT_BITES' != 'BUSY_LIMIT_BLIND'`, прогон 43686574574, шард 6), оставшись зелёным на
Маке. Это тот же класс, которому посвящены разделы `.claude/rules/deployment.md` про КАЛЕНДАРЬ,
НОМЕР ПРОЦЕССА и GIT-ОКРУЖЕНИЕ: в вердикт попадает свойство ХОЗЯИНА. Цена известна — красный по
известной причине перестаёт быть сигналом, а чужой прогон краснеет каждый раз.

ПОВЕРХНОСТЬ — пересечение двух условий, и ни одного из них по отдельности не хватает:

1. файл ГОНИТ настоящую гонку: он зовёт хотя бы одну дверь, за которой стои́т настоящий
   `_run_bounded`/поток (`RACE_DOORS`). Файл, подставляющий бегуна целиком, гонки не видит, и
   его вердикт свойством хозяина не является;
2. в нём есть утверждение, чья ОЖИДАЕМАЯ сторона — член словаря вердиктов гонки
   (`RACE_VERDICT_PREFIXES` и их короткие псевдонимы).

Одного условия №2 мало по замеру: `CANARY_` носят и `test_tier1_canary.py`, и
`test_capital_shadow_lifecycle.py` — там это СОВСЕМ другой словарь, и считать их населением
значило бы отвечать о слове, а не о предмете.

ВЕРДИКТ УТВЕРЖДЕНИЯ — четыре значения, и ни одно не сливается с другим (инв. #17):

| вердикт | что это |
|---|---|
| ``PINNED`` | ожидание есть БАРЕ-константа словаря гонки, и ответ хозяина не спрошен нигде в объемлющем классе/функции ⇒ **предмет класса** |
| ``HOST_ASKED`` | в объемлющем классе/функции ответ хозяина ИЗМЕРЕН дверью (`HOST_DOORS`), то есть ожидание условлено замером, а не машиной автора |
| ``SYNTHETIC`` | бегун подставлен (`runner=`/фальшивый агрегатор) — гонки нет, закреплять нечего |
| ``UNMEASURED`` | файл не разобран; причина НАЗВАНА, и это НЕ вычитание из населения |

**ЧЕГО ПЕРЕПИСЬ НЕ ДОКЛАДЫВАЕТ, и это сказано вслух.** Она отвечает на вопрос «условлено ли
ожидание замером ЭТОГО хозяина ВООБЩЕ», а НЕ «условлена ли каждая ветка». Файл, спросивший
хозяина один раз и закрепивший литерал в другом месте, она назовёт `HOST_ASKED` — то есть
ошибается в сторону НЕДОСЧЁТА, и число является ПОЛОМ населения, а не потолком. Вторая названная граница — та же, о которую споткнулся сторож претензии `injected-clock`
(`.claude/rules/deployment.md` § ИНЪЕКЦИЯ ЧАСОВ, «Чего это НЕ закрывает»): условие №1
спрашивается у ОБЛАСТИ, поэтому область, достающая дверь через ОБЩЕГО помощника
(`self._ctl(...)` вместо прямого зова), в поверхность не попадёт. Разрешать имена через
иерархию классов прибор не умеет и об этом ГОВОРИТ, а не молчит. Мера статическая:
краснеет ли утверждение на другом хозяине, она не меряет — у такой проверки предпосылка «второй
хозяин» есть вход ХАРНЕССА (`.claude/rules/deployment.md` § GIT-ОКРУЖЕНИЕ, п. 2), а не свойство
прибора. Гонку за GIL подменить нельзя: `faketime`-аналога у планировщика нет.

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — настоящая авария в её настоящем месте: редакция
`test_observer_margin_control.py` ДО починки (`git show origin/main:…`) обязана получить
`PINNED`. Перепись, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Код возврата: **0** — население ИЗМЕРЕНО и предмет класса ПУСТ · **1** — предмет НЕ пуст
(перечислен поимённо) · **2** — НЕ ИЗМЕРЕНО с названной причиной. «Тихого нуля» у прибора нет.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Двери, за которыми стои́т НАСТОЯЩАЯ гонка (поток + предел). Перечень ОБЪЯВЛЕН, а не выведен
#: обходом: дверь, которой здесь нет, в поверхность не попадёт, и это видно в самом перечне.
RACE_DOORS = ("observer_margin_control", "_run_bounded", "trace_once", "trace_bare",
              "primitive_control", "host_busy_limit", "bounded_countdown_probe")

#: Двери, которыми ответ ХОЗЯИНА измеряется ОТДЕЛЬНЫМ вопросом ДО сцены.
HOST_DOORS = ("host_busy_limit", "HOST_BUSY_VERDICTS")

#: Приставки словарей вердиктов, чей исход решает гонка за GIL.
RACE_VERDICT_PREFIXES = ("BUSY_LIMIT_", "COUNTDOWN_", "HOST_LIMIT_")

#: Короткие псевдонимы тех же словарей, как их распаковывают батареи
#: (`_BZ_BITES, _BZ_BLIND, _BZ_UNMEASURED = rrwc.BUSY_LIMIT_VERDICTS`). Без них перепись
#: смотрела бы на длинное имя, которого в утверждении нет ни разу.
RACE_ALIAS_PREFIXES = ("_BZ_", "_H_")

#: Ключевые слова, которыми НАСТОЯЩАЯ дверь подменяется сценой. Подстановка есть признак
#: того, что исход решают ДАННЫЕ теста, а не гонка на этой машине.
INJECTION_KWARGS = ("runner", "observe_door")

#: Имена утверждений, у которых есть ОЖИДАЕМАЯ сторона.
EQUALITY_ASSERTS = ("assertEqual", "assertEquals", "assertNotEqual", "assertIs", "assertIn")

VERDICTS = ("PINNED", "HOST_ASKED", "SYNTHETIC", "UNMEASURED")
PINNED, HOST_ASKED, SYNTHETIC, UNMEASURED = VERDICTS


class NotMeasured(RuntimeError):
    """Предпосылка замера не обеспечена. Поднимается, а не возвращается нулём."""


@dataclass
class Claim:
    """Одно утверждение поверхности."""
    file: str
    line: int
    scope: str
    constant: str
    verdict: str
    reason: str


@dataclass
class Census:
    files_seen: int = 0
    surface: List[str] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)
    unmeasured: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def subject(self) -> List[Claim]:
        return [c for c in self.claims if c.verdict == PINNED]

    @property
    def host_asked(self) -> List[Claim]:
        return [c for c in self.claims if c.verdict == HOST_ASKED]

    @property
    def synthetic(self) -> List[Claim]:
        return [c for c in self.claims if c.verdict == SYNTHETIC]


def _is_race_constant(node: ast.AST) -> Optional[str]:
    """Имя БАРЕ-константы словаря гонки, если операнд ею является."""
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    else:
        return None
    if name.startswith(RACE_VERDICT_PREFIXES) or name.startswith(RACE_ALIAS_PREFIXES):
        # Сам СЛОВАРЬ (кортеж значений) ожиданием не является — им является его ЧЛЕН.
        return None if name.endswith("VERDICTS") else name
    return None


def _names_in(node: ast.AST) -> set:
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
    return out


def _injects_a_substitute(node: ast.AST) -> bool:
    """Подставлена ли дверь вместо настоящей: `runner=` / `observe_door=` внутри области.

    Подстановка означает, что исход решают ДАННЫЕ сцены, а не гонка на этой машине, — значит
    закреплять за хозяином нечего.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            for kw in sub.keywords:
                if kw.arg in INJECTION_KWARGS:
                    return True
    return False


def measure_source(source: str, *, label: str) -> List[Claim]:
    """Утверждения ОДНОГО исходника.

    Поверхностное условие №1 спрашивается у ОБЛАСТИ, а не у файла, и это не мелочь: в
    `test_observer_margin_control.py` рядом живут СИНТЕТИЧЕСКИЕ сцены, чьи строки сфабрикованы
    (`observe_door=`), и сквозная, гоняющая настоящую гонку. Спроси условие у файла — и шесть
    синтетических утверждений попадут в население, которого они не составляют: их `_BZ_BLIND`
    закреплён за ДАННЫМИ сцены, а не за машиной. Замер: 8 ложных `PINNED` против 0 истинных.
    """
    tree = ast.parse(source)
    claims: List[Claim] = []
    # Область — КЛАСС (у unittest ожидание часто условлено в `setUpClass`), а при отсутствии
    # класса — функция. Спрашивать у одной функции означало бы не увидеть `cls.host` вовсе.
    scopes: List[Tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            scopes.append((node.name, node))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append((node.name, node))
    for scope_name, scope in scopes:
        scope_names = _names_in(scope)
        if not any(d in scope_names for d in RACE_DOORS):
            # Область настоящей гонки не гонит ⇒ она НЕ В ПОВЕРХНОСТИ. Это не «чисто» и не
            # вычитание: о ней просто не задан вопрос, и выдумывать ей вердикт значило бы
            # отвечать о том, чего не смотрели.
            continue
        asked = any(d in scope_names for d in HOST_DOORS)
        synthetic = _injects_a_substitute(scope)
        for sub in ast.walk(scope):
            if not isinstance(sub, ast.Call):
                continue
            fn = sub.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname not in EQUALITY_ASSERTS:
                continue
            for operand in sub.args:
                const = _is_race_constant(operand)
                if const is None:
                    continue
                if synthetic:
                    v, why = SYNTHETIC, (f"дверь подставлена ({'/'.join(INJECTION_KWARGS)}): "
                                         "исход решают данные сцены, а не гонка на этой "
                                         "машине — закреплять нечего")
                elif asked:
                    v, why = HOST_ASKED, ("ответ хозяина ИЗМЕРЕН в области дверью "
                                          f"{'/'.join(HOST_DOORS)} — ожидание условлено "
                                          "замером, а не машиной автора")
                else:
                    v, why = PINNED, (f"ожидание есть БАРЕ-константа {const} словаря гонки, а "
                                      "ответ хозяина в области не спрошен ни одной дверью — "
                                      "вердикт закреплён за ОДНОЙ машиной")
                claims.append(Claim(file=label, line=sub.lineno, scope=scope_name,
                                    constant=const, verdict=v, reason=why))
    return claims


def measure(repo: Path) -> Census:
    """Перепись по КАНОНИЧЕСКОМУ охвату храповиков: `spa_core/tests/test_*.py`, `glob`.

    `glob`, а не `rglob` — это ЗАМЕР охвата соседних храповиков (`.claude/rules/deployment.md`
    § ИНЪЕКЦИЯ ЧАСОВ, п. 4), а не выбор прибора.
    """
    tests = repo / "spa_core" / "tests"
    if not tests.is_dir():
        raise NotMeasured(f"каталога тестов нет: {tests} — поверхность не построить, и "
                          f"пустое население было бы свойством прибора")
    census = Census()
    paths = sorted(tests.glob("test_*.py"))
    if not paths:
        raise NotMeasured(f"в {tests} нет ни одного `test_*.py`: «ноль утверждений» здесь есть "
                          f"НЕ ИЗМЕРЕНО, а не чистый класс")
    for path in paths:
        census.files_seen += 1
        rel = str(path.relative_to(repo))
        try:
            claims = measure_source(path.read_text(encoding="utf-8"), label=rel)
        except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
            census.unmeasured.append((rel, f"{type(exc).__name__}: {exc}"))
            continue
        if claims:
            census.surface.append(rel)
            census.claims.extend(claims)
    return census


def render(census: Census) -> str:
    out: List[str] = []
    out.append(f"перепись «вердикт закреплён за ХОЗЯИНОМ»: файлов прочитано "
               f"{census.files_seen}, в поверхности {len(census.surface)}, утверждений "
               f"{len(census.claims)}")
    out.append(f"  ПРЕДМЕТ (PINNED) {len(census.subject)} · HOST_ASKED "
               f"{len(census.host_asked)} · SYNTHETIC {len(census.synthetic)} · "
               f"файлов НЕ ИЗМЕРЕНО {len(census.unmeasured)}")
    for c in census.subject:
        out.append(f"  [PINNED] {c.file}:{c.line} ({c.scope}) — {c.reason}")
    for c in census.host_asked:
        out.append(f"  [HOST_ASKED] {c.file}:{c.line} ({c.scope}) — ожидание условлено замером")
    for rel, why in census.unmeasured:
        out.append(f"  [НЕ ИЗМЕРЕНО] {rel}: {why}")
    out.append("  число ПРЕДМЕТА есть ПОЛ, а не потолок: область спрашивается целиком, поэтому "
               "файл, спросивший хозяина один раз и закрепивший литерал в другом месте, "
               "недосчитан НАМЕРЕННО (сказано в самом приборе)")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=None,
                    help="дерево замера. Умолчание — дерево прибора, и оно ПЕЧАТАЕТСЯ")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    declared = args.repo_root is not None
    repo = Path(args.repo_root) if declared else Path(__file__).resolve().parents[1]
    if declared and not repo.is_dir():
        print(f"НЕ ИЗМЕРЕНО: названное дерево не читается: {repo}", file=sys.stderr)
        return 2
    if not declared:
        print(f"дерево НЕ НАЗВАНО — умолчание: {repo}", file=sys.stderr)
    try:
        census = measure(repo)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"files_seen": census.files_seen, "surface": census.surface,
                          "claims": [vars(c) for c in census.claims],
                          "unmeasured": census.unmeasured}, ensure_ascii=False, indent=2))
    else:
        print(render(census))
    if census.unmeasured:
        return 2
    return 1 if census.subject else 0


if __name__ == "__main__":
    raise SystemExit(main())
