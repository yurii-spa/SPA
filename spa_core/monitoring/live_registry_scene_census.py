"""Перепись тестов, чья ПРЕДПОСЫЛКА СЦЕНЫ взята из ЖИВОГО реестра проб.

Заказ **G95, п. 2** приказа владельца «Portfolio CIO» (хвост
[ADR-507](../../docs/decisions/ADR-507-the-first-binding-moved-out-of-prose.md)),
самый старый непогашенный пункт ряда на 2026-10-03.

## Вопрос заказа

`.claude/rules/deployment.md` знает ТРИ двери, через которые в тест входит
необъявленное окружение: **календарь** (литеральная дата), **личность процесса**
(литеральный pid), **git-окружение** (имя ветки, глубина клона, наличие плагина).
Заказ называет **четвёртую**: предпосылка сцены, взятая из ЖИВОГО реестра проб
(`PROBES`, `probes_by_s49_criterion`) вместо входа. Замерить, сколько тестов
набора судят о предмете по реестру; метод — дифференциальный, как у pid и
git-окружения: прогнать дважды, во второй раз подменив реестр. Ноль обязан быть
отличим от «искали не той формой», а переход в `skipped` мерить наравне с
`failed`.

## Почему эта дверь опаснее трёх первых

У календаря и у pid вред ГРОМКИЙ: тест краснеет на чужой машине. У реестра вред
ТИХИЙ. Реестр — словарь, и утверждение «у каждой зарегистрированной пробы есть
X» на ПУСТОМ реестре становится утверждением обо всём пустом множестве, то есть
истинным. Тест обходит ноль проб и печатает `passed`. Это дословный урок
`pyflakes` из того же правила: отсутствие предмета дало ЧИСЛО 0, сторож
позеленел на `0 <= 36` и ничего не измерил — fail-OPEN тише красного, поэтому
опаснее.

Реестр при этом живой по построению: `.claude/rules/acceptance.md` требует
регистрировать новую пробу вместе с тестом, и за одиннадцать циклов ряда он
вырос с 11 критериев §49 до 33 проб. Дверь не гипотетическая — она открывается
каждым циклом, который делает свою работу правильно.

## Подмена: ДВЕ стороны, потому что дрейф реестра двусторонний

| прогон | что подменено | какой вред ловит |
|---|---|---|
| база | ничего; реестр ЗАПИСЫВАЕТ каждое чтение | достижимость: дошёл ли тест до реестра ВООБЩЕ |
| реестр **ПУСТ** | `PROBES` опорожнён | тихий: утверждение о членах стало утверждением о пустоте |
| реестр **ВЫРОС** | добавлена проба со своим критерием §49 | дрейф состава: предмет теста есть состав реестра СЕГОДНЯ |

**Опорожнение — ВЫБОР, а не свойство класса**, и цена названа: это предел
правдоподобного дрейфа (проба теряет регистрацию), взятый ради максимальной
чувствительности к пустоте. Снятие ОДНОЙ пробы ловило бы тот же класс слабее и
зависело бы от того, какую снять.

## Достижимость — отдельный вопрос, и ею ноль отличается от «не той формы»

Статическая сеть ловит ИМЯ, а имя не есть чтение (память: «token in the file is
not a reader»). Поэтому реестр базового прогона — не обычный `dict`, а словарь,
который записывает каждое чтение и приписывает его текущему тесту. Тест, чьё имя
сеть нашла, а прогон чтения не увидел, получает `not_reached` и в население
класса НЕ входит. Без этой оси «находок ноль» было бы неотличимо от «искали не
той формой» — ровно то, что заказ запретил.

**Чтение на СБОРЕ приписывается всем тестам файла.** `@parametrize("n",
sorted(PROBES))` читает реестр при импорте модуля, то есть до первого теста; не
приписать это чтение никому значило бы объявить самую чистую форму дефекта
отсутствующей.

## Шесть исходов, и они различимы (инв. #17)

| вердикт | что он значит | находка |
|---|---|---|
| `not_reached` | за прогон реестр не прочитан ни разу ⇒ вне класса | нет |
| `breaks_on_substitution` | подмена РОНЯЕТ тест ⇒ реестр несущий, сказано громко | нет |
| `disappears_on_substitution` | подмена уводит в `skipped`: не краснеет и не проходит — ИСЧЕЗАЕТ | **да** |
| `vacuous_over_members` | кадр ТЕСТА перечисляет реестр, и на пустом вердикт не меняется ⇒ утверждения над ничем | **да** |
| `claim_independent_of_members` | из кадра теста чтения только ПОИМЁННЫЕ ⇒ предмет в реестре не лежит | нет |
| `unmeasured` | на базе красно/`skipped`/нет в записи ⇒ предпосылка не обеспечена | нет (громко) |

`vacuous_over_members` и `claim_independent_of_members` разделены НАМЕРЕННО:
слить их в одно «зелен на пустом реестре» значило бы предъявить одну цену вместо
двух и починить не то. Тест, спросивший `PROBES.get("несуществующее имя")` и
проверяющий ОТКАЗ, на пустом реестре зелен по делу; тест, обошедший `PROBES.items()`
и ничего не нашедший, — нет. Различает их ФОРМА чтения И ЕГО КАДР, записанные
прогоном, а не догадка о намерении.

**Кадр здесь не украшение, а разница между замером и догадкой.** Первая редакция
различала только форму — и `validate_spec`, собирая ТЕКСТ ОТКАЗА
(`', '.join(sorted(PROBES))`), делала перечисляющее чтение ВНУТРИ себя. Четыре
теста, честно проверяющих отказ поимённо (ADR-333, «проба не проходит
подстрокой»), попали бы в находки за цикл, которого не писали. Поэтому
записывается ещё и кадр: `test` · `registry` · `other`.

## Перепись ничего не чинит

`applied=False`. Найденный тест — предмет своей карточки, а не прицепа (инв. #16).
Храповика нет НАМЕРЕННО: заказ велит сперва назвать население числом, и база с
ложными срабатываниями учит дописывать в неё (тот же выбор и та же причина, что
у pid и у имени ветки).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - путь импорта
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

VERDICT_NOT_REACHED = "not_reached"
VERDICT_BREAKS = "breaks_on_substitution"
VERDICT_DISAPPEARS = "disappears_on_substitution"
VERDICT_VACUOUS = "vacuous_over_members"
VERDICT_INDEPENDENT = "claim_independent_of_members"
VERDICT_UNMEASURED = "unmeasured"

ALL_VERDICTS = (VERDICT_NOT_REACHED, VERDICT_BREAKS, VERDICT_DISAPPEARS,
                VERDICT_VACUOUS, VERDICT_INDEPENDENT, VERDICT_UNMEASURED)

#: Вердикты, которые читатель обязан увидеть как НАХОДКУ (ненулевой код возврата).
FINDING_VERDICTS = (VERDICT_VACUOUS, VERDICT_DISAPPEARS)

#: Исходы прогона, считающиеся КРАСНЫМ. `skipped` сюда намеренно НЕ входит —
#: он мерится отдельным вердиктом (урок #465).
RED_OUTCOMES = ("failed", "error")

#: Режимы прогона. `record` — база; остальные подменяют реестр.
MODE_RECORD = "record"
MODE_EMPTY = "empty"
MODE_GROWN = "grown"
MODES = (MODE_RECORD, MODE_EMPTY, MODE_GROWN)

DEFAULT_MODULE = "spa_core.monitoring.card_acceptance"
DEFAULT_TEST_DIRS = ("spa_core/tests", "scripts/tests", "tests")
ARTIFACT = "live_registry_scene_census.json"

#: Имена ЖИВОГО реестра, названные заказом.
REGISTRY_NAMES = ("PROBES", "probes_by_s49_criterion")

#: Помощники ТОГО ЖЕ модуля, читающие реестр внутри себя. Шаг в помощника
#: несущий: `run_probe("имя")` спрашивает `PROBES.get(...)`, и считать такой
#: тест не читающим реестр значило бы объявить настоящего читателя
#: отсутствующим (память: «token in the file is not a reader»).
REGISTRY_HELPERS = ("run_probe", "validate_spec")

#: Синтетическая проба прогона «реестр ВЫРОС». Имя заведомо не из дерева.
SYNTHETIC_PROBE = "lrs_synthetic_probe_g95_p2"
SYNTHETIC_CRITERION = "Synthetic criterion (замер G95 п. 2)"

#: Формы чтения, ПЕРЕЧИСЛЯЮЩИЕ реестр. Именно они делают утверждение о членах
#: утверждением о пустоте, когда реестр пуст.
ENUMERATING_READS = ("iter", "keys", "items", "values", "len")

NOT_REPORTED = (
    "ТРОГАЕТ ли тест предмет пробы на самом деле (чтение реестра есть "
    "достижимость, а не исполнение предмета)",
    "чтение держателем ПРЕЖНЕЙ ссылки (`from ... import PROBES` до подключения "
    "плагина): содержимое ему подменено, но его чтения не записываются",
    "реестр, собранный в рантайме по имени из строки",
    "правдоподобность ИМЕННО опорожнения как дрейфа (это назван ВЫБОР предела)",
    "тесты вне четырёх предписанных каталогов",
    "чтение, сделанное из кадра third-party (`other`): кадр записан, но судить о "
    "его намерении прибор не берётся",
)

RU = {
    VERDICT_NOT_REACHED: "реестр за прогон не прочитан ни разу (вне класса)",
    VERDICT_BREAKS: "подмена роняет тест — реестр несущий и назван громко",
    VERDICT_DISAPPEARS: "подмена уводит тест в skipped — он ИСЧЕЗАЕТ",
    VERDICT_VACUOUS: "перечисляет реестр и зелен на ПУСТОМ — утверждения над ничем",
    VERDICT_INDEPENDENT: "чтения поимённые, вердикт от состава не зависит",
    VERDICT_UNMEASURED: "предпосылка не обеспечена (на базе красно/skipped/нет записи)",
}


class Unmeasured(RuntimeError):
    """Замер не состоялся, и причина названа. Третий исход, а не ноль."""


# ── плагин прогона: подмена реестра + запись исхода и чтений ─────────────────
#
# Плагин кладётся отдельным файлом и подключается `-p lrs_plugin`. Содержимое
# подменяется ДВУМЯ способами разом: модульный атрибут перевешивается на
# записывающий словарь, а ПРЕЖНИЙ объект правится на месте — держатель старой
# ссылки обязан видеть ТО ЖЕ содержимое, иначе подмена была бы половинной
# (урок #453: «половина инъекции» — та же бомба).
_PLUGIN_SRC = '''\
"""Служебный плагин переписи live_registry_scene. Тесты не правит."""
import json
import os
import sys
import sys as _sys

_OUT = os.environ["LRS_OUT"]
_MODE = os.environ["LRS_MODE"]
_MOD = os.environ["LRS_MODULE"]
_SYNTH = os.environ["LRS_SYNTH_PROBE"]
_SYNTH_CRIT = os.environ["LRS_SYNTH_CRITERION"]

_state = {}
_per_test = {}
_per_file = {}
_PLUGIN_FILE = __file__


def _caller_site():
    """Чей кадр сделал чтение: ТЕСТ или сам реестр.

    Без этой оси перечисляющее чтение, сделанное внутри `validate_spec` ради
    ТЕКСТА ОТКАЗА (`', '.join(sorted(PROBES))`), выглядело бы как цикл теста по
    членам реестра — и тест, честно проверяющий отказ поимённо, попал бы в
    находки. Разница между замером и догадкой здесь ровно одна: кадр.
    """
    frame = _sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        if filename != _PLUGIN_FILE:
            base = os.path.basename(filename)
            if os.sep + "tests" + os.sep in filename or base.startswith("test_"):
                return "test"
            if base == "card_acceptance.py":
                return "registry"
            return "other"
        frame = frame.f_back
    return "unknown"


def _note(what):
    what = "%s@%s" % (what, _caller_site())
    nodeid = _state.get("nodeid")
    if nodeid:
        _per_test.setdefault(nodeid, set()).add(what)
        return
    collected = _state.get("collect")
    if collected:
        _per_file.setdefault(collected, set()).add(what)


class _RecordingProbes(dict):
    """Реестр, записывающий КАЖДОЕ чтение. Поведение dict не меняет."""

    def __getitem__(self, key):
        _note("getitem:%s" % (key,))
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        _note("get:%s" % (key,))
        return dict.get(self, key, default)

    def __contains__(self, key):
        _note("contains:%s" % (key,))
        return dict.__contains__(self, key)

    def __iter__(self):
        _note("iter")
        return dict.__iter__(self)

    def keys(self):
        _note("keys")
        return dict.keys(self)

    def items(self):
        _note("items")
        return dict.items(self)

    def values(self):
        _note("values")
        return dict.values(self)

    def __len__(self):
        _note("len")
        return dict.__len__(self)


def _synthetic_probe(arg=None):
    return ("satisfied", "синтетическая проба замера G95 п. 2 — ничего не измеряет")


_synthetic_probe.s49_criterion = _SYNTH_CRIT


def pytest_configure(config):
    __import__(_MOD)
    module = sys.modules[_MOD]
    content = dict(module.PROBES)
    if _MODE == "empty":
        content = {}
    elif _MODE == "grown":
        content[_SYNTH] = _synthetic_probe
    previous = module.PROBES
    previous.clear()
    previous.update(content)
    module.PROBES = _RecordingProbes(content)


def pytest_collectstart(collector):
    nodeid = getattr(collector, "nodeid", "") or ""
    if nodeid.endswith(".py"):
        _state["collect"] = nodeid


def pytest_collectreport(report):
    """Файл, не СОБРАВШИЙСЯ под подменой, — громчайшая форма класса.

    Без этой записи его тесты просто исчезли бы из прогона, и читатель прочёл
    бы «теста нет в записи» как «не измерено», тогда как измерено было самое
    сильное: реестр читается на ИМПОРТЕ, и подмена рвёт сбор.
    """
    if not report.failed:
        return
    nodeid = getattr(report, "nodeid", "") or ""
    reason = str(getattr(report, "longrepr", ""))[-300:]
    with open(_OUT, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "collect_error", "path": nodeid.split("::")[0],
                                 "reason": reason}, ensure_ascii=False) + "\\n")


def pytest_runtest_logstart(nodeid, location):
    _state["collect"] = None
    _state["nodeid"] = nodeid
    _state["outcome"] = "passed"


def pytest_runtest_logreport(report):
    if report.outcome == "failed":
        _state["outcome"] = "failed"
    elif report.outcome == "skipped" and _state.get("outcome") == "passed":
        _state["outcome"] = "skipped"


def pytest_runtest_logfinish(nodeid, location):
    path = nodeid.split("::")[0]
    reads = set(_per_test.get(nodeid, ())) | set(_per_file.get(path, ()))
    record = {"kind": "test", "nodeid": nodeid,
              "outcome": _state.get("outcome", "passed"), "reads": sorted(reads)}
    with open(_OUT, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\\n")
    _state["nodeid"] = None
'''


def _stamp(now: Optional[dt.datetime] = None) -> str:
    moment = now or dt.datetime.now(dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


# ── статическое население: ДВЕ независимые сети ──────────────────────────────

def _ast_forms(source: str) -> Dict[str, List[str]]:
    """Какими ФОРМАМИ файл называет реестр. Пусто ⇒ форма реестр не нашла."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: Dict[str, Set[str]] = {}

    def add(kind: str, name: str) -> None:
        found.setdefault(kind, set()).add(name)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "card_acceptance" in node.module:
            for alias in node.names:
                if alias.name in REGISTRY_NAMES:
                    add("direct_import", alias.name)
                elif alias.name in REGISTRY_HELPERS:
                    add("helper_import", alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "card_acceptance" in alias.name:
                    add("module_import", alias.name)
        elif isinstance(node, ast.Attribute):
            if node.attr in REGISTRY_NAMES:
                add("direct_attribute", node.attr)
            elif node.attr in REGISTRY_HELPERS:
                add("helper_attribute", node.attr)
        elif isinstance(node, ast.Name):
            if node.id in REGISTRY_NAMES:
                add("direct_name", node.id)
            elif node.id in REGISTRY_HELPERS:
                add("helper_name", node.id)
    return {kind: sorted(names) for kind, names in sorted(found.items())}


def discover_population(root: Path, test_dirs: Sequence[str] = DEFAULT_TEST_DIRS) -> dict:
    """Статическое население ДВУМЯ сетями: текстовой и по форме (AST).

    Союз сетей и есть население прогона. Расхождение сетей ПЕЧАТАЕТСЯ, а не
    сглаживается: сеть, нашедшая меньше, и есть «не та форма», против которой
    заказ требует защиты, и увидеть это можно только рядом со второй сетью.
    """
    seen = 0
    textual: Set[str] = set()
    by_form: Set[str] = set()
    forms: Dict[str, Dict[str, List[str]]] = {}
    for folder in test_dirs:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            seen += 1
            rel = str(path.relative_to(root))
            if "card_acceptance" in source or any(n in source for n in REGISTRY_NAMES):
                textual.add(rel)
            found = _ast_forms(source)
            if found:
                by_form.add(rel)
                forms[rel] = found
    if not seen:
        raise Unmeasured(
            "ни одного файла тестов не прочитано в каталогах "
            f"{', '.join(test_dirs)} — население НЕ ИЗМЕРЕНО")
    return {
        "test_files_seen": seen,
        "net_textual": len(textual),
        "net_by_form": len(by_form),
        "only_textual": sorted(textual - by_form),
        "only_by_form": sorted(by_form - textual),
        "population": sorted(textual | by_form),
        "forms": forms,
    }


# ── прогон ───────────────────────────────────────────────────────────────────

def _run_pytest(root: Path, files: Sequence[str], *, mode: str, out: Path,
                module: str = DEFAULT_MODULE,
                timeout: int = 2400) -> dict:
    plugin_dir = out.parent / f"lrs_plugin_{mode}"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "lrs_plugin.py").write_text(_PLUGIN_SRC, encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "LRS_OUT": str(out),
        "LRS_MODE": mode,
        "LRS_MODULE": module,
        "LRS_SYNTH_PROBE": SYNTHETIC_PROBE,
        "LRS_SYNTH_CRITERION": SYNTHETIC_CRITERION,
        "SPA_ENV": "ci",
        "PYTHONHASHSEED": "0",
        # Корень дерева в пути — ПОЯС СВЕРХ ПОДТЯЖЕК, и это сказано вслух:
        # мутационный прогон #763 (41 мутант, 40 убито) оставил ровно этот
        # мутант живым, потому что `python -m pytest` при `cwd=root` кладёт
        # корень в `sys.path` сам. Строка оставлена осознанно — она держит
        # случай, когда бегуна позовут НЕ через `-m`, — но выдавать её за
        # наблюдаемую нельзя: единственный выживший мутант прибора живёт здесь.
        "PYTHONPATH": os.pathsep.join(
            [str(plugin_dir), str(root), env.get("PYTHONPATH", "")]).rstrip(os.pathsep),
    })
    # `--basetemp` не украшение: прогон идёт трижды, и временные каталоги
    # фикстур копились бы в общем корне.
    basetemp = out.parent / f"bt_{mode}"
    # `--continue-on-collection-errors` обязателен, а не удобство: файл, читающий
    # реестр на ИМПОРТЕ, под подменой не собирается, и по умолчанию pytest обрывает
    # СЕССИЮ целиком. Первая редакция замера на этом и встала: один такой файл
    # (`test_named_cards_closed_at_origin_probe.py`) обнулял весь прогон, то есть
    # самая сильная находка класса делала класс НЕИЗМЕРИМЫМ.
    cmd = [sys.executable, "-m", "pytest", *files, "-q", "--tb=no",
           "-p", "no:randomly", "-p", "lrs_plugin", "--basetemp", str(basetemp),
           "--continue-on-collection-errors"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env, text=True,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Unmeasured(f"прогон режима {mode!r} не уложился в {timeout} с")
    records, collect_errors = _read_records(out)
    if not records:
        tail = (proc.stdout or proc.stderr or "")[-600:]
        raise Unmeasured(
            f"режим {mode!r} не записал ни одного исхода (код {proc.returncode}): {tail}")
    return {"mode": mode, "returncode": proc.returncode, "records": records,
            "collect_errors": collect_errors,
            "stdout_tail": (proc.stdout or "")[-400:]}


def _read_records(path: Path) -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Разобрать запись прогона на ДВА рода: исходы тестов и ошибки СБОРА.

    Два рода, а не один: файл, не собравшийся под подменой, не даёт исходов
    вовсе, и его тесты иначе выглядели бы как «нет в записи» — то есть как
    «не измерено» там, где измерено самое сильное.
    """
    tests: Dict[str, dict] = {}
    collect_errors: Dict[str, str] = {}
    if not path.exists():
        return tests, collect_errors
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") == "collect_error":
            where = record.get("path")
            if isinstance(where, str):
                collect_errors[where] = str(record.get("reason") or "")
            continue
        nodeid = record.get("nodeid")
        if isinstance(nodeid, str):
            tests[nodeid] = record
    return tests, collect_errors


def _parse_read(read: str) -> Tuple[str, str]:
    """``"iter@test"`` → ``("iter", "test")``. Без кадра — ``"unknown"``."""
    what, sep, site = read.rpartition("@")
    if not sep:
        return read, "unknown"
    return what, site


def _registry_size(module: str = DEFAULT_MODULE) -> Optional[int]:
    """Сколько проб в ЖИВОМ реестре. Не прочитан ⇒ ``None``, а не нуль (инв. #17).

    Нуль здесь был бы ровно тем дефектом, который прибор ищет: «реестр пуст» и
    «реестр не прочитан» — разные положения дел, и сливать их нельзя даже в
    служебном поле собственного доклада.
    """
    try:
        __import__(module)
        return len(sys.modules[module].PROBES)
    except Exception:  # pragma: no cover - модуль недоступен
        return None


def classify_test(*, base: Optional[dict], empty: Optional[dict],
                  grown: Optional[dict],
                  collect_failed: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """Вердикт одного теста по трём прогонам. Шесть исходов, все различимы.

    ``collect_failed`` — режим → причина, если ФАЙЛ теста не собрался в этом
    режиме. Разбирается РАНЬШЕ отсутствия записи: тест, исчезнувший из прогона
    потому, что его модуль не импортируется под подменой, измерен, а не пропущен.
    """
    collect_failed = collect_failed or {}
    if base is None:
        if MODE_RECORD in collect_failed:
            return VERDICT_UNMEASURED, (
                "файл не собрался уже на БАЗЕ — предпосылка не обеспечена: "
                + collect_failed[MODE_RECORD][-160:])
        return VERDICT_UNMEASURED, "теста нет в записи базового прогона"
    outcome = base.get("outcome")
    if outcome in RED_OUTCOMES:
        return VERDICT_UNMEASURED, f"на базе {outcome} — предпосылка не обеспечена"
    if outcome == "skipped":
        return VERDICT_UNMEASURED, "на базе skipped — тест не исполнялся"
    broke_collection = sorted(m for m in (MODE_EMPTY, MODE_GROWN) if m in collect_failed)
    if broke_collection:
        return VERDICT_BREAKS, (
            f"файл не СОБИРАЕТСЯ под подменой ({', '.join(broke_collection)}): реестр "
            "читается на ИМПОРТЕ модуля — громчайшая форма несущего реестра")
    reads = list(base.get("reads") or ())
    if not reads:
        return VERDICT_NOT_REACHED, "реестр за прогон не прочитан ни разу"
    if empty is None or grown is None:
        missing = "пустого" if empty is None else "выросшего"
        return VERDICT_UNMEASURED, f"теста нет в записи прогона с {missing} реестром"
    substituted = {MODE_EMPTY: empty.get("outcome"), MODE_GROWN: grown.get("outcome")}
    red = sorted(m for m, o in substituted.items() if o in RED_OUTCOMES)
    if red:
        return VERDICT_BREAKS, f"роняется подменой: {', '.join(red)}"
    gone = sorted(m for m, o in substituted.items() if o == "skipped")
    if gone:
        return VERDICT_DISAPPEARS, (
            f"подмена уводит в skipped: {', '.join(gone)} — тест не краснеет и не проходит")
    parsed = [_parse_read(r) for r in reads]
    by_test = sorted({what for what, site in parsed
                      if what in ENUMERATING_READS and site == "test"})
    if by_test:
        return VERDICT_VACUOUS, (
            f"кадр ТЕСТА перечисляет реестр ({', '.join(by_test)}) и на ПУСТОМ "
            "реестре вердикт не меняется — утверждения прошли над пустым множеством")
    by_registry = sorted({what for what, site in parsed
                          if what in ENUMERATING_READS and site != "test"})
    pointed = sorted({what.split(":", 1)[0] for what, _ in parsed
                      if what not in ENUMERATING_READS})
    detail = (f"чтения из кадра теста поимённые ({', '.join(pointed) or 'нет'}) — "
              "вердикт от состава реестра не зависит")
    if by_registry:
        detail += (f"; перечисляющее чтение ({', '.join(by_registry)}) сделал САМ реестр "
                   "(например текст отказа `validate_spec`), а не тест")
    return VERDICT_INDEPENDENT, detail


def summarise(rows: Sequence[dict]) -> Dict[str, int]:
    counts = {verdict: 0 for verdict in ALL_VERDICTS}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return counts


def measure(root: Optional[Path] = None, *, test_dirs: Sequence[str] = DEFAULT_TEST_DIRS,
            module: str = DEFAULT_MODULE, workdir: Optional[Path] = None,
            timeout: int = 2400, now: Optional[dt.datetime] = None) -> dict:
    """Полный замер: население двумя сетями + три прогона + вердикты."""
    tree = Path(root) if root else _REPO_ROOT
    static = discover_population(tree, test_dirs)
    files = static["population"]
    if not files:
        raise Unmeasured(
            "обе сети нашли НОЛЬ файлов, называющих реестр — это «искали не той "
            "формой», а не отсутствие класса")
    with tempfile.TemporaryDirectory(dir=str(workdir) if workdir else None) as tmp:
        scratch = Path(tmp)
        runs = {
            mode: _run_pytest(tree, files, mode=mode, out=scratch / f"{mode}.jsonl",
                              module=module, timeout=timeout)
            for mode in MODES
        }
    base, empty, grown = (runs[m]["records"] for m in MODES)
    collect_by_mode = {m: (runs[m].get("collect_errors") or {}) for m in MODES}
    rows: List[dict] = []
    for nodeid in sorted(set(base) | set(empty) | set(grown)):
        path = nodeid.split("::")[0]
        failed_collection = {m: errs[path] for m, errs in collect_by_mode.items()
                             if path in errs}
        verdict, detail = classify_test(base=base.get(nodeid), empty=empty.get(nodeid),
                                        grown=grown.get(nodeid),
                                        collect_failed=failed_collection)
        rows.append({"nodeid": nodeid, "verdict": verdict, "detail": detail,
                     "reads": list((base.get(nodeid) or {}).get("reads") or ()),
                     "outcomes": {m: (r.get(nodeid) or {}).get("outcome")
                                  for m, r in zip(MODES, (base, empty, grown))}})
    counts = summarise(rows)
    findings = [row for row in rows if row["verdict"] in FINDING_VERDICTS]
    reached = sum(counts[v] for v in ALL_VERDICTS
                  if v not in (VERDICT_NOT_REACHED, VERDICT_UNMEASURED))
    return {
        "generated_at": _stamp(now),
        "order": "G95 п. 2 (хвост ADR-507)",
        "applied": False,
        "registry": {"module": module, "names": list(REGISTRY_NAMES),
                     "helpers": list(REGISTRY_HELPERS),
                     "probes_registered": _registry_size(module)},
        "static": {k: v for k, v in static.items() if k != "forms"},
        "forms": static["forms"],
        "tests_recorded": len(rows),
        "reached_registry": reached,
        "counts": counts,
        "rows": rows,
        "findings": [{k: row[k] for k in ("nodeid", "verdict", "detail")}
                     for row in findings],
        "returncodes": {m: runs[m]["returncode"] for m in MODES},
        "collect_errors": {m: sorted(errs) for m, errs in collect_by_mode.items()},
        "not_reported": list(NOT_REPORTED),
    }


def report(doc: dict, max_rows: int = 8) -> list:
    # `doc.get("counts") or {}` склеивало бы «сводки нет» с «сводка пуста», и
    # печатало бы нули там, где не измерено ничего (инв. #17). Прибор, который
    # ищет ровно такую подстановку у других, не вправе носить её сам.
    counts = observed(doc, "counts", kind=dict)
    static = observed(doc, "static", kind=dict)
    if counts is None or static is None:
        absent = "counts" if counts is None else "static"
        return [f"предпосылка сцены из ЖИВОГО реестра проб: НЕ ИЗМЕРЕНО — "
                f"в замере нет поля {absent!r}",
                "  про тесты, судящие о предмете по реестру, НЕ СКАЗАНО НИЧЕГО"]
    lines = [
        f"предпосылка сцены из ЖИВОГО реестра проб (заказ {doc.get('order')}): "
        f"тестов записано {doc.get('tests_recorded')} · дошли до реестра "
        f"{doc.get('reached_registry')} · НАХОДОК {len(doc.get('findings') or [])}",
        "  сети населения: текстовая {t} · по форме {f} · союз {u}"
        " (расхождение ПЕЧАТАЕТСЯ: сеть, нашедшая меньше, и есть «не та форма»)".format(
            t=static.get("net_textual"), f=static.get("net_by_form"),
            u=len(static.get("population") or [])),
        "  " + " · ".join(f"{v} {counts.get(v, 0)}" for v in ALL_VERDICTS),
    ]
    only_t, only_f = static.get("only_textual") or [], static.get("only_by_form") or []
    if only_t or only_f:
        lines.append(f"  нашла только текстовая: {len(only_t)} · только форма: {len(only_f)}")
    for row in (doc.get("rows") or []):
        if row["verdict"] in FINDING_VERDICTS:
            lines.append(f"  [{row['verdict']}] {row['nodeid']} — {row['detail']}")
    shown = len([r for r in (doc.get("rows") or []) if r["verdict"] in FINDING_VERDICTS])
    if shown > max_rows:
        lines = lines[: 4 + max_rows] + [f"  … ещё {shown - max_rows} находок(и) того же вида"]
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc.get("not_reported") or []))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False) и тесты не правит")
    return lines


def format_report(doc: dict, max_rows: int = 8) -> list:
    return ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="перепись тестов, чья предпосылка сцены взята из живого реестра проб")
    parser.add_argument("--root", default=None, help="корень дерева (по умолчанию — своё)")
    parser.add_argument("--out", default=None, help="куда записать артефакт")
    parser.add_argument("--workdir", default=None, help="корень для временных каталогов")
    parser.add_argument("--module", default=DEFAULT_MODULE,
                        help="модуль, несущий реестр (по умолчанию живой card_acceptance)")
    parser.add_argument("--test-dirs", nargs="+", default=list(DEFAULT_TEST_DIRS),
                        help="каталоги тестов (по умолчанию предписанные)")
    parser.add_argument("--timeout", type=int, default=2400, help="предел одного прогона, с")
    parser.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = parser.parse_args(argv)
    try:
        doc = measure(Path(args.root) if args.root else None,
                      test_dirs=tuple(args.test_dirs), module=args.module,
                      workdir=Path(args.workdir) if args.workdir else None,
                      timeout=args.timeout)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}")
        print("  про предпосылку сцены из живого реестра НЕ СКАЗАНО НИЧЕГО")
        return 2
    if args.out:
        atomic_save(doc, str(args.out))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc):
            print(line)
    return 1 if doc.get("findings") else 0


if __name__ == "__main__":
    raise SystemExit(main())
