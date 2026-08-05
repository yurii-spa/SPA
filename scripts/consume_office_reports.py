#!/usr/bin/env python3
"""consume_office_reports.py — обязательный шаг цикла оркестратора (ADR-066, Фаза 2).

Читает В КОНТЕКСТ сессии всё, что конституция (architecture/manifest.json)
объявила потребляемым оркестратором: продукты инвест-офиса, отчёт сторожа
соответствия, системный брифинг. Для каждого УСПЕШНО прочитанного артефакта
пишет квитанцию потребления (consumer = "orchestrator_protocol").

Честность:
  - отсутствующий/нечитаемый файл печатается как «❌ НЕ ПРОЧИТАН» и квитанцию
    НЕ получает;
  - скрипт информационный: exit 0 всегда, когда сам скрипт отработал —
    красные строки в выводе это сигналы ОРКЕСТРАТОРУ действовать (карточки),
    а не коды выхода;
  - ведом манифестом: новый consumer_required-продукт с потребителем
    "orchestrator_protocol" автоматически попадает в этот шаг без правки кода.

LLM_FORBIDDEN (детерминированный экстрактор; выводами занимается сессия).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, REPO_ROOT)

CONSUMER = "orchestrator_protocol"


def _summarize_json(path: str, data) -> list[str]:
    """Компактная выжимка известных офисных файлов; generic — для остальных."""
    name = os.path.basename(path)
    out: list[str] = []
    if not isinstance(data, dict):
        return [f"   (не-dict JSON, {type(data).__name__})"]
    if name == "chief_investment.json":
        hv = data.get("house_view") or {}
        out.append(f"   постура: {hv.get('overall_posture')}")
        for c in (hv.get("conflicts") or [])[:3]:
            out.append(f"   конфликт: {c}")
        for o in (hv.get("top_opportunities") or [])[:3]:
            v = o.get("value") or {}
            out.append(f"   возможность: {v.get('protocol')} {v.get('apy_pct')}% "
                       f"(evidence {o.get('evidence_level')})")
    elif name == "_health.json":
        out.append(f"   статус офиса: {data.get('status') or data.get('overall')}")
        for k in ("stale", "failing", "unknown"):
            if data.get(k):
                out.append(f"   {k}: {data[k]}")
    elif name == "architecture_conformance.json":
        c = data.get("counts") or {}
        out.append(f"   вердикт: {data.get('overall')} (critical={c.get('critical')} "
                   f"warn={c.get('warn')} aged={c.get('aged')} unchecked={c.get('unchecked')})")
        for f in (data.get("findings") or [])[:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        if (data.get("findings") or [])[8:]:
            out.append(f"   … ещё {len(data['findings']) - 8} наход(ок) в отчёте")
    elif name == "house_view_gap.json":
        c = data.get("counts") or {}
        out.append(f"   вердикт: {data.get('overall')} (critical={c.get('critical')} "
                   f"warn={c.get('warn')} aged={c.get('aged')} unchecked={c.get('unchecked')})")
        for f in (data.get("findings") or [])[:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        if (data.get("findings") or [])[8:]:
            out.append(f"   … ещё {len(data['findings']) - 8} расхожден(ий) в отчёте")
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u.get('check')}: {u.get('reason')}")
    elif name == "findings_bridge.json":
        c = data.get("counts") or {}
        out.append(f"   мост находка→карточка: открыто {c.get('opened')} · закрыто "
                   f"{c.get('closed')} · отложено {c.get('deferred')} · ждут подтверждения "
                   f"{c.get('pending')}")
        for f in (data.get("opened") or [])[:5]:
            out.append(f"   + карточка {f.get('card_path') or f.get('error')}")
        for f in (data.get("deferred") or [])[:5]:
            out.append(f"   … отложено: {f.get('key')}")
        for src, st in (data.get("sources") or {}).items():
            if not st.get("readable"):
                out.append(f"   [ИСТОЧНИК НЕ ПРОЧИТАН] {src}: {st.get('reason')}")
    else:
        status = data.get("status") or data.get("overall") or data.get("posture")
        if status is not None:
            out.append(f"   статус: {status}")
        reason = data.get("reason") or data.get("summary")
        if reason:
            out.append(f"   {str(reason)[:160]}")
        ts = data.get("generated_at")
        if ts:
            out.append(f"   generated_at: {ts}")
    return out or ["   (пусто)"]


def _summarize_md(full: str) -> list[str]:
    try:
        with open(full, encoding="utf-8") as f:
            head = [ln.rstrip() for _, ln in zip(range(12), f)]
        return ["   " + ln for ln in head if ln.strip()][:6]
    except Exception as e:  # noqa: BLE001
        return [f"   (md не прочитан: {e})"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--consumer", default=CONSUMER)
    ap.add_argument("--no-receipts", action="store_true",
                    help="только чтение/печать, без квитанций (для проверок)")
    args = ap.parse_args(argv)

    from spa_core.monitoring.consumption_receipts import write_receipt

    manifest_path = os.path.join(args.root, "architecture", "manifest.json")
    try:
        manifest = json.load(open(manifest_path))
    except Exception as e:  # noqa: BLE001
        print(f"❌ манифест не прочитан ({manifest_path}): {e} — шаг НЕ выполнен")
        return 1

    targets = [a["path"] for a in manifest.get("artifacts", [])
               if a.get("status") == "active" and args.consumer in (a.get("consumers") or [])]
    if not targets:
        print(f"❌ в манифесте нет active-артефактов с потребителем {args.consumer!r} — "
              f"проверить конституцию")
        return 1

    print(f"— офис и сторожа → контекст оркестратора ({len(targets)} артефактов) —")
    consumed = failed = 0
    for rel in sorted(targets):
        full = os.path.join(args.root, rel)
        lines: list[str]
        ok = False
        if not os.path.exists(full):
            lines = ["   файла нет на диске"]
        elif rel.endswith(".json"):
            try:
                lines = _summarize_json(rel, json.load(open(full)))
                ok = True
            except Exception as e:  # noqa: BLE001
                lines = [f"   JSON не прочитан: {e}"]
        else:
            lines = _summarize_md(full)
            ok = bool(lines) and not lines[0].startswith("   (md не прочитан")
        if ok:
            receipted = True if args.no_receipts else write_receipt(
                rel, args.consumer, root=args.root)
            mark = "✅" if receipted else "⚠️ (ресит НЕ записан)"
            consumed += 1
        else:
            mark = "❌ НЕ ПРОЧИТАН"
            failed += 1
        print(f"{mark} {rel}")
        for ln in lines:
            print(ln)
    print(f"— итог: прочитано {consumed}, не прочитано {failed}. "
          f"Красные строки выше = действовать (карточки), это не декорация. —")
    return 0


if __name__ == "__main__":
    sys.exit(main())
