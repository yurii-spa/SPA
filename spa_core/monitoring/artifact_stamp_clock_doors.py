"""Доходит ли инъектированный ``now`` до САМОЙ отметки объявленного артефакта.

Заказ **G97 приказа владельца «Portfolio CIO»**, пункт 3 (поставлен ADR-510).

## Вопрос

Дословно: «Отметка ``generated_at`` есть у каждого артефакта, а инъекция часов —
не у каждого производителя. Выживший показал форму: вердикт от часов не зависит,
поэтому подмена часов проходит все контроли вердикта и врёт только в ВОЗРАСТЕ
артефакта — то есть ровно там, где его потом читает сторож свежести. Перемерить
класс по репозиторию: у скольких производителей ``now`` является входом **до
САМОЙ отметки**, а не только до логики. Мерить дифференциально (подменить
стенные часы и сравнить отметку), а не чтением сигнатур.»

Цена ошибки несимметрична и молчалива. Сторож свежести (``artifact_freshness``,
``manifest_slo``) судит о возрасте артефакта по его отметке. Если отметку ставят
стенные часы, а не переданный моменту ``now``, то герметичный тест такого
производителя зелен (вердикт от часов не зависит), а ВОЗРАСТ — выдумка: «свежо»
и «протухло» становятся свойством календаря машины, а не свойством прогона.

## Почему не чтением сигнатур

``now`` в подписи ``run(root=..., now=None)`` не есть доказательство, что этим
``now`` поставлена отметка. Замер 04.10 на дереве: подпись с ``now`` есть у 103
производителей из 112 — то есть чтение сигнатур ответило бы «класс почти пуст»,
ничего не измерив. Претензия в подписи и поведение отметки суть разные факты,
и ровно на их смешении держался урок ADR-477 (пометка ``injected-clock`` на 51
файле, которую три года не сверял с кодом никто).

## Как меряется — два плеча, ОДИН пин, по процессу на плечо

* **плечо A** — производитель зовётся так, как его зовёт флот: без ``now``.
  Класс ``datetime.datetime`` подменён ДО первого импорта ``spa_core``;
* **плечо B** — то же самое плюс ``now=<якорь>`` в точку инъекции.

Моменты выбраны далёкими друг от друга и от календаря (``2033`` против
``2041``), чтобы отметка сама называла, чьи часы её поставили.

| отметка A | отметка B | исход |
|---|---|---|
| подменённые часы | **якорь** | ``injection_reaches_the_stamp`` |
| подменённые часы | подменённые часы | ``stamp_from_wall_clock`` — **находка** |
| подменённые часы | ни то, ни другое | ``stamp_from_a_third_source`` — **находка** |
| НЕ подменённые часы | — | **НЕ ИЗМЕРЕНО**: у этой двери пин не сработал |

Последняя строка — не формальность, а урок ADR-414: пин ПРОВЕРЯЕТСЯ ЗАМЕРОМ у
двери, а не верой в переданный флаг. Производитель, берущий отметку у
``time.time()`` или у чужого файла, выдаёт себя только здесь — и обязан быть
третьим исходом, а не находкой (инв. #17).

## Третий исход, которого заказ не предполагал

Заказ делил мир на два: «``now`` доходит до отметки» и «доходит только до
логики». Есть третий, и он хуже обоих для читателя: отметка не происходит ни от
переданного момента, ни от подменённых часов — её источник ТРЕТИЙ (отметка
входного файла, ``time.time()``, часы подпроцесса). Такую отметку инъекцией не
закрепить вовсе, и герметичность производителю не вернёт ни один параметр.

## Чего прибор НЕ докладывает (названо вслух)

* ПРАВ ли производитель по существу — прибор судит о происхождении отметки, а
  не о верности отчёта;
* двери на ``time.time()``: пин их не закрывает намеренно (оговорка ADR-404),
  поэтому ответ односторонний — «закрывается этим пином» либо «этим пином не
  закрывается»;
* производителя, которого прибор не умеет привести (нет точки инъекции, импорт
  упал, зов упал, артефакт не написан) — такие НАЗВАНЫ причинами, а не
  сосчитаны нулём;
* артефакт, чей писатель не разрешён по коду (``artifact_io_scan``) либо разрешён
  НЕОДНОЗНАЧНО — это «не измерено», а не «дверей нет».

Коды возврата: **0** — измерено, находок нет · **1** — измерено, находки
названы · **2** — НЕ ИЗМЕРЕНО (причина названа).

ADVISORY. Прибор только ЗОВЁТ и ЧИТАЕТ (``applied=False``): капитал не
двигается, ``POLLED_ADAPTERS``, пороги RiskPolicy v1.0, стоп-кран, живой трек и
``landing/`` не трогаются. Зов идёт ТОЛЬКО в одноразовом дереве — это
проверяется замером (``assert_disposable_tree``), а не доверием к вызывающему:
производители ПИШУТ, и запуск в боевом дереве затёр бы живое состояние.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import collections
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.monitoring import _artifact_stamp_clock_probe as probe
from spa_core.monitoring import artifact_io_scan as io_scan
from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

#: Корень дерева — три уровня вверх от ``spa_core/monitoring/<файл>``.
_ROOT = Path(__file__).resolve().parents[2]

ARTIFACT = "artifact_stamp_clock_doors.json"

#: Что этот модуль ПРОИЗВОДИТ (контракт агента, ADR-154/158).
PRODUCES = (f"data/{ARTIFACT}",)

#: Имя прибора в отчёте — чтобы находку было с кем сверить.
PRODUCER = "spa_core/monitoring/artifact_stamp_clock_doors.py"

#: Подменённые стенные часы и якорь инъекции. Годы РАЗНЫЕ и далеки от календаря:
#: отметка обязана САМА называть, чьи часы её поставили, без арифметики близости.
FAKE_WALL = "2033-05-17T04:07:11+00:00"
ANCHOR = "2041-11-23T19:53:29+00:00"

#: Сколько ждать плечо целиком. Предел на КАЖДЫЙ зов стоит внутри зонда
#: (``probe.CALL_TIMEOUT_S``); этот — страховка от процесса, который не
#: прерывается сигналом вовсе.
ARM_TIMEOUT_S = 2700

#: Такт переизмерения, дней. Предмет (двери в КОДЕ) меняется доставками, а не
#: календарём, а прогон стоит десятки минут — та же развилка и тот же выбор, что
#: у ``python_reader_clock_doors`` (ADR-414). Срок решает ФАЙЛ, а не расписание
#: запуска: иначе «раз в неделю» держалось бы на том, что никто не трогал cron.
MEASUREMENT_TACT_DAYS = 7

#: Что копируется в песочницу. ``data/`` входит НЕ ради удобства: производители
#: читают входы оттуда, и без них половина плеча отвечала бы «вход не прочитан»
#: вместо ответа про отметку. Копия же и есть то, во что они пишут.
SANDBOX_DIRS = ("spa_core", "scripts", "architecture", "data")

#: Метка, которой прибор помечает СВОЮ песочницу. Нужна потому, что признак
#: «пристёгнутое дерево git» для временной копии не выполняется вовсе (у неё нет
#: git), и один он отказал бы безопасной копии. Метку кладёт прибор; подделать её
#: можно только нарочно — то же, что передать ``--allow-live-tree``, и ГЛАВНОЕ
#: дерево она не оправдывает НИКОГДА (проверка идёт раньше метки).
SANDBOX_MARKER = ".spa_stamp_clock_sandbox"

#: Мусор сборки в песочницу не возим: он объёмнее исходников и делает копию
#: медленнее самого замера.
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache",
                                     ".mypy_cache")

# ── исходы (инв. #17: отсутствие наблюдения — ОТДЕЛЬНОЕ значение) ───────────────
REACHES = "injection_reaches_the_stamp"
WALL_CLOCK = "stamp_from_wall_clock"
THIRD_SOURCE = "stamp_from_a_third_source"
NO_DOOR = "no_door_declared"
PRODUCER_UNRESOLVED = "producer_not_resolved"

#: Писателя нашли, и это САМ прибор. Не «писателя нет»: писатель есть и назван,
#: просто звать себя внутри своего же плеча значило бы рекурсию процессов, а не
#: замер. Отдельный исход потому, что «никто не пишет» и «пишу я сам» — разные
#: факты, и слить их значило бы оболгать собственный артефакт.
PRODUCER_IS_SELF = "producer_is_the_instrument_itself"
PRODUCER_AMBIGUOUS = "producer_ambiguous"
UNMEASURED = "unmeasured"

#: Артефакт написан, но отметки в нём НЕТ ни под одним известным именем. Это не
#: «пин не сработал» и не «инъекция не дошла»: сторож свежести читать тут нечего
#: ВООБЩЕ, и смешать это с неудачей пина значило бы обвинить подмену часов в
#: том, чего она не делала. Замер 04.10 нашёл одного такого
#: (`census_consumer_census`), и первая редакция меры назвала его неудачей пина.
NO_STAMP_IN_ARTIFACT = "no_stamp_in_the_artifact"

#: Исходы, которые есть НАХОДКА. ``no_door_declared`` входит: производитель без
#: точки инъекции не может быть герметичен ни при каком вызове.
FINDINGS = (WALL_CLOCK, THIRD_SOURCE, NO_DOOR, NO_STAMP_IN_ARTIFACT)

#: Исходы, которые НЕ ИЗМЕРЕНЫ. Ноль находок при непустом этом множестве —
#: не «чисто»: такой ответ обязан называть, сколько осталось неизмеренным.
NOT_MEASURED = (PRODUCER_UNRESOLVED, PRODUCER_AMBIGUOUS, PRODUCER_IS_SELF,
                UNMEASURED)

#: Модули, которых прибор не зовёт: он сам и его зонд. Зов себя внутри своего же
#: плеча дал бы рекурсию процессов, а не замер.
SELF_MODULES = (
    "spa_core.monitoring.artifact_stamp_clock_doors",
    "spa_core.monitoring._artifact_stamp_clock_probe",
)


# ── население ───────────────────────────────────────────────────────────────────

def declared_artifacts(tree_root: Path) -> Tuple[List[dict], Optional[str]]:
    """Объявленные артефакты конституции (``architecture/manifest.json``).

    Манифест не прочитан ⇒ ``(…, причина)``: населения НЕТ, и это третий исход,
    а не пустой список. Пустой список дал бы ноль дверей, и ноль прочёлся бы
    как ответ.
    """
    path = Path(tree_root) / "architecture" / "manifest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"манифест не прочитан ({path}): {type(exc).__name__}: {exc}"
    rows = observed(doc, "artifacts", kind=list)
    if rows is None:
        return [], f"в манифесте нет списка artifacts ({path})"
    active = [r for r in rows if isinstance(r, dict)
              and str(r.get("status", "active")) == "active" and r.get("path")]
    return active, None


def _py_files(tree_root: Path) -> List[Path]:
    """Код флота без тестов: писателя артефакта ищем среди производителей."""
    out: List[Path] = []
    for rel in ("spa_core", "scripts"):
        for f in (Path(tree_root) / rel).rglob("*.py"):
            name = str(f)
            if "/tests/" in name or f.name.startswith("test_"):
                continue
            out.append(f)
    return out


def writers_by_artifact(tree_root: Path) -> Dict[str, set]:
    """Кто ПИШЕТ каждый артефакт — по коду, через ``artifact_io_scan``.

    Своего разбора записи здесь намеренно НЕТ: сосед уже отвечает на этот
    вопрос (ADR-158) и знает словарь записи флота (``_atomic_write``,
    ``_write_json``, …). Второй разбор был бы второй копией факта и разошёлся бы
    с первым при первой правке.
    """
    writes: Dict[str, set] = collections.defaultdict(set)
    for f in _py_files(tree_root):
        try:
            found = io_scan.scan_file(f)
        except (OSError, SyntaxError, ValueError):
            continue
        for name, kinds in found.items():
            if io_scan.WRITE in kinds:
                writes[name].add(str(f.relative_to(tree_root)))
    return writes


def _zero_arg_callable(fn: ast.AST) -> bool:
    """Можно ли позвать без позиционных аргументов — у ВСЕХ ли есть умолчания."""
    args = fn.args                                      # type: ignore[attr-defined]
    required_pos = len(args.posonlyargs) + len(args.args) - len(args.defaults)
    required_kw = sum(1 for d in args.kw_defaults if d is None)
    return required_pos <= 0 and required_kw == 0


def _params(fn: ast.AST) -> List[str]:
    args = fn.args                                      # type: ignore[attr-defined]
    return [a.arg for a in (args.posonlyargs + args.args + args.kwonlyargs)]


def injection_entry(source: str) -> Optional[str]:
    """Имя точки инъекции модуля: публичная функция верхнего уровня, которую
    можно позвать без аргументов и у которой есть параметр ``now``.

    ``run`` предпочитается прочим НЕ по вкусу, а по замеру: из 101 найденной
    точки 95 зовутся именно так. Порядок выбора детерминирован (сперва ``run``,
    затем по алфавиту), иначе ответ зависел бы от порядка обхода файла.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    names = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        if "now" not in _params(node) or not _zero_arg_callable(node):
            continue
        names.append(node.name)
    if not names:
        return None
    if "run" in names:
        return "run"
    return sorted(names)[0]


def _module_name(rel_path: str) -> str:
    """``spa_core/monitoring/x.py`` → ``spa_core.monitoring.x``."""
    return rel_path[:-3].replace("/", ".")


def population(tree_root: Path) -> Tuple[List[dict], Optional[str]]:
    """Строки населения: артефакт → писатель → точка инъекции.

    Каждая строка уже несёт исход, если мерить нечего: писатель не разрешён,
    разрешён неоднозначно, точки инъекции нет. Это НЕ ноль дверей — это
    названная причина.
    """
    arts, reason = declared_artifacts(tree_root)
    if reason:
        return [], reason
    writes = writers_by_artifact(tree_root)
    rows: List[dict] = []
    for art in arts:
        rel = str(art["path"])
        hits = sorted(writes.get(rel) or writes.get(Path(rel).name) or set())
        mine = [h for h in hits if _module_name(h) in SELF_MODULES]
        hits = [h for h in hits if _module_name(h) not in SELF_MODULES]
        row: dict = {"artifact": rel, "declared_producer": art.get("producer"),
                     "slo_hours": art.get("slo_hours"), "writers": hits,
                     "module": None, "entry": None, "verdict": None,
                     "reason": None}
        if not hits and mine:
            row["verdict"] = PRODUCER_IS_SELF
            row["writers"] = mine
            row["reason"] = ("писатель — сам прибор; звать себя внутри своего же "
                             "плеча значило бы рекурсию процессов, а не замер")
        elif not hits:
            row["verdict"] = PRODUCER_UNRESOLVED
            row["reason"] = "ни один модуль флота не пишет этот путь по коду"
        elif len(hits) > 1:
            row["verdict"] = PRODUCER_AMBIGUOUS
            row["reason"] = ("писателей по коду несколько — какой из них ставит "
                             f"отметку, НЕ ИЗМЕРЕНО: {', '.join(hits)}")
        else:
            module_rel = hits[0]
            row["module"] = _module_name(module_rel)
            try:
                src = (Path(tree_root) / module_rel).read_text(encoding="utf-8")
            except OSError as exc:
                row["verdict"] = UNMEASURED
                row["reason"] = f"писатель не прочитан: {type(exc).__name__}: {exc}"
                rows.append(row)
                continue
            entry = injection_entry(src)
            if entry is None:
                row["verdict"] = NO_DOOR
                row["reason"] = ("у писателя нет публичной точки верхнего уровня, "
                                 "которую можно позвать без аргументов и у которой "
                                 "есть параметр `now` — отметку нечем закрепить")
            else:
                row["entry"] = entry
        rows.append(row)
    return rows, None


# ── одноразовость дерева ────────────────────────────────────────────────────────

def is_disposable_tree(tree_root: Path) -> Tuple[bool, str]:
    """Одноразовое ли это дерево — ЗАМЕР, а не доверие вызывающему.

    Производители ПИШУТ. Прогон в боевом дереве затёр бы живое состояние молча
    и разом — ровно авария цикла #361, только без команды ``git checkout``.
    Признак измерим у git: у ПРИСТЁГНУТОГО дерева (``git worktree``) личный
    ``--git-dir`` не совпадает с общим ``--git-common-dir``, у главного —
    совпадает. Имя каталога признаком НЕ является: оно переименуемо.

    Git не ответил ⇒ ``False`` с названной причиной (fail-CLOSED): «не смог
    проверить» не имеет права читаться как «можно».
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            cwd=str(tree_root), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"git не ответил: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return False, f"git вернул {proc.returncode}: {proc.stderr.strip()[:200]}"
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if len(lines) != 2:
        return False, f"git ответил не двумя строками: {lines}"
    own, common = (os.path.realpath(os.path.join(str(tree_root), p))
                   for p in lines)
    if own == common:
        return False, ("это ГЛАВНОЕ рабочее дерево — производители пишут, и прогон "
                       "здесь затёр бы живое состояние; нужен git worktree")
    return True, f"пристёгнутое дерево: {own} ≠ {common}"


def is_own_sandbox(tree_root: Path) -> bool:
    """Это ли песочница, созданная САМИМ прибором (по его метке)."""
    return (Path(tree_root) / SANDBOX_MARKER).is_file()


def make_sandbox(source: Path, box: Path) -> Path:
    """Скопировать в песочницу ровно то, что нужно замеру, и пометить её.

    Отказ ДО копирования, если песочница совпадает с источником или вложена в
    него: тогда «копия» была бы тем же деревом, и производители писали бы в
    живое состояние — ровно то, от чего песочница и защищает.
    """
    src, dst = Path(source).resolve(), Path(box).resolve()
    if src == dst or str(dst).startswith(str(src) + os.sep) \
            or str(src).startswith(str(dst) + os.sep):
        raise RuntimeError(f"песочница {dst} не изолирует источник {src}")
    if dst.exists() and any(dst.iterdir()):
        raise RuntimeError(f"песочница {dst} уже непуста — чужие байты делают "
                           "вердикт нечитаемым")
    dst.mkdir(parents=True, exist_ok=True)
    for rel in SANDBOX_DIRS:
        origin = src / rel
        if origin.is_dir():
            shutil.copytree(origin, dst / rel, ignore=COPY_IGNORE, symlinks=True)
    (dst / "data").mkdir(parents=True, exist_ok=True)
    (dst / SANDBOX_MARKER).write_text(
        f"песочница прибора {PRODUCER}; источник {src}\n", encoding="utf-8")
    return dst


def assert_disposable_tree(tree_root: Path, *, allow_live: bool = False) -> None:
    """Отказать ДО зова, если дерево не одноразовое. Ничего не возвращает."""
    if allow_live:
        return
    ok, why = is_disposable_tree(Path(tree_root))
    if ok:
        return
    # Своя песочница — вторая принятая форма, и она НЕ оправдывает главного
    # дерева: проверка выше отвечает раньше и отказывает на нём всегда.
    if "ГЛАВНОЕ" not in why and is_own_sandbox(Path(tree_root)):
        return
    raise RuntimeError(f"зов производителей отказан: {why}")


# ── плечи ───────────────────────────────────────────────────────────────────────

def run_arm(plan: List[dict], tree_root: Path, *, inject: bool
            ) -> Tuple[Optional[dict], Optional[str]]:
    """Одно плечо — один процесс, зонд зовётся ПО ПУТИ.

    ``-m`` импортировал бы пакет ``spa_core`` раньше пина, и плечо B стало бы
    копией плеча A — нулевая разность, читаемая как ответ.

    Плечо, умершее на середине, возвращает то, что УСПЕЛО измериться: зонд
    дописывает ответ после каждого модуля. Пустой ответ ⇒ причина названа.
    """
    script = Path(tree_root) / "spa_core" / "monitoring" / Path(probe.__file__).name
    with tempfile.TemporaryDirectory(prefix="spa_g97_arm_") as tmp:
        plan_path = Path(tmp) / "plan.json"
        out = Path(tmp) / "answer.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env[probe.FAKE_WALL_ENV] = FAKE_WALL
        env[probe.ANCHOR_ENV] = ANCHOR
        env[probe.INJECT_ENV] = "1" if inject else "0"
        env[probe.TREE_ENV] = str(tree_root)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tree_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        died = None
        try:
            proc = subprocess.run([sys.executable, str(script), str(plan_path),
                                   str(out)], cwd=str(tree_root), env=env,
                                  capture_output=True, timeout=ARM_TIMEOUT_S)
            if proc.returncode != 0:
                died = (f"зонд вернул {proc.returncode}: "
                        f"{proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
        except subprocess.TimeoutExpired:
            died = f"плечо не уложилось в {ARM_TIMEOUT_S} с"
        if not out.exists():
            return None, died or "зонд не оставил ответа"
        try:
            answer = json.loads(out.read_text(encoding="utf-8"))
        except ValueError as exc:
            return None, f"ответ зонда не разобран: {exc}"
        if died:
            answer["arm_died"] = died
        return answer, None


# ── чьи это часы ────────────────────────────────────────────────────────────────

FAKE = "fake_wall"
ANCH = "anchor"
OTHER = "other"
NONE = "none"


def _parse(value: str) -> Optional[dt.datetime]:
    try:
        moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def which_clock(stamp, fake: str = FAKE_WALL, anchor: str = ANCHOR) -> str:
    """Чьи часы поставили отметку: подменённые, якорь, третий источник, никакие.

    Сравниваются МОМЕНТЫ, а не строки: производитель вправе печатать отметку
    своим форматом (``Z`` вместо ``+00:00``, другой пояс), и равенство текста
    объявило бы одинаковые моменты разными. Число читается как epoch — у
    отметки, снятой ``time.time()``, другого вида нет.
    """
    if stamp is None or str(stamp) == "":
        return NONE
    fake_at, anchor_at = _parse(fake), _parse(anchor)
    moment = _parse(stamp)
    if moment is None:
        try:
            moment = dt.datetime.fromtimestamp(float(stamp), dt.timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return OTHER
    if fake_at is not None and moment == fake_at:
        return FAKE
    if anchor_at is not None and moment == anchor_at:
        return ANCH
    return OTHER


def classify(arm_a: Optional[dict], arm_b: Optional[dict]) -> Tuple[str, str]:
    """Исход одной строки по ДВУМ плечам. Возвращает ``(вердикт, причина)``."""
    if arm_a is None or arm_b is None:
        missing = "A" if arm_a is None else "B"
        return UNMEASURED, f"плечо {missing} не дало строки по этому производителю"
    if arm_a.get("error") and not arm_a.get("wrote_artifact"):
        return UNMEASURED, f"плечо A: {arm_a['error']}"
    if not arm_a.get("wrote_artifact"):
        return UNMEASURED, ("плечо A: производитель не написал артефакт — "
                            "отметку сравнивать не с чем")
    source_a = which_clock(arm_a.get("stamp"))
    if source_a == NONE:
        return NO_STAMP_IN_ARTIFACT, (
            "артефакт написан, но отметки в нём НЕТ ни под одним известным "
            f"именем ({', '.join(probe.STAMP_KEYS)}) — сторожу свежести читать "
            "нечего вообще")
    if source_a != FAKE:
        return UNMEASURED, (
            "у этой двери пин НЕ сработал: отметка плеча A не есть подменённый "
            f"момент (прочитано {arm_a.get('stamp')!r}, ключ "
            f"{arm_a.get('stamp_key')!r}) — часы берутся не у подменяемого класса")
    if not arm_b.get("wrote_artifact"):
        return UNMEASURED, ("плечо B: производитель не написал артефакт "
                            f"({arm_b.get('error') or 'причина не названа'})")
    source_b = which_clock(arm_b.get("stamp"))
    if source_b == ANCH:
        return REACHES, "отметка плеча B есть переданный якорь"
    if source_b == FAKE:
        return WALL_CLOCK, ("инъекция дошла до логики, но НЕ до отметки: отметка "
                            "плеча B — подменённые стенные часы")
    return THIRD_SOURCE, ("отметка плеча B не происходит ни от якоря, ни от "
                          f"подменённых часов (прочитано {arm_b.get('stamp')!r}, "
                          f"ключ {arm_b.get('stamp_key')!r})")


# ── отчёт ───────────────────────────────────────────────────────────────────────

def measure(tree_root: Path, *, limit: Optional[int] = None,
            allow_live: bool = False) -> dict:
    """Замер целиком: население → два плеча → исходы. Возвращает тело отчёта."""
    rows, reason = population(Path(tree_root))
    if reason:
        return {"population_reason": reason, "rows": [], "counts": {},
                "arms": {"a": None, "b": None}}
    assert_disposable_tree(Path(tree_root), allow_live=allow_live)
    plan = [{"module": r["module"], "entry": r["entry"], "artifact": r["artifact"]}
            for r in rows if r["entry"]]
    if limit is not None:
        plan = plan[:limit]
    planned = {item["module"] for item in plan}
    arm_a, why_a = run_arm(plan, Path(tree_root), inject=False) if plan else (None, "план пуст")
    arm_b, why_b = run_arm(plan, Path(tree_root), inject=True) if plan else (None, "план пуст")
    rows_a = (arm_a or {}).get("rows") or {}
    rows_b = (arm_b or {}).get("rows") or {}
    for row in rows:
        if row["verdict"]:
            continue
        if row["module"] not in planned:
            row["verdict"] = UNMEASURED
            row["reason"] = "производитель не вошёл в план этого прогона (--limit)"
            continue
        verdict, why = classify(rows_a.get(row["module"]), rows_b.get(row["module"]))
        row["verdict"], row["reason"] = verdict, why
        row["stamp_key"] = (rows_a.get(row["module"]) or {}).get("stamp_key")
    counts = collections.Counter(r["verdict"] for r in rows)
    return {"population_reason": None, "rows": rows, "counts": dict(counts),
            "arms": {"a": {"door": (arm_a or {}).get("door"),
                           "died": (arm_a or {}).get("arm_died") or why_a,
                           "measured": len(rows_a)},
                     "b": {"door": (arm_b or {}).get("door"),
                           "died": (arm_b or {}).get("arm_died") or why_b,
                           "measured": len(rows_b)}},
            "planned": len(plan)}


def build_report(body: dict, now: dt.datetime) -> dict:
    """Отчёт: тело замера плюс отметка и самоназвание прибора."""
    # `or {}` здесь было бы ровно тем дефектом, который прибор и меряет: пустой
    # словарь вместо отсутствующего блока превратил бы «не измерено» в «находок
    # ноль» (инв. #17). Поймано своим же храповиком на этой самой строке.
    counts = observed(body, "counts", kind=dict)
    findings = (None if counts is None
                else sum(int(counts.get(k, 0)) for k in FINDINGS))
    unmeasured = (None if counts is None
                  else sum(int(counts.get(k, 0)) for k in NOT_MEASURED))
    return {
        "generated_at": now.isoformat(),
        "adr": "ADR-562",
        "order": "G97 п. 3",
        "producer": PRODUCER,
        "applied": False,
        "fake_wall": FAKE_WALL,
        "anchor": ANCHOR,
        "measurement_tact_days": MEASUREMENT_TACT_DAYS,
        "measured_in": body.get("measured_in"),
        "population": len(body.get("rows") or []),
        "planned": body.get("planned"),
        "counts": counts,
        "findings_total": findings,
        "unmeasured_total": unmeasured,
        "population_reason": body.get("population_reason"),
        "arms": body.get("arms"),
        "rows": body.get("rows") or [],
        "not_reported": [
            "ПРАВ ли производитель по существу — мера о происхождении отметки",
            "двери на time.time(): пин их не закрывает намеренно (ADR-404)",
            "производитель, которого прибор не умеет привести — назван причиной",
            "артефакт, чей писатель по коду неоднозначен — НЕ ИЗМЕРЕНО, а не ноль",
        ],
    }


def measurement_due(data_dir: Path, now: dt.datetime) -> Tuple[bool, str]:
    """Пора ли перемерять. Срок решает ФАЙЛ, а не расписание запуска."""
    path = Path(data_dir) / ARTIFACT
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return True, f"артефакта нет или он не прочитан: {type(exc).__name__}"
    stamp = _parse(str(observed(doc, "generated_at", kind=str) or ""))
    if stamp is None:
        return True, "у артефакта нет разбираемой отметки generated_at"
    age_days = (now - stamp).total_seconds() / 86400.0
    if age_days >= MEASUREMENT_TACT_DAYS:
        return True, f"возраст {age_days:.1f} дн при такте {MEASUREMENT_TACT_DAYS}"
    return False, (f"со дня замера прошло {age_days:.1f} дн из "
                   f"{MEASUREMENT_TACT_DAYS}")


def run(root: str = str(_ROOT), now: Optional[dt.datetime] = None, *,
        limit: Optional[int] = None, write: bool = True,
        allow_live: bool = False, if_due: bool = False,
        sandbox: bool = False) -> dict:
    """Замерить и (по умолчанию) записать артефакт. Возвращает отчёт.

    ``sandbox=True`` — замер идёт в КОПИИ дерева, а отчёт ложится в ``data/``
    дерева ``root``. Это единственный способ позвать прибор из боевого дерева,
    и разделение существенно: производители пишут в копию, живое состояние
    получает ровно ОДИН новый файл — отчёт самого прибора.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    tree = Path(root)
    data_dir = tree / "data"
    if if_due:
        due, why = measurement_due(data_dir, now)
        if not due:
            return {"generated_at": now.isoformat(), "skipped": True,
                    "reason": why, "producer": PRODUCER, "applied": False}
    if sandbox:
        with tempfile.TemporaryDirectory(prefix="spa_g97_box_") as tmp:
            box = make_sandbox(tree, Path(tmp) / "tree")
            body = measure(box, limit=limit, allow_live=allow_live)
        body["measured_in"] = "sandbox"
    else:
        body = measure(tree, limit=limit, allow_live=allow_live)
        body["measured_in"] = "tree"
    report = build_report(body, now)
    if write:
        data_dir.mkdir(parents=True, exist_ok=True)
        atomic_save(report, str(data_dir / ARTIFACT))
    return report


def describe(report: dict) -> List[str]:
    """Человекочитаемая сводка. Ноль находок при непустом «не измерено» —
    не «чисто»: строка обязана назвать остаток."""
    if report.get("skipped"):
        return [f"переизмерение не назначено: {report.get('reason')}"]
    if report.get("population_reason"):
        return [f"НЕ ИЗМЕРЕНО: {report['population_reason']}"]
    counts = observed(report, "counts", kind=dict)
    out = [f"производителей объявленных артефактов: {report.get('population')} "
           f"(в плане прогона {report.get('planned')})"]
    if counts is None:
        return out + ["  НЕ ИЗМЕРЕНО: в отчёте нет читаемого блока counts — "
                      "о находках не сказано НИЧЕГО, и это не ноль находок"]
    out.append(
        f"  инъекция ДОХОДИТ до отметки {counts.get(REACHES, 0)} · "
        f"отметку ставят стенные часы {counts.get(WALL_CLOCK, 0)} · "
        f"третий источник {counts.get(THIRD_SOURCE, 0)} · "
        f"двери нет вовсе {counts.get(NO_DOOR, 0)} · "
        f"отметки в артефакте нет {counts.get(NO_STAMP_IN_ARTIFACT, 0)}")
    out.append(
        f"  НЕ ИЗМЕРЕНО {report.get('unmeasured_total')}: писатель не разрешён "
        f"{counts.get(PRODUCER_UNRESOLVED, 0)} · писателей несколько "
        f"{counts.get(PRODUCER_AMBIGUOUS, 0)} · писатель — сам прибор "
        f"{counts.get(PRODUCER_IS_SELF, 0)} · прочее "
        f"{counts.get(UNMEASURED, 0)}")
    for row in report.get("rows") or []:
        if row.get("verdict") in FINDINGS:
            where = row.get("module") or "писатель не разрешён"
            if row.get("entry"):
                where = f"{where}.{row['entry']}"
            out.append(f"  [{row['verdict']}] {row['artifact']} ← {where}: "
                       f"{row.get('reason')}")
    for arm, info in (report.get("arms") or {}).items():
        if isinstance(info, dict) and info.get("died"):
            out.append(f"  ⚠️ плечо {arm.upper()}: {info['died']}")
    out.append("  ADVISORY: прибор только ЗОВЁТ и ЧИТАЕТ (applied=False)")
    return out


def office_section(data_dir: Path, now: dt.datetime) -> List[str]:
    """Секция шага 0-офис: ВТОРОЙ читатель артефакта — его возраст.

    Первый читатель — ступень моста (агент ``com.spa.decision_loop``), она же
    производитель. Эта секция отвечает на другой вопрос: ПРОИЗВЁЛ ли кто-нибудь
    артефакт вообще и не просрочен ли он. Разделение существенно: ступень,
    молчащая по любой причине (упал импорт, отказала одноразовость, умерло
    плечо), из своего собственного доклада не видна — а из возраста файла видна.

    Артефакта нет ⇒ строка НЕ ИЗМЕРЕНО с причиной, а не тишина (fail-CLOSED):
    «никто не мерил» обязано отличаться от «измерено, находок нет».
    """
    path = Path(data_dir) / ARTIFACT
    head = "— отметка артефакта: доходит ли до неё инъекция часов (ADR-562) —"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [head, f"   [НЕ ИЗМЕРЕНО] {path} не прочитан "
                      f"({type(exc).__name__}) — класс не мерил никто; "
                      f"производит ступень моста (com.spa.decision_loop), "
                      f"вручную — `python3 -m "
                      f"{PRODUCER[:-3].replace('/', '.')} --sandbox`"]
    declared = observed(doc, "generated_at", kind=str)
    stamp = None if declared is None else _parse(declared)
    # `or {}` здесь был бы ровно тем дефектом, который прибор и меряет: пустой
    # словарь вместо отсутствующего блока превратил бы «не измерено» в «находок
    # ноль» (инв. #17). Поймано своим же храповиком на этой самой строке.
    counts = observed(doc, "counts", kind=dict)
    out = [head]
    if stamp is None:
        out.append("   [НЕ ИЗМЕРЕНО] у артефакта нет разбираемой отметки "
                   "generated_at — возраст назвать нечем")
    else:
        age_days = (now - stamp).total_seconds() / 86400.0
        overdue = age_days >= MEASUREMENT_TACT_DAYS
        out.append(f"   {'❌ ПРОСРОЧЕН' if overdue else '✅'} замер "
                   f"{age_days:.1f} дн назад при такте {MEASUREMENT_TACT_DAYS} дн"
                   + (" — ступень моста молчит, перемерить "
                      "`--sandbox`" if overdue else ""))
    if counts is None:
        out.append("   [НЕ ИЗМЕРЕНО] в артефакте нет читаемого блока counts — "
                   "о находках не сказано НИЧЕГО, и это не ноль находок")
        return out
    findings = sum(int(counts.get(k, 0)) for k in FINDINGS)
    unmeasured = sum(int(counts.get(k, 0)) for k in NOT_MEASURED)
    out.append(f"   инъекция доходит до отметки {counts.get(REACHES, 0)} · "
               f"находок {findings} (стенные часы {counts.get(WALL_CLOCK, 0)} · "
               f"третий источник {counts.get(THIRD_SOURCE, 0)} · двери нет "
               f"{counts.get(NO_DOOR, 0)} · отметки нет "
               f"{counts.get(NO_STAMP_IN_ARTIFACT, 0)}) · НЕ ИЗМЕРЕНО "
               f"{unmeasured}")
    rows = observed(doc, "rows", kind=list)
    if rows is None:
        out.append("   [НЕ ИЗМЕРЕНО] в артефакте нет читаемого списка rows — "
                   "находки назвать поимённо нечем")
        return out
    for row in rows:
        if isinstance(row, dict) and row.get("verdict") in (
                WALL_CLOCK, THIRD_SOURCE, NO_STAMP_IN_ARTIFACT):
            out.append(f"   [{row['verdict']}] {row.get('artifact')} ← "
                       f"{row.get('module')}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """CLI. 0 — измерено, находок нет · 1 — находки названы · 2 — НЕ ИЗМЕРЕНО."""
    ap = argparse.ArgumentParser(
        description="Доходит ли инъектированный now до САМОЙ отметки артефакта "
                    "(заказ G97 п. 3). Зов только в ОДНОРАЗОВОМ дереве.")
    ap.add_argument("--root", default=str(_ROOT), help="корень дерева прогона")
    ap.add_argument("--limit", type=int, default=None,
                    help="сколько производителей звать (для отладки)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    ap.add_argument("--if-due", action="store_true",
                    help="мерить только если прошёл такт (решает ФАЙЛ)")
    ap.add_argument("--sandbox", action="store_true",
                    help="мерить в КОПИИ дерева, отчёт писать в data/ источника "
                         "— единственный способ зова из боевого дерева")
    ap.add_argument("--allow-live-tree", action="store_true",
                    help="ОСОЗНАННО звать производителей в главном дереве")
    args = ap.parse_args(argv)
    try:
        report = run(root=args.root, limit=args.limit, write=not args.no_write,
                     allow_live=args.allow_live_tree, if_due=args.if_due,
                     sandbox=args.sandbox)
    except RuntimeError as exc:
        sys.stderr.write(f"НЕ ИЗМЕРЕНО: {exc}\n")
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in describe(report):
            print(line)
    if report.get("skipped"):
        return 0
    if report.get("population_reason"):
        return 2
    # Счётчик, которого нет, — не ноль: вердикт «находок нет» на НЕ ИЗМЕРЕННОМ
    # счётчике был бы fail-OPEN, то есть тише красной строки и потому опаснее.
    findings = report.get("findings_total")
    unmeasured = report.get("unmeasured_total")
    if findings is None or unmeasured is None:
        return 2
    if findings > 0:
        return 1
    if unmeasured >= (report.get("population") or 0):
        return 2
    return 0


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
