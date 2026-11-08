"""Marginal APY — §12 приказа владельца «Portfolio CIO» (влияние СВОЕГО размера).

Предмет — дословный текст ТЗ владельца из якорной карточки
`inbox-task-portfolio-cio-dynamic-capital-alloc`:

    §12 «Marginal APY. Обязательно учитывать влияние нашего капитала. Если vault
    показывает 8% APY, это не означает, что $40k можно разместить под 8%. Нужно
    оценивать: APY at +$5k · APY at +$10k · APY at +$20k · APY at +$40k, если
    протокол позволяет получить такую оценку. Учитывать: TVL dilution;
    utilization; reward dilution; capacity; deposit caps; liquidity; withdrawal
    depth. Optimizer должен по возможности распределять капитал по marginal
    return curve.»

Заказ G943 п. 1 требует начинать с ЗАМЕРА, а не с кода: какие из семи названных
владельцем осей измеримы сегодня, а какие слепы. Этот модуль и есть тот замер —
плюс сама лестница по тем осям, которые измеримы.

ГЛАВНОЕ УСТРОЙСТВО: лестница отдаёт ВИЛКУ, а не точку
=====================================================
Из трёх величин, которыми можно ответить «ставка при добавлении суммы», ФАКТОМ
является только одна, и это уже было установлено соседом (`monitoring/
marginal_apy_at_size.py`, ADR-242): наградная часть ставки платится ФИКСИРОВАННЫМ
потоком эмиссии, поэтому при росте TVL она делится на больший знаменатель
ОПРЕДЕЛИТЕЛЬНО. Поведение БАЗОВОЙ части — это модель, а не наблюдение: ряда
«ставка против TVL» у наших протоколов не пишет никто (ось `tvl_dilution` ниже).

Поэтому каждая ступень лестницы несёт ТРИ числа РАЗНОГО РОДА, и смешивать их
запрещено (поправка C2 ADR-580: сравнение ставок допускается только внутри одного
рода):

* `apy_upper_pct` — разбавлена ТОЛЬКО наградная часть, база держится постоянной.
  Это ВЕРХНЯЯ граница: все семь осей §12 действуют в одну сторону — вниз
  (приток капитала не повышает ставку пула, потолок вклада её не повышает,
  глубина выхода её не повышает). Число не является ожиданием;
* `apy_modelled_pct` — та же наградная часть плюс объявленное допущение MP-911
  об эластичности базы (`√`-разбавление, `yield_dilution_analyzer._diluted_apy`,
  переиспользовано, а не переписано);
* `apy_lower_pct` — база разбавлена ПОЛНОСТЬЮ (как наградная): граница вреда
  сверху, то есть ставки снизу.

Ширина вилки `apy_bracket_width_pp` И ЕСТЬ цена слепых осей, выраженная числом.
Назвать одну из трёх величин «ставкой при размере» значило бы напечатать модель с
меткой наблюдения — ровно дефект, против которого написана поправка C2.

НОВОЕ СОСТОЯНИЕ ОСИ: «предмет записи ВЫДУМАН»
=============================================
§10/§11 (ADR-954) различали у слепой оси четыре состояния: файла нет · файл есть
и ПУСТ · данные старше срока · данные есть, а потребителя формулы нет. Замер
этого цикла нашёл ПЯТОЕ, и оно опаснее пустоты:

    `reward_dilution_velocity_log.json` — 100 записей, предмет `TestProtocol`
    `liquidity_mining_dilution_log.json` — 100 записей, предмет `TestProtocol`
    `deposit_cap_headroom_log.json` — предметы `USDC-Vault-Ample`, `ETH-Vault-NearCap`
    `staking_withdrawal_queue_log.json` — предмет `unknown`, позиция $0
    `tvl_yield_elasticity_log.json` — предметы `FARM-pool (incentive-heavy, small)`,
    `stETH (base-heavy, deep)`

Такой файл НЕ ПУСТ, у него бывает свежая отметка, и по длине он неотличим от
живого наблюдения — но ни одно его число нельзя привязать к НАШЕЙ возможности,
потому что предмета с таким именем у нас нет. Это тот же класс, что ADR-940
(«пустой перечень, читаемый только циклом, есть ЛОЖНОЕ УСИЛЕНИЕ»), только
сильнее: пустоту видно `len()`, а выдуманный предмет виден ТОЛЬКО привязкой по
имени. Поэтому привязка здесь — ЗАМЕР (пересечение имён записей с именами наших
возможностей), а не список подозрительных слов: перечень имён вроде
«TestProtocol» был бы догадкой и промахнулся бы на шестом файле.

ОДНО ИМЯ — ОДИН ОБЪЕКТ: рядом живёт СОСЕД с похожим предметом
=============================================================
Имя `marginal_apy_at_size` ЗАНЯТО, и занято не случайно: соседний прибор
`spa_core/monitoring/marginal_apy_at_size.py` (цикл #493) отвечает на ДРУГОЙ
вопрос и пишет свой артефакт `data/marginal_apy_at_size.json`. Назвать этим же
именем вторую вещь значило бы повторить дефект `.claude/rules/adapters.md`
§ «Одно имя — один объект» (цикл #274: три РАЗНЫХ набора звались
`ADAPTER_REGISTRY`, и три месяца врал `house_view_gap`). Поэтому:

| имя | что отвечает | форма числа |
|---|---|---|
| `marginal_apy_at_size` (monitoring, ADR-242) | какова ОШИБКА игнорирования размера при одной опорной сумме и знает ли о размере целевая функция тюнера | одна сумма ($5k) · три величины ошибки |
| `marginal_apy_ladder` (этот модуль, §12) | какова ставка на ЛЕСТНИЦЕ владельца (+$5/10/20/40k) и какие из СЕМИ осей §12 измеримы сегодня | четыре ступени · вилка · перепись осей |

Составы РАЗНЫЕ и совпадать не обязаны; переиспользована у соседа МОДЕЛЬ
разбавления (MP-911), а не имя.

Чего прибор НЕ делает
=====================
`IS_ADVISORY = True`. Только ЧИТАЕТ: ни один производитель не правлен, капитал не
двигается, RiskPolicy, стоп-кран, потолки концентрации и целевая функция тюнера
не тронуты ни строкой. Требование §12 «optimizer должен распределять капитал по
marginal return curve» — ПРЕДМЕТ №1 границы ADR-285 (движение денег), и этот
модуль его не исполняет, а лишь называет замером: целевая функция тюнера линейна
по ставке и размера не знает (`data/marginal_apy_at_size.json`,
`objective_size_sensitivity.size_aware = false`).

stdlib-only · LLM FORBIDDEN.

Перемер руками::

    python3 -m spa_core.analytics.apy_marginal --data-dir <путь>/data

Коды возврата: 0 — лестница измерена хотя бы у одной возможности ·
1 — находки (ни одной измеренной лестницы) · 2 — НЕ ИЗМЕРЕНО (вход не прочитан).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .yield_dilution_analyzer import _dilution_factor, _diluted_apy

ENGINE = "marginal_apy_ladder"

#: Слой советательный: ни одно число отсюда не гейтит исполнение (инв. #9).
IS_ADVISORY = True

# ---------------------------------------------------------------------------
# ОБЪЯВЛЕННЫЕ константы. Каждая — выбор, и у каждой названа причина.
# ---------------------------------------------------------------------------

#: Ступени лестницы, ДОСЛОВНО из §12 ТЗ владельца. Литералы владельца, не наши:
#: менять их значило бы отвечать на свой вопрос вместо заданного.
RUNGS_USD: Tuple[float, ...] = (5_000.0, 10_000.0, 20_000.0, 40_000.0)

#: Порог старости источника оси. 48 ч — двойной такт дневного цикла, тот же
#: операнд, что у соседа §10/§11 (`apy_expectation.BLIND_SOURCE_MAX_AGE_H`).
SOURCE_MAX_AGE_H = 48.0

#: Ключи, под которыми запись лога называет СВОЙ ПРЕДМЕТ. Перечень замкнут:
#: запись без предмета — отдельное состояние (`no_subject`), а не «предмет не
#: нашёлся». Вложенный `positions[]` разбирается отдельно (так устроен
#: `exit_liquidity_log.json`).
SUBJECT_KEYS: Tuple[str, ...] = (
    "protocol", "protocol_name", "adapter_id", "adapter", "name", "key",
    "vault", "vault_name", "token", "market", "pool", "pool_name",
)

#: Состояния оси, от худшего к лучшему. Порядок ЗНАЧИМ: у оси с несколькими
#: источниками состоянием становится ЛУЧШЕЕ, и ранг решает, какое лучше.
AXIS_STATES: Tuple[str, ...] = (
    "no_source",        # источника оси не названо вовсе — такого файла нет
    "absent",           # названный файл не существует
    "unparsed",         # файл есть и НЕ РАЗОБРАН
    "empty",            # файл есть и ПУСТ (ADR-940: пустота ответом не является)
    "no_subject",       # записи есть, предмета записи не названо ни одним ключом
    "fixture_subject",  # записи есть, предметы ВЫДУМАНЫ: пересечение с нашими ПУСТО
    "stale",            # предметы наши, но записи старше своего срока
    "no_consumer",      # привязано и свежо, а формула этого числа НЕ ЧИТАЕТ
    "credited",         # привязано, свежо и ЧИТАЕТСЯ
)

#: Состояния, при которых ось считается УЧТЁННОЙ формулой.
CREDITED_STATES: Tuple[str, ...] = ("credited",)


def _axis(axis: str, owner_words: str, sources: Sequence[str],
          consumer: Optional[str], why: str,
          not_a_source: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    return {"axis": axis, "owner_words": owner_words,
            "sources": tuple(sources), "consumer": consumer, "why": why,
            "not_a_source": tuple(not_a_source)}


#: СЕМЬ осей §12 — дословно перечень владельца, в его порядке.
#:
#: `sources` — файлы `data/`, которые НЕСЛИ БЫ предмет оси (пустой кортеж =
#: такого файла нет вовсе). `consumer` — имя места в лестнице, которое число оси
#: читает; `None` = не читает никто, и тогда ось не получает кредита даже при
#: живых данных (урок `blind_no_consumer` ADR-954: иначе в день наполнения файла
#: вилка сузилась бы БЕЗ новой информации).
#:
#: `not_a_source` — сосед, которого НЕЛЬЗЯ подставить вместо источника, и
#: причина. Поле существует затем, что подстановка похожего числа — самая дешёвая
#: форма вранья: `borrowing_power_utilization_log.json` называет наши протоколы и
#: свеж, но его предмет — LTV ЗАЁМЩИКА, а не загрузка ПУЛА.
AXES: Tuple[Dict[str, Any], ...] = (
    _axis(
        "tvl_dilution", "TVL dilution",
        ("tvl_yield_elasticity_log.json",),
        None,
        "ряда «ставка против TVL» по НАШИМ протоколам не пишет никто: снимок TVL "
        "есть у каждого адаптера, а поведение базовой ставки при притоке "
        "капитала не наблюдено ни разу — поэтому база в лестнице держится "
        "постоянной (верхняя граница) и разбавляется полностью (нижняя), а "
        "середина объявлена МОДЕЛЬЮ MP-911, а не замером",
    ),
    _axis(
        "utilization", "utilization",
        ("vault_utilization_peak_headline_revert_log.json",),
        None,
        "фида загрузки ПУЛА в data/ нет: единственный названный файл существует "
        "и ПУСТ с 20.06",
        not_a_source=(
            ("borrowing_power_utilization_log.json",
             "предмет — LTV ЗАЁМЩИКА, а не загрузка пула; файл называет наши "
             "протоколы и потому особенно соблазнителен к подстановке"),
        ),
    ),
    _axis(
        "reward_dilution", "reward dilution",
        ("adapter_status.json",),
        "ladder.apy_upper_pct (наградная часть делится на больший TVL)",
        "ЕДИНСТВЕННАЯ измеримая ось семёрки: `apy_reward` и живой `tvl_usd` "
        "записаны по каждому протоколу, и разбавление фиксированной эмиссии "
        "большим знаменателем есть ОПРЕДЕЛЕНИЕ, а не модель",
        not_a_source=(
            ("reward_dilution_velocity_log.json",
             "100 записей, предмет `TestProtocol` — ни одной нашей возможности"),
            ("liquidity_mining_dilution_log.json",
             "100 записей, предмет `TestProtocol` — ни одной нашей возможности"),
        ),
    ),
    _axis(
        "capacity", "capacity",
        ("vault_capacity_dilution_log.json",),
        None,
        "ёмкости протокола не записано нигде: названный файл существует и ПУСТ",
        not_a_source=(
            ("adapter_status.json:per_protocol_cap",
             "это потолок НАШЕЙ политики концентрации (RiskPolicy), а не "
             "ёмкость протокола; подставить его значило бы назвать своё "
             "ограничение чужим свойством"),
        ),
    ),
    _axis(
        "deposit_caps", "deposit caps",
        ("deposit_cap_headroom_log.json",),
        None,
        "потолка вклада по нашим протоколам не записано: в файле одна запись от "
        "14.06 о выдуманных хранилищах",
    ),
    _axis(
        "liquidity", "liquidity",
        ("exit_liquidity_log.json", "slippage_impact_log.json"),
        None,
        "единственная ось семёрки, у которой ЕСТЬ свежий живой писатель, "
        "называющий наши протоколы по имени — но мерит он ОДИН фиксированный "
        "размер $25k, а не лестницу §12, и лестница его не читает",
    ),
    _axis(
        "withdrawal_depth", "withdrawal depth",
        ("staking_withdrawal_queue_log.json",
         "vault_depositor_exit_velocity_log.json",
         "vault_instant_exit_nav_discount_log.json"),
        None,
        "глубины выхода по нашим протоколам не записано: два файла ПУСТЫ, в "
        "третьем предмет назван `unknown` при позиции $0",
    ),
)


def validate() -> List[str]:
    """Паритет ОБЪЯВЛЕНИЯ с собственным контрактом. Пустой список = в порядке.

    Проверяется объявление, а не чьи-то числа: мерка обязана выдерживать свою же
    мерку, иначе сторож сверяет свои константы САМ С СОБОЙ (урок ADR-913/940).
    """
    problems: List[str] = []
    if not RUNGS_USD:
        problems.append("лестница пуста — §12 называет четыре ступени")
    if list(RUNGS_USD) != sorted(RUNGS_USD):
        problems.append("ступени лестницы не возрастают")
    if len(set(RUNGS_USD)) != len(RUNGS_USD):
        problems.append("ступени лестницы повторяются")
    for r in RUNGS_USD:
        if not r > 0:
            problems.append(f"ступень {r!r} не положительна — «добавить $0» "
                            "вопросом §12 не является")
    if not SOURCE_MAX_AGE_H > 0:
        problems.append("SOURCE_MAX_AGE_H не положителен")
    for st in CREDITED_STATES:
        if st not in AXIS_STATES:
            problems.append(f"состояние {st!r} объявлено кредитным, "
                            "а в AXIS_STATES его нет")
    seen = set()
    for ax in AXES:
        a = ax["axis"]
        if not a:
            problems.append("ось §12 без имени объявлением не является")
            continue
        if a in seen:
            problems.append(f"ось {a!r} объявлена дважды")
        seen.add(a)
        if not (ax["owner_words"] or "").strip():
            problems.append(f"{a}: не названа формулировка владельца из §12")
        if not (ax["why"] or "").strip():
            problems.append(f"{a}: причина состояния не названа словами")
        for name, reason in ax["not_a_source"]:
            if not (reason or "").strip():
                problems.append(f"{a}: сосед {name!r} объявлен непригодным "
                                "без причины — запрет без причины запретом "
                                "не является")
            if name in ax["sources"]:
                problems.append(f"{a}: {name!r} назван и источником, и "
                                "непригодным соседом разом")
    if len(seen) != 7:
        problems.append(f"осей объявлено {len(seen)}, а §12 называет семь — "
                        "перепись отвечала бы не на вопрос владельца")
    return problems


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    """float или None; bool и NaN/inf числами не считаются."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _load(path: Path) -> Tuple[Any, str]:
    """(документ, причина-отказа). Отсутствие и нечитаемость РАЗЛИЧИМЫ."""
    if not path.exists():
        return None, f"{path.name}: файла нет"
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return None, f"{path.name}: не разобран ({type(exc).__name__}: {exc})"


def _age_h(path: Path, now: datetime) -> Optional[float]:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except BaseException:  # noqa: BLE001
        return None
    return (now - ts).total_seconds() / 3600.0


def _norm(s: Any) -> Optional[str]:
    """Имя предмета к сравнимой форме: регистр и пробелы значения не несут."""
    if not isinstance(s, str):
        return None
    t = s.strip().lower().replace(" ", "_").replace("-", "_")
    return t or None


def opportunity_names(adapters: Dict[str, Any]) -> set:
    """Имена НАШИХ возможностей, по которым привязывается запись лога.

    Берутся и ключ реестра, и `display_name`: один и тот же протокол соседние
    писатели называют `aave_v3` и `Aave V3`, и считать второе чужим предметом
    значило бы выдумать находку.
    """
    names = set()
    for aid, a in (adapters or {}).items():
        n = _norm(aid)
        if n:
            names.add(n)
        if isinstance(a, dict):
            n = _norm(a.get("display_name"))
            if n:
                names.add(n)
    return names


def record_subjects(doc: Any) -> Tuple[set, int]:
    """(имена предметов записей, число записей). Вложенный `positions[]` тоже.

    Пустое множество при НЕНУЛЕВОМ числе записей и есть состояние
    `no_subject`: записи существуют, а о чём они — не сказано.
    """
    subjects: set = set()
    count = 0

    def walk(node: Any, depth: int = 0) -> None:
        nonlocal count
        if depth > 6:
            return
        if isinstance(node, dict):
            for k in SUBJECT_KEYS:
                n = _norm(node.get(k))
                if n:
                    subjects.add(n)
            for k, v in node.items():
                if isinstance(v, dict):
                    # Предмет бывает КЛЮЧОМ отображения, а не значением поля:
                    # так устроен `adapter_status.json` (`adapters: {id: {...}}`).
                    # Пропусти этот случай — и ЕДИНСТВЕННАЯ измеримая ось §12
                    # получила бы `no_subject` при живых привязанных данных,
                    # то есть замер соврал бы в сторону слепоты.
                    n = _norm(k)
                    if n:
                        subjects.add(n)
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                if depth == 0:
                    count += 1
                walk(item, depth + 1)

    if isinstance(doc, list):
        walk(doc)
    elif isinstance(doc, dict):
        count = 1
        walk(doc)
    return subjects, count


def _source_state(data_dir: Path, source: str, ours: set, consumer: Optional[str],
                  now: datetime) -> Dict[str, Any]:
    """Состояние ОДНОГО источника оси. Девять исходов, и ни один не молчит."""
    rec: Dict[str, Any] = {"source": source}
    path = data_dir / source.split(":", 1)[0]
    doc, why = _load(path)
    if why and not path.exists():
        rec.update(state="absent", detail=why)
        return rec
    if why:
        rec.update(state="unparsed", detail=why)
        return rec
    subjects, count = record_subjects(doc)
    rec["records"] = count
    if isinstance(doc, (list, dict)) and len(doc) == 0:
        rec.update(state="empty",
                   detail=f"{source}: файл есть и ПУСТ — прочитанная пустота "
                          "ответом об оси не является")
        return rec
    rec["subjects_total"] = len(subjects)
    if not subjects:
        rec.update(state="no_subject",
                   detail=f"{source}: записей {count}, а предмета записи не "
                          "назвал ни один объявленный ключ — привязать число "
                          "к возможности нечем")
        return rec
    bound = sorted(subjects & ours)
    rec["bound_subjects"] = bound
    if not bound:
        rec.update(state="fixture_subject",
                   detail=f"{source}: записей {count}, предметов "
                          f"{len(subjects)}, и НИ ОДИН не наша возможность "
                          f"(например {sorted(subjects)[:3]}) — файл не пуст и "
                          "по длине неотличим от живого наблюдения")
        return rec
    age = _age_h(path, now)
    rec["age_h"] = None if age is None else round(age, 2)
    if age is None:
        rec.update(state="unparsed", detail=f"{source}: возраст не измерен")
        return rec
    if age > SOURCE_MAX_AGE_H:
        rec.update(state="stale",
                   detail=f"{source}: предметы наши ({len(bound)}), но записям "
                          f"{age:.1f} ч при пределе {SOURCE_MAX_AGE_H:.0f} ч")
        return rec
    if consumer is None:
        rec.update(state="no_consumer",
                   detail=f"{source}: привязано ({len(bound)} предметов) и "
                          "свежо, а лестница этого числа НЕ ЧИТАЕТ — кредит за "
                          "появление данных не выдаётся")
        return rec
    rec.update(state="credited",
               detail=f"{source}: привязано ({len(bound)}), свежо и читается "
                      f"({consumer})")
    return rec


def axes_state(data_dir: Path, adapters: Dict[str, Any],
               now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Состояние каждой из семи осей §12. `now` — ВХОД, а не стенные часы.

    Срок меряется относительно переданного момента намеренно
    (`.claude/rules/deployment.md` § «Время в тестах»): иначе проверка свежести
    стала бы будильником, краснеющим от сдвига календаря.
    """
    now = now or datetime.now(timezone.utc)
    ours = opportunity_names(adapters)
    out: List[Dict[str, Any]] = []
    for ax in AXES:
        rec: Dict[str, Any] = {
            "axis": ax["axis"], "owner_words": ax["owner_words"],
            "consumer": ax["consumer"], "why": ax["why"],
            "not_a_source": [{"source": n, "reason": r}
                             for n, r in ax["not_a_source"]],
        }
        if not ax["sources"]:
            rec["state"] = "no_source"
            rec["detail"] = "файла с предметом этой оси в data/ не существует"
            rec["source_states"] = []
            out.append(rec)
            continue
        states = [_source_state(data_dir, s, ours, ax["consumer"], now)
                  for s in ax["sources"]]
        rec["source_states"] = states
        best = max(states, key=lambda s: AXIS_STATES.index(s["state"]))
        rec["state"] = best["state"]
        rec["detail"] = best["detail"]
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# §12 — лестница
# ---------------------------------------------------------------------------

def ladder_rung(base_pct: float, reward_pct: float, tvl_usd: float,
                amount_usd: float) -> Dict[str, Any]:
    """Три числа РАЗНОГО РОДА для одной ступени. Модель MP-911 переиспользована.

    `apy_upper_pct` — факт (разбавлена только наградная часть);
    `apy_modelled_pct` — допущение MP-911 (`√`-эластичность базы);
    `apy_lower_pct` — база разбавлена полностью (граница снизу).
    """
    factor = _dilution_factor(tvl_usd, amount_usd)
    upper = base_pct + reward_pct * factor
    modelled = _diluted_apy(reward_pct, base_pct, tvl_usd, amount_usd)
    lower = (base_pct + reward_pct) * factor
    return {
        "amount_usd": round(amount_usd, 2),
        "dilution_factor": round(factor, 8),
        "share_of_pool_pct": round(amount_usd / (tvl_usd + amount_usd) * 100.0, 6),
        "apy_upper_pct": round(upper, 4),
        "apy_modelled_pct": round(modelled, 4),
        "apy_lower_pct": round(lower, 4),
        "apy_bracket_width_pp": round(upper - lower, 4),
    }


def _live_tvl(a: Dict[str, Any]) -> Tuple[Optional[float], str]:
    """TVL только ЖИВОЙ. Константа с меткой `live` — дефект ADR-053, не вход."""
    src = a.get("tvl_source")
    tvl = _num(a.get("tvl_usd"))
    if src != "live":
        return None, (f"TVL не живой (`tvl_source`={src!r}) — знаменатель "
                      "разбавления на константе есть ровно запрет ADR-053")
    if tvl is None or tvl <= 0:
        return None, f"живой TVL не положителен ({a.get('tvl_usd')!r})"
    return tvl, ""


def opportunity_ladder(a: Dict[str, Any]) -> Dict[str, Any]:
    """Лестница §12 для ОДНОЙ возможности, либо отказ с названной причиной."""
    rec: Dict[str, Any] = {}
    comp = a.get("apy_composition_unmeasured")
    if isinstance(comp, str) and comp.strip():
        rec["unmeasured"] = (f"состав ставки НЕ ИЗМЕРЕН ({comp}) — принять всю "
                             "ставку базовой значило бы утверждать, что "
                             "разбавлять нечего, то есть напечатать нулевое "
                             "влияние своего размера")
        return rec
    base = _num(a.get("apy_base"))
    reward = _num(a.get("apy_reward"))
    if base is None:
        rec["unmeasured"] = "базовой ставки (`apy_base`) у протокола не записано"
        return rec
    if reward is None:
        rec["unmeasured"] = "ставки стимулов (`apy_reward`) у протокола не записано"
        return rec
    tvl, why = _live_tvl(a)
    if tvl is None:
        rec["unmeasured"] = why
        return rec
    rec["tvl_usd"] = tvl
    rec["rungs"] = [ladder_rung(base, reward, tvl, amt) for amt in RUNGS_USD]
    return rec


def measure(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Секция цикла: перепись семи осей §12 + лестница по измеримым осям."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    rep: Dict[str, Any] = {
        "status": "OK",
        "engine": ENGINE,
        "is_advisory": IS_ADVISORY,
        "question": ("§12: «если vault показывает 8 % APY, это не означает, что "
                     "$40k можно разместить под 8 %»"),
        "declared": {
            "rungs_usd": list(RUNGS_USD),
            "source_max_age_h": SOURCE_MAX_AGE_H,
            "axes_declared": len(AXES),
            "dilution_model": ("spa_core.analytics.yield_dilution_analyzer."
                               "_diluted_apy (MP-911, переиспользован)"),
        },
    }

    broken = validate()
    if broken:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["объявление осей не выдерживает своего контракта: "
                             + "; ".join(broken)]
        rep["reason"] = rep["unmeasured"][0]
        return rep

    status_doc, why_status = _load(data_dir / "adapter_status.json")
    if why_status or not isinstance(status_doc, dict):
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = [why_status or "adapter_status.json не является записью"]
        rep["reason"] = rep["unmeasured"][0]
        return rep
    adapters = status_doc.get("adapters")
    if not isinstance(adapters, dict) or not adapters:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["в adapter_status.json нет перечня `adapters` — "
                             "ноль возможностей и непрочитанный вход неразличимы"]
        rep["reason"] = rep["unmeasured"][0]
        return rep

    axes = axes_state(data_dir, adapters, now=now)
    rep["axes"] = axes
    credited = [a for a in axes if a["state"] in CREDITED_STATES]
    rep["axes_credited"] = len(credited)
    rep["axes_blind"] = len(axes) - len(credited)
    rep["axes_credited_names"] = [a["axis"] for a in credited]
    rep["axes_blind_names"] = [a["axis"] for a in axes
                               if a["state"] not in CREDITED_STATES]
    fixture = [a["axis"] for a in axes if a["state"] == "fixture_subject"]
    rep["axes_with_fixture_subject"] = fixture

    rows: List[Dict[str, Any]] = []
    for aid in sorted(adapters):
        a = adapters[aid]
        if not isinstance(a, dict):
            continue
        displayed = _num(a.get("live_apy"))
        if displayed is None:
            displayed = _num(a.get("apy"))
        row: Dict[str, Any] = {
            "adapter_id": aid,
            "tier": a.get("tier"),
            "displayed_apy_pct": displayed,
            "base_apy_pct": _num(a.get("apy_base")),
            "incentive_apy_pct": _num(a.get("apy_reward")),
        }
        row.update(opportunity_ladder(a))
        if row.get("rungs"):
            top = row["rungs"][-1]
            row["top_rung_usd"] = top["amount_usd"]
            if displayed is not None:
                row["top_rung_drop_pp_upper"] = round(
                    displayed - top["apy_upper_pct"], 4)
                row["top_rung_drop_pp_lower"] = round(
                    displayed - top["apy_lower_pct"], 4)
            row["top_rung_bracket_width_pp"] = top["apy_bracket_width_pp"]
        rows.append(row)

    rep["opportunities"] = rows
    measured = [r for r in rows if r.get("rungs")]
    rep["counts"] = {
        "opportunities": len(rows),
        "ladder_measured": len(measured),
        "ladder_unmeasured": len(rows) - len(measured),
        "axes_declared": len(axes),
        "axes_credited": len(credited),
        "axes_blind": len(axes) - len(credited),
        "axes_with_fixture_subject": len(fixture),
    }
    if measured:
        widths = [r["top_rung_bracket_width_pp"] for r in measured]
        rep["top_rung_bracket_width_pp_min"] = round(min(widths), 4)
        rep["top_rung_bracket_width_pp_max"] = round(max(widths), 4)
        drops = [r["top_rung_drop_pp_lower"] for r in measured
                 if r.get("top_rung_drop_pp_lower") is not None]
        if drops:
            rep["top_rung_drop_pp_lower_max"] = round(max(drops), 4)
            worst = max((r for r in measured
                         if r.get("top_rung_drop_pp_lower") is not None),
                        key=lambda r: r["top_rung_drop_pp_lower"])
            rep["top_rung_worst_adapter"] = worst["adapter_id"]
    else:
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["ни одной лестницы не измерено — причины названы "
                             "у каждой возможности поимённо"]
    return rep


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print(rep: Dict[str, Any]) -> int:
    print(f"MARGINAL APY AT SIZE (§12) — {rep.get('status')}"
          f"{'  [ADVISORY]' if rep.get('is_advisory') else ''}")
    if rep.get("verdict") == "UNMEASURED" and not rep.get("opportunities"):
        for u in rep.get("unmeasured") or []:
            print(f"  НЕ ИЗМЕРЕНО: {u}")
        return 2
    c = rep.get("counts") or {}
    print(f"  осей §12 объявлено {c.get('axes_declared')} · УЧТЕНО "
          f"{c.get('axes_credited')} · слепых {c.get('axes_blind')} · из них "
          f"предмет ВЫДУМАН у {c.get('axes_with_fixture_subject')}")
    for a in rep.get("axes") or []:
        print(f"     [{a['state']}] {a['axis']} ({a['owner_words']}): {a['detail']}")
        for ns in a.get("not_a_source") or []:
            print(f"         ✗ НЕ источник: {ns['source']} — {ns['reason']}")
    print(f"  возможностей {c.get('opportunities')} · лестница измерена "
          f"{c.get('ladder_measured')} / НЕ ИЗМЕРЕНА {c.get('ladder_unmeasured')}")
    if rep.get("top_rung_drop_pp_lower_max") is not None:
        print(f"  на верхней ступени (${int(RUNGS_USD[-1]):,}) худшее падение "
              f"ставки {rep['top_rung_drop_pp_lower_max']} пп "
              f"({rep.get('top_rung_worst_adapter')}); ширина вилки "
              f"{rep.get('top_rung_bracket_width_pp_min')}…"
              f"{rep.get('top_rung_bracket_width_pp_max')} пп")
    for r in rep.get("opportunities") or []:
        if not r.get("rungs"):
            continue
        print(f"     {r['adapter_id']:<22} напечатано "
              f"{(r['displayed_apy_pct'] if r['displayed_apy_pct'] is not None else float('nan')):>7.4f} % → "
              + " · ".join(f"+${int(g['amount_usd'] / 1000)}k: "
                           f"{g['apy_lower_pct']:.4f}…{g['apy_upper_pct']:.4f} %"
                           for g in r["rungs"]))
    n_un = c.get("ladder_unmeasured") or 0
    if n_un:
        print(f"  НЕ ИЗМЕРЕНО у {n_un} возможностей — причины:")
        shown = set()
        for r in rep.get("opportunities") or []:
            why = r.get("unmeasured")
            if why and why[:40] not in shown:
                shown.add(why[:40])
                print(f"     · {why}")
    return 0 if c.get("ladder_measured") else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default="data",
                    help="каталог состояния (живой трек — у ПРОД-дерева)")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    rep = measure(Path(ns.data_dir))
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if (rep.get("counts") or {}).get("ladder_measured") else (
            2 if rep.get("status") == "SKIPPED" else 1)
    return _print(rep)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
