"""emergency_mode_census.py — §29 ТЗ «Portfolio CIO»: Emergency mode.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §29 «Emergency mode»::

    Обычная yield optimization и emergency risk management — разные процессы.
    При:
    exploit · depeg · oracle failure · withdrawal issue · protocol suspension ·
    critical security alert
    сохранность капитала имеет приоритет над:
    gas · APY · break-even · cooldown · turnover
    Использовать существующую emergency policy либо спроектировать extension отдельно.

Требований здесь ЧЕТЫРЕ, и слить их в одно — ответить не на то:

* **(A) шесть триггеров** — у каждого есть ДАТЧИК, и его вердикт ДОХОДИТ до книги
  (сохранность капитала = капитал выведен из-под угрозы, а не «цикл остановлен»);
* **(B) пять приоритетов** — ни одна из пяти экономических дверей не задерживает
  аварийный выход. Мерится ДИФФЕРЕНЦИАЛЬНО: той же двери подаются ВЫХОД (книга → кэш)
  и ПЕРЕТАСОВКА (A → B) при одинаковых издержках; дверь, кусающая перетасовку и
  пропускающая выход, уступает; дверь, останавливающая оба, — вето;
* **(C) разные процессы** — аварийный путь и путь доходности живут в РАЗНЫХ процессах;
* **(D) существующая emergency policy** — что она умеет: есть ли в её словаре ВЫХОД.

🪤 ЛОВУШКА, ради которой прибор мерит ПОРЯДОК шагов, а не только двери
========================================================================
Каждая дверь аварийного пути по отдельности отвечает верно: стоп-кран выдаёт книгу
«весь кэш», демпфер де-риск не задерживает никогда (``REASON_DERISK``), урезание хода
де-риск не трогает, RTMR-поза обнуляет цель. Но в ``run_cycle`` **Step 2b
(EmergencyBreakers) возвращается из цикла ДО Step 2c (all-cash стоп-крана) и ДО
Step 3 (сделка)**: при ``HALT``/``PAUSE`` цикл выходит с ``traded=False`` и
``positions=current_positions``. То есть ровно в тот момент, когда датчик эксплойта
(EB-01, APY > 100 %) или каскада оракула (EB-02) сработал, книга ДЕРЖИТСЯ в
поражённом протоколе, а стоп-кран, взведённый реактором угроз по тому же событию,
вывести капитал НЕ МОЖЕТ, пока датчик горит. Замер по дверям сказал бы «всё
исполнено»; замер по ПОРЯДКУ говорит обратное. Порядок читается из исходника
``cycle_runner.py`` по трём маркерам, каждый обязан встретиться РОВНО один раз.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): стоп-кран, EmergencyBreakers, RiskPolicy, демпфер,
RTMR и живой трек не правит ни байтом. Карточку владельцу не заводит. Сцены идут на
НАСТОЯЩИХ дверях (ввоз сцен §22, книг и капитала — своих копий нет), реактор угроз
читает одноразовый каталог, который прибор создаёт и удаляет сам.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import inspect
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/emergency_mode_census.json"

# ── владелец: §29 дословно ───────────────────────────────────────────────────
SECTION_HEAD = "29. Emergency mode"
NEXT_SECTION_HEAD = "30. Shadow Mode — обязательный этап"
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

OWNER_SEPARATION_LINE = ("Обычная yield optimization и emergency risk management — "
                         "разные процессы.")
OWNER_TRIGGER_LEAD = "При:"
OWNER_PRIORITY_LEAD = "сохранность капитала имеет приоритет над:"
OWNER_DIRECTIVE_LINE = ("Использовать существующую emergency policy либо спроектировать "
                        "extension отдельно.")

OWNER_TRIGGERS: Tuple[str, ...] = (
    "exploit", "depeg", "oracle failure", "withdrawal issue",
    "protocol suspension", "critical security alert",
)
OWNER_PRIORITIES: Tuple[str, ...] = ("gas", "APY", "break-even", "cooldown", "turnover")
OWNER_TRIGGERS_DECLARED = 6
OWNER_PRIORITIES_DECLARED = 5
#: Что назвал заказ G961 п. 1 «по первым строкам»: шесть триггеров; хвост (приоритеты)
#: заказ честно объявил не читанным — ``None`` = не считал, а не ноль.
ORDER_G961_NAMED: Dict[str, Optional[int]] = {"triggers": 6, "priorities": None}

# ── шкалы ────────────────────────────────────────────────────────────────────
#: Ось A — куда доходит вердикт датчика.
REACH_KINDS: Tuple[str, ...] = (
    "exits_the_book",          # вердикт обнуляет позицию/книгу и сделка проходит двери
    "holds_the_book",          # вердикт останавливает ЦИКЛ — позиции держатся как есть
    "declared_by_registry",    # датчик заявлен именем модуля Tier-A, сценой не мерен
    "undetected",              # ни одна дверь быстрого пути триггер не называет
    UNMEASURED,
)
#: Ось B — что делает экономическая дверь с аварийным выходом.
PRIORITY_KINDS: Tuple[str, ...] = (
    "yields_to_exit",   # перетасовку кусает, выход пропускает
    "vetoes_exit",      # останавливает цикл целиком — выход в том числе
    UNMEASURED,
)
#: Ось C — в каком процессе живёт звено.
PROCESS_KINDS: Tuple[str, ...] = ("separate_agent", "inside_yield_cycle", UNMEASURED)
#: Порядок шагов цикла.
ORDER_KINDS: Tuple[str, ...] = ("halt_precedes_exit", "exit_precedes_halt", UNMEASURED)

# ── маркеры порядка в cycle_runner.py (каждый — РОВНО один раз) ──────────────
CYCLE_RUNNER_REL = "spa_core/paper_trading/cycle_runner.py"
ORDER_MARKERS: Dict[str, str] = {
    "breaker_return": "return _eb_cycle_result",          # ранний выход Step 2b
    "kill_switch_override": "apply_kill_switch_override(",  # Step 2c — all-cash
    "trade_damper": "_churn_decide(",                     # Step 3 — сделка
}
BREAKER_STATUS_MARKER = "blocked_by_emergency_"

# ── датчики по триггерам ─────────────────────────────────────────────────────
#: Триггер → двери быстрого пути, которые прибор спрашивает СЦЕНОЙ.
TRIGGER_DOORS: Dict[str, Tuple[str, ...]] = {
    "exploit": ("eb01",),
    "depeg": ("peg_reactor", "rtmr_peg"),
    "oracle failure": ("eb02", "rtmr_oracle"),
    "withdrawal issue": ("rtmr_liquidity",),
    "protocol suspension": ("governance_red_flag",),
    "critical security alert": (),
}
#: Триггер → подстроки имён модулей Tier-A (`_module_registry`, тир A): заявленное
#: обнаружение, которое сценой здесь НЕ меряется — поэтому отдельный род.
TIER_A_NAME_HINTS: Dict[str, Tuple[str, ...]] = {
    "exploit": ("exploit",),
    "depeg": ("depeg",),
    "oracle failure": ("oracle",),
    "withdrawal issue": ("withdrawal", "exit_liquidity", "liquidity_crisis"),
    "protocol suspension": ("sequencer_downtime", "suspen", "pause"),
    "critical security alert": ("security", "admin_key"),
}
#: Приоритет → дверь живого пути, которую спрашивает ось B (с контролем).
PRIORITY_DOORS: Dict[str, str] = {
    "gas": "eb03",
    "APY": "economics",
    "break-even": "economics",
    "cooldown": "damper_min_hold",
    "turnover": "admissible_trim",
}
#: Какие причины теневой двери цены отвечают за какой приоритет владельца.
ECONOMICS_REASON_PREFIX: Dict[str, str] = {
    "APY": "gain_below_band",
    "break-even": "payback_too_long",
}
#: Звенья аварийного пути → ожидаемый хозяин-процесс (launchd-метка или «цикл»).
PROCESS_LINKS: Dict[str, Dict[str, str]] = {
    "emergency_breakers": {"host": "cycle", "evidence": "from spa_core.risk.emergency_breakers import"},
    "kill_switch_override": {"host": "cycle", "evidence": "apply_kill_switch_override("},
    "trade_step_3": {"host": "cycle", "evidence": "_churn_decide("},
    "threat_reactor": {"host": "com.spa.threat_reactor", "evidence": ""},
    "peg_monitor": {"host": "com.spa.peg_monitor", "evidence": ""},
    "red_flag_monitor": {"host": "com.spa.red_flag_monitor", "evidence": ""},
    "rtmr_sense": {"host": "com.spa.rtmr_sense", "evidence": ""},
}
EXIT_WORDS: Tuple[str, ...] = ("EXIT", "CASH")
EMERGENCY_WORDS: Tuple[str, ...] = ("emergency", "exploit", "depeg", "oracle",
                                     "withdraw", "suspen", "security", "threat")
SCENE_PROTOCOL = "aave_v3"
SCENE_GAS_CRISIS_GWEI = 80.0
SCENE_GAS_CALM_GWEI = 10.0
SCENE_EXPLOIT_APY_PCT = 150.0


# ───────────────────────────── общие помощники ───────────────────────────────

@contextlib.contextmanager
def _quiet():
    """Глушит журналирование дверей на время сцены (урок ADR-967: stdout не поток лога)."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _read_text(path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read(), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _scene_books() -> Tuple[float, Dict[str, float], Dict[str, float], Dict[str, float], Any]:
    """Капитал, книга A, перетасовка B и выход (все позиции → 0); момент сцены — у §22."""
    from spa_core.analytics import anti_churn_census as s22
    capital = float(s22._scene_capital())
    books = s22._books(capital)
    current = dict(books["A"])
    reshuffle = dict(books["B"])
    exit_book = {k: 0.0 for k in current}
    return capital, current, reshuffle, exit_book, s22.SCENE_NOW


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                      f"{NEXT_SECTION_HEAD!r} — перечень не ограничен, и счёт по нему "
                      f"был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _items_between(body: List[str], lead: str, stops: Tuple[str, ...]) -> Optional[List[str]]:
    start = next((i for i, ln in enumerate(body) if ln.strip() == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if not s or s == "⸻":
            if out:
                break
            continue
        if s in stops:
            break
        out.append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    """Разобрать §29 из карточки: триггеры, приоритеты, строка-разделение, директива."""
    text, why = _read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    triggers = _items_between(body, OWNER_TRIGGER_LEAD, (OWNER_PRIORITY_LEAD,))
    priorities = _items_between(body, OWNER_PRIORITY_LEAD, (OWNER_DIRECTIVE_LINE,))
    return {
        "measured": True,
        "triggers": triggers,
        "priorities": priorities,
        "separation_line_present": OWNER_SEPARATION_LINE in stripped,
        "directive_present": OWNER_DIRECTIVE_LINE in stripped,
    }


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    if parsed["triggers"] is None:
        mism.append(f"в разделе нет строки {OWNER_TRIGGER_LEAD!r}")
    elif list(parsed["triggers"]) != list(OWNER_TRIGGERS):
        mism.append(f"триггеры карточки {parsed['triggers']} ≠ константам {list(OWNER_TRIGGERS)}")
    if parsed["priorities"] is None:
        mism.append(f"в разделе нет строки {OWNER_PRIORITY_LEAD!r}")
    elif list(parsed["priorities"]) != list(OWNER_PRIORITIES):
        mism.append(f"приоритеты карточки {parsed['priorities']} ≠ константам "
                    f"{list(OWNER_PRIORITIES)}")
    if not parsed["separation_line_present"]:
        mism.append("строка «разные процессы» не найдена")
    if not parsed["directive_present"]:
        mism.append("директива «существующая emergency policy / extension» не найдена")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if parsed["triggers"] is not None:
        out["order_undercount"] = len(parsed["triggers"]) - int(ORDER_G961_NAMED["triggers"] or 0)
    out["order_priorities_counted"] = ORDER_G961_NAMED["priorities"] is not None
    return out


# ───────────────────────────── порядок шагов цикла ───────────────────────────

def measure_cycle_order(root: str = REPO_ROOT, text: Optional[str] = None) -> Dict[str, Any]:
    """Порядок трёх маркеров в ``cycle_runner.py``: ранний выход EB · all-cash · сделка.

    Каждый маркер обязан встретиться РОВНО один раз: ноль — порядок не измерен, два и
    больше — тоже (неизвестно, о каком из двух говорить).
    """
    if text is None:
        text, why = _read_text(os.path.join(root, CYCLE_RUNNER_REL))
        if text is None:
            return {"kind": UNMEASURED, "reason": f"{CYCLE_RUNNER_REL} не прочитан: {why}"}
    lines = text.splitlines()
    pos: Dict[str, Optional[int]] = {}
    problems: List[str] = []
    for name, marker in ORDER_MARKERS.items():
        hits = [i + 1 for i, ln in enumerate(lines) if marker in ln]
        if len(hits) != 1:
            problems.append(f"маркер {name} ({marker!r}) встречается {len(hits)} раз, ожидался 1")
            pos[name] = None
        else:
            pos[name] = hits[0]
    status_hits = sum(1 for ln in lines if BREAKER_STATUS_MARKER in ln)
    out: Dict[str, Any] = {"lines": pos, "breaker_status_marker_hits": status_hits}
    if problems:
        out.update(kind=UNMEASURED, reason="; ".join(problems))
        return out
    br, ks, tr = pos["breaker_return"], pos["kill_switch_override"], pos["trade_damper"]
    if br < ks and br < tr:  # type: ignore[operator]
        out["kind"] = "halt_precedes_exit"
        out["reason"] = (f"ранний выход EmergencyBreakers (строка {br}) стои́т ДО all-cash "
                         f"стоп-крана (строка {ks}) и ДО сделки (строка {tr}): при HALT/PAUSE "
                         f"цикл возвращается с позициями как есть")
    else:
        out["kind"] = "exit_precedes_halt"
        out["reason"] = (f"all-cash (строка {ks}) и/или сделка (строка {tr}) стоя́т ДО раннего "
                         f"выхода EB (строка {br})")
    return out


# ───────────────────────────── двери сцен ────────────────────────────────────

def _door_eb(check: str, **scene: Any) -> Dict[str, Any]:
    """Вердикт одного датчика EmergencyBreakers на сцене (настоящий класс, свои пороги)."""
    try:
        from spa_core.risk.emergency_breakers import EmergencyBreakers
        eb = EmergencyBreakers()
        with _quiet():
            res = getattr(eb, check)(**scene)
        return {"measured": True, "verdict": res.get("verdict"), "id": res.get("id"),
                "message": res.get("message")}
    except Exception as exc:  # noqa: BLE001 — нечем измерить ≠ «чисто»
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_kill_switch_override(current: Dict[str, float], capital: float) -> Dict[str, Any]:
    """Книга стоп-крана через настоящую дверь Step 2c: все позиции → 0?"""
    try:
        from spa_core.paper_trading.cycle_gates import apply_kill_switch_override
        alloc = {"cash": 1.0, **{k: 0.0 for k in current}}
        notes: List[str] = []
        out = apply_kill_switch_override(dict(current), ks_triggered=True, ks_allocation=alloc,
                                         capital_usd=capital, notes=notes)
        zeroed = all(float(v) == 0.0 for v in out.values()) and set(out) == set(current)
        return {"measured": True, "all_zero": zeroed, "target": out, "notes": notes}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_damper(current: Dict[str, float], target: Dict[str, float], trades: List[dict],
                 capital: float, now: Any) -> Dict[str, Any]:
    try:
        from spa_core.governance import churn_damper as damper
        with _quiet():
            v = damper.decide(dict(current), dict(target), list(trades), capital, now=now)
        return {"measured": True, "decision": str(v.decision), "reason": str(v.reason),
                "is_pure_reduction": bool(v.is_pure_reduction)}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_trim(current: Dict[str, float], target: Dict[str, float], capital: float,
               now: Any) -> Dict[str, Any]:
    try:
        from spa_core.paper_trading.admissible_trim import apply_admissible_trim
        notes: List[str] = []
        with _quiet():
            out, rec = apply_admissible_trim(dict(target), current_positions=dict(current),
                                             capital_usd=capital, notes=notes, trades=[],
                                             now=now)
        return {"measured": True, "verdict": rec.get("verdict"), "target_unchanged": out == target,
                "why": rec.get("why")}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_economics(current: Dict[str, float], target: Dict[str, float]) -> Dict[str, Any]:
    """Теневая дверь цены (§22 `_econ_move`): что она говорит про ВЫХОД в кэш."""
    try:
        from spa_core.analytics import anti_churn_census as s22
        with _quiet():
            d = s22._econ_move(dict(current), dict(target), SCENE_PROTOCOL)
        return {"measured": True, "decision": str(d.decision), "reasons": list(d.reasons)[:6],
                "gain_pp": d.gain_pp, "payback_days": d.payback_days}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_cio_arming(current: Dict[str, float], target: Dict[str, float],
                     damper_reason: str) -> Dict[str, Any]:
    try:
        from spa_core.paper_trading.cio_arming import trade_allowed
        ok, dec, why = trade_allowed("conservative", None, dict(current), dict(target),
                                     damper_reason=damper_reason)
        return {"measured": True, "allowed": bool(ok), "decision": str(dec), "why": str(why)}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_rtmr(source: str, severity: str = "critical") -> Dict[str, Any]:
    """Лестница реакции RTMR на критический сигнал источника + честь позы в цикле."""
    try:
        from spa_core.monitoring import reaction as R
        from spa_core.monitoring import signal as S
        sig = S.RiskSignal(ts=0, source=source, scope=SCENE_PROTOCOL, metric="scene",
                           value=1.0, severity=severity, threshold_crossed=True,
                           staleness_ok=True)
        act = R.match_rule(sig, {})
        kind = None if act is None else str(act.kind)
        out: Dict[str, Any] = {"measured": True, "action": kind,
                               "exits": kind in (R.FULL_EXIT, R.MARKET_EXIT, R.ROTATE_TO_SAFE)}
        return out
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _door_posture_gate(capital: float) -> Dict[str, Any]:
    """Поза EXITED на протоколе сцены → цель цикла обнулена (настоящая дверь Step 2e)."""
    try:
        from spa_core.monitoring import posture as P
        from spa_core.paper_trading.cycle_gates import apply_rtmr_posture_gate
        pos = P.set_entry(dict(P._EMPTY, entries={}), scope=SCENE_PROTOCOL, state=P.EXITED,
                          now_ts=1_000)
        target = {SCENE_PROTOCOL: 0.4 * capital, "pendle": 0.1 * capital}
        notes: List[str] = []
        with _quiet():
            out = apply_rtmr_posture_gate(dict(target), capital_usd=capital, now_ts=1_001,
                                          notes=notes, posture=pos)
        return {"measured": True, "zeroed": float(out.get(SCENE_PROTOCOL, 1.0)) == 0.0,
                "other_untouched": out.get("pendle") == target["pendle"], "notes": notes,
                "docstring_claims_unwired": "does not call this yet" in
                (apply_rtmr_posture_gate.__doc__ or "")}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


@contextlib.contextmanager
def _reactor_data(path: Path):
    """Подать реактору угроз одноразовый каталог вместо прод-``data/`` и вернуть обратно."""
    from spa_core.monitoring import threat_reactor as TR
    saved = TR._DATA
    TR._DATA = Path(path)
    try:
        yield TR
    finally:
        TR._DATA = saved


def _door_threat_reactor(scene_files: Dict[str, dict], now: dt.datetime) -> Dict[str, Any]:
    """Реактор угроз на одноразовом каталоге: назвал ли он угрозу."""
    tmp = Path(tempfile.mkdtemp(prefix="spa_emc_"))
    try:
        for name, doc in scene_files.items():
            (tmp / name).write_text(json.dumps(doc), encoding="utf-8")
        with _reactor_data(tmp) as TR, _quiet():
            threats = list(TR._detect_threats())
        return {"measured": True, "threats": threats, "detected": bool(threats)}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _door_governance_classifier() -> Dict[str, Any]:
    """Классификатор красных флагов: тег приостановки протокола → CRITICAL?"""
    try:
        from spa_core.alerts import red_flag_monitor as RF
        tmp = Path(tempfile.mkdtemp(prefix="spa_emc_rf_"))
        try:
            mon = RF.RedFlagMonitor(output_file=tmp / "rf.json", risk_scores_file=tmp / "rs.json",
                                    historical_apy_file=tmp / "ha.json")
            # Классификатор судит ТОЛЬКО слаги своего белого списка — сцена берёт
            # первый из них, а не имя протокола сцены (там форма `aave-v3`, не `aave_v3`).
            slug = str(RF.SPA_WHITELIST[0])
            rec = {"protocol": slug, "tag": "pause", "title": "Pause markets (scene)",
                   "proposal_id": "scene-1"}
            flags = mon._classify_governance([rec], {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sev = [str(getattr(f, "severity", "")) for f in flags]
        return {"measured": True, "severities": sev, "slug": slug,
                "critical": any(s.upper() == "CRITICAL" for s in sev),
                "critical_tags": list(RF.GOVERNANCE_CRITICAL_TAGS)}
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}


def _tier_a_names() -> Tuple[Optional[List[str]], Optional[str]]:
    try:
        from spa_core.analytics import _module_registry as reg
        mods = reg.get_tier_modules("A")
        return [str(m.get("module") or m.get("name") or "") for m in mods], None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


# ───────────────────────────── ось A: триггеры ───────────────────────────────

def _exit_leg(current: Dict[str, float], exit_book: Dict[str, float], capital: float,
              now: Any) -> Dict[str, Any]:
    """Общее звено «книга → кэш проходит двери живого пути»: стоп-кран · демпфер · урезание."""
    ks = _door_kill_switch_override(current, capital)
    dm = _door_damper(current, exit_book, [], capital, now)
    tr = _door_trim(current, exit_book, capital, now)
    ok = (ks.get("all_zero") is True and dm.get("decision") == "ALLOW"
          and tr.get("target_unchanged") is True)
    measured = all(d.get("measured") for d in (ks, dm, tr))
    return {"measured": measured, "passes": ok if measured else None,
            "kill_switch_override": ks, "damper": dm, "trim": tr}


def measure_triggers(order: Dict[str, Any], now: dt.datetime) -> Dict[str, Any]:
    """Ось A: у каждого триггера владельца — датчики, их вердикты и ДОСЯГАЕМОСТЬ книги."""
    out: Dict[str, Any] = {"measured": True, "triggers": {}, "scene_protocol": SCENE_PROTOCOL}
    try:
        capital, current, _resh, exit_book, scene_now = _scene_books()
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"сцены §22 не ввезены: {type(exc).__name__}: {exc}"}
    exit_leg = _exit_leg(current, exit_book, capital, scene_now)
    out["exit_leg"] = exit_leg
    posture = _door_posture_gate(capital)
    out["posture_gate"] = posture
    names, names_why = _tier_a_names()
    out["tier_a"] = {"modules": names, "reason": names_why}
    halt_first = order.get("kind") == "halt_precedes_exit"

    def _reach_after_detection(exits_by_door: bool) -> str:
        if not exits_by_door:
            return UNMEASURED
        if not exit_leg.get("measured"):
            return UNMEASURED
        return "exits_the_book" if exit_leg.get("passes") else "holds_the_book"

    def _eb_reach(verdict: Optional[str]) -> str:
        if verdict not in ("HALT", "PAUSE"):
            return UNMEASURED
        if order.get("kind") == UNMEASURED:
            return UNMEASURED
        return "holds_the_book" if halt_first else "exits_the_book"

    peg_scene = {
        "peg_report.json": {"generated_at": now.isoformat(), "overall_status": "RED",
                            "critical": 1, "worst_adapter": SCENE_PROTOCOL,
                            "worst_deviation_pct": 3.0},
        "emergency_status.json": {"status": "CLEAR", "checked_at": now.isoformat()},
        "current_positions.json": {"positions": {SCENE_PROTOCOL: 0.4 * capital},
                                   "capital_usd": capital},
    }
    gov_scene = {
        "red_flags.json": {"generated_at": now.isoformat(), "sources": ["snapshot"],
                           "fallback_used": False,
                           "provenance": {"by_category": {"governance_proposal": "live"}},
                           "red_flags": [{"protocol": SCENE_PROTOCOL,
                                          "category": "governance_proposal",
                                          "severity": "CRITICAL", "source": "snapshot",
                                          "message": "Risk-sensitive proposal [pause]"}]},
        "peg_report.json": {"generated_at": now.isoformat(), "overall_status": "GREEN",
                            "critical": 0, "worst_deviation_pct": 0.01},
        "emergency_status.json": {"status": "CLEAR", "checked_at": now.isoformat()},
        "current_positions.json": {"positions": {SCENE_PROTOCOL: 0.4 * capital},
                                   "capital_usd": capital},
    }

    for trig in OWNER_TRIGGERS:
        doors: Dict[str, Dict[str, Any]] = {}
        for door in TRIGGER_DOORS.get(trig, ()):
            if door == "eb01":
                r = _door_eb("check_eb01_exploit_probe",
                             apy_map={SCENE_PROTOCOL: SCENE_EXPLOIT_APY_PCT})
                r["reach"] = _eb_reach(r.get("verdict")) if r.get("measured") else UNMEASURED
            elif door == "eb02":
                r = _door_eb("check_eb02_oracle_cascade",
                             apy_map={f"p{i}": 20.0 for i in range(4)},
                             static_apy={f"p{i}": 4.0 for i in range(4)})
                r["reach"] = _eb_reach(r.get("verdict")) if r.get("measured") else UNMEASURED
            elif door == "peg_reactor":
                r = _door_threat_reactor(peg_scene, now)
                hit = any("depeg" in t for t in r.get("threats", []))
                r["reach"] = (_reach_after_detection(hit) if r.get("measured") else UNMEASURED)
                if r.get("measured") and not hit:
                    r["reach"] = "undetected"
            elif door == "governance_red_flag":
                cls = _door_governance_classifier()
                r = _door_threat_reactor(gov_scene, now)
                r["classifier"] = cls
                hit = any("red flag CRITICAL" in t for t in r.get("threats", []))
                r["reach"] = (_reach_after_detection(hit) if r.get("measured") else UNMEASURED)
                if r.get("measured") and not hit:
                    r["reach"] = "undetected"
            elif door.startswith("rtmr_"):
                r = _door_rtmr(door[len("rtmr_"):])
                if not r.get("measured"):
                    r["reach"] = UNMEASURED
                elif r.get("exits"):
                    leg_ok = (posture.get("zeroed") is True and exit_leg.get("passes") is True)
                    r["reach"] = ("exits_the_book" if leg_ok else
                                  UNMEASURED if not posture.get("measured") else "holds_the_book")
                elif r.get("action") in ("FREEZE", "TIGHTEN", "REDUCE"):
                    r["reach"] = "holds_the_book"
                else:
                    r["reach"] = "undetected"
            else:
                r = {"measured": False, "reason": f"дверь {door!r} прибору неизвестна",
                     "reach": UNMEASURED}
            r["evidence"] = "scene"
            doors[door] = r
        hints = TIER_A_NAME_HINTS.get(trig, ())
        if names is None:
            doors["tier_a"] = {"measured": False, "reason": names_why, "reach": UNMEASURED,
                               "evidence": "registry"}
        else:
            matched = sorted(n for n in names if any(h in n for h in hints))
            doors["tier_a"] = {"measured": True, "modules": matched, "evidence": "registry",
                               "reach": "declared_by_registry" if matched else "undetected"}
        reaches = [d.get("reach") for d in doors.values()]
        scene_reaches = [d.get("reach") for d in doors.values() if d.get("evidence") == "scene"]
        if "holds_the_book" in scene_reaches and halt_first and any(
                d.get("evidence") == "scene" and str(d.get("id", "")).startswith("EB-")
                for d in doors.values()):
            # ранний выход EB стои́т до всех остальных дверей — он решает за всех
            reach = "holds_the_book"
        elif "exits_the_book" in scene_reaches:
            reach = "exits_the_book"
        elif "holds_the_book" in scene_reaches:
            reach = "holds_the_book"
        elif UNMEASURED in scene_reaches:
            reach = UNMEASURED
        elif "declared_by_registry" in reaches:
            reach = "declared_by_registry"
        elif UNMEASURED in reaches:
            # дверей-сцен нет, а реестр Tier-A не прочитан: «не обнаружено» было бы
            # ответом о реестре, которого прибор не видел (найдено собственной батареей)
            reach = UNMEASURED
        else:
            reach = "undetected"
        out["triggers"][trig] = {"reach": reach, "doors": doors}
    out["tally"] = {k: sum(1 for t in out["triggers"].values() if t["reach"] == k)
                    for k in REACH_KINDS}
    return out


# ───────────────────────────── ось B: приоритеты ─────────────────────────────

def measure_priorities(order: Dict[str, Any]) -> Dict[str, Any]:
    """Ось B: каждая из пяти дверей владельца — выход против перетасовки, дифференциально."""
    out: Dict[str, Any] = {"measured": True, "priorities": {}}
    try:
        capital, current, reshuffle, exit_book, now = _scene_books()
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "reason": f"сцены §22 не ввезены: {type(exc).__name__}: {exc}"}
    recent = [{"ts": (now - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "delta_abs": 10_000.0}]
    econ_exit = _door_economics(current, exit_book)
    cio_exit = _door_cio_arming(current, exit_book, "derisk_never_damped")
    for prio in OWNER_PRIORITIES:
        door = PRIORITY_DOORS[prio]
        rec: Dict[str, Any] = {"door": door}
        if door == "eb03":
            crisis = _door_eb("check_eb03_gas_crisis", gas_gwei=SCENE_GAS_CRISIS_GWEI)
            calm = _door_eb("check_eb03_gas_crisis", gas_gwei=SCENE_GAS_CALM_GWEI)
            rec.update(exit_scene=crisis, control=calm, order=order.get("kind"))
            if not (crisis.get("measured") and calm.get("measured")):
                rec["kind"] = UNMEASURED
                rec["why"] = "датчик газа не ответил на одной из сцен"
            elif calm.get("verdict") != "CLEAR":
                rec["kind"] = UNMEASURED
                rec["why"] = "контроль не прошёл: при спокойном газе датчик не CLEAR"
            elif crisis.get("verdict") != "PAUSE":
                rec["kind"] = UNMEASURED
                rec["why"] = f"при газе {SCENE_GAS_CRISIS_GWEI} Gwei датчик дал {crisis.get('verdict')}, не PAUSE"
            elif order.get("kind") == UNMEASURED:
                rec["kind"] = UNMEASURED
                rec["why"] = "порядок шагов цикла не измерен"
            else:
                rec["kind"] = ("vetoes_exit" if order.get("kind") == "halt_precedes_exit"
                               else "yields_to_exit")
                rec["why"] = ("PAUSE по газу возвращает цикл ДО all-cash и ДО сделки — выход "
                              "ждёт дешёвого газа" if rec["kind"] == "vetoes_exit" else
                              "PAUSE по газу стои́т после выхода")
        elif door == "economics":
            prefix = ECONOMICS_REASON_PREFIX[prio]
            named = [r for r in econ_exit.get("reasons", []) if str(r).startswith(prefix)]
            rec.update(shadow_door=econ_exit, live_door=cio_exit, shadow_reason=named)
            if not (econ_exit.get("measured") and cio_exit.get("measured")):
                rec["kind"] = UNMEASURED
                rec["why"] = "теневая или живая дверь не ответила"
            elif cio_exit.get("allowed") is True:
                rec["kind"] = "yields_to_exit"
                rec["why"] = (f"живая дверь (cio_arming) пропускает де-риск до вердикта CIO; "
                              f"теневая дверь цены при этом говорит {econ_exit.get('decision')} "
                              f"с причиной {named or 'не названа'} — логика доходности, "
                              f"применённая к аварийному вопросу")
            else:
                rec["kind"] = "vetoes_exit"
                rec["why"] = f"живая дверь отказала выходу: {cio_exit.get('why')}"
        elif door == "damper_min_hold":
            ex = _door_damper(current, exit_book, recent, capital, now)
            ctl = _door_damper(current, reshuffle, recent, capital, now)
            rec.update(exit_scene=ex, control=ctl)
            if not (ex.get("measured") and ctl.get("measured")):
                rec["kind"] = UNMEASURED
                rec["why"] = "демпфер не ответил на одной из сцен"
            elif ctl.get("decision") != "BLOCK":
                rec["kind"] = UNMEASURED
                rec["why"] = ("контроль не прошёл: перетасовку через час после хода демпфер "
                              f"не задержал ({ctl.get('reason')}) — сцена не различает")
            elif ex.get("decision") == "ALLOW":
                rec["kind"] = "yields_to_exit"
                rec["why"] = f"выход пропущен ({ex.get('reason')}), перетасовка задержана ({ctl.get('reason')})"
            else:
                rec["kind"] = "vetoes_exit"
                rec["why"] = f"выход задержан: {ex.get('reason')}"
        elif door == "admissible_trim":
            ex = _door_trim(current, exit_book, capital, now)
            ctl = _door_trim(current, reshuffle, capital, now)
            rec.update(exit_scene=ex, control=ctl)
            if not (ex.get("measured") and ctl.get("measured")):
                rec["kind"] = UNMEASURED
                rec["why"] = "урезание не ответило на одной из сцен"
            elif ctl.get("verdict") not in ("TRIMMED_TO_ADMISSIBLE", "REFUSED_BY_RISK_POLICY",
                                            "ALREADY_WITHIN_SIZE_CAPS"):
                rec["kind"] = UNMEASURED
                rec["why"] = f"контроль не прошёл: перетасовка получила {ctl.get('verdict')}"
            elif ex.get("target_unchanged") is True and ex.get("verdict") == "NOT_A_RESHUFFLE":
                rec["kind"] = "yields_to_exit"
                rec["why"] = f"выход не урезан ({ex.get('verdict')}), перетасовка судится ({ctl.get('verdict')})"
            else:
                rec["kind"] = "vetoes_exit"
                rec["why"] = f"выход урезан: {ex.get('verdict')}"
        else:
            rec["kind"] = UNMEASURED
            rec["why"] = f"дверь {door!r} прибору неизвестна"
        out["priorities"][prio] = rec
    out["tally"] = {k: sum(1 for p in out["priorities"].values() if p["kind"] == k)
                    for k in PRIORITY_KINDS}
    return out


# ───────────────────────────── ось C: процессы ───────────────────────────────

def measure_processes(root: str, data_dir: str) -> Dict[str, Any]:
    """Ось C: где живёт каждое звено — в отдельном агенте или внутри цикла доходности."""
    out: Dict[str, Any] = {"measured": True, "links": {}}
    text, why = _read_text(os.path.join(root, CYCLE_RUNNER_REL))
    health_path = os.path.join(data_dir, "agent_health.json")
    agents: Optional[Dict[str, Any]] = None
    health_why: Optional[str] = None
    try:
        with open(health_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        ag = doc.get("agents") if isinstance(doc, dict) else None
        if isinstance(ag, list):
            ag = {str(a.get("name") or a.get("label")): a for a in ag if isinstance(a, dict)}
        if isinstance(ag, dict):
            agents = ag
        else:
            health_why = "agent_health.json без словаря agents"
    except (OSError, ValueError) as exc:
        health_why = f"agent_health.json не прочитан: {type(exc).__name__}: {exc}"
    for link, spec in PROCESS_LINKS.items():
        rec: Dict[str, Any] = {"host": spec["host"]}
        if spec["host"] == "cycle":
            if text is None:
                rec.update(kind=UNMEASURED, why=f"{CYCLE_RUNNER_REL} не прочитан: {why}")
            else:
                hits = text.count(spec["evidence"])
                rec.update(kind="inside_yield_cycle" if hits else UNMEASURED,
                           evidence_hits=hits,
                           why=(f"{spec['evidence']!r} в run_cycle: {hits}" if hits else
                                f"маркер {spec['evidence']!r} в {CYCLE_RUNNER_REL} не найден"))
        else:
            if agents is None:
                rec.update(kind=UNMEASURED, why=health_why)
            elif spec["host"] in agents:
                a = agents[spec["host"]]
                rec.update(kind="separate_agent", status=a.get("status"),
                           last_exit=a.get("last_exit"))
            else:
                rec.update(kind=UNMEASURED, why=f"метка {spec['host']} не в agent_health.json")
        out["links"][link] = rec
    # реактор только взводит флаг и пинает цикл доходности: исполняет выход ЦИКЛ
    rtext, rwhy = _read_text(os.path.join(root, "spa_core/monitoring/threat_reactor.py"))
    if rtext is None:
        out["reactor_kickstarts_cycle"] = {"kind": UNMEASURED, "why": rwhy}
    else:
        out["reactor_kickstarts_cycle"] = {
            "kind": "measured", "kickstart": "com.spa.daily_cycle" in rtext,
            "writes_kill_switch": "kill_switch_active.json" in rtext,
            "trades_itself": any(m in rtext for m in ("_churn_decide(", "apply_kill_switch_override(")),
        }
    out["tally"] = {k: sum(1 for l in out["links"].values() if l.get("kind") == k)
                    for k in PROCESS_KINDS}
    return out


# ───────────────────────────── ось D: существующая policy ─────────────────────

def measure_policy_inventory() -> Dict[str, Any]:
    """Ось D: словари существующей emergency policy — есть ли в них ВЫХОД; вход CIO."""
    out: Dict[str, Any] = {"measured": True}
    try:
        from spa_core.risk import emergency_breakers as EB
        vocab = [EB.STATUS_CLEAR, EB.STATUS_PAUSE, EB.STATUS_HALT]
        out["breakers"] = {"vocabulary": vocab,
                           "has_exit": any(w in v.upper() for v in vocab for w in EXIT_WORDS),
                           "adr": "ADR-030"}
    except Exception as exc:  # noqa: BLE001
        out["breakers"] = {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
    try:
        from spa_core.monitoring import reaction as R
        vocab = sorted(R._DE_RISK_ONLY)
        out["rtmr_reaction"] = {"vocabulary": vocab,
                                "has_exit": any(w in v.upper() for v in vocab for w in EXIT_WORDS),
                                "adr": "ADR-053"}
    except Exception as exc:  # noqa: BLE001
        out["rtmr_reaction"] = {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
    try:
        from spa_core.allocator import rebalance_economics as E
        params = sorted(inspect.signature(E.evaluate).parameters)
        fields = sorted(getattr(E.Decision, "__dataclass_fields__", {}))
        emergency_params = [p for p in params if any(w in p.lower() for w in EMERGENCY_WORDS)]
        emergency_fields = [f for f in fields if any(w in f.lower() for w in EMERGENCY_WORDS)]
        out["cio_door"] = {"module": "spa_core.allocator.rebalance_economics.evaluate",
                           "params": params, "decision_fields": fields,
                           "emergency_params": emergency_params,
                           "emergency_fields": emergency_fields,
                           "has_emergency_input": bool(emergency_params or emergency_fields)}
    except Exception as exc:  # noqa: BLE001
        out["cio_door"] = {"measured": False, "reason": f"{type(exc).__name__}: {exc}"}
    return out


# ───────────────────────────── живое состояние ───────────────────────────────

def measure_live_state(data_dir: str) -> Dict[str, Any]:
    """Что аварийный путь говорит СЕГОДНЯ (только чтение, печать)."""
    def _load(name: str) -> Tuple[Optional[Any], Optional[str]]:
        p = os.path.join(data_dir, name)
        if not os.path.exists(p):
            return None, "absent"
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh), None
        except (OSError, ValueError) as exc:
            return None, f"{type(exc).__name__}: {exc}"
    out: Dict[str, Any] = {}
    emg, why = _load("emergency_status.json")
    out["emergency_status"] = ({"status": emg.get("status"), "triggered": emg.get("triggered"),
                                "checked_at": emg.get("checked_at")} if isinstance(emg, dict)
                               else {"reason": why or "не словарь"})
    ks, why = _load("kill_switch_active.json")
    out["kill_switch"] = ({"present": True, "active": ks.get("active", True)} if isinstance(ks, dict)
                          else {"present": False, "reason": why})
    tr, why = _load("threat_reactor_status.json")
    out["threat_reactor"] = ({"ts": tr.get("ts"), "threats": tr.get("threats"),
                              "unmeasured": tr.get("unmeasured")} if isinstance(tr, dict)
                             else {"reason": why or "не словарь"})
    pos, why = _load(os.path.join("monitoring", "risk_posture.json"))
    out["posture"] = ({"portfolio": pos.get("portfolio"),
                       "entries": sorted((pos.get("entries") or {}).keys())}
                      if isinstance(pos, dict) else {"reason": why or "не словарь"})
    return out


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], order: Dict[str, Any], triggers: Dict[str, Any],
              priorities: Dict[str, Any], processes: Dict[str, Any],
              inventory: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "message": msg})

    if parity_r.get("agrees") is False:
        add("WARN", "card_parity_mismatch", "; ".join(parity_r["mismatches"]))
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    if order.get("kind") == UNMEASURED:
        unmeasured.append(f"порядок шагов цикла: {order.get('reason')}")

    if not triggers.get("measured"):
        unmeasured.append(f"ось A: {triggers.get('reason')}")
    else:
        held = [t for t, r in triggers["triggers"].items() if r["reach"] == "holds_the_book"]
        if held and order.get("kind") == "halt_precedes_exit":
            add("CRITICAL", "breaker_halt_precedes_the_exit",
                f"датчики EmergencyBreakers на {held} дают HALT, а ранний выход Step 2b "
                f"(строка {order['lines'].get('breaker_return')}) стои́т ДО all-cash стоп-крана "
                f"(строка {order['lines'].get('kill_switch_override')}) и ДО сделки (строка "
                f"{order['lines'].get('trade_damper')}): книга ДЕРЖИТСЯ в поражённом протоколе, "
                f"пока датчик горит, и взведённый реактором стоп-кран вывести капитал не может")
        for t, r in triggers["triggers"].items():
            if r["reach"] == "declared_by_registry":
                mods = (r["doors"].get("tier_a") or {}).get("modules") or []
                add("WARN", f"trigger_declared_only:{t}",
                    f"«{t}»: ни одна дверь быстрого пути (EB · реактор · RTMR) триггер не "
                    f"называет; обнаружение заявлено только именами модулей Tier-A {mods} и "
                    f"сценой не измерено")
            elif r["reach"] == "undetected":
                add("WARN", f"trigger_undetected:{t}",
                    f"«{t}»: ни одна дверь дерева триггер не называет")
            elif r["reach"] == UNMEASURED:
                unmeasured.append(f"ось A «{t}»: " + "; ".join(
                    f"{d}: {v.get('reason')}" for d, v in r["doors"].items()
                    if v.get("reach") == UNMEASURED))

    if not priorities.get("measured"):
        unmeasured.append(f"ось B: {priorities.get('reason')}")
    else:
        for p, r in priorities["priorities"].items():
            if r["kind"] == "vetoes_exit":
                add("CRITICAL", f"priority_outranks_capital_preservation:{p}",
                    f"«{p}» ({r['door']}): {r.get('why')} — обратное требованию §29")
            elif r["kind"] == UNMEASURED:
                unmeasured.append(f"ось B «{p}»: {r.get('why')}")
        yielding = [p for p, r in priorities["priorities"].items() if r["kind"] == "yields_to_exit"]
        if yielding:
            add("INFO", "derisk_passes_live_doors",
                f"двери живого пути уступают выходу на {yielding}: демпфер (`derisk_never_damped`), "
                f"урезание (`NOT_A_RESHUFFLE`), взвод CIO (`DERISK`) — измерено сценами с контролем")
        # Отсутствие строки/двери — отдельный исход, не пустой словарь (инв. #17, храповик
        # absent_observation): нет ответа теневой двери ⇒ находки нет И об этом не говорится
        # как о «не HOLD».
        apy_row = priorities["priorities"].get("APY")
        econ = apy_row.get("shadow_door") if isinstance(apy_row, dict) else None
        if isinstance(econ, dict) and econ.get("measured") and econ.get("decision") == "HOLD":
            add("WARN", "cio_door_answers_an_emergency_with_yield_logic",
                f"теневая дверь CIO (rebalance_economics.evaluate) на выходе книги в кэш говорит "
                f"HOLD с причинами {econ.get('reasons', [])[:3]}: у неё нет аварийного входа, "
                f"и вопрос «спасать ли капитал» она решает мерой доходности — это один процесс, "
                f"а не два (§29, первая строка)")

    if not processes.get("measured"):
        unmeasured.append("ось C не измерена")
    else:
        inside = [l for l, r in processes["links"].items() if r.get("kind") == "inside_yield_cycle"]
        rk = processes.get("reactor_kickstarts_cycle") or {}
        if "kill_switch_override" in inside and "trade_step_3" in inside:
            add("WARN", "exit_leg_lives_in_the_yield_process",
                f"единственное звено, которое ДВИГАЕТ капитал (all-cash Step 2c + сделка Step 3), "
                f"живёт в run_cycle — процессе доходности; отдельные агенты "
                f"{[l for l, r in processes['links'].items() if r.get('kind') == 'separate_agent']} "
                f"только наблюдают и взводят флаг (реактор пинает `com.spa.daily_cycle`: "
                f"{rk.get('kickstart')}, сам не торгует: {not rk.get('trades_itself')})")
        for l, r in processes["links"].items():
            if r.get("kind") == UNMEASURED:
                unmeasured.append(f"ось C «{l}»: {r.get('why')}")

    br = inventory.get("breakers") or {}
    if br.get("measured", True) and br.get("has_exit") is False:
        add("INFO", "breaker_vocabulary_has_no_exit",
            f"словарь EmergencyBreakers {br.get('vocabulary')} не содержит ВЫХОДА: по построению "
            f"он умеет остановить цикл, но не вывести капитал; выход есть у RTMR "
            f"({(inventory.get('rtmr_reaction') or {}).get('vocabulary')}) и у стоп-крана")
    cio = inventory.get("cio_door") or {}
    if cio.get("measured", True) and cio.get("has_emergency_input") is False:
        add("INFO", "cio_door_has_no_emergency_input",
            f"у {cio.get('module')} ни один из {len(cio.get('params', []))} входов и "
            f"{len(cio.get('decision_fields', []))} полей вердикта не называет аварию — "
            f"extension §29 проектировать не от чего")
    pg = (triggers.get("posture_gate") or {}) if triggers.get("measured") else {}
    if pg.get("measured") and pg.get("docstring_claims_unwired") and pg.get("zeroed"):
        add("INFO", "posture_gate_docstring_claims_unwired",
            "докстринг `apply_rtmr_posture_gate` утверждает «cycle_runner does not call this "
            "yet», а цикл зовёт её на Step 2e и поза EXITED обнуляет цель — записка устарела "
            "(money-path не правится этим прибором)")
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Полный замер §29. Только ЧИТАЕТ; ``applied=False``."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)

    parity_r = parity(card_path)
    order = measure_cycle_order(root)
    triggers = measure_triggers(order, stamped)
    priorities = measure_priorities(order)
    processes = measure_processes(root, data_dir)
    inventory = measure_policy_inventory()
    live = measure_live_state(data_dir)

    findings, unmeasured = _findings(parity_r, order, triggers, priorities, processes, inventory)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else
               "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "emergency_mode_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §29 ТЗ «Portfolio CIO» (Emergency mode). "
                     "EmergencyBreakers, стоп-кран, RiskPolicy, демпфер, RTMR и живой трек НЕ "
                     "трогает; карточку владельцу не заводит"),
        "overall": overall,
        "counts": counts,
        "declared": {"triggers": list(OWNER_TRIGGERS), "priorities": list(OWNER_PRIORITIES),
                     "separation_line": OWNER_SEPARATION_LINE, "directive": OWNER_DIRECTIVE_LINE,
                     "order_g961_named": dict(ORDER_G961_NAMED),
                     "reach_kinds": list(REACH_KINDS), "priority_kinds": list(PRIORITY_KINDS),
                     "process_kinds": list(PROCESS_KINDS), "order_kinds": list(ORDER_KINDS),
                     "order_markers": dict(ORDER_MARKERS)},
        "parity": parity_r,
        "cycle_order": order,
        "axis_a_triggers": triggers,
        "axis_b_priorities": priorities,
        "axis_c_processes": processes,
        "axis_d_policy_inventory": inventory,
        "live_state": live,
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — (data, path): перестановка у §26 оставляла прибор без артефакта.
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§29 ТЗ «Portfolio CIO» (Emergency mode): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (триггеров {OWNER_TRIGGERS_DECLARED}, приоритетов "
              f"{OWNER_PRIORITIES_DECLARED}; заказ G961 назвал триггеров "
              f"{ORDER_G961_NAMED['triggers']}, сдвиг {p.get('order_undercount')}, приоритеты "
              f"заказ не считал)")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    o = doc["cycle_order"]
    print(f"   порядок шагов цикла: {o.get('kind')} — {o.get('reason')}")
    a = doc["axis_a_triggers"]
    if a.get("measured"):
        print(f"   [ось A] досягаемость книги по триггерам: {a.get('tally')}")
        for t, r in a["triggers"].items():
            doors = ", ".join(f"{d}→{v.get('reach')}" for d, v in r["doors"].items())
            print(f"      «{t}»: {r['reach']} ({doors})")
    else:
        print(f"   [ось A] НЕ ИЗМЕРЕНО: {a.get('reason')}")
    b = doc["axis_b_priorities"]
    if b.get("measured"):
        print(f"   [ось B] приоритеты против выхода: {b.get('tally')}")
        for pr, r in b["priorities"].items():
            print(f"      «{pr}» ({r['door']}): {r['kind']} — {r.get('why')}")
    else:
        print(f"   [ось B] НЕ ИЗМЕРЕНО: {b.get('reason')}")
    cx = doc["axis_c_processes"]
    if cx.get("measured"):
        print(f"   [ось C] процессы: {cx.get('tally')} · реактор пинает цикл: "
              f"{(cx.get('reactor_kickstarts_cycle') or {}).get('kickstart')}")
    d = doc["axis_d_policy_inventory"]
    print(f"   [ось D] словарь EB: {(d.get('breakers') or {}).get('vocabulary')} (выход: "
          f"{(d.get('breakers') or {}).get('has_exit')}) · RTMR выход: "
          f"{(d.get('rtmr_reaction') or {}).get('has_exit')} · аварийный вход CIO: "
          f"{(d.get('cio_door') or {}).get('has_emergency_input')}")
    ls = doc["live_state"]
    print(f"   живое: EB {ls['emergency_status'].get('status')} · стоп-кран файл "
          f"{ls['kill_switch'].get('present')} · реактор угроз {ls['threat_reactor'].get('threats')} "
          f"· поза {ls['posture'].get('portfolio')}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


def parse_now(raw: Optional[str]) -> Tuple[Optional[dt.datetime], Optional[str]]:
    """``--now`` — вход, не окружение. Пустое/неразбираемое — ОТКАЗ, не часы."""
    if raw is None:
        return None, None
    s = raw.strip()
    if not s:
        return None, "--now пуст — отказ, а не стенные часы"
    try:
        ts = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None, f"--now {raw!r} не разбирается как ISO-8601 — отказ, а не стенные часы"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts, None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§29 ТЗ «Portfolio CIO»: Emergency mode — доходят ли шесть триггеров до "
                    "книги и уступают ли пять экономических дверей аварийному выходу")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — "
                         "передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(argv)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(ns.data_dir if ns.data_dir else ns.root, who="emergency_mode_census")
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card,
              write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
