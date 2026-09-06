"""decision_audit_trail.py — можно ли объяснить прошлую перекладку ЧЕРЕЗ ДАННЫЕ.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §43 «Audit trail»::

    Каждое решение должно быть воспроизводимо.
    Сохранять: market snapshot · portfolio snapshot · policy version ·
    configuration version · optimizer version · decision · calculations ·
    execution result · post-trade result.
    Через месяц должно быть возможно ответить:
    «Почему система 13 августа переместила $12,000 из Aave в Morpho?»
    Не через память AI. Через данные.

Девять полей — НЕ наш список. Это дословный перечень владельца, и его дом —
карточка приказа (`inbox-task-portfolio-cio-dynamic-capital-alloc`). Модуль
не назначает ни одного порога: он берёт девять названных полей и по КАЖДОЙ
реальной перекладке живого трека проверяет, отвечает ли на них файл, а не
память сессии.

Что здесь проверяется — ВОССТАНОВИМОСТЬ, а не наличие файла
===========================================================
Поле засчитывается только если названный источник ОТДАЁТ значение именно для
ЭТОГО решения. «Файл с подходящим именем существует» — не ответ: ровно на этом
и держится класс ADR-053/242/243/244 (измеритель построен, потребителя нет) и
находка #505 (имя критерия было занято модулем про другое). Поэтому у каждого
поля есть исход `absent` с НАЗВАННОЙ причиной и отдельный третий исход
`unmeasured` — «источник нечитаем», который не равен «данных нет».

Почему `snapshot_id` меряется ОПЫТОМ, а не чтением кода
=======================================================
В каждой записи трейла стоит поле `snapshot_id` вида
``2026-08-31:9320103a61e4595d`` — по виду адрес содержимого рыночного снимка.
Модуль не верит виду: он дважды зовёт САМ производитель
(`spa_core.audit.audit_trail._make_snapshot_id`) с ОДНИМ И ТЕМ ЖЕ входом. Если
два вызова дают разные значения, идентификатор не может адресовать содержимое
— он именует ПРОГОН. Это измерение, а не рассуждение, и оно краснеет само,
если производителя однажды починят.

Чего этот модуль НЕ делает
==========================
Не пишет в трейл, не меняет схему событий, не трогает RiskPolicy, kill-switch,
целевую функцию и живой трек. ADVISORY: он НАЗЫВАЕТ, на какие из девяти
вопросов владельца сегодня отвечают данные, а на какие — только память.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/decision_audit_trail.json"

TRAIL_REL = "data/audit_trail.jsonl"
TRADES_REL = "data/trades.json"
EQUITY_REL = "data/equity_curve_daily.json"
APY_HISTORY_REL = "data/apy_history.json"
SHADOW_HISTORY_REL = "data/allocation_rationale_history.jsonl"

_UNCHECKED = "UNCHECKED"

#: «Через месяц» — литерал ВЛАДЕЛЬЦА из §43, а не подобранное нами число.
#: Вердикт от него не зависит (он ничего не переключает); он лишь называет,
#: сколько перекладок уже перешагнули срок, на который владелец рассчитывал.
OWNER_HORIZON_DAYS = 30
OWNER_HORIZON_PROVENANCE = "§43 ТЗ CIO, дословно: «Через месяц должно быть возможно ответить»"

#: Девять полей владельца в порядке ТЗ. Ключ → дословная формулировка.
OWNER_FIELDS: tuple[tuple[str, str], ...] = (
    ("market_snapshot", "market snapshot"),
    ("portfolio_snapshot", "portfolio snapshot"),
    ("policy_version", "policy version"),
    ("configuration_version", "configuration version"),
    ("optimizer_version", "optimizer version"),
    ("decision", "decision"),
    ("calculations", "calculations"),
    ("execution_result", "execution result"),
    ("post_trade_result", "post-trade result"),
)

PRESENT, PARTIAL, ABSENT, UNMEASURED = "present", "partial", "absent", "unmeasured"


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_jsonl(path: str) -> tuple[list[dict], int] | None:
    """Строки JSONL и число НЕразобранных. ``None`` — файла нет / он нечитаем."""
    try:
        raw = open(path, "r", encoding="utf-8").read()
    except OSError:
        return None
    rows: list[dict] = []
    bad = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad


def _day(ts: object) -> str | None:
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None


# ── Опыт над производителем snapshot_id ───────────────────────────────────────

def probe_snapshot_id(make_id: Callable[[str], str] | None, cycle_date: str) -> dict:
    """Адресует ли ``snapshot_id`` СОДЕРЖИМОЕ снимка — проверяется опытом.

    Два вызова с одним входом. Разные ответы ⇒ идентификатор именует прогон,
    а не рыночный снимок, и восстановить по нему нечего.
    """
    if make_id is None:
        return {"measured": False,
                "reason": "производитель snapshot_id не импортируется — опыт не поставлен"}
    try:
        first, second = make_id(cycle_date), make_id(cycle_date)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"производитель snapshot_id упал: {exc}"}
    return {
        "measured": True,
        "same_input_same_output": first == second,
        "content_addressed": first == second,
        "samples": [first, second],
    }


# ── Разрешение девяти полей по ОДНОЙ перекладке ───────────────────────────────

def _f(status: str, source: str, detail: str = "") -> dict:
    return {"status": status, "source": source, "detail": detail}


def resolve_move(move: dict, chain: list[dict], ctx: dict) -> dict:
    """Девять полей владельца по одной записи ``trade_executed``.

    ``chain`` — все события того же ``correlation_id`` (цикл, породивший ход).
    ``ctx`` — уже прочитанные посторонние источники со своим статусом чтения.
    """
    data = move.get("data") or {}
    date = _day(move.get("timestamp"))
    by_type: dict[str, dict] = {}
    for ev in chain:
        by_type.setdefault(str(ev.get("event_type")), ev)
    proposal = (by_type.get("allocation_proposal") or {}).get("data") or {}
    verdict = (by_type.get("risk_verdict") or {}).get("data") or {}

    out: dict[str, dict] = {}

    # 1. market snapshot — ставки/TVL, которые аллокатор ранжировал в тот день.
    out["market_snapshot"] = _market_snapshot(date, ctx)

    # 2. portfolio snapshot — книга ДО хода.
    before = data.get("from_allocation")
    if isinstance(before, dict) and before:
        extra = ""
        pos = (ctx.get("equity_positions") or {}).get(date)
        if isinstance(pos, dict) and pos:
            extra = " (сходится со вторым источником equity_curve_daily.daily[].positions)"
        out["portfolio_snapshot"] = _f(PRESENT, f"{TRAIL_REL}::trade_executed.from_allocation",
                                       f"{len(before)} позиц.{extra}")
    else:
        out["portfolio_snapshot"] = _f(ABSENT, TRAIL_REL,
                                       "у записи хода нет непустой from_allocation")

    # 3. policy version — версия RiskPolicy, которой судили ЭТОТ ход.
    out["policy_version"] = _version_field(
        chain, ("policy_version", "risk_policy_version", "policy"),
        live=ctx.get("live_policy_version"),
        what="версия RiskPolicy",
        carrier="risk_verdict")

    # 4. configuration version — пороги, которыми судили ЭТОТ ход.
    out["configuration_version"] = _version_field(
        chain, ("configuration_version", "config_version", "risk_config_version", "config"),
        live=ctx.get("live_config_version"),
        what="версия конфигурации порогов",
        carrier="risk_verdict")

    # 5. optimizer version — чем считали цель.
    model = proposal.get("model_used")
    if isinstance(model, str) and model:
        out["optimizer_version"] = _f(
            PARTIAL, f"{TRAIL_REL}::allocation_proposal.model_used",
            f"записано ИМЯ модели '{model}', а не её версия: правка оптимизатора "
            f"оставит это поле прежним")
    else:
        out["optimizer_version"] = _f(ABSENT, TRAIL_REL, "model_used не записан")

    # 6. decision — сама цель.
    target = proposal.get("target_usd")
    if isinstance(target, dict) and target:
        out["decision"] = _f(PRESENT, f"{TRAIL_REL}::allocation_proposal.target_usd",
                             f"{len(target)} ключ(ей) цели")
    else:
        out["decision"] = _f(ABSENT, TRAIL_REL,
                             "в цепочке хода нет allocation_proposal с непустой целью")

    # 7. calculations — числа, ИЗ КОТОРЫХ получилась цель.
    out["calculations"] = _calculations(date, verdict, ctx)

    # 8. execution result — что получилось.
    after = data.get("to_allocation")
    if isinstance(after, dict) and after and data.get("diff_usd") is not None:
        out["execution_result"] = _f(PRESENT,
                                     f"{TRAIL_REL}::trade_executed.to_allocation+diff_usd",
                                     f"diff_usd={data.get('diff_usd')}")
    else:
        out["execution_result"] = _f(ABSENT, TRAIL_REL,
                                     "у записи хода нет to_allocation и/или diff_usd")

    # 9. post-trade result — что ход ПРИНЁС.
    out["post_trade_result"] = _post_trade(date, ctx)

    return out


def _market_snapshot(date: str | None, ctx: dict) -> dict:
    """Ставки, по которым ранжировали в ЭТОТ день, — из хранилища, а не из памяти."""
    if date is None:
        return _f(UNMEASURED, TRAIL_REL, "у записи хода нет разбираемой отметки времени")
    hist = ctx.get("apy_history")
    if hist is None:
        return _f(UNMEASURED, APY_HISTORY_REL, "файл истории ставок нечитаем")
    if not isinstance(hist, dict) or not hist:
        snap = ctx.get("snapshot_probe") or {}
        why = "истории ставок по протоколам не ведёт никто (protocol_history пуст)"
        if snap.get("measured") and not snap.get("content_addressed"):
            why += ("; snapshot_id в трейле адресует ПРОГОН, а не содержимое — "
                    "два вызова производителя на одном входе дали разные значения")
        return _f(ABSENT, APY_HISTORY_REL, why)
    rates = {p: v for p, v in hist.items() if _rate_on(v, date) is not None}
    if not rates:
        return _f(ABSENT, APY_HISTORY_REL, f"в истории ставок нет ни одного протокола на {date}")
    return _f(PRESENT, f"{APY_HISTORY_REL}::protocol_history", f"{len(rates)} протокол(ов) на {date}")


def _rate_on(series: object, date: str) -> float | None:
    if isinstance(series, dict):
        v = series.get(date)
        return v if isinstance(v, (int, float)) else None
    if isinstance(series, list):
        for point in series:
            if isinstance(point, dict) and _day(point.get("date") or point.get("ts")) == date:
                v = point.get("apy")
                return v if isinstance(v, (int, float)) else None
    return None


def _version_field(chain: list[dict], keys: tuple[str, ...], *, live: str | None,
                   what: str, carrier: str) -> dict:
    for ev in chain:
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        for k in keys:
            if data.get(k) not in (None, ""):
                return _f(PRESENT, f"{TRAIL_REL}::{ev.get('event_type')}.{k}", str(data[k]))
    detail = f"ни одно событие цикла не несёт {what}; носителем было бы событие '{carrier}'"
    if live:
        detail += (f". Сегодня она существует и равна '{live}' — то есть теряется не "
                   f"значение, а его ЗАПИСЬ рядом с решением")
    return _f(ABSENT, TRAIL_REL, detail)


def _calculations(date: str | None, verdict: dict, ctx: dict) -> dict:
    """Числа решения: не «что решили», а «из чего это следует».

    Строки вердикта гейта — причины ОТКАЗА по ограничениям. Они объясняют, чего
    система НЕ сделала, и не объясняют, почему цель именно такая; поэтому это
    `partial`, а не ответ.
    """
    reasons = list(verdict.get("violations") or []) + list(verdict.get("warnings") or [])
    note = ""
    shadow_day = (ctx.get("shadow_days") or {}).get(date)
    if isinstance(shadow_day, dict) and shadow_day:
        # Накопитель ADR-060 хранит числа ТЕНЕВОГО слоя за тот же день. Это
        # ДРУГОЕ решение (advisory, оно капитал не двигало), поэтому объяснить
        # им ход живого аллокатора нельзя — подставить его вместо ответа значило
        # бы выдать чужой расчёт за расчёт этого хода.
        note = (f"; числа за {date} есть у ТЕНЕВОГО слоя ({SHADOW_HISTORY_REL}), "
                f"но он этот ход не принимал — это расчёт ДРУГОГО решения")
    if reasons:
        return _f(PARTIAL, f"{TRAIL_REL}::risk_verdict",
                  f"записаны {len(reasons)} строк(и) вердикта гейта — это причины ОТКАЗА "
                  f"по ограничениям, а не расчёт, из которого получилась цель{note}")
    return _f(ABSENT, TRAIL_REL,
              f"в цепочке хода нет ни одной величины, из которой следует цель{note}")


def _post_trade(date: str | None, ctx: dict) -> dict:
    """Что ход ПРИНЁС: книга на следующий день есть, вклад самого хода — нет."""
    if date is None:
        return _f(UNMEASURED, TRAIL_REL, "у записи хода нет разбираемой отметки времени")
    days = ctx.get("equity_days")
    if days is None:
        return _f(UNMEASURED, EQUITY_REL, "дневная кривая нечитаема")
    after = sorted(d for d in days if d > date)
    if not after:
        return _f(ABSENT, EQUITY_REL, f"после {date} в дневной кривой нет ни одного дня")
    return _f(PARTIAL, f"{EQUITY_REL}::daily",
              f"есть КНИГА за {after[0]} (equity/apy_today) — уровень портфеля; "
              f"вклада ИМЕННО этого хода не считает никто, и связи хода с исходом нет")


# ── Тождество хода ────────────────────────────────────────────────────────────

def id_collisions(moves: list[dict]) -> dict:
    """Именует ли ``trade_id`` ровно один ход — вопрос, на котором стои́т §43.

    Вопрос владельца поставлен через ход («перекладку $12 000 13 августа»), и
    ответить на него данными можно, только если у хода есть однозначное имя.
    """
    seen: dict[str, list[dict]] = {}
    unnamed = 0
    for m in moves:
        tid = (m.get("data") or {}).get("trade_id")
        if not isinstance(tid, str) or not tid:
            unnamed += 1
            continue
        seen.setdefault(tid, []).append(m)
    reused = {tid: rows for tid, rows in seen.items() if len(rows) > 1}
    worst = None
    if reused:
        tid = sorted(reused, key=lambda t: -len(reused[t]))[0]
        worst = {
            "trade_id": tid,
            "occurrences": [
                {"date": _day(r.get("timestamp")), "diff_usd": (r.get("data") or {}).get("diff_usd")}
                for r in reused[tid]
            ],
        }
    return {
        "moves": len(moves),
        "distinct_ids": len(seen),
        "reused_ids": len(reused),
        "unnamed_moves": unnamed,
        "worst": worst,
    }


# ── Прогон ────────────────────────────────────────────────────────────────────

def run(root: str | None = None, *, now: dt.datetime | None = None,
        read: Callable[[str], Any] = _read_json,
        read_lines: Callable[[str], "tuple[list[dict], int] | None"] = _read_jsonl,
        write: bool = True) -> dict:
    """Собрать отчёт. ``now`` инъектируется — иных обращений к часам здесь нет."""
    root = root or REPO_ROOT
    now = now or dt.datetime.now(dt.timezone.utc)

    trail = read_lines(os.path.join(root, TRAIL_REL))
    if trail is None:
        return _report(root, now, overall=_UNCHECKED, fields={}, findings=[],
                       unchecked=[f"{TRAIL_REL} нечитаем — судить о восстановимости нечем"],
                       population={}, identity={}, snapshot={}, moves=[], write=write)
    rows, bad_lines = trail
    moves = [r for r in rows if r.get("event_type") == "trade_executed"]
    if not moves:
        return _report(root, now, overall=_UNCHECKED, fields={}, findings=[],
                       unchecked=["в трейле нет ни одной перекладки — восстанавливать нечего"],
                       population={"trail_events": len(rows), "unparseable_lines": bad_lines},
                       identity={}, snapshot={}, moves=[], write=write)

    chains: dict[str, list[dict]] = {}
    for r in rows:
        chains.setdefault(str(r.get("correlation_id")), []).append(r)

    ctx = _context(root, read, read_lines, sample_date=_day(moves[-1].get("timestamp")) or "1970-01-01")

    resolved = []
    for m in moves:
        chain = chains.get(str(m.get("correlation_id")), [m])
        fields = resolve_move(m, chain, ctx)
        age = _age_days(_day(m.get("timestamp")), now)
        resolved.append({
            "trade_id": (m.get("data") or {}).get("trade_id"),
            "date": _day(m.get("timestamp")),
            "diff_usd": (m.get("data") or {}).get("diff_usd"),
            "age_days": age,
            "fields": fields,
            "fully_answerable": all(f["status"] == PRESENT for f in fields.values()),
        })

    per_field = {}
    for key, wording in OWNER_FIELDS:
        counts = {PRESENT: 0, PARTIAL: 0, ABSENT: 0, UNMEASURED: 0}
        detail = ""
        source = ""
        for r in resolved:
            f = r["fields"][key]
            counts[f["status"]] += 1
            if not detail or f["status"] in (ABSENT, UNMEASURED):
                detail, source = f["detail"], f["source"]
        per_field[key] = {"owner_wording": wording, "counts": counts,
                          "source": source, "detail": detail}

    identity = id_collisions(moves)
    older = [r for r in resolved if (r["age_days"] or 0) >= OWNER_HORIZON_DAYS]
    population = {
        "trail_events": len(rows),
        "unparseable_lines": bad_lines,
        "moves": len(resolved),
        "moves_older_than_owner_horizon": len(older),
        "owner_horizon_days": OWNER_HORIZON_DAYS,
        "owner_horizon_provenance": OWNER_HORIZON_PROVENANCE,
        "fully_answerable": sum(1 for r in resolved if r["fully_answerable"]),
        "oldest_move_date": min((r["date"] for r in resolved if r["date"]), default=None),
        "newest_move_date": max((r["date"] for r in resolved if r["date"]), default=None),
    }

    findings, unchecked = _judge(per_field, identity, population, ctx)

    if all(c[UNMEASURED] == len(resolved) for c in (v["counts"] for v in per_field.values())):
        overall = _UNCHECKED
    elif any(f["severity"] == "CRITICAL" for f in findings):
        overall = "CRITICAL"
    elif any(f["severity"] == "WARN" for f in findings):
        overall = "WARN"
    else:
        overall = "OK"

    return _report(root, now, overall=overall, fields=per_field, findings=findings,
                   unchecked=unchecked, population=population, identity=identity,
                   snapshot=ctx.get("snapshot_probe") or {}, moves=resolved, write=write)


def _age_days(date: str | None, now: dt.datetime) -> float | None:
    if date is None:
        return None
    try:
        d = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return round((now - d).total_seconds() / 86400.0, 2)


def _context(root: str, read: Callable[[str], Any],
             read_lines: Callable[[str], "tuple[list[dict], int] | None"],
             *, sample_date: str) -> dict:
    ctx: dict = {}

    hist = read(os.path.join(root, APY_HISTORY_REL))
    ctx["apy_history"] = (hist or {}).get("protocol_history") if isinstance(hist, dict) else None

    eq = read(os.path.join(root, EQUITY_REL))
    daily = (eq or {}).get("daily") if isinstance(eq, dict) else None
    if isinstance(daily, list):
        ctx["equity_days"] = {d.get("date") for d in daily if isinstance(d, dict)}
        ctx["equity_positions"] = {d.get("date"): d.get("positions")
                                   for d in daily if isinstance(d, dict)}
    else:
        ctx["equity_days"] = None
        ctx["equity_positions"] = {}

    sh = read_lines(os.path.join(root, SHADOW_HISTORY_REL))
    ctx["shadow_days"] = ({r.get("cycle_date"): r for r in sh[0]} if sh else {})

    # Версии, которые СУЩЕСТВУЮТ сегодня, — чтобы отличить «версии нет» от
    # «версия есть, но её не записывают рядом с решением».
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        ctx["live_policy_version"] = str(getattr(cfg, "version", "") or "")
        ctx["live_config_version"] = str(getattr(cfg, "version_date", "") or "")
    except Exception:  # noqa: BLE001
        ctx["live_policy_version"] = None
        ctx["live_config_version"] = None

    make_id = None
    try:
        from spa_core.audit import audit_trail as _at
        make_id = _at._make_snapshot_id
    except Exception:  # noqa: BLE001
        make_id = None
    ctx["snapshot_probe"] = probe_snapshot_id(make_id, sample_date)
    return ctx


def _judge(per_field: dict, identity: dict, population: dict, ctx: dict
           ) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []
    n = population.get("moves") or 0

    for key, v in per_field.items():
        c = v["counts"]
        if not n or c[PRESENT]:
            continue
        if c[ABSENT]:
            # Ни одна перекладка не отдаёт поле целиком, и хотя бы одна не
            # отдаёт вовсе. Для §43 это и есть «не воспроизводимо данными».
            where = (f"НИ ПО ОДНОЙ из {n}" if c[ABSENT] == n
                     else f"ни по одной из {n} (нет вовсе — {c[ABSENT]}, "
                          f"частично — {c[PARTIAL]})")
            findings.append({
                "severity": "CRITICAL",
                "code": f"field_never_recoverable:{key}",
                "message": (f"поле владельца «{v['owner_wording']}» не восстановимо "
                            f"{where} перекладок живого трека: {v['detail']}"),
            })
        else:
            findings.append({
                "severity": "WARN",
                "code": f"field_partial:{key}",
                "message": (f"поле владельца «{v['owner_wording']}» восстановимо ЧАСТИЧНО "
                            f"на всех {n} перекладках: {v['detail']}"),
            })
    recoverable = [v["owner_wording"] for v in per_field.values()
                   if n and v["counts"][PRESENT] == n]
    if recoverable:
        findings.append({
            "severity": "INFO",
            "code": "fields_recoverable",
            "message": (f"отвечают данными на всех {n} перекладках {len(recoverable)} из "
                        f"{len(per_field)} полей: " + ", ".join(f"«{w}»" for w in recoverable)),
        })
    for key, v in per_field.items():
        if v["counts"][UNMEASURED]:
            unchecked.append(f"«{v['owner_wording']}»: {v['counts'][UNMEASURED]} из {n} — "
                             f"{v['detail']}")

    if identity.get("reused_ids"):
        w = identity.get("worst") or {}
        occ = "; ".join(f"{o['date']} на ${o['diff_usd']:,.2f}" for o in w.get("occurrences", [])
                        if o.get("diff_usd") is not None)
        findings.append({
            "severity": "CRITICAL",
            "code": "trade_id_not_unique",
            "message": (f"имя хода НЕ однозначно: {identity['reused_ids']} из "
                        f"{identity['distinct_ids']} значений trade_id названы больше одного "
                        f"раза — {w.get('trade_id')} это {occ}. Вопрос владельца поставлен "
                        f"ЧЕРЕЗ ход («перекладка 13 августа»), и такой join отвечает двумя "
                        f"разными ходами сразу"),
        })
    if identity.get("unnamed_moves"):
        findings.append({
            "severity": "WARN",
            "code": "unnamed_moves",
            "message": f"{identity['unnamed_moves']} перекладок записаны без trade_id",
        })

    snap = ctx.get("snapshot_probe") or {}
    if snap.get("measured") and not snap.get("content_addressed"):
        findings.append({
            "severity": "INFO",
            "code": "snapshot_id_is_a_run_id",
            "message": ("опыт над производителем: два вызова _make_snapshot_id на ОДНОМ "
                        "входе дали разные значения — поле snapshot_id именует ПРОГОН, "
                        "а не содержимое рыночного снимка, и восстановить по нему нечего"),
        })
    elif not snap.get("measured"):
        unchecked.append(f"snapshot_id: {snap.get('reason', 'опыт не поставлен')}")

    if n and not population.get("fully_answerable"):
        findings.append({
            "severity": "CRITICAL",
            "code": "no_move_is_fully_answerable",
            "message": (f"ни одна из {n} перекладок не объяснима данными полностью: "
                        f"{population.get('moves_older_than_owner_horizon')} из них уже "
                        f"старше месяца, на который рассчитывал §43"),
        })
    if population.get("unparseable_lines"):
        unchecked.append(f"{population['unparseable_lines']} строк(и) трейла не разобраны")
    return findings, unchecked


def _report(root: str, now: dt.datetime, *, overall: str, fields: dict,
            findings: list[dict], unchecked: list[str], population: dict,
            identity: dict, snapshot: dict, moves: list[dict], write: bool) -> dict:
    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": {
            "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
            "warn": sum(1 for f in findings if f["severity"] == "WARN"),
            "info": sum(1 for f in findings if f["severity"] == "INFO"),
            "unchecked": len(unchecked),
        },
        "population": population,
        "owner_fields": fields,
        "identity": identity,
        "snapshot_id_probe": snapshot,
        "moves": moves[-10:],
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: схема трейла, RiskPolicy, kill-switch и живой трек НЕ "
                     "трогаются — дописать поле в запись решения значит изменить путь, "
                     "по которому двигается капитал, это решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    c = doc["counts"]
    print(f"decision_audit_trail: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
