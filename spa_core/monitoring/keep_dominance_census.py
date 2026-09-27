#!/usr/bin/env python3
"""Побеждает ли DO NOTHING ту раскладку, которую система называет оптимальной.

Критерий §49 `Economics` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #702.

Дословно критерий звучит так: **«Решения используют net expected return, а не
raw APY»**, а §1 приказа отдельно требует: «Решение DO NOTHING / KEEP является
полноценным инвестиционным решением и не должно считаться отсутствием работы».
До этого прибора критерий был ПРОЗОЙ: издержки в коде НАЗЫВАЛИСЬ
(`allocator/rebalance_economics.py` считает `cost_usd`, `cost_pp`,
`payback_days`), а ИСХОД — побеждает ли опубликованный оптимум решение ничего
не делать — не мерил никто. «Модуль есть, тесты зелёные» ≠ «работает»
(`.claude/rules/acceptance.md`).

Что прибор меряет
------------------------------------------------------------------------------
Одну вещь: **доминирование KEEP**. Запись журнала вердиктов несёт СВОЮ
доходность книги (`book_apy_pp`) и доходность цели, которую тот же документ
зовёт оптимальной (`target_apy_pp`, в артефакте — `apy_opt_pp`). Если вторая
МЕНЬШЕ первой, то предъявленный оптимум проигрывает решению ничего не делать —
причём ДО учёта издержек, которые могут только ухудшить его.

Почему этот знак и есть ответ на вопрос владельца
------------------------------------------------------------------------------
Решение ничего не делать доступно ВСЕГДА и стоит $0. Поэтому оптимизатор,
который ранжирует варианты по ожидаемой чистой доходности и держит KEEP в
допустимом множестве, отрицательного `gain_pp` выдать НЕ МОЖЕТ: KEEP
доминировал бы и был бы выбран. Отрицательный `gain_pp` в журнале — это
наблюдаемое доказательство, что KEEP не оценивается вовсе: цель строит
аллокатор (по наблюдённым ставкам), а издержки входят ПОЗЖЕ и только как ВЕТО
(`evaluate(current, target, …)` цель получает готовой и не выбирает её).

То есть система отвечает на два вопроса владельца разными мерками: «как должна
выглядеть оптимальная раскладка» — по сырой ставке, «оправдан ли переход» — по
чистой. Критерий §49 требует первого тоже.

Порода находки: две, и прибор их НЕ смешивает
------------------------------------------------------------------------------
* ``dominated_by_keep`` — `gain_pp < 0`: оптимум проигрывает KEEP по СВОЕЙ же
  мерке, до издержек. Это вопрос ПРЕДМЕТА ранжирования;
* ``net_negative_missed_by_gate`` — `gain_pp ≥ 0`, за горизонт окупаемости
  владельца (`max_payback_days`) прирост не отбивает `cost_usd`, **и при этом
  собственный гейт записи `payback_within_horizon` сказал `True`**. Это находка
  только в таком виде: «чистый исход отрицателен, и гейт его ПОЙМАЛ» — не
  находка, а гейт за работой, и выдавать её за находку значило бы топить
  настоящую в шуме. Замер 27.09: поймано 35, ПРОПУЩЕНО 0, гейта нет вовсе у 28
  записей старой схемы `shadow-hist-v1` (третий исход `net_gate_unchecked`, не
  «ноль пропусков»).

Причину отрицательного знака прибор РАЗЛАГАЕТ, а не угадывает
------------------------------------------------------------------------------
Разложение точное (сумма равна `gain_pp`, и это проверяется):

* **смесь** (`mix_pp`) — те же деньги в протоколах с другой ставкой;
* **размер** (`size_pp`) — сколько денег вообще развёрнуто; недоразвёрнутый
  доллар лежит в кэше под 0 %, и знаменатель ставки — ВЕСЬ капитал.

Замер, ради которого прибор написан (книга `conservative`, 69 записей): у ВСЕХ
шести отрицательных записей смесь УЛУЧШАЛАСЬ (+0,02…+0,39 пп), а цель при этом
выводила из оборота $10 789…$20 263 в кэш под 0 % (−0,45…−1,09 пп), и второе
съедало первое. То есть оптимум проигрывал KEEP не из-за плохого выбора
протоколов, а потому что деньги ПЕРЕСТАВАЛИ работать, и цену этого никто не
вычитал.

Своих чисел прибор не имеет ни одного
------------------------------------------------------------------------------
Существенность (`min_leg_frac`), горизонт окупаемости (`max_payback_days`) и
полоса прироста (`min_gain_pp`) берутся из `TriggerParams.for_mode()` — той же
колонки ADR-060 §3, которой судит живой путь. §22 приказа требует дословно:
«Все значения должны быть config/policy. Не hardcode». **Колонка недоступна ⇒
третий исход**, а не подставленное умолчание: своя копия порога отвечала бы на
свой вопрос, а не на нужный.

Существенность применяется к ПРИЧИНЕ, а не к пунктам
------------------------------------------------------------------------------
Отрицательный знак бывает и от дрейфа на копейки: у книг `balanced` и
`aggressive` по 12 таких записей, и там цель недоразвёрнута на $11…$36 при
капитале $100 000 — это начисленный процент, а не решение. Поэтому порода
находки объявляется материальной только когда ДОЛЛАРЫ, её породившие
(выведенные из оборота либо переложенные), не ниже пыли владельца
`min_leg_frac × capital`. Прибор не судит, «много ли» 0,41 пп, — он судит,
выше ли пыли те деньги, которые эти 0,41 пп сделали.

Второй производитель, а не пересказ записи
------------------------------------------------------------------------------
Все три числа (`book_apy_pp`, `target_apy_pp`, `gain_pp`) прибор ВЫЧИСЛЯЕТ сам
из `current_positions`, `target_positions`, `apy_evidenced_pct` и
`capital_usd`, и сверяет с записанными. Расхождение — не повод доверять
записи: такая запись выпадает в третий исход `recomputation_mismatch` С
НАЗВАННОЙ причиной и в вердикт не идёт. Пересказ чужого числа не был бы
измерением (замер 27.09: расхождений 0 из 69 — журнал внутренне согласован, и
это ЗАМЕР, а не предположение).

Побочно: объяснение простоя кэша отвечает про ДРУГУЮ книгу
------------------------------------------------------------------------------
ADR-055 требует объяснять кэш сверх буфера каждый цикл, и объяснение
печатается в том же документе (`allocation_rationale.json` → `cash`). Но
считается оно по `current_positions` — по книге, которую держим. Цель,
опубликованную в ТОМ ЖЕ документе, оно не видит: 26.09 секция сообщала
`excess_pct: 0.0, status: explained` рядом с целью, оставляющей в кэше 15,8 %
капитала. Прибор называет это отдельным полем
(`cash_explanation_silent_on_target_idle`), а не вердиктом: это наблюдение об
ОСИ объяснения. Документ недоступен ⇒ поле `unchecked`, а не `False`.

Почему вердикт судит НАСТОЯЩЕЕ, а история остаётся замером
------------------------------------------------------------------------------
История не меняется: оптимум, проигравший KEEP 15.09, проиграл навсегда.
Сторож, чей вердикт считает всю историю, КРАСЕН НАВСЕГДА и позеленеть не может
ни от какой починки — а такой сторож учит себя игнорировать. Поэтому:

* **замер** — все записи всех книг, с породой и ценой каждой находки;
* **вердикт** — только САМАЯ СВЕЖАЯ дата каждого журнала: ``CRITICAL``, если
  материальная находка есть на ней; ``WARNING``, если на свежей дате чисто, но
  в истории находки есть; ``OK``, если не было ни одной.

Чего прибор НЕ утверждает
------------------------------------------------------------------------------
* **Что деньги двинулись.** Все 69 вердиктов журнала — `HOLD`; полосу прироста
  отрицательный знак не проходит, и капитал не пострадал. Предмет находки —
  чем ранжируется оптимум, а не что уже потеряно.
* **Что недоразвёртывание НЕВЕРНО.** Потолки концентрации и отказы по TVL —
  настоящие ограничения, и кэш иногда единственный допустимый ответ. Прибор
  говорит лишь, что такую цель нельзя звать оптимальной, не сравнив её с KEEP.
* **Что виноват аллокатор.** Цель строит он, вето ставят демпфер и CIO; кто
  именно обязан оценивать KEEP — решение владельца, а не вывод прибора.

Прибор ТОЛЬКО ЧИТАЕТ: журналы вердиктов, документ советника, пороги и часы. Ни
`TriggerParams`, ни пороги RiskPolicy v1.0, ни стоп-кран, ни живой трек, ни
аллокатор он не трогает и ничего не чинит. **LLM запрещён** (инвариант #3 —
monitoring-путь).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.observation import observed

#: Артефакт прибора — его читает шаг 0-офис.
ARTIFACT_NAME = "keep_dominance_census.json"

#: Документ советника за текущий цикл — источник побочного наблюдения про кэш.
#: Имя берётся у писателя (`allocation_rationale.RATIONALE_FILENAME`), второй
#: копии здесь нет; недоступность писателя — третий исход поля, не False.
RATIONALE_DOC_FALLBACK = "allocation_rationale.json"

#: Шаблон журналов вердиктов. Разбор имени сверяется с ПРАВИЛОМ писателя
#: (`allocation_rationale.history_filename`) в обе стороны — см. `discover_books`.
JOURNAL_GLOB = "allocation_rationale_history*.jsonl"

#: Предмет прибора — один текст на обе ветки, чтобы измеренный и неизмеренный
#: артефакты называли ОДНО И ТО ЖЕ, а не две редакции одной фразы.
CRITERION = ("§49 Economics — «Решения используют net expected return, а не raw "
             "APY» (+ §1: DO NOTHING есть полноценное решение)")

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Код возврата третьего исхода. Ноль здесь был бы «чисто», которого никто не мерил.
EXIT_UNMEASURED = 3

#: Разложение считается сошедшимся с точностью до этой доли пп. Не порог решения,
#: а допуск арифметики с плавающей точкой: расхождение выше означает, что
#: разложение НЕВЕРНО, и запись уходит в третий исход.
_DECOMP_EPS_PP = 1e-6

#: Тот же смысл для сверки со записанными числами: журнал округляет до 6 знаков.
_RECOMPUTE_EPS_PP = 1e-4

#: Породы, считающиеся НАХОДКОЙ. «Гейт поймал» и «гейта нет» находками не
#: являются: первое — гейт за работой, второе — честный третий исход. Смешать их
#: с находкой значило бы утопить настоящую в шуме (замер 27.09: 6 против 35+28).
_FINDING_KINDS = ("dominated_by_keep", "net_negative_missed_by_gate")

#: Дней в году. Астрономическая константа, а не порог решения: горизонт в днях
#: приходит из колонки владельца, и перевод годовой ставки в доллары за горизонт
#: обязан чем-то делить.
_DAYS_YEAR = 365.0


def _num(value: object) -> Optional[float]:
    """Конечное число либо ``None``. ``bool`` числом не считается («True» — не $1).

    Отдельно от «0.0 по умолчанию»: отсутствие наблюдения обязано быть отличимо
    от наблюдённого нуля (инвариант #17).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if f != f or abs(f) == float("inf"):
        return None
    return f


def _positions(raw: object) -> Optional[Dict[str, float]]:
    """Карта «протокол → доллары». Не-словарь или нечисловая сумма ⇒ ``None``."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, float] = {}
    for key, value in raw.items():
        num = _num(value)
        if num is None:
            return None
        out[str(key)] = num
    return out


# ── пороги: колонка владельца, а не наши числа ───────────────────────────────

def load_policy(params: Any = None) -> Dict[str, Any]:
    """Пыль, горизонт окупаемости и полоса прироста из ``TriggerParams.for_mode()``.

    Колонка недоступна ⇒ ``measured=False``. Подставить сюда умолчание значило
    бы завести ещё одну копию чисел ADR-060 §3 и ответить на свой вопрос вместо
    нужного (урок `pyflakes`: отсутствие инструмента — третий исход).
    """
    if params is None:
        try:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        except Exception as exc:  # noqa: BLE001 — назвать причину, не подставить число
            return {"measured": False,
                    "reason": (f"колонка порогов ADR-060 §3 недоступна "
                               f"({type(exc).__name__}: {exc}) — пыль, горизонт "
                               f"окупаемости и полоса прироста НЕ ИЗМЕРЕНЫ, подставлять "
                               f"свои нельзя (§22: «Все значения должны быть "
                               f"config/policy. Не hardcode»)")}
    try:
        min_leg_frac = float(params.min_leg_frac)
        max_payback_days = float(params.max_payback_days)
        min_gain_pp = float(params.min_gain_pp)
        mode = str(getattr(params, "mode", "unknown"))
        version = str(getattr(params, "version", "unknown"))
    except (AttributeError, TypeError, ValueError) as exc:
        return {"measured": False,
                "reason": (f"колонка порогов не несёт нужных полей "
                           f"({type(exc).__name__}: {exc}) — НЕ ИЗМЕРЕНО")}
    return {"measured": True, "min_leg_frac": min_leg_frac,
            "max_payback_days": max_payback_days, "min_gain_pp": min_gain_pp,
            "mode": mode, "version": version}


# ── журналы вердиктов: имя разбирается ПРАВИЛОМ ПИСАТЕЛЯ ─────────────────────

def _writer_history_filename(book_id: Optional[str]) -> Optional[str]:
    """Имя журнала по правилу ПИСАТЕЛЯ. Писатель недоступен ⇒ ``None``.

    Второй копии правила «как зовётся журнал книги» здесь нет намеренно: именно
    так расходились имена в этом проекте. Недоступность писателя — третий исход,
    а не своя догадка о суффиксе.
    """
    try:
        from spa_core.paper_trading.allocation_rationale import history_filename
        return str(history_filename(book_id))
    except Exception:  # noqa: BLE001 — причину назовёт вызывающий
        return None


def discover_books(data_dir: Path) -> Dict[str, Any]:
    """Какие книги ведут журнал вердиктов — обходом каталога, не списком в коде.

    Список книг в коде был бы вторым местом для знания, которое уже есть у
    писателя. Поэтому: найти файлы по шаблону, вывести `book_id` обратным
    разбором имени и ПРОВЕРИТЬ круговым ходом — `history_filename(book_id)`
    обязан дать то же имя. Не дал ⇒ файл объявляется `unroutable` с названной
    причиной и в население не входит (молча пропустить журнал денег нельзя).
    """
    default_name = _writer_history_filename(None)
    if default_name is None:
        return {"measured": False,
                "reason": ("правило имён журналов недоступно (писатель "
                           "`allocation_rationale` не импортируется) — свою копию "
                           "суффикса заводить нельзя, это НЕ ИЗМЕРЕНО")}
    prefix = default_name[:-len(".jsonl")] + "_"
    books: List[Tuple[str, Path]] = []
    unroutable: List[Dict[str, str]] = []
    for path in sorted(Path(data_dir).glob(JOURNAL_GLOB)):
        name = path.name
        if name == default_name:
            book_id = "conservative"
        elif name.startswith(prefix) and name.endswith(".jsonl"):
            book_id = name[len(prefix):-len(".jsonl")]
        else:
            unroutable.append({"file": name,
                               "reason": "имя не разбирается правилом писателя"})
            continue
        round_trip = _writer_history_filename(book_id)
        if round_trip != name:
            unroutable.append({"file": name, "book_id": book_id,
                               "reason": (f"круговой ход правила писателя даёт "
                                          f"{round_trip!r}, а файл зовётся {name!r}")})
            continue
        books.append((book_id, path))
    if not books:
        return {"measured": False,
                "reason": (f"журналов вердиктов не найдено в {data_dir} по шаблону "
                           f"{JOURNAL_GLOB} — мерить нечего, и это НЕ «оптимум всегда "
                           f"побеждал KEEP»"),
                "unroutable": unroutable}
    return {"measured": True, "books": books, "unroutable": unroutable}


def read_journal(path: Path) -> Dict[str, Any]:
    """Строки журнала. Нечитаемая строка НЕ пропускается молча — она считается."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"measured": False,
                "reason": f"журнал {path} не прочитан ({type(exc).__name__}: {exc})"}
    rows: List[dict] = []
    unparsable = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            unparsable += 1
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        else:
            unparsable += 1
    if not rows:
        return {"measured": False,
                "reason": (f"журнал {path} не содержит ни одной разобранной записи "
                           f"(нечитаемых строк {unparsable})")}
    return {"measured": True, "rows": rows, "unparsable": unparsable,
            "path": str(path)}


# ── ядро: одна запись ───────────────────────────────────────────────────────

def score_record(record: dict, policy: Dict[str, Any]) -> Dict[str, Any]:
    """Одна запись журнала: побеждает ли KEEP, и какими деньгами это сделано.

    Возвращает либо ``{"measured": False, "reason": …}`` (третий исход записи),
    либо полный разбор. Ни одна ветка не подставляет ноль вместо наблюдения.
    """
    cycle_date = str(record.get("cycle_date") or "").strip()
    if not cycle_date:
        return {"measured": False, "reason": "запись без `cycle_date` — "
                                             "к дате её отнести нечем"}
    capital = _num(record.get("capital_usd"))
    if capital is None or capital <= 0.0:
        return {"measured": False, "cycle_date": cycle_date,
                "reason": "`capital_usd` отсутствует или неположителен — "
                          "знаменатель ставки не наблюдён"}
    current = _positions(record.get("current_positions"))
    target = _positions(record.get("target_positions"))
    apy = _positions(record.get("apy_evidenced_pct"))
    if current is None or target is None or apy is None:
        missing = [name for name, value in
                   (("current_positions", current), ("target_positions", target),
                    ("apy_evidenced_pct", apy)) if value is None]
        return {"measured": False, "cycle_date": cycle_date,
                "reason": ("нечитаемы поля " + ", ".join(missing) +
                           " — пересчитать вторым производителем нечем")}

    deployed_now = sum(current.values())
    deployed_tgt = sum(target.values())
    weighted_now = sum(usd * apy.get(proto, 0.0) for proto, usd in current.items())
    weighted_tgt = sum(usd * apy.get(proto, 0.0) for proto, usd in target.items())
    apy_now_pp = weighted_now / capital
    apy_opt_pp = weighted_tgt / capital
    gain_pp = apy_opt_pp - apy_now_pp

    # Сверка со записанными числами: расхождение — третий исход, НЕ доверие записи.
    for field, mine in (("book_apy_pp", apy_now_pp), ("target_apy_pp", apy_opt_pp),
                        ("gain_pp", gain_pp)):
        recorded = _num(record.get(field))
        if recorded is None:
            continue
        if abs(recorded - mine) > _RECOMPUTE_EPS_PP:
            return {"measured": False, "cycle_date": cycle_date,
                    "reason": (f"recomputation_mismatch: `{field}` записан "
                               f"{recorded:.6f}, пересчёт даёт {mine:.6f} — два "
                               f"производителя спорят, и запись в вердикт не идёт")}

    # Точное разложение: смесь (та же сумма, другие ставки) + размер (сколько
    # денег вообще работает). Сумма обязана равняться `gain_pp`.
    apy_now_deployed = (weighted_now / deployed_now) if deployed_now > 0 else 0.0
    apy_tgt_deployed = (weighted_tgt / deployed_tgt) if deployed_tgt > 0 else 0.0
    mix_pp = deployed_now * (apy_tgt_deployed - apy_now_deployed) / capital
    size_pp = (deployed_tgt - deployed_now) * apy_tgt_deployed / capital
    if abs(mix_pp + size_pp - gain_pp) > _DECOMP_EPS_PP:
        return {"measured": False, "cycle_date": cycle_date,
                "reason": (f"decomposition_unbalanced: смесь {mix_pp:.9f} + размер "
                           f"{size_pp:.9f} ≠ прирост {gain_pp:.9f} — причину назвать "
                           f"нечем, и угадывать её нельзя")}

    dedeployed_usd = deployed_now - deployed_tgt
    outflow_usd = sum(max(0.0, usd - target.get(proto, 0.0))
                      for proto, usd in current.items())
    cost_usd = _num(record.get("cost_usd"))

    # Чистый исход за горизонт владельца. `cost_usd` не наблюдён ⇒ порода
    # `net_negative` НЕ ИЗМЕРЕНА (не «ноль издержек»).
    horizon_frac = policy["max_payback_days"] / _DAYS_YEAR
    if cost_usd is None:
        net_usd_horizon: Optional[float] = None
    else:
        net_usd_horizon = capital * gain_pp / 100.0 * horizon_frac - cost_usd

    # Причина знака — у того слагаемого, что больше по модулю. Существенность
    # применяется к ДОЛЛАРАМ этой причины, а не к пунктам прироста.
    cause = "cash" if abs(size_pp) > abs(mix_pp) else "mix"
    cause_usd = abs(dedeployed_usd) if cause == "cash" else outflow_usd
    dust_usd = policy["min_leg_frac"] * capital
    material = cause_usd >= dust_usd

    # Собственный гейт записи про окупаемость. Он и есть существующая проверка
    # чистого исхода: `payback_days ≤ max_payback_days` тождественно «за горизонт
    # прирост отбивает издержки». Поэтому отрицательный чистый исход есть НАХОДКА
    # только когда гейт при этом сказал `True` — то есть промахнулся. Гейта нет
    # (старая схема) ⇒ третий исход, а не «промахов ноль».
    gates = record.get("gates")
    payback_gate = (gates or {}).get("payback_within_horizon") \
        if isinstance(gates, dict) else None
    if gain_pp < 0.0:
        kind = "dominated_by_keep"
    elif net_usd_horizon is None:
        kind = "net_unmeasured"
    elif net_usd_horizon >= 0.0:
        kind = "ok"
    elif payback_gate is True:
        kind = "net_negative_missed_by_gate"
    elif payback_gate is False:
        kind = "net_negative_caught_by_gate"
    else:
        kind = "net_gate_unchecked"

    return {
        "measured": True,
        "cycle_date": cycle_date,
        "generated_at": record.get("generated_at"),
        "schema": record.get("schema"),
        "verdict_recorded": record.get("verdict"),
        "capital_usd": round(capital, 2),
        "apy_now_pp": round(apy_now_pp, 6),
        "apy_opt_pp": round(apy_opt_pp, 6),
        "gain_pp": round(gain_pp, 6),
        "mix_pp": round(mix_pp, 6),
        "size_pp": round(size_pp, 6),
        "deployed_now_usd": round(deployed_now, 2),
        "deployed_target_usd": round(deployed_tgt, 2),
        "dedeployed_usd": round(dedeployed_usd, 2),
        "outflow_usd": round(outflow_usd, 2),
        "cost_usd": cost_usd,
        "net_usd_horizon": (None if net_usd_horizon is None
                            else round(net_usd_horizon, 2)),
        "payback_gate": payback_gate,
        "cause": cause,
        "cause_usd": round(cause_usd, 2),
        "dust_usd": round(dust_usd, 2),
        "material": bool(material),
        "kind": kind,
    }


# ── побочное наблюдение: на какой книге считается объяснение кэша ────────────

def cash_explanation_axis(data_dir: Path, scored: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Видит ли объяснение простоя кэша ЦЕЛЬ, опубликованную в том же документе.

    ADR-055 требует объяснять кэш сверх буфера каждый цикл. Объяснение лежит в
    `allocation_rationale.json` → `cash` и считается по `current_positions`.
    Вопрос прибора один: бывает ли, что на ОДНУ дату объяснение говорит «излишка
    нет», а цель того же документа выводит деньги из оборота. Документ или поле
    недоступны ⇒ ``unchecked``, никогда ``False``.
    """
    try:
        from spa_core.paper_trading.allocation_rationale import RATIONALE_FILENAME
        name = str(RATIONALE_FILENAME)
    except Exception:  # noqa: BLE001
        name = RATIONALE_DOC_FALLBACK
    path = Path(data_dir) / name
    if not path.exists():
        return {"status": "unchecked",
                "reason": f"документ советника не найден: {path}"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "unchecked",
                "reason": (f"документ советника не прочитан "
                           f"({type(exc).__name__}: {exc})")}
    if not isinstance(doc, dict):
        return {"status": "unchecked", "reason": "документ советника — не объект"}
    cash = doc.get("cash")
    excess = _num((cash or {}).get("excess_pct")) if isinstance(cash, dict) else None
    if excess is None:
        return {"status": "unchecked",
                "reason": "в документе советника нет наблюдённого `cash.excess_pct`"}
    cycle_date = str(doc.get("cycle_date") or "").strip()
    same_day = [s for s in scored
                if s.get("measured") and s.get("cycle_date") == cycle_date]
    if not same_day:
        return {"status": "unchecked", "excess_pct": excess, "cycle_date": cycle_date,
                "reason": ("дата документа советника не встречается среди "
                           "измеренных записей журнала — сравнивать нечего")}
    idle = max((s["dedeployed_usd"] for s in same_day), default=0.0)
    silent = bool(excess <= 0.0 and idle > 0.0)
    return {
        "status": "measured",
        "cycle_date": cycle_date,
        "excess_pct": excess,
        "target_idle_beyond_current_usd": round(idle, 2),
        "silent_on_target_idle": silent,
        "explained_status": (cash or {}).get("status"),
    }


# ── перепись целиком ────────────────────────────────────────────────────────

def run_census(data_dir: Path, now: Optional[datetime] = None,
               params: Any = None) -> Dict[str, Any]:
    """Замер по всем книгам. Третий исход — всегда с названной причиной."""
    now = now or datetime.now(timezone.utc)
    policy = load_policy(params)
    if not policy.get("measured"):
        return _unmeasured(policy["reason"], now)
    found = discover_books(data_dir)
    if not found.get("measured"):
        return _unmeasured(found["reason"], now,
                           unroutable=found.get("unroutable") or [],
                           policy=policy)

    books: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    unmeasured_records: List[Dict[str, Any]] = []
    statuses: List[str] = []
    for book_id, path in found["books"]:
        journal = read_journal(path)
        if not journal.get("measured"):
            books.append({"book_id": book_id, "measured": False,
                          "reason": journal["reason"], "path": str(path)})
            statuses.append(STATUS_UNMEASURED)
            continue
        scored = [score_record(row, policy) for row in journal["rows"]]
        ok = [s for s in scored if s.get("measured")]
        bad = [s for s in scored if not s.get("measured")]
        for item in bad:
            unmeasured_records.append({"book_id": book_id, **item})
        book_findings = [dict(s, book_id=book_id) for s in ok
                         if s["kind"] in _FINDING_KINDS and s["material"]]
        dust = [s for s in ok if s["kind"] in _FINDING_KINDS and not s["material"]]
        findings.extend(book_findings)
        latest_date = max((s["cycle_date"] for s in ok), default=None)
        fresh = [f for f in book_findings if f["cycle_date"] == latest_date]
        if book_findings:
            book_status = STATUS_CRITICAL if fresh else STATUS_WARNING
        elif ok:
            book_status = STATUS_OK
        else:
            book_status = STATUS_UNMEASURED
        statuses.append(book_status)
        books.append({
            "book_id": book_id, "measured": True, "status": book_status,
            "path": str(path), "rows": journal["rows"] and len(journal["rows"]),
            "unparsable_lines": journal["unparsable"],
            "records_measured": len(ok), "records_unmeasured": len(bad),
            "latest_cycle_date": latest_date,
            "findings_material": len(book_findings),
            "findings_dust": len(dust),
            "fresh_findings": len(fresh),
            "dominated_by_keep": sum(1 for s in ok
                                     if s["kind"] == "dominated_by_keep"),
            "net_negative_missed_by_gate": sum(
                1 for s in ok if s["kind"] == "net_negative_missed_by_gate"),
            "net_negative_caught_by_gate": sum(
                1 for s in ok if s["kind"] == "net_negative_caught_by_gate"),
            "net_gate_unchecked": sum(1 for s in ok
                                      if s["kind"] == "net_gate_unchecked"),
            "net_unmeasured": sum(1 for s in ok if s["kind"] == "net_unmeasured"),
        })

    if all(s == STATUS_UNMEASURED for s in statuses):
        # Третий исход обязан НАЗВАТЬ причину по каждой книге и донести до
        # читателя разбор каждой непрошедшей записи. Замер приёмки #702: первая
        # редакция эту ветку обнуляла (`records_unmeasured` = 0 при пяти
        # названных причинах), то есть «не измерено» было неотличимо от «нечего
        # мерить» — ровно тот дефект, против которого прибор написан.
        why = "; ".join(
            str(b.get("reason")) if b.get("reason")
            else (f"книга {b['book_id']}: измеренных записей нет "
                  f"(не измерено {b.get('records_unmeasured', 0)})")
            for b in books) or "книг не найдено"
        return _unmeasured("ни одна книга не дала измеренной записи — " + why,
                           now, unroutable=found.get("unroutable") or [],
                           books=books, unmeasured_records=unmeasured_records,
                           policy=policy)

    if STATUS_CRITICAL in statuses:
        status = STATUS_CRITICAL
    elif STATUS_WARNING in statuses:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    fresh_total = sum(b.get("fresh_findings", 0) for b in books if b.get("measured"))
    return {
        "measured": True,
        "status": status,
        "generated_at": now.isoformat(),
        "criterion": CRITERION,
        "policy": {k: policy[k] for k in ("min_leg_frac", "max_payback_days",
                                          "min_gain_pp", "mode", "version")},
        "horizon_days": policy["max_payback_days"],
        "books": books,
        "unroutable_journals": found.get("unroutable") or [],
        "findings": findings,
        "unmeasured_records": unmeasured_records,
        "cash_explanation": cash_explanation_axis(data_dir, findings),
        # Заголовочные числа дублируются наверх намеренно: мост и офис читают их
        # через `observed_number(doc, key)`, который смотрит верхний уровень. Это
        # не второе место для числа — оба вычислены здесь же, одной строкой.
        "findings_material": len(findings),
        "dominated_by_keep": sum(1 for f in findings
                                 if f["kind"] == "dominated_by_keep"),
        "net_negative_missed_by_gate": sum(
            1 for f in findings if f["kind"] == "net_negative_missed_by_gate"),
        "net_negative_caught_by_gate": sum(
            b.get("net_negative_caught_by_gate", 0) for b in books if b.get("measured")),
        "net_gate_unchecked": sum(
            b.get("net_gate_unchecked", 0) for b in books if b.get("measured")),
        "fresh_findings": fresh_total,
        "records_unmeasured": len(unmeasured_records),
        "dedeployed_usd_max": round(
            max((f["dedeployed_usd"] for f in findings), default=0.0), 2),
    }


def _unmeasured(reason: str, now: datetime,
                unroutable: Optional[List[dict]] = None,
                books: Optional[List[dict]] = None,
                unmeasured_records: Optional[List[dict]] = None,
                policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Третий исход. Причина названа, и разбор непрошедших записей НЕ теряется.

    Предмет (`criterion`) стоит и здесь: артефакт, не называющий, ЧТО именно не
    удалось измерить, читателю бесполезен. Колонка порогов печатается, если её
    успели прочитать, и честно отсутствует, если нет, — «не измерено» у неё своё.
    """
    records = list(unmeasured_records or [])
    return {"measured": False, "status": STATUS_UNMEASURED, "reason": reason,
            "generated_at": now.isoformat(), "criterion": CRITERION,
            "policy": (dict(policy) if policy else None),
            "horizon_days": (policy or {}).get("max_payback_days"),
            "books": list(books or []),
            "findings": [],
            "unmeasured_records": records,
            "unroutable_journals": unroutable or [],
            "cash_explanation": {"status": "unchecked",
                                 "reason": "перепись не измерена"},
            "findings_material": 0, "dominated_by_keep": 0,
            "net_negative_missed_by_gate": 0, "net_negative_caught_by_gate": 0,
            "net_gate_unchecked": 0,
            "fresh_findings": 0, "records_unmeasured": len(records),
            "dedeployed_usd_max": 0.0}


# ── отчёт ───────────────────────────────────────────────────────────────────

def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return (f"оптимум против DO NOTHING (§49 Economics): НЕ ИЗМЕРЕНО — "
                f"{report.get('reason')}")
    return (f"оптимум против DO NOTHING (§49 Economics): {report['status']} · книг "
            f"{len(report['books'])} · материальных находок "
            f"{report['findings_material']} (оптимум ПРОИГРАЛ KEEP "
            f"{report['dominated_by_keep']}, гейт окупаемости ПРОМАХНУЛСЯ "
            f"{report['net_negative_missed_by_gate']}) · гейт поймал "
            f"{report['net_negative_caught_by_gate']}, гейта нет у "
            f"{report['net_gate_unchecked']} записей · на свежей дате "
            f"{report['fresh_findings']} · "
            f"максимум выведенного из оборота ${report['dedeployed_usd_max']:,.0f} · "
            f"записей НЕ ИЗМЕРЕНО {report['records_unmeasured']}")


def _refused_record_lines(report: Dict[str, Any], limit: int) -> List[str]:
    """Перечень непрошедших записей. Поля НЕТ ⇒ так и сказать, а не «их ноль»."""
    items = observed(report, "unmeasured_records", kind=list)
    if items is None:
        return ["[ЗАПИСИ НЕ ИЗМЕРЕНЫ] НЕ ИЗМЕРЕНО — артефакт не несёт поля "
                "`unmeasured_records`, и это НЕ «непрошедших записей нет»"]
    return [f"[ЗАПИСЬ НЕ ИЗМЕРЕНА] {item.get('book_id')} "
            f"{item.get('cycle_date')}: {item.get('reason')}"
            for item in items[:limit] if isinstance(item, dict)]


def _unroutable_lines(report: Dict[str, Any]) -> List[str]:
    """Журналы, чьё имя не разобралось правилом писателя. Та же честность чтения."""
    items = observed(report, "unroutable_journals", kind=list)
    if items is None:
        return ["[ЖУРНАЛЫ НЕ МАРШРУТИЗИРОВАНЫ] НЕ ИЗМЕРЕНО — артефакт не несёт "
                "поля `unroutable_journals`"]
    return [f"[ЖУРНАЛ НЕ МАРШРУТИЗИРОВАН] {item.get('file')}: {item.get('reason')}"
            for item in items if isinstance(item, dict)]


def format_report(report: Dict[str, Any], limit: int = 6) -> List[str]:
    """Строки для офиса — находка называет СВОЮ дверь."""
    lines = [summary_line(report)]
    if not report.get("measured"):
        # Третий исход тоже обязан НАЗВАТЬ причины читателю: «не измерено» без
        # перечня непрошедших записей неотличимо от «мерить было нечего».
        lines.extend(_refused_record_lines(report, limit))
        lines.extend(_unroutable_lines(report))
        return lines
    if report["status"] == STATUS_WARNING:
        lines.append(
            "[ВЕРДИКТ] на самой свежей дате журналов материальных находок НЕТ, но в "
            "истории они есть — «сегодня тихо» НЕ значит «такого не бывало»")
    for book in report["books"]:
        if not book.get("measured"):
            lines.append(f"[КНИГА {book['book_id']}] НЕ ИЗМЕРЕНО — {book['reason']}")
            continue
        lines.append(
            f"[КНИГА {book['book_id']}] {book['status']} · записей измерено "
            f"{book['records_measured']} (не измерено {book['records_unmeasured']}) · "
            f"оптимум проиграл KEEP {book['dominated_by_keep']} раз · промахов гейта "
            f"окупаемости {book['net_negative_missed_by_gate']} (поймано "
            f"{book['net_negative_caught_by_gate']}, гейта нет у "
            f"{book['net_gate_unchecked']}) · материальных "
            f"{book['findings_material']}, пыль {book['findings_dust']} · свежая дата "
            f"{book['latest_cycle_date']}")
    for item in report["findings"][:limit]:
        if item["kind"] == "dominated_by_keep":
            lines.append(
                f"[ОПТИМУМ ПРОИГРАЛ KEEP] {item['book_id']} {item['cycle_date']}: "
                f"книга {item['apy_now_pp']:.3f} пп, «оптимум» {item['apy_opt_pp']:.3f} пп, "
                f"прирост {item['gain_pp']:+.3f} пп ДО издержек · причина "
                f"{item['cause']}: смесь {item['mix_pp']:+.3f} пп, размер "
                f"{item['size_pp']:+.3f} пп · выведено из оборота в кэш под 0 % "
                f"${item['dedeployed_usd']:,.0f} (пыль владельца "
                f"${item['dust_usd']:,.0f}) · записанный вердикт "
                f"{item['verdict_recorded']}")
        else:
            lines.append(
                f"[ГЕЙТ ОКУПАЕМОСТИ ПРОМАХНУЛСЯ] {item['book_id']} "
                f"{item['cycle_date']}: прирост {item['gain_pp']:+.3f} пп за горизонт "
                f"{report['horizon_days']:.0f} дн. даёт "
                f"${item['net_usd_horizon']:,.2f} после издержек "
                f"${item['cost_usd']:,.2f}, а `payback_within_horizon` сказал True · "
                f"записанный вердикт {item['verdict_recorded']}")
    extra = len(report["findings"]) - limit
    if extra > 0:
        lines.append(f"… ещё {extra} находок(и) — полный перечень в артефакте")
    # Поле читается ЧЕСТНО: его отсутствие есть третий исход («артефакт не несёт
    # оси»), а не пустой словарь, из которого потом вышло бы «молчания нет».
    cash = observed(report, "cash_explanation", kind=dict)
    if cash is None:
        lines.append("[ОСЬ ОБЪЯСНЕНИЯ КЭША] НЕ ИЗМЕРЕНО — артефакт не несёт поля "
                     "`cash_explanation`")
    elif cash.get("status") == "measured" and cash.get("silent_on_target_idle"):
        lines.append(
            f"[ОСЬ ОБЪЯСНЕНИЯ КЭША] {cash['cycle_date']}: секция ADR-055 сообщает "
            f"излишек {cash['excess_pct']:.1f} % («{cash.get('explained_status')}»), а "
            f"цель ТОГО ЖЕ документа оставляет вне оборота "
            f"${cash['target_idle_beyond_current_usd']:,.0f} сверх удержанного — "
            f"объяснение считается по `current_positions`, цель ему не видна")
    elif cash.get("status") != "measured":
        lines.append(f"[ОСЬ ОБЪЯСНЕНИЯ КЭША] НЕ ПРОВЕРЕНО — {cash.get('reason')}")
    lines.extend(_refused_record_lines(report, limit))
    lines.extend(_unroutable_lines(report))
    lines.append(
        "ОПОРА: все три числа пересчитаны ВТОРЫМ производителем из позиций и ставок и "
        "сверены с записанными — расхождение уводит запись в третий исход, а не в "
        "доверие журналу; существенность применена к ДОЛЛАРАМ причины "
        f"(пыль владельца {report['policy']['min_leg_frac']:.3f} капитала), горизонт "
        f"{report['horizon_days']:.0f} дн. и полоса {report['policy']['min_gain_pp']:.2f} пп "
        f"взяты из колонки ADR-060 §3 ({report['policy']['mode']}, "
        f"{report['policy']['version']})")
    lines.append(
        "НЕ ДОКЛАДЫВАЕТ: что деньги двинулись (полосу прироста отрицательный знак не "
        "проходит) · что недоразвёртывание НЕВЕРНО (потолки и отказы по TVL настоящие) · "
        "кто именно обязан оценивать KEEP — это решение владельца. Пороги RiskPolicy v1.0, "
        "стоп-кран, аллокатор и живой трек НЕ трогаются: прибор только читает")
    return lines


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Артефакт для шага 0-офис. Запись атомарная (инвариант #5)."""
    from spa_core.utils.atomic import atomic_save
    path = Path(data_dir) / ARTIFACT_NAME
    # Порядок доводов — (данные, путь). Обратный порядок `atomic_save` отвергает
    # fail-CLOSED, и артефакт не появляется ВОВСЕ, а ступень докладывает
    # `measured=True` — отказ записи становится неотличим от успеха у всех, кто
    # смотрит на вывод, а не на диск (настоящая поломка цикла #701).
    atomic_save(report, str(path))
    return path


def run(root: str = ".", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Ступень моста находок (`findings_bridge`): померить и оставить артефакт.

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до читателя, иначе шаг 0-офис увидит отсутствие
    файла и не сможет отличить его от «ступень не запускалась».
    """
    data_dir = Path(root) / "data"
    report = run_census(data_dir, now=now)
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=None,
                    help="каталог данных (по умолчанию — data/ репозитория)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт целиком")
    ap.add_argument("--save", action="store_true",
                    help=f"записать {ARTIFACT_NAME} в каталог данных")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else (
        Path(__file__).resolve().parents[2] / "data")
    report = run_census(data_dir)
    if args.save and report.get("measured"):
        save_artifact(report, data_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)

    if not report.get("measured"):
        return EXIT_UNMEASURED
    # Ненулевой код — только на находку СВЕЖЕЙ даты, то есть на то, что решается
    # сегодня. `WARNING` (история есть, свежая дата чиста) печатается всегда, но
    # кодом не нудит: постоянно ненулевой прибор учит пропускать свой вывод, а
    # структурное утверждение держат ADR и карточка владельцу.
    return 1 if report["status"] == STATUS_CRITICAL else 0


if __name__ == "__main__":
    sys.exit(main())
