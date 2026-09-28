"""Deterministic GREEN answers — read the SAME canonical sources the Visual OS projects from.

No LLM here (the free-form ask_router LLM stays as a fallback for unstructured questions). These are the
structured Owner-Remote queries: capital, strategies, system, attention, and the Aave vertical slice.
Same projection, same evidence, same truth as Desktop/Mobile.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(rel):
    try:
        return json.loads((REPO / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _usd(v):
    if v is None:
        return "н/д"
    try:
        return "$" + format(round(float(v)), ",").replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def answer_capital() -> str:
    p = _load("data/current_positions.json")
    if not isinstance(p, dict):
        return "Капитал: данные недоступны (data/current_positions.json)."
    mode = (p.get("execution_mode") or "paper")
    track = "PAPER (виртуальный)" if mode != "live" else "REAL"
    n = len((p.get("positions_detail") or {}))
    return (f"💰 Капитал — {track}\n"
            f"Всего: {_usd(p.get('capital_usd'))} · размещено {_usd(p.get('deployed_usd'))} · "
            f"свободно {_usd(p.get('cash_usd'))}\nПозиций: {n}. Это не реальные деньги.")


def answer_strategies(paper_only: bool = False) -> str:
    s = _load("data/strategy_summary.json")
    if not isinstance(s, dict):
        return "Стратегии: данные недоступны."
    items = s.get("strategies") or []
    from collections import Counter
    tiers = Counter(x.get("risk_tier") for x in items)
    head = "📚 Стратегии (советательный каталог, paper)" if paper_only else "📚 Стратегии (каталог)"
    return (f"{head}\nВсего: {len(items)} · "
            + " · ".join(f"{k}:{v}" for k, v in sorted(tiers.items()) if k)
            + "\nВсе — advisory/paper, капитал не двигают.")


def answer_system() -> str:
    rm = _load("studio_shell/read_model.json") or {}
    sysd = rm.get("system") or {}
    disp = (sysd.get("dispatch") or {})
    health = sysd.get("health") or {}
    ra = (health.get("risk_alerts") or {}).get("count")
    gl = sysd.get("golive") or {}
    parts = [f"диспетчер {'OPEN' if disp.get('open') else 'CLOSED'}"]
    if gl:
        parts.append(f"GoLive {gl.get('passed', '?')}/{gl.get('total', '?')}")
    if ra is not None:
        parts.append(f"risk-alerts {ra}")
    return "🛰️ Система: " + " · ".join(parts) + "." if parts else "Система: данные недоступны."


def answer_attention() -> str:
    rm = _load("studio_shell/read_model.json") or {}
    dec = ((rm.get("decisions") or {}).get("items")) or []
    counts = (rm.get("overview") or {}).get("counts") or {}
    owner_wait = (counts.get("owner_wait") or 0) + len(dec)
    blocked = counts.get("blocked") or 0
    failed = counts.get("failed") or 0
    if not (owner_wait or blocked or failed):
        return "✅ Ничего срочного: нет решений в ожидании, нет заблокированных/упавших задач."
    lines = ["❗ Требует внимания:"]
    if owner_wait:
        lines.append(f"• решений владельца в очереди: {owner_wait}")
    if blocked:
        lines.append(f"• заблокировано задач: {blocked}")
    if failed:
        lines.append(f"• упавших: {failed}")
    for d in dec[:3]:
        lines.append(f"  — {d.get('title', '')[:80]}")
    return "\n".join(lines)


def answer_broken() -> str:
    rm = _load("studio_shell/read_model.json") or {}
    counts = (rm.get("overview") or {}).get("counts") or {}
    health = ((rm.get("system") or {}).get("health") or {})
    ra = (health.get("risk_alerts") or {}).get("count") or 0
    failed = counts.get("failed") or 0
    if not (failed or ra):
        return "✅ Ничего явно не сломано: 0 упавших задач, 0 risk-alerts (по read model)."
    return f"⚠️ По read model: упавших задач {failed}, risk-alerts {ra}."


def _work_by_state():
    rm = _load("studio_shell/read_model.json") or {}
    from collections import defaultdict
    d = defaultdict(list)
    for w in (rm.get("work") or []):
        d[w.get("ui_state") or w.get("zone")].append(w)
    return d


def answer_active() -> str:
    d = _work_by_state()
    act = d.get("running", []) + d.get("review", [])
    if not act:
        return "▶️ Активных задач сейчас нет (running/review = 0). Источник: mission ledger."
    lines = [f"▶️ Активные задачи: {len(act)}"]
    for w in act[:6]:
        lines.append(f"• [{w.get('ui_state')}] {(w.get('title') or w.get('id'))[:80]}")
    return "\n".join(lines)


def answer_blocked() -> str:
    d = _work_by_state()
    bl = d.get("blocked", []) + d.get("failed", [])
    if not bl:
        return "✅ Ничего не заблокировано и не упало (blocked/failed = 0)."
    lines = [f"⛔ Заблокировано/упало: {len(bl)}"]
    for w in bl[:6]:
        lines.append(f"• [{w.get('ui_state')}] {(w.get('title') or w.get('id'))[:70]} — {w.get('reason_code','')}")
    return "\n".join(lines)


def answer_decisions_waiting() -> str:
    rm = _load("studio_shell/read_model.json") or {}
    dec = ((rm.get("decisions") or {}).get("items")) or []
    try:
        from spa_core.studio_os.decisions import list_drafts
        drafts = [d for d in list_drafts() if d["status"] in ("PROPOSED", "OWNER_REVIEW")]
    except Exception:
        drafts = []
    if not dec and not drafts:
        return "✅ Решений в ожидании нет."
    lines = [f"🟡 Ждут решения: {len(dec)} карточек владельца + {len(drafts)} черновиков (PROPOSED/OWNER_REVIEW)"]
    for d in dec[:4]:
        lines.append(f"• {d.get('title','')[:80]}")
    for d in drafts[:4]:
        lines.append(f"• [{d['status']}] {d['draft_id']}")
    return "\n".join(lines)


def answer_done_today() -> str:
    d = _work_by_state()
    done = d.get("done", [])
    lines = [f"✅ Недавно завершено: {len(done)} (read model — недавнее окно леджера)"]
    for w in done[:6]:
        lines.append(f"• {(w.get('title') or w.get('id'))[:80]}")
    return "\n".join(lines) if done else "Недавно завершённых задач в read model нет."


def answer_next_step() -> str:
    try:
        from spa_core.studio_os.context import build_context_pack
        p = build_context_pack("earn-defi-product")
        return "➡️ Следующий шаг: " + str(p["next_recommended_work"]["value"])
    except Exception:
        return "Следующий шаг: см. раздел РЕШЕНИЯ."


def answer_decided_about(topic: str) -> str:
    """'Что мы решили по X' — search decisions for the topic, prefer ACCEPTED decisions."""
    try:
        from spa_core.studio_os.search import search as _search
        hits = [h for h in _search(topic) if h["type"] in ("decision", "decision-draft")][:4]
        rep = [h for h in _search(topic) if h["type"] == "report"][:2]
    except Exception:
        hits, rep = [], []
    if not hits and not rep:
        return f"По «{topic}» принятых решений не нашёл. Возможно, это рабочая тема без ADR."
    lines = [f"🔎 По «{topic}»:"]
    for h in hits:
        lines.append(f"• {h['id']} ({h['type']}) → {h['ref']}")
    for r in rep:
        lines.append(f"• отчёт: {r['ref']}")
    return "\n".join(lines)


def answer_slice(protocol: str = "aave_v3") -> str:
    from spa_core.owner_remote.slice import build_investment_slice
    s = build_investment_slice(protocol)
    o, r, res = s["opportunity"], s["risk"], s["result"]
    label = s["entity"]["label"]
    apy = o["apy_pct"]["value"]
    ev = o["apy_evidence"]["value"]
    cap = s["capital"]["allocated_to_this"]["value"]
    lines = [f"📊 {label} — {res['label']['value']}",
             f"APY: {apy}% ({ev}) · TVL {_usd(o['tvl_usd']['value'])} ({o['tvl_source']['value']})",
             f"Капитал в объекте: {_usd(cap)} ({s['capital']['track']['value']})",
             f"Причина: {res['reason']['value']}"]
    return "\n".join(lines)


def answer_slice_missing(protocol: str = "aave_v3") -> str:
    from spa_core.owner_remote.slice import build_investment_slice
    s = build_investment_slice(protocol)
    miss = []
    for stage in ("opportunity", "position", "strategy"):
        for k, f in s[stage].items():
            if isinstance(f, dict) and f.get("status") in ("MISSING", "PARTIAL"):
                miss.append(f"{stage}.{k}: {f['status']}")
    label = s["entity"]["label"]
    if not miss:
        return f"{label}: всё ключевое доступно."
    return f"❓ Чего не хватает по {label}:\n" + "\n".join("• " + m for m in miss[:12])


def answer_why(protocol: str = "aave_v3") -> str:
    from spa_core.owner_remote.slice import build_investment_slice
    s = build_investment_slice(protocol)
    r = s["risk"]
    lines = [f"🔎 Почему {s['entity']['label']} не в живой аллокации:"]
    for g in r["gates"]["value"]:
        lines.append(f"{'✅' if g['pass'] else '⛔'} {g['rule']} (вход: {g['input']})")
    lines.append(f"Политика: RiskPolicy {r['policy_version']['value']} ({r['policy_kind']['value']}).")
    edges = s["why"]["missing_edges"]["value"]
    if edges:
        lines.append("Недостающие связи: " + ", ".join(edges))
    return "\n".join(lines)


_PROTO_ALIASES = [
    (("aave", "аав"), "aave_v3"),
    (("pendle", "пендл"), "pendle"),
    (("morpho", "морфо"), "morpho_steakhouse"),
    (("susde", "сусде"), "susde"),
    (("spark", "спарк"), "spark_susds"),
]


def _protocols_in(text: str) -> list[str]:
    t = (text or "").lower()
    found = []
    for aliases, pid in _PROTO_ALIASES:
        if any(a in t for a in aliases) and pid not in found:
            found.append(pid)
    return found


def answer_compare(protocol_a: str, protocol_b: str) -> str:
    from spa_core.owner_remote.compare import compare_slices
    c = compare_slices(protocol_a, protocol_b)
    a, b = c["a"], c["b"]

    def line(label, ka, kb):
        return f"{label}: {ka}  |  {kb}"
    lines = [f"⚖️ {a['protocol']}  vs  {b['protocol']} (факты, не рекомендация)",
             line("доказано APY", a["evidence"], b["evidence"]),
             line("APY %", a["apy_pct"], b["apy_pct"]),
             line("держим", "да $" + str(int(a["paper_capital_usd"] or 0)) if a["held"] else "нет",
                  "да $" + str(int(b["paper_capital_usd"] or 0)) if b["held"] else "нет"),
             line("гейты риска", a["risk_gates_passed"], b["risk_gates_passed"]),
             line("итог", a["result"], b["result"]),
             line("нет данных (полей)", a["missing_or_partial_fields"], b["missing_or_partial_fields"])]
    return "\n".join(lines)


# Routing table for GREEN structured queries → deterministic answer.
def route_green(text: str, view: str | None) -> str:
    t = (text or "").lower()
    if "сравни" in t or "compare" in t or " vs " in t or " против " in t:
        protos = _protocols_in(text)
        if len(protos) >= 2:
            return answer_compare(protos[0], protos[1])
        if len(protos) == 1:
            other = "pendle" if protos[0] != "pendle" else "aave_v3"
            return answer_compare(protos[0], other)
        return answer_compare("aave_v3", "pendle")
    # Studio OS operational queries (deterministic, from the same projections as desktop)
    if ("что мы решили" in t or "что решили" in t or "решили по" in t or "decided about" in t):
        import re as _re
        m = _re.search(r"(?:реши(?:ли)?\s+по|about)\s+(.+)", text, _re.I)
        topic = (m.group(1).strip(" ?.!") if m else text)
        return answer_decided_about(topic)
    if ("активн" in t and "задач" in t) or "active task" in t or "какие задачи" in t:
        return answer_active()
    if "заблокир" in t or "blocked" in t:
        return answer_blocked()
    if ("решени" in t and ("ждут" in t or "ждет" in t or "ожида" in t or "waiting" in t)) or "decisions waiting" in t:
        return answer_decisions_waiting()
    if ("сделано" in t and ("сегодня" in t or "today" in t)) or "done today" in t or "что было сделано" in t:
        return answer_done_today()
    if ("следующ" in t and "шаг" in t) or "next step" in t or "next action" in t:
        return answer_next_step()
    aave = "aave" in t or "аав" in t
    if aave and ("не хват" in t or "не хватает" in t or "каких данн" in t or "missing" in t):
        return answer_slice_missing("aave_v3")
    if aave and ("почему" in t or "why" in t or "не live" in t or "заблок" in t):
        return answer_why("aave_v3")
    if aave:
        return answer_slice("aave_v3")
    if "требует" in t or "внимани" in t or "attention" in t:
        return answer_attention()
    if "сломан" in t or "broken" in t or "не работает" in t:
        return answer_broken()
    if view == "capital" or "капитал" in t or "портфел" in t or "деньг" in t:
        return answer_capital()
    if view == "strategies" or "стратег" in t:
        return answer_strategies(paper_only=("paper" in t or "бумаг" in t))
    if view == "system" or "систем" in t:
        return answer_system()
    if view == "why" or "почему" in t:
        return answer_why("aave_v3")
    return ("Отвечаю по данным read model. Спроси: «покажи капитал», «какие стратегии», "
            "«что требует моего внимания», «статус Aave», «почему Aave не live».")
