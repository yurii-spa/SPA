"""§45 ТЗ «Portfolio CIO» — Architecture constraints: измеряем разделение слоёв.

Владелец (§45, дословно):

    Не создавать одного огромного AI-agent, который: читает рынок; считает APY;
    считает gas; принимает risk decision; подписывает транзакцию.
    Разделить: Data → Deterministic Portfolio Optimizer → Risk Policy →
    Execution Planner → Execution → Monitoring.
    AI/LLM может быть orchestration/explanation layer, но не единственным
    финансовым control layer.

Это ДВА разных требования, и мерить их надо порознь — они и нарушаются порознь:

1. **Концентрация.** Не совмещены ли названные владельцем ответственности в
   ОДНОМ модуле. Мера — по САЙТУ ИСПОЛНЕНИЯ (разбор AST), а не по упоминанию.
2. **LLM как control layer.** Достижима ли дверь к LLM с денежного пути, и —
   главное — **меряет ли это хоть один сторож**. Ответ «сегодня не достижима»
   без сторожа означает «держится случайно», а не «ограничение стои́т».

🪤 Три ловушки, ради которых проба устроена именно так.

**Первая — упоминание принимают за исполнение.** Модуль, ОПИСЫВАЮЩИЙ аварию
подписи или падение `claude`, содержит те же слова, что и модуль, который
подписывает и зовёт. Живой образец в дереве: `spa_core/monitoring/
owner_decision_pending.py` называет `ask_router` и `claude` четырежды — и все
четыре раза в комментариях. Поэтому строковые литералы берутся БЕЗ докстрок, а
комментарии до AST не доходят вовсе. Обратный контроль на этом образце —
обязательное условие вердикта.

**Вторая — достижимость выдают за управление.** «Из `spa_core/monitoring/` LLM
достижим» — верное измерение и НЕ находка: все семь путей идут в канал
уведомления владельца (`owner_queue.notify` → `telegram.bot`), то есть ровно в
тот explanation layer, который владелец РАЗРЕШАЕТ. Отчёт, назвавший это
нарушением, был бы верным ответом на не тот вопрос (класс #511: сцена обязана
нарушать ИМЕННО своё ограничение). Поэтому достижимость печатается вместе с
путём и с именем канала, а находкой объявляется не она, а слепота сторожа.

**Третья — «сторож есть» вместо «сторож видит».** Инвариант #3 («LLM запрещён в
risk / execution / monitoring / kill») охраняется единственной проверкой
`scripts/lint_llm_forbidden.py`, и она ищет ИМПОРТЫ SDK. Дверь этой системы к
LLM — не SDK, а `subprocess` к бинарю `claude` (`spa_core/telegram/
ask_router.py:148`). Слепота меряется ЗАМЕРОМ, а не рассуждением: в копию
дерева во временном каталоге вносится дверь того и другого рода, и линт
запускается на копии. Живой каталог при этом не читается и не пишется.

Третий исход обязателен и громкий: не разобран ни один модуль ⇒ вердикт
`UNCHECKED`, счёт читать нельзя. Положительный контроль — условие всего отчёта.

ADVISORY. Модуль ничего не разделяет и ничего не запрещает: он МЕРЯЕТ. Разнести
ответственности живых адаптеров исполнения и расширить сторожа инварианта #3 —
изменение money-path и решение владельца, а не строка автокарточки.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import pathlib
import shutil
import tempfile
from typing import Any

from spa_core.monitoring.cio_target_producers import (
    _fleet_entry_modules,
    _import_graph,
    _iter_runtime_modules,
    _module_dotted,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_architecture_constraints.json"

UNCHECKED = "UNCHECKED"

#: Пять ответственностей ровно из текста §45, и КАК каждая опознаётся на сайте
#: исполнения. Формулировка владельца — слева, признак — справа; расхождение
#: между ними и есть то, за что проба отвечает.
RESPONSIBILITIES: tuple[tuple[str, str, str], ...] = (
    ("market_read", "читает рынок",
     "модуль сам открывает сетевое соединение (urlopen / HTTPConnection / "
     "HTTPSConnection / create_connection)"),
    ("apy", "считает APY",
     "модуль определяет функцию со ставкой в имени, ВОЗВРАЩАЮЩУЮ выражение, "
     "а не литерал и не поле"),
    ("gas", "считает gas",
     "модуль спрашивает газ у цепи: строковый литерал RPC-метода eth_gasPrice "
     "/ eth_estimateGas / eth_maxPriorityFeePerGas / eth_feeHistory"),
    ("risk_decision", "принимает risk decision",
     "модуль СТРОИТ вердикт допуска: конструирует отображение или вызов с "
     "ключом approved"),
    ("sign", "подписывает транзакцию",
     "модуль подписывает или отправляет транзакцию: литерал "
     "eth_sendRawTransaction, вызов sign_transaction / signTransaction / "
     "from_key, либо чтение приватного ключа из окружения"),
)

_NET_CALLS = {"urlopen", "HTTPSConnection", "HTTPConnection", "create_connection"}
_GAS_RPC = {"eth_gasPrice", "eth_estimateGas", "eth_maxPriorityFeePerGas",
            "eth_feeHistory"}
_SIGN_RPC = {"eth_sendRawTransaction"}
_SIGN_CALLS = {"sign_transaction", "signTransaction", "from_key",
               "sign_typed_data"}
_SIGN_ENV = {"SPA_PRIVATE_KEY", "PRIVATE_KEY", "SPA_SIGNER_KEY"}
_RATE_WORDS = ("apy", "yield", "supply_rate", "borrow_rate")
_VERDICT_KEYS = {"approved"}

#: Шесть слоёв §45 → их дом в дереве. Побеждает САМЫЙ ДЛИННЫЙ префикс: планировщик
#: живёт внутри пакета исполнения, и без этого правила он был бы неотличим от него.
LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1-data", ("spa_core.adapters", "spa_core.feeds", "spa_core.price_feeds",
                "spa_core.data_pipeline")),
    ("2-optimizer", ("spa_core.allocator", "spa_core.tuner",
                     "spa_core.optimization")),
    ("3-risk-policy", ("spa_core.risk", "spa_core.governance")),
    ("4-execution-planner", ("spa_core.execution.draft_prep",
                             "spa_core.execution.router",
                             "spa_core.execution.safe_tx_builder",
                             "spa_core.execution.arming")),
    ("5-execution", ("spa_core.execution",)),
    ("6-monitoring", ("spa_core.monitoring",)),
)

#: Каналы, которые владелец §45 РАЗРЕШАЕТ (orchestration / explanation). Путь к
#: LLM, идущий через них, — не находка; объявлено данными, чтобы отчёт не решал
#: это по наитию.
_EXPLANATION_CHANNELS = ("spa_core.telegram", "spa_core.owner_queue")

#: Дверь к LLM бывает ДВУХ родов. Действующий сторож знает только первый.
_SDK_ROOTS = ("anthropic", "openai", "google.generativeai", "langchain",
              "llama", "cohere", "mistralai", "ollama")
_LLM_BINARIES = ("claude", "llm", "ollama")


# ───────────────────────────── разбор одного модуля ───────────────────────────

def _docstring_ids(tree: ast.AST) -> set[int]:
    """Узлы-докстроки: их литералы к делу не относятся (ловушка №1)."""
    out: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            body = getattr(n, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _code_strings(tree: ast.AST) -> set[str]:
    """Строковые литералы КОДА — без докстрок. Комментариев в AST нет вовсе."""
    docs = _docstring_ids(tree)
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docs}


def _called_names(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def _computes_rate(tree: ast.AST) -> bool:
    """Функция со ставкой в имени, возвращающая ВЫРАЖЕНИЕ, а не литерал/поле."""
    for f in ast.walk(tree):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(w in f.name.lower() for w in _RATE_WORDS):
            continue
        for r in ast.walk(f):
            if isinstance(r, ast.Return) and isinstance(r.value, ast.BinOp):
                return True
    return False


def _builds_verdict(tree: ast.AST) -> bool:
    """Модуль СТРОИТ вердикт допуска (ключ ``approved``), а не читает чужой."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and k.value in _VERDICT_KEYS:
                    return True
        if isinstance(n, ast.keyword) and n.arg in _VERDICT_KEYS:
            return True
    return False


def module_responsibilities(tree: ast.AST) -> set[str]:
    """Какие из пяти ответственностей §45 модуль ИСПОЛНЯЕТ (не упоминает)."""
    strings = _code_strings(tree)
    calls = _called_names(tree)
    out: set[str] = set()
    if calls & _NET_CALLS:
        out.add("market_read")
    if _computes_rate(tree):
        out.add("apy")
    if strings & _GAS_RPC:
        out.add("gas")
    if _builds_verdict(tree):
        out.add("risk_decision")
    if (strings & _SIGN_RPC) or (calls & _SIGN_CALLS) or (strings & _SIGN_ENV):
        out.add("sign")
    return out


_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _string_bindings(tree: ast.AST) -> dict[str, set[str]]:
    """Имя → строковые значения, ПРОИСХОДЯЩИЕ от его присваивания.

    ``_CLAUDE = os.environ.get("SPA_CLAUDE_BIN") or "/abs/path/claude"`` даёт
    имени оба литерала: какой из них выиграет в рантайме, статикой не решить,
    и обе ветви одинаково ведут к бинарю.
    """
    out: dict[str, set[str]] = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign) or n.value is None:
            continue
        values = {c.value for c in ast.walk(n.value)
                  if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if not values:
            continue
        for target in n.targets:
            if isinstance(target, ast.Name):
                out.setdefault(target.id, set()).update(values)
    return out


def _argv_strings(call: ast.Call, binds: dict[str, set[str]]) -> set[str]:
    """Строки, попадающие в argv вызова, — литералами или через имя."""
    if not call.args:
        return set()
    head = call.args[0]
    out: set[str] = set()
    for node in ast.walk(head):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
        elif isinstance(node, ast.Name):
            out.update(binds.get(node.id, ()))
    return out


def _is_llm_binary(value: str) -> bool:
    tail = value.rsplit("/", 1)[-1]
    return tail in _LLM_BINARIES or tail.startswith("claude")


def llm_door(tree: ast.AST) -> str:
    """Род двери к LLM: ``sdk`` · ``subprocess`` · ``""`` (двери нет).

    🪤 Дверь признаётся по ПРОИСХОЖДЕНИЮ значения, а не по совпадению строки в
    теле модуля. Первая редакция считала дверью любой модуль, где рядом живут
    вызов ``subprocess`` и строка про LLM, — и назвала дверьми два невиновных:
    ``scripts/fill_agent_passports.py`` (литерал ``"CLAUDE_BIN"`` там —
    ИСКОМАЯ строка чужого паспорта, а зовёт модуль git) и
    ``spa_core/monitoring/telegram_watcher.py`` (слово ``ANTHROPIC_API_KEY``
    внутри текста ОШИБКИ про Keychain, а зовёт модуль ``security``). Ложная
    дверь не краснеет никогда — она молча раздувает счёт, — поэтому спрашивать
    надо, доходит ли имя бинаря до argv вызова.
    """
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if any(a.name == r or a.name.startswith(r + ".")
                       for r in _SDK_ROOTS):
                    return "sdk"
        elif isinstance(n, ast.ImportFrom) and n.module:
            if any(n.module == r or n.module.startswith(r + ".")
                   for r in _SDK_ROOTS):
                return "sdk"
    binds = _string_bindings(tree)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else "")
        if name not in _SUBPROCESS_FUNCS:
            continue
        if any(_is_llm_binary(v) for v in _argv_strings(n, binds)):
            return "subprocess"
    return ""


# ───────────────────────────── разбор всего дерева ────────────────────────────

def _layer_of(module: str) -> str:
    best: tuple[int, str] | None = None
    for name, prefixes in LAYERS:
        for p in prefixes:
            if module == p or module.startswith(p + "."):
                if best is None or len(p) > best[0]:
                    best = (len(p), name)
    return best[1] if best else ""


def scan_tree(root: str) -> dict:
    """Один проход по дереву: ответственности и двери LLM у каждого модуля."""
    responsibilities: dict[str, list[str]] = {}
    doors: dict[str, str] = {}
    unparsed: list[str] = []
    parsed = 0
    for rel, path in _iter_runtime_modules(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            unparsed.append(f"{rel}: {type(exc).__name__}")
            continue
        parsed += 1
        resp = module_responsibilities(tree)
        if resp:
            responsibilities[rel] = sorted(resp)
        kind = llm_door(tree)
        if kind:
            doors[rel] = kind
    return {"responsibilities": responsibilities, "doors": doors,
            "unparsed": unparsed, "parsed": parsed}


def _reverse_reach(root: str, targets: set[str]) -> tuple[dict[str, list[str]], str]:
    """Кратчайший путь импортов от каждого модуля до ближайшей двери.

    ``""`` во втором поле — измерено; иначе причина, по которой НЕ измерено.
    """
    graph = _import_graph(root)
    if not graph:
        return {}, "ни один модуль рантайма не разобран — граф импортов пуст"
    known = set(graph)

    def resolve(dep: str) -> str | None:
        cand = dep
        while cand and cand not in known:
            cand = cand.rpartition(".")[0]
        return cand or None

    edges = {m: {r for r in (resolve(d) for d in deps) if r}
             for m, deps in graph.items()}
    import collections
    paths: dict[str, list[str]] = {}
    for start in graph:
        prev: dict[str, str | None] = {start: None}
        queue = collections.deque([start])
        hit = ""
        while queue:
            cur = queue.popleft()
            if cur in targets and cur != start:
                hit = cur
                break
            for dep in edges.get(cur, ()):
                if dep not in prev:
                    prev[dep] = cur
                    queue.append(dep)
        if hit:
            chain: list[str] = []
            node: str | None = hit
            while node is not None:
                chain.append(node)
                node = prev[node]
            paths[start] = list(reversed(chain))
    return paths, ""


def control_layers_reaching_llm(by_layer: dict[str, Any]) -> list[str]:
    """Слои ДЕНЕЖНОГО пути, с которых LLM достижим НЕ через канал объяснения.

    Отдельной функцией — по замеру, а не для красоты. Фильтр «не через канал
    объяснения» на сегодняшнем дереве **инертен**: у всех пяти денежных слоёв
    ``modules_reaching == 0`` (замер 07.09, цикл #514), поэтому его снятие не
    меняет ни одной строки отчёта и НЕ красит ни одного теста — ровно тот
    случай, когда сторож не проверен, потому что при сегодняшнем состоянии
    он лишний. Проверить его можно только подачей состояния, которого в дереве
    нет, а подать состояние можно только в функцию. Внутри ``run`` он был
    непроверяемым по построению.

    Монитор (``6-monitoring``) сюда не входит намеренно: владелец §45 разрешает
    LLM как orchestration/explanation layer, а канал уведомления живёт именно
    там.
    """
    return [name for name, _prefixes in LAYERS
            if name != "6-monitoring"
            and by_layer.get(name, {}).get("modules_reaching")
            and not by_layer.get(name, {}).get("through_explanation_channel")]


# ───────────────────── слепота действующего сторожа (замер) ───────────────────

def lint_blindness(root: str) -> dict:
    """ЗАМЕР: что видит `scripts/lint_llm_forbidden.py` из двух родов двери.

    Обе двери вносятся в КОПИЮ дерева во временном каталоге — живой каталог
    не читается и не пишется. Ответ «инструмента нет» — самостоятельный третий
    исход, а не ноль нарушений (класс #465).
    """
    lint_path = os.path.join(root, "scripts", "lint_llm_forbidden.py")
    if not os.path.isfile(lint_path):
        return {"measured": False,
                "reason": f"проверки нет в дереве: scripts/lint_llm_forbidden.py"}
    import importlib.util
    spec = importlib.util.spec_from_file_location("_spa_llm_lint_probe", lint_path)
    if spec is None or spec.loader is None:
        return {"measured": False, "reason": "проверку не удалось загрузить как модуль"}
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"проверка не импортируется: {type(exc).__name__}: {exc}"}
    if not hasattr(mod, "run_lint"):
        return {"measured": False, "reason": "у проверки нет run_lint(base_dir)"}

    scenes = {
        "sdk_import": "import anthropic\n\n\ndef ask(q):\n    return anthropic.go(q)\n",
        "subprocess_binary": (
            "import subprocess\n\n\ndef ask(q):\n"
            "    out = subprocess.run(['/usr/local/bin/claude', '-p', q],\n"
            "                         capture_output=True, text=True)\n"
            "    return out.stdout\n"),
    }
    out: dict[str, Any] = {"measured": True, "reason": "", "scenes": {}}
    for key, body in scenes.items():
        tmp = tempfile.mkdtemp(prefix="spa_llm_lint_")
        try:
            risk_dir = os.path.join(tmp, "spa_core", "risk")
            os.makedirs(risk_dir)
            with open(os.path.join(risk_dir, "probe_llm_door.py"), "w",
                      encoding="utf-8") as fh:
                fh.write(body)
            _files, violations = mod.run_lint(tmp)
            out["scenes"][key] = {"violations": len(violations),
                                  "seen": bool(violations)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    sdk = out["scenes"].get("sdk_import", {})
    sub = out["scenes"].get("subprocess_binary", {})
    out["blind_to_subprocess"] = bool(sdk.get("seen")) and not sub.get("seen")
    out["control_ok"] = bool(sdk.get("seen"))
    return out


# ───────────────────────────── положительный контроль ─────────────────────────

_CONTROL_MONOLITH = '''
import subprocess
import urllib.request


def get_apy(raw):
    return raw["rate"] * 100.0


def gas():
    return _rpc("eth_gasPrice")


def _rpc(method):
    return urllib.request.urlopen("https://rpc.example/" + method)


def decide(target):
    return {"approved": True, "target": target}


def send(tx):
    return _rpc("eth_sendRawTransaction")


def ask(q):
    return subprocess.run(["claude", "-p", q])
'''


def _positive_control(root: str, scan: dict) -> tuple[bool, str, dict]:
    """Три контроля. Ни один не пройден ⇒ вердикт не применяется вовсе.

    К1 — синтетический монолит опознаётся по ВСЕМ пяти ответственностям.
    К2 — известная дверь `spa_core/telegram/ask_router.py` опознаётся дверью
         рода `subprocess`: не опознана ⇒ проба слепа именно там, где отвечает.
    К3 (обратный) — модуль, лишь УПОМИНАЮЩИЙ дверь и подпись в комментариях,
         дверью и подписантом НЕ считается. Образец живой, не выдуманный.
    """
    checks: dict[str, str] = {}

    tree = ast.parse(_CONTROL_MONOLITH)
    got = module_responsibilities(tree)
    want = {name for name, _, _ in RESPONSIBILITIES}
    checks["К1 монолит"] = ("опознан 5/5" if got == want else
                            f"опознано {sorted(got)}, ожидалось {sorted(want)}")
    if got != want:
        return False, (f"К1: синтетический монолит опознан не полностью "
                       f"({sorted(got)}) — «концентрации нет» ниже означало бы "
                       f"не разделение слоёв, а слепую пробу"), checks
    if llm_door(tree) != "subprocess":
        checks["К1 дверь"] = "дверь монолита не опознана"
        return False, ("К1: у синтетического монолита не опознана дверь к LLM "
                       "— «дверей нет» ниже читать нельзя"), checks
    checks["К1 дверь"] = "опознана (subprocess)"

    known_door = "spa_core/telegram/ask_router.py"
    kind = scan["doors"].get(known_door, "")
    checks["К2 известная дверь"] = kind or "НЕ опознана"
    if kind != "subprocess":
        return False, (f"К2: известная дверь {known_door} опознана как "
                       f"«{kind or 'её нет'}» — проба слепа ровно там, где "
                       f"отвечает на вопрос владельца"), checks

    mention_only = "spa_core/monitoring/owner_decision_pending.py"
    mpath = os.path.join(root, mention_only)
    if os.path.isfile(mpath):
        bad_door = scan["doors"].get(mention_only, "")
        bad_resp = set(scan["responsibilities"].get(mention_only, ()))
        checks["К3 упоминание"] = (
            f"дверь={bad_door or 'нет'} подпись={'да' if 'sign' in bad_resp else 'нет'}")
        if bad_door or "sign" in bad_resp:
            return False, (f"К3 (обратный): {mention_only} только УПОМИНАЕТ "
                           f"дверь и подпись в комментариях, а проба засчитала "
                           f"их исполнением — счёт завышен ложными"), checks
    else:
        checks["К3 упоминание"] = "образец из дерева пропал — контроль не поставлен"

    return True, "", checks


# ─────────────────────────────────── замер ────────────────────────────────────

def run(root: str = REPO_ROOT, *, write: bool = True,
        now: dt.datetime | None = None) -> dict:
    """Замер §45. Живой ``data/`` не читается и не пишется (кроме отчёта)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    scan = scan_tree(root)

    findings: list[dict] = []
    unchecked: list[str] = []

    if not scan["parsed"]:
        doc = _document(now, UNCHECKED, {"critical": 0, "warn": 0, "info": 0,
                                         "unchecked": 1},
                        scan, {}, {}, {}, [],
                        ["ни один модуль рантайма не разобран — вердикт о "
                         "разделении слоёв мерить нечем"],
                        {"passed": False,
                         "reason": "дерево не разобрано", "checks": {}})
        if write:
            _write(doc, root)
        return doc

    control_ok, control_reason, checks = _positive_control(root, scan)
    control = {"passed": control_ok, "reason": control_reason, "checks": checks}

    if not control_ok:
        doc = _document(now, UNCHECKED,
                        {"critical": 0, "warn": 0, "info": 0, "unchecked": 1},
                        scan, {}, {}, {}, [],
                        [f"положительный контроль не пройден — {control_reason}; "
                         "счёт по §45 читать нельзя"], control)
        if write:
            _write(doc, root)
        return doc

    # ── 1. Концентрация ответственностей ─────────────────────────────────────
    concentrated = sorted(
        ((len(v), rel, v) for rel, v in scan["responsibilities"].items()
         if len(v) >= 2), reverse=True)
    market_and_sign = [rel for _n, rel, v in concentrated
                       if "market_read" in v and "sign" in v]
    concentration = {
        "max": concentrated[0][0] if concentrated else 0,
        "of": len(RESPONSIBILITIES),
        "modules": [{"module": rel, "count": n, "responsibilities": v,
                     "layer": _layer_of(_module_dotted(rel))}
                    for n, rel, v in concentrated],
        "market_and_sign": market_and_sign,
    }

    for n, rel, v in concentrated:
        if n < 3:
            continue
        words = ", ".join(w for key, w, _ in RESPONSIBILITIES if key in v)
        findings.append({
            "severity": "CRITICAL" if n >= 4 else "WARN",
            "code": f"concentration:{rel}",
            "message": (
                f"{rel} исполняет {n} из {len(RESPONSIBILITIES)} названных "
                f"владельцем ответственностей в ОДНОМ модуле: {words}. "
                f"Слой по дереву — {_layer_of(_module_dotted(rel)) or '—'}. "
                f"«Не один огромный агент» нарушается не размером, а именно "
                f"этим совмещением. Слова здесь — владельца, признак — "
                f"измеряемый: «читает рынок» это СОБСТВЕННАЯ сетевая дверь "
                f"модуля (у адаптеров исполнения ею идут и котировка ставки, "
                f"и вызовы цепи), полный список признаков — в "
                f"responsibilities_declared")})

    if market_and_sign:
        findings.append({
            "severity": "WARN", "code": "market_and_sign",
            "message": (
                f"{len(market_and_sign)} модул(ь/я/ей) совмещают ДВА полюса "
                f"списка §45 — чтение рынка и подпись транзакции: "
                + ", ".join(market_and_sign)
                + ". Капитал сегодня не двигается (live-путь за флагом "
                  "SPA_EXECUTION_MODE=live и dry_run по умолчанию), поэтому "
                  "это находка ПРОЕКТА, а не сегодняшняя авария — и сказано "
                  "это здесь, а не подразумевается")})

    # ── 2. LLM: достижимость и то, что она значит ────────────────────────────
    door_modules = {_module_dotted(rel) for rel in scan["doors"]}
    paths, reach_reason = _reverse_reach(root, door_modules)
    llm: dict[str, Any] = {
        "doors": [{"module": rel, "kind": kind}
                  for rel, kind in sorted(scan["doors"].items())],
        "reach_measured": not reach_reason,
        "reach_reason": reach_reason,
        "by_layer": {},
    }
    if reach_reason:
        unchecked.append(f"достижимость двери LLM: {reach_reason}")
    else:
        for name, _prefixes in LAYERS:
            hits = sorted(m for m, chain in paths.items()
                          if _layer_of(m) == name and chain)
            entry: dict[str, Any] = {"modules_reaching": len(hits)}
            if hits:
                sample = min((paths[m] for m in hits), key=len)
                entry["shortest_path"] = sample
                entry["through_explanation_channel"] = any(
                    hop.startswith(c) for hop in sample[1:-1]
                    for c in _EXPLANATION_CHANNELS)
            llm["by_layer"][name] = entry

        control_layers = [n for n, _ in LAYERS if n != "6-monitoring"]
        direct = control_layers_reaching_llm(llm["by_layer"])
        if direct:
            findings.append({
                "severity": "CRITICAL", "code": "llm_on_control_path",
                "message": (
                    "дверь к LLM достижима со слоя(ёв) " + ", ".join(direct)
                    + " НЕ через канал объяснения — владелец разрешает LLM "
                      "только как orchestration/explanation layer")})
        else:
            findings.append({
                "severity": "INFO", "code": "llm_reach_explanation_only",
                "message": (
                    "LLM с денежного пути НЕ достижим: у слоёв "
                    + ", ".join(f"{n}={llm['by_layer'].get(n, {}).get('modules_reaching', 0)}"
                                for n in control_layers)
                    + "; из monitoring достижим у "
                    + str(llm["by_layer"].get("6-monitoring", {}).get("modules_reaching", 0))
                    + " модул(я/ей), и все пути идут через канал уведомления "
                      "владельца — это explanation layer, который владелец "
                      "разрешает. Достижимость здесь НЕ находка")})

    # ── 3. Сторож: видит ли он дверь, которой система пользуется ─────────────
    guard = lint_blindness(root)
    llm["guard"] = guard
    if not guard.get("measured"):
        unchecked.append(f"слепота сторожа инварианта #3 НЕ измерена: "
                         f"{guard.get('reason')}")
    elif not guard.get("control_ok"):
        unchecked.append(
            "слепота сторожа НЕ измерена: контрольная сцена (SDK-импорт) им "
            "не поймана — значит проба запустила сторожа неверно, и «не видит "
            "subprocess» ничего не означает")
    elif guard.get("blind_to_subprocess"):
        subprocess_doors = [rel for rel, kind in scan["doors"].items()
                            if kind == "subprocess"]
        findings.append({
            "severity": "CRITICAL", "code": "guard_blind_to_real_door",
            "message": (
                "единственный сторож инварианта #3 (scripts/lint_llm_forbidden.py) "
                "видит ТОЛЬКО импорт SDK: контрольная дверь-SDK в spa_core/risk/ "
                "поймана, дверь-subprocess к бинарю claude в том же каталоге — "
                "НЕТ (0 нарушений). А дверь этой системы именно вторая "
                f"({len(subprocess_doors)} модул(ь/я/ей): "
                f"{', '.join(sorted(subprocess_doors)) or '—'}). "
                "Ограничение §45 сегодня выполняется, но держится оно НЕ "
                "сторожем: вставить вызов claude в risk/execution/monitoring "
                "можно, и ни одна проверка не покраснеет")})

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               UNCHECKED if counts["unchecked"] else "OK")
    doc = _document(now, overall, counts, scan, concentration, llm, {},
                    findings, unchecked, control)
    if write:
        _write(doc, root)
    return doc


def _document(now: dt.datetime, overall: str, counts: dict, scan: dict,
              concentration: dict, llm: dict, _spare: dict,
              findings: list[dict], unchecked: list[str],
              control: dict) -> dict:
    return {
        "schema": "cio_architecture_constraints/v1",
        "generated_at": now.isoformat(),
        "question": ("§45 ТЗ Portfolio CIO «Architecture constraints»: не "
                     "совмещены ли в ОДНОМ модуле пять названных владельцем "
                     "ответственностей (рынок · APY · gas · risk decision · "
                     "подпись), и не является ли LLM финансовым control layer "
                     "— вместе с вопросом, меряет ли это хоть один сторож"),
        "overall": overall,
        "counts": counts,
        "control": control,
        "responsibilities_declared": [
            {"key": k, "owner_wording": w, "measured_as": m}
            for k, w, m in RESPONSIBILITIES],
        "layers_declared": [{"layer": n, "prefixes": list(p)} for n, p in LAYERS],
        "modules_parsed": scan["parsed"],
        "modules_unparsed": scan["unparsed"],
        "concentration": concentration,
        "llm": llm,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: ответственности не разносятся и сторож не "
                     "расширяется — и то и другое money-path и решение "
                     "владельца, а не строка автокарточки"),
    }


def _write(doc: dict, root: str) -> None:
    from spa_core.utils.atomic import atomic_save
    atomic_save(doc, os.path.join(root, REPORT_REL))


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    c = doc["counts"]
    print(f"cio_architecture_constraints: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    if not doc["control"]["passed"]:
        print(f"  [НЕ ИЗМЕРЕНО] положительный контроль не пройден — "
              f"{doc['control']['reason']}")
        return 0
    conc = doc["concentration"]
    print(f"  концентрация: максимум {conc['max']} из {conc['of']}; "
          f"модулей с двумя и более — {len(conc['modules'])}; "
          f"совмещают рынок и подпись — {len(conc['market_and_sign'])}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
