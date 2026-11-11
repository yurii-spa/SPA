"""paper_apy_census.py — §35 ТЗ «Portfolio CIO»: «Paper APY cleanup».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §35::

    Paper APY cleanup
    Отдельно исправить или документировать текущий Paper APY.
    Owner должен четко видеть различие:
    Current displayed weighted APY · Expected Net APY · Realized APY ·
    7-day realized/estimated APY · Optimal policy-compliant APY
    Не использовать неочевидную метрику без понятного определения.

Величин владельца **ПЯТЬ**. Предмет — «у КАЖДОЙ из пяти есть ПРОИЗВОДИТЕЛЬ с объявленным
РОДОМ, на поверхности владельца она стои́т с ОПРЕДЕЛЕНИЕМ (род · окно · метод), и пять
величин РАЗЛИЧИМЫ: одно слово не носит двух величин, одна величина не ходит двумя числами
без объяснения», а не «есть ли APY на странице». Ради этого у величины три оси:

* **производитель** — носитель(и) числа и его РОД (ADR-580 §C2 / ADR-953: начисленный
  замер · ожидание · модель · нижняя граница · среднее), третий исход по носителю;
* **определение на поверхности владельца** — утренний отчёт (единственная поверхность,
  которую владелец получает сам), слой дашборда (``cio_brief``, ADR-488) и витрина чисел
  сайта (``site_numbers.json`` — ОДИН адрес чтения, ADR-357 п. 5). Определение — три части:
  **род** (измерено / ожидание / оценка), **окно** (сегодня · 7 дн. · за период) и **метод**
  (формула или источник). Оценка: ``defined`` · ``partial`` (названы не все части) ·
  ``bare`` (голое число) · ``absent`` (величины на поверхности нет);
* **различимость** — одно СЛОВО не носит двух величин (замер: «paper» в утреннем отчёте —
  начисленная ставка дня, «paper» на витрине — годовой эквивалент за период); одна величина
  не ходит ДВУМЯ числами по двум поверхностям без объяснения (замер: «current» в отчёте и
  «current» на дашборде — разные носители и разные числа).

🪤 ЛОВУШКА, ради которой доходимость в отчёте меряется ЯРЛЫКОМ, а не числом
========================================================================
«Displayed» и «weighted» владельца — ДВА поля одного бара (``apy_today`` начисленная,
``apy_expected_pct`` взвешенная, ADR-301), и в день без ненаблюдаемых пулов они РАВНЫ до
четвёртого знака. Поиск рендера значения нашёл бы «3,83» и объявил взвешенную дошедшей —
а в отчёте её нет: строка «ожидание при полной наблюдаемости» печатается только когда
ADR-298 обнулил чью-то ставку. Поэтому доходимость величины судится по её ЯРЛЫКУ в тексте,
а совпадение числа печатается рядом отдельным полем.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): ни одной ставки не ВЫЧИСЛЯЕТ (7-дневную доходность
NAV-отношением — тоже: это дало бы третье место для чисел, `.claude/rules/site-numbers.md`),
отчёт не отправляет (``drain=False``), витрину, запись и трек не правит. Карточку владельцу
не заводит: определение рядом с числом — advisory-слой, работа агента. Контрапункты
ВВЕЗЕНЫ, не перемерены: формула Paper APY (ADR-953: три ставки книги в одном цикле),
нижняя граница оптимума (ADR-859/979), что доходит до отчёта (ADR-980), роды витрины
(ADR-580 §C2), «один APY за сегодня» (ADR-301).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.analytics import daily_report_census as drc
from spa_core.analytics import error_class_census as ecc
from spa_core.analytics import shadow_mode_census as smc
from spa_core.analytics.transaction_economics import UNMEASURED

REPO_ROOT = smc.REPO_ROOT
REPORT_REL = "data/paper_apy_census.json"
CARD_REL = smc.CARD_REL
MANIFEST_REL = ecc.MANIFEST_REL

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "35. Paper APY cleanup"
NEXT_SECTION_HEAD = "36. Owner UI"
OWNER_LEAD = "Отдельно исправить или документировать текущий Paper APY."
OWNER_SEE_LINE = "Owner должен четко видеть различие:"
OWNER_RULE_LINE = "Не использовать неочевидную метрику без понятного определения."

#: Пять величин владельца — дословно, в порядке §35.
OWNER_QUANTITIES: Tuple[str, ...] = (
    "Current displayed weighted APY",
    "Expected Net APY",
    "Realized APY",
    "7-day realized/estimated APY",
    "Optimal policy-compliant APY",
)
OWNER_QUANTITIES_DECLARED = 5

#: Заказ G968 п. 1 назвал «Пять величин владельца» и перечислил их — сдвиг применим.
ORDER_G968_NAMED: Dict[str, Any] = {"quantities": 5, "tail_read": True}

#: Поверхности владельца. Отчёт — то, что он получает сам (агент ``com.spa.digest_daily``);
#: дашборд — слой ``cio_brief`` (ADR-488); витрина — единственный адрес чтения сайта.
SURFACES: Tuple[str, ...] = ("digest", "brief", "shelf")
SHELF_REL = "landing/src/data/site_numbers.json"
SNAPSHOT_REL = "landing/src/data/track_snapshot.json"
REPLAY_REL = "cio_shadow_replay.json"
RECORD_REL = smc.RECORD_REL
TRACK_REL = smc.TRACK_REL

#: Части определения и оценки.
DEFINITION_PARTS: Tuple[str, ...] = ("род", "окно", "метод")
GRADES: Tuple[str, ...] = ("defined", "partial", "bare", "absent", UNMEASURED)

#: Словарь определения в ТЕКСТЕ (строка ярлыка и её продолжение «↳»). Слово роды́ говорит,
#: измерено это или ожидание; слово окна — за какой срок; слово метода — как посчитано.
TEXT_KIND_WORDS: Tuple[str, ...] = ("начислен", "заработан", "наблюд", "фактич", "realized",
                                    "ожидан", "estimated", "оценк", "модел", "нижняя граница",
                                    "замер")
TEXT_WINDOW_WORDS: Tuple[str, ...] = ("сегодня", "за 7 дн", "за период", "за день",
                                      "подтверждённых дн", "trailing", "7-day")
TEXT_METHOD_WORDS: Tuple[str, ...] = ("÷", "/ nav", "nav_", "взвешенн", "сложный процент",
                                      "эквивалент", "act/365", "формул", "источник", "среднее", "перебор")

#: Словарь определения в СЛОВАРЕ носителя (витрина, слой дашборда, data сборщика).
DICT_KIND_KEYS: Tuple[str, ...] = ("kind", "metric_type", "evidence", "horizon",
                                   "optimal_is_lower_bound", "search_kind", "rate_kind")
DICT_WINDOW_KEYS: Tuple[str, ...] = ("window_days", "period", "window", "as_of")
DICT_METHOD_KEYS: Tuple[str, ...] = ("annualisation", "source", "method", "convention", "formula")

#: Слово, которое не имеет права носить две величины. Замер 11.11: «paper» в отчёте —
#: начисленная ставка дня (3,83 %), «paper» на витрине — годовой эквивалент за период (4,86 %).
COLLISION_WORDS: Tuple[str, ...] = ("paper",)

#: Расхождение двух чисел ОДНОЙ величины на двух поверхностях, которое владелец заметит
#: во втором знаке (pp).
DIVERGENCE_TOLERANCE_PP = 0.01

#: Роды чисел (ADR-580 §C2, словами ADR-953).
KIND_ACCRUED = "замер — начисленная годовая ставка ДНЯ: доход × 365 / NAV на открытии, кэш в знаменателе (ADR-298/301, ADR-953)"
KIND_WEIGHTED = "ожидание — взвешенная по позициям ставка книги при полной наблюдаемости (ADR-301)"
KIND_EXPECT_T0 = "ожидание T0 — ставка держимой книги из evidenced-ставок дня (советник ADR-060)"
KIND_REPLAY_NET = "модель — реплей теневых решений с НАЧИСЛЕННОЙ стоимостью (газ + комиссии) по руке current"
KIND_REALIZED = "замер — годовой ЭКВИВАЛЕНТ доходности за фактический период: NAV_RATIO, ACT/365 по датам оценки"
KIND_SEVEN_MEAN = "среднее семи дневных НАЧИСЛЕННЫХ ставок (простая аннуализация каждого дня), не доходность за 7 дней"
KIND_LOWER_BOUND = "ожидание T0 — НИЖНЯЯ ГРАНИЦА объявленного оптимума: поиск перебирает подмножества (ADR-859/979)"

#: Величина → носители (поля) и ярлыки на поверхностях.
#: ``carriers`` — где число ЛЕЖИТ; ``digest_labels`` — ярлыки, которыми отчёт его называет;
#: ``digest_value`` — ключ ``data`` сборщика; ``brief_key`` — ключ слоя дашборда;
#: ``shelf_paths`` — фигуры витрины. ``components`` — слагаемые без сложения.
QUANTITY_SPEC: Dict[str, Dict[str, Any]] = {
    "Current displayed weighted APY": {
        "carriers": (
            {"id": "bar.apy_today", "where": f"{TRACK_REL}: daily[-1].apy_today", "kind": KIND_ACCRUED,
             "role": "displayed"},
            {"id": "bar.apy_expected_pct", "where": f"{TRACK_REL}: daily[-1].apy_expected_pct",
             "kind": KIND_WEIGHTED, "role": "weighted"},
            {"id": "record.book_apy_pp", "where": f"{RECORD_REL}: book_apy_pp", "kind": KIND_EXPECT_T0,
             "role": "current (дашборд)"},
        ),
        "digest_labels": ("APY (paper)", "APY сегодня"),
        "digest_value": "apy_today_pct",
        "digest_secondary": {"label": "ожидание при полной наблюдаемости", "value": "apy_expected_pct",
                             "carrier": "bar.apy_expected_pct",
                             "when": "только когда ADR-298 обнулил ставку хотя бы одного пула"},
        "brief_key": "current_apy_pp", "brief_carrier": "record.book_apy_pp",
        "shelf_paths": (),
        "qualifier": ("слово владельца «displayed weighted» — ДВА поля бара: displayed = начисленная "
                      "(apy_today), weighted = ожидание (apy_expected_pct); совпадают только в день без "
                      "ненаблюдаемых пулов"),
    },
    "Expected Net APY": {
        "carriers": (
            {"id": "replay.net_current", "where": f"{REPLAY_REL}: comparison.charged.net_apy_pct.current",
             "kind": KIND_REPLAY_NET, "role": "net (модель)"},
            {"id": "record.book_apy_pp", "where": f"{RECORD_REL}: book_apy_pp", "kind": KIND_EXPECT_T0,
             "role": "expected (слово «net» носителем не объявлено, ADR-980)"},
        ),
        "digest_labels": ("Expected Net APY", "Net APY", "нетто", "чистая ставка"),
        "digest_value": None,
        "brief_key": None,
        "shelf_paths": (),
        "qualifier": ("единственный носитель слова «net» — реплей: у него net и gross по руке current "
                      "РАЗНОГО ЗНАКА (стоимость ходов начислена), и без определения это ровно "
                      "«неочевидная метрика» владельца"),
    },
    "Realized APY": {
        "carriers": (
            {"id": "snapshot.paper_apy_pct",
             "where": f"{SNAPSHOT_REL}: paper_apy_pct (= track_period.annualised_equivalent_pct)",
             "kind": KIND_REALIZED, "role": "realized (сайт)"},
            {"id": "digest.books.conservative",
             "where": "data сборщика: books_summary.books.conservative.annualized_apy_pct (+ _rate)",
             "kind": KIND_REALIZED, "role": "realized (отчёт)"},
        ),
        "digest_labels": ("год.",),
        "digest_value": ("books_summary", "books", "conservative", "annualized_apy_pct"),
        "digest_rate_dict": ("books_summary", "books", "conservative", "annualized_apy_pct_rate"),
        "brief_key": None,
        "shelf_paths": ("headline.apy", "books.conservative.apy"),
    },
    "7-day realized/estimated APY": {
        "carriers": (
            {"id": "digest.apy_7day_avg_pct", "where": "data сборщика: apy_7day_avg_pct (среднее apy_today семи баров)",
             "kind": KIND_SEVEN_MEAN, "role": "7-day (среднее начисленных)"},
        ),
        "components": {"id": "bars.7d_period_return", "where": f"{TRACK_REL}: daily[-7:] open/close",
                       "not_composed": "доходность за 7 дней NAV-отношением (realized за окно) не считает никто"},
        "digest_labels": ("среднее за 7 дн", "среднее за 7 дней"),
        "digest_value": "apy_7day_avg_pct",
        "brief_key": None,
        "shelf_paths": (),
        "qualifier": ("владелец спрашивает «realized/estimated» — ярлык отчёта не отвечает ни тем, ни другим; "
                      "по построению это среднее семи НАЧИСЛЕННЫХ дневных ставок, то есть realized, но "
                      "простой аннуализацией, а не доходность за окно"),
    },
    "Optimal policy-compliant APY": {
        "carriers": (
            {"id": "record.target_apy_pp", "where": f"{RECORD_REL}: target_apy_pp", "kind": KIND_LOWER_BOUND,
             "role": "optimal (нижняя граница)"},
        ),
        "digest_labels": ("Optimal", "оптимальн", "policy-compliant"),
        "digest_value": None,
        "brief_key": "optimal_apy_pp", "brief_carrier": "record.target_apy_pp",
        "shelf_paths": (),
        "qualifier": "нижняя граница объявленного оптимума (ADR-859/979) — родом в носителе не объявлена",
    },
}

#: Документация владельцу: §35 говорит «исправить ИЛИ документировать». Формула Paper APY
#: разобрана ADR-953 — это документ для агентов; доходит ли он до поверхности владельца,
#: судится отдельно.
DOC_REL = "docs/decisions/ADR-953-one-apy-name-many-economic-quantities.md"
DOC_MARKER = "ADR-953"


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


def _quantities_after(body: List[str]) -> Optional[List[str]]:
    """Величины владельца — непустые строки после «Owner должен четко видеть различие:» до
    строки-правила. HTML-комментарии карточки — не строки владельца."""
    start = next((i for i, ln in enumerate(body) if ln.strip() == OWNER_SEE_LINE), None)
    if start is None:
        return None
    out: List[str] = []
    for ln in body[start + 1:]:
        s = ln.strip()
        if s == OWNER_RULE_LINE or s == "⸻":
            break
        if not s or s.startswith("<!--"):
            continue
        out.append(s)
    return out


def owner_section_from_card(card_path: str) -> Dict[str, Any]:
    text, why = smc._read_text(card_path)
    if text is None:
        return {"measured": False, "reason": f"карточка не прочитана: {why}"}
    body, why = _section_lines(text.splitlines())
    if body is None:
        return {"measured": False, "reason": why}
    stripped = [ln.strip() for ln in body]
    return {"measured": True, "quantities": _quantities_after(body),
            "lead_present": OWNER_LEAD in stripped,
            "rule_present": OWNER_RULE_LINE in stripped}


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None, "order_tail_read": ORDER_G968_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    q = parsed.get("quantities")
    if q is None:
        mism.append(f"в разделе нет строки владельца {OWNER_SEE_LINE!r} — перечень не объявлен")
    elif list(q) != list(OWNER_QUANTITIES):
        mism.append(f"величины карточки {q} ≠ константам {list(OWNER_QUANTITIES)}")
    if not parsed.get("lead_present"):
        mism.append(f"в разделе нет строки {OWNER_LEAD!r}")
    if not parsed.get("rule_present"):
        mism.append(f"в разделе нет правила {OWNER_RULE_LINE!r}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if q is not None:
        out["order_undercount"] = {"quantities": len(q) - int(ORDER_G968_NAMED["quantities"])}
    return out


# ───────────────────────────── носители ──────────────────────────────────────

def load_carriers(data_dir: str, root: str = REPO_ROOT) -> Dict[str, Any]:
    """Лента решений и трек — дверью §30; реплей — свой; витрина и снимок — от корня дерева."""
    out = smc.load_carriers(data_dir)
    d = Path(data_dir)
    replay, why = smc._read_json(d / REPLAY_REL)
    out["replay"] = replay if isinstance(replay, dict) else None
    out["replay_reason"] = why if replay is None else (None if isinstance(replay, dict) else f"{REPLAY_REL} не словарь")
    for key, rel in (("shelf", SHELF_REL), ("snapshot", SNAPSHOT_REL)):
        doc, why = smc._read_json(Path(root) / rel)
        out[key] = doc if isinstance(doc, dict) else None
        out[f"{key}_reason"] = why if doc is None else (None if isinstance(doc, dict) else f"{rel} не словарь")
    out["doc_present"] = os.path.isfile(os.path.join(root, DOC_REL))
    out["data_dir"] = str(d)
    out["root"] = root
    return out


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _dig(doc: Any, path: Sequence[str]) -> Any:
    cur = doc
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _shelf_figure(shelf: Optional[dict], dotted: str) -> Optional[dict]:
    fig = _dig(shelf, dotted.split(".")) if shelf else None
    return fig if isinstance(fig, dict) else None


def _bar_shape(daily: Optional[List[dict]], key: str) -> Dict[str, Any]:
    """Три состояния поля по барам трека: число · None · ключа нет (инв. #17)."""
    rows = [b for b in (daily or []) if isinstance(b, dict)]
    numeric = sum(1 for b in rows if _num(b.get(key)))
    nulls = sum(1 for b in rows if key in b and b.get(key) is None)
    absent = sum(1 for b in rows if key not in b)
    third = ("наблюдён (None в барах отличим от значения)" if nulls else
             "только отсутствием ключа (None в барах не наблюдён)" if absent else
             "не наблюдён (все бары со значением — отличимость не доказана треком)")
    return {"rows": len(rows), "with_value": numeric, "null_rows": nulls, "absent_rows": absent,
            "third_outcome": third}


def carrier_values(carriers: Dict[str, Any], digest_data: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Значение и третий исход у КАЖДОГО объявленного носителя. Ничего не вычисляется."""
    recs = carriers.get("records") or []
    daily = carriers.get("daily") or []
    last_bar = daily[-1] if daily and isinstance(daily[-1], dict) else {}
    last_rec = recs[-1] if recs else {}
    replay = carriers.get("replay")
    snap = carriers.get("snapshot")
    out: Dict[str, Dict[str, Any]] = {}

    def put(cid: str, value: object, third: str, reason: Optional[str] = None) -> None:
        present = _num(value)
        out[cid] = {"value": value if present else None, "state": "produced" if present else "absent",
                    "third_outcome": third, "reason": reason}

    if not daily:
        why = f"трек {TRACK_REL} не прочитан/пуст: {carriers.get('daily_reason') or 'нет баров'}"
        out["bar.apy_today"] = {"value": None, "state": UNMEASURED, "third_outcome": None, "reason": why}
        out["bar.apy_expected_pct"] = dict(out["bar.apy_today"])
    else:
        put("bar.apy_today", last_bar.get("apy_today"), _bar_shape(daily, "apy_today")["third_outcome"],
            None if _num(last_bar.get("apy_today")) else "последний бар без apy_today")
        put("bar.apy_expected_pct", last_bar.get("apy_expected_pct"),
            _bar_shape(daily, "apy_expected_pct")["third_outcome"],
            None if _num(last_bar.get("apy_expected_pct")) else "последний бар без apy_expected_pct (ADR-301)")
    if not recs:
        why = f"лента решений {RECORD_REL} не прочитана/пуста: {carriers.get('records_reason') or 'нет строк'}"
        out["record.book_apy_pp"] = {"value": None, "state": UNMEASURED, "third_outcome": None, "reason": why}
        out["record.target_apy_pp"] = dict(out["record.book_apy_pp"])
    else:
        for cid, key in (("record.book_apy_pp", "book_apy_pp"), ("record.target_apy_pp", "target_apy_pp")):
            shape = drc._ledger_shape(recs, key)
            put(cid, last_rec.get(key), shape["third_outcome"],
                None if _num(last_rec.get(key)) else f"поле {key} в последней записи без значения")
    if replay is None:
        out["replay.net_current"] = {"value": None, "state": UNMEASURED, "third_outcome": None,
                                     "reason": f"реплей {REPLAY_REL} не прочитан: {carriers.get('replay_reason')}"}
    else:
        net = _dig(replay, ("comparison", "charged", "net_apy_pct", "current"))
        gross = _dig(replay, ("comparison", "charged", "gross_apy_pct", "current"))
        put("replay.net_current", net, "не применимо — одно число артефакта, не лента",
            None if _num(net) else "в реплее нет comparison.charged.net_apy_pct.current")
        out["replay.net_current"]["gross_current"] = gross if _num(gross) else None
    if snap is None:
        out["snapshot.paper_apy_pct"] = {"value": None, "state": UNMEASURED, "third_outcome": None,
                                         "reason": f"снимок {SNAPSHOT_REL} не прочитан: {carriers.get('snapshot_reason')}"}
    else:
        tp = snap.get("track_period") if isinstance(snap.get("track_period"), dict) else {}
        put("snapshot.paper_apy_pct", snap.get("paper_apy_pct"),
            f"состояние периода {tp.get('state')!r} — без MEASURED число обязано быть null",
            None if _num(snap.get("paper_apy_pct")) else "paper_apy_pct в снимке без значения")
    if digest_data is None:
        why = "отчёт не собран — data сборщика нет"
        out["digest.apy_7day_avg_pct"] = {"value": None, "state": UNMEASURED, "third_outcome": None, "reason": why}
        out["digest.books.conservative"] = dict(out["digest.apy_7day_avg_pct"])
    else:
        put("digest.apy_7day_avg_pct", digest_data.get("apy_7day_avg_pct"),
            "None у сборщика при <1 баре с apy_today (daily_telegram_report._seven_day_avg_apy)",
            None if _num(digest_data.get("apy_7day_avg_pct")) else "apy_7day_avg_pct у сборщика без значения")
        bk = _dig(digest_data, ("books_summary", "books", "conservative", "annualized_apy_pct"))
        put("digest.books.conservative", bk, "None у сборщика до 30 valid-дней (reportable=False)",
            None if _num(bk) else "annualized_apy_pct книги Conservative у сборщика без значения")
    return out


# ───────────────────────────── определение: оценка ───────────────────────────

_SEGMENT_STOPS: Tuple[str, ...] = (" · ", ";")
_PCT_VALUE_RE = re.compile(r"\d\s?%")


def _segment(line: str, label: str) -> str:
    """Отрезок строки, принадлежащий ЯРЛЫКУ: от ярлыка до ближайшего разделителя. Скобка после
    ярлыка — часть отрезка, если в ней СЛОВА («(начисленная за день, доход ÷ NAV)»), и чужая
    величина, если в ней число с процентом («(среднее за 7 дней: 4,00 %)»). Иначе слово соседней
    величины засчиталось бы определением этой."""
    low = line.lower()
    i = low.find(label.lower())
    if i < 0:
        return ""
    rest = line[i:]
    cut = len(rest)
    for stop in _SEGMENT_STOPS:
        j = rest.find(stop, len(label))
        if 0 <= j < cut:
            cut = j
    k = rest.find(" (", len(label))
    while 0 <= k < cut:
        close = rest.find(")", k)
        inner = rest[k + 2:close if close >= 0 else len(rest)]
        if _PCT_VALUE_RE.search(inner):
            cut = k
            break
        k = rest.find(" (", k + 2)
    return rest[:cut]


def grade_text(text: Optional[str], labels: Sequence[str]) -> Dict[str, Any]:
    """Оценка определения по ТЕКСТУ отчёта: отрезок строки от ярлыка до разделителя плюс
    продолжение «↳». Все строки с ярлыком величины возвращаются списком ``lines`` — по ним
    судится и коллизия слов."""
    if text is None:
        return {"grade": UNMEASURED, "label": None, "parts": {}, "lines": [], "reason": "текст отчёта не собран"}
    lines = text.splitlines()
    hits: List[Tuple[int, str]] = []
    for i, ln in enumerate(lines):
        low = ln.lower()
        for lab in labels:
            if lab.lower() in low:
                hits.append((i, lab))
                break
    if not hits:
        return {"grade": "absent", "label": None, "parts": {}, "lines": [],
                "reason": f"ни один ярлык {list(labels)} в отчёте не найден"}
    best: Optional[Dict[str, Any]] = None
    segments: List[str] = []
    rank = {"defined": 3, "partial": 2, "bare": 1}
    for i, lab in hits:
        chunk = _segment(lines[i], lab)
        for nxt in lines[i + 1:i + 3]:
            if nxt.strip().startswith("↳"):
                chunk += "\n" + nxt
        low = chunk.lower()
        parts = {"род": any(w in low for w in TEXT_KIND_WORDS),
                 "окно": any(w in low for w in TEXT_WINDOW_WORDS),
                 "метод": any(w in low for w in TEXT_METHOD_WORDS)}
        cand = {"grade": _grade(parts), "label": lab, "parts": parts, "line": lines[i].strip()[:200],
                "segment": chunk.strip()[:160]}
        segments.append(_segment(lines[i], lab).strip()[:160])
        if best is None or rank[cand["grade"]] > rank[best["grade"]]:
            best = cand
    assert best is not None
    best["lines"] = [lines[i].strip()[:200] for i, _ in hits]
    best["segments"] = segments
    return best


def grade_dict(fig: Optional[dict]) -> Dict[str, Any]:
    """Оценка определения по СЛОВАРЮ носителя (витрина / слой дашборда / data сборщика)."""
    if not isinstance(fig, dict):
        return {"grade": "absent", "parts": {}, "reason": "фигуры нет"}
    keys = set(fig)
    unit = str(fig.get("numbers_unit") or fig.get("unit") or "").lower()
    parts = {"род": bool(keys & set(DICT_KIND_KEYS)),
             "окно": bool(keys & set(DICT_WINDOW_KEYS)) or ("годов" in unit) or ("annual" in unit),
             "метод": bool(keys & set(DICT_METHOD_KEYS))}
    return {"grade": _grade(parts), "parts": parts, "keys": sorted(keys & (set(DICT_KIND_KEYS) | set(DICT_WINDOW_KEYS) | set(DICT_METHOD_KEYS)))}


def _grade(parts: Dict[str, bool]) -> str:
    if all(parts.get(p) for p in DEFINITION_PARTS):
        return "defined"
    if any(parts.get(p) for p in DEFINITION_PARTS):
        return "partial"
    return "bare"


# ───────────────────────────── поверхности ───────────────────────────────────

def measure_surfaces(spec: Dict[str, Any], values: Dict[str, Dict[str, Any]],
                     report_text: Optional[str], digest_data: Optional[Dict[str, Any]],
                     brief: Optional[Dict[str, Any]], shelf: Optional[dict]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    # — утренний отчёт: доходимость по ЯРЛЫКУ, совпадение числа — отдельным полем
    g = grade_text(report_text, spec["digest_labels"])
    dv = spec.get("digest_value")
    value = (_dig(digest_data, dv) if isinstance(dv, tuple) else (digest_data or {}).get(dv)) if (digest_data is not None and dv) else None
    value_in_text = None
    if report_text is not None and _num(value):
        value_in_text = drc.value_reaches(value, "rate", report_text)
        if value_in_text is not True and spec["digest_labels"] == ("год.",):
            # строка книг печатает ОДИН знак («~4.9% год.») — рендера с тремя значащими цифрами нет
            value_in_text = f"{float(value):.1f}% год." in report_text
    rate_dict = _dig(digest_data, spec["digest_rate_dict"]) if (digest_data is not None and spec.get("digest_rate_dict")) else None
    out["digest"] = {"reach": None if g["grade"] == UNMEASURED else g["grade"] != "absent",
                     "label": g.get("label"), "value": value if _num(value) else None,
                     "value_in_text": value_in_text, "definition": g,
                     "definition_in_data": grade_dict(rate_dict) if isinstance(rate_dict, dict) else None}
    sec = spec.get("digest_secondary")
    if sec:
        marker_present = None if report_text is None else (sec["label"].lower() in report_text.lower())
        sv = values.get(sec["carrier"], {}).get("value")
        coincides = None
        prim = out["digest"]["value"]
        if _num(sv) and _num(prim):
            coincides = abs(float(sv or 0.0) - float(prim or 0.0)) < 1e-9
        out["digest"]["secondary"] = {"label": sec["label"], "reach": marker_present, "value": sv,
                                      "coincides_with_primary": coincides, "when": sec["when"]}
    # — слой дашборда
    bk = spec.get("brief_key")
    if bk is None:
        out["brief"] = {"reach": False, "definition": {"grade": "absent", "parts": {}, "reason": "у величины нет ключа в слое дашборда"}}
    elif brief is None or not brief.get("available"):
        out["brief"] = {"reach": None, "definition": {"grade": UNMEASURED, "parts": {}, "reason": "слой дашборда не собран"}}
    else:
        bv = brief.get(bk)
        out["brief"] = {"reach": _num(bv), "value": bv if _num(bv) else None, "key": bk,
                        "definition": grade_dict(brief) if _num(bv) else {"grade": "absent", "parts": {}, "reason": f"{bk} без значения"}}
    # — витрина
    paths = spec.get("shelf_paths") or ()
    if not paths:
        out["shelf"] = {"reach": False, "definition": {"grade": "absent", "parts": {}, "reason": "у величины нет фигуры на витрине"}}
    elif shelf is None:
        out["shelf"] = {"reach": None, "definition": {"grade": UNMEASURED, "parts": {}, "reason": f"витрина {SHELF_REL} не прочитана"}}
    else:
        figs = {p: _shelf_figure(shelf, p) for p in paths}
        first = next((f for f in figs.values() if f is not None), None)
        out["shelf"] = {"reach": first is not None and _num(first.get("value")),
                        "value": first.get("value") if first and _num(first.get("value")) else None,
                        "paths": [p for p, f in figs.items() if f is not None],
                        "definition": grade_dict(first) if first else {"grade": "absent", "parts": {}, "reason": f"фигур {list(paths)} на витрине нет"},
                        "measured_at": shelf.get("measured_at"), "published_at": shelf.get("published_at")}
    return out


def best_grade(surfaces: Dict[str, Any]) -> str:
    order = ("defined", "partial", "bare")
    grades = [s.get("definition", {}).get("grade") for s in surfaces.values()]
    for g in order:
        if g in grades:
            return g
    if UNMEASURED in grades and not any(s.get("reach") for s in surfaces.values()):
        return UNMEASURED
    return "absent"


# ───────────────────────────── величины ──────────────────────────────────────

def measure_quantities(carriers: Dict[str, Any], report_text: Optional[str],
                       digest_data: Optional[Dict[str, Any]], brief: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    values = carrier_values(carriers, digest_data)
    shelf = carriers.get("shelf")
    out: Dict[str, Any] = {}
    for name in OWNER_QUANTITIES:
        spec = QUANTITY_SPEC[name]
        cs = []
        for c in spec["carriers"]:
            v = values.get(c["id"], {"state": UNMEASURED, "reason": "носитель не объявлен в carrier_values"})
            cs.append({**c, **v})
        states = [c["state"] for c in cs]
        if any(s == "produced" for s in states):
            kind = "produced"
        elif all(s == UNMEASURED for s in states):
            kind = UNMEASURED
        else:
            kind = "components_only" if spec.get("components") else "absent"
        surfaces = measure_surfaces(spec, values, report_text, digest_data, brief, shelf)
        reach = [s for s in SURFACES if surfaces[s].get("reach") is True]
        out[name] = {"kind": kind, "carriers": cs, "surfaces": surfaces, "reach_surfaces": reach,
                     "definition_grade": best_grade(surfaces), "qualifier": spec.get("qualifier"),
                     "components": spec.get("components")}
    return {"quantities": out, "values": values,
            "declared": OWNER_QUANTITIES_DECLARED,
            "produced": sum(1 for q in out.values() if q["kind"] == "produced"),
            "on_owner_surface": sum(1 for q in out.values() if q["reach_surfaces"]),
            "defined": sum(1 for q in out.values() if q["definition_grade"] == "defined"),
            "report_built": report_text is not None}


# ───────────────────────────── различимость ──────────────────────────────────

def measure_distinctness(measured: Dict[str, Any], shelf: Optional[dict]) -> Dict[str, Any]:
    qs = measured["quantities"]
    # — одно слово, две величины
    collisions: Dict[str, Dict[str, Any]] = {}
    for word in COLLISION_WORDS:
        bearers: Dict[str, Dict[str, Any]] = {}

        def bear(name: str, surface: str, text: str, value: object) -> None:
            b = bearers.setdefault(name, {"surfaces": [], "texts": [], "values": {}})
            if surface not in b["surfaces"]:
                b["surfaces"].append(surface)
                b["texts"].append(f"{surface}: {text}"[:160])
                b["values"][surface] = value

        for name, q in qs.items():
            d = q["surfaces"]["digest"]
            # судится ОТРЕЗОК ярлыка, не вся строка: «APY (paper)» в строке, где рядом стои́т
            # «среднее за 7 дней», — чужое слово для 7-дневной величины
            for seg in (d.get("definition") or {}).get("segments") or []:
                if d.get("reach") and word in str(seg).lower():
                    bear(name, "digest", str(seg), d.get("value"))
                    break
            sh = q["surfaces"]["shelf"]
            if sh.get("reach") and shelf is not None:
                for p in sh.get("paths") or []:
                    fig = _shelf_figure(shelf, p) or {}
                    blob = " ".join(str(fig.get(k, "")) for k in ("source", "evidence", "metric_type")).lower()
                    if word in blob:
                        bear(name, "shelf", f"{p}: {fig.get('source', '')}", fig.get("value"))
                        break
        collisions[word] = {"bearers": bearers, "collides": len(bearers) > 1}
    # — одна величина, два числа на двух поверхностях
    divergences: Dict[str, Dict[str, Any]] = {}
    for name, q in qs.items():
        vals = {s: q["surfaces"][s].get("value") for s in SURFACES if _num(q["surfaces"][s].get("value"))}
        if len(vals) >= 2:
            lo, hi = min(vals.values()), max(vals.values())
            spread = round(float(hi) - float(lo), 6)
            explained = any(q["surfaces"][s].get("definition", {}).get("grade") == "defined" for s in vals)
            divergences[name] = {"values": vals, "spread_pp": spread,
                                 "diverges": spread > DIVERGENCE_TOLERANCE_PP, "explained_by_definition": explained}
    # — displayed и weighted совпадают сегодня
    cur = qs.get("Current displayed weighted APY", {})
    sec = (cur.get("surfaces") or {}).get("digest", {}).get("secondary") or {}
    return {"collisions": collisions, "divergences": divergences,
            "displayed_weighted_coincide": sec.get("coincides_with_primary"),
            "weighted_reaches_digest": sec.get("reach")}


# ───────────────────────────── свежесть ──────────────────────────────────────

def freshness_of(carriers: Dict[str, Any], slo: Dict[str, Optional[float]], now: dt.datetime) -> Dict[str, Any]:
    recs = carriers.get("records") or []
    replay = carriers.get("replay") or {}
    snap = carriers.get("snapshot") or {}
    out = {"record": ecc.freshness(recs[-1].get("generated_at") if recs else None, RECORD_REL, slo, now),
           "replay": ecc.freshness(replay.get("generated_at"), REPLAY_REL, slo, now),
           "snapshot": ecc.freshness(snap.get("generated_at"), f"../{SNAPSHOT_REL}", slo, now)}
    shelf = carriers.get("shelf") or {}
    out["shelf"] = {"measured_at": shelf.get("measured_at"), "published_at": shelf.get("published_at"),
                    "cadence": shelf.get("cadence")}
    return out


# ───────────────────────────── находки ───────────────────────────────────────

def _bearer_text(b: Dict[str, Any]) -> str:
    return ", ".join(f"{sf}: {b['values'].get(sf)}" for sf in b.get("surfaces") or [])


def _findings(parity_r: Dict[str, Any], measured: Dict[str, Any], distinct: Dict[str, Any],
              fresh: Dict[str, Any], carriers: Dict[str, Any], report_reason: Optional[str],
              brief_reason: Optional[str], report_text: Optional[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
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
    if carriers.get("shelf") is None:
        unmeasured.append(f"витрина {SHELF_REL} не прочитана: {carriers.get('shelf_reason')}")

    qs = measured["quantities"]
    measured_any = any(q["kind"] != UNMEASURED for q in qs.values())
    for name, q in qs.items():
        if q["kind"] == UNMEASURED:
            unmeasured.append(f"величина «{name}»: " + "; ".join(str(c.get("reason")) for c in q["carriers"]))
            continue
        kinds = "; ".join(f"{c['id']} = {c.get('value')} ({c['kind']})" for c in q["carriers"] if c["state"] == "produced")
        if q["kind"] == "absent":
            add("CRITICAL", f"quantity_absent:{name}", f"«{name}»: ни один объявленный носитель не несёт значения")
            continue
        grade = q["definition_grade"]
        reach = q["reach_surfaces"]
        if not reach and grade == UNMEASURED:
            unmeasured.append(f"величина «{name}»: поверхности владельца не собраны — доходимость не измерена")
            continue
        if not reach:
            add("CRITICAL", f"quantity_not_on_owner_surface:{name}",
                f"«{name}»: производитель есть ({kinds}), ни одна поверхность владельца (отчёт · дашборд · витрина) "
                f"её под этим именем не несёт")
        elif grade != "defined":
            where = ", ".join(f"{s}: {q['surfaces'][s]['definition'].get('grade')} "
                              f"(нет: {[p for p, ok in (q['surfaces'][s]['definition'].get('parts') or {}).items() if not ok]})"
                              for s in reach)
            add("CRITICAL", f"quantity_without_definition:{name}",
                f"«{name}» доходит до владельца ({where}) БЕЗ понятного определения — правило §35 нарушено; "
                f"род числа: {kinds}")
        else:
            defined_on = [s for s in reach if q["surfaces"][s]["definition"].get("grade") == "defined"]
            add("INFO", f"quantity_defined:{name}",
                f"«{name}»: определение (род · окно · метод) есть на {defined_on}; носители: {kinds}")
        dig = q["surfaces"]["digest"]
        dd = dig.get("definition_in_data")
        if dig.get("reach") and dd and dd.get("grade") == "defined" and dig["definition"].get("grade") != "defined":
            add("WARN", f"definition_dropped_by_renderer:{name}",
                f"«{name}»: data сборщика несёт полное определение ({dd.get('keys')}), текст отчёта печатает "
                f"«{dig['definition'].get('line')}» — форма ADR-488: определение теряется в слое отображения")
        if q.get("qualifier"):
            add("WARN", f"quantity_qualifier:{name}", f"«{name}»: {q['qualifier']}")
        comp = q.get("components")
        if comp:
            add("WARN", f"quantity_components_only:{name}", f"«{name}»: {comp['where']} — {comp['not_composed']}")
        rep = next((c for c in q["carriers"] if c["id"] == "replay.net_current" and c["state"] == "produced"), None)
        if rep and _num(rep.get("gross_current")) and _num(rep.get("value")) \
                and (float(rep["value"] or 0.0) < 0) != (float(rep["gross_current"] or 0.0) < 0):
            add("WARN", "expected_net_sign_differs_from_gross",
                f"реплей: net {rep['value']} % против gross {rep['gross_current']} % по руке current — знаки разные; "
                f"без определения («стоимость ходов начислена») владелец прочёл бы это как убыточную книгу")

    for word, c in distinct["collisions"].items():
        if c["collides"]:
            add("CRITICAL", f"one_word_two_quantities:{word}",
                f"слово «{word}» носит {len(c['bearers'])} величины: " +
                "; ".join(f"«{n}» ({_bearer_text(b)})" for n, b in c["bearers"].items()))
        elif measured_any and report_text is not None:
            add("INFO", f"one_word_one_quantity:{word}",
                f"слово «{word}» на поверхностях владельца носит {len(c['bearers'])} величину")
    for name, d in distinct["divergences"].items():
        if d["diverges"] and not d["explained_by_definition"]:
            add("WARN", f"one_quantity_two_values:{name}",
                f"«{name}»: {d['values']} — разброс {d['spread_pp']} pp между поверхностями, и ни одна не "
                f"объясняет, почему числа разные")
        elif d["diverges"]:
            add("INFO", f"one_quantity_two_values_explained:{name}",
                f"«{name}»: {d['values']} — разброс {d['spread_pp']} pp объяснён определением (такт публикации)")
    if distinct.get("displayed_weighted_coincide") is True and distinct.get("weighted_reaches_digest") is False:
        add("INFO", "displayed_and_weighted_coincide_today",
            "displayed (apy_today) и weighted (apy_expected_pct) сегодня равны — ненаблюдаемых пулов нет; "
            "взвешенная до отчёта не доходит и различима только когда ADR-298 обнуляет ставку")

    if measured_any:
        if carriers.get("doc_present") is False:
            add("WARN", "formula_documentation_missing", f"документ формулы Paper APY ({DOC_REL}) в дереве не найден")
        elif report_text is not None and DOC_MARKER not in report_text:
            add("WARN", "formula_documented_for_agents_only",
                f"формула Paper APY документирована ({DOC_REL}), но ни одна поверхность владельца на неё не ссылается")

    for key, label in (("record", f"лента решений {RECORD_REL}"), ("replay", f"реплей {REPLAY_REL}")):
        fr = fresh.get(key) or {}
        if fr.get("fresh") is False:
            add("WARN", f"stale:{key}", f"{label}: {fr['age_hours']} ч при SLO {fr['slo_hours']} ч (отметка {fr['stamp']})")
        elif fr.get("fresh") is None:
            unmeasured.append(f"свежесть «{label}»: {fr.get('reason')}")
    if measured_any and measured["report_built"]:
        rest = [n for n, q in qs.items() if q["kind"] != UNMEASURED and q["definition_grade"] != "defined"]
        if rest:
            add("CRITICAL", "quantities_declared_vs_defined",
                f"объявлено {OWNER_QUANTITIES_DECLARED} величин, производится {measured['produced']}, на поверхности "
                f"владельца {measured['on_owner_surface']}, с определением {measured['defined']}; без определения: "
                + ", ".join(f"«{n}»→{qs[n]['definition_grade']}" for n in rest))
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

def run(root: str = REPO_ROOT, data_dir: Optional[str] = None,
        card_path: Optional[str] = None, write: bool = True,
        now: Optional[dt.datetime] = None,
        reader: Optional[drc.ReportReader] = None) -> Dict[str, Any]:
    """Полный замер §35. Только ЧИТАЕТ; ``applied=False``. ``reader`` — сборщик отчёта
    (вход; по умолчанию живой ``build_digest_messages`` с ``drain=False``)."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    read = reader or drc.live_report_reader

    parity_r = parity(card_path)
    carriers = load_carriers(data_dir, root)
    slo = ecc.load_slo(root)
    headline, details, data, report_reason = read(data_dir, stamped)
    report_text = None if headline is None and details is None else f"{headline or ''}\n{details or ''}"
    brief, brief_reason = drc.brief_for(carriers.get("records") or []) if carriers.get("records") else (None, None)
    measured = measure_quantities(carriers, report_text, data, brief)
    distinct = measure_distinctness(measured, carriers.get("shelf"))
    fresh = freshness_of(carriers, slo, stamped)
    findings, unmeasured = _findings(parity_r, measured, distinct, fresh, carriers, report_reason, brief_reason, report_text)
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
        "schema": "paper_apy_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §35 ТЗ «Portfolio CIO» (Paper APY cleanup). Ни одной ставки не "
                     "вычисляет, отчёт не отправляет (drain=False), витрину, запись и трек не трогает; карточку "
                     "владельцу не заводит — определение рядом с числом есть advisory-слой, работа агента. "
                     "Доходимость в отчёте судится ЯРЛЫКОМ величины, совпадение числа печатается отдельно: "
                     "displayed и weighted равны в день без ненаблюдаемых пулов, и число нашлось бы у обеих"),
        "overall": overall,
        "counts": counts,
        "declared": {"quantities": list(OWNER_QUANTITIES), "quantities_declared": OWNER_QUANTITIES_DECLARED,
                     "surfaces": list(SURFACES), "definition_parts": list(DEFINITION_PARTS), "grades": list(GRADES),
                     "collision_words": list(COLLISION_WORDS), "divergence_tolerance_pp": DIVERGENCE_TOLERANCE_PP,
                     "order_g968_named": dict(ORDER_G968_NAMED),
                     "report_reader": "spa_core.telegram.reports.daily.build_digest_messages (drain=False)",
                     "dashboard_reader": "spa_core.paper_trading.cio_brief.brief_from_history",
                     "shelf": SHELF_REL, "slo_source": MANIFEST_REL, "formula_doc": DOC_REL},
        "parity": parity_r,
        "measured": measured,
        "distinctness": distinct,
        "freshness": fresh,
        "report": {"built": report_text is not None, "reason": report_reason,
                   "headline_chars": len(headline) if headline else None,
                   "details_chars": len(details) if details else None},
        "carriers_read": {k: (carriers.get(k) is not None)
                          for k in ("records", "daily", "replay", "shelf", "snapshot")},
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
    print(f"§35 ТЗ «Portfolio CIO» (Paper APY cleanup): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (величин {OWNER_QUANTITIES_DECLARED}, строка «исправить или "
              f"документировать», правило «без понятного определения»; заказ G968 назвал {ORDER_G968_NAMED['quantities']} — "
              f"сдвиг {p.get('order_undercount')})")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    m = doc["measured"]
    rep = doc["report"]
    print(f"   отчёт владельцу собран: {rep.get('built')} (заголовок {rep.get('headline_chars')} зн., подробности "
          f"{rep.get('details_chars')} зн.)")
    print(f"   величин объявлено {m['declared']}, производится {m['produced']}, на поверхности владельца "
          f"{m['on_owner_surface']}, с определением {m['defined']}")
    for name, q in m["quantities"].items():
        vals = "; ".join(f"{cc['id']}={cc.get('value')}" for cc in q["carriers"])
        grades = ", ".join(f"{s}:{q['surfaces'][s]['definition'].get('grade')}" for s in SURFACES)
        print(f"      «{name}»: {q['kind']} — {vals}; поверхности [{grades}]; определение: {q['definition_grade']}")
    d = doc["distinctness"]
    for w, cc in d["collisions"].items():
        print(f"   слово «{w}»: {'КОЛЛИЗИЯ' if cc['collides'] else 'одна величина'} — {list(cc['bearers'])}")
    for n, dv in d["divergences"].items():
        print(f"   «{n}»: два числа {dv['values']} разброс {dv['spread_pp']} pp, объяснён: {dv['explained_by_definition']}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


parse_now = smc.parse_now


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§35 ТЗ «Portfolio CIO»: у КАЖДОЙ из пяти величин владельца есть ли производитель с родом, "
                    "определение на поверхности владельца и различимость")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого состояния (из worktree его НЕТ по построению — передавать прод-дерево)")
    ap.add_argument("--card", default=None, help="карточка приказа владельца")
    ap.add_argument("--now", default=None, help="момент замера ISO-8601 (вход, не часы)")
    ap.add_argument("--no-write", action="store_true")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    now, why = parse_now(ns.now)
    if why:
        print(f"НЕ ИЗМЕРЕНО: {why}")
        return 2
    doc = run(root=ns.root, data_dir=ns.data_dir, card_path=ns.card, write=not ns.no_write, now=now)
    _print(doc)
    if doc["overall"] in ("CRITICAL", "WARNING"):
        return 1
    if doc["overall"] == "UNCHECKED":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
