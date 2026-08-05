"""architecture_conformance — соответствует ли флот спроектированной архитектуре? (ADR-066, Фаза 1)

Вопрос, на который до 2026-08-05 не отвечал НИ ОДИН сторож. Существующие отвечают на другие:

| Вопрос | Сторож | Чего НЕ проверяет |
|---|---|---|
| Это тот код, который мы приняли? | `deployment_drift_monitor` | работоспособен ли он |
| Способен ли флот стартовать? | `deployment_acceptance` | та ли это архитектура |
| Живы ли процессы? | `agent_health_monitor` | объявлен ли агент вообще |
| Соблюдены ли риск-правила? | `rules_watchdog` | всё вышеперечисленное |

Зелёный ответ на один вопрос никогда не означает ответа на остальные. Аудит 2026-08-05
показал цену этого пробела фактами: реестр агентов протух 19 дней, два ЖИВЫХ агента
(`artifact_freshness`, `swarm_dwell`) отсутствовали в реестре и работали без персистентного
plist (не пережили бы ребут), 12 агентов `io_*` ежедневно писали честный продукт, которого
не читал никто, а два агента (`checkpoint-7day`, `novel_edge_rnd`) месяцами висели в
состоянии «никто не решал».

Пять проверок — ровно эти пять аварий (`architecture/manifest.json` — конституция намерения,
Фаза 0):

  B1 fleet ↔ манифест В ОБЕ СТОРОНЫ — загружен, но не объявлен; объявлен `active`, но не
     загружен; `retired`, но живой; `active` без персистентного plist (не переживёт ребут);
     `unresolved` — честное «никто не решал» (СЛАБЫЙ сигнал, стареет).
  B2 свежесть продуктов по SLO манифеста — протухший `agent_registry.json` (475ч при SLO 26ч).
  B3 замыкание потребления — `consumer_required` ⇒ объявленный потребитель И свежий ресит
     в `data/consumption_receipts.jsonl`. «Кто-то читает» становится фактом, а не мнением.
  B4 designed-дрейф — архитектура со статусом `designed` не смеет иметь живой процесс
     (активация мимо ADR/владельца).
  B5 согласованность ролей/слоёв (ADR-004) — dev-агент не производит продуктовые артефакты;
     у артефакта ровно один продюсер; половины манифеста (`produces` ↔ `artifacts`) согласны.

Семантика вердикта — как у `rules_watchdog`: `OK` ТОЛЬКО когда всё реально вычислено и
прошло; «не измерено» = `UNCHECKED`, а не тихий зачёт (инвариант #2, класс fail-OPEN
#29–#38). Коды возврата: 0 — OK · 1 — WARN/UNCHECKED · 2 — CRITICAL.

Старение слабых сигналов (ADR-066 P2): слабая находка, которую невозможно закрыть без
владельца, через `WEAK_AGE_OUT_DAYS` перестаёт участвовать в вердикте, но остаётся в отчёте
с честной пометкой — иначе неустранимое «не измерено» навсегда затыкает очередь (урок
`irreversible-unchecked-starves-queue`). Сильные находки не стареют никогда.

Read-only: ничего не чинит, не деплоит, не двигает капитал. Выход — файл-отчёт
`data/architecture_conformance.json` (атомарно) + алерт ТОЛЬКО через `push_policy`
(единая push-авторитет). RiskPolicy / kill-switch / execution не затрагиваются (ADR-066 P5).

LLM_FORBIDDEN. Только stdlib. Атомарные записи.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.monitoring.agent_health_monitor import parse_launchctl_list
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.monitoring.architecture_conformance")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = _REPO_ROOT / "architecture" / "manifest.json"
STATE_FILENAME = "architecture_conformance.json"
RECEIPTS_FILENAME = "consumption_receipts.jsonl"

OK, UNCHECKED, WARN, CRITICAL = "OK", "UNCHECKED", "WARN", "CRITICAL"
_EXIT_CODES = {OK: 0, UNCHECKED: 1, WARN: 1, CRITICAL: 2}

# Слабая находка живёт в очереди столько дней; дальше — в отчёте, но не в вердикте.
WEAK_AGE_OUT_DAYS = 14

# Насколько артефакт должен просрочить свой SLO, чтобы это перестало быть «сбой прогона»
# и стало «продюсер брошен». Реестр 2026-08-05: 475ч при SLO 26ч = 18× — именно этот класс.
GROSSLY_STALE_FACTOR = 3.0

# Продуктовые пространства имён (ADR-004): решающая поверхность продуктового слоя.
# dev-слой сюда не пишет — это и есть нарушение двухслойности.
PRODUCT_NAMESPACES = ("data/investment_os/",)

STRONG, WEAK = "strong", "weak"


# ═══════════════════════════════════════════════════════════════════════════
# Находка
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class Finding:
    """Одна находка сторожа. `key` — СТАБИЛЬНЫЙ отпечаток (dedup, старение, мост Фазы 3)."""

    check: str          # B1 … B5
    key: str
    severity: str       # WARN | CRITICAL | UNCHECKED
    subject: str        # label агента / путь артефакта
    message: str
    strength: str = STRONG   # STRONG не стареет никогда; WEAK — стареет
    first_seen: str = ""
    aged_out: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _f(check: str, key: str, severity: str, subject: str, message: str,
       strength: str = STRONG) -> Finding:
    return Finding(check=check, key=key, severity=severity, subject=subject,
                   message=message, strength=strength)


# ═══════════════════════════════════════════════════════════════════════════
# Входы (каждый — инъектируемый; «не смог прочитать» ≠ «пусто»)
# ═══════════════════════════════════════════════════════════════════════════
def read_fleet(launchctl_output: Optional[str] = None) -> Tuple[Optional[Dict[str, dict]], str]:
    """Загруженный флот `com.spa.*` → ({label: {...}}, "") либо (None, причина).

    `None` — это «не измерено», и оно НЕ равно пустому флоту. `agent_health_monitor`
    fail-safe отдаёт '' при недоступном launchctl; здесь такой ответ прочитался бы как
    «загружено ноль агентов» — ровно fail-OPEN класса #29–#38. Поэтому свой запуск.
    """
    if launchctl_output is not None:
        parsed = parse_launchctl_list(launchctl_output)
        return {k: v for k, v in parsed.items() if k.startswith("com.spa.")}, ""
    try:
        proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15)
    except Exception as exc:  # noqa: BLE001
        return None, "launchctl недоступен: {}: {}".format(type(exc).__name__, exc)
    if proc.returncode != 0:
        return None, "launchctl list вернул код {}".format(proc.returncode)
    parsed = parse_launchctl_list(proc.stdout or "")
    if not parsed:
        # Разбор дал ноль строк ВООБЩЕ (не ноль наших агентов) — читали не то.
        return None, "launchctl list не дал ни одной разобранной строки"
    return {k: v for k, v in parsed.items() if k.startswith("com.spa.")}, ""


def read_manifest(path: Optional[Path] = None) -> Tuple[Optional[dict], str]:
    """Манифест архитектуры → (dict, "") либо (None, причина). Пустой манифест — тоже отказ."""
    p = Path(path) if path else DEFAULT_MANIFEST
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return None, "манифест {} не прочитан: {}: {}".format(p, type(exc).__name__, exc)
    if not isinstance(doc, dict) or not doc.get("agents"):
        return None, "манифест {} без единого агента — сверять не с чем".format(p)
    return doc, ""


def read_receipts(data_dir: Path) -> Tuple[Optional[List[dict]], str]:
    """Реситы потребления (append-only jsonl) → (список, "") либо (None, причина).

    Отсутствие файла — НЕ «не измерено»: это измеренный факт «никто не отчитался о чтении»
    (Фаза 2 ещё не построена). Возвращаем пустой список, причину — в отчёт.
    """
    p = Path(data_dir) / RECEIPTS_FILENAME
    if not p.exists():
        return [], "файла реситов нет — ни один потребитель ещё не отчитался"
    out: List[dict] = []
    bad = 0
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    bad += 1
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except Exception as exc:  # noqa: BLE001
        return None, "реситы {} не читаются: {}: {}".format(p, type(exc).__name__, exc)
    return out, ("{} строк реситов не разобрано".format(bad) if bad else "")


# ═══════════════════════════════════════════════════════════════════════════
# Вспомогательное
# ═══════════════════════════════════════════════════════════════════════════
def _parse_iso(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_hours(path: Path, now_ts: float) -> Optional[float]:
    try:
        return (now_ts - path.stat().st_mtime) / 3600.0
    except Exception:  # noqa: BLE001
        return None


def _produced_paths(agent: dict) -> List[Tuple[str, Optional[float]]]:
    out: List[Tuple[str, Optional[float]]] = []
    for item in agent.get("produces") or []:
        if isinstance(item, dict) and item.get("artifact"):
            slo = item.get("slo_hours")
            out.append((str(item["artifact"]), slo if isinstance(slo, (int, float)) else None))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# B1 — fleet ↔ манифест в обе стороны
# ═══════════════════════════════════════════════════════════════════════════
def check_b1_fleet_vs_manifest(manifest: dict, fleet: Optional[Dict[str, dict]],
                               fleet_reason: str = "") -> List[Finding]:
    """Сверка «объявлено ↔ загружено» В ОБЕ СТОРОНЫ, плюс переживёт ли active ребут.

    Односторонняя сверка (только «объявленное живо?») пропустила бы ровно ту аварию, что
    случилась: `swarm_dwell` РАБОТАЛ, не будучи объявлен нигде, — со стороны реестра его
    не существовало, и 19 дней это никого не разбудило.
    """
    findings: List[Finding] = []
    agents = {a.get("label"): a for a in manifest.get("agents", []) if a.get("label")}

    # Сверка с флотом возможна только если флот ИЗМЕРЕН. Иначе — честное «не измерено»,
    # а не молчаливый зачёт: именно так свежая авария осталась бы невидимой.
    if fleet is None:
        findings.append(_f("B1", "b1:fleet-unmeasured", UNCHECKED, "launchctl",
                           "флот не измерен — сверка «объявлен ↔ загружен» не выполнялась ни "
                           "в одну сторону ({})".format(fleet_reason or "причина не названа")))
    else:
        for label in sorted(set(fleet) - set(agents)):
            findings.append(_f(
                "B1", "b1:loaded-not-declared:" + label, CRITICAL, label,
                "агент ЗАГРУЖЕН во флот, но не объявлен в манифесте — архитектура о нём не "
                "знает (авария swarm_dwell / artifact_freshness 2026-08-05)"))
        for label, agent in sorted(agents.items()):
            intent = agent.get("intent")
            if intent == "active" and label not in fleet:
                findings.append(_f(
                    "B1", "b1:active-not-loaded:" + label, CRITICAL, label,
                    "объявлен active, но во флоте его нет — либо он мёртв, либо намерение "
                    "устарело; молчаливого третьего варианта нет"))
            elif intent == "retired" and label in fleet:
                findings.append(_f(
                    "B1", "b1:retired-but-loaded:" + label, WARN, label,
                    "объявлен retired, но ЗАГРУЖЕН — зомби-агент работает вне архитектуры"))

    # Не зависит от флота: манифест сам знает, переживёт ли агент ребут.
    for label, agent in sorted(agents.items()):
        intent = agent.get("intent")
        if intent == "active" and not agent.get("reboot_safe"):
            findings.append(_f(
                "B1", "b1:active-not-reboot-safe:" + label, CRITICAL, label,
                "active без персистентного plist в ~/Library/LaunchAgents — не переживёт "
                "ребут (авария swarm_dwell 2026-08-05: жил, но не был бы восстановлен)"))
        if intent == "unresolved":
            findings.append(_f(
                "B1", "b1:intent-unresolved:" + label, WARN, label,
                "намерение не решено (`unresolved`): {} — нужен ретайр или активация "
                "владельцем (R4)".format(agent.get("notes") or "обоснование не записано"),
                strength=WEAK))
    return findings


# ═══════════════════════════════════════════════════════════════════════════
# B2 — свежесть продуктов по SLO
# ═══════════════════════════════════════════════════════════════════════════
def check_b2_artifact_freshness(manifest: dict, repo_root: Path,
                                now_ts: Optional[float] = None) -> List[Finding]:
    """Возраст берётся по mtime файла — тому же признаку, что у `deployment_acceptance`.

    Отсутствие файла — не освобождение от проверки, а худшая форма «не свежий»
    («никогда не производился»). Просрочка сверх `GROSSLY_STALE_FACTOR`×SLO — уже не
    пропущенный прогон, а брошенный продюсер (реестр: 475ч при SLO 26ч).
    """
    now_ts = time.time() if now_ts is None else now_ts
    findings: List[Finding] = []
    for art in manifest.get("artifacts", []):
        if art.get("status") != "active":
            continue  # planned-артефакт Фаз 2–4 ещё не обязан существовать
        path = art.get("path")
        slo = art.get("slo_hours")
        if not path or not isinstance(slo, (int, float)) or slo <= 0:
            findings.append(_f(
                "B2", "b2:no-slo:" + str(path), WARN, str(path),
                "активный артефакт без положительного slo_hours — свежесть не с чем сверять"))
            continue
        target = repo_root / path
        age = _age_hours(target, now_ts)
        if age is None:
            findings.append(_f(
                "B2", "b2:missing:" + path, CRITICAL, path,
                "артефакт не найден: продюсер {} не произвёл его ни разу (или путь в "
                "манифесте неверен)".format(art.get("producer") or "не объявлен")))
            continue
        if age > slo:
            gross = age > slo * GROSSLY_STALE_FACTOR
            findings.append(_f(
                "B2", "b2:stale:" + path, CRITICAL if gross else WARN, path,
                "протух: {:.1f}ч при SLO {}ч ({:.1f}×){}".format(
                    age, slo, age / slo,
                    " — это не пропущенный прогон, а брошенный продюсер" if gross else "")))
    return findings


# ═══════════════════════════════════════════════════════════════════════════
# B3 — замыкание потребления
# ═══════════════════════════════════════════════════════════════════════════
def check_b3_consumption_closure(manifest: dict, receipts: Optional[List[dict]],
                                 receipts_reason: str = "",
                                 now: Optional[datetime] = None) -> List[Finding]:
    """`consumer_required` ⇒ объявленный потребитель И свежий ресит.

    Свежесть ресита меряется тем же SLO, что и производство: продукт с суточным циклом,
    прочитанный неделю назад, не потребляется — он архивируется. Это и есть разница между
    «формально есть читатель» и «петля замкнута».
    """
    now = now or datetime.now(timezone.utc)
    findings: List[Finding] = []
    if receipts is None:
        findings.append(_f("B3", "b3:receipts-unreadable", UNCHECKED, RECEIPTS_FILENAME,
                           "реситы не прочитаны — замыкание потребления не проверялось: "
                           "{}".format(receipts_reason or "причина не названа")))
        return findings

    latest: Dict[str, datetime] = {}
    for rec in receipts:
        art = rec.get("artifact")
        when = _parse_iso(rec.get("consumed_at"))
        if not isinstance(art, str) or when is None:
            continue
        if art not in latest or when > latest[art]:
            latest[art] = when

    arts = {a.get("path"): a for a in manifest.get("artifacts", []) if a.get("path")}
    for agent in manifest.get("agents", []):
        if not agent.get("consumer_required"):
            continue
        if agent.get("intent") != "active":
            # Продукт требует читателя, только пока он производится. Требовать ресит от
            # retired-агента (он ничего не пишет) или от designed (ещё не активирован) —
            # значит выдумать находку, которую невозможно закрыть, и заткнуть ею очередь.
            continue
        label = agent.get("label", "<без label>")
        produced = _produced_paths(agent)
        if not produced:
            findings.append(_f(
                "B3", "b3:required-without-product:" + label, CRITICAL, label,
                "consumer_required, но манифест не называет ни одного продукта — требование "
                "потребителя нечем проверить"))
            continue
        for path, agent_slo in produced:
            art = arts.get(path)
            if art is None:
                findings.append(_f(
                    "B3", "b3:product-not-registered:" + path, CRITICAL, path,
                    "продукт {} не объявлен в реестре артефактов — потребителя назвать "
                    "негде".format(label)))
                continue
            consumers = [c for c in (art.get("consumers") or []) if c]
            if not consumers:
                findings.append(_f(
                    "B3", "b3:no-consumer:" + path, CRITICAL, path,
                    "у продукта {} нет НИ ОДНОГО объявленного потребителя — он пишется в "
                    "никуда (авария 12 io_* 2026-08-05)".format(label)))
                continue
            slo = art.get("slo_hours")
            if not isinstance(slo, (int, float)) or slo <= 0:
                slo = agent_slo if isinstance(agent_slo, (int, float)) and agent_slo > 0 else 26.0
            seen = latest.get(path)
            if seen is None:
                findings.append(_f(
                    "B3", "b3:no-receipt:" + path, CRITICAL, path,
                    "потребители объявлены ({}), но ни один не отчитался о чтении: реситов "
                    "нет{}".format(", ".join(consumers),
                                   " — " + receipts_reason if receipts_reason else "")))
                continue
            age_h = (now - seen).total_seconds() / 3600.0
            if age_h > slo:
                findings.append(_f(
                    "B3", "b3:receipt-stale:" + path, WARN, path,
                    "последнее чтение {:.1f}ч назад при SLO продукта {}ч — продукт "
                    "архивируется, а не потребляется".format(age_h, slo)))
    return findings


# ═══════════════════════════════════════════════════════════════════════════
# B4 — designed-дрейф
# ═══════════════════════════════════════════════════════════════════════════
def check_b4_designed_drift(manifest: dict, fleet: Optional[Dict[str, dict]],
                            fleet_reason: str = "") -> List[Finding]:
    """Спроектированное ≠ разрешённое. Живой процесс раньше активации — обход владельца."""
    findings: List[Finding] = []
    designed = [a for a in manifest.get("agents", []) if a.get("intent") == "designed"]
    if fleet is None:
        if designed:
            findings.append(_f(
                "B4", "b4:fleet-unmeasured", UNCHECKED, "launchctl",
                "флот не измерен — {} designed-агент(ов) не проверены на самовольную "
                "активацию ({})".format(len(designed), fleet_reason or "причина не названа")))
        return findings
    for agent in designed:
        label = agent.get("label", "<без label>")
        if label in fleet:
            findings.append(_f(
                "B4", "b4:designed-but-running:" + label, CRITICAL, label,
                "архитектура объявлена designed (активация owner-gated: {}), но процесс "
                "ЗАПУЩЕН — активация мимо ADR и мимо владельца".format(
                    ", ".join(agent.get("governed_by") or []) or "ADR не назван")))
    return findings


# ═══════════════════════════════════════════════════════════════════════════
# B5 — согласованность ролей/слоёв (ADR-004)
# ═══════════════════════════════════════════════════════════════════════════
def check_b5_role_layer_coherence(manifest: dict) -> List[Finding]:
    """Слои не смешиваются, у продукта один хозяин, половины манифеста согласны.

    Три разных способа потерять ответ на вопрос «кто это сломал»: dev-агент, пишущий в
    продуктовое пространство (нарушение двухслойности ADR-004); два продюсера одного
    артефакта (владение неоднозначно); расхождение между `produces` агента и полем
    `producer` артефакта (манифест противоречит сам себе и перестаёт быть конституцией).
    """
    findings: List[Finding] = []
    agents = [a for a in manifest.get("agents", []) if a.get("label")]
    producers: Dict[str, List[str]] = {}

    for agent in agents:
        label = agent["label"]
        for path, _slo in _produced_paths(agent):
            producers.setdefault(path, []).append(label)
            if agent.get("layer") == "dev" and path.startswith(PRODUCT_NAMESPACES):
                findings.append(_f(
                    "B5", "b5:dev-writes-product:{}:{}".format(label, path), CRITICAL, label,
                    "агент слоя dev производит продуктовый артефакт {} — нарушение "
                    "двухслойности ADR-004".format(path)))

    for path, labels in sorted(producers.items()):
        if len(labels) > 1:
            findings.append(_f(
                "B5", "b5:multiple-producers:" + path, CRITICAL, path,
                "артефакт заявлен продуктом сразу у {} — владение неоднозначно, «кто это "
                "сломал» не определимо".format(", ".join(sorted(labels)))))

    for art in manifest.get("artifacts", []):
        path, declared = art.get("path"), art.get("producer")
        if not path:
            continue
        actual = producers.get(path, [])
        if declared is None:
            if actual:
                findings.append(_f(
                    "B5", "b5:producer-null-but-claimed:" + path, WARN, path,
                    "артефакт объявлен без продюсера, но {} заявляет его своим продуктом — "
                    "половины манифеста не согласны".format(", ".join(sorted(actual)))))
            continue
        if declared not in actual:
            findings.append(_f(
                "B5", "b5:producer-mismatch:" + path, WARN, path,
                "продюсером объявлен {}, но в его `produces` этого пути нет (заявляют: "
                "{})".format(declared, ", ".join(sorted(actual)) or "никто)")))
    return findings


# ═══════════════════════════════════════════════════════════════════════════
# Старение слабых сигналов (ADR-066 P2)
# ═══════════════════════════════════════════════════════════════════════════
def apply_aging(findings: List[Finding], previous: Optional[dict],
                now: Optional[datetime] = None,
                age_out_days: int = WEAK_AGE_OUT_DAYS) -> List[Finding]:
    """Переносит `first_seen` из прошлого отчёта и гасит СЛАБЫЕ находки старше окна.

    Сильная находка не стареет никогда — иначе сторож сам себя выключит на самой
    неприятной аварии. Слабая (та, что закрывается только решением владельца) остаётся
    в отчёте с пометкой `aged_out`, но перестаёт держать вердикт красным: неустранимое
    «не измерено» навсегда затыкает очередь и обесценивает все остальные сигналы.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    seen_before: Dict[str, str] = {}
    for item in (previous or {}).get("findings", []) or []:
        key, first = item.get("key"), item.get("first_seen")
        if isinstance(key, str) and isinstance(first, str) and first:
            seen_before[key] = first
    cutoff = now - timedelta(days=age_out_days)
    for f in findings:
        f.first_seen = seen_before.get(f.key, now_iso)
        if f.strength == WEAK:
            first_dt = _parse_iso(f.first_seen)
            f.aged_out = bool(first_dt and first_dt < cutoff)
    return findings


# ═══════════════════════════════════════════════════════════════════════════
# Прогон
# ═══════════════════════════════════════════════════════════════════════════
def _rollup(findings: List[Finding]) -> str:
    live = [f for f in findings if not f.aged_out]
    if any(f.severity == CRITICAL for f in live):
        return CRITICAL
    if any(f.severity == WARN for f in live):
        return WARN
    if any(f.severity == UNCHECKED for f in live):
        return UNCHECKED
    return OK


def run_conformance(
    *,
    manifest_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    launchctl_output: Optional[str] = None,
    now: Optional[datetime] = None,
    write: bool = True,
    send_alert: bool = False,
) -> dict:
    """Прогнать B1–B5 и вернуть отчёт. Никогда не бросает; неизвестное = CRITICAL."""
    now = now or datetime.now(timezone.utc)
    root = Path(repo_root) if repo_root else _REPO_ROOT
    ddir = Path(data_dir) if data_dir else (root / "data")

    doc: dict = {
        "monitor": "architecture_conformance",
        "adr": "ADR-066",
        "checked_at": now.isoformat(),
        "overall": CRITICAL,
        "note": ("Отвечает ТОЛЬКО на вопрос «соответствует ли флот спроектированной "
                 "архитектуре?». Не проверяет ни версию кода (deployment_drift), ни "
                 "способность стартовать (deployment_acceptance), ни живость процессов "
                 "(agent_health) — четыре разных вопроса, ни один не заменяет другой."),
    }
    findings: List[Finding] = []
    try:
        manifest, mreason = read_manifest(manifest_path or (root / "architecture" / "manifest.json"))
        if manifest is None:
            # Без конституции сверять не с чем. Это не «нечего проверять», а отказ.
            findings.append(_f("B0", "b0:manifest-unreadable", CRITICAL, "manifest",
                               "манифест архитектуры недоступен: {}".format(mreason)))
            manifest = {"agents": [], "artifacts": []}
        else:
            fleet, freason = read_fleet(launchctl_output)
            receipts, rreason = read_receipts(ddir)
            findings += check_b1_fleet_vs_manifest(manifest, fleet, freason)
            findings += check_b2_artifact_freshness(manifest, root, now.timestamp())
            findings += check_b3_consumption_closure(manifest, receipts, rreason, now)
            findings += check_b4_designed_drift(manifest, fleet, freason)
            findings += check_b5_role_layer_coherence(manifest)
            doc["fleet_loaded"] = None if fleet is None else len(fleet)
            doc["agents_declared"] = len(manifest.get("agents", []))
            doc["artifacts_declared"] = len(manifest.get("artifacts", []))

        previous = None
        try:
            with open(ddir / STATE_FILENAME, encoding="utf-8") as fh:
                previous = json.load(fh)
        except Exception:  # noqa: BLE001 — первого отчёта просто ещё нет
            previous = None
        findings = apply_aging(findings, previous, now)
        doc["overall"] = _rollup(findings)
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: сторож не имеет права упасть в OK
        findings.append(_f("B0", "b0:checker-crashed", CRITICAL, "architecture_conformance",
                           "сам сторож упал: {}: {}".format(type(exc).__name__, exc)))
        doc["overall"] = CRITICAL

    live = [f for f in findings if not f.aged_out]
    doc["findings"] = [f.to_dict() for f in findings]
    doc["counts"] = {
        "critical": sum(1 for f in live if f.severity == CRITICAL),
        "warn": sum(1 for f in live if f.severity == WARN),
        "unchecked": sum(1 for f in live if f.severity == UNCHECKED),
        "aged_out": sum(1 for f in findings if f.aged_out),
        "by_check": {c: sum(1 for f in live if f.check == c) for c in
                     sorted({f.check for f in live})},
    }
    doc["unchecked"] = [{"check": f.check, "subject": f.subject, "reason": f.message}
                        for f in live if f.severity == UNCHECKED]

    if write:
        try:
            atomic_save(doc, str(Path(ddir) / STATE_FILENAME))
        except Exception as exc:  # noqa: BLE001
            log.warning("architecture_conformance: отчёт не сохранён (%s)", exc)
    if send_alert:
        _alert(doc)

    level = {CRITICAL: log.error, WARN: log.warning, UNCHECKED: log.warning}.get(
        doc["overall"], log.info)
    level("architecture_conformance: %s — critical=%s warn=%s unchecked=%s aged=%s",
          doc["overall"], doc["counts"]["critical"], doc["counts"]["warn"],
          doc["counts"]["unchecked"], doc["counts"]["aged_out"])
    return doc


def _alert(doc: dict) -> bool:
    """Алерт ТОЛЬКО через push_policy (единая push-авторитет). Никогда не бросает."""
    try:
        from spa_core.telegram import push_policy
    except Exception as exc:  # noqa: BLE001
        log.warning("push_policy недоступен: %s", exc)
        return False
    live_critical = sorted(f["key"] for f in doc.get("findings", [])
                           if f.get("severity") == CRITICAL and not f.get("aged_out"))
    if doc.get("overall") != CRITICAL:
        return bool(push_policy.resolve(
            "architecture_conformance_critical",
            "SPA — архитектура снова соответствует",
            "Критичных расхождений флота с манифестом больше нет."))
    return bool(push_policy.push_critical(
        "architecture_conformance_critical", CRITICAL,
        "SPA — флот разошёлся с архитектурой",
        format_report_text(doc),
        # Отпечаток = МНОЖЕСТВО критичных находок: то же множество молчит (dedup),
        # другое — новый инцидент и пушится.
        dedup_key="|".join(live_critical)))


def format_report_text(doc: dict) -> str:
    overall = str(doc.get("overall") or "")
    icon = {OK: "✅", WARN: "⚠️", UNCHECKED: "❓", CRITICAL: "🚨"}.get(overall, "❓")
    counts = doc.get("counts", {})
    lines = ["{} architecture_conformance: {}".format(icon, overall),
             "  объявлено агентов: {} · во флоте: {} · артефактов: {}".format(
                 doc.get("agents_declared", "?"),
                 "НЕ ИЗМЕРЕНО" if doc.get("fleet_loaded") is None else doc.get("fleet_loaded"),
                 doc.get("artifacts_declared", "?")),
             "  critical={} warn={} unchecked={} (устарело и снято с вердикта: {})".format(
                 counts.get("critical", 0), counts.get("warn", 0),
                 counts.get("unchecked", 0), counts.get("aged_out", 0))]
    for f in doc.get("findings", []):
        if f.get("aged_out"):
            continue
        mark = {CRITICAL: "✗", WARN: "•", UNCHECKED: "?"}.get(f.get("severity"), "•")
        lines.append("    {} [{}] {}: {}".format(mark, f.get("check"), f.get("subject"),
                                                 f.get("message")))
    if not doc.get("findings"):
        lines.append("    расхождений нет — всё объявленное измерено и совпало")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="Соответствует ли флот спроектированной архитектуре? (ADR-066, Фаза 1)")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--alert", action="store_true",
                    help="отправить алерт через push_policy при CRITICAL")
    ap.add_argument("--exit-zero-on-findings", action="store_true",
                    help="находки не считать сбоем ПРОЦЕССА (режим launchd): код 0, пока "
                         "сторож отработал; ненулевой — только если он сам упал")
    args = ap.parse_args(argv)
    doc = run_conformance(
        manifest_path=Path(args.manifest) if args.manifest else None,
        repo_root=Path(args.repo_root) if args.repo_root else None,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        write=not args.no_write,
        send_alert=args.alert)
    print(format_report_text(doc))
    if args.exit_zero_on_findings:
        # Под launchd находка — это СОДЕРЖАНИЕ отчёта, а не сбой процесса. Возвращая 2,
        # сторож бы вечно висел в agent_health как «last_exit=2», приучив всех считать
        # свой же флот жёлтым и не читать его; при этом настоящее падение агента стало бы
        # неотличимо от честной находки. Вердикт живёт в файле и в push_policy;
        # ненулевым кодом остаётся только собственная поломка сторожа.
        crashed = any(f.get("key") == "b0:checker-crashed" for f in doc.get("findings", []))
        return 2 if crashed else 0
    return _EXIT_CODES.get(str(doc.get("overall") or ""), 2)


if __name__ == "__main__":
    raise SystemExit(main())
