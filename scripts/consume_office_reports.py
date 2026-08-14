#!/usr/bin/env python3
"""consume_office_reports.py — обязательный шаг цикла оркестратора (ADR-066, Фаза 2).

Читает В КОНТЕКСТ сессии всё, что конституция (architecture/manifest.json)
объявила потребляемым оркестратором: продукты инвест-офиса, отчёт сторожа
соответствия, системный брифинг. Для каждого УСПЕШНО прочитанного артефакта
пишет квитанцию потребления (consumer = "orchestrator_protocol").

Честность:
  - отсутствующий/нечитаемый файл печатается как «❌ НЕ ПРОЧИТАН» и квитанцию
    НЕ получает;
  - отсутствующее поле печатается как «НЕ ИЗМЕРЕНО», НИКОГДА как `None`:
    `None` в выводе читается глазом как «пусто, всё в порядке» — это ровно
    fail-OPEN, сторож молчит утвердительно;
  - у КАЖДОГО артефакта печатается возраст: рекомендация 19-часовой давности
    и рекомендация свежая — разные вещи, и решает это читатель, а не выжимка;
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
import datetime as dt
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, REPO_ROOT)

CONSUMER = "orchestrator_protocol"

# Порог, с которого возраст артефакта проговаривается вслух. Это МЕТКА ПЕЧАТИ,
# а не гейт: политика свежести офиса живёт в `investment_os/health.py` и здесь
# не дублируется. Смысл метки — 19.4 ч и 0.2 ч не должны выглядеть одинаково.
STALE_HOURS = 24.0

_UNMEASURED = "НЕ ИЗМЕРЕНО"

# ЧТО каждая именованная ветка читает у производителя — объявлено ДАННЫМИ, а не
# спрятано в теле ветки, и сверяется с настоящим артефактом на каждом прогоне.
#
# Почему так, а не «проверить ветки глазами». Класс «ветка читает поля, которых
# производитель не пишет» рецидивировал в ЭТОМ файле трижды подряд:
#   * `findings_bridge` — читала файл `findings_bridge.json` и `counts.opened/
#     pending`, которых нет ни у одного производителя (починено циклом #170);
#   * `house_view_gap` — читала `overall` / `counts.critical` / `findings`, а
#     производитель пишет `gaps` / `counts.warn|info|unchecked`, и обязательный
#     шаг печатал «вердикт: None» при ДВУХ реальных расхождениях (#176);
#   * `_health` — читала `stale` / `failing` / `unknown` на верхнем уровне, где
#     их нет: протухший аналитик не был бы назван вовсе (найдено тем же замером).
# Каждый раз это находили вручную и по одной ветке. Объявленная схема + строка
# «СХЕМА РАЗОШЛАСЬ» переводят проверку из «посмотреть внимательно» в измерение,
# которое само краснеет на живых файлах в тот цикл, когда производитель уехал.
#
# Путь с точкой — вложенное поле (`house_view.overall_posture`): у house_view
# всё интересное лежит на втором уровне, и проверка только верхнего уровня
# пропустила бы ровно тот дрейф, ради которого она заведена.
_READ_SCHEMA: dict[str, tuple[str, ...]] = {
    "chief_investment.json": ("house_view.overall_posture", "house_view.conflicts",
                              "house_view.top_opportunities"),
    "_health.json": ("overall", "counts.total", "counts.healthy", "counts.stale",
                     "counts.missing", "counts.unknown_or_corrupt", "analysts"),
    "architecture_conformance.json": ("overall", "counts.critical", "counts.warn",
                                      "counts.aged", "counts.unchecked", "findings"),
    "house_view_gap.json": ("gaps", "unchecked", "counts.warn", "counts.info",
                            "counts.unchecked"),
    "findings_bridge_report.json": ("created", "closed", "deferred", "waiting_hysteresis",
                                    "escalated", "sources_unread", "open_cards", "delivery"),
}

# Отметка времени в шапке md-артефакта: `Auto-updated: **2026-08-09 05:44 UTC**`.
_MD_TS_RE = re.compile(r"(20\d\d-\d\d-\d\d)[ T](\d\d:\d\d)(?::\d\d)?\s*UTC")


def _has_path(data, path: str) -> bool:
    """Есть ли (возможно вложенное) поле `a.b.c` — именно ЕСТЬ, а не истинно."""
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _schema_drift(name: str, data) -> list[str]:
    """Поля, которые ветка читает, а производитель не пишет — вслух."""
    missing = [p for p in _READ_SCHEMA.get(name, ()) if not _has_path(data, p)]
    if not missing:
        return []
    return ["   ⚠️ СХЕМА РАЗОШЛАСЬ: производитель не пишет " + ", ".join(missing)
            + " — выжимка ниже читает НЕ ТОТ файл. Это находка (карточка), а не деталь."]


def _num(container, key):
    """Счётчик или явное «НЕ ИЗМЕРЕНО».

    Отсутствующий счётчик — это НЕ ноль, а неизмеренная величина (fail-CLOSED).
    """
    if not isinstance(container, dict) or key not in container:
        return _UNMEASURED
    v = container.get(key)
    return _UNMEASURED if v is None else v


def _parse_ts(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _age_line(ts_value, now: dt.datetime) -> str:
    """Возраст артефакта — безусловно, для КАЖДОГО артефакта.

    Отдельная строка, а не свойство generic-ветки: до #176 возраст печатался
    только тем артефактам, у которых не нашлось именованной ветки, и самый
    важный из них — house_view — ехал в контекст оркестратора без единого
    признака возраста (замер: 19.4 ч, и три «возможности» в нём были дофиксовые).
    """
    if ts_value is None:
        return "   ⚠️ возраст НЕ ИЗМЕРЕН: производитель не пишет generated_at"
    parsed = _parse_ts(ts_value)
    if parsed is None:
        return f"   ⚠️ возраст НЕ ИЗМЕРЕН: generated_at не разобран ({ts_value!r})"
    hours = (now - parsed).total_seconds() / 3600.0
    mark = "  ⚠️ старше суток" if hours >= STALE_HOURS else ""
    return f"   generated_at: {ts_value} (возраст {hours:.1f}ч){mark}"


def _summarize_json(path: str, data, *, now: dt.datetime | None = None) -> list[str]:
    """Компактная выжимка известных офисных файлов; generic — для остальных."""
    name = os.path.basename(path)
    if not isinstance(data, dict):
        return [f"   (не-dict JSON, {type(data).__name__})"]
    now = now or dt.datetime.now(dt.timezone.utc)
    head: list[str] = _schema_drift(name, data)
    head.append(_age_line(data.get("generated_at"), now))
    out: list[str] = []
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
        # Схема ВЫМЕРЕНА по производителю (`investment_os/health.py`): счётчики
        # лежат в `counts`, а строки аналитиков — в `analysts`. Прежняя ветка
        # читала `stale`/`failing`/`unknown` на верхнем уровне: ни одного такого
        # поля нет, поэтому «протух аналитик» шаг 0-офис не сказал бы НИКОГДА —
        # печаталась одна строка «статус офиса», и она читалась как весь ответ.
        c = data.get("counts") or {}
        out.append(f"   статус офиса: {data.get('overall') or data.get('status')}")
        out.append(f"   аналитики: всего {_num(c, 'total')} · здоровы {_num(c, 'healthy')} · "
                   f"протухли {_num(c, 'stale')} · нет файла {_num(c, 'missing')} · "
                   f"нечитаемы {_num(c, 'unknown_or_corrupt')}")
        for a in (data.get("analysts") or []):
            if not isinstance(a, dict):
                continue
            if a.get("present") and a.get("fresh") and a.get("status") == "ok":
                continue
            out.append(f"   ⚠️ аналитик {a.get('agent')}: present={a.get('present')} "
                       f"fresh={a.get('fresh')} status={a.get('status')}")
    elif name == "architecture_conformance.json":
        c = data.get("counts") or {}
        out.append(f"   вердикт: {data.get('overall') or _UNMEASURED} "
                   f"(critical={_num(c, 'critical')} warn={_num(c, 'warn')} "
                   f"aged={_num(c, 'aged')} unchecked={_num(c, 'unchecked')})")
        for f in (data.get("findings") or [])[:8]:
            out.append(f"   [{f.get('severity')}] {f.get('message')}")
        if (data.get("findings") or [])[8:]:
            out.append(f"   … ещё {len(data['findings']) - 8} наход(ок) в отчёте")
    elif name == "house_view_gap.json":
        # Схема ВЫМЕРЕНА по производителю (`monitoring/house_view_gap.py`):
        # расхождения лежат в `gaps`, счётчики — `warn`/`info`/`unchecked`.
        # Прежняя ветка читала `overall`/`counts.critical`/`findings` — ни одного
        # такого поля производитель не пишет, и обязательный шаг печатал
        # «вердикт: None (critical=None …)» при ДВУХ реальных расхождениях.
        # «None» глазом читается как «пусто, всё в порядке» — тот же fail-OPEN,
        # что уже разбирали соседней веткой в этом же файле.
        c = data.get("counts") or {}
        gaps = data.get("gaps") or []
        out.append(f"   расхождений house_view↔факт: {len(gaps)} "
                   f"(warn={_num(c, 'warn')} info={_num(c, 'info')} "
                   f"unchecked={_num(c, 'unchecked')})")
        for g in gaps[:8]:
            out.append(f"   [{g.get('severity')}] {g.get('message')}")
        if gaps[8:]:
            out.append(f"   … ещё {len(gaps) - 8} расхожден(ий) в отчёте")
        for u in (data.get("unchecked") or [])[:4]:
            out.append(f"   [НЕ ИЗМЕРЕНО] {u.get('check')}: {u.get('reason')}")
    elif name == "findings_bridge_report.json":
        # Имя и схема ВЫМЕРЕНЫ по производителю (`findings_bridge.REPORT_REL`),
        # а не по памяти: ветка звалась `findings_bridge.json` и читала поля
        # `counts.opened/pending` — такого файла нет ни у одного производителя,
        # такой схемы нет ни в одном отчёте. Ветка была мёртвой, и обязательный
        # шаг 0-офис печатал по мосту одну строку `generated_at`, хотя манифест
        # требует «deferred читать ОБЯЗАТЕЛЬНО». Тот же класс, что #144: правка
        # детали при мёртвой проводке зелёная и бесполезная.
        out.append(f"   мост находка→карточка: создано {len(data.get('created') or [])} · "
                   f"закрыто {len(data.get('closed') or [])} · отложено "
                   f"{len(data.get('deferred') or [])} · ждут гистерезиса "
                   f"{len(data.get('waiting_hysteresis') or [])} · "
                   f"открытых карточек {_num(data, 'open_cards')}")
        for f in (data.get("created") or [])[:5]:
            out.append(f"   + [{f.get('severity')}] карточка {f.get('card')}")
        for k in (data.get("deferred") or [])[:5]:
            out.append(f"   ⚠️ ОТЛОЖЕНО rate-limit'ом (карточки НЕТ): {k}")
        for k in (data.get("escalated") or [])[:5]:
            out.append(f"   ⬆️ эскалация WARN→CRITICAL: {k}")
        for src in (data.get("sources_unread") or []):
            out.append(f"   [ИСТОЧНИК НЕ ПРОЧИТАН] {src}")
        # Доставка карточек на origin: `needs-owner` вне origin для очереди
        # владельца не существует, поэтому провал доставки — находка, а не деталь.
        d = data.get("delivery") or {}
        if d:
            st = d.get("status")
            if st in ("DELIVERED", "IDLE"):
                out.append(f"   доставка карточек: {st} ({len(d.get('delivered') or [])} на origin)")
            else:
                out.append(f"   ⚠️ ДОСТАВКА КАРТОЧЕК {st}: {d.get('reason')} "
                           f"(пыталось {len(d.get('attempted') or [])})")
            # Долг доставки (ADR-081) — ОТДЕЛЬНАЯ строка, а не хвост статуса.
            # Статус говорит про ЭТОТ прогон, долг — про то, чего на origin нет
            # до сих пор; 12.08 схлопывание этих двух вопросов в один означало,
            # что через два часа `IDLE` покажет зелёную строку при трёх
            # недоставленных карточках, и потеря исчезнет из поля зрения.
            debt = d.get("debt")
            if debt is None:
                out.append("   ⚠️ долг доставки НЕ ИЗМЕРЕН: в квитанции нет блока debt "
                           "(отчёт старого образца — до ADR-081)")
            elif debt.get("unmeasured"):
                out.append(f"   ⚠️ долг доставки НЕ ИЗМЕРЕН: {debt['unmeasured']}")
            elif debt.get("count"):
                age = debt.get("oldest_hours")
                age_s = f"старшему {age}ч" if age is not None else "возраст не датируется"
                out.append(f"   ⚠️ ДОЛГ ДОСТАВКИ: {debt['count']} карточк(и) НЕ на origin "
                           f"({age_s}) — поедут следующим прогоном")
                after = debt.get("stale_after")
                for p in (debt.get("stale") or [])[:5]:
                    out.append(f"   ⛔ не рассасывается повтором "
                               f"(≥{after if after is not None else '?'} попыток), "
                               f"нужен человек: {p}")
                for dr in (debt.get("dropped") or [])[:5]:
                    out.append(f"   ⚠️ снято с долга: {dr.get('path')} — {dr.get('reason')}")
        else:
            out.append("   ⚠️ доставка карточек НЕ ИЗМЕРЕНА: в отчёте нет блока delivery")
    elif name == "owner_decision_pending.json":
        out.append(f"   статус: {data.get('status')}")
        if data.get("reason"):
            out.append(f"   {str(data['reason'])[:160]}")
        # Канал: уезжали ли владельцу сообщения с вариантами БЕЗ кнопок (жалоба 14.08).
        # Печатаем ОТДЕЛЬНОЙ строкой и всегда: молчание про этот вопрос читалось бы как
        # «кнопки в порядке», а до цикла #229 он был неизмерим по построению.
        ch = data.get("channel_buttons")
        if not isinstance(ch, dict):
            out.append("   ⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: в отчёте нет блока "
                       "channel_buttons (отчёт старого образца)")
        elif not ch.get("measured"):
            out.append(f"   ⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: {ch.get('reason')}")
        else:
            # Импорт локальный и защищённый: обязательный шаг 0-офис не имеет права
            # упасть из-за строчки оформления — упавший шаг это НЕ прочитанный офис.
            try:
                from spa_core.telegram.buttonless_audit import summary_line

                line = summary_line(ch)
            except Exception as exc:  # noqa: BLE001
                line = (f"⚠️ кнопки в канале НЕ ИЗМЕРЕНЫ: строку не собрать ({exc})")
            out.append(f"   {line}")
    else:
        status = data.get("status") or data.get("overall") or data.get("posture")
        if status is not None:
            out.append(f"   статус: {status}")
        reason = data.get("reason") or data.get("summary")
        if reason:
            out.append(f"   {str(reason)[:160]}")
    return head + (out or ["   (пусто)"])


def _summarize_md(full: str, *, now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        with open(full, encoding="utf-8") as f:
            head = [ln.rstrip() for _, ln in zip(range(12), f)]
    except Exception as e:  # noqa: BLE001
        return [f"   (md не прочитан: {e})"]
    stamp = None
    for ln in head:
        m = _MD_TS_RE.search(ln)
        if m:
            stamp = f"{m.group(1)}T{m.group(2)}:00+00:00"
            break
    body = ["   " + ln for ln in head if ln.strip()][:6]
    return [_age_line(stamp, now)] + body


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--consumer", default=CONSUMER)
    ap.add_argument("--no-receipts", action="store_true",
                    help="только чтение/печать, без квитанций (для проверок)")
    args = ap.parse_args(argv)
    now = now or dt.datetime.now(dt.timezone.utc)

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
                lines = _summarize_json(rel, json.load(open(full)), now=now)
                ok = True
            except Exception as e:  # noqa: BLE001
                lines = [f"   JSON не прочитан: {e}"]
        else:
            lines = _summarize_md(full, now=now)
            ok = bool(lines) and not any(
                ln.startswith("   (md не прочитан") for ln in lines)
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
