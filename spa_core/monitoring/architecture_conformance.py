"""architecture_conformance.py — сторож соответствия флота конституции (ADR-066, Фаза 1).

Отвечает на вопрос, на который не отвечает ни один существующий сторож:
**соответствует ли работающий флот спроектированной архитектуре и замыкаются ли
петли потребления?** (deployment_drift — «тот ли код», deployment_acceptance —
«способен ли стартовать», agent_health — «жив ли процесс», rules_watchdog —
«соблюдены ли риск-правила»; см. таблицу в .claude/rules/deployment.md.)

Конституция — `architecture/manifest.json` (ADR-066 Фаза 0). Проверки:

  B1  флот ↔ манифест в обе стороны:
        загружен, в манифесте нет            → CRITICAL (инцидент swarm_dwell 2026-08-05)
        загружен при intent=retired          → CRITICAL (зомби)
        загружен при intent=designed         → CRITICAL (активация мимо ADR)
        intent=active, не загружен           → CRITICAL (мёртвый по конституции)
        intent=active, plist не персистентен → WARN     (не переживёт ребут — 2026-08-05)
        intent=unresolved                    → WARN weak (дрейф без решения; стареет)
  B2  свежесть активных артефактов по SLO (generated_at из содержимого, иначе mtime)
        → WARN (инцидент agent_registry: 19 дней протухания никто не заметил)
        + ВЫПОЛНИМОСТЬ самого SLO: литерал `slo_hours` сверяется с физическим
        минимумом `period_hours + такт производителя`; объявить свежесть строже,
        чем производитель способен дать, — дефект МАНИФЕСТА, а не производителя
        (замер #256: `outcomes.jsonl` — строка в сутки от 6-часового агента,
        честный максимум разрыва 30ч против объявленных 26ч). Бюджет и его
        слагаемые лежат машинно в `slo_budgets` (урок #235: бюджет обязан быть
        показательным, иначе спорить не с чем).
  B3  замыкание потребления: продукт агента с consumer_required обязан иметь СВЕЖИЙ
        ресит в data/consumption_receipts.jsonl → WARN (ядро аудита: 12 io_* в никуда).
        Срок годности ПОТРЕБЛЕНИЯ — собственный (`consumption_slo_hours`, по умолчанию
        26ч), а НЕ заимствованный `slo_hours` продюсера: «файл свежий?» и «его кто-то
        читает?» — разные вопросы разного масштаба, и пока B3 брал чужой литерал,
        ужесточение SLO продюсера молча ужесточало требование к ЧИТАТЕЛЮ (замер #348:
        `chief_investment.json` slo_hours=1 при часовом такте шага 0-офис ⇒ 60 %
        разрывов реситов «нарушали» бюджет на исправном контуре). Литерал сверяется
        с тактом самого частого читателя — тот же приём, что у B2; бюджет и его
        слагаемые лежат машинно в `consumption_budgets`.
  B5  манифест сам соответствует фактам plist'ов (перегенерация без дрейфа;
        на хосте без ~/Library/LaunchAgents/com.spa.* — честный UNCHECKED).
        Отдельно: plist, объявленный манифестом путём В РЕПО, которого в этом
        дереве нет, а на `origin/main` он ЕСТЬ, — это граница синхронизации,
        а не дрейф механики (цикл #267; доказательство — в
        `build_architecture_manifest`). Цикл #236 доделал вторую половину:
        такой случай больше не UNCHECKED навсегда — вопрос задаётся тому,
        у кого есть ответ, и ОБЕ стороны сравнения читаются с `origin/main`
        (plist и запись манифеста), а провенанс лежит в `mechanics_from_ref`.
        Прочитать с ref нечем ⇒ по-прежнему UNCHECKED, не «сошлось».
  B6  локальная курация ↔ `origin/main` (замер 2026-08-08, цикл #168/#169)
  B7  КОНТРАКТ агента (ADR-154 «контракты раньше оркестрации», ADR-158):
        объявление `PRODUCES` в точке входа против того, что модуль реально пишет,
        и против манифеста — плюс сверка срока годности с `uptime_monitor`.
        Находка — ТОЛЬКО противоречие и расхождение множеств. `unmeasured` /
        `undeclared` / `not_compared` — состояние РАБОТЫ, а не авария: они лежат
        строкой в блоке `contracts` и НЕ красят вердикт. Причина названа вслух:
        unchecked даёт UNCHECKED (exit 1), и 31 агент без объявления навсегда
        стёр бы разницу между «измерено и чисто» и «не смотрели» — сторож,
        который всегда жёлтый, перестают читать.

Откуда берётся КУРАЦИЯ (`intent` и родня) — отдельный вопрос от «какие plist'ы
лежат на диске». Механика (`plist_source`/`reboot_safe`/`schedule`/`program`)
перегенерируется из фактов локально; курация — durable-запись принятых решений,
и живёт она в git (`CLAUDE.md` инв. 13). ПОПРАВКА 29.08: с тех пор
`architecture` ДОБАВЛЕН в `CODE_PATHS` синхронизации — прод-дерево получает
манифест (проверено: сегодняшние правки контракта доехали в прод). На 08.08
это было НЕ так, и описанная ниже авария случилась именно поэтому. Чтение
курации с `origin/main` остаётся верным: синк бывает реже прогона сторожа и
может не состояться вовсе, а вердикт о курации не должен зависеть от того,
успел ли прод обновиться. Тогда прод перегенерировал манифест из своей стёртой памяти и выдал
4 CRITICAL про агентов, которых владелец разрешил поставить 08.08: локально
`intent=retired`, на origin `active`. Приём тот же, что принят для карточек в
цикле #147: **курация читается с `origin/main`, и это НАЗЫВАЕТСЯ вслух**
(блок `curation` в отчёте + находка B6 о самом расхождении). Порог: сторож не
смеет становиться зеленее — он смеет только перестать врать о том, что
доказуемо доставлено. Настоящий зомби (origin ТОЖЕ говорит `retired`, агент
загружен) остаётся CRITICAL; origin недостижим ⇒ честный UNCHECKED, а не
молчаливый откат на локальную копию.

Семантика вердикта (инвариант 2, refusal-first): `OK` ТОЛЬКО когда всё вычислено
и прошло. Невычисленное — UNCHECKED, не «прошло». Слабые (weak) находки СТАРЕЮТ:
после WEAK_AGE_DAYS уходят из findings в aged (видимы, не красят) — урок
«irreversible UNCHECKED starves the queue». Сильные не стареют.

Exit: 0 OK · 1 WARN/UNCHECKED · 2 CRITICAL. Выход: data/architecture_conformance.json
(атомарно). Tier-1 push НАМЕРЕННО отсутствует: whitelist push_policy — закрытый
контракт внимания владельца (R4); доставка находок владельцу — мост «находка→
карточка» (ADR-066 Фаза 3). LLM_FORBIDDEN. Только stdlib. Время — вход (now=),
не окружение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода — вывести производителя разбором нельзя
#: (замер 28.08: верно 13 из 27, одна ошибка, семья harness недостижима).
#: Сверяется с фактической записью — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/architecture_conformance.json",
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_PATH = os.path.join(REPO_ROOT, "architecture", "manifest.json")
REPORT_PATH = os.path.join(REPO_ROOT, "data", "architecture_conformance.json")
RECEIPTS_PATH = os.path.join(REPO_ROOT, "data", "consumption_receipts.jsonl")

WEAK_AGE_DAYS = 14
SUBPROC_TIMEOUT = 20
_TS_FIELDS = ("generated_at", "updated_at", "timestamp", "last_updated")

MANIFEST_REL = os.path.join("architecture", "manifest.json")
CURATION_REF = "origin/main"
# Ровно ключи build_architecture_manifest.CURATED_DEFAULTS — то, что генератор
# НЕ выводит из фактов, а сохраняет как решение. Расхождение двух списков ловит
# test_curated_fields_match_builder (иначе новое курируемое поле молча осталось
# бы читаться с устаревшей локальной копии).
CURATED_FIELDS = ("layer", "role", "intent", "produces", "consumes",
                  "consumer_required", "governed_by", "curation", "notes",
                  # passport (AI1 гл.3/24) — курация, а не факт: цель, метрика и
                  # эскалация выводятся из источников, но решение «вот эта цель»
                  # принимает человек. Значит читается с origin, как остальная
                  # курация, и расхождение с локальной копией НАЗЫВАЕТСЯ.
                  "passport")

# «Не спрашивали» — не то же, что «спросили и не смогли». Без этого различия один
# новый аргумент судил бы и те вызовы, которые о нём не знают: шесть тестов про B1/B3
# покраснели бы на ИСПРАВНОМ дереве и перестали называть свою цель. Тот же приём уже
# принят здесь для `drift_unmeasurable`. Живой путь (`main`) передаёт значение ВСЕГДА —
# явный None ⇒ честный UNCHECKED; это закреплено test_main_passes_contracts_into_the_report.
_NOT_REQUESTED: dict = {"__not_requested__": True}

EXIT_BY_OVERALL = {"OK": 0, "UNCHECKED": 1, "WARN": 1, "CRITICAL": 2}


# ── сбор фактов (в тестах всё инъектируется) ─────────────────────────────────

def gather_contracts(manifest: dict | None = None) -> dict:
    """Три сверки контрактов. НИКОГДА не бросает и падает по одной, а не всем скопом.

    Каждая обёрнута отдельно НАМЕРЕННО: сломанная сверка обязана ослепить только
    себя. Не выполнилась ⇒ None ⇒ честный UNCHECKED у своей проверки, а не тишина,
    неотличимая от «сошлось» (инвариант 2).

    `manifest` — СВЕДЁННЫЙ манифест этого прогона (`reconcile_curation`), и он обязан
    доехать до сверок. Замер #431: обе parity-сверки делали своё, второе чтение файла
    с диска и потому судили ДРУГОЙ манифест, чем B1/B2/B5 рядом. На живой системе это
    значило, что курация, доставленная на `origin/main`, не гасит находку в проде
    ВООБЩЕ: прод-дерево каталог `architecture/` при синхронизации не получает — ровно
    то, о чём предупреждает строка B6 этого же сторожа.
    """
    out: dict = {"contract": None, "manifest_parity": None, "freshness_parity": None,
                 "errors": {}}
    for key, call in (
        ("contract", lambda: __import__(
            "spa_core.monitoring.artifact_contract", fromlist=["x"]).audit_fleet()),
        ("manifest_parity", lambda: __import__(
            "spa_core.monitoring.contract_manifest_parity",
            fromlist=["x"]).audit(manifest=manifest)),
        ("freshness_parity", lambda: __import__(
            "spa_core.monitoring.freshness_threshold_parity",
            fromlist=["x"]).audit(manifest=manifest)),
    ):
        try:
            out[key] = call()
        except Exception as e:                      # noqa: BLE001 — сторож не падает
            out["errors"][key] = f"{type(e).__name__}: {e}"
    return out


def gather_fleet() -> set[str] | None:
    """Метки com.spa.*, реально загруженные в launchd. None = НЕ ИЗМЕРЕНО."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=SUBPROC_TIMEOUT)
        if out.returncode != 0:
            return None
        fleet = set()
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2].startswith("com.spa."):
                fleet.add(parts[2])
        return fleet
    except Exception:
        return None


def _parse_iso(value) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def artifact_timestamp(rel_path: str, root: str = REPO_ROOT) -> dt.datetime | None:
    """Отметка свежести артефакта: содержимое (generated_at и родня) прежде mtime —
    mtime лжёт при синхронизациях/checkout. Нет файла → None."""
    full = os.path.join(root, rel_path)
    if not os.path.exists(full):
        return None
    if full.endswith(".json"):
        try:
            data = json.load(open(full))
            if isinstance(data, dict):
                for f in _TS_FIELDS:
                    raw = data.get(f)
                    # date-only метка («2026-08-06») парсится как полночь и
                    # ЗАВЫШАЕТ возраст до 24ч — ложный stale-WARN каждую ночь
                    # (инцидент 02:39 07.08). Дата без времени точнее mtime НЕ
                    # является — падаем на mtime.
                    if isinstance(raw, str) and "T" not in raw:
                        continue
                    ts = _parse_iso(raw)
                    if ts:
                        return ts
        except Exception:
            pass  # нечитаемый JSON — честно падаем на mtime
    return dt.datetime.fromtimestamp(os.path.getmtime(full), tz=dt.timezone.utc)


def producer_tick_hours(schedule) -> float | None:
    """Такт производителя из машинного `schedule` манифеста. None = НЕ ИЗМЕРИМ.

    Словарь задаёт `build_architecture_manifest.py`: `interval:Ns` ·
    `calendar:HH:MM` (раз в сутки) · `calendar:wdN·HH:MM` (раз в неделю) ·
    `daemon` (непрерывно ⇒ квантования нет, 0) · `manual`/`event:*`/нет — такт
    не определён расписанием, и это НЕ ноль.
    """
    if not isinstance(schedule, str) or not schedule:
        return None
    if schedule == "daemon":
        return 0.0
    if schedule.startswith("interval:"):
        raw = schedule.split(":", 1)[1].rstrip("s")
        try:
            return int(raw) / 3600.0
        except ValueError:
            return None
    if schedule.startswith("calendar:"):
        return 168.0 if "wd" in schedule.split(":", 1)[1] else 24.0
    return None


def freshness_floor(art: dict, by_label: dict) -> dict:
    """Физический минимум бюджета свежести артефакта — из ФАКТОВ, не из литерала.

    Разрыв между двумя записями артефакта не может быть меньше, чем
    `period_hours` (как часто у артефакта ВООБЩЕ появляется новое содержимое;
    отсутствует ⇒ 0 = пишется каждый такт) плюс такт производителя (запись
    случается только на такте, поэтому такт — это КВАНТОВАНИЕ, а не запас).

    Замер 2026-08-16 (цикл #256), из-за которого это появилось:
    `outcomes.jsonl` — строка на календарный день (`period_hours: 24`) от
    производителя с тактом 6ч ⇒ честный максимум разрыва 30ч; объявлено 26ч,
    и сторож полгода краснел на ИСПРАВНОМ refusal-first производителе
    (наблюдённая последовательность разрывов по логу: 18ч · 24ч · 30ч).
    Возвращает {"floor_h", "period_h", "tick_h", "reason"}; floor_h=None —
    такт производителя не определён расписанием (НЕ повод считать бюджет нулём).
    """
    period_h = float(art.get("period_hours") or 0.0)
    producer = art.get("producer")
    if not producer:
        return {"floor_h": None, "period_h": period_h, "tick_h": None,
                "reason": "продюсер не объявлен — такт неизвестен"}
    agent = by_label.get(producer)
    if agent is None:
        return {"floor_h": None, "period_h": period_h, "tick_h": None,
                "reason": f"продюсера {producer} нет в манифесте"}
    tick_h = producer_tick_hours(agent.get("schedule"))
    if tick_h is None:
        return {"floor_h": None, "period_h": period_h, "tick_h": None,
                "reason": f"расписание {producer} не задаёт такт "
                          f"({agent.get('schedule')!r})"}
    return {"floor_h": period_h + tick_h, "period_h": period_h,
            "tick_h": tick_h, "reason": ""}


# Бюджет ПОТРЕБЛЕНИЯ по умолчанию — ровно тот литерал, что стоял в B3 запасным
# значением с самого рождения проверки (`art.get("slo_hours") or 26`). Он НЕ
# выдуман этим изменением: у вопроса «этот отчёт вообще кто-нибудь читает?»
# масштаб суток, а не часов (ядро аудита 2026-08-05 — 12 io_* без читателя
# МЕСЯЦАМИ).
CONSUMPTION_SLO_DEFAULT_H = 26.0

# Словарь `consumers` манифеста — курация, и имена в нём не всегда launchd-ярлыки:
# шаги протокола названы по роли. Соответствие держим ЗДЕСЬ и явно, а не гадаем
# подстрокой (класс «сличение имён подстрокой выручает не тот объект»).
CONSUMER_LABEL_ALIASES = {
    "orchestrator_protocol": "com.spa.orchestrator",
}


def consumer_tick_hours(consumer: str, by_label: dict) -> float | None:
    """Такт ПОТРЕБИТЕЛЯ по имени из `consumers`. None = не измерим (не гадаем)."""
    for label in (consumer, f"com.spa.{consumer}",
                  CONSUMER_LABEL_ALIASES.get(consumer)):
        agent = by_label.get(label) if label else None
        if agent is not None:
            return producer_tick_hours(agent.get("schedule"))
    return None


def consumption_floor(art: dict, by_label: dict) -> dict:
    """Физический минимум бюджета ПОТРЕБЛЕНИЯ — из такта самого частого читателя.

    Ресит появляется только когда потребитель РАБОТАЕТ, поэтому возраст последнего
    ресита при такте T гуляет в [0, T] на исправной системе. Требовать ресит свежее
    T — значит краснеть на системе, которая читает ровно так часто, как объявлено.

    Замер 2026-08-22 (цикл #348), из-за которого это появилось:
    `chief_investment.json` объявлен `slo_hours: 1` (контракт ПРОИЗВОДИТЕЛЯ — с
    ADR-104 он пишет раз в 300с), а самый частый его читатель — шаг 0-офис
    протокола оркестратора с тактом 3600с. По журналу реситов: 210 из 352
    разрывов (60 %) больше часа, медиана 1.27ч, максимум 6.0ч — то есть сторож
    объявлял «потребитель замолчал» на исправном контуре чаще, чем молчал.

    Возвращает {"floor_h", "consumer", "tick_h", "reason"}; floor_h=None — такт
    ни одного потребителя не измерим (НЕ повод расширять бюджет: fail-CLOSED).
    """
    consumers = [c for c in (art.get("consumers") or []) if c]
    if not consumers:
        return {"floor_h": None, "consumer": None, "tick_h": None,
                "reason": "потребители не объявлены"}
    best: tuple[float, str] | None = None
    unresolved: list[str] = []
    for c in consumers:
        tick = consumer_tick_hours(c, by_label)
        if tick is None:
            unresolved.append(c)
            continue
        if best is None or tick < best[0]:
            best = (tick, c)
    if best is None:
        return {"floor_h": None, "consumer": None, "tick_h": None,
                "reason": f"такт не измерим ни у одного потребителя: "
                          f"{', '.join(unresolved)}"}
    return {"floor_h": best[0], "consumer": best[1], "tick_h": best[0],
            "reason": (f"такт не измерим у: {', '.join(unresolved)}"
                       if unresolved else "")}


def load_receipts(path: str = RECEIPTS_PATH) -> dict[str, dt.datetime]:
    """artifact → отметка САМОГО СВЕЖЕГО ресита потребления. Нет файла → {}."""
    latest: dict[str, dt.datetime] = {}
    if not os.path.exists(path):
        return latest
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_iso(rec.get("consumed_at"))
                art = rec.get("artifact")
                if art and ts and (art not in latest or ts > latest[art]):
                    latest[art] = ts
    except Exception:
        pass
    return latest


def group_drift_by_agent(problems: list[str]) -> list[dict]:
    """Строки замера → находки, ключ которых — ЛИЧНОСТЬ агента, а не текст поля.

    Одна пропавшая точка входа даёт ТРИ строки (`plist_source`/`schedule`/`program`):
    ключ по тексту завёл бы три карточки об одной причине, а любая правка
    формулировки завела бы их заново. Строка без префикса `com.spa.<…>: ` живёт
    своим ключом — выдумывать ей владельца нельзя.
    """
    order: list[str] = []
    groups: dict[str, list[str]] = {}
    for p in problems:
        label = p.split(": ", 1)[0] if (p.startswith("com.spa.") and ": " in p) else None
        gid = label or p
        if gid not in groups:
            groups[gid] = []
            order.append(gid)
        groups[gid].append(p.split(": ", 1)[1] if label else p)
    out: list[dict] = []
    for gid in order:
        if gid.startswith("com.spa."):
            out.append({"key": gid, "message": f"{gid}: " + "; ".join(groups[gid])})
        else:
            out.append({"key": gid[:80], "message": gid})
    return out


def _manifest_drift_problems() -> dict | None:
    """B5: перегенерировать манифест из фактов plist'ов. None = НЕ ИЗМЕРИМО здесь.

    Возвращает `{"drift": [сгруппированные находки], "unmeasurable": [строки]}`.
    Второй список — то, что в ЭТОМ дереве измерить нечем: он уезжает в `unchecked`,
    а не в находки. Замер 16.08 (цикл #267): `com.spa.site_freshness` объявлен
    манифестом как `repo:launchd/…`, на origin файл есть, в прод-дереве нет
    (синхронизация не возит `launchd/`; на 16.08 она не возила и `architecture/`,
    сейчас возит — на этот случай не влияет) — сторож печатал три
    строки «→ None» и звучал как ДРЕЙФ МЕХАНИКИ, хотя мерил ГРАНИЦУ СИНХРОНИЗАЦИИ.
    Находка кормит мост карточками владельцу; ложная — тратит его внимание
    (карточка `inbox-prod-storozh-arhitektury-chitaet-fail-ko`).

    Отдаёт САМ диагноз, а не указатель на него. До цикла #264 здесь стоял
    `gen.main([])`, из которого брался ОДИН код возврата, а находка звучала
    «manifest --check вернул дрейф (см. build_architecture_manifest.py)»: ни
    агента, ни поля, ни направления — и флага `--check` у скрипта нет вовсе
    (`argparse: unrecognized arguments: --check`), так что читатель находки
    не мог даже повторить замер по её же инструкции. Живой замер 16.08:
    три строки про `com.spa.site_freshness` печатались в stdout и пропадали.
    """
    try:
        import glob
        import importlib.util
        gen_path = os.path.join(REPO_ROOT, "scripts", "build_architecture_manifest.py")
        spec = importlib.util.spec_from_file_location("bam", gen_path)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        if not glob.glob(os.path.join(gen.LAUNCH_AGENTS_DIR, "com.spa.*.plist")):
            return None  # не прод-хост
        m = gen.measure()  # тот же вердикт, что у CLI без флагов: пусто ⇔ rc 0
        return {"drift": group_drift_by_agent(m["problems"] + m["drift"]),
                "unmeasurable": list(m.get("unmeasurable") or []),
                "measured_from_ref": list(m.get("measured_from_ref") or [])}
    except Exception as e:  # noqa: BLE001
        # Ключ БЕЗ текста исключения: путь/номер строки в ключе плодили бы новую
        # находку (и новую карточку) на каждый чих окружения.
        return {"drift": [{"key": "measure_failed", "message": f"B5 упал: {e}"}],
                "unmeasurable": [], "measured_from_ref": []}


def subject_inputs(root: str = REPO_ROOT) -> list[dict]:
    """Провенанс ПРЕДМЕТА: по какой именно копии конституции вынесен вердикт.

    Зачем (замер цикла #337). 21.08 07:44Z решение ADR-104 сменило такт
    `com.spa.io_chief_investment` в манифесте `interval:86400s → interval:300s`;
    в прод-дерево `architecture/` эта правка доехала в 19:21Z, а последний отчёт
    сторожа был произведён в 16:19Z. Обязательный шаг 0-офис три часа печатал
    `вердикт: OK (critical=0 warn=0)` — и это была ПРАВДА о прежней конституции
    и НЕИЗМЕРЕННОСТЬ о текущей, а различить их читателю было нечем: у отчёта
    есть возраст, но не было ответа на вопрос «а предмет с тех пор менялся?».
    Тот же класс, что #222 закрыл для `house_view_gap` сверкой РАЗНЫХ тактов:
    возраст каждого входа обязан лежать машинно и называться словами.

    `sha256` важнее `mtime`: перезапись файла тем же содержимым двигает mtime и
    дала бы ложную находку каждый раз, когда цикл перегенерировал манифест
    байт-в-байт (генератор идемпотентен по построению — тест
    `test_idempotent_write`). Поэтому читатель судит по содержимому, а mtime
    остаётся для отчёта и для старых отчётов без `inputs`.

    Fail-CLOSED: нечитаемый предмет — `measured: false` с причиной, а НЕ
    молчание и не «сошлось».
    """
    import hashlib
    rows: list[dict] = []
    for rel in (MANIFEST_REL,):
        path = os.path.join(root, rel)
        row: dict = {"path": rel, "role": "subject", "measured": False,
                     "mtime": None, "sha256": None, "reason": ""}
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
            row["sha256"] = hashlib.sha256(blob).hexdigest()
            row["mtime"] = dt.datetime.fromtimestamp(
                os.path.getmtime(path), dt.timezone.utc).isoformat()
            row["measured"] = True
        except OSError as e:
            row["reason"] = f"предмет не прочитан: {e}"
        rows.append(row)
    return rows


def origin_manifest(root: str = REPO_ROOT, ref: str = CURATION_REF,
                    rel: str = MANIFEST_REL) -> tuple[dict | None, str]:
    """Манифест из git (`<ref>:<rel>`) — конституция. Сети не требует: читается
    локальный ref. Возвращает (манифест|None, причина-если-None)."""
    try:
        out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=root,
                             capture_output=True, text=True, timeout=SUBPROC_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        return None, f"git недоступен: {e}"
    if out.returncode != 0:
        return None, f"нет `{ref}:{rel}` (git show rc={out.returncode})"
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        return None, f"`{ref}:{rel}` не разбирается как JSON: {e}"
    if not isinstance(data, dict) or not isinstance(data.get("agents"), list):
        return None, f"`{ref}:{rel}` не похож на манифест"
    return data, ""


def reconcile_curation(local: dict, origin: dict | None,
                       reason: str = "", ref: str = CURATION_REF) -> tuple[dict, dict]:
    """Манифест-для-проверок + провенанс курации.

    Механика остаётся ЛОКАЛЬНОЙ (она и есть факты этого хоста), курация —
    с `origin`. Агент, которого origin знает, а локальная копия нет,
    ДОБАВЛЯЕТСЯ (иначе загруженный `telegram_health` вечно ловил бы ложное
    «в манифесте ОТСУТСТВУЕТ»). Агент, которого нет на origin, живёт со своей
    локальной курацией — она единственная, что о нём известно.
    """
    if origin is None:
        return local, {"source": "local", "ref": ref, "measured": False,
                       "reason": reason or "курация НЕ сверена с origin",
                       "overridden": [], "added_from_origin": [], "local_only": []}

    by_origin = {a["label"]: a for a in origin.get("agents", []) if a.get("label")}
    merged: list[dict] = []
    overridden: list[dict] = []
    for a in local.get("agents", []):
        entry = dict(a)
        src = by_origin.get(entry.get("label"))
        if src is not None:
            for field in CURATED_FIELDS:
                if field not in src:
                    continue
                if entry.get(field) != src[field]:
                    overridden.append({"label": entry["label"], "field": field,
                                       "local": entry.get(field), "origin": src[field]})
                entry[field] = src[field]
        merged.append(entry)

    local_labels = {a.get("label") for a in local.get("agents", [])}
    added = []
    for label in sorted(set(by_origin) - local_labels):
        entry = dict(by_origin[label])
        entry.setdefault("intent", "unresolved")
        entry["curation_from"] = ref
        merged.append(entry)
        added.append(label)

    result = dict(local)
    result["agents"] = merged
    return result, {
        "source": ref, "ref": ref, "measured": True, "reason": "",
        "overridden": overridden,
        "added_from_origin": added,
        "local_only": sorted(local_labels - set(by_origin)),
    }


# ── ядро (чистое: все входы — параметры) ─────────────────────────────────────

def _finding(key: str, check: str, severity: str, cls: str, message: str) -> dict:
    return {"key": key, "check": check, "severity": severity, "class": cls,
            "message": message}


def run_checks(manifest: dict,
               fleet: set[str] | None,
               ts_of,                      # rel_path -> datetime|None
               receipts: dict[str, dt.datetime],
               now: dt.datetime,
               prev_first_seen: dict[str, str] | None = None,
               drift_problems: list[str | dict] | None = None,
               drift_measured: bool = False,
               curation: dict | None = None,
               drift_unmeasurable: list[str] | None = None,
               drift_from_ref: list[dict] | None = None,
               inputs: list[dict] | None = None,
               contract_audit: dict | None = _NOT_REQUESTED,
               manifest_parity: dict | None = _NOT_REQUESTED,
               freshness_parity: dict | None = _NOT_REQUESTED,
               prev_contract_labels: list[str] | None = None) -> dict:
    findings: list[dict] = []
    unchecked: list[dict] = []
    agents = manifest.get("agents", [])
    by_label = {a["label"]: a for a in agents}

    # B1 — флот ↔ манифест
    if fleet is None:
        unchecked.append({"check": "B1_fleet", "reason": "launchctl недоступен — флот НЕ ИЗМЕРЕН"})
    else:
        for label in sorted(fleet):
            a = by_label.get(label)
            if a is None:
                findings.append(_finding(
                    f"B1:unknown:{label}", "B1", "CRITICAL", "strong",
                    f"{label} загружен, в манифесте ОТСУТСТВУЕТ (класс swarm_dwell 2026-08-05)"))
            elif a["intent"] == "retired":
                findings.append(_finding(
                    f"B1:zombie:{label}", "B1", "CRITICAL", "strong",
                    f"{label} работает при intent=retired"))
            elif a["intent"] == "designed":
                findings.append(_finding(
                    f"B1:premature:{label}", "B1", "CRITICAL", "strong",
                    f"{label} работает при intent=designed — активация мимо ADR"))
            elif a["intent"] == "unresolved":
                findings.append(_finding(
                    f"B1:unresolved_running:{label}", "B1", "WARN", "weak",
                    f"{label} работает при intent=unresolved — намерение никем не решено"))
        for a in agents:
            if a["intent"] != "active":
                continue
            if a["label"] not in fleet:
                findings.append(_finding(
                    f"B1:dead:{a['label']}", "B1", "CRITICAL", "strong",
                    f"{a['label']}: intent=active, но НЕ загружен во флоте"))
            elif not a.get("reboot_safe"):
                findings.append(_finding(
                    f"B1:reboot_unsafe:{a['label']}", "B1", "WARN", "strong",
                    f"{a['label']} работает, но plist не персистентен "
                    f"({a.get('plist_source')}) — не переживёт ребут"))

    # B2 — свежесть активных артефактов + выполнимость самого SLO
    slo_budgets: list[dict] = []
    slo_unassigned: list[dict] = []
    for art in manifest.get("artifacts", []):
        if art.get("status") != "active":
            continue
        path = art["path"]
        declared = float(art.get("slo_hours") or 0)
        floor = freshness_floor(art, by_label)
        floor_h = floor["floor_h"]

        # Бюджет ПОКАЗАТЕЛЬНЫЙ (урок #235): не литерал, а литерал против фактов.
        # Объявить свежесть строже, чем производитель физически способен дать,
        # нельзя — такой SLO краснеет на ИСПРАВНОЙ системе и учит не верить B2.
        unsatisfiable = bool(declared and floor_h is not None and declared < floor_h)
        budget = max(declared, floor_h) if unsatisfiable else declared
        slo_budgets.append({"path": path, "declared_h": declared or None,
                            "floor_h": floor_h, "period_h": floor["period_h"],
                            "tick_h": floor["tick_h"], "budget_h": budget or None,
                            "satisfiable": (None if floor_h is None
                                            else not unsatisfiable),
                            "reason": floor["reason"]})

        if not declared:
            # СРОК НЕ НАЗНАЧЕН — и до цикла #426 это состояние было НЕМЫМ.
            #
            # `declared = float(art.get("slo_hours") or 0)` превращает пустое
            # поле в ноль, а ниже стоит `if budget and age_h > budget` — при
            # нулевом бюджете условие не срабатывает НИКОГДА. Замер #426:
            # активный артефакт, не менявшийся 40 суток, не даёт ни находки,
            # ни `unchecked`; единственный след — строка `slo_budgets` с
            # `budget_h: None`, которую не читает ни один потребитель отчёта.
            # Итог: «срок никто не назначил» неотличимо от «свежесть в порядке».
            #
            # И это не экзотика, а ШТАТНЫЙ покой по ADR-158: срок назначают ДВЕ
            # роли по согласованию, а fail-CLOSED исход «не сошлись» — ровно
            # пустое поле («агент остаётся в списке „нужен автор“, а не получает
            # выдуманное число»). То есть состояние, объявленное честным,
            # сторож читал как чистое.
            #
            # Эскалации здесь НЕТ намеренно (ADR-164 п.2): состояние работы,
            # загнанное в `unchecked`, делает сторожа вечно жёлтым, и разница
            # между «измерено и чисто» и «мы туда не смотрели» исчезает. Исход
            # НАЗЫВАЕТСЯ и СЧИТАЕТСЯ, вердикт не трогает.
            #
            # Возраст мерится ВСЁ РАВНО: срока нет, но факт есть — и это ровно
            # тот вход, по которому две роли назначают срок («через сколько
            # молчание становится опасным», ADR-158). Без него у ролей нет
            # ничего, кроме расписания, а его владелец как основание отклонил.
            seen = ts_of(path)
            slo_unassigned.append({
                "path": path,
                "producer": art.get("producer"),
                "consumers": list(art.get("consumers") or []),
                "exists": seen is not None,
                "observed_age_h": (None if seen is None else
                                   round((now - seen).total_seconds() / 3600.0, 2)),
                "reason": "срок годности не назначен (ADR-158 — назначают две "
                          "роли по согласованию); свежесть НЕ ИЗМЕРЕНА, "
                          "а не в порядке",
            })

        if unsatisfiable:
            findings.append(_finding(
                f"B2:slo_unsatisfiable:{path}", "B2", "WARN", "strong",
                f"{path}: объявленный SLO {declared:g}ч МЕНЬШЕ физического минимума "
                f"{floor_h:g}ч (период артефакта {floor['period_h']:g}ч + такт "
                f"производителя {floor['tick_h']:g}ч) — производитель не может его "
                f"обеспечить, протухание считается по {budget:g}ч. Чинить литерал в "
                f"манифесте, а не производителя (класс #256: сторож краснел на "
                f"исправном refusal-first производителе)"))

        ts = ts_of(path)
        if ts is None:
            findings.append(_finding(
                f"B2:missing:{path}", "B2", "WARN", "strong",
                f"{path}: активный артефакт отсутствует на диске"))
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        if budget and age_h > budget:
            how = (f"SLO {declared:g}ч" if not unsatisfiable else
                   f"бюджет {budget:g}ч = период {floor['period_h']:g}ч + такт "
                   f"производителя {floor['tick_h']:g}ч (объявленный SLO "
                   f"{declared:g}ч невыполним)")
            findings.append(_finding(
                f"B2:stale:{path}", "B2", "WARN", "strong",
                f"{path}: возраст {age_h:.1f}ч > {how} "
                f"(класс agent_registry: 19 дней молчаливого протухания)"))

    # B3 — замыкание потребления
    consumption_budgets: list[dict] = []
    for art in manifest.get("artifacts", []):
        if art.get("status") != "active":
            continue
        producer = art.get("producer")
        if producer and by_label.get(producer, {}).get("consumer_required"):
            path = art["path"]
            ts = receipts.get(path)
            # Срок годности ПОТРЕБЛЕНИЯ — свой, а не заимствованный у продюсера.
            # `slo_hours` отвечает на вопрос «файл свежий?» (контракт производителя);
            # вопрос B3 — «его кто-нибудь читает?», и это разные вопросы с разным
            # масштабом. Пока B3 брал чужой литерал, ужесточение SLO продюсера
            # молча ужесточало требование к ЧИТАТЕЛЮ — цикл #348.
            declared = float(art.get("consumption_slo_hours") or 0) or CONSUMPTION_SLO_DEFAULT_H
            floor = consumption_floor(art, by_label)
            floor_h = floor["floor_h"]
            unsatisfiable = bool(floor_h is not None and declared < floor_h)
            budget = max(declared, floor_h) if unsatisfiable else declared
            consumption_budgets.append({
                "path": path, "declared_h": declared,
                "declared_explicit": bool(art.get("consumption_slo_hours")),
                "floor_h": floor_h, "fastest_consumer": floor["consumer"],
                "budget_h": budget,
                "satisfiable": (None if floor_h is None else not unsatisfiable),
                "reason": floor["reason"]})
            if unsatisfiable:
                findings.append(_finding(
                    f"B3:consumption_slo_unsatisfiable:{path}", "B3", "WARN", "strong",
                    f"{path}: объявленный `consumption_slo_hours` {declared:g}ч МЕНЬШЕ "
                    f"такта самого частого читателя ({floor['consumer']}, "
                    f"{floor_h:g}ч) — читатель не может его обеспечить, молчание "
                    f"считается по {budget:g}ч. Чинить литерал в манифесте, а не "
                    f"читателя (класс #256/#348: сторож краснел на исправном контуре)"))
            if ts is None:
                findings.append(_finding(
                    f"B3:no_consumption:{path}", "B3", "WARN", "strong",
                    f"{path}: consumer_required, но НИ ОДНОГО ресита потребления "
                    f"(ядро аудита 2026-08-05: отчёты в никуда)"))
            elif (now - ts).total_seconds() / 3600.0 > budget:
                findings.append(_finding(
                    f"B3:consumption_stale:{path}", "B3", "WARN", "strong",
                    f"{path}: последний ресит старше бюджета потребления {budget:g}ч "
                    f"— потребитель замолчал"))

    # B5 — манифест соответствует фактам plist'ов
    if not drift_measured:
        unchecked.append({"check": "B5_manifest",
                          "reason": "хост без ~/Library/LaunchAgents/com.spa.* — дрейф НЕ ИЗМЕРЕН"})
    else:
        for p in (drift_problems or []):
            # dict — сгруппированная находка (ключ = агент, см. group_drift_by_agent);
            # строка — прежняя форма, ключом остаётся сам текст.
            key, msg = ((p["key"], p["message"]) if isinstance(p, dict)
                        else (p[:80], p))
            findings.append(_finding(f"B5:drift:{key}", "B5", "WARN", "strong",
                                     f"манифест ↔ факты: {msg}"))
        # Расхождение, которого в ЭТОМ дереве не измерить (plist объявлен путём
        # в репо, каталог сюда не синкается) — не находка, но и не тишина.
        # Вердикт от этого не зеленеет: непустой `unchecked` даёт overall
        # UNCHECKED (exit 1), просто мост не заводит по нему карточку владельцу.
        for u in (drift_unmeasurable or []):
            unchecked.append({"check": "B5_manifest",
                              "reason": f"манифест ↔ факты: {u}"})

    # B6 — локальная курация ↔ origin (см. шапку модуля)
    if curation is not None:
        if not curation.get("measured"):
            unchecked.append({
                "check": "B6_curation",
                "reason": f"курация НЕ сверена с {curation.get('ref')}: "
                          f"{curation.get('reason')} — локальный `intent` мог "
                          f"устареть, вердикты B1 не доказаны"})
        else:
            over = curation.get("overridden") or []
            added = curation.get("added_from_origin") or []
            if over or added:
                labels = sorted({o["label"] for o in over} | set(added))
                findings.append(_finding(
                    "B6:curation_drift", "B6", "WARN", "strong",
                    f"локальная копия {MANIFEST_REL} разошлась с {curation['ref']} "
                    f"по курации: {len(over)} пол(я/ей) у {len(labels)} агент(ов) "
                    f"({', '.join(labels)}); курация взята с {curation['ref']} "
                    f"(решения живут в git), но прод-дерево `architecture/` при "
                    f"синхронизации не получает — стёртая память вернётся"))

    # ── B7 — контракты (ADR-154/158) ────────────────────────────────────────
    # Три сверки, написанные 28.08 и до сих пор никем не вызванные — дословно та
    # патология, ради которой писался ADR-154. Правило подключения одно на все три:
    # находка = ПРОТИВОРЕЧИЕ или расхождение множеств; всё остальное — строка отчёта.
    # Вердикты сверок держатся здесь литералами НАМЕРЕННО: сторож не должен падать
    # из-за импорта того, что он проверяет. Литералы связаны с константами сверок
    # тестом (test_conformance_contract_wiring.py) — расхождение домов краснеет.
    contracts_report: dict = {}

    if contract_audit is _NOT_REQUESTED:
        pass                                    # проверка не запрашивалась
    elif contract_audit is None:
        unchecked.append({"check": "B7_contract",
                          "reason": "сверка контрактов НЕ ВЫПОЛНИЛАСЬ — объявления не прочитаны"})
    else:
        now_labels = sorted(r["label"] for r in (contract_audit.get("rows") or []))
        contracts_report["contract"] = {"total": contract_audit.get("total"),
                                        "counts": dict(contract_audit.get("counts") or {}),
                                        "labels": now_labels}
        # ВЫБЫВШИЕ ИЗ ПЕРЕПИСИ. Класс пойман 29.08 на самом важном агенте системы:
        # `run_daily_paper_cycle.sh` получил третий и четвёртый шаги, целей стало
        # четыре, вывод точки входа честно отказал — и `com.spa.daily_cycle` исчез
        # из переписи ВМЕСТЕ СО СВОИМ ПРОТИВОРЕЧИЕМ. Ни одной находки при этом не
        # появилось: счётчик просто стал 71 вместо 72. Отказ был верным, молчание —
        # нет. «Больше не измеряется» обязано быть событием, а не убылью в счётчике.
        gone = sorted(set(prev_contract_labels or []) - set(now_labels))
        for label in gone:
            a = by_label.get(label)
            if a is None or a.get("intent") != "active":
                continue          # агента вывели из строя — это другой вопрос, B1
            findings.append(_finding(
                f"B7:left_census:{label}", "B7", "WARN", "strong",
                f"{label} БЫЛ в переписи контрактов, теперь его там нет: точка входа "
                f"перестала выводиться (обёртка изменилась?). Вместе с агентом пропали "
                f"и все его находки — объявить точку входа в обёртке (# AGENT_MODULE:)"))
        for r in (contract_audit.get("rows") or []):
            if r.get("verdict") != "contradiction":
                continue
            decl = ", ".join(r.get("declared") or []) or "—"
            extra = ", ".join(r.get("undeclared_writes") or []) or "—"
            findings.append(_finding(
                f"B7:contradiction:{r['label']}", "B7", "WARN", "strong",
                f"{r['label']}: объявлено PRODUCES ({decl}), а собственный модуль пишет "
                f"ещё и ({extra}) — объявление и код расходятся, и читатель продукта "
                f"опирается на неверный контракт"))

    if manifest_parity is _NOT_REQUESTED:
        pass                                    # проверка не запрашивалась
    elif manifest_parity is None:
        unchecked.append({"check": "B7_manifest_parity",
                          "reason": "сверка объявлений с манифестом НЕ ВЫПОЛНИЛАСЬ"})
    else:
        contracts_report["manifest_parity"] = {
            "compared": manifest_parity.get("compared"),
            "verdict": manifest_parity.get("verdict")}
        for row in (manifest_parity.get("findings") or []):
            only_d = ", ".join(row.get("declared_only") or []) or "—"
            only_m = ", ".join(row.get("manifest_only") or []) or "—"
            findings.append(_finding(
                f"B7:manifest_parity:{row['label']}", "B7", "WARN", "strong",
                f"{row['label']}: код и манифест называют РАЗНЫЙ продукт "
                f"(только в объявлении: {only_d}; только в манифесте: {only_m}) — "
                f"{row.get('note', '')}"))

    if freshness_parity is _NOT_REQUESTED:
        pass                                    # проверка не запрашивалась
    elif freshness_parity is None:
        unchecked.append({"check": "B7_freshness_parity",
                          "reason": "сверка сроков годности с uptime_monitor НЕ ВЫПОЛНИЛАСЬ"})
    else:
        contracts_report["freshness_parity"] = {
            "compared": freshness_parity.get("compared"),
            "verdict": freshness_parity.get("verdict")}
        for row in (freshness_parity.get("findings") or []):
            if row.get("verdict") == "different_artifact":
                msg = (f"{row['label']}: манифест и uptime_monitor считают продуктом РАЗНЫЕ "
                       f"файлы (монитор: {row.get('monitor_artifact')}; манифест: "
                       f"{', '.join(row.get('manifest_artifacts') or []) or '—'}) — "
                       f"чью-то свежесть никто не сторожит")
            else:
                msg = (f"{row['label']}: продукт {row.get('artifact')} объявлен протухающим "
                       f"через {row.get('manifest_hours')}ч, а тревога о молчании агента "
                       f"сработает только через {row.get('monitor_hours')}ч — в этом окне "
                       f"файл уже негоден, а сигнала ещё нет")
            findings.append(_finding(
                f"B7:freshness_parity:{row['label']}", "B7", "WARN", "strong", msg))

    # первое появление + старение слабых
    prev_first_seen = prev_first_seen or {}
    now_iso = now.isoformat()
    aged: list[dict] = []
    kept: list[dict] = []
    for f in findings:
        f["first_seen"] = prev_first_seen.get(f["key"], now_iso)
        first = _parse_iso(f["first_seen"]) or now
        age_days = (now - first).total_seconds() / 86400.0
        if f["class"] == "weak" and age_days > WEAK_AGE_DAYS:
            f["aged_out"] = True
            aged.append(f)
        else:
            kept.append(f)

    if any(f["severity"] == "CRITICAL" for f in kept):
        overall = "CRITICAL"
    elif kept:
        overall = "WARN"
    elif unchecked:
        overall = "UNCHECKED"
    else:
        overall = "OK"

    return {
        "generated_at": now_iso,
        "adr": "ADR-066",
        "overall": overall,
        "exit_code": EXIT_BY_OVERALL[overall],
        "counts": {"critical": sum(1 for f in kept if f["severity"] == "CRITICAL"),
                   "warn": sum(1 for f in kept if f["severity"] == "WARN"),
                   "aged": len(aged), "unchecked": len(unchecked),
                   # Считается ОТДЕЛЬНЫМ числом и намеренно НЕ входит ни в
                   # `warn`, ни в `unchecked`: это не находка и не сбой
                   # проверки, а названный пробел в контракте (ADR-158).
                   # Счётчик существует затем, чтобы «ноль назначенных сроков»
                   # нельзя было прочитать как «все сроки на месте».
                   "slo_unassigned": len(slo_unassigned)},
        "fleet_size": (len(fleet) if fleet is not None else None),
        "manifest_agents": len(agents),
        "curation": curation,
        # Провенанс B5: агенты, чей plist объявлен в репо и в это дерево не
        # доехал — обе стороны сравнения прочитаны с ref. Вердикт не меняет,
        # но отвечает на «чем измерено», иначе OK был бы неотличим от тишины.
        "mechanics_from_ref": list(drift_from_ref or []),
        # Провенанс ПРЕДМЕТА: по какой копии конституции вынесен этот вердикт
        # (см. `subject_inputs`). Читатель отчёта обязан уметь спросить «а
        # предмет с тех пор менялся?» — иначе `OK` о прежнем манифесте
        # неотличим от `OK` о текущем.
        "inputs": list(inputs or []),
        # Состояние контрактов (B7). Мягкие исходы живут ЗДЕСЬ, а не в findings и
        # не в unchecked: их место — отчёт, их адресат — очередь работ, не тревога.
        "contracts": contracts_report,
        "slo_budgets": slo_budgets,
        # Активные артефакты, которым срок годности ещё НЕ НАЗНАЧЕН (ADR-158).
        # Раньше это состояние было различимо только по `budget_h: None` внутри
        # `slo_budgets` — то есть по ОТСУТСТВИЮ значения в служебной строке;
        # отдельный список существует потому, что отсутствие не читают.
        # Наблюдённый возраст лежит рядом СПЕЦИАЛЬНО: он и есть тот факт, по
        # которому две роли назначают срок.
        "slo_unassigned": slo_unassigned,
        "consumption_budgets": consumption_budgets,
        "findings": kept,
        "aged": aged,
        "unchecked": unchecked,
    }


# ── обвязка ──────────────────────────────────────────────────────────────────

def _prev_first_seen(report_path: str = REPORT_PATH) -> dict[str, str]:
    try:
        prev = json.load(open(report_path))
        out = {}
        for f in prev.get("findings", []) + prev.get("aged", []):
            if f.get("key") and f.get("first_seen"):
                out[f["key"]] = f["first_seen"]
        return out
    except Exception:
        return {}


def _prev_contract_labels(report_path: str = REPORT_PATH) -> list[str]:
    """Кого перепись контрактов видела в прошлый раз. Нет отчёта ⇒ пусто, не авария."""
    try:
        prev = json.load(open(report_path))
        return list(((prev.get("contracts") or {}).get("contract") or {}).get("labels") or [])
    except Exception:                                   # noqa: BLE001
        return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ADR-066 architecture conformance watchdog")
    ap.add_argument("--run", "--once", action="store_true", dest="run",
                    help="один прогон против живой системы")
    ap.add_argument("--exit-zero", action="store_true",
                    help="плановый launchd-режим: exit 0, если проверка ВЫПОЛНИЛАСЬ "
                         "(вердикт — в отчёте). Иначе exit 1 у сторожа с находками "
                         "неотличим для agent_health от «агент сломан» и маскирует "
                         "настоящие падения. Крах по-прежнему ≠ 0.")
    ap.add_argument("--report", default=REPORT_PATH)
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0

    local = json.load(open(MANIFEST_PATH))
    origin, why = origin_manifest()
    manifest, curation = reconcile_curation(local, origin, reason=why)
    fleet = gather_fleet()
    receipts = load_receipts()
    b5 = _manifest_drift_problems()
    now = dt.datetime.now(dt.timezone.utc)
    contracts = gather_contracts(manifest)
    report = run_checks(manifest, fleet, artifact_timestamp, receipts, now,
                        prev_first_seen=_prev_first_seen(args.report),
                        drift_problems=(b5 or {}).get("drift"),
                        drift_measured=b5 is not None,
                        drift_unmeasurable=(b5 or {}).get("unmeasurable"),
                        drift_from_ref=(b5 or {}).get("measured_from_ref"),
                        inputs=subject_inputs(),
                        curation=curation,
                        contract_audit=contracts["contract"],
                        manifest_parity=contracts["manifest_parity"],
                        freshness_parity=contracts["freshness_parity"],
                        prev_contract_labels=_prev_contract_labels(args.report))

    from spa_core.utils.atomic import atomic_save
    atomic_save(report, args.report)

    c = report["counts"]
    print(f"architecture_conformance: {report['overall']} — critical={c['critical']} "
          f"warn={c['warn']} aged={c['aged']} unchecked={c['unchecked']} "
          f"(флот {report['fleet_size']}, манифест {report['manifest_agents']}, "
          f"курация {curation['source']})")
    cr = report.get("contracts") or {}
    if cr.get("contract"):
        cc = cr["contract"]["counts"]
        print("  контракты: " + " · ".join(f"{k}={v}" for k, v in sorted(cc.items()))
              + f" (из {cr['contract']['total']})")
    for k in ("manifest_parity", "freshness_parity"):
        if cr.get(k):
            print(f"  {k}: {cr[k]['verdict']} (сопоставлено {cr[k]['compared']})")
    for k, why in (contracts.get("errors") or {}).items():
        print(f"  [UNCHECKED] сверка {k} не выполнилась: {why}")
    # Печатается ВСЕГДА, когда пробел есть: блок в JSON, который не звучит в
    # выводе, — это тот же немой исход, только этажом выше (урок #426).
    for u in report.get("slo_unassigned") or []:
        age = ("файла нет на диске" if not u["exists"] else
               f"наблюдённый возраст {u['observed_age_h']:g}ч")
        print(f"  [СРОК НЕ НАЗНАЧЕН] {u['path']} (производитель "
              f"{u['producer']}): свежесть НЕ ИЗМЕРЕНА, {age} — срок обязаны "
              f"назначить две роли (ADR-158)")
    for f in report["findings"][:30]:
        print(f"  [{f['severity']}] {f['message']}")
    return 0 if args.exit_zero else report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
