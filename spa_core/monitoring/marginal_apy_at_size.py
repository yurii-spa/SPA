"""marginal_apy_at_size.py — ставка пула НЕ зависит от того, сколько мы в него кладём.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO» ставит его дважды:

* §12 «Marginal APY»: «**Обязательно учитывать влияние нашего капитала.** Если vault
  показывает 8% APY, это не означает, что $40k можно разместить под 8%.»
* §49 «Acceptance criteria» → «**Marginal return.**»

Ответ на «учитывается ли» — **НЕТ, и это ИЗМЕРЕНО, а не заявлено** (цикл #731).
Целевая функция оптимизатора линейна по ставке пула::

    _weighted_apy = Σ  weight[pid] · apy[pid]        # spa_core/tuner/allocation_tuner.py
    _score        = _weighted_apy − concentration − constraints

``apy[pid]`` берётся из снимка и НЕ зависит от ``weight[pid]``. Положить в пул $1 и
положить $40 000 — обе раскладки оцениваются одной и той же ставкой. Ровно это
владелец и описал.

**Почему слова «и это измерено» здесь стоят отдельно.** До цикла #731 абзац выше
и был всем ответом: находка ``objective_is_linear_in_rate`` добавлялась в отчёт
БЕЗУСЛОВНО, с готовым текстом, при любом снимке. Претензия была верной — и не
проверялась ни разу, то есть пережила бы свой предмет молча: сделай кто-нибудь
ранжирующее число чувствительным к размеру, модуль продолжил бы печатать, что
оно линейно. Теперь ответ даёт :func:`objective_size_sensitivity` — она
спрашивает ЖИВОЙ доходностный член целевой функции дважды, при крошечной позиции
и при наибольшей разрешённой политикой, и сравнивает приписанную ставку. Замер
29.09: **8.0 пп при $40 и 8.0 пп при $40 000, Δ = 0.0**, тогда как модель
разбавления на той же сцене роняет ставку на **0.0318 пп**.

Чего этот модуль НЕ делает
==========================
**Не чинит целевую функцию.** Ранжирующее число — money-path: изменить его значит
изменить раскладку, которую судит гейт. Модуль ADVISORY: он **называет** ошибку и её
размер, а решение — владельца. Капитал по этому вердикту не двигается.

Модель разбавления НЕ пишется заново
====================================
Она в репозитории уже есть — ``spa_core/analytics/yield_dilution_analyzer`` (MP-911),
и §3 ТЗ прямо запрещает дублировать существующие механизмы. Проблема этого модуля не
в математике, а в том, что **он никогда не видел настоящего пула**: ``--run`` считает
``_sample_pools()`` — «TurboFarm USDC», «Distressed LP» и ещё два выдуманных, — и
пишет их в ``data/yield_dilution_log.json``. Потребителя у файла нет. Здесь
переиспользуется именно его ``_diluted_apy``; своей копии формулы нет намеренно.

Три числа, и только ОДНО из них факт
====================================
Разбавление зависит от того, как ставка реагирует на приток. Это допущение, а не
наблюдение, и подавать его как факт нельзя. Поэтому отчёт всегда несёт три величины:

``share_pct``
    наша доля пула, ``d/(T+d)``. **ФАКТ** при наблюдённом ``T``. Ничего не
    предполагает.
``error_pp_definitional``
    разбавляется только наградная часть ставки: фиксированный бюджет эмиссии делится
    на бо́льший TVL. Допущений об эластичности не требует — **нижняя граница**.
``error_pp_modelled``
    документированная модель MP-911 (награда линейно, база — корнем). **ДОПУЩЕНИЕ**,
    названное вслух.
``error_pp_full_elastic``
    обе части разбавляются полностью, ``T/(T+d)``. **Верхняя граница**.

Замер 06.09 стоит того, чтобы его назвать: ``apy_reward`` равен нулю у ВСЕХ ключей,
чей состав ставки измерен. То есть определительный канал разбавления сегодня пуст —
``error_pp_definitional`` = 0.0000 у всей книги, и всё, что больше нуля, приходит
исключительно из допущения об эластичности базы. Сторож, показавший бы одно
модельное число, выдал бы допущение за измерение.

Третий исход
============
``UNCHECKED`` — самостоятельный вердикт с названной причиной, ВЫШЕ ``CRITICAL``.
Разбавление считается делением на TVL, поэтому **литеральный TVL знаменателем не
является**: ``tvl_source != "live"`` ⇒ ключ не измерен, и это говорится вслух.
Замер 06.09: так стоит **$65 000 из $95 000 развёрнутых (68.4 %)** — ``compound_v3``
($3 млрд литералом), ``fluid_usdc`` ($100 млн), ``aave_v3`` ($12 млрд). Тот же порядок,
что у ADR-053 («TVL-floor проверяется ТОЛЬКО живым TVL»): число, которого никто не
наблюдал, не становится знаменателем оттого, что оно большое.

Граница задана САМОЙ политикой, и она движется вместе с капиталом
================================================================
Главный результат — не сегодняшняя ошибка, а её потолок. Пул фондируется, только
если прошёл TVL-floor (``$5 млн``), а доля одного протокола ограничена потолком
концентрации (``40 %`` T1). Значит худшая мыслимая доля пула — это ``cap·C/(floor+cap·C)``
и она зависит ТОЛЬКО от капитала ``C``. Отсюда:

===============  ==================  ====================  ==================
капитал          позиция при 40 %    доля тончайшего пула  ошибка (модель)
===============  ==================  ====================  ==================
$100 000         $40 000             0.79 %                0.032 пп
$1 000 000       $400 000            7.41 %                0.302 пп
$10 000 000      $4 000 000          44.44 %               2.037 пп
===============  ==================  ====================  ==================

Порог существенности взят НЕ из головы: ``min_gain_pp = 0.50`` — это требуемая
выгода перекладки в ``spa_core/allocator/rebalance_economics`` (демпфер ADR-168),
и она уже меряется в пп ОТ ВСЕГО КАПИТАЛА. Поэтому и ошибка приводится к тому же
знаменателю (``вес позиции × ошибка ставки``) — сравнивать пп пула с пп капитала
значило бы сравнивать разные вещи. Пока приведённая ошибка мала против ``0.50``,
линейная целевая функция безвредна не по счастью, а по границе, которую держит
сама политика; когда сравнима — линейность начинает съедать всю требуемую выгоду
целиком, и это перестаёт быть вопросом вкуса.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from spa_core.utils.observation import observed, observed_number

from spa_core.utils.atomic import atomic_save

# Модель разбавления живёт в ОДНОМ месте (MP-911) — §3 ТЗ запрещает дублировать
# существующие механизмы. Берём приватный ``_diluted_apy``, а не публичный
# ``analyze()``, по измеренной причине: ``analyze()`` округляет ставку до 2 знаков
# (``round(diluted, 2)``), а измеряемый здесь эффект на живой книге — сотые доли
# процентного пункта, и округление обнулило бы ровно то, что мы меряем.
from spa_core.analytics.yield_dilution_analyzer import _diluted_apy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/marginal_apy_at_size.json"

# ── чей мерой объявлен этот прибор ───────────────────────────────────────────

#: Критерий §49 ТЗ «Portfolio CIO», мерой которого объявлен ЭТОТ прибор.
#: Проба `card_acceptance` сверяет объявление ПО ЯКОРЮ («§49 Marginal return»),
#: а не подстрокой: подстрока «Marginal return» совпала бы с любой заметкой о
#: предельной доходности (ADR-333).
CRITERION = ("§49 Marginal return — «Position size влияет на expected yield» "
             "(+ тело ТЗ §12 «Marginal APY»: «обязательно учитывать влияние "
             "нашего капитала»)")

CRITERION_SATISFIED = "SATISFIED"
CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
CRITERION_UNMEASURED = "UNMEASURED"

#: Ось находки: каким УТВЕРЖДЕНИЕМ она отвечает на вопрос критерия.
#:
#: `found`       — утверждение СУЩЕСТВОВАНИЯ: ставка, по которой решение
#:                 ранжирует, от нашего размера НЕ зависит (либо зависит, но
#:                 ошибка уже съедает полосу выгоды). Неполнота материала рядом
#:                 такую находку не отменяет.
#: `compared`    — сравнение состоялось, и целевая функция на размер РЕАГИРУЕТ.
#: `unobserved`  — сравнение не состоялось: знаменатель разбавления не наблюдён.
#:                 Третий исход.
#: `context`     — факт об устройстве решения, а не наблюдение дня.
AXIS_FOUND = "found"
AXIS_COMPARED = "compared"
AXIS_UNOBSERVED = "unobserved"
AXIS_CONTEXT = "context"

#: Вид находки → ось. Перечень ЗАКРЫТ: вид, которого здесь нет, обрывает вердикт
#: критерия третьим исходом с названным именем вида. Классифицировать новый вид
#: молча значило бы решить за автора, существование это или его отсутствие.
#:
#: Таблица живёт У ПРИБОРА, а не у пробы: виды порождает он, и вторая копия
#: таблицы рядом с пробой разъехалась бы с ними молча (урок цикла #730).
FINDING_AXIS = {
    "objective_is_linear_in_rate": AXIS_FOUND,
    "objective_reacts_to_our_size": AXIS_COMPARED,
    "linearity_eats_the_gain_band": AXIS_FOUND,
    "denominator_is_a_literal": AXIS_UNOBSERVED,
}

# ── у кого спрашивают про размер ─────────────────────────────────────────────

#: Где живёт целевая функция, у которой спрашивают. Имя объявлено СТРОКОЙ, а не
#: зашито импортом в теле замера: контроль подменяет модуль в ``sys.modules`` и
#: убеждается, что замер читает ЖИВУЮ функцию, а не свою копию её свойства.
OBJECTIVE_MODULE = "spa_core.tuner.allocation_tuner"

#: Член целевой функции, который приписывает раскладке ожидаемую доходность.
#: Переименуют или унесут — замер обязан сказать «НЕ ИЗМЕРЕНО» с адресом, а не
#: промолчать: именно так напечатанная претензия и переживает свой предмет.
OBJECTIVE_YIELD_TERM = "_weighted_apy"

#: Ключ сцены замера. Синтетический по построению — ни в одном реестре его нет,
#: столкнуться с живым протоколом сцена не может.
PROBE_POOL_ID = "probe_marginal_return_pool"

#: Ставка сцены, пп. Взята НЕ из головы: это дословное число примера владельца в
#: §12 ТЗ («если vault показывает 8% APY, это не означает, что $40k можно
#: разместить под 8%»). Масштаб, а не чья-то доходность.
PROBE_RATE_PP = 8.0

#: Порог «функция вернула ДРУГОЕ число». Он ЧИСЛЕННЫЙ, а не политический: он
#: отделяет шум двоичной арифметики от реакции на размер и ничьим решением не
#: является. Что он на порядки ниже настоящего эффекта — не предположение, а
#: замер: рядом печатается ``reference_dilution_pp`` — насколько ставку роняет
#: модель разбавления на ТОЙ ЖЕ сцене (29.09: 0.0318 пп, то есть в ~3·10⁷ раз
#: больше этого порога). Сравнивать их читателю не приходится: обе величины
#: стоят в отчёте рядом.
NUMERICAL_EPS_PP = 1e-9

# Ни одного порога этот модуль НЕ назначает. Все три читаются из своих домов:
# TVL-floor и потолок концентрации — ``TunerConstraints`` (те самые, которыми
# оптимизатор отбирает пулы), требуемая выгода перекладки — ``TriggerParams.for_mode()``
# (демпфер ADR-168, пп ОТ ВСЕГО КАПИТАЛА, колонка зависит от режима капитала).
#
# Запасного литерала здесь НЕТ намеренно. Порог, не прочитанный из своего дома, —
# это «не измерено», а не число: подставь мы 0.50 «на всякий случай», отчёт стал бы
# неотличим от прочитавшего настоящую политику, и расхождение с ней росло бы молча.
# Класс разобран в `.claude/rules/deployment.md` («отсутствие инструмента —
# самостоятельный третий исход, а не число и не скип»).


def _policy_limits() -> tuple[float | None, float | None, float | None, list[str], list[str]]:
    """(tvl_floor, protocol_cap, min_gain_pp, провенанс, ОТКАЗЫ).

    Непрочитанный порог возвращается как ``None`` вместе с названной причиной —
    вызывающий обязан объявить это ``UNCHECKED``, а не считать по литералу.
    """
    provenance: list[str] = []
    refusals: list[str] = []
    floor = cap = min_gain = None
    try:
        from spa_core.tuner.allocation_tuner import TunerConstraints

        c = TunerConstraints()
        floor = float(c.tvl_floor_usd)
        cap = float(max(c.per_protocol_t1_max, c.per_protocol_t2_max))
        provenance.append(
            f"TunerConstraints: tvl_floor_usd={floor:,.0f}, protocol_cap={cap}")
    except Exception as exc:
        refusals.append(
            f"TVL-floor и потолок концентрации не прочитаны из TunerConstraints ({exc}) "
            f"— граница политики не считается по литералу")
    try:
        from spa_core.allocator.rebalance_economics import TriggerParams

        p = TriggerParams.for_mode()
        min_gain = float(p.min_gain_pp)
        provenance.append(
            f"TriggerParams.for_mode(mode={getattr(p, 'mode', None)!r}): "
            f"min_gain_pp={min_gain}")
    except Exception as exc:
        refusals.append(
            f"требуемая выгода перекладки не прочитана из TriggerParams ({exc}) "
            f"— порог существенности не назначается этим модулем")
    return floor, cap, min_gain, provenance, refusals


@dataclass(frozen=True)
class PoolMeasurement:
    """Одна позиция книги против одного пула снимка."""

    key: str
    amount_usd: float
    tvl_usd: float | None
    tvl_source: str | None
    apy_pct: float | None
    apy_base_pct: float | None
    apy_reward_pct: float | None
    measured: bool
    reason: str | None
    share_pct: float | None
    error_pp_definitional: float | None
    error_pp_modelled: float | None
    error_pp_full_elastic: float | None
    blended_error_pp_modelled: float | None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "amount_usd": round(self.amount_usd, 2),
            "tvl_usd": self.tvl_usd,
            "tvl_source": self.tvl_source,
            "apy_pct": self.apy_pct,
            "apy_base_pct": self.apy_base_pct,
            "apy_reward_pct": self.apy_reward_pct,
            "measured": self.measured,
            "reason": self.reason,
            "share_pct": self.share_pct,
            "error_pp_definitional": self.error_pp_definitional,
            "error_pp_modelled": self.error_pp_modelled,
            "error_pp_full_elastic": self.error_pp_full_elastic,
            "blended_error_pp_modelled": self.blended_error_pp_modelled,
        }


def _num(v: object) -> float | None:
    """Число или None. bool числом НЕ считается."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _import_module(name: str) -> Any:
    """Импорт по ИМЕНИ — вход замера, чтобы контроль мог подставить свою дверь."""
    import importlib
    return importlib.import_module(name)


def measure_pool(
    key: str,
    amount_usd: float,
    row: dict,
    capital_usd: float,
) -> PoolMeasurement:
    """Одна позиция. Не измеряется — говорит ПОЧЕМУ, а не молчит нулём."""
    tvl = _num(row.get("tvl_usd"))
    src = row.get("tvl_source")
    apy = _num(row.get("apy"))
    base = _num(row.get("apy_base"))
    reward = _num(row.get("apy_reward"))

    def _unmeasured(reason: str) -> PoolMeasurement:
        return PoolMeasurement(
            key=key, amount_usd=amount_usd, tvl_usd=tvl, tvl_source=src,
            apy_pct=apy, apy_base_pct=base, apy_reward_pct=reward,
            measured=False, reason=reason, share_pct=None,
            error_pp_definitional=None, error_pp_modelled=None,
            error_pp_full_elastic=None, blended_error_pp_modelled=None,
        )

    # Знаменатель разбавления — только НАБЛЮДЁННЫЙ TVL (тот же порядок, что
    # ADR-053 для TVL-floor). Литерал знаменателем не становится от величины.
    if src != "live":
        return _unmeasured(
            f"TVL не наблюдён (tvl_source={src!r}) — знаменатель разбавления "
            f"был бы литералом, а не измерением"
        )
    if tvl is None or tvl <= 0:
        return _unmeasured(f"TVL непригоден как знаменатель (tvl_usd={row.get('tvl_usd')!r})")
    if base is None and reward is None:
        return _unmeasured(
            "состав ставки не измерен (apy_base/apy_reward отсутствуют) — "
            "разделить наградную часть от базовой не на чем"
        )

    b = base if base is not None else 0.0
    r = reward if reward is not None else 0.0
    total = apy if apy is not None else (b + r)

    share = amount_usd / (tvl + amount_usd)
    factor = tvl / (tvl + amount_usd)          # T/(T+d)

    # ФАКТ: наградная часть делится на больший TVL. Допущений не требует.
    err_definitional = r * (1.0 - factor)
    # ДОПУЩЕНИЕ MP-911: награда линейно, база корнем. Считает чужой модуль.
    err_modelled = total - _diluted_apy(r, b, tvl, amount_usd)
    # ВЕРХНЯЯ ГРАНИЦА: обе части полностью эластичны.
    err_full = total * (1.0 - factor)

    # Приведение к знаменателю min_gain_pp: тот меряется в пп ОТ ВСЕГО КАПИТАЛА.
    weight = (amount_usd / capital_usd) if capital_usd > 0 else 0.0
    blended = err_modelled * weight

    return PoolMeasurement(
        key=key, amount_usd=amount_usd, tvl_usd=tvl, tvl_source=src,
        apy_pct=apy, apy_base_pct=base, apy_reward_pct=reward,
        measured=True, reason=None,
        share_pct=round(share * 100.0, 6),
        error_pp_definitional=round(err_definitional, 6),
        error_pp_modelled=round(err_modelled, 6),
        error_pp_full_elastic=round(err_full, 6),
        blended_error_pp_modelled=round(blended, 6),
    )


def policy_bound(capital_usd: float, tvl_floor: float, protocol_cap: float) -> dict:
    """Худшая мыслимая доля пула при ДАННОМ капитале — из потолков самой политики.

    Тончайший фондируемый пул — ровно на TVL-floor; крупнейшая допустимая позиция —
    ``cap · capital``. Ставка взята 8.0 пп исключительно как МАСШТАБ для перевода
    доли в пп (эффект пропорционален ставке); число объявлено в отчёте, чтобы его
    не прочли как чью-то доходность.
    """
    position = protocol_cap * capital_usd
    denom = tvl_floor + position
    share = (position / denom) if denom > 0 else 0.0
    ref_rate = 8.0
    err_pool = ref_rate - _diluted_apy(0.0, ref_rate, tvl_floor, position)
    return {
        "capital_usd": round(capital_usd, 2),
        "tvl_floor_usd": tvl_floor,
        "protocol_cap": protocol_cap,
        "position_usd": round(position, 2),
        "worst_case_share_pct": round(share * 100.0, 6),
        "reference_rate_pp": ref_rate,
        "worst_case_error_pp_pool": round(err_pool, 6),
        "worst_case_error_pp_blended": round(err_pool * protocol_cap, 6),
    }


def scale_ceiling(
    tvl_floor: float,
    protocol_cap: float,
    min_gain_pp: float,
    *,
    max_capital_usd: float = 1_000_000_000.0,
) -> dict:
    """При каком капитале приведённая худшая ошибка догоняет требуемую выгоду.

    Монотонная по капиталу величина ⇒ двоичный поиск, детерминированно.
    Не догоняет в пределах ``max_capital_usd`` ⇒ говорим это, а не выдумываем число.
    """
    def _blended(c: float) -> float:
        return policy_bound(c, tvl_floor, protocol_cap)["worst_case_error_pp_blended"]

    if _blended(max_capital_usd) < min_gain_pp:
        return {
            "min_gain_pp": min_gain_pp,
            "capital_usd_at_crossing": None,
            "reason": (
                f"приведённая худшая ошибка не догоняет {min_gain_pp} пп даже при "
                f"${max_capital_usd:,.0f} капитала"
            ),
        }
    lo, hi = 0.0, max_capital_usd
    for _ in range(200):                       # фиксированное число шагов = детерминизм
        mid = (lo + hi) / 2.0
        if _blended(mid) < min_gain_pp:
            lo = mid
        else:
            hi = mid
    return {
        "min_gain_pp": min_gain_pp,
        "capital_usd_at_crossing": round(hi, 2),
        "reason": None,
    }


def objective_size_sensitivity(
    capital_usd: float,
    tvl_floor: float | None,
    protocol_cap: float | None,
    *,
    importer: Callable[[str], Any] | None = None,
) -> dict:
    """Спросить ЖИВУЮ целевую функцию: меняется ли приписанная ставка от РАЗМЕРА.

    Находка цикла #731, ради которой замер и написан
    ---------------------------------------------------------------------------
    До этого цикла модуль отвечал на главный вопрос владельца **напечатанным
    предложением**: находка ``objective_is_linear_in_rate`` добавлялась в отчёт
    БЕЗУСЛОВНО, при любом снимке, и её текст («целевая функция линейна по ставке
    пула») был утверждением автора, прочитавшего код однажды. Утверждение верно и
    сегодня — но никто его не спрашивал у кода ни разу, а значит:

    * сделай кто-нибудь целевую функцию чувствительной к размеру — модуль
      продолжил бы печатать, что она линейна, и вердикт §49 стал бы молча ложным;
    * перенести такую находку в машинный вердикт критерия значило бы перенести
      ПРОЗУ, то есть ровно тот дефект, против которого написана вся эта работа
      (`.claude/rules/site-numbers.md`: перепечатанное число не расходится — оно
      перестаёт быть правдой молча).

    Поэтому претензия стала ЗАМЕРОМ, и замер ДИФФЕРЕНЦИАЛЬНЫЙ.

    Как он устроен
    ---------------------------------------------------------------------------
    Строится сцена из ОДНОГО синтетического пула со ставкой :data:`PROBE_RATE_PP`
    и у живого члена целевой функции (:data:`OBJECTIVE_YIELD_TERM` модуля
    :data:`OBJECTIVE_MODULE`) дважды спрашивается приписанная доходность — при
    крошечной позиции и при НАИБОЛЬШЕЙ разрешённой политикой (``cap·capital``,
    те самые «$40k» из примера владельца). Обе величины приводятся к ставке за
    единицу веса. Совпали ⇒ размер на ранжирующее число не влияет.

    Границы сцены заданы ПОЛИТИКОЙ, а не этим модулем: потолок концентрации и
    TVL-floor приходят из ``TunerConstraints`` (см. :func:`_policy_limits`).
    Непрочитанный порог ⇒ сцену строить не из чего ⇒ третий исход с причиной, а
    не «функция линейна» по умолчанию.

    Чего замер НЕ докладывает
    ---------------------------------------------------------------------------
    * **Верность самой ставки.** Сцена синтетическая: спрашивается СВОЙСТВО
      функции (реагирует ли она на размер), а не сегодняшняя доходность книги.
    * **Штрафы целевой функции.** Концентрационный штраф от весов зависит, и это
      не «учёт размера в ожидаемой доходности», а штраф. Спрашивается ровно
      доходностный член.
    * **Пути, идущие мимо этого члена.** Если ожидаемую доходность где-то считают
      ещё раз своей копией, замер об этом не знает — он судит объявленную дверь.

    Возврат — словарь с ``measured``; ``False`` несёт ``reason``. Числа при
    неизмеренном замере остаются ``None``: ноль сюда не подставляется (инв. #17).
    """
    out: dict = {
        "measured": False,
        "reason": None,
        "objective": f"{OBJECTIVE_MODULE}.AllocationTuner.{OBJECTIVE_YIELD_TERM}",
        "small_usd": None,
        "large_usd": None,
        "rate_at_small_pp": None,
        "rate_at_large_pp": None,
        "delta_pp": None,
        "reference_dilution_pp": None,
        "size_aware": None,
    }

    if capital_usd is None or capital_usd <= 0:
        out["reason"] = ("капитал книги не прочитан — размеры сцены задаются "
                         "потолком политики ОТ КАПИТАЛА, и без него сцены нет")
        return out
    if protocol_cap is None or tvl_floor is None:
        out["reason"] = ("потолок концентрации и/или TVL-floor не прочитаны из "
                         "`TunerConstraints` — сцену строить не из чего, и "
                         "литералом они здесь не заменяются")
        return out

    large = float(protocol_cap) * float(capital_usd)
    small = large / 1000.0
    if large <= 0 or small <= 0:
        out["reason"] = (f"размеры сцены непригодны (большая ${large:,.2f}, "
                         f"малая ${small:,.2f}) — спрашивать нечем")
        return out
    out["small_usd"] = round(small, 6)
    out["large_usd"] = round(large, 2)

    imp = importer or _import_module
    try:
        module = imp(OBJECTIVE_MODULE)
    except BaseException as exc:                      # noqa: BLE001
        out["reason"] = (f"целевая функция не загружена ({OBJECTIVE_MODULE}): "
                         f"{type(exc).__name__}: {exc}")
        return out

    tuner_cls = getattr(module, "AllocationTuner", None)
    if tuner_cls is None:
        out["reason"] = (f"в {OBJECTIVE_MODULE} нет `AllocationTuner` — целевая "
                         f"функция переехала, и спросить её НЕ У ЧЕГО")
        return out
    try:
        tuner = tuner_cls()
    except BaseException as exc:                      # noqa: BLE001
        out["reason"] = (f"`AllocationTuner()` не построен: "
                         f"{type(exc).__name__}: {exc}")
        return out

    term = getattr(tuner, OBJECTIVE_YIELD_TERM, None)
    if not callable(term):
        out["reason"] = (f"у целевой функции нет вызываемого "
                         f"`{OBJECTIVE_YIELD_TERM}` — доходностный член "
                         f"переименован или унесён; молчать об этом нельзя")
        return out

    scene = [{"id": PROBE_POOL_ID, "apy": PROBE_RATE_PP, "tier": "T1"}]
    rates: list[float] = []
    for amount in (small, large):
        weight = amount / float(capital_usd)
        try:
            value = term({PROBE_POOL_ID: weight}, scene)
        except BaseException as exc:                  # noqa: BLE001
            out["reason"] = (f"доходностный член целевой функции упал на сцене "
                             f"(${amount:,.2f}): {type(exc).__name__}: {exc}")
            return out
        number = _num(value)
        if number is None or weight <= 0:
            out["reason"] = (f"доходностный член вернул непригодное значение "
                             f"{value!r} при весе {weight!r} — ставка за единицу "
                             f"веса НЕ ИЗМЕРЕНА")
            return out
        rates.append(number / weight)

    rate_small, rate_large = rates
    delta = rate_small - rate_large
    out.update({
        "measured": True,
        "rate_at_small_pp": round(rate_small, 9),
        "rate_at_large_pp": round(rate_large, 9),
        "delta_pp": round(delta, 9),
        # Насколько ту же ставку роняет МОДЕЛЬ разбавления на той же сцене:
        # масштаб настоящего эффекта рядом с численным порогом. Считает чужой
        # модуль (MP-911), своей копии формулы здесь нет.
        "reference_dilution_pp": round(
            PROBE_RATE_PP - _diluted_apy(0.0, PROBE_RATE_PP, float(tvl_floor), large), 9),
        "size_aware": abs(delta) > NUMERICAL_EPS_PP,
    })
    return out


def _criterion_block(findings: list[dict], unchecked: list[str],
                     sensitivity: dict, *, deployed_usd: float) -> dict:
    """Вердикт КРИТЕРИЯ §49 `Marginal return` — и почему он НЕ есть ``overall``.

    ``overall`` у этого прибора — лестница ТЯЖЕСТИ для здоровья артефакта, и
    третий исход стои́т в ней ВЫШЕ ``CRITICAL`` намеренно. Для здоровья это
    верно; для вердикта критерия тот же порядок был бы ложью в другую сторону:
    находка «ранжирующая ставка от размера не зависит» есть утверждение
    СУЩЕСТВОВАНИЯ, и непрочитанный рядом пул её не отменяет. Перенести
    ``overall`` значило бы спрятать измеренное красное за «не измерено» —
    инвариант #17 наизнанку (урок цикла #730, ADR-513).

    Порядок разрешения:

    1. вид находки не объявлен осью ⇒ третий исход с именем вида;
    2. есть находка оси ``found`` ⇒ ``NOT_SATISFIED`` независимо от неполноты;
    3. иначе есть ``unchecked`` или находка оси ``unobserved`` ⇒ третий исход;
    4. иначе ЗЕЛЁНЫЙ путь, и только на нём спрашивается законность: развёрнут ли
       вообще капитал. «Размер учитывается» про пустую книгу — тишина мёртвого
       дерева, а не ответ о системе.
    """
    found: list[str] = []
    unobserved: list[str] = []
    compared: list[str] = []
    for f in findings:
        kind = str(f.get("kind"))
        axis = FINDING_AXIS.get(kind)
        if axis is None:
            return {"criterion": CRITERION, "status": CRITERION_UNMEASURED,
                    "reason": (f"у находки {kind!r} не объявлена ось "
                               f"(`FINDING_AXIS`) — отнести её к существованию "
                               f"или к его отсутствию молча нельзя"),
                    "found": [], "unobserved": [], "compared": [],
                    "sensitivity": sensitivity}
        if axis == AXIS_FOUND:
            found.append(kind)
        elif axis == AXIS_UNOBSERVED:
            unobserved.append(kind)
        elif axis == AXIS_COMPARED:
            compared.append(kind)

    base = {"criterion": CRITERION, "found": sorted(set(found)),
            "unobserved": sorted(set(unobserved)),
            "compared": sorted(set(compared)), "sensitivity": sensitivity}

    if found:
        return dict(base, status=CRITERION_NOT_SATISFIED,
                    reason=("размер позиции на ожидаемую доходность решения не "
                            "влияет: " + ", ".join(sorted(set(found)))
                            + " — находка существования, и неполнота материала "
                              "рядом её не отменяет"))
    if unchecked or unobserved:
        why = list(unchecked) + [f"находка {k}" for k in sorted(set(unobserved))]
        return dict(base, status=CRITERION_UNMEASURED,
                    reason=("спросить решение о влиянии размера было нечем: "
                            + "; ".join(why)))
    if deployed_usd <= 0:
        return dict(base, status=CRITERION_UNMEASURED,
                    reason=("книга пуста (развёрнуто $0) — «размер учитывается» "
                            "отсюда было бы тишиной мёртвого дерева, а не "
                            "ответом о системе"))
    return dict(base, status=CRITERION_SATISFIED,
                reason=(f"целевая функция на размер РЕАГИРУЕТ (измерено: ставка "
                        f"{sensitivity.get('rate_at_small_pp')} пп при "
                        f"${sensitivity.get('small_usd')} против "
                        f"{sensitivity.get('rate_at_large_pp')} пп при "
                        f"${sensitivity.get('large_usd')}), и знаменатель "
                        f"разбавления наблюдён у всего развёрнутого капитала "
                        f"(${deployed_usd:,.2f})"))


def run(
    root: str = REPO_ROOT,
    *,
    write: bool = True,
    data_dir: str | None = None,
    now: dt.datetime | None = None,
    reader: Callable[[str], Any] | None = None,
) -> dict:
    """Замер на живом снимке. Часы и чтение — ВХОДЫ, чтобы тест был бессмертен."""
    now = now or dt.datetime.now(dt.timezone.utc)
    read = reader or _read_json
    ddir = data_dir or os.path.join(root, "data")

    findings: list[dict] = []
    unchecked: list[str] = []

    status_path = os.path.join(ddir, "adapter_status.json")
    book_path = os.path.join(ddir, "current_positions.json")

    try:
        status = read(status_path)
        adapters = status.get("adapters")
        if not isinstance(adapters, dict):
            raise ValueError(f"adapters имеет форму {type(adapters).__name__}, ожидался dict")
    except Exception as exc:
        adapters = None
        unchecked.append(f"снимок адаптеров не прочитан ({status_path}): {exc}")
    try:
        book_doc = read(book_path)
        positions = book_doc.get("positions")
        capital = observed_number(book_doc, "capital_usd")
        if capital is None:
            raise ValueError("в книге нет capital_usd — доли размера не измеримы")
        if not isinstance(positions, dict):
            raise ValueError(f"positions имеет форму {type(positions).__name__}, ожидался dict")
    except Exception as exc:
        positions, capital = None, 0.0
        unchecked.append(f"книга не прочитана ({book_path}): {exc}")

    measurements: list[dict] = []
    deployed = 0.0
    unmeasured_capital = 0.0
    if adapters is not None and positions is not None:
        for key in sorted(positions):
            amt = _num(positions[key])
            if amt is None or amt <= 0:
                continue
            deployed += amt
            m = measure_pool(key, amt, adapters.get(key) or {}, capital)
            measurements.append(m.to_dict())
            if not m.measured:
                unmeasured_capital += amt
                unchecked.append(f"{key} (${amt:,.0f}): {m.reason}")

    floor, cap, min_gain, provenance, refusals = _policy_limits()
    unchecked.extend(refusals)
    limits_ok = floor is not None and cap is not None
    bound = policy_bound(capital, floor, cap) if (limits_ok and capital > 0) else None
    ceiling = (
        scale_ceiling(floor, cap, min_gain)
        if (limits_ok and min_gain is not None)
        else {"min_gain_pp": min_gain, "capital_usd_at_crossing": None,
              "reason": "пороги политики не прочитаны из своих домов — см. `unchecked`"}
    )

    # Находка №1 — сам вопрос владельца, и она СПРАШИВАЕТСЯ У КОДА, а не
    # печатается. До цикла #731 здесь безусловно добавлялась готовая фраза
    # «целевая функция линейна»: верная сегодня и не проверенная ни разу — то
    # есть претензия, способная пережить свой предмет молча. Теперь это
    # дифференциальный замер живой целевой функции (`objective_size_sensitivity`),
    # и «спросить не вышло» — третий исход с причиной, а не прежнее умолчание.
    sensitivity = objective_size_sensitivity(capital, floor, cap)
    if not sensitivity["measured"]:
        unchecked.append(
            f"целевую функцию о влиянии размера НЕ СПРОСИЛИ: {sensitivity['reason']}")
    elif sensitivity["size_aware"]:
        findings.append({
            "severity": "INFO",
            "kind": "objective_reacts_to_our_size",
            "message": (
                f"ИЗМЕРЕНО у живой целевой функции ({sensitivity['objective']}): "
                f"приписанная ставка падает с {sensitivity['rate_at_small_pp']} пп "
                f"при ${sensitivity['small_usd']:,.2f} до "
                f"{sensitivity['rate_at_large_pp']} пп при "
                f"${sensitivity['large_usd']:,.2f} — размер позиции на ранжирующее "
                f"число влияет"
            ),
        })
    else:
        findings.append({
            "severity": "INFO",
            "kind": "objective_is_linear_in_rate",
            "message": (
                f"ИЗМЕРЕНО дифференциально у живой целевой функции "
                f"({sensitivity['objective']}): приписанная ставка одна и та же — "
                f"{sensitivity['rate_at_small_pp']} пп при "
                f"${sensitivity['small_usd']:,.2f} и при "
                f"${sensitivity['large_usd']:,.2f} (Δ {sensitivity['delta_pp']} пп), "
                f"тогда как модель разбавления на той же сцене роняет её на "
                f"{sensitivity['reference_dilution_pp']} пп. Размер НАШЕЙ позиции "
                f"ставку, по которой её ранжируют, не меняет — §12 ТЗ CIO. Правка "
                f"ранжирующего числа money-path, здесь только замер"
            ),
        })

    if unmeasured_capital > 0 and deployed > 0:
        pct = unmeasured_capital / deployed * 100.0
        findings.append({
            "severity": "WARN",
            "kind": "denominator_is_a_literal",
            "message": (
                f"${unmeasured_capital:,.0f} из ${deployed:,.0f} развёрнутых "
                f"({pct:.1f} %) стоят в пулах с ЛИТЕРАЛЬНЫМ TVL — влияние нашего "
                f"размера на ставку там не считается ни в какую сторону"
            ),
        })

    if (bound is not None and min_gain is not None
            and bound["worst_case_error_pp_blended"] >= min_gain):
        findings.append({
            "severity": "CRITICAL",
            "kind": "linearity_eats_the_gain_band",
            "message": (
                f"при капитале ${capital:,.0f} худшая приведённая ошибка "
                f"{bound['worst_case_error_pp_blended']:.3f} пп ≥ требуемой выгоды "
                f"перекладки {min_gain} пп — линейная ставка способна съесть весь "
                f"порог целиком"
            ),
        })

    counts = {"critical": 0, "warn": 0, "info": 0, "unchecked": len(unchecked)}
    for f in findings:
        counts[str(f["severity"]).lower()] = counts.get(str(f["severity"]).lower(), 0) + 1

    if counts["unchecked"]:
        overall = "UNCHECKED"
    elif counts["critical"]:
        overall = "CRITICAL"
    elif counts["warn"]:
        overall = "WARN"
    elif counts["info"]:
        overall = "INFO"
    else:
        overall = "OK"

    report = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "capital_usd": round(capital, 2),
        "deployed_usd": round(deployed, 2),
        "unmeasured_capital_usd": round(unmeasured_capital, 2),
        "unmeasured_capital_pct": (
            round(unmeasured_capital / deployed * 100.0, 2) if deployed > 0 else None
        ),
        "measurements": measurements,
        "policy_bound": bound,
        "scale_ceiling": ceiling,
        "policy_provenance": provenance,
        "objective_size_sensitivity": sensitivity,
        "findings": findings,
        "unchecked": unchecked,
        "criterion": _criterion_block(findings, unchecked, sensitivity,
                                      deployed_usd=deployed),
        "note": (
            "ADVISORY. Отвечает на §12 «Marginal APY» и §49 «Marginal return» ТЗ "
            "«Portfolio CIO». Капитал по этому вердикту НЕ двигается: целевая функция "
            "оптимизатора не трогается, RiskPolicy и пороги не трогаются. Модель "
            "разбавления не дублируется — переиспользован MP-911 "
            "`yield_dilution_analyzer._diluted_apy`. Из трёх величин ошибки ФАКТОМ "
            "является только `error_pp_definitional` (наградная часть делится на "
            "больший TVL); `error_pp_modelled` — документированное допущение MP-911 об "
            "эластичности базы, `error_pp_full_elastic` — верхняя граница."
        ),
    }
    if write:
        atomic_save(report, os.path.join(root, REPORT_REL))
    return report


def _main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)

    rep = run(root=args.root, write=not args.no_save, data_dir=args.data_dir)
    c = rep["counts"]
    print(f"marginal_apy_at_size: {rep['overall']} (critical={c['critical']} "
          f"warn={c['warn']} info={c['info']} unchecked={c['unchecked']})")
    for m in rep["measurements"]:
        if m["measured"]:
            print(f"   {m['key']:22} ${m['amount_usd']:>10,.0f} · наша доля пула "
                  f"{m['share_pct']:.4f} % · ошибка ставки: факт "
                  f"{m['error_pp_definitional']:.4f} пп / модель "
                  f"{m['error_pp_modelled']:.4f} пп / верх "
                  f"{m['error_pp_full_elastic']:.4f} пп")
        else:
            print(f"   {m['key']:22} ${m['amount_usd']:>10,.0f} · [НЕ ИЗМЕРЕНО] {m['reason']}")
    b = rep["policy_bound"]
    if b:
        print(f"   граница политики: позиция ${b['position_usd']:,.0f} в пуле на "
              f"TVL-floor ${b['tvl_floor_usd']:,.0f} ⇒ доля "
              f"{b['worst_case_share_pct']:.2f} %, приведённая ошибка "
              f"{b['worst_case_error_pp_blended']:.4f} пп")
    sc = rep["scale_ceiling"]
    if sc.get("capital_usd_at_crossing") is not None:
        print(f"   потолок масштаба: приведённая ошибка догоняет требуемую выгоду "
              f"{sc['min_gain_pp']} пп при капитале "
              f"${sc['capital_usd_at_crossing']:,.0f}")
    for u in rep["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {u}")
    cr = rep["criterion"]
    print(f"   §49 Marginal return: {cr['status']} — {cr['reason']}")
    return {"OK": 0, "INFO": 0, "WARN": 1, "CRITICAL": 1, "UNCHECKED": 2}[rep["overall"]]


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(_main())
