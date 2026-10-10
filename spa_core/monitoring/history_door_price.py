"""Откуда ступень моста берёт ИСТОРИЮ: три двери и цена каждой, измеренная исходом.

**Заказ G112 п. 1 (ADR-538), дословно:**

> **На боевом хосте вопрос «списана или потеряна» не задаётся, и это НЕ свойство
> прибора.** Ступень моста работает из обрезанного дерева, поэтому шесть координат
> вечно будут `absent_retirement_unmeasured`. Полный клон на хосте ЕСТЬ
> (`~/Documents/SPA_mirror`, ADR-152), но путь к нему host-specific, и вписывать его
> в модуль нельзя. Решить, откуда ступень берёт историю (объявление в манифесте ·
> переменная окружения · глубина клона самого дерева), — отдельным циклом, с замером
> цены каждого варианта.

## Вред НЕ в том, что шесть строк помечены «не измерено»

Он в том, что ГЛАВНОЕ число соседа от слепой двери становится НУЛЁМ. Перепись дублей
(`duplicate_subject_census`) существует ради одного ответа: сколько координат работы
не доехало до базы. Замер 10.10 на живом журнале (3567 объявленных координат):

| число | через дверь ступени (обрезанное дерево) | через полный клон |
|---|---|---|
| `lost_coordinates` | **0** | **5** |
| `sessions_on_lost_coordinates` | **0** | **5** |
| `subjects_on_lost_coordinates` | **0** | **1** |
| `retired_at_base` | 0 | 1 |
| `retirement_unmeasured` | **6** | **0** |

Население двери в обоих замерах одно и то же — шесть. Слепая дверь не теряет строки,
она ПЕРЕКЛАДЫВАЕТ их из «потеряно» в «не измерено», и наружу выходит ноль. Ноль
читается как «чисто»: ровно тот дефект, против которого написан инв. #17, только
наизнанку — третий исход честно объявлен внутри и МОЛЧА обнуляет заголовок снаружи.
Пятая из этих координат — настоящее списание (`scripts/day30_review.py`, удалена
коммитом `d45cb4a3c` 19.08), и выдать её за потерю было бы симметричной ложью: именно
поэтому сосед отказывается судить из обрезанного дерева, и отказ его ВЕРЕН.

## Три двери заказа, и цена у них РАЗНОРОДНАЯ

Цена здесь не одно число: доступность, ответ, байты, задержка и **наблюдаемость** —
разные вопросы, и склеить их значило бы выбрать дверь на вкус.

| дверь | чем названа | кто может проверить, что она настроена | кто вправе её доставить |
|---|---|---|---|
| `declared_root` | объявлением `architecture/history_roots.json` | сторож читает ОБЪЯВЛЕНИЕ — файл в git | **агент** (ADR-285: ни деньги, ни публичные числа, ни необратимое) |
| `environment` | переменной `SPA_HISTORY_ROOT` | до этого прибора — НИКТО | владелец: `plist` ступени переменной не несёт, правка = переустановка агента (инв. #12) |
| `own_clone_depth` | самим деревом, из которого идёт ступень | `git rev-parse --is-shallow-repository` | владелец: распрямление клона есть действие над прод-деревом (`.claude/rules/deployment.md` п. 6) |

**Измеренная цена байтов опрокидывает ожидание.** «Обрезанное дерево дешевле полного»
на этом хосте ЛОЖНО: замер 10.10 — рабочее дерево 443 достижимых коммита при
**1.83 ГиБ рыхлых объектов** (из них 22 257 уже лежат в паках), зеркало — 27 410
коммитов в **191 МиБ упакованных**. Полная история стоит на порядок МЕНЬШЕ, чем
обрезанное дерево уже израсходовало впустую. Поэтому байты из решения не выкинуты, а
названы: они говорят не «полная история дорога», а «обрезка не экономит ничего».

## Что здесь РЕШЕНО (и почему это решение агента, а не вопрос владельцу)

Ступень берёт историю через **объявленный корень**: это единственная из трёх дверей,
которая (а) пригодна на этом хосте сейчас, (б) наблюдаема сторожем и (в) доставляется
агентом по границе ADR-285. Переменная окружения остаётся явной подменой оператора и
теперь НАБЛЮДАЕМА — разрешённая дверь названа в отчёте. Глубина своего дерева не
выбрана не потому, что дорога, а потому, что принадлежит владельцу; её цена измерена и
уехала карточкой.

**Порядок разрешения объявлен и прочитан исходом:** переменная (явная подмена) →
первый ПРИГОДНЫЙ объявленный корень → своё дерево. Непригодный корень не выбирается
молча: причина его отвода попадает в отчёт, иначе «зеркало отстало» и «зеркала нет»
слились бы в одно слово.

## Третий исход есть у КАЖДОГО числа этого прибора (инв. #17)

Не прочитано объявление · `git` не отработал · корень не дерево git · база не найдена —
всё это `unmeasured` с НАЗВАННОЙ причиной и ненулевым кодом возврата, а не ноль байт,
не «дверь слепа» и не пропуск строки. Байты корня, которого нет, — `None`, а не `0`:
ноль здесь означал бы измеренный пустой репозиторий.

ADVISORY: прибор только ЧИТАЕТ (``applied=False``) — объявление, окружение и
``git``-деревья. Ничего не распрямляет, не переустанавливает и не правит. RiskPolicy
v1.0, стоп-кран, аллокатор, живой трек и ``landing/`` не трогаются. Только stdlib,
сети нет (``git`` локален, ``fetch`` не вызывается).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import duplicate_subject_census as census
from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "history_door_price.json"
ORDER = ("G112 п. 1 (ADR-538) — откуда ступень моста берёт историю: объявление · "
         "переменная окружения · глубина своего клона, с замером цены каждой двери")

#: Объявление корней истории. Путь host-specific, поэтому живёт ДАННЫМИ в git, а не
#: литералом в модуле: литерал сделал бы прибор непереносимым и непроверяемым.
DECLARATION_REL = "architecture/history_roots.json"

#: Явная подмена оператором. Имя переменной читается ИЗ объявления (поле ``env_var``);
#: эта константа — только умолчание на случай, когда объявление его не несёт.
DEFAULT_ENV_VAR = "SPA_HISTORY_ROOT"

#: Двери в ПОРЯДКЕ разрешения. Порядок объявлен здесь один раз и им же меряется:
#: ``resolve_history_root`` обходит именно этот кортеж.
DOOR_ENV = "environment"
DOOR_DECLARED = "declared_root"
DOOR_OWN = "own_clone_depth"
DOORS = (DOOR_ENV, DOOR_DECLARED, DOOR_OWN)

#: Исходы пробы корня. «Пригоден» — ровно один; остальные различают ПРИЧИНУ отвода,
#: потому что лечатся они разным (инв. #17).
STATE_USABLE = "usable"
STATE_NOT_NAMED = "not_named"
STATE_ABSENT = "absent"
STATE_NOT_A_TREE = "not_a_git_tree"
STATE_SHALLOW = "shallow"
STATE_BASE_REF_ABSENT = "base_ref_absent"
STATE_UNMEASURED = "unmeasured"

STATES = (STATE_USABLE, STATE_NOT_NAMED, STATE_ABSENT, STATE_NOT_A_TREE,
          STATE_SHALLOW, STATE_BASE_REF_ABSENT, STATE_UNMEASURED)

#: Кто вправе доставить дверь. Не свойство вкуса: граница ADR-285 и правило доставки.
BY_AGENT = "agent"
BY_OWNER = "owner"

#: Чем проверяется, что дверь НАСТРОЕНА. «Никто» — самостоятельный исход, а не прочерк.
CHECK_NOBODY = "nobody"

STATUS_CHOSEN = "HISTORY_DOOR_CHOSEN"
STATUS_BLIND = "HISTORY_DOOR_BLIND"
STATUS_UNMEASURED = "UNMEASURED"

_KIB = 1024.0


# ───────────────────────────── объявление дверей ─────────────────────────────

def read_declaration(repo_root: Path, *, rel: str = DECLARATION_REL) -> Dict[str, Any]:
    """Объявленные корни истории. Нет файла / битый JSON ⇒ НЕ ИЗМЕРЕНО с причиной.

    Пустой список корней — это ИЗМЕРЕНО И РАВНО НУЛЮ (объявление есть, корней в нём
    нет), и путать его с «объявление не прочитано» нельзя: первое лечится строкой в
    файле, второе — доставкой файла.
    """
    path = repo_root / rel
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"measured": False, "reason": f"объявление не найдено: {rel}",
                "roots": [], "env_var": DEFAULT_ENV_VAR, "path": str(path)}
    except (OSError, ValueError) as exc:
        return {"measured": False, "reason": f"объявление не прочитано: {type(exc).__name__}: {exc}",
                "roots": [], "env_var": DEFAULT_ENV_VAR, "path": str(path)}
    if not isinstance(raw, dict):
        return {"measured": False, "reason": f"объявление не словарь: {type(raw).__name__}",
                "roots": [], "env_var": DEFAULT_ENV_VAR, "path": str(path)}
    roots: List[Dict[str, Any]] = []
    for item in (observed(raw, "roots", kind=list) or []):
        if isinstance(item, dict) and str(item.get("path") or "").strip():
            roots.append(item)
    env_var = str(raw.get("env_var") or "").strip() or DEFAULT_ENV_VAR
    return {"measured": True, "reason": None, "roots": roots,
            "env_var": env_var, "path": str(path)}


def _git_runner(root: Path):
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(root),
                              capture_output=True, text=True, timeout=120)
    return _git


def object_store_price(root: Path, *, git=None) -> Dict[str, Any]:
    """Байты и коммиты корня. Нет замера ⇒ `None`, а НЕ ноль.

    Ноль байт означал бы измеренный пустой объектный склад; у корня, которого нет
    или который не дерево git, замера нет вовсе, и это разные ответы.
    """
    out: Dict[str, Any] = {"loose_kib": None, "pack_kib": None, "total_kib": None,
                           "commits_reachable": None, "measured": False, "reason": None}
    run = git or _git_runner(root)
    try:
        counted = run("count-objects", "-v")
    except (OSError, subprocess.SubprocessError) as exc:
        out["reason"] = f"git не отработал: {type(exc).__name__}: {exc}"
        return out
    if counted.returncode != 0:
        out["reason"] = f"склад объектов не прочитан: {counted.stderr.strip()[:160]}"
        return out
    fields: Dict[str, int] = {}
    for line in counted.stdout.splitlines():
        key, _, value = line.partition(":")
        try:
            fields[key.strip()] = int(value.strip())
        except ValueError:
            continue
    if "size" not in fields or "size-pack" not in fields:
        out["reason"] = "ответ `count-objects -v` не несёт `size`/`size-pack`"
        return out
    out["loose_kib"] = fields["size"]
    out["pack_kib"] = fields["size-pack"]
    out["total_kib"] = fields["size"] + fields["size-pack"]
    out["loose_objects"] = fields.get("count")
    out["already_packed_loose"] = fields.get("prune-packable")
    # Коммиты считаются и у ОБРЕЗАННОГО дерева: именно их число (443 против 27410
    # замером 10.10) и показывает, какую часть истории дверь вообще видит.
    try:
        counted_commits = run("rev-list", "--count", "HEAD")
        if counted_commits.returncode == 0:
            out["commits_reachable"] = int(counted_commits.stdout.strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass  # цена коммитов необязательна: пригодность она не решает
    out["measured"] = True
    return out


def probe_root(root: Optional[Path], *, base_ref: str, git=None) -> Dict[str, Any]:
    """Пригоден ли корень на вопрос «списана или потеряна».

    Пригодность — конъюнкция трёх НАЗВАННЫХ условий, и каждое отводит корень своей
    причиной: дерево существует · история не обрезана · база в нём есть. Склеить их
    в одно «непригоден» значило бы спрятать, что лечится каждое по-своему.
    """
    out: Dict[str, Any] = {"root": None if root is None else str(root),
                           "state": STATE_NOT_NAMED, "reason": "корень не назван",
                           "shallow": None, "price": None}
    if root is None:
        return out
    if not root.exists():
        out["state"], out["reason"] = STATE_ABSENT, f"каталога нет: {root}"
        return out
    run = git or _git_runner(root)
    try:
        inside = run("rev-parse", "--git-dir")
    except (OSError, subprocess.SubprocessError) as exc:
        out["state"] = STATE_UNMEASURED
        out["reason"] = f"git не отработал: {type(exc).__name__}: {exc}"
        return out
    if inside.returncode != 0:
        out["state"] = STATE_NOT_A_TREE
        out["reason"] = f"не дерево git: {inside.stderr.strip()[:160]}"
        return out
    try:
        shallow = run("rev-parse", "--is-shallow-repository")
    except (OSError, subprocess.SubprocessError) as exc:
        out["state"] = STATE_UNMEASURED
        out["reason"] = f"глубина клона не прочитана: {type(exc).__name__}: {exc}"
        return out
    if shallow.returncode != 0:
        out["state"] = STATE_UNMEASURED
        out["reason"] = f"глубина клона не прочитана: {shallow.stderr.strip()[:160]}"
        return out
    out["shallow"] = shallow.stdout.strip() == "true"
    out["price"] = object_store_price(root, git=run)
    if out["shallow"]:
        out["state"] = STATE_SHALLOW
        out["reason"] = ("история ОБРЕЗАНА (`.git/shallow`): пустой обход пути не есть "
                         "отсутствие удаления, судить из такого дерева нельзя")
        return out
    try:
        resolved = run("rev-parse", "--verify", base_ref)
    except (OSError, subprocess.SubprocessError) as exc:
        out["state"] = STATE_UNMEASURED
        out["reason"] = f"база не проверена: {type(exc).__name__}: {exc}"
        return out
    if resolved.returncode != 0:
        out["state"] = STATE_BASE_REF_ABSENT
        out["reason"] = f"базы {base_ref} в дереве нет: {resolved.stderr.strip()[:160]}"
        return out
    out["base_sha"] = resolved.stdout.strip()
    out["state"], out["reason"] = STATE_USABLE, None
    return out


def _expand(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def survey_doors(repo_root: Path, *, base_ref: str = census.DEFAULT_BASE_REF,
                 env: Optional[Dict[str, str]] = None,
                 declaration: Optional[Dict[str, Any]] = None,
                 git_for=None) -> List[Dict[str, Any]]:
    """Проба КАЖДОЙ двери заказа, в объявленном порядке и без обрыва.

    Одно правило — одна копия: обзор и разрешение ходят ОДНИМ этим обходом, поэтому
    «чем пойдёт ступень» и «чего стоит каждая дверь» не могут разойтись. Обрыв на
    первой пригодной живёт в :func:`resolve_history_root`, а не здесь: оборви его
    тут — и своё дерево осталось бы неспрошенным ровно тогда, когда дверь нашлась,
    то есть главное сравнение заказа стало бы НЕ ИЗМЕРЕНО в момент успеха.
    """
    environ = os.environ if env is None else env
    decl = declaration if declaration is not None else read_declaration(repo_root)
    env_var = decl.get("env_var") or DEFAULT_ENV_VAR
    rows: List[Dict[str, Any]] = []

    def _probe(root: Optional[Path]) -> Dict[str, Any]:
        return probe_root(root, base_ref=base_ref,
                          git=git_for(root) if (git_for and root is not None) else None)

    for door in DOORS:
        if door == DOOR_ENV:
            raw = str(environ.get(env_var) or "").strip()
            probe = _probe(_expand(raw) if raw else None)
            probe["named_by"] = f"{env_var} (окружение)"
            if not raw:
                probe["reason"] = f"переменная {env_var} не задана"
        elif door == DOOR_DECLARED:
            probe = {"state": STATE_NOT_NAMED, "root": None, "shallow": None,
                     "price": None, "named_by": DECLARATION_REL,
                     "reason": (decl.get("reason")
                                or f"объявленных корней нет в {DECLARATION_REL}")}
            for item in decl.get("roots") or []:
                candidate = _probe(_expand(str(item.get("path"))))
                candidate["named_by"] = f"{DECLARATION_REL}: {item.get('path')}"
                candidate["declared_by"] = item.get("declared_by")
                probe = candidate
                if candidate["state"] == STATE_USABLE:
                    break
        else:
            probe = _probe(repo_root)
            probe["named_by"] = "своё дерево ступени"
        probe["door"] = door
        rows.append(probe)
    return rows


def resolve_history_root(repo_root: Path, *, base_ref: str = census.DEFAULT_BASE_REF,
                         env: Optional[Dict[str, str]] = None,
                         declaration: Optional[Dict[str, Any]] = None,
                         git_for=None,
                         survey: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Корень, у которого ступень СПРАШИВАЕТ историю, и чем он назван.

    Эту функцию зовёт сама ступень (`duplicate_subject_census.run`), поэтому у неё
    два свойства, которые нельзя терять:

    1. **Она НИКОГДА не падает и не возвращает выдумку.** Непригодны все двери ⇒
       `root=None`, и сосед остаётся при своём честном третьем исходе. Подставить
       обрезанное дерево как «ну хоть что-то» значило бы вернуть ноль в заголовок.
    2. **Отвод каждой двери НАЗВАН** (`trail`): «зеркало отстало», «зеркала нет» и
       «переменная не задана» — три разных ответа, и в отчёте они три разные строки.
    """
    decl = declaration if declaration is not None else read_declaration(repo_root)
    rows = list(survey) if survey is not None else survey_doors(
        repo_root, base_ref=base_ref, env=env, declaration=decl, git_for=git_for)
    trail: List[Dict[str, Any]] = []
    for probe in rows:
        trail.append(probe)
        if probe["state"] == STATE_USABLE:
            return {"root": Path(probe["root"]), "door": probe["door"],
                    "named_by": probe["named_by"], "trail": trail,
                    "declaration": decl, "survey": rows}
    return {"root": None, "door": None, "named_by": None, "trail": trail,
            "declaration": decl, "survey": rows}


# ───────────────────────── цена двери, измеренная ИСХОДОМ ─────────────────────

def _headline(repo_root: Path, *, history_root: Optional[Path],
              journal: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """Главные числа соседа, посчитанные ЧЕРЕЗ названную дверь, и задержка ответа.

    Меряется ИСХОД, а не структура: зовётся настоящая `measure_price` настоящего
    соседа с настоящей `retirement_door`. Утверждение «дверь передана аргументом»
    к ответу слепо и контролем не является (ADR-333).
    """
    started = time.monotonic()
    try:
        price = census.measure_price(
            journal["records"], base,
            retirement=census.retirement_door(history_root or repo_root, base["ref"]))
    except Exception as exc:  # noqa: BLE001 — цена двери не смеет валить прибор
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}",
                "latency_seconds": round(time.monotonic() - started, 3)}
    latency = round(time.monotonic() - started, 3)
    # Поле, которого сосед не вернул, НЕ ноль: это смена его формы, и склеить её
    # с «измерено и равно нулю» значило бы доложить чистый ответ о непрочитанном
    # (инв. #17). `observed` отдаёт `None`, и исход становится третьим.
    counts = {k: observed(price, k, kind=int)
              for k in ("retired_at_base", "lost_coordinates", "retirement_unmeasured")}
    missing = sorted(k for k, v in counts.items() if v is None)
    if missing:
        return {"measured": False,
                "reason": f"сосед не вернул поля {', '.join(missing)} — форма изменилась",
                "latency_seconds": latency}
    answered = counts["retired_at_base"] + counts["lost_coordinates"]
    blind = counts["retirement_unmeasured"]
    return {
        "measured": True, "reason": None, "latency_seconds": latency,
        "population": answered + blind,
        "answered": answered, "blind": blind,
        "lost_coordinates": price.get("lost_coordinates"),
        "retired_at_base": price.get("retired_at_base"),
        "retirement_unmeasured": price.get("retirement_unmeasured"),
        "sessions_on_lost_coordinates": price.get("sessions_on_lost_coordinates"),
        "subjects_on_lost_coordinates": price.get("subjects_on_lost_coordinates"),
    }


def _delivery_right(door: str) -> Tuple[str, str]:
    """Кто вправе доставить дверь — по правилу, а не по вкусу."""
    if door == DOOR_DECLARED:
        return BY_AGENT, ("объявление — файл в git; ни деньги, ни публичные числа, ни "
                          "необратимое (ADR-285) ⇒ решение агента, записью в журнал")
    if door == DOOR_ENV:
        return BY_OWNER, ("plist ступени переменной не несёт: правка = переустановка "
                          "агента (инв. #12, `.claude/rules/deployment.md` п. 6)")
    return BY_OWNER, ("распрямление клона есть действие над прод-деревом — только с "
                      "разрешения владельца (`.claude/rules/deployment.md` п. 6)")


def _checkable_by(door: str, env_var: str) -> str:
    if door == DOOR_DECLARED:
        return f"{DECLARATION_REL} + data/{ARTIFACT_NAME}"
    if door == DOOR_ENV:
        return (f"data/{ARTIFACT_NAME} (до этого прибора — {CHECK_NOBODY}: «{env_var} не "
                f"задана» было неотличимо от «дверь не настроена»)")
    return "git rev-parse --is-shallow-repository + data/" + ARTIFACT_NAME


def build_report(repo_root: Path, *, data_dir: Optional[Path] = None,
                 base_ref: str = census.DEFAULT_BASE_REF,
                 now: Optional[datetime] = None,
                 env: Optional[Dict[str, str]] = None,
                 git_for=None) -> Dict[str, Any]:
    """Отчёт прибора. ``measured=False`` ⇒ вердикта нет вовсе, и причина названа."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    data = data_dir or (repo_root / "data")
    report: Dict[str, Any] = {
        "generated_at": stamp,
        "order": ORDER,
        "applied": False,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        # Форма отчёта ПОСТОЯННА: поле, которое не посчиталось, несёт `None`, а не
        # исчезает. Иначе шаг 0-офис не отличил бы «производитель перестал писать
        # поле» от «в этот раз поле не считалось» (инв. #17).
        "base_ref": base_ref,
        "declaration": None,
        "doors": None,
        "chosen": None,
        "effective": None,
        "false_zero": None,
    }

    decl = read_declaration(repo_root)
    survey = survey_doors(repo_root, base_ref=base_ref, env=env, declaration=decl,
                          git_for=git_for)
    resolution = resolve_history_root(repo_root, base_ref=base_ref, env=env,
                                      declaration=decl, git_for=git_for, survey=survey)
    env_var = decl.get("env_var") or DEFAULT_ENV_VAR
    report["declaration"] = {"path": decl.get("path"), "measured": decl.get("measured"),
                             "reason": decl.get("reason"),
                             "roots_declared": len(decl.get("roots") or []),
                             "env_var": env_var}

    journal = census.load_journal(data / census.JOURNAL_NAME)
    if not journal["measured"]:
        report["reason"] = f"журнал объявлений не прочитан: {journal['reason']}"
        return report
    base = census.read_base_tree(repo_root, base_ref)
    if not base["measured"]:
        report["reason"] = f"база не прочитана: {base['reason']}"
        return report

    # Обзор идёт по ВСЕМ трём дверям, а не по следу разрешения: след обрывается на
    # первой пригодной, и тогда своё дерево осталось бы неспрошенным — то есть
    # главное сравнение заказа («сколько прячет слепая дверь») стало бы НЕ ИЗМЕРЕНО
    # ровно в тот момент, когда дверь нашлась. Разрешение отвечает «чем пойдёт
    # ступень», обзор — «чего стоит каждая»; это два вопроса.
    doors: List[Dict[str, Any]] = []
    for probe in survey:
        door = probe["door"]
        right, why = _delivery_right(door)
        root = Path(probe["root"]) if probe.get("root") else None
        row: Dict[str, Any] = {
            "door": door,
            "named_by": probe.get("named_by"),
            "root": probe.get("root"),
            "state": probe["state"],
            "reason": probe.get("reason"),
            "shallow": probe.get("shallow"),
            "price": probe.get("price"),
            "checkable_by": _checkable_by(door, env_var),
            "deliverable_by": right,
            "deliverable_reason": why,
            "outcome": None,
        }
        if probe["state"] in (STATE_USABLE, STATE_SHALLOW, STATE_BASE_REF_ABSENT):
            # Исход меряется у любой двери, корень которой ОКАЗАЛСЯ деревом git —
            # включая обрезанное: именно его ответ уходит наружу сегодня, и без него
            # сравнение «сколько прячет слепая дверь» измерить нечем. У двери, корня
            # которой нет вовсе, спрашивать не у чего — третий исход с причиной.
            row["outcome"] = _headline(repo_root, history_root=root,
                                       journal=journal, base=base)
        else:
            row["outcome"] = {"measured": False,
                              "reason": f"спрашивать негде: {probe['state']} — "
                                        f"{probe.get('reason')}",
                              "latency_seconds": None}
        doors.append(row)

    report["doors"] = doors
    own = next((d for d in doors if d["door"] == DOOR_OWN), None)
    usable = [d for d in doors if d["state"] == STATE_USABLE]
    agent_usable = [d for d in usable if d["deliverable_by"] == BY_AGENT
                    and CHECK_NOBODY not in str(d["checkable_by"])]

    if resolution["root"] is not None:
        chosen = next(d for d in doors if d["door"] == resolution["door"])
        report["chosen"] = {"door": chosen["door"], "root": chosen["root"],
                            "named_by": chosen["named_by"],
                            "why": ("пригодна на этом хосте, наблюдаема сторожем и "
                                    "доставляется агентом"
                                    if chosen in agent_usable else
                                    "единственная пригодная дверь в объявленном порядке")}
    report["effective"] = {
        "root": None if resolution["root"] is None else str(resolution["root"]),
        "door": resolution["door"],
        "stage_is_blind": resolution["root"] is None,
        "agent_deliverable_doors": [d["door"] for d in agent_usable],
        "owner_doors_named": [d["door"] for d in doors if d["deliverable_by"] == BY_OWNER],
    }

    chosen_outcome = (report["chosen"] and
                      next((d["outcome"] for d in doors
                            if d["door"] == report["chosen"]["door"]), None))
    own_outcome = own and own.get("outcome")
    if (chosen_outcome and chosen_outcome.get("measured")
            and own_outcome and own_outcome.get("measured")):
        report["false_zero"] = {
            "metric": "lost_coordinates",
            "through_own_door": own_outcome["lost_coordinates"],
            "through_chosen_door": chosen_outcome["lost_coordinates"],
            "hidden": (int(chosen_outcome["lost_coordinates"] or 0)
                       - int(own_outcome["lost_coordinates"] or 0)),
            "named": ("слепая дверь не теряет строки, а перекладывает их из «потеряно» "
                      "в «не измерено»: наружу выходит ноль, и ноль читается как «чисто»"),
        }
    elif own_outcome is not None or chosen_outcome is not None:
        report["false_zero"] = {
            "metric": "lost_coordinates", "through_own_door": None,
            "through_chosen_door": None, "hidden": None,
            "named": "сравнение НЕ ИЗМЕРЕНО: хотя бы один исход двери не посчитан",
        }

    report["measured"] = True
    report["status"] = STATUS_BLIND if resolution["root"] is None else STATUS_CHOSEN
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def _kib(value: Optional[int]) -> str:
    if value is None:
        return "НЕ ИЗМЕРЕНО"
    if value >= _KIB * _KIB:
        return f"{value / (_KIB * _KIB):.2f} ГиБ"
    if value >= _KIB:
        return f"{value / _KIB:.0f} МиБ"
    return f"{value} КиБ"


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    head = "откуда ступень берёт историю (заказ G112 п. 1)"
    if not report.get("measured"):
        lines.append(f"{head}: НЕ ИЗМЕРЕНО — {report.get('reason')}")
        return lines
    doors = observed(report, "doors", kind=list)
    if doors is None:
        lines.append(f"{head}: НЕ ИЗМЕРЕНО — отчёт не несёт раздела `doors`")
        return lines
    effective = observed(report, "effective", kind=dict) or {}
    decl = observed(report, "declaration", kind=dict) or {}
    lines.append(
        f"{head}: {report['status']} · дверь ступени "
        f"{effective.get('door') or 'НЕТ — ступень слепа'} "
        f"({effective.get('root') or 'корень не назван'}) · объявленных корней "
        f"{decl.get('roots_declared')} "
        + ("" if decl.get("measured") else f"· объявление НЕ ПРОЧИТАНО: {decl.get('reason')}"))
    for row in doors:
        # `or {}` здесь склеило бы «цена не мерилась» с «склад пуст» (инв. #17).
        price = observed(row, "price", kind=dict)
        outcome = observed(row, "outcome", kind=dict)
        tail = ""
        if outcome is None:
            tail = " · ОТВЕТ НЕ ИЗМЕРЕН: отчёт не несёт раздела `outcome`"
        elif outcome.get("measured"):
            tail = (f" · ОТВЕТ {outcome['answered']}/{outcome['population']} "
                    f"(слепо {outcome['blind']}, задержка {outcome['latency_seconds']} с, "
                    f"потерянных координат {outcome['lost_coordinates']})")
        else:
            tail = f" · ОТВЕТ НЕ ИЗМЕРЕН: {outcome.get('reason')}"
        lines.append(
            f"[{row['door']}] {row['state']}"
            + (f" — {row['reason']}" if row.get("reason") else "")
            + f" · назвал: {row['named_by']}"
            + (" · склад НЕ ИЗМЕРЕН: отчёт не несёт раздела `price`" if price is None
               else f" · склад {_kib(price.get('total_kib'))}")
            + ("" if price is None or not price.get("measured") else
               f" (рыхлых {_kib(price.get('loose_kib'))}, коммитов "
               f"{price.get('commits_reachable')})")
            + f" · доставляет {row['deliverable_by']}: {row['deliverable_reason']}"
            + f" · проверяет: {row['checkable_by']}"
            + tail)
    fz = observed(report, "false_zero", kind=dict)
    if fz is not None:
        lines.append(
            f"[ГЛАВНОЕ ЧИСЛО] `{fz['metric']}`: через своё дерево "
            f"{fz['through_own_door']} · через выбранную дверь {fz['through_chosen_door']} "
            f"⇒ спрятано {fz['hidden']} — {fz['named']}")
    lines.append(
        f"[ГРАНИЦА] агентом доставимы: {effective.get('agent_deliverable_doors')} · "
        f"у владельца: {effective.get('owner_doors_named')} — вторые названы, а не "
        "выбраны молча")
    lines.append(
        "НЕ ДОКЛАДЫВАЕТ: ПРАВ ли сосед в своём вердикте (прибор мерит дверь, не "
        "перепись) · свежесть объявленного клона (отставшее зеркало пригодно, и это "
        "ВЕРНО: удаление, которое в нём есть, достижимо) · доехала ли потерянная "
        "работа куда-то ещё · стоит ли распрямлять прод-дерево (это решение владельца)")
    lines.append(
        "ADVISORY: прибор только ЧИТАЕТ (applied=False) — объявление, окружение и "
        "git-деревья; ничего не распрямляет и не переустанавливает. RiskPolicy v1.0, "
        "стоп-кран, аллокатор, живой трек и landing/ не трогаются")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def exit_code_for(report: Dict[str, Any]) -> int:
    """0 — ступень не слепа · 1 — находка (слепа или отвечает не на всё) · 2 — замера нет.

    Число `false_zero.hidden` красным САМО ПО СЕБЕ не является и зелени не отменяет:
    оно есть измеренная ЦЕНА слепой двери и остаётся в отчёте навсегда, даже когда
    ступень ходит уже не через неё. Краснит ровно то, что вредит сейчас, — слепая
    ступень; иначе прибор был бы красен вечно и его перестали бы читать.
    """
    if not report.get("measured"):
        return 2
    if report["status"] != STATUS_CHOSEN:
        return 1
    chosen = observed(report, "chosen", kind=dict) or {}
    doors = observed(report, "doors", kind=list) or []
    outcome = next((d.get("outcome") or {} for d in doors
                    if d.get("door") == chosen.get("door")), {})
    if not outcome.get("measured"):
        return 1
    return 1 if int(outcome.get("blind") or 0) else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--data-dir", default=None, help="каталог данных (по умолчанию — свой)")
    ap.add_argument("--base-ref", default=census.DEFAULT_BASE_REF, help="базовый ref доставки")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root,
                          data_dir=Path(args.data_dir) if args.data_dir else None,
                          base_ref=args.base_ref)
    if args.save:
        save_artifact(report, Path(args.data_dir) if args.data_dir else (repo_root / "data"))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
