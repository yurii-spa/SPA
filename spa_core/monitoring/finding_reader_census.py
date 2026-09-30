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
import sys

from spa_core.monitoring.prior_run_operand_census import (
    SOURCE_ROOTS,
    _PathResolver,
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


# ─────────────────────────────────────────────────────────────────────────────────────
# Конституция
# ─────────────────────────────────────────────────────────────────────────────────────

def _load_manifest(root):
    path = root / "architecture" / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"manifest_unreadable:{type(exc).__name__}"


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
    """``(имя файла → читатели, модуль → им записанные имена)``.

    Разбор переиспользован у соседа ADR-524: второй копии правила «что есть запись» и
    «что есть чтение» в дереве быть не должно — ровно тот дефект, который ловит
    ``rule_second_copy_census`` (ADR-522).
    """
    reads = collections.defaultdict(set)
    writes_by_module = collections.defaultdict(set)
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
            w, r = _sites(tree, _PathResolver(tree))
            for name in w:
                writes_by_module[rel].add(name)
            for name in r:
                reads[name].add(rel)
    return reads, writes_by_module, unparsed, seen_any


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
    reads, writes_by_module, unparsed, seen_any = _code_sites(root)
    code_measured = seen_any

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

    findings = [r for r in rows if r["verdict"] == "no_reader_found"]
    return {
        "applied": APPLIED,
        "order": ORDER,
        "population": len(rows),
        "verdicts": dict(tally),
        "shape": dict(shape_tally),
        "vocabulary": len(vocabulary),
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
    """0 — находок нет · 1 — находки НАЗВАНЫ · 2 — НЕ ИЗМЕРЕНО."""
    if doc.get("unmeasured"):
        return 2
    if doc["verdicts"].get("unmeasured"):
        return 2
    return 1 if doc["findings"] else 0


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
    for row in doc["findings"]:
        mark = ("НЕСЁТ НАХОДКИ" if row["shape"] == "finding_key_present"
                else row["shape"])
        out.append(f"  [ЧИТАТЕЛЯ НЕТ] {row['agent']} → {row['artifact']} "
                   f"(возраст {row.get('age_hours')}ч, {mark})")
    if doc["unparsed"]:
        out.append(f"  [не разобрано] модулей {len(doc['unparsed'])}: "
                   + ", ".join(u["module"] for u in doc["unparsed"][:3]))
    out.append("  НЕ ДОКЛАДЫВАЕТ: читает ли объявленный потребитель файл на самом деле · "
               "читателя по адресу (имя файла не есть адрес, ADR-465) · читателя вне "
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
