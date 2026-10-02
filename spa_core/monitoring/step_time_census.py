#!/usr/bin/env python3
"""Куда уходит время шага тестов — замер по потоковой записи прогона (заказ G87 п. 3).

**Зачем (цикл #747, 2026-10-02, ADR-534).** Шаг `Run spa_core unit tests` в
`.github/workflows/test.yml` носит границу `timeout-minutes: 240`, и в комментарии
рядом прямо написано: «240 — по-прежнему ГРАНИЦА ЗАВИСАНИЯ, а не бюджет. Настоящую
длительность шага измерит первый ДОШЕДШИЙ прогон, и до него она остаётся НЕ ИЗМЕРЕННОЙ».
Заказ G87 п. 3 (ADR-491, 25.09) требует не поднять границу, а спросить, **ГДЕ уходит
время**, и мерить это у записи, а не экстраполяцией двух чисел в третье (ADR-473).

Предпосылка появилась только с ADR-528: до него `reports/` не выгружался ничем, и
запись умирала вместе с раннером. Теперь она переживает его артефактом.

**Что меряет прибор.** Одно: СЕКУНДЫ прогона, разложенные по названным корзинам, сумма
которых РАВНА размаху записи. Тождество учёта — не украшение: без него «где уходит
время» отвечается долей от доли, и остаток молча исчезает (инв. #17).

    размах = до первого случая + Σ(случай) + после последнего случая

`до первого случая` — сбор и ввоз модулей: плагин пишет строку `session` в
`pytest_configure`, то есть ДО сбора. `случай` — от своего `start` до `start`
следующего, поэтому разборка предыдущего теста и работа каркаса между тестами лежат
в случае, а не в безымянном остатке.

**Чего прибор НЕ утверждает — и это существенно:**

* **Размах ≤ длительности шага.** Часы здесь принадлежат плагину, а он включается в
  `pytest_configure`: старт интерпретатора, ввоз самого pytest и работа оболочки шага
  в размах не входят. Ошибка в сторону ЗАНИЖЕНИЯ, названа числом быть не может —
  у записи нет стороннего времени, с которым её сверить.
* **Нет строки `end` ⇒ бюджет НЕ ИЗМЕРЕН.** Размах оборванной сессии есть нижняя
  граница, и выдать его за длительность шага значило бы ровно то, что запрещает
  ADR-473. Доли при этом считаются честно — но от наблюдённого размаха, а не от
  «сколько шло бы».
* **Вердикта о наборе прибор не выносит.** Предмет здесь — секунды, а не исходы.

**Поле `d` несёт НЕ длительность случая, и это замер, а не оговорка.** Писатель
(`spa_core/ci/pytest_stream_record.py`) кладёт `d` из `report.duration` отчёта фазы
`call` у прошедших и той фазы, на которой упал, — у упавших. Установка и разборка
фикстур в `d` не попадают никогда. Поэтому прибор считает `d` ОТДЕЛЬНОЙ осью и
печатает её рядом с наблюдёнными фазами: разница и есть время, которого не несёт
ни одно поле записи.

**Порог `--timeout` ЧИТАЕТСЯ ИЗ ЗАПИСИ**, а не берётся из текста воркфлоу: строка
`session` несёт `args` прогона. Нет аргумента ⇒ порог `None`, и вопрос «клин или
медленный тест» объявляется НЕ ИЗМЕРЕННЫМ, а не отвечается числом 180 по памяти
(`.claude/rules/site-numbers.md` поймала на этом сама себя).

Прибор только ЧИТАЕТ (`applied=False`): ни тестов, ни воркфлоу, ни порогов он не
трогает. Только stdlib (инв. #4).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, NamedTuple

# Имена исходов чтения записи — часть контракта, читаются тестами и ci_verdict.
READ_OK = "read"
READ_ABSENT = "record_absent"
READ_UNREADABLE = "record_unreadable"
READ_NO_SESSION = "no_session_header"
READ_EMPTY = "no_events"

# Пороги, по которым считается концентрация. ВЫБОР, объявленный входом: сами по себе
# они ничего не доказывают, но без лестницы «33 случая стоят треть шага» негде увидеть.
DEFAULT_BUCKETS_S = (60.0, 10.0, 1.0, 0.1)

# Сколько строк печатать в выжимке. Остаток НАЗЫВАЕТСЯ числом, а не отбрасывается.
_NAMES_SHOWN = 10


class Case(NamedTuple):
    """Один случай прогона. ``to_outcome`` = ``None`` ⇒ исхода у случая нет вовсе."""

    nodeid: str
    start: float
    span: float                 # start → start следующего случая (или до конца записи)
    to_outcome: float | None    # start → последний исход этого же nodeid
    declared_d: float | None    # сумма поля `d` у исходов случая
    outcome: str | None         # ok / fail / skip; None = исхода нет

    @property
    def after_outcome(self) -> float | None:
        """Хвост случая, который не назвало ни одно событие (разборка + каркас)."""
        if self.to_outcome is None:
            return None
        return self.span - self.to_outcome

    @property
    def file(self) -> str:
        return self.nodeid.split("::", 1)[0]


class Census(NamedTuple):
    """Итог замера одной сессии. ``read`` != READ_OK ⇒ все числа ниже бессмысленны."""

    read: str
    reason: str
    # --- тождество учёта: сумма трёх равна size ---
    span_s: float
    before_first_case_s: float
    inside_cases_s: float
    after_last_case_s: float
    # --- оси, в сумму НЕ входящие ---
    observed_phases_s: float          # Σ (start → исход)
    unnamed_between_s: float          # Σ (исход → следующий start)
    declared_d_s: float               # Σ поля `d`
    # --- население и третьи исходы ---
    cases: tuple[Case, ...]
    ended: bool                       # есть строка `end`
    torn_lines: int
    cases_without_outcome: int
    backwards_clock: int
    sessions_in_record: int
    timeout_s: float | None           # прочитан из args сессии
    args: tuple[str, ...]

    @property
    def measured_budget(self) -> bool:
        """Можно ли назвать размах длительностью шага. Нет `end` ⇒ нельзя."""
        return self.read == READ_OK and self.ended

    def identity_holds(self, tolerance: float = 1e-6) -> bool:
        total = self.before_first_case_s + self.inside_cases_s + self.after_last_case_s
        return abs(total - self.span_s) <= tolerance


def _unreadable(kind: str, reason: str) -> Census:
    return Census(
        read=kind, reason=reason, span_s=0.0, before_first_case_s=0.0,
        inside_cases_s=0.0, after_last_case_s=0.0, observed_phases_s=0.0,
        unnamed_between_s=0.0, declared_d_s=0.0, cases=(), ended=False,
        torn_lines=0, cases_without_outcome=0, backwards_clock=0,
        sessions_in_record=0, timeout_s=None, args=(),
    )


def parse_lines(lines: Iterable[str]) -> tuple[list[dict], int]:
    """Разобрать строки JSONL. Второе число — строк, НЕ разобранных как JSON.

    Оборванный хвост здесь ожидаем по построению (процесс убивают посреди записи), и
    он СЧИТАЕТСЯ, а не выбрасывается молча: молчаливый пропуск и есть та безымянность,
    против которой вся запись заведена.
    """
    events: list[dict] = []
    torn = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            torn += 1
            continue
        if not isinstance(event, dict) or "e" not in event:
            torn += 1
            continue
        events.append(event)
    return events, torn


def _timeout_from_args(args: Iterable[str]) -> float | None:
    """Порог `--timeout` прогона, прочитанный У ЗАПИСИ. Нет аргумента ⇒ ``None``.

    ``None`` — третий исход, а не 180: подставить сюда число из текста воркфлоу
    значило бы судить о КЛИНЕ по чужой константе, которая могла смениться.
    """
    items = list(args)
    for i, raw in enumerate(items):
        token = str(raw)
        if token.startswith("--timeout="):
            try:
                return float(token.split("=", 1)[1])
            except ValueError:
                return None
        if token == "--timeout" and i + 1 < len(items):
            try:
                return float(items[i + 1])
            except ValueError:
                return None
    return None


def census_from_events(events: list[dict], *, torn_lines: int = 0) -> Census:
    """Разложить размах последней сессии записи по корзинам.

    **Берётся ПОСЛЕДНЯЯ сессия.** Писатель открывает файл на дозапись, поэтому один
    путь может нести несколько сессий; смешать их значило бы сложить два размаха в
    один и получить число, которого не было ни у одного прогона. Их количество
    печатается рядом — чтобы «одна сессия» было замером, а не допущением.
    """
    if not events:
        return _unreadable(READ_EMPTY, "в записи нет ни одного события")

    heads = [i for i, ev in enumerate(events) if ev.get("e") == "session"]
    if not heads:
        return _unreadable(
            READ_NO_SESSION,
            "в записи нет строки `session`: без неё неизвестно, когда прогон начался, "
            "и размах был бы посчитан от первого попавшегося события",
        )
    block = events[heads[-1]:]
    head = block[0]
    args = tuple(str(a) for a in (head.get("args") or []))

    t_session = _as_float(head.get("t"))
    if t_session is None:
        return _unreadable(
            READ_NO_SESSION,
            "у строки `session` нет читаемой отметки времени `t`",
        )

    starts: list[tuple[int, str, float]] = []
    outcomes: dict[str, list[tuple[float, str, float | None]]] = {}
    ended = False
    backwards = 0
    last_t = t_session
    t_last_event = t_session

    for pos, ev in enumerate(block):
        t = _as_float(ev.get("t"))
        if t is None:
            continue
        if t < last_t:
            backwards += 1
        last_t = max(last_t, t)
        t_last_event = max(t_last_event, t)
        kind = ev.get("e")
        if kind == "start":
            node = str(ev.get("n") or "")
            if node:
                starts.append((pos, node, t))
        elif kind in ("ok", "fail", "skip"):
            node = str(ev.get("n") or "")
            if node:
                outcomes.setdefault(node, []).append((t, str(kind), _as_float(ev.get("d"))))
        elif kind == "end":
            ended = True

    span = t_last_event - t_session
    if not starts:
        # Сессия есть, случаев нет: сбор не дошёл до первого теста либо набор пуст.
        # Это НЕ «ноль времени в случаях», а отсутствие населения — называем словом.
        return Census(
            read=READ_OK,
            reason="в сессии нет ни одного случая: сбор не дошёл до первого теста "
                   "(или набор пуст) — раскладывать по случаям нечего",
            span_s=span, before_first_case_s=span, inside_cases_s=0.0,
            after_last_case_s=0.0, observed_phases_s=0.0, unnamed_between_s=0.0,
            declared_d_s=0.0, cases=(), ended=ended, torn_lines=torn_lines,
            cases_without_outcome=0, backwards_clock=backwards,
            sessions_in_record=len(heads), timeout_s=_timeout_from_args(args), args=args,
        )

    before_first = starts[0][2] - t_session
    cases: list[Case] = []
    without_outcome = 0

    for idx, (pos, node, t_start) in enumerate(starts):
        # Закрытие случая: следующий `start`, а для последнего — последнее событие
        # записи. Так разборка фикстур и работа каркаса между тестами попадают в
        # случай, а не в безымянный остаток.
        close = starts[idx + 1][2] if idx + 1 < len(starts) else t_last_event
        span_i = max(0.0, close - t_start)
        own = [o for o in outcomes.get(node, []) if t_start <= o[0] <= close]
        if own:
            to_outcome = max(0.0, own[-1][0] - t_start)
            declared = sum(d for _, _, d in own if d is not None)
            outcome = own[-1][1]
        else:
            to_outcome = None
            declared = None
            outcome = None
            without_outcome += 1
        cases.append(Case(node, t_start, span_i, to_outcome, declared, outcome))

    inside = sum(c.span for c in cases)
    after_last = max(0.0, span - before_first - inside)
    observed = sum(c.to_outcome for c in cases if c.to_outcome is not None)
    unnamed = sum(c.after_outcome for c in cases if c.after_outcome is not None)
    declared_total = sum(c.declared_d for c in cases if c.declared_d is not None)

    return Census(
        read=READ_OK, reason="", span_s=span, before_first_case_s=before_first,
        inside_cases_s=inside, after_last_case_s=after_last,
        observed_phases_s=observed, unnamed_between_s=unnamed,
        declared_d_s=declared_total, cases=tuple(cases), ended=ended,
        torn_lines=torn_lines, cases_without_outcome=without_outcome,
        backwards_clock=backwards, sessions_in_record=len(heads),
        timeout_s=_timeout_from_args(args), args=args,
    )


def _as_float(value: object) -> float | None:
    """Число или ``None``. Отсутствие отметки — не ноль (инв. #17)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def census_from_path(path: Path | None) -> Census:
    """Прочитать запись с диска. Нет файла ⇒ НАЗВАННЫЙ третий исход, а не нули."""
    if path is None:
        return _unreadable(READ_ABSENT, "путь к потоковой записи не передан")
    if not path.exists():
        return _unreadable(READ_ABSENT, f"потоковой записи нет ({path})")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _unreadable(READ_UNREADABLE, f"запись не прочитана ({path}): {exc}")
    events, torn = parse_lines(text.splitlines())
    return census_from_events(events, torn_lines=torn)


# --- производные переписи ---------------------------------------------------

def by_file(census: Census) -> Counter:
    """Секунды случаев, сложенные по файлу теста."""
    out: Counter = Counter()
    for case in census.cases:
        out[case.file] += case.span
    return out


def concentration(census: Census, buckets: Iterable[float] = DEFAULT_BUCKETS_S) -> list[tuple[float, int, float]]:
    """Лестница «случаев дороже X секунд»: (порог, сколько, сколько секунд)."""
    rows = []
    for threshold in buckets:
        chosen = [c.span for c in census.cases if c.span >= threshold]
        rows.append((threshold, len(chosen), sum(chosen)))
    return rows


def at_or_beyond_limit(census: Census) -> tuple[int, int]:
    """(на пороге или выше, пережили порог вдвое) — по НАБЛЮДЁННЫМ фазам случая.

    Порог `--timeout` у pytest-timeout действует на ФАЗУ (setup/call/teardown), а
    наблюдённое время случая покрывает setup+call — поэтому «на пороге или выше» есть
    подозрение, а не улика. Уликой служит второе число: случай, проживший ВДВОЕ
    дольше порога, порог заведомо пережил, и это уже свойство клина, а не теста
    (SIGALRM не прерывает блокировку в C-коде — оговорка ADR-474).
    Порога нет ⇒ (-1, -1): «не измерено», а не два нуля.
    """
    if census.timeout_s is None:
        return (-1, -1)
    at = sum(1 for c in census.cases if c.to_outcome is not None and c.to_outcome >= census.timeout_s)
    over = sum(1 for c in census.cases if c.to_outcome is not None and c.to_outcome >= 2 * census.timeout_s)
    return (at, over)


def format_census(census: Census, *, label: str = "шаг тестов", shown: int = _NAMES_SHOWN) -> str:
    """Выжимка для лога. Вердикта не выносит и кода возврата не трогает."""
    if census.read != READ_OK:
        return f"   время {label}: {census.reason}"
    if not census.cases:
        return f"   время {label}: {census.reason}"

    span = census.span_s
    pct = (lambda v: f"{100.0 * v / span:.1f} %" if span > 0 else "НЕ ИЗМЕРЕНО")
    lines = []
    if census.measured_budget:
        head = f"размах сессии {span / 60:.1f} мин ({span:.0f} с) — сессия ДОШЛА до конца"
    else:
        head = (f"размах сессии {span / 60:.1f} мин ({span:.0f} с) — НИЖНЯЯ ГРАНИЦА: "
                f"строки `end` нет, бюджет шага НЕ ИЗМЕРЕН")
    lines.append(f"   время {label}: {head} · случаев {len(census.cases)}")
    lines.append(
        f"   раскладка (сумма равна размаху): сбор до первого случая {census.before_first_case_s:.0f} с "
        f"({pct(census.before_first_case_s)}) · в случаях {census.inside_cases_s:.0f} с "
        f"({pct(census.inside_cases_s)}) · после последнего {census.after_last_case_s:.0f} с "
        f"({pct(census.after_last_case_s)})"
    )
    # Три числа, а не одно: «сколько несёт поле», «сколько внутри наблюдённых фаз
    # оно НЕ несёт» (установка + остаток фазы) и «сколько лежит ПОСЛЕ исхода»
    # (разборка и каркас). Склеить их значило бы потерять, где именно время.
    lines.append(
        f"   поле `d` несёт {census.declared_d_s:.0f} с из {census.observed_phases_s:.0f} с наблюдённых фаз; "
        f"внутри фаз его не несёт {census.observed_phases_s - census.declared_d_s:.0f} с (установка), "
        f"после исхода — ещё {census.unnamed_between_s:.0f} с (разборка и каркас); "
        f"итого вне поля {census.inside_cases_s - census.declared_d_s:.0f} с"
    )
    for threshold, count, total in concentration(census):
        lines.append(
            f"   случаев ≥ {threshold:g} с: {count} — {total:.0f} с ({pct(total)} размаха)"
        )
    at, over = at_or_beyond_limit(census)
    if at < 0:
        lines.append("   порог `--timeout`: НЕ ИЗМЕРЕН (в args сессии его нет) — "
                     "клин от медленного теста здесь не отличить")
    else:
        lines.append(
            f"   порог `--timeout` прочитан у записи: {census.timeout_s:g} с · "
            f"случаев на пороге или выше {at} · прожили ВДВОЕ дольше порога {over} "
            f"(порог их не взял)"
        )
    third = []
    if census.torn_lines:
        third.append(f"строк не разобрано {census.torn_lines}")
    if census.cases_without_outcome:
        third.append(f"случаев без исхода {census.cases_without_outcome}")
    if census.backwards_clock:
        third.append(f"часы шли назад {census.backwards_clock} раз(а)")
    if census.sessions_in_record > 1:
        third.append(f"сессий в записи {census.sessions_in_record} — взята ПОСЛЕДНЯЯ")
    lines.append("   третьи исходы: " + ("; ".join(third) if third else "нет"))

    top = sorted(census.cases, key=lambda c: c.span, reverse=True)[:shown]
    for case in top:
        mark = "⏳" if case.outcome is None else "🔝"
        lines.append(f"   {mark} {case.span:7.1f} с  {case.nodeid}")
    if len(census.cases) > shown:
        rest = len(census.cases) - shown
        lines.append(f"   … и ещё {rest} случа(ев) дешевле перечисленных")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Куда уходит время шага тестов (заказ G87 п. 3, ADR-534). Только ЧИТАЕТ.",
    )
    parser.add_argument("record", type=Path, help="потоковая запись прогона (JSONL)")
    parser.add_argument("--label", default="spa_core/tests/")
    parser.add_argument("--top", type=int, default=_NAMES_SHOWN)
    parser.add_argument("--by-file", action="store_true", help="перепись по файлам теста")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    census = census_from_path(args.record)
    if args.json:
        print(json.dumps({
            "read": census.read, "reason": census.reason,
            "span_s": round(census.span_s, 3),
            "before_first_case_s": round(census.before_first_case_s, 3),
            "inside_cases_s": round(census.inside_cases_s, 3),
            "after_last_case_s": round(census.after_last_case_s, 3),
            "observed_phases_s": round(census.observed_phases_s, 3),
            "declared_d_s": round(census.declared_d_s, 3),
            "cases": len(census.cases), "ended": census.ended,
            "torn_lines": census.torn_lines,
            "cases_without_outcome": census.cases_without_outcome,
            "backwards_clock": census.backwards_clock,
            "sessions_in_record": census.sessions_in_record,
            "timeout_s": census.timeout_s,
            "identity_holds": census.identity_holds(),
            "top": [
                {"nodeid": c.nodeid, "span_s": round(c.span, 3),
                 "to_outcome_s": None if c.to_outcome is None else round(c.to_outcome, 3),
                 "declared_d_s": None if c.declared_d is None else round(c.declared_d, 3),
                 "outcome": c.outcome}
                for c in sorted(census.cases, key=lambda c: c.span, reverse=True)[:args.top]
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print(format_census(census, label=args.label, shown=args.top))
        if args.by_file:
            print("   — по файлам —")
            for name, total in by_file(census).most_common(args.top):
                print(f"   {total:8.1f} с  {name}")
    return 0 if census.read == READ_OK else 2


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
