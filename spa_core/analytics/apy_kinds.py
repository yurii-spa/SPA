"""Объявление РОДОВ числа, названного «APY» (приказ владельца «Portfolio CIO», §5 и §9).

Предмет — дословное требование владельца из якорного ТЗ
`inbox-task-portfolio-cio-dynamic-capital-alloc`:

    §5 «Paper APY ... Он выглядит потенциально несовместимым с displayed
    allocation/APY. Необходимо установить точную формулу Paper APY. Разделить:
    displayed APY · weighted position APY · gross portfolio APY · net portfolio
    APY · realized APY · paper/model APY. **Не допускать использования одного
    названия APY для разных экономических показателей.**»

    §9 «Текущий APY нельзя считать ожидаемой доходностью.»

Это тот же класс, что `.claude/rules/adapters.md` § «Одно имя — один объект»
(цикл #274: три РАЗНЫХ набора звались `ADAPTER_REGISTRY`, и три месяца врал
`house_view_gap`) и что поправка C2 ADR-580 к `.claude/rules/site-numbers.md`
(бэктест печатался с `kind="замер"`). Разница в том, что там предметом было ИМЯ
НАБОРА и РОД ЧИСЛА САЙТА, а здесь — род числа ВНУТРИ цикла, у которого рода не
было объявлено ВООБЩЕ.

Почему объявление, а не правка производителей
=============================================
Числа не «расходятся» — они отвечают на РАЗНЫЕ вопросы, и это законно. Незаконно
то, что вопрос не назван рядом с ответом: читатель, взявший любое из них как
«ставку книги», ошибается на величину, которую никто не печатает. Поэтому модуль
НИЧЕГО не считает и ничего не чинит — он ОБЪЯВЛЯЕТ, а мерит перепись
`apy_name_census` (она же единственный читатель этих перечней).

Контракт объявления — СВОЙ
==========================
У каждого рода обязаны быть заполнены все поля `ApyKind`, и у рода-ставки
(`is_rate=True`) обязаны быть названы `denominator` и `window`: ставка без
знаменателя и без окна есть намерение, а не число (дословный довод
`.claude/rules/site-numbers.md`). Это проверяет не литерал в тесте, а паритет с
самим объявлением (`validate()`), — иначе мерка и измеряемое разошлись бы молча
(урок ADR-940/943).

stdlib-only · LLM FORBIDDEN · только чтение · money-path не затронут.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Словари значений полей. ЗАМКНУТЫ намеренно: значение вне словаря — не новый
# род, а необъявленное число (fail-CLOSED), и `validate()` его назовёт.
# ---------------------------------------------------------------------------

#: КОГО описывает число.
SUBJECTS: Tuple[str, ...] = ("portfolio", "position", "none")

#: НА ЧТО делится годовая доходность, чтобы получить ставку. `None` — у числа,
#: которое ставкой не является (знаменателя у него нет, и ставить сюда "none"
#: значило бы выдать отсутствие за выбор).
DENOMINATORS: Tuple[str, ...] = ("nav", "deployed", "position", None)

#: ЗА КАКОЙ СРОК снято число.
WINDOWS: Tuple[str, ...] = ("today", "trailing_ring", "trailing_7d", None)

#: НА КАКИХ барах трека число имеет право стоять.
#: `evidenced_only` — только на доказанных (ADR-580 C2: бэктест/разогрев
#: никогда не несёт метку замера); `any_bar` — роду безразлично;
#: `not_applicable` — число не из трека вовсе.
EVIDENCE_BASES: Tuple[str, ...] = ("evidenced_only", "any_bar", "not_applicable")


@dataclass(frozen=True)
class ApyKind:
    """Род числа, названного «APY». Поля — ВОПРОСЫ, на которые род отвечает."""

    kind: str
    subject: str
    is_rate: bool
    denominator: str | None
    window: str | None
    evidence: str
    meaning: str
    #: Имя рода из словаря ТЗ владельца (§5), если он там назван; иначе "".
    owner_term: str


def _k(*a, **kw) -> ApyKind:  # краткая форма объявления ниже
    return ApyKind(*a, **kw)


#: ПЕРЕЧЕНЬ РОДОВ. Читатель один — `apy_name_census`.
KINDS: Dict[str, ApyKind] = {
    "portfolio_rate_on_nav": _k(
        kind="portfolio_rate_on_nav",
        subject="portfolio",
        is_rate=True,
        denominator="nav",
        window="today",
        evidence="evidenced_only",
        meaning=("годовая ставка ВСЕЙ книги за сегодня: доход, делённый на NAV, "
                 "то есть КЭШ СТОИТ В ЗНАМЕНАТЕЛЕ и тянет число вниз"),
        owner_term="net portfolio APY",
    ),
    "portfolio_rate_on_deployed": _k(
        kind="portfolio_rate_on_deployed",
        subject="portfolio",
        is_rate=True,
        denominator="deployed",
        window="today",
        evidence="evidenced_only",
        meaning=("годовая ставка РАЗМЕЩЁННОГО капитала за сегодня: кэша в "
                 "знаменателе НЕТ, поэтому число всегда ≥ ставки на NAV"),
        owner_term="weighted position APY",
    ),
    "portfolio_rate_time_mean": _k(
        kind="portfolio_rate_time_mean",
        subject="portfolio",
        is_rate=True,
        denominator="nav",
        window="trailing_ring",
        evidence="evidenced_only",
        meaning=("СРЕДНЯЯ по времени ставка книги на окне кольцевого буфера — "
                 "это история, а не сегодняшнее наблюдение"),
        owner_term="historical APY",
    ),
    "position_rate": _k(
        kind="position_rate",
        subject="position",
        is_rate=True,
        denominator="position",
        window="today",
        evidence="not_applicable",
        meaning="наблюдённая годовая ставка ОДНОГО протокола",
        owner_term="current APY",
    ),
    "rate_dispersion_pp": _k(
        kind="rate_dispersion_pp",
        subject="position",
        is_rate=False,
        denominator=None,
        window="trailing_7d",
        evidence="not_applicable",
        meaning=("РАЗБРОС ставки в процентных пунктах. Ставкой НЕ является: "
                 "0.85 здесь — не «0.85 % годовых», а «ставка гуляет на 0.85 пп»"),
        owner_term="",
    ),
    "health_subscore": _k(
        kind="health_subscore",
        subject="position",
        is_rate=False,
        denominator=None,
        window=None,
        evidence="not_applicable",
        meaning=("БАЛЛ здоровья адаптера по оси доходности, шкала 0…100. "
                 "Ставкой НЕ является: 79.79 здесь — не «79.79 % APY»"),
        owner_term="",
    ),
}

#: ПУТЬ (нормализованный: индексы списков → «[]») → имя рода.
#: Ключ — путь, а не ИМЯ ключа, намеренно: одно и то же написание `apy_pct`
#: стоит и у позиции, и у балла, и решает его РОД место, а не написание.
PATH_KINDS: Dict[str, str] = {
    # трек цикла
    "equity_curve_daily/daily[]/apy_today": "portfolio_rate_on_nav",
    "equity_curve_daily/daily[]/apy_expected_pct": "portfolio_rate_on_nav",
    # сводка аналитики
    "sections/yield_attribution_tracker/effective_apy_pct": "portfolio_rate_on_deployed",
    "sections/yield_attribution_tracker/contributions[]/apy_pct": "position_rate",
    "sections/portfolio_volatility_tracker/mean_apy_pct": "portfolio_rate_time_mean",
    "sections/adapter_health_scorecard/adapters[]/apy_pct": "position_rate",
    "sections/adapter_health_scorecard/adapters[]/apy_vol_7d_pp": "rate_dispersion_pp",
    "sections/adapter_health_scorecard/adapters[]/components/apy": "health_subscore",
}


def validate() -> list[str]:
    """Паритет ОБЪЯВЛЕНИЯ с собственным контрактом. Пустой список = в порядке.

    Проверяется объявление, а не чьи-то числа: мерка обязана выдерживать свою
    же мерку, иначе сторож мерит сам себя (урок ADR-940).
    """
    problems: list[str] = []
    for name, k in KINDS.items():
        if name != k.kind:
            problems.append(f"ключ {name!r} не совпадает с kind={k.kind!r}")
        if k.subject not in SUBJECTS:
            problems.append(f"{name}: subject={k.subject!r} вне SUBJECTS")
        if k.denominator not in DENOMINATORS:
            problems.append(f"{name}: denominator={k.denominator!r} вне DENOMINATORS")
        if k.window not in WINDOWS:
            problems.append(f"{name}: window={k.window!r} вне WINDOWS")
        if k.evidence not in EVIDENCE_BASES:
            problems.append(f"{name}: evidence={k.evidence!r} вне EVIDENCE_BASES")
        if not k.meaning.strip():
            problems.append(f"{name}: meaning пуст — род без смысла СЛОВАМИ "
                            "объявлением не является")
        if k.is_rate and k.denominator is None:
            problems.append(f"{name}: ставка без знаменателя")
        if k.is_rate and k.window is None:
            problems.append(f"{name}: ставка без окна")
        if not k.is_rate and k.denominator is not None:
            problems.append(f"{name}: не ставка, а знаменатель назван — "
                            "знаменателя у неставки не существует")
    for path, kind in PATH_KINDS.items():
        if kind not in KINDS:
            problems.append(f"путь {path!r} объявлен родом {kind!r}, "
                            "которого нет в KINDS")
    return problems


def kind_of(path: str) -> ApyKind | None:
    """Род по нормализованному пути; `None` = путь НЕ ОБЪЯВЛЕН (fail-CLOSED)."""
    name = PATH_KINDS.get(path)
    return KINDS[name] if name else None
