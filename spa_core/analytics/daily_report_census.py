"""daily_report_census.py — §34 ТЗ «Portfolio CIO»: «Daily Report».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §34::

    Daily Report
    Обновить SPA Daily Report.
    Сохранить существующие полезные части, но добавить CIO section.
    Пример:
    🧠 Portfolio CIO
    Current expected net APY · Optimal policy-compliant APY · Yield gap · Target allocation
    (…: %, Cash: %) · Decision: REBALANCE · Recommended (Move $X, A → B) ·
    Expected incremental return (7d · 30d · 90d) · Switching cost · Break-even ·
    Expected persistence · Risk (before · after) · Confidence
    Если ничего делать не надо: Decision: KEEP · Reason: …

Пунктов CIO-секции **ТРИНАДЦАТЬ**; у одного («Expected incremental return») три горизонта;
у «Decision» словарь владельца — REBALANCE / KEEP; существующие части отчёта владелец велел
СОХРАНИТЬ. Прибор сверяет перечень, горизонты, словарь и обе границы раздела с карточкой.

Предмет — «у КАЖДОГО пункта CIO-секции есть ПРОИЗВОДИТЕЛЬ (поле носителя с третьим исходом),
ЧИТАТЕЛЬ-ВЛАДЕЛЕЦ (пункт ДОХОДИТ до отчёта, который владелец получает каждое утро) и
третий исход», а не «есть ли дайджест». Разница существенна, и ради неё у пункта три оси:

* **производитель** — ``produced`` (поле записи решения несёт значение) ·
  ``components_only`` (слагаемые лежат в записи, число владельца не складывает никто) ·
  ``absent`` (ни поля, ни слагаемых — ближайший носитель назван) · ``unmeasured``;
* **читатель-владелец** — доходит ли ЗНАЧЕНИЕ (не подстрока имени) до утреннего отчёта
  (``spa_core.telegram.reports.daily.build_digest_messages`` — ЕДИНСТВЕННЫЙ отправитель
  владельцу, агент ``com.spa.digest_daily``) и, отдельно, до слоя дашборда
  (``cio_brief.brief_from_history`` → ``/api/live/books/brief``, ADR-488/808);
* **третий исход** — отличает ли носитель «не измерено» от «ноль» (``None``/отсутствие
  ключа наблюдены в ленте, инв. #17).

🪤 ЛОВУШКА, ради которой ось читателя меряется НАСТОЯЩИМ сборщиком отчёта
========================================================================
ADR-488 нашёл, что журнал нёс все три числа, слой отображения оставлял одно; ADR-808 — что
объяснение доходит до дашборда, но не до отчёта. Ответить «поля есть в записи, значит
владелец видит» значило бы повторить обе ошибки. Поэтому отчёт СОБИРАЕТСЯ настоящим
сборщиком на том же каталоге данных (``drain=False`` — очередь событий не очищается,
ни один файл не пишется) и в его тексте ищется РЕНДЕР значения с ≥3 значащими цифрами
(«4,01» / «4.01» / «55,000»), а не слово «Yield gap». Сборщик — ВХОД (``reader=``), по
умолчанию живой; сцена батареи подаёт своего читателя для контроля в обе стороны.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): отчёт не отправляет, запись, дайджест, очередь событий и
витрину не правит ни байтом, пункты CIO не ВЫЧИСЛЯЕТ (это дало бы третье место для чисел,
`.claude/rules/site-numbers.md`). Карточку владельцу не заводит: CIO-секция отчёта —
advisory-слой, работа агента. Контрапункты ВВЕЗЕНЫ, не перемерены: нижняя граница цели
(ADR-859/979), восемь фактов объяснения (ADR-808), три числа дашборда (ADR-488), горизонты
контрфакта (ADR-977: из пяти считается один), словарь вердиктов §24.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import error_class_census as ecc
from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/daily_report_census.json"
CARD_REL = smc.CARD_REL
MANIFEST_REL = ecc.MANIFEST_REL

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "34. Daily Report"
NEXT_SECTION_HEAD = "35. Paper APY cleanup"
OWNER_KEEP_WORDS = "Сохранить существующие полезные части"
OWNER_EXAMPLE_WORD = "Пример:"
OWNER_SECTION_TITLE = "🧠 Portfolio CIO"
OWNER_KEEP_BRANCH = "Если ничего делать не надо:"

#: Пункты CIO-секции в порядке примера владельца. Ярлык — дословно до двоеточия.
OWNER_ITEMS: Tuple[str, ...] = (
    "Current expected net APY",
    "Optimal policy-compliant APY",
    "Yield gap",
    "Target allocation",
    "Decision",
    "Recommended",
    "Expected incremental return",
    "Switching cost",
    "Break-even",
    "Expected persistence",
    "Risk",
    "Confidence",
    "Reason",
)
OWNER_ITEMS_DECLARED = 13
OWNER_HORIZONS: Tuple[str, ...] = ("7d", "30d", "90d")
OWNER_DECISION_WORDS: Tuple[str, ...] = ("REBALANCE", "KEEP")
#: Строка Cash в примере целевой раскладки — доля кэша есть пункт раскладки, не остаток.
OWNER_ALLOCATION_CASH_ROW = "Cash"

#: Заказ G967 п. 1 назвал предмет и границы (`sed -n '936,975p'`, вторая граница — §35),
#: чисел не называл — сдвиг не применим, и это печатается отдельно от «назвал верно».
ORDER_G967_NAMED: Dict[str, Any] = {"items": None, "horizons": None, "tail_read": True}

ITEM_KINDS: Tuple[str, ...] = ("produced", "components_only", "absent", UNMEASURED)
PRODUCED_KINDS: Tuple[str, ...] = ("produced",)

#: Носители.
RECORD_REL = smc.RECORD_REL                     # лента решений Conservative (отчёт — о ней)
TRACK_REL = smc.TRACK_REL
DIGEST_GUARD_REL = ".last_daily_digest"         # когда утренний отчёт отправлен в последний раз
ALERT_STATE_REL = "telegram_alert_state.json"   # PRODUCES отправителя (ADR-154/158)

#: Род ЧИСЛА (ADR-580 §C2): запись советника — ожидание в момент решения.
NUMBER_EXPECTATION = "ожидание T0 (из evidenced-ставок дня)"
NUMBER_MODEL = "оценка T0 (модель стоимости ADR-243)"

#: Сколько значащих цифр обязан нести рендер, чтобы совпадение в тексте отчёта считалось
#: ДОХОДИМОСТЬЮ значения, а не случайностью («4,0» совпадёт с чем угодно).
MIN_SIGNIFICANT_DIGITS = 3

#: Пункт → производитель. ``field`` — поле записи решения; ``brief_key`` — ключ слоя
#: дашборда (``cio_brief.brief_from_history``); ``components`` — слагаемые, когда числа
#: владельца никто не складывает; ``nearest`` — ближайший носитель у отсутствующего.
ITEM_SPEC: Dict[str, Dict[str, Any]] = {
    "Current expected net APY": {
        "field": "book_apy_pp", "brief_key": "current_apy_pp", "number_kind": NUMBER_EXPECTATION,
        "value_kind": "rate",
        "qualifier": ("слово владельца «net» носителем не подтверждено: запись не объявляет род "
                      "ставки (gross/net); book_apy_pp — ожидание из evidenced-ставок, стоимость "
                      "переключения у держимой книги равна нулю")},
    "Optimal policy-compliant APY": {
        "field": "target_apy_pp", "brief_key": "optimal_apy_pp", "number_kind": NUMBER_EXPECTATION,
        "value_kind": "rate",
        "qualifier": ("НИЖНЯЯ ГРАНИЦА объявленного оптимума — поиск перебирает подмножества "
                      "(ADR-859/979); унаследовано, здесь не перемеряется")},
    "Yield gap": {
        "field": "gain_pp", "brief_key": "yield_gap_pp", "number_kind": NUMBER_EXPECTATION,
        "value_kind": "rate",
        "qualifier": "нижняя граница разрыва — наследует род уменьшаемого (ADR-979)"},
    "Target allocation": {
        # слой дашборда (`where`) печатает ДЕРЖИМОЕ и ноги хода, не целевую раскладку
        "components": ("target_positions", "capital_usd"), "brief_key": None,
        "number_kind": NUMBER_EXPECTATION, "value_kind": "allocation",
        "not_composed": ("в записи — доллары по протоколам; доли в % и строка "
                         f"«{OWNER_ALLOCATION_CASH_ROW}» (капитал − Σ позиций) не "
                         "складывает никто")},
    "Decision": {
        "field": "verdict", "brief_key": "verdict", "number_kind": "вердикт", "value_kind": "word",
        "vocabulary": OWNER_DECISION_WORDS},
    "Recommended": {
        "field": "legs", "brief_key": "where", "number_kind": NUMBER_EXPECTATION,
        "value_kind": "legs"},
    "Expected incremental return": {
        "components": ("gain_pp", "capital_usd", "cost_usd"), "brief_key": None,
        "number_kind": NUMBER_EXPECTATION, "value_kind": "money",
        "not_composed": ("долларовый прирост по горизонтам 7d/30d/90d не складывает никто; "
                         "контрфакт считается на одном горизонте из пяти (ADR-977)")},
    "Switching cost": {
        "field": "cost_usd", "brief_key": None, "number_kind": NUMBER_MODEL, "value_kind": "money"},
    "Break-even": {
        "field": "payback_days", "brief_key": None, "number_kind": NUMBER_EXPECTATION,
        "value_kind": "days"},
    "Expected persistence": {
        "nearest": ("ни одно поле записи не несёт ожидаемую длительность преимущества; "
                    "ближайшее — apy_as_of (возраст ставок), но это свежесть входа, не "
                    "устойчивость выхода")},
    "Risk": {
        "nearest": ("меры риска «до/после» нет; ближайшее — admissible_trim.policy.approved "
                    "(вердикт RiskPolicy по урезанному предложению, да/нет), не число")},
    "Confidence": {
        "nearest": ("уровня уверенности нет; ближайшее — gates.target_fully_evidenced и "
                    "apy_unevidenced (все ли ставки цели доказаны), но слово Confidence и "
                    "его шкалу никто не производит")},
    "Reason": {
        "field": "reasons", "brief_key": "why", "number_kind": "перечень причин",
        "value_kind": "reasons"},
}

#: Существующие части отчёта, которые владелец велел СОХРАНИТЬ (по его же примеру §2 ТЗ:
#: портфель, Paper APY с 7-дневным средним, позиции) — ключ ``data`` сборщика → род.
PRESERVED_PARTS: Tuple[Tuple[str, str], ...] = (
    ("equity_usd", "money"),
    ("apy_today_pct", "rate"),
    ("apy_7day_avg_pct", "rate"),
    ("positions", "allocation"),
)


# ───────────────────────────── паритет с карточкой ────────────────────────────

_LABEL_RE = re.compile(r"^([A-Z][A-Za-z -]*?):\s*(.*)$")
_HORIZON_RE = re.compile(r"^(\d+d):")


def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница "
                      f"{NEXT_SECTION_HEAD!r} — пример не ограничен, и счёт по нему "
                      f"был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _example_items(body: List[str]) -> Dict[str, Any]:
    """Пункты примера владельца: ярлык до двоеточия на строке ВЕРХНЕГО уровня.

    Строка-ярлык без значения («Target allocation:», «Recommended:», «Risk:», «Reason:»)
    открывает блок: следующие непустые строки до пустой — её ДЕТИ, не пункты (так
    «Aave: 22%» и «7d: +$X» не становятся пунктами секции). Повтор ярлыка («Decision» в
    ветке KEEP) считается один раз. HTML-комментарии карточки — не строки владельца.
    """
    start = next((i for i, ln in enumerate(body) if ln.strip() == OWNER_EXAMPLE_WORD), None)
    if start is None:
        return {"items": None, "horizons": None, "allocation_rows": None, "decision_words": None}
    items: List[str] = []
    horizons: List[str] = []
    allocation_rows: List[str] = []
    decision_words: List[str] = []
    open_block: Optional[str] = None
    for ln in body[start + 1:]:
        s = ln.strip()
        if s == "⸻":
            break
        if not s:
            open_block = None
            continue
        if s.startswith("<!--") or s == OWNER_SECTION_TITLE or s == OWNER_KEEP_BRANCH:
            continue
        if open_block is not None:
            hm = _HORIZON_RE.match(s)
            if open_block == "Expected incremental return" and hm:
                horizons.append(hm.group(1))
            elif open_block == "Target allocation":
                m = _LABEL_RE.match(s)
                allocation_rows.append(m.group(1) if m else s)
            continue
        m = _LABEL_RE.match(s)
        if not m:
            continue
        label, value = m.group(1), m.group(2).strip()
        if label not in items:
            items.append(label)
        if label == "Decision" and value and value not in decision_words:
            decision_words.append(value)
        if not value:
            open_block = label
    return {"items": items, "horizons": horizons, "allocation_rows": allocation_rows,
            "decision_words": decision_words}


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = smc._read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    out: Dict[str, Any] = {"measured": True,
                           "keep_words_present": any(OWNER_KEEP_WORDS in s for s in stripped),
                           "title_present": OWNER_SECTION_TITLE in stripped,
                           "keep_branch_present": OWNER_KEEP_BRANCH in stripped}
    out.update(_example_items(body))
    return out


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None,
                           "order_tail_read": ORDER_G967_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    items = parsed.get("items")
    if items is None:
        mism.append(f"в разделе нет слова владельца {OWNER_EXAMPLE_WORD!r} — пример не объявлен, "
                    f"пункты не прочитаны")
    elif list(items) != list(OWNER_ITEMS):
        mism.append(f"пункты примера {items} ≠ константам {list(OWNER_ITEMS)}")
    if items is not None and list(parsed.get("horizons") or []) != list(OWNER_HORIZONS):
        mism.append(f"горизонты примера {parsed.get('horizons')} ≠ константам {list(OWNER_HORIZONS)}")
    if items is not None and list(parsed.get("decision_words") or []) != list(OWNER_DECISION_WORDS):
        mism.append(f"словарь Decision в примере {parsed.get('decision_words')} ≠ "
                    f"константам {list(OWNER_DECISION_WORDS)}")
    if items is not None and OWNER_ALLOCATION_CASH_ROW not in (parsed.get("allocation_rows") or []):
        mism.append(f"в примере целевой раскладки нет строки {OWNER_ALLOCATION_CASH_ROW!r}")
    if not parsed.get("keep_words_present"):
        mism.append(f"в разделе нет слов владельца {OWNER_KEEP_WORDS!r}")
    if not parsed.get("title_present"):
        mism.append(f"в примере нет заголовка секции {OWNER_SECTION_TITLE!r}")
    if not parsed.get("keep_branch_present"):
        mism.append(f"в примере нет ветки {OWNER_KEEP_BRANCH!r}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if items is not None and ORDER_G967_NAMED["items"] is not None:
        out["order_undercount"] = {"items": len(items) - int(ORDER_G967_NAMED["items"])}
    return out


# ───────────────────────────── носители ──────────────────────────────────────

def load_carriers(data_dir: str, root: str = REPO_ROOT) -> Dict[str, Any]:
    """Лента решений и трек — дверью §30; отметка отправки отчёта и состояние отправителя — своими."""
    out = smc.load_carriers(data_dir)
    d = Path(data_dir)
    for key, rel in (("digest_guard", DIGEST_GUARD_REL), ("alert_state", ALERT_STATE_REL)):
        doc, why = smc._read_json(d / rel)
        ok = isinstance(doc, dict)
        out[key] = doc if ok else None
        out[f"{key}_reason"] = why if doc is None else (None if ok else f"{rel} не словарь")
    out["data_dir"] = str(d)
    out["root"] = root
    return out


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _ledger_shape(rows: List[dict], key: str) -> Dict[str, Any]:
    """Три состояния поля по ленте: число/непустое · None · ключа нет (инв. #17)."""
    numeric = sum(1 for r in rows if key in r and r.get(key) is not None and r.get(key) != [] and r.get(key) != {})
    nulls = sum(1 for r in rows if key in r and (r.get(key) is None or r.get(key) == [] or r.get(key) == {}))
    absent = sum(1 for r in rows if key not in r)
    if nulls:
        third = "наблюдён (None/пусто в ленте отличимо от значения)"
    elif absent:
        third = "только отсутствием ключа (None в ленте не наблюдён)"
    else:
        third = "не наблюдён (все строки со значением — отличимость не доказана лентой)"
    return {"rows": len(rows), "with_value": numeric, "null_rows": nulls, "absent_rows": absent,
            "third_outcome": third}


# ───────────────────────────── ось читателя: рендеры значения ────────────────

def _significant_digits(value: float, decimals: int) -> int:
    """Значащие цифры числа, напечатанного с ``decimals`` знаками: ведущие нули и нули,
    ДОПИСАННЫЕ форматом в дробной части, значимостью не являются («0,430» несёт две цифры,
    «55 000» — пять). Считается от ЧИСЛА, а не разбором строки: запятая в «55,000» и в
    «4,012» — разные знаки, и строка этого не знает."""
    whole, _, frac = f"{abs(value):.{decimals}f}".partition(".")
    return len((whole + frac.rstrip("0")).lstrip("0"))


def renderings(value: object, value_kind: str) -> List[str]:
    """Как число могло быть НАПЕЧАТАНО владельцу: EN/RU разделители, 0…3 знака, тысячи.
    Оставляются только рендеры с ≥``MIN_SIGNIFICANT_DIGITS`` значащими цифрами."""
    out: List[str] = []
    if value_kind in ("rate", "days", "money") and isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        for k in (0, 1, 2, 3):
            if _significant_digits(v, k) < MIN_SIGNIFICANT_DIGITS:
                continue
            plain, grouped = f"{v:.{k}f}", f"{v:,.{k}f}"
            ru = grouped.replace(",", "\u2009").replace(".", ",")   # RU: 55 000 · 4,01 — ОДНА дверь
            out.extend([plain, grouped, ru, ru.replace("\u2009", " ")])
    elif value_kind == "word" and isinstance(value, str) and value:
        out.append(value)
    uniq: List[str] = []
    for r in out:
        if r not in uniq:
            uniq.append(r)
    return uniq


def value_reaches(value: object, value_kind: str, text: str) -> Optional[bool]:
    """Доходит ли ЗНАЧЕНИЕ до текста. ``None`` — рендера с достаточной точностью нет
    (например 0.43 → две значащие цифры), то есть доходимость НЕ ИЗМЕРЕНА, не «нет»."""
    if value_kind == "allocation" and isinstance(value, dict):
        amounts = [v for v in value.values() if _num(v)]
        if not amounts:
            return None
        hits = [value_reaches(v, "money", text) for v in amounts]
        if any(h is None for h in hits):
            return None
        return all(hits)
    if value_kind == "legs" and isinstance(value, list):
        legs = [lg for lg in value if isinstance(lg, dict) and _num(lg.get("delta_usd"))]
        if not legs:
            return None
        hits = [(str(lg.get("protocol")) in text) and value_reaches(abs(float(lg["delta_usd"])), "money", text) is True
                for lg in legs]
        return all(hits)
    if value_kind == "reasons" and isinstance(value, list):
        reasons = [str(r) for r in value if str(r).strip()]
        if not reasons:
            return None
        return all(r in text for r in reasons)
    forms = renderings(value, value_kind)
    if not forms:
        return None
    return any(f in text for f in forms)


ReportReader = Callable[[str, dt.datetime], Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]], Optional[str]]]


def live_report_reader(data_dir: str, now: dt.datetime
                       ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """НАСТОЯЩИЙ сборщик утреннего отчёта владельцу, только чтение (``drain=False``).
    Возврат — (заголовок, подробности, data, причина-если-не-собрался)."""
    try:
        from spa_core.telegram.reports.daily import build_digest_messages
    except Exception as exc:  # noqa: BLE001 — нечем собрать ≠ «не доходит»
        return None, None, None, f"сборщик отчёта не импортирован: {type(exc).__name__}: {exc}"
    try:
        headline, details, data = build_digest_messages(None, data_dir=data_dir, now=now, drain=False)
    except Exception as exc:  # noqa: BLE001
        return None, None, None, f"сборщик отчёта упал: {type(exc).__name__}: {exc}"
    return headline, details, data if isinstance(data, dict) else {}, None


def brief_for(records: List[dict]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Слой дашборда — НАСТОЯЩИЙ ``cio_brief.brief_from_history`` (чистая функция, без I/O)."""
    try:
        from spa_core.paper_trading.cio_brief import brief_from_history
    except Exception as exc:  # noqa: BLE001
        return None, f"cio_brief не импортирован: {type(exc).__name__}: {exc}"
    try:
        doc = brief_from_history(list(records))
    except Exception as exc:  # noqa: BLE001
        return None, f"cio_brief упал: {type(exc).__name__}: {exc}"
    return (doc if isinstance(doc, dict) else None), (None if isinstance(doc, dict) else "brief не словарь")


def _brief_reach(spec: Dict[str, Any], value: object, brief: Optional[Dict[str, Any]]) -> Optional[bool]:
    key = spec.get("brief_key")
    if key is None or brief is None or not brief.get("available"):
        return None
    got = brief.get(key)
    kind = spec.get("value_kind")
    if kind in ("rate", "days", "money", "word"):
        return got == value if got is not None else False
    if kind in ("allocation", "legs", "reasons"):
        text = str(got or "")
        if kind == "allocation" and isinstance(value, dict):
            return all(str(k) in text for k in value) if value else None
        if kind == "legs" and isinstance(value, list):
            legs = [lg for lg in value if isinstance(lg, dict) and _num(lg.get("delta_usd"))]
            return bool(legs) and all(str(lg.get("protocol")) in text
                                      and f"{abs(float(lg['delta_usd'])):,.0f}" in text for lg in legs)
        if kind == "reasons" and isinstance(value, list):
            # слой прозы переводит коды причин словами — доходимость судится по НАЛИЧИЮ прозы
            return bool(text.strip()) if value else None
    return None


# ───────────────────────────── измерение пунктов ─────────────────────────────

def measure_items(carriers: Dict[str, Any], report_text: Optional[str],
                  brief: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    recs = carriers.get("records")
    out: Dict[str, Any] = {}
    if not recs:
        why = f"лента решений {RECORD_REL} не прочитана/пуста: {carriers.get('records_reason') or 'нет строк'}"
        for name in OWNER_ITEMS:
            out[name] = {"kind": UNMEASURED, "reason": why}
        return _tally(out, report_text)
    last = recs[-1]
    for name in OWNER_ITEMS:
        spec = ITEM_SPEC[name]
        r: Dict[str, Any] = {"number_kind": spec.get("number_kind"), "qualifier": spec.get("qualifier")}
        if "field" in spec:
            key = spec["field"]
            shape = _ledger_shape(recs, key)
            value = last.get(key)
            present = key in last and value is not None and value != [] and value != {}
            r.update({"kind": "produced" if present or shape["with_value"] else "absent",
                      "carrier": f"{RECORD_REL}: {key}", "value": value if present else None,
                      "value_present_in_last": present, "ledger": shape,
                      "third_outcome": shape["third_outcome"]})
            if not present and shape["with_value"] == 0:
                r["reason"] = f"поле {key} ни в одной из {shape['rows']} записей не несёт значения"
            if spec.get("vocabulary") is not None:
                seen = sorted({str(x.get(key)) for x in recs if x.get(key) is not None})
                r["vocabulary"] = {"owner": list(spec["vocabulary"]), "ledger": seen,
                                   "agrees": bool(set(seen) & set(spec["vocabulary"]))}
            r["report_reach"] = (value_reaches(value, spec["value_kind"], report_text)
                                 if (present and report_text is not None) else None)
            r["brief_reach"] = _brief_reach(spec, value, brief) if present else None
        elif "components" in spec:
            comps = {c: last.get(c) for c in spec["components"]}
            have = [c for c, v in comps.items() if v is not None and v != {} and v != []]
            r.update({"kind": "components_only" if have else "absent",
                      "carrier": f"{RECORD_REL}: {', '.join(spec['components'])}",
                      "components_present": have, "reason": spec["not_composed"],
                      "third_outcome": "не применимо — числа владельца никто не производит"})
            r["report_reach"] = None
            r["brief_reach"] = _brief_reach(spec, comps.get("target_positions"), brief) if have else None
        else:
            r.update({"kind": "absent", "carrier": None, "reason": spec["nearest"],
                      "third_outcome": "не применимо — производителя нет",
                      "report_reach": None, "brief_reach": None})
        out[name] = r
    return _tally(out, report_text)


def _tally(items: Dict[str, Any], report_text: Optional[str]) -> Dict[str, Any]:
    tally = {k: sum(1 for r in items.values() if r["kind"] == k) for k in ITEM_KINDS}
    produced = [n for n, r in items.items() if r["kind"] in PRODUCED_KINDS]
    reach = [n for n in produced if items[n].get("report_reach") is True]
    dash = [n for n, r in items.items() if r.get("brief_reach") is True]
    return {"items": items, "tally": tally, "declared": OWNER_ITEMS_DECLARED,
            "produced": len(produced), "reach_report": len(reach), "reach_dashboard": len(dash),
            "reach_report_names": reach, "reach_dashboard_names": dash,
            "report_built": report_text is not None,
            "section_title_in_report": (OWNER_SECTION_TITLE in report_text) if report_text is not None else None}


def measure_preserved(data: Optional[Dict[str, Any]], report_text: Optional[str]) -> Dict[str, Any]:
    """Существующие части отчёта (владелец: СОХРАНИТЬ) — есть ли число у сборщика и доходит ли оно."""
    out: Dict[str, Any] = {}
    for key, kind in PRESERVED_PARTS:
        if data is None or report_text is None:
            out[key] = {"kind": UNMEASURED, "reason": "отчёт не собран"}
            continue
        value = data.get(key)
        if value is None or value == {} or value == []:
            out[key] = {"kind": "absent", "reach": None}
            continue
        if kind == "allocation" and isinstance(value, dict):
            amounts = {k: (v.get("usd") if isinstance(v, dict) else v) for k, v in value.items()}
            reach = value_reaches(amounts, "allocation", report_text)
        else:
            reach = value_reaches(value, kind, report_text)
        out[key] = {"kind": "produced", "reach": reach}
    return {"parts": out,
            "all_reach": all(p.get("reach") is True for p in out.values()) if out else None}


def freshness_of(carriers: Dict[str, Any], slo: Dict[str, Optional[float]], now: dt.datetime
                 ) -> Dict[str, Any]:
    recs = carriers.get("records") or []
    rec_stamp = recs[-1].get("generated_at") if recs else None
    guard = carriers.get("digest_guard") or {}
    return {"record": ecc.freshness(rec_stamp, RECORD_REL, slo, now),
            "digest_sent": ecc.freshness(guard.get("sent_at"), ALERT_STATE_REL, slo, now)}


# ───────────────────────────── находки ───────────────────────────────────────

def _short(value: object) -> str:
    """Значение для строки находки: список/словарь — размером и первыми именами, не телом."""
    if isinstance(value, list):
        names = [str(x.get("protocol")) for x in value if isinstance(x, dict) and x.get("protocol")]
        return f"список из {len(value)}" + (f" ({', '.join(names[:3])}{'…' if len(names) > 3 else ''})" if names else "")
    if isinstance(value, dict):
        return f"словарь из {len(value)} ({', '.join(list(map(str, value))[:3])}{'…' if len(value) > 3 else ''})"
    return repr(value)


def _findings(parity_r: Dict[str, Any], items: Dict[str, Any], preserved: Dict[str, Any],
              fresh: Dict[str, Any], report_reason: Optional[str], brief_reason: Optional[str]
              ) -> Tuple[List[Dict[str, Any]], List[str]]:
    findings: List[Dict[str, Any]] = []
    unmeasured: List[str] = []

    def add(sev: str, code: str, msg: str) -> None:
        findings.append({"severity": sev, "code": code, "message": msg})

    if parity_r.get("agrees") is False:
        add("WARN", "card_parity_mismatch", "; ".join(parity_r["mismatches"]))
    elif parity_r.get("agrees") is None:
        unmeasured.append(f"паритет с карточкой: {parity_r['parsed'].get('reason')}")

    if report_reason:
        unmeasured.append(f"утренний отчёт владельцу не собран: {report_reason}")
    if brief_reason:
        unmeasured.append(f"слой дашборда не собран: {brief_reason}")

    rows = items.get("items") or {}
    measured_any = any(r["kind"] != UNMEASURED for r in rows.values())
    # Отсутствие секции — находка об ОТЧЁТЕ, но без единого измеренного пункта это пустой
    # каталог, и ответ прибора — НЕ ИЗМЕРЕНО (код 2), а не CRITICAL.
    if measured_any and items.get("report_built") and items.get("section_title_in_report") is False:
        add("CRITICAL", "cio_section_absent_from_daily_report",
            f"в утреннем отчёте владельцу (оба сообщения дайджеста) нет секции «{OWNER_SECTION_TITLE}»; "
            f"из {OWNER_ITEMS_DECLARED} пунктов до отчёта доходит {items.get('reach_report')}, "
            f"до дашборда (/api/live/books/brief, ADR-488) — {items.get('reach_dashboard')}")
    for name, r in rows.items():
        k = r["kind"]
        if k == UNMEASURED:
            unmeasured.append(f"пункт «{name}»: {r.get('reason')}")
            continue
        if k == "produced":
            reach = r.get("report_reach")
            if reach is True:
                add("INFO", f"item_reaches_report:{name}",
                    f"«{name}»: {r['carrier']} → утренний отчёт; род числа «{r.get('number_kind')}»; "
                    f"третий исход: {r.get('third_outcome')}")
            elif reach is False:
                where = " (доходит до дашборда, не до отчёта — форма ADR-808)" if r.get("brief_reach") else ""
                add("CRITICAL", f"item_not_in_report:{name}",
                    f"«{name}»: производитель есть ({r['carrier']}, значение {_short(r.get('value'))}), "
                    f"до утреннего отчёта владельцу не доходит{where}; род числа «{r.get('number_kind')}»; "
                    f"третий исход: {r.get('third_outcome')}")
            else:
                unmeasured.append(f"доходимость пункта «{name}»: отчёт не собран либо у значения "
                                  f"{_short(r.get('value'))} нет рендера с ≥{MIN_SIGNIFICANT_DIGITS} значащими цифрами")
            if r.get("qualifier"):
                add("WARN", f"item_qualifier:{name}", f"«{name}»: {r['qualifier']}")
            voc = r.get("vocabulary")
            if voc is not None and not voc["agrees"]:
                add("WARN", f"decision_vocabulary_differs:{name}",
                    f"«{name}»: словарь владельца {voc['owner']}, в ленте {voc['ledger']} — "
                    f"читатель примера не найдёт ни одного слова владельца в записи")
        elif k == "components_only":
            add("CRITICAL", f"item_components_only:{name}",
                f"«{name}»: слагаемые в записи ({', '.join(r.get('components_present') or [])}), "
                f"число владельца не складывает никто — {r.get('reason')}")
        elif k == "absent":
            add("CRITICAL", f"item_absent:{name}", f"«{name}»: {r.get('reason')}")

    parts = preserved.get("parts") or {}
    if parts:
        missing = [k for k, p in parts.items() if p.get("kind") == "absent" or p.get("reach") is False]
        unm = [k for k, p in parts.items() if p.get("kind") == UNMEASURED or (p.get("kind") == "produced" and p.get("reach") is None)]
        if parts and all(p.get("kind") in ("absent", UNMEASURED) for p in parts.values()):
            # сборщик не получил ни одного числа трека — это пустой каталог, не снятые части
            unmeasured.append("существующие части отчёта: сборщик собрал отчёт без единого числа трека "
                              f"({list(parts)}) — сохранены ли они, НЕ ИЗМЕРЕНО")
        elif missing:
            add("WARN", "preserved_parts_missing",
                f"существующие части отчёта, которые владелец велел сохранить, не доходят: {missing}")
        elif unm:
            unmeasured.append(f"существующие части отчёта: не измерены {unm}")
        else:
            add("INFO", "preserved_parts_present",
                f"существующие части отчёта сохранены и доходят: {list(parts)}")

    for key, label in (("record", f"лента решений {RECORD_REL}"), ("digest_sent", "отправка утреннего отчёта")):
        fr = fresh.get(key) or {}
        if fr.get("fresh") is False:
            add("WARN", f"stale:{key}", f"{label}: {fr['age_hours']} ч при SLO {fr['slo_hours']} ч (отметка {fr['stamp']})")
        elif fr.get("fresh") is None:
            unmeasured.append(f"свежесть «{label}»: {fr.get('reason')}")

    if rows and items.get("report_built"):
        missing_items = [n for n, r in rows.items() if r["kind"] != UNMEASURED
                         and not (r["kind"] in PRODUCED_KINDS and r.get("report_reach") is True)]
        if missing_items:
            add("CRITICAL", "cio_items_declared_vs_reaching",
                f"объявлено {OWNER_ITEMS_DECLARED} пунктов CIO-секции, производится {items.get('produced')}, "
                f"до утреннего отчёта владельцу доходит {items.get('reach_report')}; не доходят: "
                + ", ".join(f"«{n}»→{rows[n]['kind']}" for n in missing_items))
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None,
        reader: Optional[ReportReader] = None) -> Dict[str, Any]:
    """Полный замер §34. Только ЧИТАЕТ; ``applied=False``. ``reader`` — сборщик отчёта
    (вход; по умолчанию живой ``build_digest_messages`` с ``drain=False``)."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    read = reader or live_report_reader

    parity_r = parity(card_path)
    carriers = load_carriers(data_dir, root)
    slo = ecc.load_slo(root)
    headline, details, data, report_reason = read(data_dir, stamped)
    report_text = None if headline is None and details is None else f"{headline or ''}\n{details or ''}"
    brief, brief_reason = brief_for(carriers.get("records") or []) if carriers.get("records") else (None, None)
    items = measure_items(carriers, report_text, brief)
    preserved = measure_preserved(data, report_text)
    fresh = freshness_of(carriers, slo, stamped)
    findings, unmeasured = _findings(parity_r, items, preserved, fresh, report_reason, brief_reason)
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
        "schema": "daily_report_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §34 ТЗ «Portfolio CIO» (Daily Report). Отчёт не отправляет, "
                     "запись, дайджест, очередь событий и витрину НЕ трогает (drain=False), пункты CIO не "
                     "вычисляет; карточку владельцу не заводит — CIO-секция отчёта есть advisory-слой, "
                     "работа агента. Доходимость судится РЕНДЕРОМ значения в тексте отчёта: случайное "
                     "совпадение цифр ошибается в сторону ЗАВЫШЕНИЯ доходимости — порог "
                     f"{MIN_SIGNIFICANT_DIGITS} значащих цифр держит эту ошибку, но не исключает"),
        "overall": overall,
        "counts": counts,
        "declared": {"items": list(OWNER_ITEMS), "items_declared": OWNER_ITEMS_DECLARED,
                     "horizons": list(OWNER_HORIZONS), "decision_words": list(OWNER_DECISION_WORDS),
                     "section_title": OWNER_SECTION_TITLE, "keep_words": OWNER_KEEP_WORDS,
                     "order_g967_named": dict(ORDER_G967_NAMED),
                     "item_kinds": list(ITEM_KINDS), "produced_kinds": list(PRODUCED_KINDS),
                     "report_reader": "spa_core.telegram.reports.daily.build_digest_messages (drain=False)",
                     "dashboard_reader": "spa_core.paper_trading.cio_brief.brief_from_history",
                     "slo_source": MANIFEST_REL},
        "parity": parity_r,
        "items": items,
        "preserved": preserved,
        "freshness": fresh,
        "report": {"built": report_text is not None, "reason": report_reason,
                   "headline_chars": len(headline) if headline else None,
                   "details_chars": len(details) if details else None},
        "carriers_read": {k: (carriers.get(k) is not None)
                          for k in ("records", "daily", "digest_guard", "alert_state")},
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
    print(f"§34 ТЗ «Portfolio CIO» (Daily Report): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (пунктов {OWNER_ITEMS_DECLARED}, горизонты "
              f"{'/'.join(OWNER_HORIZONS)}, словарь {'/'.join(OWNER_DECISION_WORDS)}, строка Cash, "
              f"слова «сохранить существующие части», заголовок секции, ветка KEEP; заказ G967 "
              f"числа не называл — сдвиг не применим)")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    it = doc["items"]
    rep = doc["report"]
    print(f"   отчёт владельцу собран: {rep.get('built')} (заголовок {rep.get('headline_chars')} зн., "
          f"подробности {rep.get('details_chars')} зн.); секция «{OWNER_SECTION_TITLE}» в нём: "
          f"{it.get('section_title_in_report')}")
    print(f"   пунктов объявлено {it.get('declared')}, производится {it.get('produced')}, до отчёта "
          f"доходит {it.get('reach_report')}, до дашборда {it.get('reach_dashboard')}; роды {it.get('tally')}")
    for name, r in (it.get("items") or {}).items():
        print(f"      «{name}»: {r['kind']} — носитель {r.get('carrier')}, значение {_short(r.get('value'))}, "
              f"отчёт {r.get('report_reach')}, дашборд {r.get('brief_reach')}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


parse_now = smc.parse_now


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§34 ТЗ «Portfolio CIO»: у КАЖДОГО пункта CIO-секции утреннего отчёта есть ли "
                    "производитель, читатель-владелец и третий исход")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — "
                         "передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
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
