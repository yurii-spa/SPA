#!/usr/bin/env python3
"""Кто выдаёт ПРИСУТСТВИЕ файла за доказательство ЖИВОГО ПИСАТЕЛЯ — перепись класса ADR-875.

# LLM_FORBIDDEN

**Зачем (цикл #994, 2026-10-31, заказ G876 п. 1).** ADR-875 нашёл и закрыл РОВНО ОДИН
сторож: `consume_office_reports._office_absent_wholesale` считал дерево «производящим»,
если ХОТЬ ОДИН артефакт офиса СУЩЕСТВУЕТ, — а существовали ровно две цели из 142, и обе
git-tracked и равны HEAD, то есть их выложил `git checkout`, а не написал флот. Из любого
изолированного worktree — того самого, который §3.4 протокола ТРЕБУЕТ — шаг 1 приказа
печатал 140 строк «❌ НЕ ПРОЧИТАН» под подписью «действовать (карточки)». Сам ADR-875
запретил считать класс закрытым по этой находке:

> «Население класса „сторож судит по СУЩЕСТВОВАНИЮ пути вместо наблюдения“ НЕ ИЗМЕРЕНО.
> Закрыт ОДИН сторож — шага 0-офис; сколько ещё дверей читают присутствие файла как
> доказательство живого писателя, не спрашивал никто.»

Этот прибор и есть та перепись. Он НИЧЕГО не чинит — только ЧИТАЕТ дерево и называет
поимённо каждое место, где ПРИСУТСТВИЕ пути становится ответом на вопрос о НАБЛЮДЕНИИ.

## Ось у класса ОДНА, и это НАПРАВЛЕНИЕ, а не наличие `exists()`

Первая редакция меры ловила «проверку существования артефакта без вопроса о свежести» и
дала **238** мест. Вывод был опровергнут собственным населением: почти все 238 — честные
`if not path.exists(): return None`, то есть **отсутствие ⇒ отказ**, ровно инв. #17 и
fail-CLOSED. Шумная перепись хуже пустой: по ней нельзя ни чинить, ни считать.

Дефект ADR-875 смотрит в ДРУГУЮ сторону:

| направление | что утверждается | вердикт |
|---|---|---|
| **отсутствие ⇒ «не измерено»** | файла нет ⇒ наблюдения нет | **ЭТАЛОН** (инв. #17), не находка |
| **присутствие ⇒ «наблюдено»** | файл есть ⇒ писатель был | **НАХОДКА** — fail-OPEN, дословный ADR-875 |

Поэтому мера судит по ВЕТКЕ, в которой лежит вердикт, с учётом `not`, а не по наличию
вызова `exists()`. Присутствие — свойство ДЕРЕВА, а не наблюдение: `git checkout` выкладывает
tracked-файл со всем его содержимым и размером. Метка «живое» на КОНСТАНТЕ — дословный класс
ADR-126.

## Что здесь считается ДВЕРЬЮ (мера тугая намеренно, цена туготы печатается)

Дверь — вызов предиката существования (`os.path.exists` / `isfile` / `isdir`,
`Path.exists` / `is_file` / `is_dir`) внутри функции НЕ-тестового модуля, у которого:

1. есть **объемлющая ветка** (`if` или `A if cond else B`), куда значение предиката
   доходит; полярность протягивается через `not`. Ветки нет ⇒ исход `no_branch` — ЦЕНА,
   а не находка: куда пошёл ответ, мера не знает;
2. в ветке ПРИСУТСТВИЯ стоит вердикт о НАБЛЮДЕНИИ. Слово, попавшее и в словарь
   отсутствия (`«не прочитан»` несёт `прочитан`; `«SAFE_ADDRESS not configured
   (ADR-010 exists …)»` несёт `exists`), засчитывается ТОЛЬКО как отсутствие — иначе
   отрицание читалось бы утверждением.

**Формы вердикта, которые мера считает доказательством** — строковая константа · ИМЯ
ВЫЗЫВАЕМОЙ функции (`ok(...)`, `fail(...)`) · ИМЯ-КОНСТАНТА В ВЕРХНЕМ РЕГИСТРЕ
(`UNMEASURED`) · ИМЯ КЛЮЧЕВОГО АРГУМЕНТА (`passed=True`). Простой строчный идентификатор
доказательством НЕ является, и это решение с ЗАМЕРОМ: пока он им был,
`card_delivery.validate` попадал в находки за `ok.append(absolute)` — локальный СПИСОК
доставляемых путей, к вердикту о наблюдении отношения не имеющий. Цена решения — нижняя
граница населения, и она названа здесь, а не умолчана.

## Сила утверждения различается, и прибор её НЕ завышает — ТРИ яруса

| ярус | вердикт в ветке присутствия | находка? |
|---|---|---|
| `presence_to_observed` | НАБЛЮДЕНИЕ или ГОТОВНОСТЬ (`прочитано`, `measured`, `confirmed`, `работает`) либо **прибавленный балл готовности** (`score += 2`) | **ДА** — присутствие этого не доказывает |
| `presence_generic_pass` | родовое «прошло» (`PASS`, `ok`, `VERIFIED`, `✓`) | **НЕТ — НЕ ИЗМЕРЕНО** |
| `presence_restated` | ПОВТОР вопроса (`exists`, `present`, `найден`) | нет — честная тавтология |

Средний ярус — не поблажка, а отказ завышать. Критерий объявлен докстрокой зовущего, а не
кодом ветки: у `pre_paper_checklist._check_d003` («D003: GMX research adapter file
exists»), `readiness_checker` C011 («push_to_github.py present»),
`system_config_validator.check_file_exists` и `golive_preflight._check_file_exists`
критерий ЕСТЬ существование, и «PASS» там ВЕРНЫЙ ответ. Считать их находками значило бы
совершить ровно ту ошибку, против которой написан класс, — выдать незнание за замер.
Все 18 таких мест печатаются ПОИМЁННО: это список для человека, а не ноль.

## Вторая ось — ЖИВАЯ: а вердикт вообще может стать иным?

Статическая ось говорит «место есть». `tracked_constant_axis` отвечает на то, чего та не
знает: путь собирается из сегментов исходника, проверяется НА ДИСКЕ и спрашивается у git
теми же тремя исходами, что у `_writer_evidence` (ADR-875) — `constant` (git-tracked и
равен HEAD ⇒ присутствие обеспечено `git checkout`) · `writer` (untracked либо переписан)
· `absent` (кандидат собрался, на диске его нет) · `unmeasured`. Склеивать оси запрещено:
статическая даёт ВЕРХНИЙ край населения, живая говорит о СИЛЕ каждой находки.

Замер цикла #994 (`origin/main` 018b2bb68): из 7 находок у **4** вердикт — КОНСТАНТА, и
три из них подряд в `golive_readiness_report.assess_data_sources`: **6 баллов готовности
к go-live из 10** начисляются за ПРИСУТСТВИЕ git-tracked ИСХОДНИКОВ
(`spa_core/utils/defillama.py`, `adapters/defillama_feed.py`,
`analytics/t1_data_verifier.py`, `analytics/strategy_promoter.py`). Эти баллы не могут
стать меньше ни при каком состоянии системы — это механизм под уже объявленным в
`docs/STATE.md` предупреждением «GoLive 29/29 — инвентарь, НЕ готовность» (ADR-530).

## Два ВЕТО, и каждое снимает свой род ложного срабатывания

* **`content_checked`** — ветка присутствия (или сам тест) ЧИТАЕТ содержимое файла
  (`open`, `read_text`, `json.load`, `_read_json`, …). Тогда вердикт стоит на
  СОДЕРЖИМОМ, а не на присутствии, и дверь из класса выходит. Замер: без этого вето в
  находки попадали `kill_switch.check_manual_trigger` (читает `active` из файла) и
  `verify_spa.check_ots_anchors` (сверяет хеш с именем файла) — оба судят по содержимому,
  объявить их дефектными значило бы опровергнуть меру её же выводом.
* **`writer_asked`** — объемлющая функция спрашивает о ПИСАТЕЛЕ или свежести
  (`getmtime`, `st_mtime`, `.stat(`, `generated_at`, `ls-files`, `_writer_evidence`, …).
  Это ЭТАЛОН — починенная ADR-875 форма.

## Чего перепись НЕ знает (названо, а не умолчано)

* **Исполнение.** Статическая ось говорит «место есть», а не «через него ходят»
  (урок ADR-674: дорога есть достижимость, а не исполнение).
* **Оболочка и воркфлоу.** `*.sh` и `.github/workflows/*.yml` спрашивают `test -f` тем
  же вопросом; их разбор здесь НЕ сделан, и число таких мест печатается отдельно со
  вердиктом НЕ ИЗМЕРЕНО — не нулём и не «чисто».
* **Происхождение пути через импорт.** Привязка протягивается до неподвижной точки
  внутри модуля (та же мера, что у `spa_core/tests/_injected_clock.py`); через импорт
  она не ходит, поэтому «путь — артефакт `data/`» есть НИЖНЯЯ граница. Ось артефактности
  на вердикт не влияет — она только РАЗМЕЧАЕТ находки, чтобы дверь к живому артефакту
  была отличима от двери к исходнику.
* **Вердикт прозой.** Ветка, печатающая результат в многострочный отчёт через
  переменную, мерой не достаётся; это та же нижняя граница.

Код возврата CLI: ``0`` — ни одной находки · ``1`` — находки НАЗВАНЫ ·
``2`` — НЕ ИЗМЕРЕНО с названной причиной (корень не прочитан либо файл не разобран).

> Прибор держит собственную меру: ни одна его ветка не судит о наблюдении по присутствию
> пути — отсутствие корня у него ТРЕТИЙ исход, а не ноль. Дверь, не выдерживающая своей
> же меры, меру и опровергает.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from typing import Iterable

#: Коды возврата CLI. Объявлены В КОДЕ (а не прозой), чтобы читатель этой двери
#: мог различить «находок нет» и «не измерено» — требование ADR-869/870.
RC_CLEAN, RC_FINDINGS, RC_UNMEASURED = 0, 1, 2

#: Исходы одного места. `presence_to_observed` — единственная НАХОДКА;
#: сила утверждения различается и прибором НЕ завышается (см. `claim`).
PRESENCE_TO_OBSERVED = "presence_to_observed"
PRESENCE_RESTATED = "presence_restated"
PRESENCE_GENERIC_PASS = "presence_generic_pass"
ABSENCE_TO_UNMEASURED = "absence_to_unmeasured"
CONTENT_CHECKED = "content_checked"
WRITER_ASKED = "writer_asked"
NO_OBSERVATION_VERDICT = "no_observation_verdict"
NO_BRANCH = "no_branch"

#: Полный словарь исходов. Храповик сверяет род находки с ЭТИМ набором, а не с
#: парой «находка / не находка»: расширение словаря есть УСИЛЕНИЕ проверки.
OUTCOMES = (
    PRESENCE_TO_OBSERVED,
    PRESENCE_RESTATED,
    PRESENCE_GENERIC_PASS,
    ABSENCE_TO_UNMEASURED,
    CONTENT_CHECKED,
    WRITER_ASKED,
    NO_OBSERVATION_VERDICT,
    NO_BRANCH,
)

#: Род утверждения у находки. `observation` — назвал наблюдение словом;
#: `readiness_score` — промолчал словом, но прибавил балл готовности.
CLAIMS = ("observation", "readiness_score")

#: Предикаты существования. `isdir`/`is_dir` входят намеренно: «каталог офиса
#: есть ⇒ офис жив» — тот же дефект на уровень выше файла.
_PREDICATES = frozenset({"exists", "isfile", "is_file", "isdir", "is_dir"})

#: Чтение СОДЕРЖИМОГО. Первое вето: вердикт на содержимом из класса выходит.
_CONTENT_READERS = frozenset({
    "open", "read_text", "read_bytes", "readlines", "read",
    "load", "loads", "safe_load",
    "_read_json", "read_json", "load_json", "_load_json", "_load",
    "_read_jsonl", "read_jsonl", "iter_lines",
})

#: Вопрос о ПИСАТЕЛЕ или свежести. Второе вето: это ЭТАЛОН (ADR-875).
_WRITER_QUESTION = re.compile(
    r"(getmtime|st_mtime|st_ctime|\.stat\(|generated_at|observed\(|age_hours"
    r"|ls-files|_writer_evidence|\bmtime\b|last_modified|updated_at"
    r"|измерен_писател|writer_evidence)")

#: Слова, которыми код называет ОТСУТСТВИЕ наблюдения. Проверяются ПЕРВЫМИ:
#: «не прочитан» несёт в себе «прочитан», и без этого порядка отрицание
#: читалось бы утверждением.
_ABSENCE = re.compile(
    r"(?i)(не\s+измерен|не\s+прочитан|не\s+наблюда|не\s+найден|не\s+обеспечен"
    r"|не\s+читается|не\s+настроен|not\s+configured|not\s+found|not\s+yet"
    r"|unmeasured|not_measured|unchecked|\bmissing\b|\babsent\b"
    r"|нет\s+файла|файла\s+нет|нет\s+в\s+дереве|\bstale\b|протух|отсутств"
    r"|пропал|\bno_writer\b|нет\s+писател|unreadable|НЕ\s+СУЩЕСТВУЕТ"
    r"|\bfail\b|\bFAILED\b|\bwarn\b)")

#: НАБЛЮДЕНИЕ или ГОТОВНОСТЬ — утверждение, которого присутствие пути НЕ
#: доказывает. Слово отсюда в ветке присутствия и есть находка.
_OBSERVATION_WORDS = re.compile(
    r"(?i)(прочитан|наблюдени|наблюдён|наблюдено|измерено|\bmeasured\b"
    r"|\bobserved\b|\balive\b|\bжив\b|\bживо|\bproduced\b|\bwriter\b|писател"
    r"|свеж|пульс|\bconfirmed\b|подтвержд|готов|\bready\b"
    r"|работает|\bdeployed\b|\bwired\b|\bactive\b|\bapproved\b|одобр)")

#: ПРИСУТСТВИЕ как таковое. Вердикт из этого словаря ПОВТОРЯЕТ вопрос, а не
#: надстраивает над ним утверждение, — честная тавтология, не находка.
_PRESENCE_WORDS = re.compile(
    r"(?i)(\bpresent\b|\bexists\b|\bнайден\b|есть\s+файл|существует"
    r"|существуют|\bв\s+дереве\b|\bна\s+диске\b)")

#: РОДОВАЯ метка «прошло» без названного предмета: `PASS`, `ok`, `VERIFIED`,
#: `✓`. Про что именно сказано «прошло» — про присутствие (и тогда ответ
#: ВЕРЕН) или про наблюдение (и тогда это дефект), — статическая мера НЕ
#: знает: критерий объявлен докстрокой зовущего, а не кодом ветки. Поэтому
#: это ТРЕТИЙ исход, а не находка и не чистота (инв. #17).
#:
#: Замер, на котором решение стоит: `pre_paper_checklist._check_d003`
#: («D003: GMX research adapter file exists»), `readiness_checker` C011
#: («push_to_github.py present»), `system_config_validator.check_file_exists`
#: и `golive_preflight._check_file_exists` — у ВСЕХ ЧЕТЫРЁХ критерий объявлен
#: как существование, и «PASS» там ВЕРНЫЙ ответ. Считать их находками значило
#: бы завысить силу утверждения — ровно то, против чего весь класс.
_GENERIC_PASS = re.compile(
    r"(?i)(\bok\b|✓|\bgood\b|\bvalid\b|\bPASS\b|\bpassed\b"
    r"|\bVERIFIED\b|\bverified\b|\bsuccess\b)")

#: Имена накопителей готовности: `score += 2` в ветке присутствия и есть
#: утверждение о готовности, даже когда рядом напечатано только «present».
#: Ровно эта форма у `golive_readiness_report.assess_data_sources`.
_READINESS_COUNTERS = re.compile(
    r"(?i)^(score|points|pts|n_pass|passed|ok_count|ready|readiness|"
    r"criteria_met|met|done)")

#: Что считается живым артефактом: разметка находки, НЕ условие вердикта.
_ARTEFACT_HINT = re.compile(
    r"(^|/)data/|\.json$|\.jsonl$|_report\.json|data_dir|DATA_DIR|DATA_PATH"
    r"|_PATH$|_FILE$|SPA_DATA_DIR")

#: Где ищем. Тесты исключены: у теста литеральная сцена — его предмет.
DEFAULT_SCOPE = ("spa_core", "scripts")

#: Каталоги, которые не разбираются никогда.
_SKIP_PARTS = ("/tests/", "/__pycache__/", "/.git/", "/node_modules/",
               "/.claude/", "/worktrees/")


# ── происхождение значения: до неподвижной точки, как у _injected_clock ──────

def _bindings(scope: ast.AST) -> dict[str, list[ast.AST]]:
    """Имя → выражения, из которых оно могло получить значение.

    Собираются ВСЕ привязки, а не последняя: какая из них дошла до чтения,
    статическая мера не знает, и подставлять одну значило бы угадывать.
    """
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out.setdefault(tgt.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                out.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, []).append(node.iter)
    return out


def path_origin_strings(node: ast.AST, binds: dict[str, list[ast.AST]],
                        *, depth: int = 0,
                        seen: frozenset[str] = frozenset()) -> list[str]:
    """Строки и имена, из которых путь мог произойти.

    Имя тоже улика: `DATA_DIR`, `REPORT_PATH`, `_data_dir` говорят об артефакте
    ровно столько же, сколько литерал `"data/x.json"`.
    """
    if depth > 6:
        return []
    if isinstance(node, ast.Name):
        if node.id in seen:
            return []
        out = [node.id]
        nseen = seen | {node.id}
        for value in binds.get(node.id, []):
            out += path_origin_strings(value, binds, depth=depth + 1, seen=nseen)
        return out
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    out = []
    for child in ast.iter_child_nodes(node):
        out += path_origin_strings(child, binds, depth=depth + 1, seen=seen)
    return out


# ── вердикт в ветке ──────────────────────────────────────────────────────────

def _called_names(nodes: Iterable[ast.AST]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Attribute):
                    names.add(func.attr)
                elif isinstance(func, ast.Name):
                    names.add(func.id)
    return names


def path_segments(node: ast.AST, binds: dict[str, list[ast.AST]],
                  *, depth: int = 0,
                  seen: frozenset[str] = frozenset()) -> list[str]:
    """Строки пути В ПОРЯДКЕ ИСХОДНИКА — чтобы `base / "a" / "b.py"` собиралось.

    Обход СЛЕВА НАПРАВО и В ГЛУБИНУ (`iter_child_nodes`, не `ast.walk`): у
    `ast.walk` порядок — по уровням, и цепочка `/` склеилась бы в «b.py/a».
    Порядок здесь — часть ответа, а не украшение.
    """
    if depth > 6:
        return []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        if node.id in seen:
            return []
        out: list[str] = []
        nseen = seen | {node.id}
        for value in binds.get(node.id, []):
            out += path_segments(value, binds, depth=depth + 1, seen=nseen)
        return out
    out = []
    for child in ast.iter_child_nodes(node):
        out += path_segments(child, binds, depth=depth + 1, seen=seen)
    return out


#: Три исхода оси «а константа ли этот вердикт» — дословно `_writer_evidence`
#: из ADR-875: tracked и равен HEAD ⇒ КОНСТАНТА (его выложил `git checkout`);
#: untracked либо расходится ⇒ был ПИСАТЕЛЬ; git не ответил или путь не
#: собрался ⇒ НЕ ИЗМЕРЕНО (инв. #17), и никогда подстановка.
TRACKED_CONSTANT = "constant"
TRACKED_WRITER = "writer"
TRACKED_ABSENT = "absent"
TRACKED_UNMEASURED = "unmeasured"


def _git_lines(args: list[str], cwd: str) -> list[str] | None:
    import subprocess
    try:
        done = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                              text=True, timeout=20)
    except (OSError, ValueError, Exception):                    # noqa: BLE001
        return None
    if done.returncode not in (0, 1):
        return None
    return [ln for ln in done.stdout.split("\n") if ln]


def tracked_constant_axis(site: dict, *, root: str) -> dict:
    """Живая ось: вердикт этого места — КОНСТАНТА в любой выкладке?

    Статическая ось говорит «место есть». Эта отвечает на то, чего та не
    знает: присутствие, которым место судит, обеспечено `git checkout` — и
    значит вердикт не может стать иным ни при каком состоянии системы.

    Путь собирается из сегментов исходника и проверяется НА ДИСКЕ; собралось
    НЕСКОЛЬКО существующих путей ⇒ `unmeasured` с их перечнем, а не выбор
    одного наугад.
    """
    segments: list[str] = []
    for item in site.get("path_segments", []):
        if item and "\n" not in item and item not in segments:
            segments.append(item)
    # Путь собирается из СМЕЖНЫХ окон сегментов, от самого длинного к самому
    # короткому: `base / "spa_core" / "utils" / "defillama.py"` даёт окно из
    # трёх, и оно существует. Брать отдельный сегмент раньше окна нельзя —
    # первая редакция так ответила «constant (spa_core)» про каталог вместо
    # файла, то есть сказала о дереве правду, а о предмете ложь.
    def _window_joins(length: int) -> list[str]:
        out: list[str] = []
        for start in range(0, len(segments) - length + 1):
            rel = "/".join(part.strip("/") for part in
                           segments[start:start + length])
            if rel and not rel.startswith("/") and ".." not in rel \
                    and rel not in out:
                out.append(rel)
        return out

    file_shaped = [seg for seg in segments
                   if "." in os.path.basename(seg.strip("/"))]
    found: list[str] = []
    for length in range(len(segments), 0, -1):
        found = [rel for rel in _window_joins(length)
                 if os.path.exists(os.path.join(root, rel))]
        if found:
            break
    if len(found) > 1:
        # Несколько путей ОДНОЙ длины — выбор одного из них был бы угадыванием.
        return {"kind": TRACKED_UNMEASURED,
                "reason": f"сегменты дают НЕСКОЛЬКО существующих путей: "
                          f"{sorted(found)[:4]}"}
    if found and os.path.isdir(os.path.join(root, found[0])) and file_shaped \
            and found[0] not in file_shaped:
        # Ответ-КАТАЛОГ при неразмещённом сегменте-имени файла значит, что имя
        # файла реконструкция потеряла: о предмете тогда не известно ничего.
        return {"kind": TRACKED_UNMEASURED,
                "reason": f"реконструкция неполна: собрался каталог "
                          f"{found[0]!r}, а сегмент-имя файла "
                          f"{file_shaped[:2]} не размещён"}
    if not found:
        # Кандидат с расширением — это СОБРАННЫЙ путь, которого на диске нет:
        # присутствие тут выкладкой НЕ обеспечено, и это другой ответ, чем
        # «путь не собрался». Смешать их значило бы выдать незнание за замер.
        if file_shaped:
            return {"kind": TRACKED_ABSENT, "path": file_shaped[0],
                    "reason": "кандидат собрался, на диске его НЕТ ⇒ "
                              "присутствие выкладкой не обеспечено"}
        return {"kind": TRACKED_UNMEASURED,
                "reason": f"путь не собрался из сегментов {segments[:4]}"}
    rel = found[0]
    tracked = _git_lines(["ls-files", "--", rel], root)
    if tracked is None:
        return {"kind": TRACKED_UNMEASURED, "path": rel,
                "reason": "git не ответил о tracked-состоянии"}
    if not tracked:
        return {"kind": TRACKED_WRITER, "path": rel,
                "reason": "untracked ⇒ его писал кто-то"}
    changed = _git_lines(["diff", "--name-only", "HEAD", "--", rel], root)
    if changed is None:
        return {"kind": TRACKED_UNMEASURED, "path": rel,
                "reason": "tracked, но «правлен ли» не спросить"}
    if changed:
        return {"kind": TRACKED_WRITER, "path": rel,
                "reason": "tracked и ПЕРЕПИСАН ⇒ писатель был"}
    return {"kind": TRACKED_CONSTANT, "path": rel,
            "reason": "git-tracked и равен HEAD ⇒ присутствие обеспечено "
                      "`git checkout`, вердикт не зависит от состояния системы"}


def branch_tokens(nodes: Iterable[ast.AST]) -> list[str]:
    """Строки, которые ветка ОБЪЯВЛЯЕТ вердиктом.

    Доказательством считаются ЧЕТЫРЕ формы: строковая константа · имя
    ВЫЗЫВАЕМОЙ функции · имя-константа в ВЕРХНЕМ регистре · имя КЛЮЧЕВОГО
    аргумента (`passed=True` — структурное объявление, а не локальная
    переменная). Простой строчный идентификатор формой НЕ является, и это
    решение с ЗАМЕРОМ: пока он ею был, `card_delivery.validate` попадал в
    находки за `ok.append(absolute)` — локальный список доставляемых путей.

    **Имена самих предикатов (`exists`, `is_file`, …) вычеркнуты.** Иначе
    вызов `p.exists()` внутри ветки читался бы как вердикт «существует», то
    есть мера подтверждала бы себя собой: замер первой редакции — 4 ложные
    находки из 21 ровно этой формы (`director_verify`, `run_identity_key_price`,
    `guardian_forward`).
    """
    out: list[str] = []
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.append(sub.value)
            elif isinstance(sub, ast.Call):
                func = sub.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else None)
                if name and name not in _PREDICATES:
                    out.append(name)
            elif isinstance(sub, ast.Name) and sub.id.isupper():
                out.append(sub.id)
            elif isinstance(sub, ast.Attribute) and sub.attr.isupper():
                out.append(sub.attr)
            elif isinstance(sub, ast.keyword) and sub.arg:
                out.append(sub.arg)
    return out


def _readiness_counters(nodes: Iterable[ast.AST]) -> list[str]:
    """`score += 2` в ветке присутствия — утверждение о ГОТОВНОСТИ.

    Без этой формы `golive_readiness_report` ушёл бы в «вердикт повторяет
    вопрос»: напечатано там только «Promotion engine: present ✓», а
    прибавляются ДВА БАЛЛА готовности к go-live.
    """
    names: list[str] = []
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
                if _READINESS_COUNTERS.match(sub.target.id):
                    names.append(sub.target.id)
    return names


def _match(tokens: Iterable[str], want: re.Pattern[str]) -> list[str]:
    """Совпадения, у которых НЕТ отрицания в той же строке.

    Вето отрицания — построчное: «не прочитан» несёт «прочитан», а
    «SAFE_ADDRESS not configured (ADR-010 exists …)» несёт `exists`. Обе
    строки утверждением НЕ являются, и обе были ложными находками первой
    редакции.
    """
    hits: list[str] = []
    for text in tokens:
        if _ABSENCE.search(text):
            continue
        if want.search(text):
            hits.append(text[:70])
    return hits


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    pmap: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            pmap[child] = node
    return pmap


def _governing_branch(call: ast.AST, pmap: dict[ast.AST, ast.AST]):
    """Ветка, куда дошло значение предиката, и ПОЛЯРНОСТЬ прихода.

    Возвращает ``(node, polarity)`` либо ``None``: `None` значит «ветки нет» —
    это ЦЕНА меры (куда пошёл ответ, не знаем), а не находка.
    """
    cur: ast.AST = call
    polarity = True
    while cur in pmap:
        parent = pmap[cur]
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            polarity = not polarity
        if isinstance(parent, (ast.If, ast.IfExp)) and cur is parent.test:
            return parent, polarity
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.Module, ast.ClassDef)):
            return None
        cur = parent
    return None


def classify_site(call: ast.Call,
                  pmap: dict[ast.AST, ast.AST],
                  binds: dict[str, list[ast.AST]],
                  *, writer_asked: bool) -> dict:
    """Исход ОДНОГО места. Порядок вето объявлен и существен."""
    target = call.args[0] if call.args else (
        call.func.value if isinstance(call.func, ast.Attribute) else None)
    origins = path_origin_strings(target, binds) if target is not None else []
    artefact = any(_ARTEFACT_HINT.search(s) for s in origins)
    segments = (path_segments(target, binds) if target is not None else [])
    base = {"artefact": artefact, "verdict": [], "claim": None,
            "path_segments": segments}

    branch = _governing_branch(call, pmap)
    if branch is None:
        return {**base, "outcome": NO_BRANCH}
    node, polarity = branch
    if isinstance(node, ast.IfExp):
        true_branch: list[ast.AST] = [node.body]
        false_branch: list[ast.AST] = [node.orelse]
    else:
        true_branch = list(node.body)
        false_branch = list(node.orelse)
    present, absent = ((true_branch, false_branch) if polarity
                       else (false_branch, true_branch))

    tokens = branch_tokens(present)
    observed = _match(tokens, _OBSERVATION_WORDS)
    counters = _readiness_counters(present)
    claim = ("observation" if observed
             else "readiness_score" if counters else None)
    evidence = sorted(set(observed or counters))[:3]

    if claim is not None:
        # Вето 1: вердикт стоит на СОДЕРЖИМОМ, а не на присутствии.
        if (_called_names(present) | _called_names([node.test])) & _CONTENT_READERS:
            return {**base, "outcome": CONTENT_CHECKED, "verdict": evidence}
        # Вето 2: дверь спросила ПИСАТЕЛЯ — это эталон ADR-875.
        if writer_asked:
            return {**base, "outcome": WRITER_ASKED, "verdict": evidence}
        return {**base, "outcome": PRESENCE_TO_OBSERVED, "verdict": evidence,
                "claim": claim}

    if _match(tokens, _PRESENCE_WORDS):
        return {**base, "outcome": PRESENCE_RESTATED,
                "verdict": sorted(set(_match(tokens, _PRESENCE_WORDS)))[:3]}
    if _match(tokens, _GENERIC_PASS):
        return {**base, "outcome": PRESENCE_GENERIC_PASS,
                "verdict": sorted(set(_match(tokens, _GENERIC_PASS)))[:3]}
    if any(_ABSENCE.search(text) for text in branch_tokens(absent)):
        return {**base, "outcome": ABSENCE_TO_UNMEASURED}
    return {**base, "outcome": NO_OBSERVATION_VERDICT}


# ── обход дерева ─────────────────────────────────────────────────────────────

def _python_files(root: str, scope: Iterable[str]) -> list[str]:
    found: list[str] = []
    for rel in scope:
        base = os.path.join(root, rel)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            marker = dirpath.replace(os.sep, "/") + "/"
            if any(part in marker for part in _SKIP_PARTS):
                dirnames[:] = []
                continue
            for name in sorted(filenames):
                if name.endswith(".py"):
                    found.append(os.path.join(dirpath, name))
    return sorted(found)


def measure_module(source: str, *, rel: str) -> dict:
    """Исходы всех мест ОДНОГО модуля. Разбор не вышел ⇒ третий исход."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"unmeasured": f"{rel}: не разобран ({exc.__class__.__name__}: {exc})"}
    pmap = _parents(tree)
    module_binds = _bindings(tree)
    sites: list[dict] = []
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for func in funcs:
        # Привязки дедуплицируются ПО УЗЛУ: `_bindings(tree)` обходит всё
        # дерево, включая тела функций, поэтому одно присваивание попадало в
        # список ДВАЖДЫ — и сегменты пути собирались как
        # `spa_core/utils/defillama.py/spa_core/utils/defillama.py`, то есть
        # живая ось отвечала про каталог `spa_core` вместо файла.
        binds: dict[str, list[ast.AST]] = {}
        for source_map in (module_binds, _bindings(func)):
            for key, values in source_map.items():
                bucket = binds.setdefault(key, [])
                known = {id(node) for node in bucket}
                bucket.extend(v for v in values if id(v) not in known)
        body_src = ast.get_source_segment(source, func) or ""
        writer = bool(_WRITER_QUESTION.search(body_src))
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else None)
            if name not in _PREDICATES:
                continue
            verdict = classify_site(node, pmap, binds, writer_asked=writer)
            verdict.update({"file": rel, "line": node.lineno,
                            "col": node.col_offset,
                            "function": func.name, "predicate": name})
            sites.append(verdict)
    return {"sites": sites}


def finding_key(site: dict) -> str:
    """Стабильное имя находки — для карточек и для сверки «та же ли это»."""
    col = site.get("col")
    where = f"{site['line']}" if col is None else f"{site['line']}:{col}"
    return f"{site['file']}:{where} [{site['function']}]"


def shell_surface(root: str) -> dict:
    """Сколько мест того же вопроса живёт в оболочке и воркфлоу.

    Разбор НЕ сделан, поэтому число печатается как НЕ ИЗМЕРЕНО — не как ноль.
    Читается `test -f` / `test -e` / `[ -f` в `*.sh` и `*.yml` воркфлоу.
    """
    rx = re.compile(r"(test\s+-[fed]\s|\[\s+-[fed]\s|\[\[\s+-[fed]\s)")
    sites = 0
    files = 0
    unreadable: list[str] = []
    for rel in ("scripts", ".github/workflows", "launchd"):
        base = os.path.join(root, rel)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in sorted(filenames):
                if not name.endswith((".sh", ".yml", ".yaml", ".bash")):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    text = open(full, encoding="utf-8", errors="replace").read()
                except OSError as exc:
                    unreadable.append(f"{os.path.relpath(full, root)}: {exc}")
                    continue
                hits = len(rx.findall(text))
                if hits:
                    files += 1
                    sites += hits
    return {"sites": sites, "files": files, "unreadable": unreadable,
            "verdict": "unmeasured"}


def measure(root: str | None = None,
            scope: Iterable[str] = DEFAULT_SCOPE) -> dict:
    """Перепись целиком. Корень не прочитан ⇒ вердикт НЕ ИЗМЕРЕНО с причиной."""
    root = os.path.abspath(root or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if not os.path.isdir(root):
        return {"verdict": "unmeasured",
                "reason": f"корень дерева не прочитан: {root}"}
    files = _python_files(root, scope)
    if not files:
        return {"verdict": "unmeasured",
                "reason": (f"в {root} ни одного python-модуля по областям "
                           f"{tuple(scope)} — мерить нечего, и это НЕ «чисто»")}
    counts = {outcome: 0 for outcome in OUTCOMES}
    claims = {claim: 0 for claim in CLAIMS}
    findings: list[dict] = []
    generic_pass: list[dict] = []
    unmeasured_files: list[str] = []
    for full in files:
        rel = os.path.relpath(full, root).replace(os.sep, "/")
        try:
            source = open(full, encoding="utf-8").read()
        except OSError as exc:
            unmeasured_files.append(f"{rel}: не прочитан ({exc})")
            continue
        report = measure_module(source, rel=rel)
        if "unmeasured" in report:
            unmeasured_files.append(report["unmeasured"])
            continue
        for site in report["sites"]:
            counts[site["outcome"]] += 1
            if site["outcome"] == PRESENCE_TO_OBSERVED:
                findings.append(site)
                claims[site["claim"]] += 1
            elif site["outcome"] == PRESENCE_GENERIC_PASS:
                generic_pass.append(site)
    # Живая ось — только у НАХОДОК: она отвечает на вопрос «а вердикт тут
    # вообще может стать иным», и задавать его 2277 раз значило бы 2277
    # процессов git ради строк, которые находками не являются.
    tracked_kinds = {TRACKED_CONSTANT: 0, TRACKED_WRITER: 0,
                     TRACKED_ABSENT: 0, TRACKED_UNMEASURED: 0}
    for site in findings:
        axis = tracked_constant_axis(site, root=root)
        site["tracked"] = axis
        tracked_kinds[axis["kind"]] += 1
    verdict = ("unmeasured" if unmeasured_files
               else "findings" if findings else "clean")
    return {
        "verdict": verdict,
        "root": root,
        "scope": list(scope),
        "module_count": len(files),
        "site_count": sum(counts.values()),
        "counts": counts,
        "claims": claims,
        "tracked_kinds": tracked_kinds,
        "findings": sorted(findings, key=finding_key),
        "generic_pass_sites": sorted(generic_pass, key=finding_key),
        "unmeasured_files": unmeasured_files,
        "shell_surface": shell_surface(root),
    }


def exit_code(report: dict) -> int:
    if report.get("verdict") == "unmeasured":
        return RC_UNMEASURED
    return RC_FINDINGS if report.get("findings") else RC_CLEAN


# ── живая ось: различает ли мера ДВА направления ─────────────────────────────

#: Сцена ЭТАЛОНА — отсутствие ⇒ «не измерено» (инв. #17), находкой НЕ является.
SCENE_HONEST = '''
import os
def check(path):
    if not os.path.exists(path):
        return "НЕ ИЗМЕРЕНО: файла нет"
    return load(path)
'''

#: Сцена ВЕТО ОТРИЦАНИЯ — присутствие ⇒ «не прочитан». Находкой НЕ является:
#: отрицание утверждением не бывает. Дословная форма `consume_office_reports`.
SCENE_NEGATED = '''
import os
P = "data/office_report.json"
def step():
    if os.path.exists(P):
        return "JSON не прочитан"
    return "файла нет"
'''

#: Сцена ДЕФЕКТА — присутствие ⇒ «наблюдено» (дословный ADR-875).
SCENE_DEFECT = '''
import os
DATA_PATH = "data/office_report.json"
def check():
    if os.path.exists(DATA_PATH):
        return "прочитано: писатель был"
    return "НЕ ПРОЧИТАН"
'''

DRIVE_DISTINGUISHES = "distinguishes"
DRIVE_BLIND = "blind"
DRIVE_UNMEASURED = "unmeasured"


def drive_both_directions() -> dict:
    """Положительный контроль ВНУТРИ прибора: две сцены, РАЗНЫЕ вердикты.

    Отвечает на то, чего население не знает: что различение направлений
    ДОСТИЖИМО, а не только описано. Мера, назвавшая находкой честный отказ
    (или промолчавшая на дефекте), есть ровно тот класс, который она мерит.
    """
    scenes = {"honest": SCENE_HONEST, "negated": SCENE_NEGATED,
              "defect": SCENE_DEFECT}
    kinds: dict[str, set[str]] = {}
    for label, source in scenes.items():
        try:
            report = measure_module(source, rel=f"scene_{label}.py")
        except Exception as exc:                                # noqa: BLE001
            return {"kind": DRIVE_UNMEASURED,
                    "reason": f"сцена {label} не поднялась: "
                              f"{type(exc).__name__}: {exc}"}
        if "unmeasured" in report:
            return {"kind": DRIVE_UNMEASURED,
                    "reason": f"сцена {label} не разобрана: {report['unmeasured']}"}
        kinds[label] = {site["outcome"] for site in report["sites"]}
    # Три звена, и любое одно порванное даёт `blind` с ИМЕНЕМ звена.
    if PRESENCE_TO_OBSERVED in kinds["honest"]:
        return {"kind": DRIVE_BLIND, "link": "honest",
                "reason": "честный отказ «файла нет ⇒ не измерено» назван находкой — "
                          "мера судит по наличию exists(), а не по направлению"}
    if PRESENCE_TO_OBSERVED in kinds["negated"]:
        return {"kind": DRIVE_BLIND, "link": "negated",
                "reason": "«не прочитан» в ветке присутствия прочитано как "
                          "утверждение — снято вето отрицания"}
    if PRESENCE_TO_OBSERVED not in kinds["defect"]:
        return {"kind": DRIVE_BLIND, "link": "defect",
                "reason": f"дефект ADR-875 мерой НЕ найден (исходы сцены: "
                          f"{sorted(kinds['defect'])}) — перепись слепа к "
                          f"своему предмету"}
    return {"kind": DRIVE_DISTINGUISHES,
            **{label: sorted(value) for label, value in kinds.items()}}


# ── CLI ──────────────────────────────────────────────────────────────────────

def render(report: dict) -> list[str]:
    if report.get("verdict") == "unmeasured" and "reason" in report:
        return [f"НЕ ИЗМЕРЕНО: {report['reason']}"]
    counts = report["counts"]
    claims = report["claims"]
    lines = [
        f"перепись «присутствие выдано за наблюдение» (ADR-875) — "
        f"модулей {report['module_count']}, мест {report['site_count']}",
        f"  НАХОДКИ presence_to_observed: {counts[PRESENCE_TO_OBSERVED]}"
        f" (словом о наблюдении {claims['observation']} · баллом готовности "
        f"{claims['readiness_score']})",
        f"  эталон (отсутствие ⇒ не измерено): {counts[ABSENCE_TO_UNMEASURED]}",
        f"  вето «вердикт на СОДЕРЖИМОМ»: {counts[CONTENT_CHECKED]}"
        f" · вето «спросил ПИСАТЕЛЯ»: {counts[WRITER_ASKED]}",
        f"  НЕ ИЗМЕРЕНО (родовое «прошло», предмет критерия не назван): "
        f"{counts[PRESENCE_GENERIC_PASS]}"
        f" · вердикт ПОВТОРЯЕТ вопрос (тавтология, не находка): "
        f"{counts[PRESENCE_RESTATED]}",
        f"  ЦЕНА меры: без вердикта о наблюдении {counts[NO_OBSERVATION_VERDICT]}"
        f" · без объемлющей ветки {counts[NO_BRANCH]}",
        f"  живая ось у находок: вердикт КОНСТАНТА "
        f"{report['tracked_kinds'][TRACKED_CONSTANT]} · писатель был "
        f"{report['tracked_kinds'][TRACKED_WRITER]} · на диске НЕТ "
        f"{report['tracked_kinds'][TRACKED_ABSENT]} · НЕ ИЗМЕРЕНО "
        f"{report['tracked_kinds'][TRACKED_UNMEASURED]}",
    ]
    for site in report["findings"]:
        mark = "живой артефакт" if site["artefact"] else "путь не разобран как артефакт"
        tracked = site.get("tracked") or {}
        lines.append(f"  ❌ {finding_key(site)} {site['predicate']}() ⇒ "
                     f"{site['claim']}: {site['verdict']}  [{mark}]")
        lines.append(f"       живая ось: {tracked.get('kind')} — "
                     f"{tracked.get('reason')}"
                     + (f" ({tracked['path']})" if tracked.get("path") else ""))
    for site in report["generic_pass_sites"]:
        lines.append(f"  ?  {finding_key(site)} {site['predicate']}() ⇒ "
                     f"{site['verdict']} — критерий объявлен не кодом ветки, "
                     f"предмет НЕ ИЗМЕРЕН")
    shell = report["shell_surface"]
    lines.append(f"  НЕ ИЗМЕРЕНО: оболочка/воркфлоу — {shell['sites']} мест в "
                 f"{shell['files']} файлах (разбор не сделан, это НЕ ноль)")
    for item in report["unmeasured_files"]:
        lines.append(f"  НЕ ИЗМЕРЕНО: {item}")
    lines.append("ADVISORY: прибор только ЧИТАЕТ исходники — RiskPolicy v1.0, "
                 "стоп-кран, живой трек и landing/ не трогает")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Перепись класса ADR-875: кто выдаёт присутствие файла за "
                    "доказательство живого писателя.")
    parser.add_argument("--root", default=None, help="корень дерева")
    parser.add_argument("--scope", nargs="*", default=list(DEFAULT_SCOPE),
                        help="области обхода (умолчание spa_core scripts)")
    parser.add_argument("--json", action="store_true", help="замер как JSON")
    parser.add_argument("--drive", action="store_true",
                        help="только живая ось: различает ли мера направления")
    args = parser.parse_args(argv)

    if args.drive:
        drive = drive_both_directions()
        print(json.dumps(drive, ensure_ascii=False, indent=2))
        return {DRIVE_DISTINGUISHES: RC_CLEAN,
                DRIVE_BLIND: RC_FINDINGS}.get(drive["kind"], RC_UNMEASURED)

    report = measure(args.root, args.scope)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in render(report):
            print(line)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
