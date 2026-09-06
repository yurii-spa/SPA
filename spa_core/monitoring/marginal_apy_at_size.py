"""marginal_apy_at_size.py — ставка пула НЕ зависит от того, сколько мы в него кладём.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO» ставит его дважды:

* §12 «Marginal APY»: «**Обязательно учитывать влияние нашего капитала.** Если vault
  показывает 8% APY, это не означает, что $40k можно разместить под 8%.»
* §49 «Acceptance criteria» → «**Marginal return.**»

Ответ на «учитывается ли» — **НЕТ, по построению.** Целевая функция оптимизатора
линейна по ставке пула::

    _weighted_apy = Σ  weight[pid] · apy[pid]        # spa_core/tuner/allocation_tuner.py
    _score        = _weighted_apy − concentration − constraints

``apy[pid]`` берётся из снимка и НЕ зависит от ``weight[pid]``. Положить в пул $1 и
положить $40 000 — обе раскладки оцениваются одной и той же ставкой. Ровно это
владелец и описал.

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

from spa_core.utils.atomic import atomic_save

# Модель разбавления живёт в ОДНОМ месте (MP-911) — §3 ТЗ запрещает дублировать
# существующие механизмы. Берём приватный ``_diluted_apy``, а не публичный
# ``analyze()``, по измеренной причине: ``analyze()`` округляет ставку до 2 знаков
# (``round(diluted, 2)``), а измеряемый здесь эффект на живой книге — сотые доли
# процентного пункта, и округление обнулило бы ровно то, что мы меряем.
from spa_core.analytics.yield_dilution_analyzer import _diluted_apy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/marginal_apy_at_size.json"

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
        capital = _num(book_doc.get("capital_usd")) or 0.0
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

    # Находка №1 — сам факт, который спрашивал владелец. Он не зависит от снимка:
    # линейность целевой функции есть свойство кода, а не сегодняшних чисел.
    findings.append({
        "severity": "INFO",
        "kind": "objective_is_linear_in_rate",
        "message": (
            "целевая функция оптимизатора линейна по ставке пула "
            "(`_weighted_apy` = Σ weight·apy): размер НАШЕЙ позиции ставку, по "
            "которой её ранжируют, не меняет — §12 ТЗ CIO. Правка ранжирующего "
            "числа money-path, здесь только замер"
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
        "findings": findings,
        "unchecked": unchecked,
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
    return {"OK": 0, "INFO": 0, "WARN": 1, "CRITICAL": 1, "UNCHECKED": 2}[rep["overall"]]


if __name__ == "__main__":                                    # pragma: no cover
    raise SystemExit(_main())
