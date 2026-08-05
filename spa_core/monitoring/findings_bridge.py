"""findings_bridge.py — мост «находка → карточка» (ADR-066, Фаза 3, C2).

Замыкает петлю: находки сторожа архитектуры и gap-анализа ПРЕВРАЩАЮТСЯ в
карточки бэклога сами, без надежды на то, что кто-то вручную прочитает отчёт.

Дисциплина против спама (каждое правило — против конкретного отказа):
  dedup        одна ОТКРЫТАЯ карточка на ключ находки — и не больше;
  гистерезис   WARN становится карточкой только с REQUIRED_SIGHTINGS-го
               подряд наблюдения (флаппинг не рождает мусор); CRITICAL — сразу;
  rate-limit   ≤ MAX_CARDS_PER_DAY карточек/сутки; излишек — в отчёт с
               пометкой deferred, ГРОМКО, не молча (правило «no silent caps»);
  авто-закрытие исчезнувшая находка закрывает свою карточку, но ТОЛЬКО если
               карточка нетронута (status=new); взятую в работу не трогаем;
  эскалация    WARN→CRITICAL по тому же ключу = новая карточка needs-owner.

Маршрутизация: CRITICAL → owner-decision (формат §2.4, 4 секции, по-русски)
+ Telegram-notify; WARN → inbox (agent-backlog). Всё — ТОЛЬКО через
scripts/orchestrator_queue.py (единственный мутационный API очереди).
Инвариант 14 соблюдён по построению: мост никогда не ставит owner-done.

Запуск: агент com.spa.decision_loop (каждые 6ч): сначала пересчёт
house_view_gap, затем мост. Состояние: data/findings_bridge_state.json;
отчёт: data/findings_bridge_report.json. LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT

STATE_REL = os.path.join("data", "findings_bridge_state.json")
REPORT_REL = os.path.join("data", "findings_bridge_report.json")

REQUIRED_SIGHTINGS = 2
MAX_CARDS_PER_DAY = 5
SUBPROC_TIMEOUT = 60


# ── сбор находок из источников ───────────────────────────────────────────────

def collect_findings(root: str = REPO_ROOT) -> tuple[list[dict], list[str]]:
    """[{key, severity, message, source}], [источники, которые не прочитались]."""
    findings: list[dict] = []
    unread: list[str] = []

    conf_rel = os.path.join("data", "architecture_conformance.json")
    try:
        conf = json.load(open(os.path.join(root, conf_rel)))
        for f in (conf.get("findings") or []):
            findings.append({"key": f["key"], "severity": f["severity"],
                             "message": f["message"], "source": "architecture_conformance"})
    except Exception:
        unread.append(conf_rel)

    gap_rel = os.path.join("data", "house_view_gap.json")
    try:
        gap = json.load(open(os.path.join(root, gap_rel)))
        for g in (gap.get("gaps") or []):
            if g.get("severity") in ("WARN", "CRITICAL"):
                findings.append({"key": g["key"], "severity": g["severity"],
                                 "message": g["message"], "source": "house_view_gap"})
    except Exception:
        unread.append(gap_rel)

    return findings, unread


# ── карточки через единственный мутационный API ──────────────────────────────

def _queue(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join(root, "scripts", "orchestrator_queue.py"), *args],
        capture_output=True, text=True, timeout=SUBPROC_TIMEOUT, cwd=root)


def create_card(root: str, finding: dict) -> str | None:
    """Создать карточку; вернуть путь к файлу карточки или None."""
    critical = finding["severity"] == "CRITICAL"
    if critical:
        body = (
            "## Что случилось и почему это важно\n"
            f"Сторож петли ({finding['source']}) нашёл КРИТИЧНОЕ расхождение с архитектурой:\n"
            f"{finding['message']}\n\n"
            "## Что от тебя нужно\n"
            "Посмотреть находку и решить: чиним / принимаем осознанно (тогда фиксируем "
            "решение в манифесте или ADR). Рекомендация агента — чинить: критичные "
            "находки этого класса уже стоили нам молчаливых отказов.\n\n"
            "## Как понять, что готово\n"
            "Находка исчезает из data/architecture_conformance.json при следующем прогоне.\n\n"
            "## Что будет после\n"
            "Мост сам закроет эту карточку, когда находка исчезнет; сторож продолжит "
            "следить, чтобы она не вернулась.\n\n"
            f"_finding_key: `{finding['key']}` · источник: {finding['source']} · ADR-066_\n")
        args = ["create", "--type", "owner-decision", "--status", "needs-owner",
                "--source", "nimbalyst",
                "--title", f"Критичная находка петли: {finding['message'][:70]}",
                "--body", body, "--field", f"finding_key={finding['key']}"]
    else:
        body = (f"Находка петли ADR-066 ({finding['source']}, WARN, подтверждена "
                f"{REQUIRED_SIGHTINGS} прогонами подряд):\n\n{finding['message']}\n\n"
                f"Сделано = находка исчезает из отчёта источника при следующем прогоне "
                f"(мост закроет карточку сам).\n\n"
                f"_finding_key: `{finding['key']}` · ADR-066_\n")
        args = ["create", "--type", "inbox", "--status", "new", "--source", "nimbalyst",
                "--title", f"Находка петли: {finding['message'][:70]}",
                "--body", body, "--field", f"finding_key={finding['key']}"]
    try:
        r = _queue(root, *args)
        if r.returncode != 0:
            return None
        path = (r.stdout or "").strip().splitlines()[-1].strip()
        return path if path.endswith(".md") else None
    except Exception:
        return None


def notify_card(root: str, card_path: str) -> bool:
    try:
        return _queue(root, "notify", card_path).returncode == 0
    except Exception:
        return False


def card_status(card_path: str) -> str | None:
    try:
        with open(card_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("status:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def close_card(root: str, card_path: str) -> bool:
    """Закрыть ТОЛЬКО нетронутую (new) карточку моста. Взятую в работу не трогаем."""
    if card_status(card_path) != "new":
        return False
    try:
        return _queue(root, "set-status", card_path, "done").returncode == 0
    except Exception:
        return False


# ── ядро моста ───────────────────────────────────────────────────────────────

def _load_state(root: str) -> dict:
    try:
        return json.load(open(os.path.join(root, STATE_REL)))
    except Exception:
        return {"findings": {}, "daily": {}}


def run_bridge(root: str = REPO_ROOT, now: dt.datetime | None = None,
               create=create_card, close=close_card, notify=notify_card) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    state = _load_state(root)
    findings, unread = collect_findings(root)
    current = {f["key"]: f for f in findings}
    st_findings: dict = state.setdefault("findings", {})
    daily: dict = state.setdefault("daily", {})
    created_today = int(daily.get(today, 0))

    created, deferred, closed, waiting, escalated = [], [], [], [], []

    for key, f in sorted(current.items()):
        entry = st_findings.get(key)
        if entry is None:
            entry = st_findings[key] = {"first_seen": now.isoformat(), "seen_count": 0,
                                        "severity": f["severity"], "card": None,
                                        "status": "observed"}
        entry["seen_count"] = int(entry.get("seen_count", 0)) + 1
        entry["last_seen"] = now.isoformat()

        esc = (f["severity"] == "CRITICAL" and entry.get("severity") != "CRITICAL"
               and entry.get("status") == "carded")
        entry["severity"] = f["severity"]
        needs_card = (entry.get("status") == "observed"
                      and (f["severity"] == "CRITICAL"
                           or entry["seen_count"] >= REQUIRED_SIGHTINGS)) or esc

        if not needs_card:
            if entry.get("status") == "observed":
                waiting.append(key)
            continue
        if created_today >= MAX_CARDS_PER_DAY:
            deferred.append(key)  # ГРОМКО в отчёте — не молчаливое обрезание
            continue
        path = create(root, f)
        if path:
            created_today += 1
            entry.update(status="carded", card=path, carded_at=now.isoformat())
            created.append({"key": key, "card": path, "severity": f["severity"]})
            if esc:
                escalated.append(key)
            if f["severity"] == "CRITICAL":
                notify(root, path)

    for key in sorted(set(st_findings) - set(current)):
        entry = st_findings[key]
        if entry.get("status") == "carded" and entry.get("card"):
            if close(root, entry["card"]):
                entry["status"] = "closed"
                entry["closed_at"] = now.isoformat()
                closed.append({"key": key, "card": entry["card"]})
            else:
                entry["status"] = "resolved_untouched"  # взята в работу — решит человек
                entry["resolved_at"] = now.isoformat()
        elif entry.get("status") == "observed":
            del st_findings[key]  # мигнула и исчезла — гистерезис отработал

    daily[today] = created_today
    report = {"generated_at": now.isoformat(), "adr": "ADR-066",
              "created": created, "deferred": deferred, "closed": closed,
              "waiting_hysteresis": waiting, "escalated": escalated,
              "sources_unread": unread,
              "open_cards": sum(1 for e in st_findings.values() if e.get("status") == "carded"),
              "rate_limit": {"max_per_day": MAX_CARDS_PER_DAY, "used_today": created_today}}

    from spa_core.utils.atomic import atomic_save
    atomic_save(state, os.path.join(root, STATE_REL))
    atomic_save(report, os.path.join(root, REPORT_REL))

    from spa_core.monitoring.consumption_receipts import write_receipt
    for rel in ("data/architecture_conformance.json", "data/house_view_gap.json"):
        if rel not in unread:
            write_receipt(rel, "findings_to_cards", root=root)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--skip-gap", action="store_true",
                    help="не пересчитывать house_view_gap перед мостом")
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0
    if not args.skip_gap:
        from spa_core.monitoring import house_view_gap
        house_view_gap.run(root=args.root)
    r = run_bridge(root=args.root)
    print(f"findings_bridge: created={len(r['created'])} closed={len(r['closed'])} "
          f"deferred={len(r['deferred'])} waiting={len(r['waiting_hysteresis'])} "
          f"open_cards={r['open_cards']} unread={r['sources_unread']}")
    for c in r["created"]:
        print(f"  + [{c['severity']}] {os.path.basename(c['card'])}")
    for c in r["closed"]:
        print(f"  ✓ закрыта {os.path.basename(c['card'])}")
    if r["deferred"]:
        print(f"  ⚠️ ОТЛОЖЕНО rate-limit'ом ({MAX_CARDS_PER_DAY}/сутки): {r['deferred']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
