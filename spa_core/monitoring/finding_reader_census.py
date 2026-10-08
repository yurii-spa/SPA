"""Перепись: у произведённой НАХОДКИ нет читателя внутри цикла.

Заказ владельца **G86 п. 4** (хвост [ADR-475](../../docs/decisions/ADR-475-publisher-stuck-is-not-deploy-lag.md),
стои́т остатком с 25.09 и перевыставлялся восемнадцатью заказами):

> У находки ``PUBLISHER_STUCK`` внутри цикла ЧИТАТЕЛЯ нет. Отчёт кустодиана доходит до
> человека двумя каналами — тревогой в Телеграм и красной джобой, — и ни один из них не
> читает шаг 0-офис: ``data/site_freshness_report.json`` в перечне артефактов офиса (97
> прочитанных) не значится. Объявить его с SLO нельзя механически: на Маке локальный
> кустодиан не загружен (``intent=designed``), в прод-дереве лежит тот же фоссил от 04.07,
> и объявление дало бы ПОСТОЯННЫЙ красный, чинимый только деплоем агента (действие
> владельца). **Спросить надо по порядку: сначала кто ПИШЕТ этот артефакт на Маке, и
> только потом — кто его читает.** Замер обязателен до объявления, иначе SLO станет
> украшением.

## Почему порядок ног есть часть утверждения

Оба вопроса дают одно и то же слово «нет», и означают они противоположное.

* Читателя нет, а писателя нет тоже ⇒ объявить читателя значит завести **вечный красный**,
  который не чинится работой цикла вовсе: нужен деплой агента, то есть действие владельца
  (инв. #12). Такое объявление и есть украшение, против которого написан заказ.
* Читателя нет, а писатель **жив и пишет** ⇒ находка производится каждые несколько часов
  и **не доходит ни до кого**, кто по ней действует. Вот это и есть вред.

Поэтому нога писателя спрашивается ПЕРВОЙ, и спрашивается она у **наблюдения** (есть ли
свежий артефакт в дереве), а не у объявления: поле ``intent`` в конституции есть намерение
владельца, и ADR-475 отказался объявлять SLO ровно по нему. Объявление участвует только
тогда, когда наблюдение уже сказало «свежего артефакта нет» — чтобы РАЗЛИЧИТЬ «агент снят с
флота» (``retired``), «агент не загружен» (``designed``) и «агент объявлен живым, а не
пишет» (``writer_silent``): три разные починки, и сливать их в одну значило бы повторить
ошибку, ради которой заказ и написан.

## Исходы (форма ЗАКРЫТА, сумма равна населению, инв. #17)

Ноги спрашиваются в ЭТОМ порядке:

1. ``writer_retired`` — свежего артефакта нет, агент снят с флота. Читателя объявлять
   нечему: производства нет и не будет.
2. ``writer_not_loaded`` — свежего артефакта нет, агент объявлен, но не загружен. Это
   дословно состояние кустодиана на 25.09 и положительный контроль исхода.
3. ``writer_silent`` — свежего артефакта нет, а агент объявлен ЖИВЫМ. Отдельная беда и
   отдельная починка (чинится писателем), в вопрос о читателе не сливается.
4. ``read_by_the_cycle`` — артефакт объявлен в ``artifacts[]`` активным с потребителем
   ``orchestrator_protocol``. Шаг 0-офис читает РОВНО этот перечень, поэтому здесь
   «объявлено» и «прочитано» совпадают по построению, а не по обещанию.
5. ``read_by_another_declared_consumer`` — объявлен, но потребитель другой. Это
   ОБЪЯВЛЕНИЕ: что названный потребитель действительно читает файл, перепись не
   проверяет, и потому исход зовётся ``declared``, а не ``read``-и-точка.
6. ``read_by_another_agent`` — путь стои́т в ``consumes`` другого агента флота. Тоже
   объявление, и тоже названо им.
7. ``read_in_code_by_another_module`` — модуль под ``spa_core/``/``scripts/``, который
   этот файл ЧИТАЕТ и НЕ пишет. Чтение своего же вывода читателем не считается: это
   вопрос «предыдущего прогона» (ADR-524), а не этот.
8. ``no_reader_found`` — **находка заказа**: производится и не читается никем.
9. ``unmeasured:<причина>`` — громкий третий исход с НАЗВАННОЙ причиной. Никогда не ноль
   и никогда не «чисто».

## Форма находки — отдельная ось, а не слагаемое, и она ОДНОСТОРОННЯЯ

Вред заказа острее, когда непрочитанный артефакт несёт НАХОДКИ, а не просто число. Ось
считается ОТДЕЛЬНО (``finding_key_present`` / ``finding_key_absent_not_proof`` /
``shape_unmeasured``) и в сумму исходов не входит: смешать их значило бы сделать сумму
непроверяемой.

Форма спрашивается у СХЕМЫ, а не у сегодняшнего содержимого: артефакт с пустым ``fails``
сегодня несёт находки завтра, и объявлять его безобидным по одному спокойному дню было бы
ровно той подменой, против которой написан инв. #17.

**Односторонность оси названа ЧИСЛОМ, а не оговоркой.** Перечень ключей ЗАКРЫТ (их
двадцать три), а словарь населения ИЗМЕРЕН — 1137 различных ключей верхнего уровня.
Закрытый перечень такого размера против такого словаря по построению не может отвечать
«находок не несёт», поэтому отрицательный исход и зовётся ``..._not_proof``. Ошибка идёт
в сторону ЗАНИЖЕНИЯ вреда: острая форма находки (читателя нет И находки есть) есть
**нижняя граница**, и это сказано вслух, а не спрятано.

## Односторонность — НАЗВАНА ЗАРАНЕЕ, и каждая клауза ПОНИЖАЕТ находку

- **Читатель в коде ищется по ИМЕНИ ФАЙЛА, а не по адресу** (ADR-465: имя не есть адрес).
  Два артефакта с одинаковым базовым именем (``status.json`` лежит в дереве не раз)
  сливаются, и чужой читатель зачтётся как свой. Ошибка идёт в сторону «читатель есть» ⇒
  ``no_reader_found`` есть **нижняя граница**.
- **Радиус читателя** — ``spa_core/`` и ``scripts/``, без тестов: тест, читающий артефакт,
  есть фикстура, а не читатель дерева.
- **Запись видна на один уровень помощника** — ровно столько, сколько видит сосед
  ``prior_run_operand_census`` (его разбор и переиспользуется, второй копии правила нет).
- **Объявление ≠ чтение.** Исходы 5 и 6 названы ``declared``: потребитель объявлен в
  конституции, и читает ли он файл на самом деле — следующий вопрос, здесь не измеренный.
- **Свежесть спрашивается только там, где срок ОБЪЯВЛЕН.** У артефакта без ``slo_hours``
  наблюдением считается само присутствие файла, и строка несёт признак
  ``freshness_undeclared``: «файл есть» слабее, чем «писатель жив», и выдавать одно за
  другое перепись не вправе.

ADVISORY: прибор только ЧИТАЕТ (``applied=False``). Ни строки risk-логики, стоп-крана
просадки, аллокатора, гейта исполнения, живого трека, ``landing/**`` или флота он не
меняет и менять не может.
"""

from __future__ import annotations

import argparse
import ast
import collections
import datetime as dt
import json
import os
import pathlib
import re
import sys

from spa_core.monitoring.agent_code_freshness import _module_file, import_closure
from spa_core.monitoring.entrypoint_import_probe import resolve_wrapper_target
from spa_core.monitoring.prior_run_operand_census import (
    SOURCE_ROOTS,
    _PathResolver,
    _artifact_literals,
    _sites,
)

APPLIED = False

#: Заказ, которым эта перепись поставлена.
ORDER = "G86.4"

#: Потребитель, чьё объявление ОЗНАЧАЕТ чтение: шаг 0-офис обходит ровно те артефакты
#: ``artifacts[]``, у которых он значится в ``consumers`` (`scripts/consume_office_reports.py`).
CYCLE_CONSUMER = "orchestrator_protocol"

#: Форма исхода ЗАКРЫТА. Сумма по перечню обязана равняться населению, и каждый ноль
#: объявляется явно (инв. #17): «такого исхода нет» и «исход не считался» — разное.
VERDICTS = (
    "writer_retired",
    "writer_not_loaded",
    "writer_silent",
    "read_by_the_cycle",
    "read_by_another_declared_consumer",
    "read_by_another_agent",
    "read_in_code_by_another_module",
    "no_reader_found",
    "unmeasured",
)

#: Ключи, ИМЕНУЮЩИЕ множество проблем. Перечень ЗАКРЫТ и собран не из головы, а
#: отбором по ИЗМЕРЕННОМУ словарю населения (замер 30.09: 1137 различных ключей
#: верхнего уровня у 195 произведённых артефактов). Спрашивается присутствие КЛЮЧА, а
#: не непустота значения: пустой сегодня `fails` завтра не пуст, и объявить артефакт
#: безобидным по одному спокойному дню значило бы подменить форму содержимым.
#:
#: Попадание — ДОКАЗАТЕЛЬСТВО, что артефакт несёт находки. Промах доказательством
#: обратного НЕ является и так и называется (`finding_key_absent_not_proof`): закрытый
#: перечень из двух десятков имён против словаря в 1137 имён по построению НЕ может
#: отвечать «находок не несёт». `data/watchdog_alerts.json` — живой пример промаха:
#: ключи верхнего уровня там суть ЯРЛЫКИ АГЕНТОВ, а тревоги лежат под ними.
FINDING_KEYS = (
    "fails", "n_fails", "failures", "findings", "alerts", "violations", "issues",
    "problems", "errors", "error", "red_flags", "anomalies", "breaches", "warnings",
    "severity", "critical", "stale", "n_stale", "any_stale", "unreadable",
    "corrupt_history_lines", "concern", "triggered",
)

#: Оси формы. Отрицательная названа так, чтобы её нельзя было прочесть как «чисто».
SHAPES = ("finding_key_present", "finding_key_absent_not_proof", "shape_unmeasured")

#: Исходы, которые суть ОБЪЯВЛЕНИЕ, а не замер чтения. Заказ G105 п. 3 поставлен ровно
#: на них: «спросить у кода, читает ли названный потребитель этот путь на самом деле».
DECLARATION_VERDICTS = ("read_by_another_declared_consumer", "read_by_another_agent")

#: Ось «подтверждено ли ОБЪЯВЛЕНИЕ кодом» (заказ G105 п. 3). Считается ТОЛЬКО у рядов,
#: чей исход есть объявление, в сумму исходов НЕ входит — иначе сумма перестала бы
#: проверяться против населения.
#:
#: Форма ЗАКРЫТА и устроена так, чтобы ОБА её крайних значения были доказательствами,
#: а вся неуверенность уходила в середину с НАЗВАННОЙ причиной:
#:
#: * ``declaration_confirmed`` — СВОЙ файл названного потребителя читает этот путь.
#:   Доказательство: разбор нашёл место чтения прямо в нём.
#: * ``declaration_unbacked`` — **находка заказа**: во всём коде, достижимом импортом
#:   от названного потребителя, путь не упомянут ВОВСЕ — ни чтением, ни записью, ни
#:   литералом. Читать нечем, и объявление пусто.
#: * ``declaration_unmeasured:<причина>`` — громкий третий исход. Сюда уходит ВСЁ, что
#:   не доказано ни в ту, ни в другую сторону, и причина называется.
#:
#: Почему чтение из импортного замыкания — это «не измерено», а не «подтверждено»:
#: замыкание входа агента в этом дереве — **шестьсот с лишним файлов**, и «кто-то в
#: замыкании читает этот путь» отвечает утвердительно почти на любой популярный
#: артефакт. Импорт не есть вызов (урок `wiring ratchet counts an import as a call`),
#: поэтому такая пара называется неизмеренной, а не прочитанной.
CLAIMS = ("declaration_confirmed", "declaration_unbacked", "declaration_unmeasured")


# ─────────────────────────────────────────────────────────────────────────────────────
# Конституция
# ─────────────────────────────────────────────────────────────────────────────────────

def _load_manifest(root):
    path = root / "architecture" / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"manifest_unreadable:{type(exc).__name__}"


def _listed(manifest, key):
    """Перечень конституции по ключу — проверкой ТИПА, а не `or`-падением.

    `x or []` неразличимо представляет «ключа нет», «список пуст» и «там ноль» (инв.
    #17), поэтому новый код этой формы не вводит. Три ПРЕЖНИХ её места в этом модуле
    намеренно НЕ тронуты: храповик `test_absent_observation_ratchet` красен на чистом
    `origin/main` от ТРЁХ ЧУЖИХ членов класса, и снятие своих трёх в том же пуше
    смешало бы два изменения — чьё падение чьё, стало бы не видно. Понижение класса
    здесь — отдельная работа, и она разрешена (база может только убывать).
    """
    value = manifest.get(key)
    return value if isinstance(value, list) else []


def _population(manifest):
    """Пары (агент, произведённый артефакт) — ровно то, что объявляет конституция."""
    pairs = []
    for agent in manifest.get("agents") or []:
        for produced in agent.get("produces") or []:
            path = produced.get("artifact")
            if not path:
                continue
            pairs.append({
                "agent": agent.get("label"),
                "intent": agent.get("intent"),
                "artifact": path,
                "slo_hours": produced.get("slo_hours"),
            })
    return pairs


def _declared_consumers(manifest):
    """path → множество потребителей у АКТИВНОЙ строки ``artifacts[]``."""
    out = collections.defaultdict(set)
    for art in manifest.get("artifacts") or []:
        if art.get("status") != "active":
            continue
        out[art.get("path")] |= set(art.get("consumers") or [])
    return out


def _agent_consumes(manifest):
    """path → множество агентов, объявивших путь в ``consumes``."""
    out = collections.defaultdict(set)
    for agent in manifest.get("agents") or []:
        for path in agent.get("consumes") or []:
            out[path].add(agent.get("label"))
    return out


# ─────────────────────────────────────────────────────────────────────────────────────
# Наблюдение: пишется ли артефакт на этой машине
# ─────────────────────────────────────────────────────────────────────────────────────

def _artifact_mtime(full, *, stat=os.stat, scandir=os.scandir):
    """Отметка времени артефакта: файл — своя, каталог — самой свежей записи внутри.

    Двери к ОС приходят ВХОДОМ (`.claude/rules/deployment.md`: живость — вход, а не
    окружение). Отказ ОС в правах воспроизводится подстановкой двери, а не `chmod` на
    живой машине: тест, чей исход решает хост, и есть бомба, против которой написано
    правило про личность процесса.
    """
    try:
        st = stat(full)
    except OSError as exc:
        return None, f"stat_failed:{type(exc).__name__}"
    if not os.path.isdir(full):
        return st.st_mtime, None
    newest = None
    try:
        for entry in scandir(full):
            try:
                ts = entry.stat().st_mtime
            except OSError:
                continue
            newest = ts if newest is None else max(newest, ts)
    except OSError as exc:
        return None, f"scandir_failed:{type(exc).__name__}"
    if newest is None:
        return None, "directory_empty"
    return newest, None


def _writer_observed(row, *, data_dir, now):
    """Наблюдение о писателе. Возвращает ``(observed, note)``.

    ``observed`` истинно, когда в дереве лежит артефакт, и — если срок ОБЪЯВЛЕН — он
    свежее срока. Срок не объявлен ⇒ наблюдением считается присутствие, и об этом
    говорится признаком ``freshness_undeclared``, а не молчанием.
    """
    rel = row["artifact"]
    if rel.startswith("data/"):
        full = os.path.join(data_dir, rel[len("data/"):])
    else:
        full = os.path.join(os.path.dirname(data_dir.rstrip(os.sep)), rel)
    if not os.path.exists(full):
        return False, "artifact_absent"
    mtime, why = _artifact_mtime(full)
    if mtime is None:
        return False, why
    age_h = (now.timestamp() - mtime) / 3600.0
    row["age_hours"] = round(age_h, 2)
    slo = row.get("slo_hours")
    if slo is None:
        return True, "freshness_undeclared"
    if age_h > float(slo):
        return False, f"stale:{age_h:.1f}h>{float(slo):g}h"
    return True, None


# ─────────────────────────────────────────────────────────────────────────────────────
# Читатели в коде
# ─────────────────────────────────────────────────────────────────────────────────────

def _code_sites(root):
    """``(читатели, записанное по модулям, УПОМЯНУТОЕ по именам, разобранные, …)``.

    Разбор переиспользован у соседа ADR-524: второй копии правила «что есть запись» и
    «что есть чтение» в дереве быть не должно — ровно тот дефект, который ловит
    ``rule_second_copy_census`` (ADR-522).

    ``mentions`` — третья, САМАЯ СЛАБАЯ проба того же разбора: имя артефакта встречается
    в модуле ЛИТЕРАЛОМ, безразлично к месту (чтение, запись, перечень, аргумент
    помощника, которого разбор не опознал). Она нужна оси объявлений: «упомянут, но
    места чтения разбор не нашёл» и «не упомянут нигде» — разные ответы, и сливать их
    значило бы объявлять находкой верхнюю границу. Литерал опознаётся ТЕМ ЖЕ правилом
    (``_artifact_literals``), а не второй его копией, поэтому прозаическое вкрапление
    вроде ``f"копится ({name})"`` упоминанием НЕ становится: у него хвост не есть имя
    файла.
    """
    reads = collections.defaultdict(set)
    writes_by_module = collections.defaultdict(set)
    mentions = collections.defaultdict(set)
    parsed = set()
    unparsed = []
    seen_any = False
    for base in SOURCE_ROOTS:
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            rel = str(path.relative_to(root))
            if "/tests/" in rel or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, ValueError, UnicodeDecodeError) as exc:
                unparsed.append({"module": rel, "reason": f"unparsed:{type(exc).__name__}"})
                continue
            seen_any = True
            parsed.add(rel)
            w, r = _sites(tree, _PathResolver(tree))
            for name in w:
                writes_by_module[rel].add(name)
            for name in r:
                reads[name].add(rel)
            for name in _artifact_literals(tree):
                mentions[name].add(rel)
    return reads, writes_by_module, mentions, parsed, unparsed, seen_any


def _module_index(parsed):
    """``имя модуля без расширения → пути`` из УЖЕ РАЗОБРАННЫХ модулей.

    Нужен для потребителей, названных ОДНИМ СЛОВОМ (``cycle_health_monitor``). Слово
    адресом не является: ниже оно разрешается в адрес, и неоднозначность объявляется
    третьим исходом, а не выбором «первого похожего».

    Строится из ``parsed`` обхода выше, а не своим обходом дерева: иначе правило «что
    считается модулем этого дерева» (корни исходников, отсев фикстур) получило бы
    вторую копию — ровно тот дефект, который ловит ``rule_second_copy_census``.
    """
    out = collections.defaultdict(set)
    for rel in parsed:
        out[pathlib.PurePath(rel).stem].add(rel)
    return out


# ─────────────────────────────────────────────────────────────────────────────────────
# Ось «подтверждено ли ОБЪЯВЛЕНИЕ кодом» (заказ G105 п. 3)
# ─────────────────────────────────────────────────────────────────────────────────────

_BARE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _repo_relative(target, root):
    """Абсолютный путь обёртки → путь ВНУТРИ этого дерева, или ``None``.

    Обёртка объявляет корень ПРОД-дерева литералом, поэтому её цель указывает мимо
    одноразового дерева замера. Срезается по первому корню исходников: иначе замер из
    worktree судил бы о файлах прод-дерева — ровно тот дефект, которым отличается
    «пушер разрешает относительные пути к прод-дереву».
    """
    parts = pathlib.PurePath(target).parts
    for base in SOURCE_ROOTS:
        if base in parts:
            rel = pathlib.PurePath(*parts[parts.index(base):])
            if (root / rel).is_file():
                return str(rel)
            return None
    return None


def _consumer_addresses(name, *, root, agents, module_index):
    """``([адрес кода], причина)`` для ИМЕНИ потребителя из конституции.

    Ровно один адрес ⇒ причина пуста. Ноль или несколько ⇒ адреса не названы, а
    причина названа: выбирать «первый похожий» значило бы выдать догадку за замер.
    """
    name = (name or "").strip()
    if name.endswith(".py"):
        return ([name], "") if (root / name).is_file() else ([], f"consumer_path_absent:{name}")

    if name.startswith("com.spa."):
        agent = agents.get(name)
        if agent is None:
            return [], "consumer_agent_absent_from_the_constitution"
        program = agent.get("program")
        if not program:
            return [], "consumer_agent_declares_no_program"
        wrapper = root / "scripts" / program
        if not wrapper.is_file():
            return [], f"consumer_wrapper_absent:{program}"
        info = resolve_wrapper_target(str(wrapper), default_repo_root=str(root))
        if info.get("structural"):
            return [], "consumer_wrapper_is_a_multi_step_script_not_one_target"
        if info.get("kind") == "module":
            f = _module_file(info["target"], root)
            return ([str(f.relative_to(root))], "") if f else ([], "consumer_module_outside_the_tree")
        if info.get("kind") == "script":
            rel = _repo_relative(info["target"], root)
            return ([rel], "") if rel else ([], "consumer_script_outside_the_parsed_source_roots")
        return [], "consumer_wrapper_target_unresolved"

    if not _BARE_NAME_RE.match(name):
        return [], "consumer_name_is_not_a_code_address"

    found = set(module_index.get(name, ()))
    wrapper = root / "scripts" / f"agent_{name}.sh"
    if wrapper.is_file():
        info = resolve_wrapper_target(str(wrapper), default_repo_root=str(root))
        if info.get("kind") == "module":
            f = _module_file(info["target"], root)
            if f:
                found.add(str(f.relative_to(root)))
        elif info.get("kind") == "script":
            rel = _repo_relative(info["target"], root)
            if rel:
                found.add(rel)
    if len(found) == 1:
        return [found.pop()], ""
    if not found:
        return [], "consumer_name_is_not_a_code_address"
    return [], f"consumer_name_resolves_to_{len(found)}_code_addresses"


def _claim_for(artifact, consumer, *, root, agents, module_index, reads, mentions,
               parsed, shared, closures=None):
    """``(исход оси, подробность)`` для ОДНОЙ пары «артефакт ← названный потребитель».

    ``closures`` — память замыканий на один замер. Замыкание входа агента есть 600+
    файлов, у соседних пар вход один и тот же, и считать его заново значило бы
    удвоить цену шага 0-офис без единого нового ответа.
    """
    addresses, why = _consumer_addresses(consumer, root=root, agents=agents,
                                         module_index=module_index)
    if why:
        return "declaration_unmeasured", why
    entry = addresses[0]
    if entry not in parsed:
        return "declaration_unmeasured", f"consumer_module_not_parsed:{entry}"

    name = os.path.basename(artifact)
    if "." not in name:
        return "declaration_unmeasured", "code_reader_not_measurable_for_a_directory"

    if entry in reads.get(name, frozenset()):
        if shared > 1:
            # Разбор читателей опознаёт ИМЯ ФАЙЛА, а не адрес (ADR-465). Когда имя
            # носят несколько произведённых артефактов, попадание не доказывает, что
            # читается ИМЕННО этот путь: `latest.json` в этом дереве носят трое.
            return ("declaration_unmeasured",
                    f"confirmed_only_by_an_ambiguous_basename:{name}:{shared}")
        return "declaration_confirmed", entry

    # Короткий ход, и он же САМЫЙ ЧАСТЫЙ у находки: если путь не читает и не упоминает
    # НИ ОДИН модуль дерева, то его не содержит и любое замыкание — считать замыкание
    # нечего. Ответ тот же, цена нулевая, и усечение замыкания здесь не при чём: полное
    # замыкание читателя тоже не содержало бы.
    if not reads.get(name, frozenset()) and not mentions.get(name, frozenset()):
        return "declaration_unbacked", entry

    if closures is None:
        closures = {}
    if entry not in closures:
        closure, truncated = import_closure(root / entry, root)
        reachable = set()
        for path in closure:
            try:
                reachable.add(str(path.relative_to(root)))
            except ValueError:
                continue
        closures[entry] = (reachable, truncated)
    reachable, truncated = closures[entry]
    far = sorted(reachable & reads.get(name, frozenset()))
    if far:
        return "declaration_unmeasured", f"read_reachable_only_through_the_import_closure:{far[0]}"
    named = sorted(reachable & mentions.get(name, frozenset()))
    if named:
        return "declaration_unmeasured", f"named_in_code_but_no_read_site_parsed:{named[0]}"
    if truncated:
        return "declaration_unmeasured", "import_closure_truncated"
    return "declaration_unbacked", entry


def _row_claim(pairs):
    """Исход оси для РЯДА из исходов его пар.

    Подтверждает ряд ОДИН подтверждённый потребитель: «читает хоть кто-то из названных»
    и есть вопрос. Пустым объявление ряда зовётся только тогда, когда пусты ВСЕ его
    объявления; смешанный ряд — третий исход, а не находка.
    """
    kinds = {k for k, _ in pairs}
    if "declaration_confirmed" in kinds:
        return "declaration_confirmed"
    if kinds == {"declaration_unbacked"}:
        return "declaration_unbacked"
    return "declaration_unmeasured"


# ─────────────────────────────────────────────────────────────────────────────────────
# Ось «несёт ли находки»
# ─────────────────────────────────────────────────────────────────────────────────────

def _finding_shape(row, *, data_dir):
    rel = row["artifact"]
    if not rel.startswith("data/") or not rel.endswith(".json"):
        return "shape_unmeasured", "not_a_json_artifact"
    full = os.path.join(data_dir, rel[len("data/"):])
    try:
        doc = json.loads(pathlib.Path(full).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "shape_unmeasured", f"{type(exc).__name__}"
    if not isinstance(doc, dict):
        return "shape_unmeasured", "not_a_mapping"
    keys = set(doc)
    hit = sorted(keys & set(FINDING_KEYS))
    row["_keys"] = keys
    if hit:
        return "finding_key_present", ",".join(hit)
    return "finding_key_absent_not_proof", None


# ─────────────────────────────────────────────────────────────────────────────────────
# Замер
# ─────────────────────────────────────────────────────────────────────────────────────

def measure(root, *, data_dir=None, now=None, manifest=None):
    """Замер. Внешние двери приходят ВХОДОМ — иначе тест судил бы о живой машине."""
    root = pathlib.Path(root)
    now = now or dt.datetime.now(dt.timezone.utc)
    data_dir = os.path.abspath(data_dir or (root / "data"))

    if manifest is None:
        manifest, why = _load_manifest(root)
        if manifest is None:
            return _unmeasured_whole(why)
    if not os.path.isdir(data_dir):
        return _unmeasured_whole(f"data_dir_absent:{data_dir}")

    rows = _population(manifest)
    if not rows:
        return _unmeasured_whole("manifest_declares_no_produced_artifact")

    consumers = _declared_consumers(manifest)
    consumes = _agent_consumes(manifest)
    reads, writes_by_module, mentions, parsed, unparsed, seen_any = _code_sites(root)
    code_measured = seen_any
    module_index = _module_index(parsed)
    agents_by_label = {a.get("label"): a for a in _listed(manifest, "agents")}

    # Сколько ПРОИЗВЕДЁННЫХ артефактов носят одно имя файла (заказ G105 п. 2). Разбор
    # читателей опознаёт имя, а не адрес, поэтому у неоднозначного имени попадание
    # доказательством не является — и число этой неоднозначности обязано быть
    # ИЗМЕРЕНО, а не предположено.
    shared_names = collections.Counter(os.path.basename(r["artifact"]) for r in rows)

    tally = collections.Counter({v: 0 for v in VERDICTS})
    shape_tally = collections.Counter({k: 0 for k in SHAPES})
    vocabulary = set()

    for row in rows:
        observed, note = _writer_observed(row, data_dir=data_dir, now=now)
        if note:
            row["note"] = note
        row["writer_observed"] = observed
        row["verdict"] = _verdict_for(row, observed,
                                      consumers=consumers, consumes=consumes,
                                      reads=reads, writes_by_module=writes_by_module,
                                      code_measured=code_measured)
        tally[row["verdict"].split(":", 1)[0]] += 1
        shape, why = _finding_shape(row, data_dir=data_dir)
        row["shape"] = shape
        if why:
            row["shape_reason"] = why
        shape_tally[shape] += 1
        vocabulary |= row.pop("_keys", set())

    # ── ось объявлений (заказ G105 п. 3) ───────────────────────────────────────────
    claim_tally = collections.Counter({k: 0 for k in CLAIMS})
    pair_tally = collections.Counter({k: 0 for k in CLAIMS})
    claim_rows = []
    closures = {}
    for row in rows:
        if row["verdict"] not in DECLARATION_VERDICTS:
            continue
        pairs = []
        for consumer in row.get("declared_consumers", ()):
            kind, detail = _claim_for(
                row["artifact"], consumer, root=root, agents=agents_by_label,
                module_index=module_index, reads=reads, mentions=mentions,
                parsed=parsed, shared=shared_names[os.path.basename(row["artifact"])],
                closures=closures)
            pairs.append((kind, detail))
            pair_tally[kind] += 1
            row.setdefault("claim_pairs", []).append(
                {"consumer": consumer, "claim": kind, "detail": detail})
        row["claim"] = _row_claim(pairs) if pairs else "declaration_unmeasured"
        if not pairs:
            row["claim_pairs"] = []
        claim_tally[row["claim"]] += 1
        claim_rows.append(row)

    findings = [r for r in rows if r["verdict"] == "no_reader_found"]
    claim_findings = [r for r in claim_rows if r["claim"] == "declaration_unbacked"]
    ambiguous = {n: c for n, c in shared_names.items() if c > 1}
    return {
        "applied": APPLIED,
        "order": ORDER,
        "population": len(rows),
        "verdicts": dict(tally),
        "shape": dict(shape_tally),
        "vocabulary": len(vocabulary),
        "claims": dict(claim_tally),
        "claim_pairs": dict(pair_tally),
        "claim_rows": claim_rows,
        "claim_findings": claim_findings,
        "ambiguity": {
            "artifact_names": len(shared_names),
            "ambiguous_names": len(ambiguous),
            "rows_sharing_a_name": sum(ambiguous.values()),
            "worst": sorted(ambiguous.items(), key=lambda kv: (-kv[1], kv[0]))[:3],
        },
        "no_reader_lower_bound": tally["no_reader_found"] + len(claim_findings),
        "rows": rows,
        "findings": findings,
        "unparsed": unparsed,
        "data_dir": data_dir,
    }


def _verdict_for(row, observed, *, consumers, consumes, reads, writes_by_module,
                 code_measured):
    """Ноги в ОБЪЯВЛЕННОМ порядке: сначала писатель, только потом читатель."""
    if not observed:
        intent = row.get("intent")
        if intent == "retired":
            return "writer_retired"
        if intent != "active":
            return "writer_not_loaded"
        return "writer_silent"

    path = row["artifact"]
    declared = consumers.get(path) or set()
    if CYCLE_CONSUMER in declared:
        return "read_by_the_cycle"
    if declared:
        row["declared_consumers"] = sorted(declared)
        return "read_by_another_declared_consumer"
    others = {a for a in (consumes.get(path) or set()) if a != row.get("agent")}
    if others:
        row["declared_consumers"] = sorted(others)
        return "read_by_another_agent"

    name = os.path.basename(path)
    if "." not in name:
        # Каталог-артефакт: разбор читателей опирается на имя файла с расширением
        # (ADR-524), и каталога он не видит ВОВСЕ. Это «не измерено» с причиной,
        # а не «читателя нет».
        return "unmeasured:code_reader_not_measurable_for_a_directory"
    if not code_measured:
        return "unmeasured:no_source_tree_parsed"
    readers = {m for m in (reads.get(name) or set())
               if name not in writes_by_module.get(m, ())}
    if readers:
        row["code_readers"] = sorted(readers)[:4]
        return "read_in_code_by_another_module"
    return "no_reader_found"


def _unmeasured_whole(reason):
    return {
        "applied": APPLIED,
        "order": ORDER,
        "population": 0,
        "verdicts": {v: 0 for v in VERDICTS},
        "shape": {},
        "rows": [],
        "findings": [],
        "unparsed": [],
        "unmeasured": reason,
    }


def verdict(doc):
    """0 — находок нет · 1 — находки НАЗВАНЫ · 2 — НЕ ИЗМЕРЕНО.

    Пустое объявление — находка ТОГО ЖЕ класса: артефакт производится, объявленный
    читатель назван, и в его коде этого пути нет вовсе. Не считать её находкой значило
    бы оставить вред за объявлением — ровно то, ради чего поставлен заказ G105 п. 3.
    """
    if doc.get("unmeasured"):
        return 2
    if doc["verdicts"].get("unmeasured"):
        return 2
    return 1 if (doc["findings"] or doc.get("claim_findings")) else 0


# ─────────────────────────────────────────────────────────────────────────────────────
# Отчёт
# ─────────────────────────────────────────────────────────────────────────────────────

def report_lines(doc):
    if doc.get("unmeasured"):
        return [f"[НЕ ИЗМЕРЕНО] перепись читателей находок: {doc['unmeasured']}"]
    out = [f"находка без читателя в цикле (заказ G86 п. 4): население "
           f"{doc['population']} пар(ы) «агент → артефакт»"]
    out.append("  " + " · ".join(f"{k} {doc['verdicts'][k]}" for k in VERDICTS))
    out.append("  форма (ось отдельная, в сумму не входит; перечень ключей ЗАКРЫТ — "
               f"{len(FINDING_KEYS)} имён против ИЗМЕРЕННОГО словаря населения в "
               f"{doc.get('vocabulary')} ключ(ей), промах доказательством обратного НЕ "
               "является): "
               + " · ".join(f"{k} {v}" for k, v in sorted(doc["shape"].items())))
    amb = doc.get("ambiguity", {})
    out.append("  объявление против кода (ось отдельная, в сумму не входит; заказ G105 "
               "п. 3 — исходы «объявлен другим потребителем» и «объявлен другим агентом» "
               "суть ОБЪЯВЛЕНИЯ): "
               + " · ".join(f"{k} {doc.get('claims', {}).get(k, 0)}" for k in CLAIMS)
               + f" (пар {sum(doc.get('claim_pairs', {}).values())}: "
               + " · ".join(f"{k} {v}" for k, v in sorted(doc.get("claim_pairs", {}).items()))
               + ")")
    out.append(f"  имя файла не есть адрес (заказ G105 п. 2, ИЗМЕРЕНО): имён "
               f"{amb.get('artifact_names')} · НЕОДНОЗНАЧНЫХ {amb.get('ambiguous_names')} "
               f"· рядов под ними {amb.get('rows_sharing_a_name')}"
               + (" · худшие: " + ", ".join(f"{n}×{c}" for n, c in amb.get("worst", ()))
                  if amb.get("worst") else ""))
    for row in doc["findings"]:
        mark = ("НЕСЁТ НАХОДКИ" if row["shape"] == "finding_key_present"
                else row["shape"])
        out.append(f"  [ЧИТАТЕЛЯ НЕТ] {row['agent']} → {row['artifact']} "
                   f"(возраст {row.get('age_hours')}ч, {mark})")
    for row in doc.get("claim_findings", ()):
        who = ", ".join(c["consumer"] for c in row.get("claim_pairs", ()))
        out.append(f"  [ОБЪЯВЛЕНИЕ ПУСТО] {row['agent']} → {row['artifact']}: "
                   f"объявленный потребитель «{who}» этого пути не упоминает ВОВСЕ "
                   f"(ни чтением, ни записью, ни литералом) ни в одном файле своего "
                   f"импортного замыкания")
    for row in doc.get("claim_rows", ()):
        if row["claim"] != "declaration_unmeasured":
            continue
        why = "; ".join(f"{c['consumer']} → {c['detail']}"
                        for c in row.get("claim_pairs", ())
                        if c["claim"] == "declaration_unmeasured")
        out.append(f"  [ОБЪЯВЛЕНИЕ НЕ ИЗМЕРЕНО] {row['artifact']}: {why or 'потребитель не назван'}")
    out.append(f"  граница снизу у «читателя нет»: {doc.get('no_reader_lower_bound')} "
               f"= {doc['verdicts'].get('no_reader_found')} доказанных + "
               f"{len(doc.get('claim_findings', ()))} с пустым объявлением; "
               f"{doc.get('claims', {}).get('declaration_unmeasured', 0)} объявлени(я) "
               "не измерены и в границу не включены")
    if doc["unparsed"]:
        out.append(f"  [не разобрано] модулей {len(doc['unparsed'])}: "
                   + ", ".join(u["module"] for u in doc["unparsed"][:3]))
    out.append("  НЕ ДОКЛАДЫВАЕТ: ВЫЗЫВАЕТСЯ ли найденное место чтения на самом деле "
               "(импорт не есть вызов — поэтому чтение из замыкания зовётся неизмеренным, "
               "а не прочитанным) · читателя по адресу: разбор опознаёт ИМЯ ФАЙЛА, и "
               "число этой неоднозначности напечатано строкой выше · читателя вне "
               "spa_core/scripts · верность самого срока годности")
    out.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return out


def format_report(doc):
    return "\n".join(report_lines(doc))


def main(argv=None, *, now=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[2]))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = measure(args.root, data_dir=args.data_dir, now=now)
    if args.json:
        printable = {k: v for k, v in doc.items() if k != "rows"}
        print(json.dumps(printable, ensure_ascii=False, indent=2))
    else:
        print(format_report(doc))
    return verdict(doc)


if __name__ == "__main__":
    sys.exit(main())
