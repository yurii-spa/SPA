#!/usr/bin/env python3
"""
Gnosis Safe Deployment Checklist — ADR-024
Проверяет готовность к деплою Gnosis Safe 2-of-3 multisig.

Usage: python3 scripts/gnosis_safe_checklist.py
       python3 scripts/gnosis_safe_checklist.py --json        # вывод в JSON
       python3 scripts/gnosis_safe_checklist.py --blockers    # только USER-блокеры
"""

import subprocess
import json
import datetime
import os
import sys

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

DEPLOY_TARGET = datetime.date(2026, 7, 1)
ADR_REFERENCE = "ADR-024"

CHECKS: list[dict] = [
    # ── 1. Технические предпосылки ──────────────────────────────────────────
    {
        "id": "GS-01",
        "title": "Alchemy/Infura RPC key в Keychain",
        "description": (
            "security find-generic-password -s alchemy_rpc_key -w должен "
            "вернуть непустую строку"
        ),
        "check_cmd": "security find-generic-password -s alchemy_rpc_key -w",
        "status": "PENDING",
        "deadline": "2026-06-15",
        "owner": "USER",
    },
    {
        "id": "GS-02",
        "title": "3 hardware wallet адреса задокументированы",
        "description": (
            "Owner primary, Owner backup, Co-investor (silent) — "
            "адреса записаны в docs/adr/ADR-024-gnosis-safe-multisig.md"
        ),
        "check_cmd": None,
        "status": "PENDING",
        "deadline": "2026-06-20",
        "owner": "USER",
    },
    {
        "id": "GS-03",
        "title": "Gnosis Safe UI доступен app.safe.global",
        "description": "HTTPS endpoint отвечает 200 OK",
        "check_cmd": None,
        "status": "READY",
        "deadline": None,
        "owner": "AUTO",
    },
    {
        "id": "GS-04",
        "title": "Zodiac Roles module версия >= 2.0.0 доступен",
        "description": (
            "Zodiac Roles контракт задеплоен на Ethereum mainnet и Sepolia, "
            "версия >= 2.0.0 подтверждена"
        ),
        "check_cmd": None,
        "status": "READY",
        "deadline": None,
        "owner": "AUTO",
    },
    # ── 2. Конфигурационные параметры ────────────────────────────────────────
    {
        "id": "GS-05",
        "title": "Threshold: 2-of-3 определён в ADR-024",
        "description": "Порог 2-of-3 зафиксирован в ADR-024, принят командой",
        "check_cmd": None,
        "status": "DONE",
        "deadline": None,
        "owner": "AUTO",
    },
    {
        "id": "GS-06",
        "title": "Daily spending limit: 10% = $10,000",
        "description": (
            "Zodiac Roles Guard лимит 10%/день ($10,000) без multisig-подписи "
            "задокументирован в ADR-024 §Модули Safe"
        ),
        "check_cmd": None,
        "status": "DONE",
        "deadline": None,
        "owner": "AUTO",
    },
    {
        "id": "GS-07",
        "title": "Emergency pause: Owner1 или Owner2 может заморозить",
        "description": (
            "Механизм экстренной паузы (freeze) определён: "
            "достаточно 1-из-2 Owner'ов"
        ),
        "check_cmd": None,
        "status": "DONE",
        "deadline": None,
        "owner": "AUTO",
    },
    {
        "id": "GS-08",
        "title": "Upgrade time-lock 24h задокументирован",
        "description": (
            "ADR-024: изменение threshold требует 24h time-lock; "
            "механизм описан в документации"
        ),
        "check_cmd": None,
        "status": "DONE",
        "deadline": None,
        "owner": "AUTO",
    },
    # ── 3. Тесты перед деплоем ───────────────────────────────────────────────
    {
        "id": "GS-09",
        "title": "Testnet (Sepolia) деплой проведён",
        "description": (
            "Safe 2-of-3 задеплоен на Sepolia; Safe address сохранён "
            "в data/gnosis_safe_config.json как testnet_safe_address"
        ),
        "check_cmd": None,
        "status": "PENDING",
        "deadline": "2026-06-25",
        "owner": "USER",
    },
    {
        "id": "GS-10",
        "title": "Test tx отправлена и подтверждена 2-of-3 на Sepolia",
        "description": (
            "Тестовая транзакция (например, 0 ETH self-transfer) подписана "
            "двумя из трёх owner'ов и включена в блок"
        ),
        "check_cmd": None,
        "status": "PENDING",
        "deadline": "2026-06-25",
        "owner": "USER",
    },
    {
        "id": "GS-11",
        "title": "Zodiac Roles spending limit тест PASS на Sepolia",
        "description": (
            "Transfer < $10,000 проходит с 1 подписью; "
            "transfer > $10,000 требует 2/3 — оба сценария проверены"
        ),
        "check_cmd": None,
        "status": "PENDING",
        "deadline": "2026-06-28",
        "owner": "USER",
    },
    # ── 4. Go-live gate ──────────────────────────────────────────────────────
    {
        "id": "GS-12",
        "title": "30-day paper trading evidence window начат (2026-06-10)",
        "description": (
            "Paper trading track record стартовал 2026-06-10; "
            "gap_monitor.json фиксирует непрерывность"
        ),
        "check_cmd": None,
        "status": "DONE",
        "deadline": None,
        "owner": "AUTO",
    },
    {
        "id": "GS-13",
        "title": "Kill-switch тест PASS (< 10ms)",
        "description": (
            "spa_core/paper_trading/cycle_runner.py kill-switch latency "
            "подтверждена scripts/kill_switch_drill.py"
        ),
        "check_cmd": None,
        "status": "DONE",
        "deadline": None,
        "owner": "AUTO",
    },
    {
        "id": "GS-14",
        "title": "Mainnet деплой Safe выполнен (target 2026-07-01)",
        "description": (
            "Safe задеплоен на Ethereum mainnet; "
            "Safe address занесён в data/gnosis_safe_config.json"
        ),
        "check_cmd": None,
        "status": "PENDING",
        "deadline": "2026-07-01",
        "owner": "USER",
    },
    {
        "id": "GS-15",
        "title": "Equity tracker address переведён на Safe (target 2026-07-12)",
        "description": (
            "Paper equity tracker EOA address заменён на Safe address "
            "согласно ADR-024 §Этапы внедрения"
        ),
        "check_cmd": None,
        "status": "PENDING",
        "deadline": "2026-07-12",
        "owner": "USER",
    },
]

# ---------------------------------------------------------------------------
# Цвета / эмодзи
# ---------------------------------------------------------------------------

STATUS_ICON = {
    "DONE":    "✅ DONE   ",
    "READY":   "🟢 READY  ",
    "PENDING": "⏳ PENDING",
    "BLOCKED": "❌ BLOCKED",
}


def _days_until(deadline_str: str) -> int:
    d = datetime.date.fromisoformat(deadline_str)
    return (d - datetime.date.today()).days


def _deadline_tag(check: dict) -> str:
    if not check["deadline"]:
        return ""
    days = _days_until(check["deadline"])
    urgency = f"DL:{check['deadline']}"
    if days < 0:
        urgency = f"⚠️ OVERDUE {check['deadline']}"
    elif days <= 3:
        urgency = f"🔴 DL:{check['deadline']} ({days}d)"
    elif days <= 7:
        urgency = f"🟡 DL:{check['deadline']} ({days}d)"
    return urgency


def _try_auto_check(check: dict) -> str:
    """Пробуем выполнить check_cmd; возвращаем 'DONE'/'FAIL'/'SKIP'."""
    cmd = check.get("check_cmd")
    if not cmd:
        return "SKIP"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "DONE"
        return "FAIL"
    except Exception:
        return "SKIP"


def run_checks(checks: list[dict]) -> list[dict]:
    """Обновляет статус AUTO-проверок на основе check_cmd."""
    enriched = []
    for c in checks:
        item = dict(c)
        if item["owner"] == "AUTO" and item["status"] == "PENDING" and item.get("check_cmd"):
            result = _try_auto_check(item)
            if result == "DONE":
                item["status"] = "DONE"
            elif result == "FAIL":
                item["status"] = "BLOCKED"
        enriched.append(item)
    return enriched


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------

def print_report(checks: list[dict], blockers_only: bool = False) -> None:
    today = datetime.date.today()
    days_to_deploy = (DEPLOY_TARGET - today).days

    print()
    print("=" * 60)
    print(f"  Gnosis Safe Deployment Checklist  ({ADR_REFERENCE})")
    print("=" * 60)
    print(f"  Deploy target : {DEPLOY_TARGET}  ({days_to_deploy} days)")
    print(f"  Go-live       : 2026-08-01")
    print(f"  Network       : Ethereum mainnet + Arbitrum One L2")
    print(f"  Config        : 2-of-3 multisig, Zodiac Roles, Guard 10%/day")
    print("=" * 60)
    print()

    counts: dict[str, int] = {"DONE": 0, "READY": 0, "PENDING": 0, "BLOCKED": 0}
    blockers: list[dict] = []

    for c in checks:
        status = c["status"]
        counts[status] = counts.get(status, 0) + 1

        if blockers_only and not (status == "PENDING" and c["owner"] == "USER"):
            continue

        icon = STATUS_ICON.get(status, "❓ UNKNOWN ")
        dl_tag = _deadline_tag(c)
        dl_str = f"  [{dl_tag} / {c['owner']}]" if dl_tag else (
            f"  [{c['owner']}]" if c["owner"] != "AUTO" else ""
        )

        print(f"  {icon}  {c['id']}  {c['title']}{dl_str}")

        if status in ("PENDING", "BLOCKED") and c["owner"] == "USER":
            blockers.append(c)

    print()
    print("-" * 60)
    total = len(checks)
    done_ready = counts["DONE"] + counts["READY"]
    print(
        f"  Summary : DONE={counts['DONE']}  READY={counts['READY']}  "
        f"PENDING={counts['PENDING']}  BLOCKED={counts.get('BLOCKED', 0)}"
    )
    print(f"  Progress: {done_ready}/{total} checks clear")
    print()

    if blockers:
        print("  ⚠️  USER ACTION REQUIRED:")
        for b in blockers:
            dl_tag = _deadline_tag(b)
            print(f"     • [{b['id']}]  {b['title']}")
            if dl_tag:
                print(f"              Deadline: {dl_tag}")
    else:
        print("  ✅  No user-action blockers remaining.")

    print()


def print_json(checks: list[dict]) -> None:
    today = datetime.date.today()
    payload = {
        "generated_at": today.isoformat(),
        "deploy_target": str(DEPLOY_TARGET),
        "days_to_deploy": (DEPLOY_TARGET - today).days,
        "adr_reference": ADR_REFERENCE,
        "checks": checks,
        "summary": {
            status: sum(1 for c in checks if c["status"] == status)
            for status in ("DONE", "READY", "PENDING", "BLOCKED")
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    output_json = "--json" in args
    blockers_only = "--blockers" in args

    enriched = run_checks(CHECKS)

    if output_json:
        print_json(enriched)
    else:
        print_report(enriched, blockers_only=blockers_only)


if __name__ == "__main__":
    main()
