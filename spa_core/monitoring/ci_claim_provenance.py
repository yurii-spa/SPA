"""Претензия о CI, не называющая свой прогон, перемерить нечем.

# LLM_FORBIDDEN

**Замер, ради которого прибор написан** (2026-11-27, цикл #1268, подтверждено
#1270). Ежедневный аудит «90 %» доложил владельцу строкой announce-лога:

    CI control RED 140 имён (вчера 58), худший — f-string SyntaxError на py3.11 ×26

Канонический читатель ``scripts/ci_control_verdict.py`` на том же дне даёт
**84** упавших, а не 140; худший файл — ``test_reachability_of_the_rest_wiring.py``
действительно **×26**, но причина, прочитанная в логе шарда, —
``Failed: Timeout (>180.0s) from pytest-timeout`` в ``setUpModule``. Класс
f-string при этом измерен в НОЛЬ двумя приборами. То есть **совпавшее число
×26 сделало ложную причину убедительной** и отправило бы следующий цикл чинить
то, чего нет.

**Предмет прибора — не «верна ли претензия», а «можно ли её вообще
перемерить».** У претензии о прогоне CI есть ровно одна личность, по которой
её перемеряют: НОМЕР ПРОГОНА. Претензия, несущая число или род падения и НЕ
несущая номера, не ошибочна и не верна — она **неопровержима**, и никакой
сторож о ней ничего не скажет. Это тот же класс, что «не измерено, выданное за
ответ» (`.claude/rules/deployment.md`), только с другой стороны: здесь за
ответ выдаётся ПРОЗА.

**Почему номер ищется ТОЛЬКО внутри сегмента претензии.** В той же строке
сводки стоят другие номера и другие sha — например коммит песочницы
(``песочница A/B/C на c5931f41b``) или номер ЗАКАЗАННОГО прогона из соседней
записи. Первая редакция мерки спрашивала «есть ли в строке хоть что-то похожее
на sha» и объявляла претензию 27.11 ПЕРЕМЕРЯЕМОЙ — ошибка в сторону «чисто»,
ровно та, против которой прибор написан. Поэтому личность берётся из
СЕГМЕНТА (от маркера до следующего ``;``), а номер, найденный в строке мимо
сегмента, назван отдельной осью и перемеряемости НЕ даёт.

**Чего прибор НЕ делает.** Он не сверяет РОД падения: род в претензии — проза,
и сверять её с осью причин канонического читателя нечем, кроме чтения лога
шарда. Поэтому у претензии с названным прогоном и названным родом исход свой —
«число сверено, РОД НЕ СВЕРЕН», и он находка: именно совпадение числа делает
непроверенный род убедительным. Выдумать прозаический сравнитель значило бы
завести меру, отвечающую «я не умею» под видом «чисто».
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

#: Маркеры, по которым узнаётся претензия о контрольном прогоне. Перечень
#: ОБЪЯВЛЕН здесь: маркер, которого тут нет, даёт запись «вне населения», а не
#: молчание.
CLAIM_MARKS: tuple[str, ...] = (
    r"CI\s+control",
    r"CI\s+контроль",
    r"контрольн\w*\s+прогон\w*",
    r"автопроверк\w*\s+кода",
)
_MARK_RE = re.compile("|".join(CLAIM_MARKS), re.IGNORECASE)

#: Формы ЧИСЛА упавших. `RED 140 имён`, `RED 68`, `красных 59`, `упавших 84`.
COUNT_FORMS: tuple[str, ...] = (
    r"RED\s+(\d+)",
    r"красн\w*\s+(\d+)",
    r"упавш\w*\s+(\d+)",
    r"failed\s*[=:]?\s*(\d+)",
)
_COUNT_RE = re.compile("|".join(COUNT_FORMS), re.IGNORECASE)

#: Хвосты, после которых число есть ДЛИТЕЛЬНОСТЬ, а не счёт упавших.
#:
#: Форма ``красн\w*\s+(\d+)`` выше читает `красных 59` — и ровно так же читает
#: `красное 4.1 суток`, то есть ДЛИНУ СЕРИИ. Это разные утверждения: счёт
#: упавших принадлежит ОДНОМУ прогону и перемеряется его номером, а длина
#: серии принадлежит ЗАДАНИЮ и перемеряется номером последнего зелёного.
#: Считать второе первым значило бы завести находку там, где претензия честна.
#: Население этой ловушки в наблюдаемых носителях ИЗМЕРЕНО и равно НУЛЮ
#: (замер 27.11, цикл #1271: announce-лог 0 · трекер+журналы 0), и ноль здесь
#: печатается, а не умалчивается: форму приносит ЧЕТВЁРТЫЙ носитель —
#: утренняя сводка владельцу (``scripts/morning_work_digest.py`` печатает
#: «АВТОПРОВЕРКА КОДА: КРАСНАЯ. «<задание>» красное 4.1 суток»).
DURATION_TAILS: tuple[str, ...] = (
    r"сут\w*", r"дн\w*", r"час\w*", r"ч\b", r"мин\w*", r"нед\w*", r"мес\w*",
    r"days?\b", r"hours?\b", r"h\b", r"min\b",
)
_DURATION_RE = re.compile(
    r"\s*(?:[.,]\d+)?\s*(?:" + "|".join(DURATION_TAILS) + r")", re.IGNORECASE)

#: Формы РОДА падения с кратностью: `худший — <проза> ×26`, `причина … x13`.
CAUSE_FORMS: tuple[str, ...] = (
    r"худш\w*\s*[—\-:]\s*(?P<cause>[^,;()]{3,120}?)\s*[×x]\s*(?P<mult>\d+)",
    r"причина\w*\s*[—\-:]\s*(?P<cause>[^,;()]{3,120}?)\s*[×x]\s*(?P<mult>\d+)",
)
#: Формы рода компилируются ПООТДЕЛЬНОСТИ: у каждой свои именованные
#: группы, и склейка через `|` их бы переопределила.
_CAUSE_RES = tuple(re.compile(f, re.IGNORECASE) for f in CAUSE_FORMS)


def _search_cause(segment: str) -> re.Match | None:
    for rx in _CAUSE_RES:
        m = rx.search(segment)
        if m is not None:
            return m
    return None

#: Номер прогона GitHub Actions. Замер: живые номера этого репозитория — 11
#: знаков; вилка 10…12 взята с запасом в ОБЕ стороны, чтобы мерка не зависела
#: от того, когда GitHub перешагнёт разряд.
RUN_ID_RE = re.compile(r"\b(\d{10,12})\b")

#: Ширина номера прогона ОБЪЯВЛЕНА, и число ДРУГОЙ ширины в сегменте есть
#: отдельная ось, а не молчание. Замер 27.11: живые номера прогонов этого
#: репозитория — 11 знаков, идентификаторы ВОРКФЛОУ — 9
#: (`387027328 SPA CI control`), и запись аудита 27.10 несла `908015739`,
#: которого среди прогонов нет вовсе (`GET …/actions/runs/908015739` → 404).
#: Промолчи мерка об этом — читатель решил бы, что прогон назван, а прибор его
#: не увидел.
_DIGITS_RE = re.compile(r"\b(\d{4,})\b")

#: Кавычки ЦИТАТЫ. Претензия, попавшая внутрь «…», принадлежит ДРУГОЙ записи:
#: её автор пересказывает чужую сводку, а не утверждает своё. Считать цитату
#: находкой значило бы удваивать население и наказывать разбор — ровно ошибка
#: в сторону НАХОДКИ (замер 27.11: из 22 претензий с числом цитатой является
#: РОВНО одна — запись цикла #1270, разбиравшего сводку аудита).
QUOTE_OPEN, QUOTE_CLOSE = "«", "»"


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """Диапазоны цитат «…» (вложенные считаются как одна внешняя)."""
    out: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text or ""):
        if ch == QUOTE_OPEN:
            if depth == 0:
                start = i
            depth += 1
        elif ch == QUOTE_CLOSE and depth:
            depth -= 1
            if depth == 0:
                out.append((start, i))
    return out


# ── РАЗМЕТКА: цитата в markdown бывает не только «…» ───────────────────────
#
# ADR-1124 измерил класс в ОДНОМ носителе — announce-логе, где запись есть
# ПЛОСКАЯ строка, и единственная форма цитаты там «…». У остальных трёх
# носителей (карточки трекера, `docs/journal/**`, утренняя сводка владельцу)
# текст есть markdown, и в нём пересказ чужой претензии выглядит ещё тремя
# способами: вставка кода ``…``, огороженный блок ``` … ``` и блок-цитата
# `> …`. Не спроси их — и разбор аварии, цитирующий дословную строку аудита,
# пошёл бы в население КАК ПРЕТЕНЗИЯ. Замер 27.11 (цикл #1271): такой
# пересказ в журналах и карточках есть, и без оси вставки кода он давал
# ровно одно ложное срабатывание (`docs/journal/2026-W48.md`, разбор
# ADR-1124 своей же находки) — ошибка в сторону НАХОДКИ.
QUOTE_NONE = "not_quoted"
QUOTE_GUILLEMETS = "quoted_guillemets"
QUOTE_INLINE_CODE = "quoted_inline_code"
QUOTE_FENCE = "quoted_fence"
QUOTE_BLOCKQUOTE = "quoted_blockquote"
QUOTE_UNDECIDED = "quotation_undecided"

QUOTATION_KINDS: tuple[str, ...] = (
    QUOTE_NONE, QUOTE_GUILLEMETS, QUOTE_INLINE_CODE, QUOTE_FENCE,
    QUOTE_BLOCKQUOTE, QUOTE_UNDECIDED,
)

#: Роды цитаты, при которых претензия принадлежит ДРУГОЙ записи.
QUOTING_KINDS: frozenset[str] = frozenset({
    QUOTE_GUILLEMETS, QUOTE_INLINE_CODE, QUOTE_FENCE, QUOTE_BLOCKQUOTE})

_BACKTICK_RUN_RE = re.compile(r"`+")


def code_spans(text: str) -> list[tuple[int, int]]:
    """Диапазоны вставок кода ``…``: серия бэктиков ↔ серия ТОЙ ЖЕ длины.

    Длина серии существенна: ``` ``текст с `бэктиком` внутри`` ``` — законная
    форма markdown, и пара по «любому следующему бэктику» разорвала бы её
    посередине.
    """
    runs = [(m.start(), m.end() - m.start())
            for m in _BACKTICK_RUN_RE.finditer(text or "")]
    out: list[tuple[int, int]] = []
    used: set[int] = set()
    for i, (pos, width) in enumerate(runs):
        if i in used:
            continue
        for j in range(i + 1, len(runs)):
            if j in used:
                continue
            if runs[j][1] == width:
                end = runs[j][0] + runs[j][1] - 1
                # Серии ВНУТРИ найденной пары закрыты внешней вставкой и своей
                # пары не образуют: иначе ``тут `вложенный` бэктик`` дало бы
                # ДВА диапазона, и внутренний накрыл бы претензию, которую
                # накрывает внешний, — ответ о разметке, которой нет.
                used.update(k for k in range(i, j + 1))
                out.append((pos, end))
                break
    return out


def unclosed_opener(text: str, *, markup: bool) -> int:
    """Позиция открывателя цитаты, который НЕ закрылся, или −1.

    Третий исход оси цитаты (инв. #17). Запись с незакрытой кавычкой или
    непарной серией бэктиков не даёт ответа «в цитате / не в цитате»: ответ
    зависит от того, где автор её закрыл — может быть в соседней записи.
    Угадать здесь значило бы соврать в одну из двух сторон, поэтому исход
    свой — `quotation_undecided`, и он идёт в ВЕРХНИЙ край вилки населения.
    """
    text = text or ""
    # Пары берутся ТОЙ ЖЕ дверью, что и накрытие (`quoted_spans`/`code_spans`):
    # разойдись они — «не закрылось» отвечало бы о другой разметке, чем
    # «накрыто». И «внутри закрытой пары» значит ВНУТРИ ДИАПАЗОНА, а не
    # «равно его концу»: вложенный открыватель закрыт внешней парой, и считать
    # его свободным значило бы объявлять неразрешимой любую запись с
    # вложенной разметкой.
    def _free(positions: list[int], spans: list[tuple[int, int]]) -> list[int]:
        return [p for p in positions
                if not any(a <= p <= b for a, b in spans)]

    quotes = quoted_spans(text)
    free = _free([i for i, ch in enumerate(text) if ch == QUOTE_OPEN], quotes)
    if markup:
        code = code_spans(text)
        runs = [m.start() for m in _BACKTICK_RUN_RE.finditer(text)]
        free += _free(runs, code)
    return min(free) if free else -1


def quotation_of(text: str, *, start: int, claim_end: int = -1,
                 markup: bool = False, fenced: bool = False,
                 blockquote: bool = False) -> tuple[str, str]:
    """Род цитаты, накрывающей претензию, и причина. ЕДИНСТВЕННАЯ дверь.

    **Накрывает — значит накрывает ОБА конца.** Первая редакция оси (ADR-1124)
    спрашивала только положение МАРКЕРА, и этого мало: журналы берут в кавычки
    сам ТЕРМИН («контрольный прогон»), после чего претензия, стоящая СНАРУЖИ
    кавычек, числилась цитатой — ошибка в сторону «чисто» (замер 27.11:
    `CARD-archive-portfolio-cio-chronicle-2026-11-19.md`). Поэтому спрашивается
    диапазон, накрывающий и маркер, и то, ЧЕМ претензия утверждает — число
    либо род.

    ``claim_end`` < 0 ⇒ конец претензии неизвестен, и ось отвечает о маркере;
    это сказано в причине, а не умолчано.
    """
    if fenced:
        return QUOTE_FENCE, ("претензия стоит в огороженном блоке ``` — это "
                             "дословный пересказ чужой записи, а не "
                             "утверждение автора")
    if blockquote:
        return QUOTE_BLOCKQUOTE, ("претензия стоит в блок-цитате `> …` — она "
                                  "принадлежит ДРУГОЙ записи")
    if start < 0:
        return QUOTE_NONE, ("положение сегмента неизвестно — ось цитаты НЕ "
                            "спрашивалась")
    end = claim_end if claim_end >= start else start
    candidates: list[tuple[tuple[int, int], str]] = [
        (s, QUOTE_GUILLEMETS) for s in quoted_spans(text)]
    if markup:
        candidates += [(s, QUOTE_INLINE_CODE) for s in code_spans(text)]
    for (a, b), kind in candidates:
        if a <= start and end <= b:
            tail = ("" if claim_end >= start
                    else "; конец претензии НЕ ИЗВЕСТЕН — ось отвечает о маркере")
            return kind, (f"претензия целиком стоит внутри цитаты "
                          f"({kind}) — она принадлежит ДРУГОЙ записи, и "
                          f"спрашивать её у этого автора значило бы удвоить "
                          f"население{tail}")
    free = unclosed_opener(text, markup=markup)
    if 0 <= free <= start:
        return QUOTE_UNDECIDED, (f"у записи есть открыватель цитаты в позиции "
                                 f"{free}, который в ней НЕ закрылся — "
                                 f"принадлежит претензия автору или пересказу, "
                                 f"по этой записи НЕ ВИДНО")
    return QUOTE_NONE, "претензия не накрыта ни одной цитатой"


# ── НОСИТЕЛИ: markdown-запись есть АВТОРСКАЯ единица, не строка и не файл ──
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_NEW_BLOCK_RE = re.compile(
    r"^(?:\s*(?:[-*+]\s|\d+[.)]\s)|\s{0,3}#{1,6}\s|\s*\||\s*>)")


def markdown_records(text: str) -> list[dict]:
    """Авторские единицы markdown: абзац · пункт списка · строка таблицы · цитата.

    **Почему НЕ строка и НЕ файл — и обе ошибки идут в РАЗНЫЕ стороны.**
    Проза в журналах переносится жёстко (~95 знаков), поэтому номер прогона и
    число оказываются на РАЗНЫХ строках: мерка по строке объявила бы
    перемеряемую претензию неопровержимой, то есть соврала бы в сторону
    НАХОДКИ. Файл целиком — ошибка в другую сторону: номер из соседнего
    абзаца дал бы претензии ЧУЖУЮ личность, и это ровно дефект, против
    которого ADR-1124 взял сегмент вместо строки.

    Поэтому склеиваются ровно ПРОДОЛЖЕНИЯ: строка, начинающая новый пункт,
    заголовок, строку таблицы или блок-цитату, начинает и новую запись.
    Огороженный блок ``` … ``` склеивается целиком и помечается `fenced`:
    пустая строка внутри него границей записи не является.
    """
    records: list[dict] = []
    buf: list[str] = []
    start = 0
    fence: str | None = None
    fenced_now = False
    quote_now = False

    def flush() -> None:
        nonlocal buf, start, fenced_now, quote_now
        if buf:
            records.append({"line": start, "text": " ".join(buf),
                            "fenced": fenced_now, "blockquote": quote_now})
        buf = []
        fenced_now = False
        quote_now = False

    for num, raw in enumerate((text or "").splitlines(), 1):
        line = raw.rstrip()
        m = _FENCE_RE.match(line)
        if fence is not None:
            # Внутри ограды закрывателем считается ограда ТОГО ЖЕ знака.
            if m is not None and m.group(1)[0] == fence[0]:
                flush()
                fence = None
                continue
            if not buf:
                start = num
                fenced_now = True
            buf.append(line)
            continue
        if m is not None:
            flush()
            fence = m.group(1)
            continue
        if not line.strip():
            flush()
            continue
        if _NEW_BLOCK_RE.match(line) or not buf:
            flush()
            start = num
            quote_now = bool(_BLOCKQUOTE_RE.match(line))
        buf.append(line)
    flush()
    return records

# ── исходы (инв. #17: «не измерено» — отдельное значение, а не ноль) ────────
NO_CLAIM = "no_claim"
QUOTED = "quoted_claim_of_another_record"
UNFALSIFIABLE = "unfalsifiable"
COUNT_AGREES = "count_agrees"
COUNT_DIFFERS = "count_differs"
CAUSE_UNVERIFIED = "cause_unverified_number_only"
OUT_OF_WINDOW = "unmeasured_out_of_window"
NO_CANONICAL = "unmeasured_no_canonical"
UNPARSED = "unmeasured_unparsed"
#: Ось цитаты не дала ответа (незакрытый открыватель). Это НЕ «не цитата»:
#: такая претензия идёт в ВЕРХНИЙ край вилки населения, а не в ноль.
QUOTATION_UNDECIDED = "unmeasured_quotation_undecided"

KINDS: tuple[str, ...] = (
    NO_CLAIM, QUOTED, UNFALSIFIABLE, COUNT_AGREES, COUNT_DIFFERS, CAUSE_UNVERIFIED,
    OUT_OF_WINDOW, NO_CANONICAL, UNPARSED, QUOTATION_UNDECIDED,
)

#: Исходы, которые есть НАХОДКА, а не состояние.
FINDING_KINDS: frozenset[str] = frozenset({UNFALSIFIABLE, COUNT_DIFFERS,
                                           CAUSE_UNVERIFIED})

#: Исходы «НЕ ИЗМЕРЕНО»: нулём они не считаются и находкой не являются.
UNMEASURED_KINDS: frozenset[str] = frozenset({OUT_OF_WINDOW, NO_CANONICAL,
                                              UNPARSED, QUOTATION_UNDECIDED})


def claim_segments(summary: str) -> list[dict]:
    """Сегменты претензии: от маркера до следующего ``;`` (или до конца).

    Граница именно ``;``: сводка аудита перечисляет предметы через точку с
    запятой, и «флот 97,8 %» к прогону CI отношения не имеет. Брать строку
    целиком значило бы отдать претензии номер соседнего предмета.
    """
    out: list[dict] = []
    for m in _MARK_RE.finditer(summary or ""):
        tail = summary[m.start():]
        cut = tail.find(";")
        seg = tail if cut < 0 else tail[:cut]
        out.append({"mark": m.group(0), "start": m.start(), "segment": seg})
    return out


def _first_group(m: re.Match | None) -> str | None:
    if m is None:
        return None
    for g in m.groups():
        if g:
            return g
    return None


def read_claim(segment: str) -> dict:
    """Что ОБЪЯВЛЕНО в сегменте: число, род с кратностью, номера прогонов.

    Отдаёт и ПОЛОЖЕНИЯ найденного (``count_span`` / ``cause_span``): ось
    цитаты спрашивает диапазон, накрывающий претензию ЦЕЛИКОМ, и без концов
    она могла бы ответить только о маркере.
    """
    count = count_span = None
    duration: list[str] = []
    for m in _COUNT_RE.finditer(segment):
        value = _first_group(m)
        if value is None:
            continue
        if _DURATION_RE.match(segment, m.end()):
            # Число есть ДЛИТЕЛЬНОСТЬ («красное 4.1 суток»), а не счёт
            # упавших: оно принадлежит ЗАДАНИЮ, а не одному прогону.
            duration.append(value)
            continue
        if count is None:
            count, count_span = int(value), (m.start(), m.end() - 1)
    cause_m = _search_cause(segment)
    cause = mult = cause_span = None
    if cause_m is not None:
        cause = (cause_m.groupdict().get("cause") or "").strip() or None
        mult = cause_m.groupdict().get("mult")
        cause_span = (cause_m.start(), cause_m.end() - 1)
    return {
        "count": count,
        "count_span": count_span,
        "cause": cause,
        "cause_mult": int(mult) if mult else None,
        "cause_span": cause_span,
        "duration_not_a_count": duration,
        "run_ids": RUN_ID_RE.findall(segment),
        "digits_not_run_id": [d for d in _DIGITS_RE.findall(segment)
                              if not RUN_ID_RE.fullmatch(d)],
    }


def classify_claim(segment: str, *, line: str = "", start: int = -1,
                   canonical: dict | None = None,
                   canonical_reason: str = "",
                   markup: bool = False, fenced: bool = False,
                   blockquote: bool = False) -> dict:
    """Исход ОДНОЙ претензии. Третий исход обязателен и несёт причину.

    ``start`` — положение сегмента в строке; нужно ОСИ ЦИТАТЫ. Без него (−1)
    ось не спрашивается, и это сказано в исходе, а не умолчано.

    ``markup`` объявляет, что носитель есть markdown: тогда к оси цитаты
    добавляются вставка кода ``…``, ограда и блок-цитата. Умолчание ``False``
    оставлено announce-логу намеренно — он ПЛОСКАЯ строка, и спрашивать у неё
    разметку значило бы объявить цитатой бэктик, которого там нет (замер
    27.11: в announce-логе бэктиков нет ни в одной претензии).
    """
    got = read_claim(segment)
    row = dict(got)
    row["segment"] = segment
    # Номер в СТРОКЕ мимо сегмента — отдельная ось. Перемеряемости он не даёт:
    # неизвестно, о том ли он прогоне, а догадка здесь была бы ошибкой в
    # сторону «чисто».
    outside = [r for r in RUN_ID_RE.findall(line or "") if r not in got["run_ids"]]
    row["run_id_outside_segment"] = outside

    claims_something = got["count"] is not None or got["cause"] is not None
    if not claims_something:
        row["kind"] = NO_CLAIM
        row["reason"] = "сегмент не несёт ни числа, ни рода — претензии нет"
        return row

    ends = [sp[1] for sp in (got["count_span"], got["cause_span"]) if sp]
    claim_end = start + max(ends) if (ends and start >= 0) else -1
    row["claim_end"] = claim_end
    quotation, quote_why = quotation_of(line, start=start, claim_end=claim_end,
                                        markup=markup, fenced=fenced,
                                        blockquote=blockquote)
    row["quotation"] = quotation
    row["quoted"] = quotation in QUOTING_KINDS
    if row["quoted"]:
        row["kind"] = QUOTED
        row["reason"] = quote_why
        return row
    if quotation == QUOTE_UNDECIDED:
        row["kind"] = QUOTATION_UNDECIDED
        row["reason"] = quote_why
        return row

    if not got["run_ids"]:
        row["kind"] = UNFALSIFIABLE
        extra = (f"; номер(а) в строке мимо сегмента: {', '.join(outside)} — "
                 f"о том ли он прогоне, НЕ ИЗВЕСТНО" if outside else "")
        if got["digits_not_run_id"]:
            extra += ("; числа в сегменте, номером прогона НЕ являющиеся: "
                      + ", ".join(got["digits_not_run_id"])
                      + " (живой номер прогона — 10…12 знаков)")
        row["reason"] = ("претензия несёт "
                         + ("число" if got["count"] is not None else "")
                         + (" и " if got["count"] is not None and got["cause"] else "")
                         + ("род падения" if got["cause"] else "")
                         + " и НЕ называет прогон — перемерить нечем" + extra)
        return row

    row["run_id"] = got["run_ids"][0]
    if canonical is None:
        row["kind"] = NO_CANONICAL
        row["reason"] = ("канонический читатель не ответил: "
                         + (canonical_reason or "причина не названа"))
        return row

    cid = str(((canonical.get("run") or {}).get("id")) or "")
    if cid != row["run_id"]:
        row["kind"] = OUT_OF_WINDOW
        row["reason"] = (f"канонический читатель отвечает о прогоне {cid or '—'}, "
                         f"а претензия о {row['run_id']} — перемерить этим "
                         f"чтением нечем")
        return row

    row["canonical_failed"] = canonical.get("failed")
    if got["count"] is not None and canonical.get("failed") != got["count"]:
        row["kind"] = COUNT_DIFFERS
        row["reason"] = (f"претензия назвала {got['count']}, канонический "
                         f"читатель — {canonical.get('failed')} на том же прогоне")
        return row

    if got["cause"] is not None:
        worst = ((canonical.get("red_census") or {}).get("worst") or [])
        row["canonical_worst"] = worst[0] if worst else None
        row["kind"] = CAUSE_UNVERIFIED
        row["reason"] = ("число сверено, а РОД падения — проза: сверять его "
                         "нечем, кроме чтения лога шарда. Совпавшее число "
                         "делает непроверенный род убедительным")
        return row

    row["kind"] = COUNT_AGREES
    row["reason"] = "число совпало с каноническим читателем на том же прогоне"
    return row


def read_announce(path: Path) -> tuple[list[dict], int, str]:
    """Записи announce-лога. Возврат ``(записи, неразобранных, причина)``.

    Причина непуста ⇒ **НЕ ИЗМЕРЕНО**: «файла нет» и «претензий нет» — разные
    состояния, и схлопывать их в пустой список запрещено (инв. #17).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], 0, f"{type(exc).__name__}: {exc}"
    rows: list[dict] = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        else:
            bad += 1
    return rows, bad, ""


def canonical_verdict(repo_root: Path | None = None, *,
                      runner=None) -> tuple[dict | None, str]:
    """Вердикт КАНОНИЧЕСКОГО читателя (``scripts/ci_control_verdict.py``).

    Своей копии разбора у прибора нет намеренно: разойдись она с читателем —
    прибор судил бы претензии по мерке, которой не судит никто другой.
    ``runner`` — точка инъекции для сцен.
    """
    root = Path(repo_root or _ROOT)
    tool = root / "scripts" / "ci_control_verdict.py"
    if runner is None:
        if not tool.exists():
            return None, f"канонического читателя нет в дереве: {tool}"

        def runner():  # noqa: E306 — замыкание вокруг найденного пути
            return subprocess.run(
                [sys.executable, str(tool), "--json"],
                capture_output=True, text=True, timeout=300, cwd=str(root),
            )

    try:
        out = runner()
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    text = getattr(out, "stdout", "") or ""
    if not text.strip():
        return None, (f"канонический читатель не отдал документ "
                      f"(код {getattr(out, 'returncode', '—')})")
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return None, f"документ канонического читателя не разобран: {exc}"
    if not isinstance(doc, dict):
        return None, "документ канонического читателя не объект"
    return doc, ""


# ── НОСИТЕЛИ: ADR-1124 закрыл один из четырёх ──────────────────────────────
#
# Замер 27.11 (цикл #1271) — ответ на заказ G1098 п. 5 и карточку
# `inbox-pretenziya-o-progone-ci-bez-svoei-lichno`. Претензия о прогоне CI
# живёт ЧЕТЫРЬМЯ носителями, и ADR-1124 измерил ОДИН. Нулём остальные три не
# считаются (инв. #17), поэтому носитель объявлен ЗДЕСЬ: отсутствие носителя
# в этом перечне даёт «НЕ ИЗМЕРЕНО», а не молчание.
CARRIER_ANNOUNCE = "announce"
CARRIER_TRACKER = "tracker"
CARRIER_JOURNAL = "journal"
CARRIER_DIGEST = "digest"

CARRIERS: tuple[str, ...] = (CARRIER_ANNOUNCE, CARRIER_TRACKER,
                             CARRIER_JOURNAL, CARRIER_DIGEST)

#: Носители, живущие ФАЙЛАМИ markdown в дереве КОНТЕНТА: каталог и маска.
CARRIER_PATHS: dict[str, tuple[str, str]] = {
    CARRIER_TRACKER: ("nimbalyst-local/tracker", "*.md"),
    CARRIER_JOURNAL: ("docs/journal", "*.md"),
}

#: Производитель утренней сводки владельцу. Его ТЕКСТ на диск не ложится —
#: сводка уходит в Telegram, — поэтому НАБЛЮДЁННОГО населения у этого
#: носителя нет вовсе, и это третий исход с названной причиной, а не ноль.
#: Статически же вопрос ОТВЕТИМ: литералы производителя читаются теми же
#: дверьми, и «способен ли он напечатать претензию без личности» меряется.
DIGEST_PRODUCER = "scripts/morning_work_digest.py"

#: Знак подстановки в шаблоне f-строки. ВИДИМЫЙ и заведомо не число: мерка,
#: подставившая сюда цифру, нашла бы претензию, которой в дереве нет.
COMPUTED_MARK = "⟪вычисляется⟫"


def read_markdown_carrier(root: Path, carrier: str) -> tuple[list[dict], list[str], str]:
    """Записи markdown-носителя. Возврат ``(записи, непрочитанные, причина)``.

    Причина непуста ⇒ **НЕ ИЗМЕРЕНО** о носителе целиком: «каталога нет» и
    «претензий нет» — разные состояния (инв. #17). Отдельный файл, который не
    читается или не декодируется, уходит в ``непрочитанные`` ПОИМЁННО и в
    ноль не схлопывается.
    """
    spec = CARRIER_PATHS.get(carrier)
    if spec is None:
        return [], [], f"носитель {carrier!r} не объявлен в CARRIER_PATHS"
    rel, mask = spec
    base = Path(root) / rel
    if not base.is_dir():
        return [], [], f"каталога носителя нет: {base}"
    records: list[dict] = []
    unread: list[str] = []
    files = 0
    for path in sorted(base.glob(mask)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unread.append(f"{path}: {type(exc).__name__}: {exc}")
            continue
        files += 1
        for rec in markdown_records(text):
            rec["file"] = str(path.relative_to(root))
            records.append(rec)
    if not files and not unread:
        return [], [], (f"в каталоге носителя нет ни одного файла по маске "
                        f"{mask}: {base}")
    return records, unread, ""


def carrier_census(carrier: str, *, records: list[dict], markup: bool,
                   files: int = 0, unread: list[str] | None = None,
                   canonical: dict | None = None,
                   canonical_reason: str = "") -> dict:
    """Перепись претензий ОДНОГО носителя. Записи — ВХОД, а не чтение.

    Вилка населения объявлена ЗДЕСЬ, и у её краёв разный смысл:

    * **нижний край** — претензии, у которых ось цитаты ОТВЕТИЛА «не цитата»
      и номера прогона нет: подтверждённые члены класса;
    * **верхний край** — нижний плюс те, у которых ось цитаты НЕ ОТВЕТИЛА
      (незакрытый открыватель). Назвать одно число вместо вилки значило бы
      выдать неизвестное за ноль либо за находку.

    «НЕ РАЗОБРАНО» (файл не прочитан) — число ОТДЕЛЬНОЕ: оно не входит ни в
    один край, потому что о его содержимом не известно ничего.
    """
    doc: dict = {
        "carrier": carrier,
        "markup": markup,
        "files": files,
        "records": len(records),
        "unread_files": list(unread or []),
        "claims": [],
        "by_kind": {k: 0 for k in KINDS},
        "duration_not_a_count": 0,
        # СПОСОБНОСТЬ оси «цитата не ответила» сработать, измеренная на ВСЕХ
        # записях носителя. Без этого числа ноль в `quotation_undecided` был
        # бы неотличим от закрытой дороги: ось, спрашивающая свой же пустой
        # перечень, отвечает О СЕБЕ, а не о мире.
        "records_with_unclosed_opener": 0,
        "status": "OK",
        "unmeasured": [],
    }
    for rec in records:
        text = rec.get("text") or ""
        if (not rec.get("fenced") and not rec.get("blockquote")
                and unclosed_opener(text, markup=markup) >= 0):
            doc["records_with_unclosed_opener"] += 1
        for seg in claim_segments(text):
            row = classify_claim(seg["segment"], line=text, start=seg["start"],
                                 canonical=canonical,
                                 canonical_reason=canonical_reason,
                                 markup=markup,
                                 fenced=bool(rec.get("fenced")),
                                 blockquote=bool(rec.get("blockquote")))
            # Личность записи ПРОНОСИТСЯ как есть: у markdown это файл и
            # строка, у announce-лога — отметка времени и сессия. Своя форма
            # у каждого носителя сделала бы находки несравнимыми.
            for key in ("file", "line", "ts", "session"):
                if key in rec:
                    row[key] = rec[key]
            row["mark"] = seg["mark"]
            doc["claims"].append(row)
            doc["by_kind"][row["kind"]] += 1
            if row.get("duration_not_a_count"):
                doc["duration_not_a_count"] += 1

    by = doc["by_kind"]
    doc["population_floor"] = by[UNFALSIFIABLE]
    doc["population_ceiling"] = by[UNFALSIFIABLE] + by[QUOTATION_UNDECIDED]
    doc["unfalsifiable_with_cause"] = sum(
        1 for c in doc["claims"] if c["kind"] == UNFALSIFIABLE and c.get("cause"))
    doc["findings"] = [c for c in doc["claims"] if c["kind"] in FINDING_KINDS]
    if doc["unread_files"]:
        doc["unmeasured"].append(
            f"файлов НЕ ПРОЧИТАНО {len(doc['unread_files'])} — это НЕ ноль: "
            + "; ".join(doc["unread_files"][:3]))
    if doc["findings"]:
        doc["status"] = "FINDING"
    return doc


def digest_census(root: Path) -> dict:
    """Носитель «утренняя сводка владельцу»: НАБЛЮДЁННОГО текста нет.

    Два вопроса, и их нельзя путать. «Что сводка СКАЗАЛА» — не ответим: её
    текст уходит в Telegram и на диск не ложится ни одной копией, поэтому
    исход `UNMEASURED` с названной причиной. «СПОСОБНА ли она сказать
    претензию без личности» — ответим статически, ТЕМИ ЖЕ дверьми разбора по
    строковым литералам производителя; своей копии разбора здесь нет.

    Замер 27.11: литералов с маркером претензии **10**, из них несущих ЧИСЛО
    упавших — **0**, несущих ДЛИТЕЛЬНОСТЬ красноты — есть, и это РАЗНЫЕ
    утверждения (см. ``DURATION_TAILS``): длина серии принадлежит заданию, а
    не одному прогону, и перемеряется номером последнего зелёного.
    """
    doc: dict = {
        "carrier": CARRIER_DIGEST,
        "producer": DIGEST_PRODUCER,
        "status": "UNMEASURED",
        "files": 0,
        "records": 0,
        "claims": [],
        "by_kind": {k: 0 for k in KINDS},
        "findings": [],
        "unread_files": [],
        "duration_not_a_count": 0,
        "population_floor": 0,
        "population_ceiling": 0,
        "unmeasured": ["носитель не хранит своего текста: сводка уходит в "
                       "Telegram и на диск не ложится ни одной копией — "
                       "НАБЛЮДЁННОГО населения у него нет"],
        "literals_with_mark": 0,
        "literals_with_count": 0,
        "literals_with_duration": 0,
        "literals_with_cause": 0,
        "literals_with_run_id": 0,
        # Третий исход СТАТИЧЕСКОЙ половины (инв. #17). Число в сводке
        # ВЫЧИСЛЯЕТСЯ — `f"«{name}» красное {days:.1f} суток"`, — и в дереве
        # литералом не лежит ни одно из них. Молчи мерка об этом, и «со
        # СЧЁТОМ упавших 0» читалось бы как «производитель чисел не печатает»,
        # то есть мерка ответила бы О СЕБЕ: это ровно та подмена, против
        # которой написан весь прибор.
        "templates_with_computed_number": 0,
    }
    path = Path(root) / DIGEST_PRODUCER
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        doc["unmeasured"].append(
            f"производитель не прочитан ({path}): {type(exc).__name__}: {exc}")
        return doc
    try:
        import ast as _ast
        tree = _ast.parse(src)
    except SyntaxError as exc:
        doc["unmeasured"].append(f"производитель не разобран: {exc}")
        return doc
    # Части f-строки — тоже `Constant`, и `ast.walk` выдаёт их ОТДЕЛЬНО от
    # самого шаблона. Не отметь их — и литерал с числом внутри f-строки
    # посчитался бы ДВАЖДЫ: один раз как шаблон, другой как своя часть.
    inside_template = {id(part)
                       for n in _ast.walk(tree)
                       if isinstance(n, _ast.JoinedStr)
                       for part in n.values}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.JoinedStr):
            # Шаблон f-строки: подстановка заменяется ВИДИМЫМ знаком, а не
            # выдуманным числом. Выдумай его — и мерка нашла бы претензию,
            # которой в дереве нет, поэтому знак ПРОВЕРЯЕТСЯ той же дверью
            # чтения: претензию он составить не должен.
            text = "".join(
                part.value if (isinstance(part, _ast.Constant)
                               and isinstance(part.value, str))
                else COMPUTED_MARK
                for part in node.values)
            for seg in claim_segments(text):
                if COMPUTED_MARK not in seg["segment"]:
                    # Число в шаблоне стои́т ЛИТЕРАЛОМ — это обычная
                    # претензия, и мерить её третьим исходом неверно.
                    got = read_claim(seg["segment"])
                    if got["count"] is not None:
                        doc["literals_with_count"] += 1
                        doc["literals_with_mark"] += 1
                    continue
                got = read_claim(seg["segment"])
                if got["count"] is not None:
                    # САМ знак подстановки прочитался как число упавших:
                    # дефект МЕРКИ, а не наблюдение о дереве.
                    doc["unmeasured"].append(
                        f"знак подстановки {COMPUTED_MARK!r} сам читается как "
                        f"счёт упавших ({got['count']}) — мерка выдумала бы "
                        f"претензию, которой в дереве нет")
                    continue
                doc["templates_with_computed_number"] += 1
            continue
        if not (isinstance(node, _ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in inside_template:
            continue
        for seg in claim_segments(node.value):
            got = read_claim(seg["segment"])
            doc["literals_with_mark"] += 1
            if got["count"] is not None:
                doc["literals_with_count"] += 1
            if got["duration_not_a_count"]:
                doc["literals_with_duration"] += 1
            if got["cause"] is not None:
                doc["literals_with_cause"] += 1
            if got["run_ids"]:
                doc["literals_with_run_id"] += 1
    if doc["templates_with_computed_number"]:
        doc["unmeasured"].append(
            f"шаблонов f-строки с маркером претензии и ВЫЧИСЛЯЕМЫМ значением "
            f"{doc['templates_with_computed_number']} — несут ли они число, "
            f"по дереву НЕ ВИДНО: литералом ни одно из этих чисел не лежит")
    return doc


def run_census(*, data_dir: str | os.PathLike | None = None,
               repo_root: str | os.PathLike | None = None,
               canonical: dict | None = None,
               canonical_reason: str = "",
               ask_canonical: bool = False,
               runner=None,
               carrier_root: str | os.PathLike | None = None) -> dict:
    """Перепись претензий о CI по ВСЕМ объявленным носителям.

    ``data_dir`` — ВХОД, а не расположение прибора: из worktree живого
    ``data/`` нет по построению, и прибор, молча вернувшийся к своему дереву,
    отвечал бы на СВОЙ вопрос (урок ADR-1107/1108). Выбор ПЕЧАТАЕТСЯ.

    ``carrier_root`` — дерево КОНТЕНТА для markdown-носителей, и это ТРЕТИЙ
    вход, а не повтор ``repo_root``. Причина измерена: трекер и `docs/journal`
    прод-дерева расходятся с origin по построению (прод-`docs/journal` на 12
    днях из 14 структурно пуст), поэтому население, снятое там, есть ответ о
    ПРОД-ДЕРЕВЕ, а не о проекте. Умолчание — ``repo_root``, и выбор
    ПЕЧАТАЕТСЯ вместе с числом прочитанных файлов: подставь прибор чужое
    дерево молча — и читатель не узнал бы, о чьём носителе ему ответили
    (§ поправка #1031 `.claude/rules/deployment.md`).
    """
    root = Path(repo_root or _ROOT)
    croot = Path(carrier_root) if carrier_root is not None else root
    named = data_dir is not None
    ddir = Path(data_dir) if named else root / "data"
    path = ddir / "session_changes.jsonl"

    doc: dict = {
        "status": "OK",
        "data_dir": str(ddir),
        "data_dir_named": named,
        "announce_path": str(path),
        "kinds_declared": list(KINDS),
        "records": 0,
        "unparsed_records": 0,
        "claims": [],
        "by_kind": {k: 0 for k in KINDS},
        "canonical_run": None,
        "canonical_failed": None,
        "canonical_reason": canonical_reason,
        "unmeasured": [],
        "carrier_root": str(croot),
        "carrier_root_named": carrier_root is not None,
        "carriers_declared": list(CARRIERS),
        "carriers": {},
    }

    rows, bad, why = read_announce(path)
    doc["unparsed_records"] = bad
    announce_unread = bool(why)
    if announce_unread:
        # Непрочитанный announce-лог НЕ ЗАПИРАЕТ остальные три носителя:
        # «один носитель не прочитан» и «о классе ничего не известно» —
        # разные состояния, и схлопывать первое во второе значило бы терять
        # измеримое ради неизмеримого.
        rows = []
        doc["status"] = "UNMEASURED"
        doc["unmeasured"].append(f"announce-лог не прочитан ({path}): {why}")
    doc["records"] = len(rows)

    if canonical is None and ask_canonical:
        canonical, canonical_reason = canonical_verdict(root, runner=runner)
        doc["canonical_reason"] = canonical_reason
    elif canonical is None and not canonical_reason:
        doc["canonical_reason"] = ("канонического читателя не спрашивали "
                                   "(--ask-canonical не передан)")
    if canonical is not None:
        doc["canonical_run"] = str(((canonical.get("run") or {}).get("id")) or "")
        doc["canonical_failed"] = canonical.get("failed")

    # ── announce-лог идёт той же дверью, что и остальные три носителя ──────
    # Своя копия обхода у «главного» носителя означала бы, что счётчики у
    # четырёх носителей меряются РАЗНЫМ кодом: первая редакция так и была
    # написана, и у announce число «записей с незакрытым открывателем»
    # оказалось константой 0 — ЛОЖНЫЙ ноль, выглядевший как замер.
    ann = carrier_census(
        CARRIER_ANNOUNCE,
        records=[{"text": rec.get("summary") or "", "ts": rec.get("ts"),
                  "session": rec.get("session")} for rec in rows],
        markup=False, files=0 if announce_unread else 1,
        canonical=canonical, canonical_reason=doc["canonical_reason"])
    ann["records"] = doc["records"]
    doc["claims"] = ann["claims"]
    doc["by_kind"] = dict(ann["by_kind"])
    # Подось САМОГО ОПАСНОГО вида: претензия без прогона, но с НАЗВАННЫМ родом
    # падения. Именно она отправляет следующий цикл чинить то, чего нет, —
    # число рядом делает род убедительным.
    doc["unfalsifiable_with_cause"] = ann["unfalsifiable_with_cause"]
    findings = ann["findings"]
    doc["findings"] = findings
    doc["unmeasured_claims"] = sum(
        1 for c in doc["claims"] if c["kind"] in UNMEASURED_KINDS)
    if bad:
        doc["unmeasured"].append(
            f"записей announce-лога НЕ РАЗОБРАНО {bad} — это НЕ ноль")
        ann["unmeasured"].append(
            f"записей НЕ РАЗОБРАНО {bad} — это НЕ ноль")
    if announce_unread:
        ann["status"] = "UNMEASURED"
        ann["unmeasured"].append(f"announce-лог не прочитан ({path}): {why}")
    doc["carriers"][CARRIER_ANNOUNCE] = ann
    for carrier in (CARRIER_TRACKER, CARRIER_JOURNAL):
        records, unread, fatal = read_markdown_carrier(croot, carrier)
        if fatal:
            doc["carriers"][carrier] = {
                "carrier": carrier, "markup": True, "files": 0, "records": 0,
                "unread_files": unread, "claims": [],
                "by_kind": {k: 0 for k in KINDS}, "duration_not_a_count": 0,
                "population_floor": 0, "population_ceiling": 0,
                "unfalsifiable_with_cause": 0, "findings": [],
                "status": "UNMEASURED", "unmeasured": [fatal],
            }
            continue
        files = len({r["file"] for r in records})
        doc["carriers"][carrier] = carrier_census(
            carrier, records=records, markup=True, files=files, unread=unread,
            canonical=canonical, canonical_reason=doc["canonical_reason"])
    doc["carriers"][CARRIER_DIGEST] = digest_census(croot)

    missing = [c for c in CARRIERS if c not in doc["carriers"]]
    if missing:
        # Объявленный носитель, которого в ответе нет, — это НЕ ноль.
        doc["unmeasured"].append(
            "объявленные носители без ответа: " + ", ".join(missing))

    doc["findings_total"] = sum(len(c.get("findings") or [])
                                for c in doc["carriers"].values())
    doc["population_floor_total"] = sum(c.get("population_floor", 0)
                                        for c in doc["carriers"].values())
    doc["population_ceiling_total"] = sum(c.get("population_ceiling", 0)
                                          for c in doc["carriers"].values())
    if doc["findings_total"]:
        doc["status"] = "FINDING"
    return doc


def format_report(doc: dict) -> list[str]:
    lines: list[str] = []
    choice = "НАЗВАН" if doc.get("data_dir_named") else "УМОЛЧАНИЕ"
    lines.append(f"провенанс претензий о CI: каталог {doc['data_dir']} ({choice})")
    if doc["status"] == "UNMEASURED":
        for why in doc["unmeasured"]:
            lines.append(f"   [НЕ ИЗМЕРЕНО] {why}")
        return lines
    by = doc["by_kind"]
    lines.append(f"   записей {doc['records']} · претензий о прогоне "
                 f"{len(doc['claims'])} · НЕ РАЗОБРАНО записей "
                 f"{doc['unparsed_records']}")
    lines.append(f"   цитат чужой претензии {by[QUOTED]} (население не "
                 f"удваивается)")
    lines.append(f"   без претензии {by[NO_CLAIM]} · НЕОПРОВЕРЖИМЫХ "
                 f"{by[UNFALSIFIABLE]} · число сверено {by[COUNT_AGREES]} · "
                 f"число РАСХОДИТСЯ {by[COUNT_DIFFERS]} · род НЕ СВЕРЕН "
                 f"{by[CAUSE_UNVERIFIED]}")
    lines.append(f"   из НЕОПРОВЕРЖИМЫХ несут РОД падения: "
                 f"{doc.get('unfalsifiable_with_cause', 0)} — это самый "
                 f"дорогой вид: число рядом делает непроверенный род "
                 f"убедительным")
    lines.append(f"   НЕ ИЗМЕРЕНО: вне окна читателя {by[OUT_OF_WINDOW]} · "
                 f"читатель не спрошен {by[NO_CANONICAL]} · форма не разобрана "
                 f"{by[UNPARSED]} — нулём это не считается")
    if doc.get("canonical_run"):
        lines.append(f"   канонический читатель: прогон {doc['canonical_run']}, "
                     f"упавших {doc['canonical_failed']}")
    elif doc.get("canonical_reason"):
        lines.append(f"   канонический читатель НЕ ОТВЕТИЛ: {doc['canonical_reason']}")
    for c in doc.get("findings", []):
        head = {UNFALSIFIABLE: "НЕОПРОВЕРЖИМО",
                COUNT_DIFFERS: "ЧИСЛО РАСХОДИТСЯ",
                CAUSE_UNVERIFIED: "РОД НЕ СВЕРЕН"}[c["kind"]]
        lines.append(f"   🚨 {head}  {c.get('ts')}: {c['reason']}")
        lines.append(f"        претензия: {c['segment'][:160]}")
    for why in doc.get("unmeasured", []):
        lines.append(f"   [НЕ ИЗМЕРЕНО] {why}")
    if not doc.get("findings"):
        lines.append("   ✅ находок нет: каждая претензия либо называет свой "
                     "прогон, либо ничего не утверждает")
    lines.extend(format_carriers(doc))
    lines.append("   форма, которой претензия становится перемеряемой: номер "
                 "прогона В СВОЁМ сегменте, а число и род — у "
                 "scripts/ci_control_verdict.py")
    lines.append("   ADVISORY: прибор только ЧИТАЕТ — announce-лог, карточки и "
                 "data/ не меняются")
    return lines


def format_carriers(doc: dict) -> list[str]:
    """Строки о ЧЕТЫРЁХ носителях: вилка населения и «не разобрано» отдельно."""
    carriers = doc.get("carriers") or {}
    if not carriers:
        return ["   [НЕ ИЗМЕРЕНО] носители не спрашивались: в документе нет "
                "ключа `carriers` — нулём это не считается"]
    choice = "НАЗВАНО" if doc.get("carrier_root_named") else "УМОЛЧАНИЕ"
    lines = [f"   носители ({len(carriers)} из "
             f"{len(doc.get('carriers_declared') or CARRIERS)} объявленных), "
             f"дерево контента {doc.get('carrier_root')} ({choice})"]
    for name in (doc.get("carriers_declared") or CARRIERS):
        c = carriers.get(name)
        if c is None:
            lines.append(f"     · {name}: [НЕ ИЗМЕРЕНО] носитель объявлен, но "
                         f"ответа о нём нет — это НЕ ноль")
            continue
        floor = c.get("population_floor", 0)
        ceil = c.get("population_ceiling", 0)
        bracket = (f"{floor}" if floor == ceil
                   else f"НЕ МЕНЬШЕ {floor} и НЕ БОЛЬШЕ {ceil}")
        lines.append(
            f"     · {name}: файлов {c.get('files', 0)} · записей "
            f"{c.get('records', 0)} · претензий {len(c.get('claims') or [])} · "
            f"ПРЕДМЕТ {bracket} · цитат {c['by_kind'][QUOTED]} · "
            f"ось цитаты НЕ ОТВЕТИЛА {c['by_kind'][QUOTATION_UNDECIDED]} "
            f"(записей с незакрытым открывателем "
            f"{c.get('records_with_unclosed_opener', 0)} — ось СПОСОБНА "
            f"сработать) · длительность, а не счёт упавших "
            f"{c.get('duration_not_a_count', 0)} · НЕ РАЗОБРАНО файлов "
            f"{len(c.get('unread_files') or [])}")
        for why in c.get("unmeasured") or []:
            lines.append(f"       [НЕ ИЗМЕРЕНО] {why}")
        if name == CARRIER_DIGEST:
            lines.append(
                f"       СПОСОБНОСТЬ производителя {c.get('producer')} "
                f"(статически, теми же дверьми): литералов с маркером "
                f"{c.get('literals_with_mark', 0)} · со СЧЁТОМ упавших "
                f"{c.get('literals_with_count', 0)} · с ДЛИТЕЛЬНОСТЬЮ "
                f"{c.get('literals_with_duration', 0)} · с РОДОМ "
                f"{c.get('literals_with_cause', 0)} · с НОМЕРОМ прогона "
                f"{c.get('literals_with_run_id', 0)} · ШАБЛОНОВ с вычисляемым "
                f"значением {c.get('templates_with_computed_number', 0)} "
                f"(их число по дереву НЕ ВИДНО)")
        for f in (c.get("findings") or [])[:4]:
            where = (f"{f.get('file')}:{f.get('line')}" if f.get("file")
                     else str(f.get("ts")))
            lines.append(f"       🚨 {where}: {f['segment'][:120]}")
    lines.append(
        f"   ПРЕДМЕТ по всем носителям: НЕ МЕНЬШЕ "
        f"{doc.get('population_floor_total', 0)} и НЕ БОЛЬШЕ "
        f"{doc.get('population_ceiling_total', 0)} — одно число вместо вилки "
        f"выдало бы неизвестное за ноль либо за находку")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Провенанс претензии о контрольном прогоне CI: называет ли "
                    "она прогон, которым её можно перемерить.")
    ap.add_argument("--data-dir", help="каталог артефактов (ВХОД, не "
                                       "расположение прибора); выбор печатается")
    ap.add_argument("--repo-root", help="дерево, из которого берётся "
                                        "канонический читатель")
    ap.add_argument("--carrier-root",
                    help="дерево КОНТЕНТА для markdown-носителей (карточки "
                         "трекера, docs/journal) и производителя утренней "
                         "сводки. Умолчание — --repo-root; выбор печатается, "
                         "потому что прод-дерево расходится с origin по "
                         "построению")
    ap.add_argument("--ask-canonical", action="store_true",
                    help="спросить scripts/ci_control_verdict.py (сеть). Без "
                         "него претензии с НАЗВАННЫМ прогоном получают "
                         "«НЕ ИЗМЕРЕНО» с причиной, а не вердикт")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.data_dir is not None and not Path(args.data_dir).is_dir():
        print(f"[НЕ ИЗМЕРЕНО] названный каталог не читается: {args.data_dir}",
              file=sys.stderr)
        return 2

    if args.carrier_root is not None and not Path(args.carrier_root).is_dir():
        print(f"[НЕ ИЗМЕРЕНО] названное дерево контента не читается: "
              f"{args.carrier_root}", file=sys.stderr)
        return 2

    doc = run_census(data_dir=args.data_dir, repo_root=args.repo_root,
                     ask_canonical=args.ask_canonical,
                     carrier_root=args.carrier_root)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in format_report(doc):
            print(line)
    # Находка ОБГОНЯЕТ «не измерено»: класс, названный хотя бы у одного
    # носителя, обязан быть видим кодом возврата, а нижняя граница населения
    # СКАЗАНА строкой. Обратный порядок прятал бы находку за непрочитанным
    # соседом (тот же выбор, что у шага 1е-2).
    if doc.get("findings") or doc.get("findings_total"):
        return 1
    if doc["status"] == "UNMEASURED":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
