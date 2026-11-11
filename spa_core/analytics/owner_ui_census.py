"""owner_ui_census.py — §36 ТЗ «Portfolio CIO»: «Owner UI».

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §36::

    Owner UI
    Следовать owner-first принципу.
    Owner не должен видеть: optimizer internals · JSON · policy hashes · technical IDs ·
    implementation paths · internal states — на основном экране.
    Основной вывод: Текущая доходность · Потенциальная доходность · Есть ли проблема ·
    Что система предлагает сделать · Сколько это даст · Сколько стоит · Когда окупится ·
    Изменится ли риск · Нужна ли моя реакция
    Technical details скрыть в: Подробнее

Запрещённых классов **ШЕСТЬ**, выводов основного экрана **ДЕВЯТЬ**, место для технических
подробностей — ОДНО («Подробнее»). Прибор сверяет все три перечня и обе границы раздела с
карточкой (`parity`).

Предмет — «на ОСНОВНОМ экране владельца нет ни одного запрещённого класса и есть КАЖДЫЙ из
девяти выводов», а не «есть ли дашборд». Основной экран — то, что владелец получает САМ, не
открывая ничего: ПЕРВОЕ сообщение утреннего дайджеста (`com.spa.digest_daily`, ADR-980 § 2);
второе сообщение дайджест сам объявляет «Подробности — следующим сообщением» — это и есть
«Подробнее» владельца, технические подробности там РАЗРЕШЕНЫ. Третья поверхность — слой
дашборда (`cio_brief.brief_from_history` → `/api/live/books/brief` → `portfolio-summary.astro`,
ADR-488): у него судятся только те ключи, которые страница РЕНДЕРИТ (читается сама страница),
остальные поля полезной нагрузки (`decision_id`, `policy_version`, `mode`) названы как
«несёт, но не показывает» — INFO, не находка.

Как судится запрещённый класс
=============================
Каждому классу владельца соответствует ДЕТЕКТОР формы (регулярное выражение либо замкнутый
словарь), детекторы применяются в объявленном порядке и МАСКИРУЮТ найденное — один отрезок
текста попадает ровно в один класс:

* ``implementation paths`` — пути репозитория и имена файлов (`spa_core/…`, `data/x.json`,
  `*.py`), точечные модули `spa_core.a.b`;
* ``JSON`` — литерал объекта/массива (`{"k": …`, `"k": [`);
* ``policy hashes`` — шестнадцатеричная строка ≥7 знаков с буквой (sha/отпечаток), слово
  `policy_version`/`hash`;
* ``optimizer internals`` — коды причин оптимизатора (`gain_below_band:0.104pp<0.500pp`),
  имена полей записи решения (`book_apy_pp`, `target_apy_pp`, …), словарь поиска (`tuner`,
  `optimum`, `eligible`, `trim`);
* ``technical IDs`` — UUID, `cycle-NNN`, `pidNNN`, метки launchd `com.spa.*`, форма
  `decision_id`, коды правил (`ECON-10`, `DL-03`, `ADR-980`), snake_case-идентификаторы
  (`compound_v3`, `site_freshness`);
* ``internal states`` — ЗНАЧЕНИЯ перечислений (`HOLD`, `ALL_CASH`, `SOFT_DERISK`, `CRITICAL`,
  `VIOLATION` …); слова ВЛАДЕЛЬЦА из §34 (`REBALANCE` / `KEEP`) состоянием не считаются.

Форма — не смысл: детектор ошибается в сторону НАХОДКИ (RU-слово с подчёркиванием он назовёт
идентификатором), и каждая находка печатается с отрезком, чтобы её можно было оспорить
глазами. Пустой основной экран ≠ «чисто» — без собранного отчёта класс НЕ ИЗМЕРЕН.

Как судится вывод владельца
===========================
У каждого из девяти выводов три оси (тот же порядок, что у §34, ADR-980): ПРОИЗВОДИТЕЛЬ
(поле носителя с третьим исходом), ЧИТАТЕЛЬ-ВЛАДЕЛЕЦ (ДОХОДИТ ли на основной экран:
число — РЕНДЕРОМ с ≥3 значащими цифрами, ответ «да/нет/что делать» — ФРАЗОЙ из замкнутого
словаря владельца, не внутренним словом) и доходимость до «Подробнее» и до дашборда отдельно.

Что прибор НЕ делает
====================
Только ЧИТАЕТ (``applied=False``): отчёт не отправляет (``drain=False``), запись, дайджест,
витрину и страницу не правит ни байтом, выводы владельца не ВЫЧИСЛЯЕТ (третье место для
чисел, `.claude/rules/site-numbers.md`). Карточку владельцу не заводит: форма основного
экрана — advisory-слой, работа агента. Контрапункты ВВЕЗЕНЫ, не перемерены: что доходит до
отчёта (ADR-980), определения на поверхности (ADR-981), слой отображения (ADR-488/808).
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
REPORT_REL = "data/owner_ui_census.json"
CARD_REL = smc.CARD_REL
MANIFEST_REL = ecc.MANIFEST_REL

# ───────────────────────────── объявление владельца (константы) ───────────────

SECTION_HEAD = "36. Owner UI"
NEXT_SECTION_HEAD = "37. Testing scenarios"
OWNER_PRINCIPLE_LINE = "Следовать owner-first принципу."
OWNER_FORBIDDEN_LEAD = "Owner не должен видеть:"
OWNER_FORBIDDEN_TAIL = "на основном экране."
OWNER_OUTPUTS_LEAD = "Основной вывод:"
OWNER_HIDE_LEAD = "Technical details скрыть в:"
OWNER_HIDE_WORD = "Подробнее"

FORBIDDEN_CLASSES: Tuple[str, ...] = (
    "optimizer internals",
    "JSON",
    "policy hashes",
    "technical IDs",
    "implementation paths",
    "internal states",
)
FORBIDDEN_CLASSES_DECLARED = 6

OWNER_OUTPUTS: Tuple[str, ...] = (
    "Текущая доходность",
    "Потенциальная доходность",
    "Есть ли проблема",
    "Что система предлагает сделать",
    "Сколько это даст",
    "Сколько стоит",
    "Когда окупится",
    "Изменится ли риск",
    "Нужна ли моя реакция",
)
OWNER_OUTPUTS_DECLARED = 9

#: Заказ G969 п. 1 назвал предмет и границы (`sed -n '1000,1040p'`, вторая граница — §37),
#: чисел не называл — сдвиг не применим, и это печатается отдельно от «назвал верно».
ORDER_G969_NAMED: Dict[str, Any] = {"classes": None, "outputs": None, "tail_read": True}

#: Поверхности владельца. ОСНОВНОЙ экран — первое сообщение дайджеста; «Подробнее» — второе
#: (дайджест сам объявляет его подвалом заголовка); дашборд — слой `cio_brief`, судятся только
#: ключи, которые страница рендерит.
SURFACE_MAIN = "main_screen"
SURFACE_DETAILS = "details"
SURFACE_DASHBOARD = "dashboard_brief"
SURFACES: Tuple[str, ...] = (SURFACE_MAIN, SURFACE_DETAILS, SURFACE_DASHBOARD)
HEADLINE_FOOTER_WORDS = "Подробности — следующим сообщением"
DASHBOARD_PAGE_REL = "landing/src/pages/admin/portfolio-summary.astro"
DASHBOARD_BRIEF_VAR = "br"      # так страница зовёт полезную нагрузку /api/live/books/brief

OUTPUT_KINDS: Tuple[str, ...] = ("produced", "components_only", "absent", UNMEASURED)
PRODUCED_KINDS: Tuple[str, ...] = ("produced",)

#: Носители.
RECORD_REL = smc.RECORD_REL
TRACK_REL = smc.TRACK_REL
SYSTEM_HEALTH_REL = "system_health.json"
MIN_SIGNIFICANT_DIGITS = drc.MIN_SIGNIFICANT_DIGITS

# ───────────────────────────── детекторы запрещённых классов ─────────────────

#: Слова владельца из §34 — вердикты ЕГО словаря; в STATE_WORDS их быть не может (батарея).
OWNER_DECISION_WORDS: Tuple[str, ...] = drc.OWNER_DECISION_WORDS

#: Имена полей записи решения — язык оптимизатора, не владельца (ADR-974, писатель §30).
OPTIMIZER_FIELDS: Tuple[str, ...] = (
    "book_apy_pp", "target_apy_pp", "gain_pp", "required_gain_pp", "payback_days",
    "turnover_frac", "turnover_usd", "cost_usd", "capital_usd", "admissible_trim",
    "apy_unevidenced", "apy_evidenced_pct", "target_positions", "current_positions",
    "trim_optimum", "search_kind", "optimal_is_lower_bound", "yield_gap_pp", "optimal_apy_pp",
    "current_apy_pp",
)
#: Словарь поиска/тюнера — внутренности оптимизатора, встречаются и внутри RU-слов («eligible-набора»).
OPTIMIZER_WORDS: Tuple[str, ...] = ("tuner", "optimum", "eligible", "candidate", "trim")

#: Значения перечислений, которые владелец видеть не должен; `OK` намеренно не включён —
#: «ok» в прозе владельца не состояние, а слово.
STATE_WORDS: Tuple[str, ...] = (
    "HOLD", "ACT", "ALL_CASH", "SOFT_DERISK", "HARD_KILL", "NOT_READY", "VIOLATION",
    "UNCHECKED", "UNMEASURED", "CRITICAL", "WARNING", "DEGRADED", "FAIL", "YELLOW", "RED",
    "GREEN", "PAUSE", "BLOCK", "REFUSED",
)

_RE_PATH = re.compile(
    r"(?:/Users/|/private/|/tmp/|\bspa_core/|\bscripts/|\blanding/|\bdocs/|\bdata/|\barchitecture/)[\w./\-]+"
    r"|\b[\w\-]+\.(?:py|json|jsonl|md|astro|js|ts|yml|yaml|sh|plist)\b"
    r"|\bspa_core(?:\.[a-z_][a-z0-9_]*)+\b")
_RE_JSON = re.compile(r"[{\[]\s*\"[^\"\n]+\"\s*:|\"[A-Za-z_][\w]*\"\s*:\s*[\[{\"\d\-tfn]")
_RE_HASH = re.compile(r"(?<![\w-])(?=[0-9a-f]*[a-f])[0-9a-f]{7,64}(?![\w-])|\bpolicy_version\b|\bhash(?:es)?\b",
                      re.IGNORECASE)
_RE_REASON_CODE = re.compile(r"\b[a-z]+(?:_[a-z]+)+:[-+]?\d[\d.]*(?:pp|d|%|h)?(?:[<>≤≥][-+]?\d[\d.]*(?:pp|d|%|h)?)?")
_RE_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_RE_TECH_ID = re.compile(
    r"\bcycle-\d+(?:-pid\d+)?\b|\bpid\d+\b|\bcom\.spa\.[a-z0-9_]+\b|\borchestrator-\d+-[0-9A-F]{8,}\b"
    r"|\b[a-z0-9]+-shadow-\d{4}-\d{2}-\d{2}\b|\b[A-Z]{2,6}-\d{2,4}\b")
_RE_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_RE_UPPER_SNAKE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def _mask(text: str, spans: List[Tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def _collect(pattern: "re.Pattern[str]", text: str, keep=lambda _m: True) -> List[Tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in pattern.finditer(text) if keep(m)]


def _word_hits(words: Sequence[str], text: str, *, flags: int = 0) -> List[Tuple[int, int, str]]:
    out: List[Tuple[int, int, str]] = []
    for w in words:
        for m in re.finditer(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text, flags):
            out.append((m.start(), m.end(), m.group(0)))
    return out


def detect_classes(text: Optional[str]) -> Dict[str, Any]:
    """Запрещённые классы владельца в тексте: класс → список отрезков. Детекторы идут в
    объявленном порядке и маскируют найденное, поэтому один отрезок — ровно один класс.
    ``None``-текст ⇒ ``measured=False`` (пустой экран не есть чистый экран)."""
    if text is None:
        return {"measured": False, "hits": {c: [] for c in FORBIDDEN_CLASSES}, "total": None}
    work = text
    hits: Dict[str, List[str]] = {c: [] for c in FORBIDDEN_CLASSES}

    def take(cls: str, found: List[Tuple[int, int, str]]) -> None:
        nonlocal work
        if not found:
            return
        hits[cls].extend(tok for _, _, tok in found)
        work = _mask(work, [(a, b) for a, b, _ in found])

    take("implementation paths", _collect(_RE_PATH, work))
    take("JSON", _collect(_RE_JSON, work))
    take("policy hashes", _collect(_RE_HASH, work))
    take("optimizer internals", _collect(_RE_REASON_CODE, work))
    take("optimizer internals", _word_hits(OPTIMIZER_FIELDS, work))
    take("optimizer internals", _word_hits(OPTIMIZER_WORDS, work, flags=re.IGNORECASE))
    take("technical IDs", _collect(_RE_UUID, work))
    take("technical IDs", _collect(_RE_TECH_ID, work))
    take("technical IDs", _collect(_RE_SNAKE, work))
    # Слова владельца (REBALANCE / KEEP) состоянием не являются ПО ПОСТРОЕНИЮ словаря: их нет
    # в STATE_WORDS, и подчёркивания у них нет — сторож этого свойства живёт в батарее
    # (мутация «KEEP в STATE_WORDS» краснит её), а не в фильтре здесь: фильтр без сцены,
    # которая его различала бы, пережил мутацию SMC-982 M09 и снят как мёртвый код.
    take("internal states", _collect(_RE_UPPER_SNAKE, work))
    take("internal states", _word_hits(STATE_WORDS, work))
    uniq = {c: sorted(set(v)) for c, v in hits.items()}
    return {"measured": True, "hits": uniq, "total": sum(len(v) for v in uniq.values()),
            "classes_present": [c for c in FORBIDDEN_CLASSES if uniq[c]]}


# ───────────────────────────── паритет с карточкой ────────────────────────────

def _section_lines(lines: List[str]) -> Tuple[Optional[List[str]], Optional[str]]:
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD), None)
    if start is None:
        return None, f"в карточке не найден заголовок {SECTION_HEAD!r}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == NEXT_SECTION_HEAD), None)
    if end is None:
        return None, (f"найден {SECTION_HEAD!r}, но НЕ найдена вторая граница {NEXT_SECTION_HEAD!r} — "
                      f"перечни не ограничены, и счёт по ним был бы счётом неизвестно чего")
    return lines[start + 1:end], None


def _between(stripped: List[str], lead: str, tail_pred) -> Optional[List[str]]:
    """Непустые строки после ``lead`` до первой строки, для которой ``tail_pred`` истинен.
    HTML-комментарии карточки — не строки владельца."""
    start = next((i for i, s in enumerate(stripped) if s == lead), None)
    if start is None:
        return None
    out: List[str] = []
    for s in stripped[start + 1:]:
        if tail_pred(s):
            break
        if not s or s.startswith("<!--") or s == "⸻":
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
    forbidden = _between(stripped, OWNER_FORBIDDEN_LEAD, lambda s: s == OWNER_FORBIDDEN_TAIL)
    outputs = _between(stripped, OWNER_OUTPUTS_LEAD, lambda s: s == OWNER_HIDE_LEAD)
    hide = _between(stripped, OWNER_HIDE_LEAD, lambda _s: False)
    return {"measured": True,
            "principle_present": OWNER_PRINCIPLE_LINE in stripped,
            "forbidden_tail_present": OWNER_FORBIDDEN_TAIL in stripped,
            "forbidden": forbidden, "outputs": outputs, "hide_in": hide}


def parity(card_path: str) -> Dict[str, Any]:
    parsed = owner_section_from_card(card_path)
    out: Dict[str, Any] = {"parsed": parsed, "agrees": None, "mismatches": [],
                           "order_undercount": None, "order_tail_read": ORDER_G969_NAMED["tail_read"]}
    if not parsed.get("measured"):
        return out
    mism: List[str] = []
    fb, outs, hide = parsed.get("forbidden"), parsed.get("outputs"), parsed.get("hide_in")
    if fb is None:
        mism.append(f"в разделе нет строки владельца {OWNER_FORBIDDEN_LEAD!r} — запрещённые классы не прочитаны")
    elif list(fb) != list(FORBIDDEN_CLASSES):
        mism.append(f"запрещённые классы карточки {fb} ≠ константам {list(FORBIDDEN_CLASSES)}")
    if not parsed.get("forbidden_tail_present"):
        mism.append(f"в разделе нет слов владельца {OWNER_FORBIDDEN_TAIL!r} — запрет относится к ОСНОВНОМУ "
                    f"экрану, без этой строки предмет не ограничен")
    if outs is None:
        mism.append(f"в разделе нет строки владельца {OWNER_OUTPUTS_LEAD!r} — выводы не прочитаны")
    elif list(outs) != list(OWNER_OUTPUTS):
        mism.append(f"выводы основного экрана {outs} ≠ константам {list(OWNER_OUTPUTS)}")
    if hide is None:
        mism.append(f"в разделе нет строки владельца {OWNER_HIDE_LEAD!r}")
    elif list(hide) != [OWNER_HIDE_WORD]:
        mism.append(f"место для технических подробностей {hide} ≠ [{OWNER_HIDE_WORD!r}]")
    if not parsed.get("principle_present"):
        mism.append(f"в разделе нет строки владельца {OWNER_PRINCIPLE_LINE!r}")
    out["mismatches"] = mism
    out["agrees"] = not mism
    if fb is not None and ORDER_G969_NAMED["classes"] is not None:
        out["order_undercount"] = {"classes": len(fb) - int(ORDER_G969_NAMED["classes"])}
    return out


# ───────────────────────────── носители ──────────────────────────────────────

def load_carriers(data_dir: str, root: str = REPO_ROOT) -> Dict[str, Any]:
    """Лента решений и трек — дверью §30; здоровье системы — своей (из него сборщик берёт
    первую строку основного экрана)."""
    out = smc.load_carriers(data_dir)
    doc, why = smc._read_json(Path(data_dir) / SYSTEM_HEALTH_REL)
    ok = isinstance(doc, dict)
    out["system_health"] = doc if ok else None
    out["system_health_reason"] = why if doc is None else (None if ok else f"{SYSTEM_HEALTH_REL} не словарь")
    out["data_dir"] = str(data_dir)
    out["root"] = root
    return out


def dashboard_rendered_keys(root: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Какие ключи полезной нагрузки `/api/live/books/brief` страница дашборда РЕНДЕРИТ —
    читается САМА страница (`br.<key>`), а не предполагается по ключам словаря."""
    text, why = smc._read_text(os.path.join(root, DASHBOARD_PAGE_REL))
    if text is None:
        return None, f"страница дашборда не прочитана: {why}"
    keys = sorted(set(re.findall(r"\b" + re.escape(DASHBOARD_BRIEF_VAR) + r"\.([A-Za-z_][\w]*)", text)))
    if not keys:
        return None, (f"на странице {DASHBOARD_PAGE_REL} не найдено ни одного обращения "
                      f"`{DASHBOARD_BRIEF_VAR}.<ключ>` — что она рендерит, НЕ ИЗМЕРЕНО")
    return keys, None


def dashboard_text(brief: Optional[Dict[str, Any]], rendered: Optional[List[str]]) -> Optional[str]:
    """Текст, который владелец видит на дашборде: значения ТОЛЬКО рендеримых ключей."""
    if brief is None or rendered is None:
        return None
    parts = [str(brief.get(k)) for k in rendered if brief.get(k) is not None]
    return "\n".join(parts) if parts else ""


# ───────────────────────────── выводы владельца ──────────────────────────────

#: Фразы владельца, которыми основной экран отвечает на вопросы «да/нет/что делать».
#: Внутреннее слово (`HOLD`, `WARNING`) ответом не считается — оно запрещённый класс.
PROBLEM_PHRASES: Tuple[str, ...] = (
    "Система: всё в порядке", "Система: есть предупреждения", "Система: сбой", "Система: авария",
    "аварий нет", "авария", "стоп-кран включён", "стоп-кран не включён", "Нарушение",
)
ACTION_PHRASES: Tuple[str, ...] = (
    "предлагает", "оставить как есть", "ничего не менять", "ничего делать не надо", "держать",
    "переложить", "перевести", "перебалансировать", "ход:", "рекоменд",
)
REACTION_PHRASES: Tuple[str, ...] = (
    "Ждут тебя", "реакция не нужна", "нужна твоя реакция", "нужно твоё решение", "ждёт твоего",
)

#: Вывод → производитель и форма ответа. ``field`` — поле записи решения; ``data_key`` —
#: ключ ``data`` сборщика отчёта; ``health`` — поле здоровья системы; ``brief_key`` — ключ
#: слоя дашборда; ``phrases`` — словарь владельца для нечисловых ответов; ``nearest`` —
#: ближайший носитель у отсутствующего.
OUTPUT_SPEC: Dict[str, Dict[str, Any]] = {
    "Текущая доходность": {
        "data_key": "apy_today_pct", "brief_key": "current_apy_pp", "value_kind": "rate",
        "number_kind": "начисленная ставка дня (доход × 365 / NAV), годовая",
        "qualifier": ("на дашборде под тем же словом стоит ОЖИДАНИЕ по держимой книге "
                      "(current_apy_pp) — два числа одной величины, ADR-981")},
    "Потенциальная доходность": {
        "field": "target_apy_pp", "brief_key": "optimal_apy_pp", "value_kind": "rate",
        "number_kind": drc.NUMBER_EXPECTATION,
        "qualifier": "НИЖНЯЯ ГРАНИЦА объявленного оптимума (ADR-859/979); унаследовано"},
    "Есть ли проблема": {
        "health": "overall_status", "brief_key": None, "value_kind": "phrase", "phrases": PROBLEM_PHRASES,
        "number_kind": "состояние системы словами (из system_health.json)"},
    "Что система предлагает сделать": {
        "field": "verdict", "brief_key": "where", "value_kind": "phrase", "phrases": ACTION_PHRASES,
        "number_kind": "вердикт советника словами владельца, не словом записи",
        "qualifier": ("в записи вердикт — внутреннее слово (HOLD/ACT, §24); на основной экран "
                      "обязан доходить ПЕРЕВОД из одного словаря (owner_language), не само слово")},
    "Сколько это даст": {
        "field": "gain_pp", "brief_key": "yield_gap_pp", "value_kind": "rate",
        "number_kind": drc.NUMBER_EXPECTATION,
        "qualifier": ("в записи — разрыв в pp (нижняя граница); долларовый прирост по "
                      "горизонтам не складывает никто (ADR-980)")},
    "Сколько стоит": {
        "field": "cost_usd", "brief_key": "how_much", "value_kind": "money",
        "number_kind": drc.NUMBER_MODEL},
    "Когда окупится": {
        "field": "payback_days", "brief_key": None, "value_kind": "days",
        "number_kind": drc.NUMBER_EXPECTATION,
        "qualifier": "на дашборде срок окупаемости стоит только КОДОМ причины (payback_too_long:…d) — запрещённый класс"},
    "Изменится ли риск": {
        "nearest": ("меры риска «до/после» нет (ADR-980); ближайшее — admissible_trim.policy.approved "
                    "(да/нет RiskPolicy по урезанному предложению), не ответ на вопрос")},
    "Нужна ли моя реакция": {
        "nearest": ("у записи решения признака «нужна реакция владельца» нет; основной экран несёт "
                    "очередь карточек («Ждут тебя: карточек N») — это ответ про ОЧЕРЕДЬ, не про решение"),
        "phrases": REACTION_PHRASES},
}


def _present(v: object) -> bool:
    return v is not None and v != [] and v != {} and v != ""


def _phrase_reach(phrases: Sequence[str], text: Optional[str]) -> Optional[bool]:
    if text is None:
        return None
    low = text.lower()
    return any(p.lower() in low for p in phrases)


def _reach(spec: Dict[str, Any], value: object, text: Optional[str]) -> Optional[bool]:
    if text is None:
        return None
    if spec.get("phrases") and spec.get("value_kind", "phrase") == "phrase":
        return _phrase_reach(spec["phrases"], text)
    return drc.value_reaches(value, spec["value_kind"], text)


def _brief_reach(spec: Dict[str, Any], value: object, brief: Optional[Dict[str, Any]],
                 rendered: Optional[List[str]]) -> Optional[bool]:
    key = spec.get("brief_key")
    if key is None or brief is None or not brief.get("available") or rendered is None:
        return None
    if key not in rendered:
        return False                      # слой несёт, страница не показывает — ADR-488
    got = brief.get(key)
    if spec.get("value_kind") == "phrase":
        return bool(str(got or "").strip())
    if spec.get("value_kind") in ("rate", "money", "days"):
        if isinstance(got, (int, float)) and not isinstance(got, bool):
            return got == value if spec.get("field") else True
        return drc.value_reaches(value, spec["value_kind"], str(got or "")) if _present(value) else None
    return None


def measure_outputs(carriers: Dict[str, Any], report_data: Optional[Dict[str, Any]],
                    main_text: Optional[str], details_text: Optional[str],
                    brief: Optional[Dict[str, Any]], rendered: Optional[List[str]]) -> Dict[str, Any]:
    recs = carriers.get("records") or []
    last = recs[-1] if recs else {}
    health = carriers.get("system_health") or {}
    out: Dict[str, Any] = {}
    for name in OWNER_OUTPUTS:
        spec = OUTPUT_SPEC[name]
        r: Dict[str, Any] = {"number_kind": spec.get("number_kind"), "qualifier": spec.get("qualifier")}
        value: object = None
        if "field" in spec:
            key = spec["field"]
            if not recs:
                r.update({"kind": UNMEASURED, "carrier": f"{RECORD_REL}: {key}",
                          "reason": f"лента решений {RECORD_REL} не прочитана/пуста: "
                                    f"{carriers.get('records_reason') or 'нет строк'}"})
                out[name] = r
                continue
            shape = drc._ledger_shape(recs, key)
            value = last.get(key)
            present = key in last and _present(value)
            r.update({"kind": "produced" if present or shape["with_value"] else "absent",
                      "carrier": f"{RECORD_REL}: {key}", "value": value if present else None,
                      "ledger": shape, "third_outcome": shape["third_outcome"]})
            if not present and shape["with_value"] == 0:
                r["reason"] = f"поле {key} ни в одной из {shape['rows']} записей не несёт значения"
        elif "data_key" in spec:
            key = spec["data_key"]
            if report_data is None:
                r.update({"kind": UNMEASURED, "carrier": f"сборщик отчёта: data[{key!r}]",
                          "reason": "отчёт не собран — данных сборщика нет"})
                out[name] = r
                continue
            value = report_data.get(key)
            present = _present(value)
            r.update({"kind": "produced" if present else "absent",
                      "carrier": f"сборщик отчёта: data[{key!r}]", "value": value if present else None,
                      "third_outcome": ("наблюдён (ключ есть, значения нет)" if key in report_data and not present
                                        else "только отсутствием ключа" if key not in report_data
                                        else "не наблюдён (значение есть)")})
        elif "health" in spec:
            key = spec["health"]
            if not health:
                r.update({"kind": UNMEASURED, "carrier": f"{SYSTEM_HEALTH_REL}: {key}",
                          "reason": f"{SYSTEM_HEALTH_REL} не прочитан: {carriers.get('system_health_reason')}"})
                out[name] = r
                continue
            value = health.get(key)
            present = _present(value)
            r.update({"kind": "produced" if present else "absent",
                      "carrier": f"{SYSTEM_HEALTH_REL}: {key}", "value": value if present else None,
                      "third_outcome": "наблюдён (ключ без значения)" if key in health and not present
                      else "только отсутствием ключа" if key not in health else "не наблюдён (значение есть)"})
        else:
            r.update({"kind": "absent", "carrier": None, "value": None, "reason": spec["nearest"],
                      "third_outcome": "не применимо — производителя нет"})
        produced = r["kind"] in PRODUCED_KINDS
        if produced or spec.get("phrases"):
            r["main_reach"] = _reach(spec, value, main_text) if (produced or "phrases" in spec) else None
            r["details_reach"] = _reach(spec, value, details_text) if (produced or "phrases" in spec) else None
        else:
            r["main_reach"] = None
            r["details_reach"] = None
        if "phrases" in spec and not produced:
            # фраза есть, производителя нет — доходит ОТВЕТ НА ДРУГОЙ ВОПРОС, и это печатается
            r["phrase_on_main_screen"] = r["main_reach"]
            r["main_reach"] = None
            r["details_reach"] = None
        r["dashboard_reach"] = _brief_reach(spec, value, brief, rendered) if produced else None
        out[name] = r
    return _tally(out, main_text)


def _tally(rows: Dict[str, Any], main_text: Optional[str]) -> Dict[str, Any]:
    tally = {k: sum(1 for r in rows.values() if r["kind"] == k) for k in OUTPUT_KINDS}
    produced = [n for n, r in rows.items() if r["kind"] in PRODUCED_KINDS]
    main = [n for n in produced if rows[n].get("main_reach") is True]
    details = [n for n in produced if rows[n].get("details_reach") is True]
    dash = [n for n in produced if rows[n].get("dashboard_reach") is True]
    return {"outputs": rows, "tally": tally, "declared": OWNER_OUTPUTS_DECLARED,
            "produced": len(produced), "reach_main": len(main), "reach_details": len(details),
            "reach_dashboard": len(dash), "reach_main_names": main, "reach_details_names": details,
            "reach_dashboard_names": dash, "main_screen_built": main_text is not None}


# ───────────────────────────── поверхности ───────────────────────────────────

def measure_surfaces(headline: Optional[str], details: Optional[str],
                     brief: Optional[Dict[str, Any]], rendered: Optional[List[str]]) -> Dict[str, Any]:
    dash_text = dashboard_text(brief, rendered)
    surfaces = {
        SURFACE_MAIN: detect_classes(headline),
        SURFACE_DETAILS: detect_classes(details),
        SURFACE_DASHBOARD: detect_classes(dash_text),
    }
    carried_not_rendered: List[str] = []
    if brief is not None and rendered is not None:
        carried_not_rendered = sorted(k for k in brief if k not in rendered and brief.get(k) is not None)
    return {
        "surfaces": surfaces,
        "details_separated": (HEADLINE_FOOTER_WORDS in headline) if headline is not None else None,
        "dashboard_rendered_keys": rendered,
        "dashboard_carried_not_rendered": carried_not_rendered,
        "dashboard_text_chars": len(dash_text) if dash_text is not None else None,
    }


# ───────────────────────────── находки ───────────────────────────────────────

def _findings(parity_r: Dict[str, Any], surf: Dict[str, Any], outputs: Dict[str, Any],
              report_reason: Optional[str], brief_reason: Optional[str], page_reason: Optional[str]
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
    if page_reason:
        unmeasured.append(f"рендеримые ключи дашборда: {page_reason}")

    main = surf["surfaces"][SURFACE_MAIN]
    if main.get("measured"):
        if main["total"]:
            for cls in main["classes_present"]:
                add("CRITICAL", f"forbidden_on_main_screen:{cls}",
                    f"на ОСНОВНОМ экране владельца (первое сообщение дайджеста) класс «{cls}»: "
                    f"{main['hits'][cls]}")
        else:
            add("INFO", "main_screen_free_of_forbidden_classes",
                f"на основном экране владельца ни одного из {FORBIDDEN_CLASSES_DECLARED} запрещённых классов")
    else:
        unmeasured.append("запрещённые классы на основном экране: основной экран не собран")

    det = surf["surfaces"][SURFACE_DETAILS]
    if det.get("measured") and det["total"]:
        add("INFO", "technical_details_in_details_message",
            f"в «Подробнее» (второе сообщение) технические классы РАЗРЕШЕНЫ владельцем — "
            f"найдено {det['total']}: " + ", ".join(f"{c} ×{len(det['hits'][c])}" for c in det["classes_present"]))
    if surf.get("details_separated") is False:
        add("WARN", "details_not_announced",
            f"основной экран не объявляет «{HEADLINE_FOOTER_WORDS}» — читатель не знает, где «{OWNER_HIDE_WORD}»")

    dash = surf["surfaces"][SURFACE_DASHBOARD]
    if dash.get("measured"):
        if dash["total"]:
            for cls in dash["classes_present"]:
                add("WARN", f"forbidden_on_dashboard:{cls}",
                    f"на дашборде (слой {DASHBOARD_PAGE_REL}, рендеримые ключи {surf.get('dashboard_rendered_keys')}) "
                    f"класс «{cls}»: {dash['hits'][cls]}")
        else:
            add("INFO", "dashboard_free_of_forbidden_classes", "рендеримые ключи дашборда без запрещённых классов")
        if surf.get("dashboard_carried_not_rendered"):
            add("INFO", "dashboard_carries_but_hides",
                f"слой дашборда несёт, страница не показывает: {surf['dashboard_carried_not_rendered']} — "
                f"технические поля в полезной нагрузке владельцу не видны")

    rows = outputs.get("outputs") or {}
    for name, r in rows.items():
        k = r["kind"]
        if k == UNMEASURED:
            unmeasured.append(f"вывод «{name}»: {r.get('reason')}")
            continue
        if k == "produced":
            reach = r.get("main_reach")
            if reach is True:
                add("INFO", f"output_on_main_screen:{name}",
                    f"«{name}»: {r['carrier']} → основной экран; род «{r.get('number_kind')}»; "
                    f"третий исход: {r.get('third_outcome')}")
            elif reach is False:
                where = []
                if r.get("details_reach"):
                    where.append("доходит до «Подробнее»")
                if r.get("dashboard_reach"):
                    where.append("доходит до дашборда (форма ADR-808)")
                add("CRITICAL", f"output_not_on_main_screen:{name}",
                    f"«{name}»: производитель есть ({r['carrier']}, значение {drc._short(r.get('value'))}), "
                    f"до ОСНОВНОГО экрана владельца не доходит"
                    + (f" ({'; '.join(where)})" if where else "") + f"; род «{r.get('number_kind')}»")
            else:
                unmeasured.append(f"доходимость вывода «{name}»: основной экран не собран либо у значения "
                                  f"{drc._short(r.get('value'))} нет рендера с ≥{MIN_SIGNIFICANT_DIGITS} значащими цифрами")
            if r.get("qualifier"):
                add("WARN", f"output_qualifier:{name}", f"«{name}»: {r['qualifier']}")
        elif k == "components_only":
            add("CRITICAL", f"output_components_only:{name}", f"«{name}»: {r.get('reason')}")
        elif k == "absent":
            tail = ""
            if r.get("phrase_on_main_screen") is True:
                tail = " — фраза владельца на основном экране ЕСТЬ, но отвечает на другой вопрос"
            add("CRITICAL", f"output_absent:{name}", f"«{name}»: {r.get('reason')}{tail}")

    if rows and outputs.get("main_screen_built"):
        missing = [n for n, r in rows.items() if r["kind"] != UNMEASURED
                   and not (r["kind"] in PRODUCED_KINDS and r.get("main_reach") is True)]
        if missing:
            add("CRITICAL", "outputs_declared_vs_on_main_screen",
                f"объявлено {OWNER_OUTPUTS_DECLARED} выводов основного экрана, производится {outputs.get('produced')}, "
                f"на основном экране {outputs.get('reach_main')}; нет на экране: "
                + ", ".join(f"«{n}»→{rows[n]['kind']}" for n in missing))
    return findings, unmeasured


# ───────────────────────────── прогон ────────────────────────────────────────

#: Живой сборщик отчёта — ОДНА дверь (ADR-980): настоящий ``build_digest_messages`` с
#: ``drain=False``. Имя в этом модуле — чтобы проба и батарея подменяли ЕГО, не чужой модуль.
live_report_reader = drc.live_report_reader


def run(root: str = REPO_ROOT, data_dir: Optional[str] = None, card_path: Optional[str] = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        reader: Optional[drc.ReportReader] = None,
        page_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """Полный замер §36. Только ЧИТАЕТ; ``applied=False``. ``reader`` — сборщик отчёта
    (вход; по умолчанию живой ``build_digest_messages`` с ``drain=False``); ``page_keys`` —
    рендеримые ключи дашборда (вход; по умолчанию читаются со страницы)."""
    data_dir = data_dir or os.path.join(root, "data")
    card_path = card_path or os.path.join(root, CARD_REL)
    stamped = now or dt.datetime.now(dt.timezone.utc)
    read = reader or live_report_reader

    parity_r = parity(card_path)
    carriers = load_carriers(data_dir, root)
    headline, details, data, report_reason = read(data_dir, stamped)
    recs = carriers.get("records") or []
    brief, brief_reason = drc.brief_for(recs) if recs else (None, None)
    if page_keys is not None:
        rendered, page_reason = list(page_keys), None
    else:
        rendered, page_reason = dashboard_rendered_keys(root)
    surf = measure_surfaces(headline, details, brief, rendered)
    outputs = measure_outputs(carriers, data, headline, details, brief, rendered)
    findings, unmeasured = _findings(parity_r, surf, outputs, report_reason, brief_reason, page_reason)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unmeasured": len(unmeasured),
    }
    overall = ("CRITICAL" if counts["critical"] else "WARNING" if counts["warn"] else
               "UNCHECKED" if counts["unmeasured"] else "OK")
    doc = {
        "schema": "owner_ui_census/v1",
        "generated_at": stamped.isoformat(),
        "owner_section": SECTION_HEAD,
        "applied": False,
        "advisory": ("ADVISORY. Отвечает на §36 ТЗ «Portfolio CIO» (Owner UI). Отчёт не отправляет "
                     "(drain=False), запись, дайджест, витрину и страницу не трогает, выводы владельца не "
                     "вычисляет; карточку владельцу не заводит — форма основного экрана есть advisory-слой, "
                     "работа агента. Запрещённый класс судится ФОРМОЙ (детектор ошибается в сторону "
                     "находки, отрезок печатается); вывод — РЕНДЕРОМ значения (≥"
                     f"{MIN_SIGNIFICANT_DIGITS} значащих цифр) либо ФРАЗОЙ из словаря владельца"),
        "overall": overall,
        "counts": counts,
        "declared": {"forbidden_classes": list(FORBIDDEN_CLASSES), "forbidden_declared": FORBIDDEN_CLASSES_DECLARED,
                     "outputs": list(OWNER_OUTPUTS), "outputs_declared": OWNER_OUTPUTS_DECLARED,
                     "hide_in": OWNER_HIDE_WORD, "surfaces": list(SURFACES),
                     "main_screen": "первое сообщение утреннего дайджеста (build_digest_messages, drain=False)",
                     "details": "второе сообщение дайджеста — объявлено заголовком как «Подробности»",
                     "dashboard": f"cio_brief.brief_from_history, ключи рендеримые {DASHBOARD_PAGE_REL}",
                     "order_g969_named": dict(ORDER_G969_NAMED),
                     "output_kinds": list(OUTPUT_KINDS), "produced_kinds": list(PRODUCED_KINDS)},
        "parity": parity_r,
        "surfaces": surf,
        "outputs": outputs,
        "report": {"built": headline is not None, "reason": report_reason,
                   "headline_chars": len(headline) if headline else None,
                   "details_chars": len(details) if details else None},
        "carriers_read": {k: (carriers.get(k) is not None) for k in ("records", "daily", "system_health")},
        "findings": findings,
        "unmeasured": unmeasured,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))   # (data, path) — ADR-980
    return doc


def _print(doc: Dict[str, Any]) -> None:
    c = doc["counts"]
    print(f"§36 ТЗ «Portfolio CIO» (Owner UI): {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} не измерено={c['unmeasured']})")
    p = doc["parity"]
    if p.get("agrees") is True:
        print(f"   паритет с карточкой: СОВПАЛ (запрещённых классов {FORBIDDEN_CLASSES_DECLARED}, выводов "
              f"{OWNER_OUTPUTS_DECLARED}, подробности — «{OWNER_HIDE_WORD}», строка «на основном экране», "
              f"принцип owner-first; заказ G969 числа не называл — сдвиг не применим)")
    else:
        print(f"   паритет с карточкой: {p.get('mismatches') or p['parsed'].get('reason')}")
    rep = doc["report"]
    s = doc["surfaces"]
    print(f"   основной экран собран: {rep.get('built')} (заголовок {rep.get('headline_chars')} зн., "
          f"подробности {rep.get('details_chars')} зн.); «Подробнее» объявлено: {s.get('details_separated')}")
    for name in SURFACES:
        d = s["surfaces"][name]
        print(f"   {name}: " + ("НЕ ИЗМЕРЕНО" if not d.get("measured") else
                                f"запрещённых отрезков {d['total']}; " +
                                "; ".join(f"{cls}: {d['hits'][cls]}" for cls in d.get("classes_present") or []) or "чисто"))
    o = doc["outputs"]
    print(f"   выводов объявлено {o.get('declared')}, производится {o.get('produced')}, на основном экране "
          f"{o.get('reach_main')}, в «Подробнее» {o.get('reach_details')}, на дашборде {o.get('reach_dashboard')}; "
          f"роды {o.get('tally')}")
    for name, r in (o.get("outputs") or {}).items():
        print(f"      «{name}»: {r['kind']} — носитель {r.get('carrier')}, значение {drc._short(r.get('value'))}, "
              f"экран {r.get('main_reach')}, подробнее {r.get('details_reach')}, дашборд {r.get('dashboard_reach')}")
    for fnd in doc["findings"]:
        print(f"   [{fnd['severity']}] {fnd['code']}: {fnd['message']}")
    for u in doc["unmeasured"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    print(f"   {doc['advisory']}")


parse_now = smc.parse_now


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§36 ТЗ «Portfolio CIO»: на ОСНОВНОМ экране владельца нет ли запрещённых классов "
                    "и есть ли каждый из девяти выводов")
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
