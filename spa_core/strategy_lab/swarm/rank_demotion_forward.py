"""Форвардный paper-модуль рангового демоушена — ДВЕ РУКИ в одном модуле.

Решения владельца 2026-08-08:
  * **ADR-074 принят** (вариант A карточки `own-rnd-xsd-rank-demotion-allocator`) — демоушен по
    относительному рангу вместо абсолютного порога; вариант **C** той же карточки — построить
    advisory paper-модуль.
  * **Вариант 1** карточки `own-rnd-xvd-vol-rank-second-arm` — ранжирование по волатильности
    добавляется **второй рукой внутрь этого же модуля**, а НЕ третьим paper-треком и НЕ новым
    агентом. «Один модуль, две руки, ноль новых агентов, и через 30 дней форварда мы своими
    глазами увидим, какая рука лучше — вместо того чтобы спорить об этом по бэктесту.»

Правило (из ADR-074, буква в букву; параметры унаследованы от записей #40/#45, НЕ перетюнены):

    score(b, t) = признак книги b на причинном окне [t−L, t−1]
    демоушен    : score в k САМЫХ НИЗКИХ  ⇒ книга выключена
    возврат     : вне bottom-k M дней ПОДРЯД

Две руки различаются ТОЛЬКО признаком:
  * **drift** (#39/#40) — скользящая средняя доходности. Зрячий к доходности.
  * **vol**   (#45)     — минус стандартное отклонение: выключаются самые ШУМНЫЕ книги.
    Полуслепой: σ инвариантна к смене знака, поэтому рука не отличает книгу, зарабатывающую
    20 %/год, от её зеркала, теряющего столько же.

Рядом с ними стоит ТРЕТЬЯ рука — **static**, и она **КОНТРОЛЬ, а не кандидат**
(карточка `inbox-modul-39-tretei-rukoi-obyazana-byt-prich`, задание по записям #47/#48):
средние веса руки drift, зафиксированные на ПРЕФИКСЕ трека и далее НЕ меняемые. Без неё через
30 дней форварда нельзя отличить «правило вовремя переключается» от «правило просто держит
недовес» — ровно тот спор, который ADR-074 закрыл словами «продавать как timing-эдж запрещено».
Статика здесь ПРИЧИННАЯ: окно фиксации — префикс, будущее в него не входит; статический двойник
из `train_test` (среднее по ТЕСТОВОМУ окну) был **оракулом**, и подмена одного другим ловится
тестом-положительным контролем.

═══════════════════════════════════════════════════════════════════════════════════════════
ДЕНЬ, КОГДА СКОР КНИГИ НЕ СЧИТАЕТСЯ — ЯВНАЯ ВЕТКА, А НЕ ПОБОЧНЫЙ ЭФФЕКТ
═══════════════════════════════════════════════════════════════════════════════════════════
Запись **#52 SFP** (2026-08-14) померила четыре защитимых прочтения пустой ячейки и назвала то,
чего никто бы не предположил, зная инвариант #2: **до этой правки код держал политику `open` —
тёмный фид ЗАЩИЩАЛ книгу.** Неизмеримая книга не ранжируема, значит выключить её нельзя, а уже
выключенная **КОПИЛА кредит на возврат**, пока фид тёмный: авария данных возвращала книге вес.
Это нигде не было записано и не было ничьим решением.

Здесь политика названа и закреплена (числа #52, панель 852 дня, авария синтетическая):

    carry         ранжируем по ПОСЛЕДНЕМУ ИЗВЕСТНОМУ скору — единственная из четырёх, которая при
                  20 % тёмных дней стоит ≤0.03 Calmar и ≤0.4 pp netAPY, не искажает duty и не
                  всплескивает оборот (у #45 — побайтно те же 6.25 / 0.37 / 20.88 %)
    closed_panel  за потолком возраста (`MAX_SCORE_AGE_DAYS`) правило ОТКАЗЫВАЕТСЯ судить:
                  вчерашнее состояние удерживается, счётчики возврата НЕ ДВИГАЮТСЯ. Ранжировать
                  по позапрошлогоднему числу — не «мягкая деградация», а тихое враньё
    closed_book   «не измерено ⇒ демоушен» — буквальное чтение инварианта #2 и ХУДШАЯ из четырёх:
                  −6.08 Calmar при равном duty, netAPY 25.94 % → −0.49 %, и проигрыш НА ОБОРОТЕ
                  (4.35 → 47.9/год). Здесь НЕ РЕАЛИЗОВАНА сознательно
    open          прежнее молчаливое поведение. Больше недостижимо ни одним значением параметров

**Бюджет свежести у рук РАЗНЫЙ, и это тоже замер, а не вкус** (#51 SLT): #40/drift к возрасту
отметок до ~5 дней равнодушен (ΔCalmar 4.96…5.15 — шум), а у #45/vol бюджет **НУЛЕВОЙ** — сутки
несвежести, и ΔCalmar +2.96 → −0.21, просадка −3.37 % → −5.98 %, то есть рука перестаёт
отличаться от равновеса. Поэтому рука vol включается ТОЛЬКО на отметках того же дня, иначе
пишет `SKIPPED` — то есть НЕ РЕШЕНИЕ, а признанный пропуск.

Возраст отметки каждой книги пишется РЯДОМ С РЕШЕНИЕМ каждый день. Без него форвардный трек не
интерпретируем: нельзя отличить «правило ошиблось» от «правило судило по вчерашнему».

**Границы этой ветки:** всё перечисленное — advisory / OUTSIDE_RISKPOLICY / evidence L0, и НИ ОДНА
из этих находок не является аргументом ослабить fail-CLOSED на money-path. Там непомеренный
протокол обязан отказываться, потому что цена ошибки — капитал, а не Calmar. Речь только про
advisory-отбор книг внутри бумажной книги агрессивного тира.

Почему признак зафиксирован, а не оставлен параметром: запись **#44 (2026-08-08)** опровергла
вывод #43 «признак — сноска». При ТОЧНО выровненной duty смена признака двигает ΔCalmar на
**4.07** (M=1) и **7.40** (M=20). Признак — предмет ADR, а не деталь реализации.

Почему k держится в области 2…5: замер **#46** (тоже 2026-08-08) показал, что при k ≥ 6 без
потолка раскладка вырождается в ОДНУ позицию (maxW = 100 %) — это не портфель. Там же: наш
лимит 20 % на имя в опорной ячейке НЕ БИНДИТ и стоит ноль.

═══════════════════════════════════════════════════════════════════════════════════════════
ЧЕСТНЫЕ ГРАНИЦЫ — переносятся из ADR-074 дословно, как условия принятия
═══════════════════════════════════════════════════════════════════════════════════════════
1. Это **бэктест-происхождение, evidence L0**. `IS_ADVISORY=True`, `OUTSIDE_RISKPOLICY=True`,
   капитал НЕ двигается, RiskPolicy v1.0 не затрагивается ни строкой.
2. **Ранговое правило по построению ВСЕГДА держит 100 % капитала в рынке.** Оно умеет отвернуть
   деньги от худшей книги и НЕ УМЕЕТ опустить портфель целиком. Против общего обвала по всем
   книгам оно беззащитно. Оно **не заменяет kill-switch** и не подаётся как защита.
3. Контроль на **сдвиг сигнала во времени** правило проходит СЛАБО: измерено «оно правильно
   выбирает КАКУЮ книгу», а не «оно правильно угадывает КОГДА». Продавать как timing-эдж
   запрещено.

Каждая рука пишет в лог **фактическую концентрацию**, **долю времени «выключено»** и
**фактический оборот за год** — требования владельца 2026-08-08 (карточка
`own-rnd-duty-is-concentration-adr055`) и задания по записи #48. Без них через 30 дней форварда
результат неразличим: правило его дало, премия за размер позиций или он уже съеден оборотом.
Оборот считается по Σ|Δw|, а НЕ по числу переключений: у наклонных и ансамблевых правил эдж съедает
именно объём переставленного капитала (#48: 13.49 оборота/год ≈ 647 bps).

**Руки НЕ СЛИВАЮТСЯ в один вес** — это запрет по замеру, а не стиль (#48): ансамбль наследует
оборот своей шумнейшей руки, а сигнал усредняет (порядок книг меняется у σ в 3.5 % дней, у drift
в 31.7 %, у слияния в 30.3 %), поэтому net-of-cost слияние проигрывает и инкумбенту #40, и своей
же причинной статике. Руки живут РЯДОМ, как владелец и решил, и это закреплено тестом.

Деплой агента — ОТДЕЛЬНОЙ карточкой владельцу. Принятие ADR разрешением не является.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.strategy_lab.swarm.common import append_daily_proof, apy_pct, max_drawdown_pct
from spa_core.strategy_lab.swarm.dwell_hysteresis_forward import (
    NOTIONAL_USD, CASH_DAILY_RETURN, load_panel,
    _duty_out_pct, _largest_position_pct,
)
from spa_core.utils.atomic import atomic_save

__all__ = [
    "run_forward_tick", "compute_arms", "rank_flags", "rank_decisions", "carry_scores",
    "drift_scores", "vol_scores", "static_weights", "turnover_per_year",
    "LOOKBACK", "RANK_K", "READMIT_M", "ARMS", "CONTROL_ARMS", "ALL_ARMS",
    "STALE_POLICY", "MAX_SCORE_AGE_DAYS", "FRESH_ONLY_ARMS", "STATIC_FIT_DAYS",
    "BOOK_NAME", "STATUS_NAME",
]

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

REPO_ROOT = Path(__file__).resolve().parents[3]
PANEL_DIR = REPO_ROOT / "data" / "aggressive_lab"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
BOOK_NAME = "rank_demotion_book.jsonl"
STATUS_NAME = "rank_demotion_status.json"

# Унаследованы от #39/#40, здесь НЕ перетюнены. Изменение любого — НОВЫЙ эксперимент:
# запись в реестре + карточка владельцу, никогда молчаливая правка.
LOOKBACK = 60
RANK_K = 2
READMIT_M = 20

ARMS: Tuple[str, ...] = ("drift", "vol")            # руки-ПРАВИЛА (различаются признаком)
CONTROL_ARMS: Tuple[str, ...] = ("static",)         # руки-КОНТРОЛИ (не кандидаты на доставку)
ALL_ARMS: Tuple[str, ...] = ARMS + CONTROL_ARMS

# ── политика на день, когда скор книги не считается (#52 SFP) ─────────────────────────────────
STALE_POLICY = "carry"
# Потолок возраста отметки, за которым правило ОТКАЗЫВАЕТСЯ судить (closed_panel). 5 дней —
# измеренный бюджет свежести #40 (#51 SLT: до ~5 дней ΔCalmar 4.96…5.15, то есть шум). Это
# ПОТОЛОК, а не тюнинг-параметр: сдвиг — новая запись реестра + карточка владельцу.
MAX_SCORE_AGE_DAYS = 5
# Руки, у которых бюджет свежести НУЛЕВОЙ (#51: у #45 сутки несвежести дают +2.96 → −0.21).
# Такая рука на несвежих отметках пишет SKIPPED, а не решение.
FRESH_ONLY_ARMS: Tuple[str, ...] = ("vol",)
# Окно фиксации причинной статики: два разогрева. Первый LOOKBACK сигнал обезоружен (нечего
# усреднять — усреднять равные веса значит получить raw, ровно тот тождественный «двойник»,
# на котором обжёгся #47), второй — уже вооружённое правило.
STATIC_FIT_DAYS = 2 * LOOKBACK

# Состояния дня. Пишутся рядом с решением: без них нельзя отличить «правило ошиблось» от
# «правило судило по вчерашнему» и от «правило вообще не судило».
DAY_MEASURED = "MEASURED"            # все годные отметки — сегодняшние
DAY_CARRIED = "CARRIED"              # решение принято по устаревшему скору (carry)
DAY_CLOSED_PANEL = "CLOSED_PANEL"    # за потолком возраста — правило отказалось судить
DAY_SKIPPED = "SKIPPED"              # рука с нулевым бюджетом свежести: не решение, а пропуск
DAY_UNRANKABLE = "UNRANKABLE"        # годных отметок не больше k — «худших k» не определить

HONEST_LIMITS = (
    "форвардный paper поверх живых paper-плеч, НЕ реализованный капитал; правило проверено "
    "только на бэктесте (L0, #40/#45) — этот форвард и есть проверка, и он начинается с малого; "
    "ранговое правило ВСЕГДА держит 100% капитала в рынке и kill-switch НЕ ЗАМЕНЯЕТ; контроль на "
    "сдвиг сигнала пройден слабо — это эдж про РАСПРЕДЕЛЕНИЕ капитала, не про тайминг; сигнал "
    "обезоружен первые LOOKBACK дней (все руки равны — разогрев часть трека); рука static — "
    "КОНТРОЛЬ (причинная статика на префиксе), она отвечает на вопрос «тайминг или недовес» и "
    "кандидатом на доставку не является; на тёмной отметке действует политика carry с потолком "
    "возраста MAX_SCORE_AGE_DAYS (дальше closed_panel — отказ судить), рука vol на несвежей "
    "отметке пишет SKIPPED (её бюджет свежести НУЛЕВОЙ, #51); политика на тёмный фид измерена на "
    "СИНТЕТИЧЕСКОЙ аварии (у панели ноль реальных пропусков за 852 дня) и НЕ является аргументом "
    "ослабить fail-CLOSED на money-path; если через ~30 вооружённых дней эффект не подтверждён, "
    "модуль ретайрится карточкой, а не оставляется спать"
)


# ── признаки (причинное окно [t−L, t−1] — сегодняшний день НИКОГДА не смотрит на себя) ────────
def _causal_window(rets: Sequence[float], i: int, lookback: int) -> List[float]:
    lo = max(0, i - lookback)
    return list(rets[lo:i])


def drift_scores(panel_rets: Dict[str, List[float]], lookback: int = LOOKBACK) -> Dict[str, List[Optional[float]]]:
    """#39/#40: средняя доходность на окне. Выше — лучше."""
    out: Dict[str, List[Optional[float]]] = {}
    for b, rets in panel_rets.items():
        out[b] = [(fmean(w) if (w := _causal_window(rets, i, lookback)) else None)
                  for i in range(len(rets))]
    return out


def vol_scores(panel_rets: Dict[str, List[float]], lookback: int = LOOKBACK) -> Dict[str, List[Optional[float]]]:
    """#45: МИНУС стандартное отклонение — «тихая» книга получает высокий score.

    Полуслепой признак: σ не различает знак. Книга, зарабатывающая 20 %/год, и её зеркало,
    теряющее столько же, для этой руки НЕРАЗЛИЧИМЫ — это её свойство, а не дефект, и именно
    поэтому она стоит в паре со зрячей рукой, а не вместо неё.
    """
    out: Dict[str, List[Optional[float]]] = {}
    for b, rets in panel_rets.items():
        out[b] = [(-pstdev(w) if len(w := _causal_window(rets, i, lookback)) >= 2 else None)
                  for i in range(len(rets))]
    return out


_SCORERS = {"drift": drift_scores, "vol": vol_scores}


# ── carry: возраст отметки как ПЕРВОКЛАССНАЯ величина, а не догадка ───────────────────────────
def carry_scores(scores: Dict[str, List[Optional[float]]],
                 ) -> Tuple[Dict[str, List[Optional[float]]], Dict[str, List[Optional[int]]]]:
    """(последний известный скор, возраст отметки в днях) — политика `carry` записи #52.

    `age = 0` — отметка сегодняшняя; `age = N` — скор посчитан N дней назад и с тех пор фид
    тёмный; `age = None` — книгу НЕ ИЗМЕРЯЛИ НИ РАЗУ, возраста у неё нет, и притворяться нулём
    здесь запрещено (это разные утверждения, и на них расходятся разные ветки правила).
    """
    carried: Dict[str, List[Optional[float]]] = {}
    ages: Dict[str, List[Optional[int]]] = {}
    for book, series in scores.items():
        cs: List[Optional[float]] = []
        ag: List[Optional[int]] = []
        last: Optional[float] = None
        age: Optional[int] = None
        for value in series:
            if value is not None:
                last, age = value, 0
            elif age is not None:
                age += 1
            cs.append(last)
            ag.append(age)
        carried[book], ages[book] = cs, ag
    return carried, ages


# ── ранговая машина состояний (#40, одна подстановка признака) ────────────────────────────────
def rank_decisions(scores: Dict[str, List[Optional[float]]], k: int = RANK_K,
                   readmit_m: int = READMIT_M, max_age_days: int = MAX_SCORE_AGE_DAYS,
                   fresh_only: bool = False) -> dict:
    """Полное решение дня: флаги + ВОЗРАСТ каждой отметки + состояние дня.

    Демоушен: score в k САМЫХ НИЗКИХ среди книг, у которых score годен (`carry` — годен и
    вчерашний, пока он не старше потолка). Возврат: книга вне bottom-k **M дней ПОДРЯД**. Один
    день вне — не возврат: без задержки правило начинает торговать шум, и именно отложенный
    возврат отличает #39/#40 от наивного «переставляй каждый день».

    Ветка «отметка не пришла» — ЯВНАЯ (#52 SFP), потому что раньше она существовала только как
    побочный эффект: неизмеримая книга не попадала в ранжирование, а значит её нельзя было
    выключить И она копила кредит на возврат — тёмный фид ЗАЩИЩАЛ книгу. Теперь:

      * `carry` — ранжируем по последнему известному скору (`age <= max_age_days`);
      * `closed_panel` — хоть одна годная отметка старше потолка ⇒ правило ОТКАЗЫВАЕТСЯ судить:
        вчерашнее состояние держится, счётчики возврата НЕ ДВИГАЮТСЯ (иначе тёмный фид опять
        начнёт возвращать книгам вес — тот же дефект, только с потолком);
      * `fresh_only=True` (рука с нулевым бюджетом свежести, #51) — любой возраст > 0 ⇒
        `SKIPPED`: пропуск, а не решение;
      * `UNRANKABLE` — годных отметок не больше k: «худших k» не определить. Выключить по
        неизмеренному значило бы принять решение о капитале на пустоте (fail-CLOSED разогрева).

    Возвращает `{"flags", "ages", "day_states", "policy", "max_age_days", "fresh_only"}`.
    """
    if max_age_days < 0:
        raise ValueError("max_age_days must be >= 0 — отрицательный возраст отметки не бывает")
    carried, ages = carry_scores(scores)
    books = sorted(scores)
    n = len(scores[books[0]]) if books else 0
    budget = 0 if fresh_only else max_age_days

    flags = {b: [False] * n for b in books}
    day_states: List[str] = []
    streak = {b: 0 for b in books}          # дней подряд вне bottom-k
    state = {b: False for b in books}       # выключена ли сейчас

    for i in range(n):
        usable = [(carried[b][i], b) for b in books if carried[b][i] is not None]
        oldest = max((ages[b][i] for b in books if ages[b][i] is not None), default=None)
        if len(usable) <= k:
            day_states.append(DAY_UNRANKABLE)
        elif oldest is not None and oldest > budget:
            day_states.append(DAY_SKIPPED if fresh_only else DAY_CLOSED_PANEL)
        else:
            usable.sort()
            worst = {b for _s, b in usable[:k]}
            for b in books:
                if b in worst:
                    state[b] = True
                    streak[b] = 0
                else:
                    streak[b] += 1
                    if state[b] and streak[b] >= readmit_m:
                        state[b] = False
            day_states.append(DAY_MEASURED if oldest == 0 else DAY_CARRIED)
        for b in books:
            flags[b][i] = state[b]
    return {"flags": flags, "ages": ages, "day_states": day_states,
            "policy": STALE_POLICY, "max_age_days": budget, "fresh_only": fresh_only}


def rank_flags(scores: Dict[str, List[Optional[float]]], k: int = RANK_K,
               readmit_m: int = READMIT_M, max_age_days: int = MAX_SCORE_AGE_DAYS,
               fresh_only: bool = False) -> Dict[str, List[bool]]:
    """{книга: [выключена ли в день i]} — проекция `rank_decisions` на одни флаги."""
    return rank_decisions(scores, k=k, readmit_m=readmit_m, max_age_days=max_age_days,
                          fresh_only=fresh_only)["flags"]


# ── плечи ─────────────────────────────────────────────────────────────────────────────────────
def _weights_from_flags(flags: Dict[str, List[bool]], n: int) -> Dict[str, List[float]]:
    """Выключенные книги отдают долю оставшимся поровну (аллокатор #38/#39).

    Все выключены ⇒ всё в кэш (fail-CLOSED: единственное состояние, в котором правило НЕ ДОЛЖНО
    выдумывать назначение).
    """
    books = sorted(flags)
    out = {b: [0.0] * n for b in books}
    for i in range(n):
        live = [b for b in books if not flags[b][i]]
        if not live:
            continue
        share = 1.0 / len(live)
        for b in live:
            out[b][i] = share
    return out


def static_weights(panel_rets: Dict[str, List[float]], n: int,
                   fit_days: int = STATIC_FIT_DAYS, lookback: int = LOOKBACK,
                   k: int = RANK_K, readmit_m: int = READMIT_M) -> Dict[str, List[float]]:
    """ПРИЧИННАЯ статика — третья рука-КОНТРОЛЬ (задание по записям #47/#48).

    Средние веса руки drift, посчитанные на ПРЕФИКСЕ `[0, fit_days)` и далее НЕ меняемые.
    До конца окна фиксации рука держит равные веса: фиксировать ещё нечего, и разогрев —
    честная часть трека, а не дырка в нём.

    Почему усредняется только ВООРУЖЁННАЯ часть префикса `[lookback, fit_days)`: на первом
    LOOKBACK скор не измерен, правило равно равным весам, и среднее по всему префиксу дало бы
    ТОЖДЕСТВО с `raw` — ровно тот вырожденный «статический двойник», на котором обжёгся #47
    (оборот 0.00 из 370 дней, совпадение с двойником не говорило о тайминге НИЧЕГО).

    Почему префикс, а не среднее по всему окну: среднее по всему окну — **оракул** (в #47 двойник
    считался как среднее ТЕСТОВОГО периода). Здесь будущее в фиксацию не входит по построению, и
    подмена ловится тестом: доходности ПОСЛЕ `fit_days` не имеют права двигать эти веса.
    """
    if fit_days < 1:
        raise ValueError("fit_days must be >= 1 — статика без окна фиксации не статика")
    books = sorted(panel_rets)
    if not books:
        return {}
    equal = 1.0 / len(books)
    if n <= fit_days:
        return {b: [equal] * n for b in books}
    fit_rets = {b: list(panel_rets[b][:fit_days]) for b in books}
    flags = rank_decisions(drift_scores(fit_rets, lookback), k=k, readmit_m=readmit_m)["flags"]
    w_fit = _weights_from_flags(flags, fit_days)
    armed_lo = min(lookback, fit_days - 1)
    # Сумма средних НЕ нормируется к 1: если в префиксе были дни «все выключены», средний кэш
    # — часть измеряемого профиля, и дорисовывать его до полного размещения значило бы
    # подменить контроль более агрессивной книгой, чем та, что фактически стояла.
    fixed = {b: fmean(w_fit[b][armed_lo:fit_days]) for b in books}
    return {b: [equal] * fit_days + [fixed[b]] * (n - fit_days) for b in books}


def turnover_per_year(w: Dict[str, List[float]], books: Sequence[str],
                      n_days: int) -> Optional[float]:
    """Фактический оборот за год: Σ|Δw| по всем книгам и дням, приведённая к 365 дням.

    Считается по **|Δw|, а не по числу переключений** — требование задания по записи #48: у
    наклонных и ансамблевых правил счёт идёт по объёму переставленного капитала, и именно он
    съел эдж #48 (13.49 оборота/год ≈ 647 bps при допущении 96 bp round trip из #10/#49).
    """
    if n_days < 2:
        return None
    moved = sum(abs(float(w[b][i]) - float(w[b][i - 1]))
                for b in books for i in range(1, n_days))
    return round(moved * 365.0 / n_days, 4)


def _equity(dates: Sequence[str], panel: Dict[str, Dict[str, float]],
            w: Dict[str, List[float]]) -> List[float]:
    books = sorted(panel)
    eq = [NOTIONAL_USD]
    for i in range(len(dates)):
        r = sum(w[b][i] * panel[b][dates[i]] for b in books)
        deployed = sum(w[b][i] for b in books)
        eq.append(eq[-1] * (1.0 + r + (1.0 - deployed) * CASH_DAILY_RETURN))
    return eq


def compute_arms(dates: Sequence[str], panel: Dict[str, Dict[str, float]]) -> dict:
    """raw (равные веса) + по одной руке на признак."""
    books = sorted(panel)
    n = len(dates)
    panel_rets = {b: [panel[b][d] for d in dates] for b in books}

    def view(w: Dict[str, List[float]]) -> dict:
        eq = _equity(dates, panel, w)
        return {
            "equity_usd": round(eq[-1], 2),
            "apy_pct": apy_pct(eq, n),
            "max_dd_pct": max_drawdown_pct(eq),
            "books_out_today": sorted(b for b in books if w[b][-1] == 0.0),
            # Требование владельца 2026-08-08: обе величины КАЖДЫЙ ДЕНЬ.
            "concentration_pct": _largest_position_pct(w, books, -1),
            "duty_out_pct": _duty_out_pct(w, books, n),
            # Задание по записи #48: оборот по Σ|Δw|, а не число переключений.
            "turnover_per_year": turnover_per_year(w, books, n),
        }

    equal = {b: [1.0 / len(books)] * n for b in books}
    arms: dict = {"raw": view(equal)}
    arms["raw"].pop("books_out_today")            # raw по определению никогда не вне рынка

    for arm in ARMS:
        fresh_only = arm in FRESH_ONLY_ARMS
        decision = rank_decisions(_SCORERS[arm](panel_rets), fresh_only=fresh_only)
        arms[arm] = view(_weights_from_flags(decision["flags"], n))
        # Возраст отметки КАЖДОЙ книги рядом с решением дня: без него форвардный трек не
        # интерпретируем — нельзя отличить «правило ошиблось» от «правило судило по вчерашнему».
        arms[arm]["score_age_days"] = {b: decision["ages"][b][n - 1] for b in books} if n else {}
        arms[arm]["day_state"] = decision["day_states"][n - 1] if n else None
        arms[arm]["day_state_counts"] = {
            s: decision["day_states"].count(s) for s in sorted(set(decision["day_states"]))}
        arms[arm]["stale_policy"] = {"policy": decision["policy"],
                                     "max_score_age_days": decision["max_age_days"],
                                     "fresh_only": decision["fresh_only"]}

    # Третья рука — КОНТРОЛЬ, а не кандидат. Она отвечает на вопрос «тайминг или недовес»,
    # который ADR-074 оставил открытым, и через 30 дней делает форвард атрибутируемым.
    static_w = static_weights(panel_rets, n)
    arms["static"] = view(static_w)
    arms["static"]["role"] = "control"
    arms["static"]["fit_window_days"] = STATIC_FIT_DAYS
    arms["static"]["static_armed"] = n > STATIC_FIT_DAYS
    arms["static"]["note"] = (
        "причинная статика: средние веса руки drift на префиксе [0, "
        f"{STATIC_FIT_DAYS}) дней, далее КОНСТАНТА. Будущее в фиксацию не входит; статический "
        "двойник по среднему ТЕСТОВОГО окна (#47) — оракул, и подмена ловится тестом. "
        "Контроль, НЕ кандидат на доставку.")

    # Прямое сравнение рук — то, ради чего владелец выбрал «две руки в одном модуле»
    # вместо спора по бэктесту. Слияние рук в один вес ЗАПРЕЩЕНО замером #48 (ансамбль
    # наследует оборот шумнейшей руки, а сигнал усредняет), поэтому здесь только КОНТРАСТ.
    arms["arm_contrast"] = {
        "apy_delta_pp": (None if arms["drift"]["apy_pct"] is None or arms["vol"]["apy_pct"] is None
                         else round(arms["drift"]["apy_pct"] - arms["vol"]["apy_pct"], 4)),
        "dd_delta_pp": (None if arms["drift"]["max_dd_pct"] is None or arms["vol"]["max_dd_pct"] is None
                        else round(arms["drift"]["max_dd_pct"] - arms["vol"]["max_dd_pct"], 4)),
        "note": ("drift минус vol. Читать ВМЕСТЕ с concentration_pct и duty_out_pct обеих рук: "
                 "при разной концентрации разница доходности не является разницей правил (#46)."),
    }

    def _over_static(arm: str) -> Optional[float]:
        a, s = arms[arm]["apy_pct"], arms["static"]["apy_pct"]
        return None if a is None or s is None else round(a - s, 4)

    # ЭТО и есть «тайминг или недовес» — единственное число, ради которого третья рука заведена.
    arms["static_contrast"] = {
        "drift_minus_static_apy_pp": _over_static("drift"),
        "vol_minus_static_apy_pp": _over_static("vol"),
        "note": ("рука минус ПРИЧИННАЯ статика того же профиля. Положительное — правило "
                 "переключается вовремя; ноль или отрицательное — весь результат был статическим "
                 "недовесом (#47: у σ-правила на тестовом окне оборот был 0.00 из 370 дней, то "
                 "есть таймить было НЕЧЕГО). Читать net-of-cost, рядом с turnover_per_year."),
    }
    return arms


# ── дневной форвардный тик ────────────────────────────────────────────────────────────────────
def _last_book_day(book_path: Path) -> Optional[str]:
    last = None
    try:
        with book_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("date", last)
                except ValueError:
                    continue
    except OSError:
        return None
    return last


def run_forward_tick(panel_dir: Path = PANEL_DIR, out_dir: Path = SWARM_DIR,
                     as_of: Optional[str] = None) -> dict:
    """Один форвардный тик за один UTC-день. Дописывает ОДНУ hash-chained строку (идемпотентно
    по дню, append-only ПО ДАТЕ) + пишет статус. Капитал не двигает."""
    now = datetime.now(timezone.utc)
    day = as_of or now.date().isoformat()
    panel, missing = load_panel(panel_dir)

    doc: dict = {
        "module": "swarm.rank_demotion_forward",
        "adr": "ADR-074",
        "is_advisory": IS_ADVISORY,
        "outside_riskpolicy": OUTSIDE_RISKPOLICY,
        "generated_at": now.isoformat(),
        "day": day,
        "params": {"lookback": LOOKBACK, "k": RANK_K, "readmit_m": READMIT_M, "arms": list(ARMS),
                   "control_arms": list(CONTROL_ARMS),
                   "static_fit_days": STATIC_FIT_DAYS,
                   "stale_policy": STALE_POLICY,
                   "max_score_age_days": MAX_SCORE_AGE_DAYS,
                   "fresh_only_arms": list(FRESH_ONLY_ARMS),
                   "arms_blended": False,
                   "provenance": ("docs/DYNAMIC_LEVERAGE_GUARDIAN.md #40 (drift) + #45 (vol) + "
                                  "#47/#48 (причинная статика, оборот по Σ|Δw|) + #51/#52 "
                                  "(бюджет свежести и политика на тёмную отметку); "
                                  "параметры унаследованы, НЕ перетюнены")},
        "honest_limits": HONEST_LIMITS,
    }

    common = sorted(d for d in set.intersection(*(set(s) for s in panel.values()))
                    if d <= day) if panel and not missing else []

    payload: dict = {"phase": "forward", "is_advisory": True, "outside_riskpolicy": True,
                     "adr": "ADR-074",
                     "params": {"lookback": LOOKBACK, "k": RANK_K, "readmit_m": READMIT_M,
                                "stale_policy": STALE_POLICY,
                                "max_score_age_days": MAX_SCORE_AGE_DAYS,
                                "fresh_only_arms": list(FRESH_ONLY_ARMS),
                                "static_fit_days": STATIC_FIT_DAYS,
                                "arms_blended": False}}
    if missing:
        doc.update({"state": "NO_DATA", "missing_books": missing, "common_days": 0,
                    "reason": f"книги без живых форвардных строк: {missing}"})
        payload.update({"status": "no_data", "reason": doc["reason"]})
    elif not common or common[-1] != day:
        last_feed = common[-1] if common else None
        doc.update({"state": "NO_DATA", "last_feed_date": last_feed, "common_days": len(common),
                    "reason": (f"нет живого форвардного фида за {day} по панели "
                               f"(свежайшая общая дата: {last_feed})")})
        payload.update({"status": "no_data", "reason": doc["reason"]})
    else:
        arms = compute_arms(common, panel)
        # Пока окно не набралось, все руки равны raw — это разогрев, и он ЧАСТЬ трека.
        signal_armed = len(common) > LOOKBACK
        doc.update({"state": "TRACKING", "common_days": len(common),
                    "window": {"start": common[0], "end": common[-1]},
                    "signal_armed": signal_armed, "arms": arms})
        payload.update({"status": "tracking", "days": len(common), "window": doc["window"],
                        "signal_armed": signal_armed, "arms": arms})

    book_path = out_dir / BOOK_NAME
    last_day = _last_book_day(book_path)
    if last_day is not None and day < last_day:
        doc.update({"state": "REFUSED_OUT_OF_ORDER",
                    "reason": f"тик за {day} предшествует последнему дню книги {last_day}"})
        doc["book_appended"] = False
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        doc["book_appended"] = append_daily_proof(payload, book_path, day=day)

    atomic_save(doc, str(out_dir / STATUS_NAME))
    return doc


def main() -> int:
    doc = run_forward_tick()
    line = (f"swarm.rank_demotion_forward: state={doc['state']} "
            f"days={doc.get('common_days')} armed={doc.get('signal_armed')}")
    arms = doc.get("arms") or {}
    for arm in ARMS if arms else ():
        ages = [v for v in arms[arm]["score_age_days"].values() if v is not None]
        oldest = max(ages) if ages else None
        line += (f" {arm}[{arms[arm]['day_state']} age_max={oldest}"
                 f" turn={arms[arm]['turnover_per_year']}]")
    if arms:
        line += f" static_armed={arms['static']['static_armed']}"
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
