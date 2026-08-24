"""«Отсутствия наблюдения» не существует в данных — измерение класса, а не грепанье.

Зачем
------------------------------------------------------------------------------
18 августа независимые агенты нашли ШЕСТЬ дефектов за один день, и все шесть
оказались одной болезнью: **там, где наблюдения нет, система по умолчанию говорит
«всё хорошо» вместо «не знаю».**

| где | что говорила система | что было на самом деле |
|---|---|---|
| задержка GSM (стоп-кран Sky) | «RPC не ответил» | таймлок СНЯТ (ноль) — и гейт ОТКРЫВАЛСЯ |
| архив исходов | «книга была пустая, кэш = 0» | поля просто не было |
| турнир стратегий | доходность 0 % у протокола | ряда доходности не существует |
| модули Tier-C | «риск слашинга 0.0 — риска нет» | число валидаторов не измерено |
| счётчик воронки сайта | «принято, ok» | на диск не записалось ничего |
| внутридневная просадка | код возврата 0, всё спокойно | сенсор слеп (данные старше 30 ч) |

Каждый случай чинили отдельно, и каждый раз это выглядело частной неаккуратностью.
Шесть за день — это **форма по умолчанию**: в Python `or 0.0`, `or {}` и
`except: return {"ok": True}` пишутся короче честного отказа, поэтому появляются сами.

Решение владельца 2026-08-23 (вариант A, карточка
`owner-decision-shest-nahodok-za-den-okazalis-odnoi-bole`, ADR-129): инвариант #17
в `CLAUDE.md` + храповик на класс с базой, которая может только уменьшаться.

Почему разбор идёт по AST и УЗКО
------------------------------------------------------------------------------
Наивное «в коде есть `or 0.0`» даёт **1445** совпадений на `spa_core`+`scripts`
(замер цикла #360). Запрет такого размера был бы снят раньше, чем починен хоть
один писатель, — проект уже платил за это (`test_frozen_date_ratchet`: 346 файлов
в классе, полный запрет невозможен). Но и база на 1445 записей — та же болезнь
наизнанку: молчаливое разрешение размером с дерево.

Поэтому членом класса считается только то, что владелец и назвал: подстановка
благополучия **рядом с понятием наблюдения, у писателя артефакта**. Сходятся три
признака сразу:

* **S1 — `or`-подстановка вместо отсутствующего наблюдения.** В одном выражении:
  (а) чтение, которое законно может не найтись (`.get("k")` / `d["k"]`),
  (б) ключ из словаря наблюдений (`tvl`, `apy`, `drawdown`, `count`, `age` …),
  (в) справа — падающий литерал (`0`, `0.0`, `{}`, `[]`).
  `d.get("tvl_usd") or 0.0` не различает «ключа нет» и «TVL измерен и равен нулю»
  **по построению**: третьего исхода у выражения нет.
* **S2 — обработчик, докладывающий об успехе.** `except …:` возвращает
  успех-литерал (`True`, `0`, `0.0`, `{"ok": True}`, `{"status": "ok"}`), то есть
  провал измерения выходит наружу неотличимым от измеренного благополучия.

Оба сигнала ищутся только в файлах, которые **пишут артефакт** (`atomic_save` /
`atomic_save_text`): у чистой арифметической функции подстановка остаётся внутри,
а у писателя она уезжает в `data/*.json` и становится тем самым «всё хорошо».

Замер на `origin/main` 07784b1af: **S1 = 192 · S2 = 60**, 120 файлов.

Что НЕ является членом класса (и почему это важно)
------------------------------------------------------------------------------
* `d.get("tvl_usd")` с ЯВНОЙ проверкой `is None` — три исхода различимы, это цель;
* `d.get("k", 0.0)` — форма с умолчанием осознанно НЕ ловится: она встречается
  тысячами и в большинстве мест законна; `or`-форма уже, точна и названа владельцем;
* тесты, `academy/`, `family_fund/` — не производители наблюдений о портфеле.

Область сканирования — дерево ЗАПУЩЕННОГО кода (`REPO_ROOT`), а вложенные рабочие
деревья (`.claude/worktrees/*`) лежат вне `spa_core/` и `scripts/` и в обход не
попадают по построению (урок: сканер в проде считал чужие деревья).

Только stdlib, без импорта разбираемых модулей (разбор обязан быть инертным).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

BASELINE_PATH = Path(__file__).resolve().parent / "absent_observation_baseline.json"

#: Где ищем.
SEARCH_ROOTS = ("spa_core", "scripts")

#: Что НЕ смотрим. Тесты — потому что подстановка в фикстуре и есть фикстура;
#: `academy`/`family_fund` — продуктовые контуры, наблюдений о портфеле не пишут.
SKIP_PREFIXES = (
    "spa_core/tests/",
    "scripts/tests/",
    "spa_core/academy/",
    "spa_core/family_fund/",
)

#: Литералы, которыми подменяют отсутствующее наблюдение. `False` и `""` намеренно
#: НЕ входят: у флага и у строки «пусто» гораздо чаще законное значение.
FALSY_SCALARS = (0, 0.0)

#: Словарь наблюдений: ключ, под которым лежит ИЗМЕРЕННАЯ величина. Подстрока, а не
#: точное имя: живые ключи — `tvl_usd`, `apy_pct`, `drawdown_pct`, `audit_count`.
OBSERVATION_VOCAB = (
    "tvl", "apy", "yield", "rate", "drawdown", "equity", "nav", "price", "balance",
    "volume", "liquidity", "utilization", "count", "validator", "slash", "delay",
    "timelock", "age", "score", "ratio", "share", "pct", "percent", "amount", "usd",
    "capital", "exposure", "observed", "measured", "sample", "history", "series",
    "points", "peak", "cash", "deployed",
)

#: Ключи, чьё значение `True` означает «всё хорошо».
OK_KEYS = frozenset({"ok", "success", "healthy", "passed"})
#: Ключи, чьё значение из `OK_VALUES` означает «всё хорошо».
STATUS_KEYS = frozenset({"status", "verdict", "state", "result"})
OK_VALUES = frozenset({"ok", "OK", "healthy", "HEALTHY", "pass", "PASS",
                       "success", "SUCCESS"})

#: Функции, по которым файл опознаётся как ПИСАТЕЛЬ артефакта.
WRITER_CALLS = frozenset({"atomic_save", "atomic_save_text"})

SIGNAL_OR = "or_falsy"
SIGNAL_EXCEPT = "except_success"
SIGNALS = (SIGNAL_OR, SIGNAL_EXCEPT)


def _falsy_literal(node: ast.AST) -> str | None:
    """Литерал-подстановка справа от ``or``. ``None`` — литерал не падающий."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return None                      # True/False — не про наблюдение
        if node.value in FALSY_SCALARS:
            return repr(node.value)
        return None
    if isinstance(node, ast.Dict) and not node.keys:
        return "{}"
    if isinstance(node, ast.List) and not node.elts:
        return "[]"
    return None


def _lookup_keys(node: ast.AST) -> list[str]:
    """Строковые ключи, читаемые ``.get()``/индексом в поддереве."""
    keys: list[str] = []
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get" and sub.args
                and isinstance(sub.args[0], ast.Constant)
                and isinstance(sub.args[0].value, str)):
            keys.append(sub.args[0].value)
        if (isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant)
                and isinstance(sub.slice.value, str)):
            keys.append(sub.slice.value)
    return keys


def is_observation_key(key: str) -> bool:
    low = key.lower()
    return any(word in low for word in OBSERVATION_VOCAB)


def _success_literal(node: ast.AST) -> str | None:
    """Успех-литерал, возвращаемый из обработчика. ``None`` — не успех."""
    if isinstance(node, ast.Constant):
        if node.value is True:
            return "True"
        if isinstance(node.value, bool):
            return None
        if node.value in FALSY_SCALARS:
            return repr(node.value)
        return None
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            low = k.value.lower()
            if low in OK_KEYS and isinstance(v, ast.Constant) and v.value is True:
                return f"{{{k.value!r}: True}}"
            if (low in STATUS_KEYS and isinstance(v, ast.Constant)
                    and v.value in OK_VALUES):
                return f"{{{k.value!r}: {v.value!r}}}"
    return None


def writes_artifact(tree: ast.AST) -> bool:
    """Пишет ли модуль артефакт — то есть уезжает ли подстановка на диск."""
    for sub in ast.walk(tree):
        if isinstance(sub, ast.Call):
            fn = sub.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in WRITER_CALLS:
                return True
    return False


def scan_source(source: str, rel_path: str) -> list[dict]:
    """Члены класса в ОДНОМ файле. Пустой список — файл чист либо не писатель."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    if not writes_artifact(tree):
        return []
    found: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            literal = _falsy_literal(node.values[-1])
            if literal:
                keys: list[str] = []
                for value in node.values[:-1]:
                    keys.extend(_lookup_keys(value))
                hit = [k for k in keys if is_observation_key(k)]
                if hit:
                    found.append({
                        "signal": SIGNAL_OR,
                        "where": f"{rel_path}:{node.lineno}",
                        "detail": f"{hit[0]!r} or {literal}",
                    })
        if isinstance(node, ast.ExceptHandler):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    literal = _success_literal(sub.value)
                    if literal:
                        found.append({
                            "signal": SIGNAL_EXCEPT,
                            "where": f"{rel_path}:{sub.lineno}",
                            "detail": f"except -> return {literal}",
                        })
    return found


def scan_tree(root: str | Path = REPO_ROOT,
              search_roots: Iterable[str] = SEARCH_ROOTS) -> list[dict]:
    """Все члены класса в дереве, отсортированы по месту (diff читаем)."""
    base = Path(root)
    found: list[dict] = []
    for sub in search_roots:
        start = base / sub
        if not start.is_dir():
            continue
        for path in sorted(start.rglob("*.py")):
            rel = path.relative_to(base).as_posix()
            if any(rel.startswith(prefix) for prefix in SKIP_PREFIXES):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found.extend(scan_source(source, rel))
    found.sort(key=lambda item: (item["signal"], item["where"]))
    return found


def load_baseline(path: str | Path = BASELINE_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def baseline_places(baseline: dict, signal: str) -> list[str]:
    return list(baseline.get("signals", {}).get(signal, {}).get("places", []))


def places_of(found: list[dict], signal: str) -> list[str]:
    return sorted({item["where"] for item in found if item["signal"] == signal})
