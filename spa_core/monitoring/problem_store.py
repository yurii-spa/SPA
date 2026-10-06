"""spa_core/monitoring/problem_store.py — C6 Problem-store (ADR-580 §C6, REVIEW_1 amendment).

Проблема, которую это чинит (A4_reliability.md §2, замер 2026-10-05): цикл надёжности
обрывается на алерте. `agent_health` / `system_health` / `site_freshness` / `self_heal`
каждый час честно шлют ERROR в Telegram через edge-триггер (`push_policy`), но ПОСЛЕ
алерта ничего не происходит: нет PROBLEM-записи, нет RCA, повтор той же причины снова
будит владельца тем же сообщением (замер: 14+14 CRIT/recovered флапов, 7 «bootstrap
failed» за 35 минут). `findings_bridge` — единственная машина в доме, умеющая превращать
повторяющуюся находку в ОДНУ запись с критерием закрытия, но она (а) читает только
architecture_conformance/house_view_gap/loop_retro/tier_curator, НИКОГДА fleet-health;
(б) сама работает 3ч+ с логом 3.8 GB (она и есть писатель INC-1) — грузить её ещё
нагрузкой запрещено амендментом REVIEW_1 к C6.

Поэтому Problem-store — ОТДЕЛЬНЫЙ лёгкий шаг, не новый launchd-агент. Он читает
ЧЕТЫРЕ уже существующих read-only артефакта:

    data/agent_health.json        — per-agent WARN/CRIT + issue-строка
    data/system_health.json       — domains{status}
    data/site_freshness_report.json — fails[{code,severity,detail}]
    data/self_heal_status.json    — failures[str]

и ОДИН раз в час вызывается хвостом уже существующего ежечасного монитора
(`agent_health_monitor.main()` → `_write_problem_store`, рядом с уже работающими
side-car'ами `_write_fleet_economics`/`_write_orphaned_pytest` — тот же шаблон:
try/except, честный отказ, пульс флота важнее). Выбор этой точки, а не нового агента
и не findings_bridge: `agent_health_monitor` уже ходит ежечасно ровно в эти же
источники (он сам производит `agent_health.json`), деплой нового агента — отдельный
owner-gated шаг (инвариант #12), а нагружать decision_loop/findings_bridge запрещено
явно.

Семантика (C6, amendment):
  * ключ Problem — ``(agent, cause_code)``, НЕ просто event_key;
  * условие, увиденное ОДИН раз, — occurrence внутри уже существующей/новой записи,
    статус ``INCIDENT`` (карточки ещё нет);
  * ``>= OPEN_THRESHOLD`` occurrences в скользящем окне ``WINDOW_DAYS`` → Problem
    открывается ОДИН раз (``OPEN``), рождается ОДНА agent-карточка с
    ``acceptance_probe: problem_absent:<problem_id>``, заданным ПРИ РОЖДЕНИИ
    (ADR-208, `.claude/rules/acceptance.md`);
  * повтор ТОЙ ЖЕ причины инкрементирует ``occurrences`` существующей записи — НЕ
    создаёт вторую карточку;
  * закрытие («CLOSED») требует rca ≠ null И отсутствия условия
    ``CLOSE_ABSENT_STREAK`` прогонов подряд; без RCA очищенное условие уходит в
    ``MITIGATED``, не в ``CLOSED`` (явная амендмент-формулировка REVIEW_1);
  * находки о флоте — agent-карточки (`type: agent-task`), НЕ owner-decision: fleet
    health не входит ни в один из трёх предметов владельца ADR-285.

Третий исход (инвариант #17): источник, который не прочитался в этом прогоне,
НИКОГДА не читается как «условия нет». Запись, чей источник сегодня НЕ ИЗМЕРЕН, не
двигает ни occurrences, ни consecutive_absences — её статус просто не меняется
(`store["sources"][source]["status"] == "not_measured"`).

Только stdlib. Атомарная запись — ``spa_core.utils.atomic.atomic_save``. LLM
запрещён (учёт и сверка, не суждение).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save
from spa_core.utils.live_paths import live_data_dir as _live_data_dir
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.problem_store")

_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILENAME = "problems.json"


def _default_data_dir() -> Path:
    """Живой каталог состояния — resolved AT CALL TIME via
    ``live_paths.live_data_dir`` (ADR-580 §C8, F3 REVIEW_1 amendment).

    Problem-store читает PROD-артефакты мониторинга (``agent_health.json`` и
    трое соседей), поэтому умолчание — прод-дерево (``live_data_dir`` honours
    ``SPA_DATA_DIR``/``SPA_LIVE_ROOT`` и САМ отказывает, если песочничный
    маркер C8 всё равно резолвится в прод). Литерал ``_REPO_ROOT / "data"``,
    вычисленный при ИМПОРТЕ модуля (как было здесь до F3), заслон тестов
    (autouse ``SPA_DATA_DIR``) не увидит никогда: переменная выставляется на
    каждый тест уже ПОСЛЕ импорта — ровно та бомба, из-за которой INC-1 увёл
    запись G97-зонда в прод. ``spa_core/tests/test_data_dir_env_ratchet.py``
    проверяет именно это свойство."""
    return _live_data_dir(_REPO_ROOT)

# Параметры храповика recurrence — документированные и настраиваемые, а не вшитые
# в формулу (REVIEW_1: «configurable, documented»). Имена зеркалят уже существующий
# словарь findings_bridge (REQUIRED_SIGHTINGS/REQUIRED_ABSENCES) — тот же дом, тот
# же смысл слов.
WINDOW_DAYS = 7
OPEN_THRESHOLD = 2          # >=N occurrences внутри WINDOW_DAYS -> Problem открывается
CLOSE_ABSENT_STREAK = 2     # >=N чистых прогонов подряд (после RCA) -> CLOSED

STATUS_INCIDENT = "INCIDENT"     # увидено, ниже порога — карточки ещё нет
STATUS_OPEN = "OPEN"             # Problem открыта — карточка есть
STATUS_MITIGATED = "MITIGATED"   # условие ушло, RCA нет
STATUS_CLOSED = "CLOSED"         # условие ушло, RCA есть, выдержан absent-streak

_STATUSES = (STATUS_INCIDENT, STATUS_OPEN, STATUS_MITIGATED, STATUS_CLOSED)

SOURCE_AGENT_HEALTH = "agent_health"
SOURCE_SYSTEM_HEALTH = "system_health"
SOURCE_SITE_FRESHNESS = "site_freshness"
SOURCE_SELF_HEAL = "self_heal"

#: источник → имя файла в data_dir. Единственное место, где это сопоставление
#: записано — проба и сборщик читают ОТСЮДА, а не по своей копии.
ARTIFACT_BY_SOURCE = {
    SOURCE_AGENT_HEALTH: "agent_health.json",
    SOURCE_SYSTEM_HEALTH: "system_health.json",
    SOURCE_SITE_FRESHNESS: "site_freshness_report.json",
    SOURCE_SELF_HEAL: "self_heal_status.json",
}

#: Charset пробы (`card_acceptance._ARG_RE`): буквы/цифры/`_.+-`, без `:`/`|`. Любой
#: символ сверх этого в агенте/cause_code заменяется на `_`, а не отбрасывается —
#: отбросить значило бы, что два разных агента могут схлопнуться в один problem_id.
_ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.+-]+")


def problem_key(agent: str, cause_code: str) -> str:
    """Ключ записи в ``store["problems"]`` — человекочитаемый, НЕ тот же текст, что
    отдаётся пробе (та требует charset без ``|``)."""
    return f"{agent}|{cause_code}"


def problem_id(agent: str, cause_code: str) -> str:
    """Id для ``acceptance_probe: problem_absent:<problem_id>`` — внутри charset пробы."""
    raw = f"{agent}.{cause_code}"
    safe = _ID_UNSAFE_RE.sub("_", raw).strip("_") or "problem"
    return safe[:120]


# ── чтение источников (read-only, никогда не пишет) ──────────────────────────

def _read_json(path: Path) -> tuple[Optional[dict], Optional[str]]:
    """(doc, error). ``doc`` is ``None`` on ЛЮБОЙ сбой — никогда пустой dict, иначе
    «файла нет» и «файл пуст» склеились бы (инвариант #17)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        import json
        return json.loads(text), None
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"


_STALE_LOG_RE = re.compile(r"log stale")
_EXIT_RE = re.compile(r"last_exit=(-?\d+)")


# Дробь целиком (``70.0/100``) — раньше одиночных чисел, иначе уходит только
# числитель и остаётся висящий ``/100``.
_FRACTION_RE = re.compile(r"\d+(?:[.,]\d+)?\s*/\s*\d+(?:[.,]\d+)?")
# Число + необязательная короткая единица, приклеенная без пробела (``3.3d``,
# ``27.3h``, ``70.0``) — буквы Unicode (``\w`` минус цифра/``_``), не только ASCII,
# чтобы ловить и русские суффиксы.
_VOLATILE_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?[^\W\d_]{0,3}")


def _strip_volatile_numbers(text: str) -> str:
    """Убрать дрейфующие числа (возраст/доля/счёт) из свободного текста — F1
    (ADR-580 §C6, REVIEW_1): `equity_curve stale 27.3h` и `equity_curve stale
    41.0h` — ОДНА причина, не две. Числа, которые САМИ являются причиной
    различия (например код выхода), нормализует отдельная ветка выше и эта
    функция их не трогает."""
    text = _FRACTION_RE.sub(" ", text)
    text = _VOLATILE_NUMBER_RE.sub(" ", text)
    return text


def cause_from_agent_issue(issue: str) -> Optional[str]:
    """Нормализовать `issue`-строку `agent_health.json` в стабильный `cause_code`.

    Публичная (без `_`): `agent_health_monitor._push_via_policy` зовёт ЭТУ же
    функцию, чтобы найти Problem, соответствующую текущей алерт-строке — вызовом,
    а не копией regex (иначе прибор и мерка разойдутся молча), и ТАКЖЕ зовёт её,
    чтобы построить дедуп-отпечаток пуша: дрейф числа внутри НЕИЗМЕННОЙ причины
    (`log stale 3.3d` → `3.5d`, `portfolio_health 70.0/100` → `68.0/100`) не
    обязан выглядеть новым инцидентом (F1).
    """
    issue = (issue or "").strip()
    if not issue:
        return None
    if _STALE_LOG_RE.search(issue):
        return "stale_log"
    m = _EXIT_RE.search(issue)
    if m:
        code = m.group(1)
        if code == "0":
            return None
        return f"exit_nonzero:{code}"
    stripped = _strip_volatile_numbers(issue.lower())
    cleaned = re.sub(r"\s+", "_", stripped)[:40].strip("_")
    return cleaned or None


#: Per-agent issue, written by `agent_health_monitor._retired_but_loaded()`, for a
#: ``RETIRED_LABELS`` agent launchd still has loaded — the EXACT SAME real-world fact
#: as the fleet-level "fleet parity DRIFT (… retired-still-installed …)" system issue
#: below, computed by a second, independent code path (live launchctl vs
#: `fleet_parity.json`). F10 (ADR-580 §C6, REVIEW_1 amendment): before this guard, BOTH
#: paths fed `collect()`, so N retired-but-loaded agents opened N+1 Problems (N
#: per-agent + 1 fleet-level) for ONE violation — measured on a copy of prod data,
#: +3 extra cards after deploy (digest_weekly, tier1_digest, weekly_backup).
_RETIRED_BUT_LOADED_RE = re.compile(r"^retired_but_loaded\b")


def _conditions_from_agent_health(doc: dict) -> list[dict]:
    out: list[dict] = []
    retired_loaded_agents: list[str] = []
    for a in (observed(doc, "agents", kind=list) or []):
        if not isinstance(a, dict):
            continue
        status = a.get("status")
        if status not in ("WARNING", "CRITICAL"):
            continue
        label = a.get("label")
        if not label:
            continue
        issue = a.get("issue") or ""
        if _RETIRED_BUT_LOADED_RE.match(issue.strip()):
            # Fold into the ONE fleet-level Problem below — never a per-agent one.
            retired_loaded_agents.append(label)
            continue
        cause = cause_from_agent_issue(issue) or f"status_{str(status).lower()}"
        out.append({"agent": label, "cause_code": cause, "severity": status,
                    "detail": issue or status, "source": SOURCE_AGENT_HEALTH})
    # retired-but-loaded (A4 §1, `weekly_backup`): всплывает внутри agent_health КАК
    # МИНИМУМ двумя путями — системной строкой fleet_parity DRIFT (без имени агента)
    # И per-agent WARNING-строками (отфильтрованными выше). Один факт ⇒ ОДНА запись,
    # что бы из двух путей его ни увидело — `detail` называет агентов поимённо, когда
    # они известны, точнее, чем агрегатный счётчик fleet_parity.
    fleet_drift_detail = None
    for issue in (observed(doc, "system_issues", kind=list) or []):
        if not isinstance(issue, str):
            continue
        if "retired-still-installed" in issue or "fleet parity DRIFT" in issue:
            fleet_drift_detail = issue
    if retired_loaded_agents or fleet_drift_detail:
        parts = []
        if retired_loaded_agents:
            parts.append("загружены: " + ", ".join(sorted(set(retired_loaded_agents))))
        if fleet_drift_detail:
            parts.append(fleet_drift_detail)
        out.append({"agent": "fleet", "cause_code": "retired_but_loaded",
                    "severity": "WARNING", "detail": "; ".join(parts),
                    "source": SOURCE_AGENT_HEALTH})
    return out


def _conditions_from_system_health(doc: dict) -> list[dict]:
    """Деградация доменов `system_health` — ОДНА причина, а не по Problem на домен.

    Домены d1…d7 — это срезы одного вердикта одного производителя, и их WARNING почти всегда
    вытекают из общих корней (публикация, флот, данные), которые уже ловят свои источники.
    Замер 2026-10-05 на копии прода: семь доменных WARNING открыли бы семь Problem и семь
    карточек на один и тот же вердикт (поправка владельца к RM-TRUTH-01, Wave 0: «не создавать
    пятнадцать Problem, если семь — одна причина»). Поэтому ключ — ``system_health|domains_degraded``,
    а список доменов уходит в `detail`; тяжесть — худшая из доменов.
    """
    domains = observed(doc, "domains", kind=dict) or {}
    bad = []
    for dom_id, dom in domains.items():
        if not isinstance(dom, dict):
            continue
        status = dom.get("status")
        if status in ("WARNING", "CRITICAL"):
            bad.append((str(dom_id), str(status)))
    if not bad:
        return []
    sev = "CRITICAL" if any(st == "CRITICAL" for _, st in bad) else "WARNING"
    detail = "домены: " + ", ".join(f"{d} {st}" for d, st in sorted(bad))
    return [{"agent": "system_health", "cause_code": "domains_degraded", "severity": sev,
             "detail": detail, "source": SOURCE_SYSTEM_HEALTH}]


#: Коды `site_freshness`, которые суть ОДИН корень — «публичная витрина отстала от канона».
#: PUBLISHER_STUCK (сайт стоит, снимок ушёл вперёд), SITE_BEHIND_SNAPSHOT (то же глазами
#: даты) и SHELF_NOT_ON_ORIGIN (полка не доставлена на origin) — разные взгляды на одну
#: остановившуюся публикацию; три Problem на неё научили бы читать Problem как шум.
SITE_PUBLICATION_FAMILY = frozenset({"PUBLISHER_STUCK", "SITE_BEHIND_SNAPSHOT",
                                     "SHELF_NOT_ON_ORIGIN"})


def _conditions_from_site_freshness(doc: dict) -> list[dict]:
    out: list[dict] = []
    family: list[tuple[str, str, str]] = []
    for f in (observed(doc, "fails", kind=list) or []):
        if not isinstance(f, dict):
            continue
        code = f.get("code")
        if not code:
            continue
        sev = "CRITICAL" if f.get("severity") == "CRITICAL" else "WARNING"
        if str(code) in SITE_PUBLICATION_FAMILY:
            family.append((str(code), sev, f.get("detail") or str(code)))
            continue
        out.append({"agent": "site_freshness", "cause_code": str(code), "severity": sev,
                    "detail": f.get("detail") or str(code), "source": SOURCE_SITE_FRESHNESS})
    if family:
        sev = "CRITICAL" if any(sv == "CRITICAL" for _, sv, _ in family) else "WARNING"
        codes = sorted({c for c, _, _ in family})
        out.append({"agent": "site_freshness", "cause_code": "publication_behind",
                    "severity": sev,
                    "detail": "; ".join([", ".join(codes)] + [d for _, _, d in family])[:500],
                    "source": SOURCE_SITE_FRESHNESS})
    return out


_SELF_HEAL_LABEL_RE = re.compile(r"(com\.spa\.[A-Za-z0-9_]+)\s*$")


def _cause_from_self_heal_failure(text: str) -> tuple[str, str]:
    m = _SELF_HEAL_LABEL_RE.search(text or "")
    agent = m.group(1) if m else "self_heal"
    reason = text[: m.start()].strip() if m else text.strip()
    cause = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_") or "failure"
    return agent, cause


def _conditions_from_self_heal(doc: dict) -> list[dict]:
    out: list[dict] = []
    for f in (observed(doc, "failures", kind=list) or []):
        if not isinstance(f, str) or not f.strip():
            continue
        agent, cause = _cause_from_self_heal_failure(f)
        out.append({"agent": agent, "cause_code": cause, "severity": "WARNING",
                    "detail": f, "source": SOURCE_SELF_HEAL})
    return out


_EXTRACTORS = {
    SOURCE_AGENT_HEALTH: _conditions_from_agent_health,
    SOURCE_SYSTEM_HEALTH: _conditions_from_system_health,
    SOURCE_SITE_FRESHNESS: _conditions_from_site_freshness,
    SOURCE_SELF_HEAL: _conditions_from_self_heal,
}


def collect(data_dir: Path, *, now: Optional[datetime] = None) -> tuple[list[dict], dict]:
    """Прочитать ЧЕТЫРЕ источника. Возврат — (conditions, source_status).

    ``source_status[source] = {"status": "measured"|"not_measured", "reason", "checked_at"}``.
    Нечитаемый источник НИКОГДА не превращается в пустой (= «чисто») список условий —
    он называется ``not_measured`` именованной причиной (инвариант #17) и исключается
    из обеих частей recurrence-счёта (`update_store`) для записей, которые от него зависят.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    conditions: list[dict] = []
    source_status: dict[str, dict] = {}
    for source, filename in ARTIFACT_BY_SOURCE.items():
        doc, err = _read_json(Path(data_dir) / filename)
        if not isinstance(doc, dict):
            source_status[source] = {
                "status": "not_measured",
                "reason": err or "корень артефакта не объект",
                "checked_at": now_iso,
            }
            continue
        source_status[source] = {"status": "measured", "reason": None, "checked_at": now_iso}
        try:
            conditions.extend(_EXTRACTORS[source](doc))
        except Exception as exc:  # noqa: BLE001 — сбой разбора — НЕ ИЗМЕРЕНО, не падение хука
            source_status[source] = {
                "status": "not_measured",
                "reason": f"{type(exc).__name__}: {exc}",
                "checked_at": now_iso,
            }
    return conditions, source_status


# ── хранилище (data/problems.json), атомарное ─────────────────────────────────

def load_store(data_dir: Path | str) -> dict:
    doc, _err = _read_json(Path(data_dir) / OUTPUT_FILENAME)
    if not isinstance(doc, dict):
        return {"problems": {}}
    if not isinstance(doc.get("problems"), dict):
        doc["problems"] = {}
    return doc


def save_store(data_dir: Path | str, store: dict) -> None:
    atomic_save(store, str(Path(data_dir) / OUTPUT_FILENAME))


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _prune_window(timestamps: list[str], now: datetime, window_days: int) -> list[str]:
    cutoff = now - timedelta(days=window_days)
    out = []
    for ts in timestamps:
        dt = _parse_iso(ts)
        if dt is not None and dt >= cutoff:
            out.append(ts)
    return out


@dataclass
class ProblemEvent:
    """Одна Problem, впервые перешедшая в ``OPEN`` в этом прогоне (ещё без карточки)."""
    problem_id: str
    key: str
    agent: str
    cause_code: str
    entry: dict


def update_store(
    store: dict,
    conditions: list[dict],
    source_status: dict,
    *,
    now: Optional[datetime] = None,
    window_days: int = WINDOW_DAYS,
    open_threshold: int = OPEN_THRESHOLD,
    close_absent_streak: int = CLOSE_ABSENT_STREAK,
) -> tuple[dict, list[ProblemEvent]]:
    """Обновить `store` ПО ПРАВИЛАМ C6. Чистая функция по состоянию: не читает диск,
    не пишет диск, не создаёт карточек — это (вместе) делает `run_once`.

    Третий исход в деле: запись, чей `source` в этом прогоне `not_measured`, —
    `continue` СРАЗУ, без единого изменения occurrences/consecutive_absences/status.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    problems: dict = store.setdefault("problems", {})
    store["generated_at"] = now_iso
    store["window_days"] = window_days
    store["open_threshold"] = open_threshold
    store["close_absent_streak"] = close_absent_streak
    store["sources"] = source_status

    observed_by_key: dict[str, dict] = {}
    for c in conditions:
        observed_by_key[problem_key(c["agent"], c["cause_code"])] = c

    # Завести запись для КАЖДОГО впервые увиденного ключа.
    for key, cond in observed_by_key.items():
        if key in problems:
            continue
        pid = problem_id(cond["agent"], cond["cause_code"])
        problems[key] = {
            "problem_id": pid,
            "agent": cond["agent"],
            "cause_code": cond["cause_code"],
            "source": cond["source"],
            "status": STATUS_INCIDENT,
            "occurrences": 0,
            "first_seen": now_iso,
            "last_seen": now_iso,
            "recent_observations": [],
            "consecutive_absences": 0,
            "detail": cond["detail"],
            "severity": cond["severity"],
            "rca": None,
            "card_path": None,
            "acceptance_probe": f"problem_absent:{pid}",
        }

    newly_opened: list[ProblemEvent] = []

    for key, p in list(problems.items()):
        source = p.get("source")
        src = source_status.get(source) if source else None
        if src is not None and src.get("status") != "measured":
            # Инвариант #17: НЕ ИЗМЕРЕНО не может сойти ни за присутствие, ни за
            # отсутствие. Запись просто не трогается этот прогон.
            p["last_check"] = "not_measured"
            continue

        cond = observed_by_key.get(key)
        if cond is not None:
            p["last_check"] = "present"
            p["detail"] = cond["detail"]
            p["severity"] = cond["severity"]
            p["occurrences"] = int(p.get("occurrences", 0)) + 1
            p["last_seen"] = now_iso
            p["consecutive_absences"] = 0
            p["recent_observations"] = _prune_window(
                list(p.get("recent_observations") or []) + [now_iso], now, window_days)
            prev_status = p["status"]
            if prev_status == STATUS_INCIDENT:
                if len(p["recent_observations"]) >= open_threshold:
                    p["status"] = STATUS_OPEN
            elif prev_status in (STATUS_MITIGATED, STATUS_CLOSED):
                p["status"] = STATUS_OPEN
                p["reopened_at"] = now_iso
            # OPEN остаётся OPEN.
            if p["status"] == STATUS_OPEN and p.get("card_path") is None:
                newly_opened.append(ProblemEvent(
                    problem_id=p["problem_id"], key=key, agent=p["agent"],
                    cause_code=p["cause_code"], entry=p))
        else:
            p["last_check"] = "absent"
            p["consecutive_absences"] = int(p.get("consecutive_absences", 0)) + 1
            if p["status"] in (STATUS_OPEN, STATUS_MITIGATED):
                if p.get("rca"):
                    if p["consecutive_absences"] >= close_absent_streak:
                        p["status"] = STATUS_CLOSED
                    else:
                        p["status"] = STATUS_OPEN
                else:
                    # Амендмент REVIEW_1, буквально: без RCA очищенное условие —
                    # MITIGATED, НИКОГДА CLOSED.
                    p["status"] = STATUS_MITIGATED
            # INCIDENT (порог не набран) / CLOSED — отсутствие больше ничего не меняет.

    return store, newly_opened


def record_rca(
    data_dir: Path | str,
    *,
    problem_id: Optional[str] = None,  # noqa: A002 — читаемое имя важнее линта
    agent: Optional[str] = None,
    cause_code: Optional[str] = None,
    cause: str,
    fix_ref: str = "",
    regression_test: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Записать RCA — ЕДИНСТВЕННЫЙ писатель поля ``rca``. Обязателен для CLOSED.

    Поиск — по ``problem_id`` (уникален) либо по паре ``(agent, cause_code)``.
    ``KeyError`` — Problem не заведена (RCA нельзя привязать к тому, что не открывалось).
    """
    data_dir = Path(data_dir)
    store = load_store(data_dir)
    problems = store.setdefault("problems", {})
    key = None
    if problem_id is not None:
        key = next((k for k, p in problems.items()
                   if isinstance(p, dict) and p.get("problem_id") == problem_id), None)
    if key is None and agent is not None and cause_code is not None:
        cand = problem_key(agent, cause_code)
        key = cand if cand in problems else None
    if key is None:
        raise KeyError(
            f"Problem не найдена (problem_id={problem_id!r}, agent={agent!r}, "
            f"cause_code={cause_code!r}) — RCA нельзя привязать к незаведённой записи")
    now = now or datetime.now(timezone.utc)
    problems[key]["rca"] = {
        "cause": cause, "fix_ref": fix_ref, "regression_test": regression_test,
        "recorded_at": now.isoformat(),
    }
    save_store(data_dir, store)
    return problems[key]


# ── карточка (agent-task, НЕ owner-decision — ADR-285) ────────────────────────

def _card_body(entry: dict, *, window_days: int, open_threshold: int,
               close_absent_streak: int) -> str:
    agent, cause_code = entry["agent"], entry["cause_code"]
    pid, key = entry["problem_id"], problem_key(agent, cause_code)
    return (
        f"## Что случилось\n"
        f"Условие `{cause_code}` у `{agent}` повторилось {open_threshold}+ раз за "
        f"{window_days} дн. (источник: `{entry['source']}`). Это Problem C6 "
        f"(ADR-580 §C6), ключ `{key}` — повторяющаяся причина, не разовый сбой.\n\n"
        f"## Почему это важно\n"
        f"Раньше повтор просто слал владельцу тот же алерт заново (замер A4_reliability.md: "
        f"14+14 CRIT/recovered флапов, 7 «bootstrap failed» за 35 минут). Эта карточка — "
        f"ОДНА на `({agent}, {cause_code})`: повтор инкрементирует `occurrences` в "
        f"`data/problems.json`, а не плодит вторую карточку на тот же повод.\n\n"
        f"**Что это НЕ означает** (F10, ADR-580 §C6 REVIEW_1 amendment — прежняя формулировка "
        f"здесь была неточной): сама карточка Telegram НЕ глушит, и её `status` на это не "
        f"влияет. Тишину при повторе ТОЙ ЖЕ причины даёт `push_policy`'s собственный "
        f"edge-триггер — и только когда зовущий передаёт УСТОЙЧИВЫЙ `dedup_key` (так с F1 "
        f"устроен `agent_health_critical`: отпечаток строится из кода причины "
        f"`cause_from_agent_issue`, а не из дрейфующего текста). У источника "
        f"`{entry['source']}` может быть своя, независимая проводка `push_policy` (другой "
        f"`event_key`, свой `dedup_key` или вовсе прямой зов без дедупа) — закрыть ЭТУ "
        f"карточку или оставить её открытой НЕ переключает тишину Telegram ни в одну "
        f"сторону; проверять надо `push_state.json` того `event_key`, а не статус Problem.\n\n"
        f"## Что нужно сделать\n"
        f"Найти корневую причину и записать её "
        f"(`spa_core.monitoring.problem_store.record_rca(problem_id={pid!r}, cause=..., "
        f"fix_ref=..., regression_test=...)`), затем починить так, чтобы условие "
        f"перестало наблюдаться.\n\n"
        f"## Как понять, что готово\n"
        f"Проба `problem_absent:{pid}` отвечает `satisfied`: RCA записан И условие не "
        f"наблюдалось {close_absent_streak} прогона(ов) подряд "
        f"(`data/problems.json → problems[\"{key}\"]`).\n"
    )


def _create_problem_card(
    entry: dict,
    *,
    tracker_dir: Optional[Path | str] = None,
    now: Optional[datetime] = None,
    window_days: int = WINDOW_DAYS,
    open_threshold: int = OPEN_THRESHOLD,
    close_absent_streak: int = CLOSE_ABSENT_STREAK,
) -> Optional[str]:
    """Создать ОДНУ agent-карточку. ``None`` — не создана (проба отвергнута / сбой
    записи); никогда не бросает — вызывающий (`run_once`) не имеет права упасть
    из-за того, что не получилось завести карточку."""
    try:
        from spa_core.monitoring.card_acceptance import validate_spec
        from spa_core.owner_queue.queue import create_card
    except Exception as exc:  # noqa: BLE001
        log.warning("problem_store: owner_queue/card_acceptance не импортированы: %s: %s",
                    type(exc).__name__, exc)
        return None

    probe_spec = entry["acceptance_probe"]
    reason = validate_spec(probe_spec)
    if reason is not None:
        log.warning("problem_store: карточка не создана — проба отвергнута: %s", reason)
        return None

    title = f"Повторяющийся сбой {entry['agent']}: {entry['cause_code']}"
    body = _card_body(entry, window_days=window_days, open_threshold=open_threshold,
                      close_absent_streak=close_absent_streak)
    extra = {
        "acceptance_probe": probe_spec,
        "problem_id": entry["problem_id"],
        "agent": entry["agent"],
        "cause_code": entry["cause_code"],
        # "problem_source", NOT "source": `create_card`'s own `source=` kwarg below
        # already writes a `source:` frontmatter line (card provenance — who/what
        # CREATED the card: "nimbalyst"/"obsidian"/"problem_store"). A second field
        # of the same name would silently double-write the key.
        "problem_source": entry["source"],
    }
    try:
        path = create_card("agent-task", title, body, status="backlog",
                           source="problem_store", extra_fields=extra,
                           tracker_dir=tracker_dir, now=now)
    except Exception as exc:  # noqa: BLE001 — «не создана» — не «упал хук»
        log.warning("problem_store: create_card упал: %s: %s", type(exc).__name__, exc)
        return None
    return str(path)


# ── единственная точка входа хука ─────────────────────────────────────────────

def run_once(
    data_dir: Optional[Path | str] = None,
    *,
    now: Optional[datetime] = None,
    tracker_dir: Optional[Path | str] = None,
    create_cards: bool = True,
    window_days: int = WINDOW_DAYS,
    open_threshold: int = OPEN_THRESHOLD,
    close_absent_streak: int = CLOSE_ABSENT_STREAK,
) -> dict:
    """Один тик хука: прочитать 4 артефакта → обновить `data/problems.json` → завести
    ОДНУ agent-карточку на каждую впервые ОТКРЫВШУЮСЯ Problem.

    Fail-safe, как соседние side-car'ы `agent_health_monitor` (`_write_fleet_economics`,
    `_write_orphaned_pytest`): НИКОГДА не бросает наружу — падение здесь не имеет права
    уронить пульс флота. Возврат — отчёт; `report["error"]` присутствует ТОЛЬКО когда
    что-то пошло не так (инвариант #17 — отсутствие ошибки не печатается как `None`,
    поле просто не появляется).

    ``data_dir=None`` (умолчание) резолвится В МОМЕНТ ВЫЗОВА через
    ``_default_data_dir()`` (F3) — НЕ при определении функции: значение по
    умолчанию в сигнатуре вычисляется один раз при импорте модуля, а именно
    так заслон SPA_DATA_DIR теряется молча (см. докстринг `_default_data_dir`).
    """
    data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    now = now or datetime.now(timezone.utc)
    report: dict = {
        "generated_at": now.isoformat(), "newly_opened": [], "cards_created": [],
        "sources": {}, "written": False,
    }
    try:
        conditions, source_status = collect(data_dir, now=now)
        report["sources"] = source_status
        store = load_store(data_dir)
        store, events = update_store(
            store, conditions, source_status, now=now, window_days=window_days,
            open_threshold=open_threshold, close_absent_streak=close_absent_streak)
        if create_cards:
            for ev in events:
                path = _create_problem_card(
                    ev.entry, tracker_dir=tracker_dir, now=now, window_days=window_days,
                    open_threshold=open_threshold, close_absent_streak=close_absent_streak)
                if path:
                    ev.entry["card_path"] = path
                    report["cards_created"].append({"problem_id": ev.problem_id, "path": path})
        save_store(data_dir, store)
        report["written"] = True
        report["newly_opened"] = [e.problem_id for e in events]
        report["open_count"] = sum(
            1 for p in store["problems"].values()
            if isinstance(p, dict) and p.get("status") == STATUS_OPEN)
    except Exception as exc:  # noqa: BLE001 — пульс флота важнее Problem-стора
        log.warning("problem_store.run_once упал: %s: %s", type(exc).__name__, exc)
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def main(argv: Optional[list] = None) -> int:
    """Ручной прогон для отладки (НЕ новый launchd-агент — расписание у `agent_health`)."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="SPA Problem-store (C6) — ручной прогон")
    parser.add_argument("--data-dir", default=str(_default_data_dir()))
    parser.add_argument("--no-cards", action="store_true")
    args = parser.parse_args(argv)
    report = run_once(Path(args.data_dir), create_cards=not args.no_cards)
    print(_json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
