"""cio_explainability.py — §44 ТЗ «Portfolio CIO»: из чего состоит объяснение,
которое система даёт владельцу о СВОЁМ решении.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §44 «Explainability»::

    Для каждой recommendation owner explanation должна быть простой.
    Плохой вариант:
        utility score 0.7234
    Хороший:
        Aave currently earns 2.7%.
        Morpho's conservative expected yield is 4.5%.
        After moving $12k the projected Morpho yield remains 4.3%.
        Estimated switching cost is $7.80.
        Expected break-even is 2.6 days.
        The yield advantage has persisted for 36 hours.
        Risk remains inside existing limits.
        Recommendation: move $12k.

Владелец назвал ВОСЕМЬ фактов и назвал их сам — порядок и формулировки его.
Он же назвал ПЛОХУЮ форму: внутренний токен вместо человеческой фразы. Оба
списка здесь воспроизведены дословно и не расширены нами: §44 — критерий
владельца, а не наше представление о хорошем объяснении.

Ответ на «мерил ли кто-нибудь» — НЕТ
====================================
Объяснительный слой у нас есть и он не пустой:
:func:`spa_core.paper_trading.cio_brief.build_books_brief` строит по каждой
книге короткую русскую прозу из записанного вердикта. Но §44 спрашивает не
«есть ли объяснение», а из ЧЕГО оно состоит — сколько из восьми названных
владельцем фактов произносится о настоящем сегодняшнем решении. Такого счёта
не делал никто, и чтением кода его не получить: надо взять ТЕКСТ, который
система выдала сегодня, и сверить его с записью, из которой он построен.

Три исхода, и средний — самый важный
=====================================
``SPOKEN``
    факт произнесён в тексте владельцу, и там, где у владельца в примере
    стои́т ЧИСЛО, в тексте стои́т это же число.
``SILENT``
    величина в системе ЕСТЬ и названа поимённо (поле записи решения или
    соседний артефакт), но до фразы владельцу не доходит. Это разрыв
    ОТОБРАЖЕНИЯ — дешёвый.
``ABSENT``
    величины не считает никто. Это разрыв ИЗМЕРЕНИЯ — дорогой.
``UNCHECKED``
    судить не о чем или не удалось: у книги нет предложенного хода (объяснять
    нечего — это не провал), нет журнала решений, сорван положительный
    контроль. Отдельный исход с названной причиной, а не ноль и не пропуск:
    «не измерено» обязано быть отличимо от «прошло».

Разница между ``SILENT`` и ``ABSENT`` — единственное, ради чего этот замер
стоит делать. «Объяснение неполно» одинаково звучит в обоих случаях, а стоит
разного: в первом надо дописать предложение, во втором — построить
измеритель.

Почему присутствие факта ищется ПО ЗНАЧЕНИЮ, а не по словам
============================================================
Соблазн — искать в тексте слово «APY» или знак «%». Так делать нельзя:
сегодняшняя фраза несёт «Оборот $22,105 (22.1% капитала)», и поиск процента
объявил бы ставку пула произнесённой. Процент там есть — но он про оборот, а
не про доходность, и владельцу от него нет никакой пользы в вопросе «сколько
зарабатывает Aave».

Поэтому факт считается произнесённым, только если в тексте стои́т ЕГО
СОБСТВЕННОЕ ЧИСЛО — то самое, которое лежит в записи решения, из которой
текст построен, в одном из форматов, которыми эта проза пользуется. Совпавшая
подстрока кладётся в отчёт (``matched``), чтобы вердикт можно было проверить
глазами, а не поверить ему.

Положительный контроль — условие ВСЕГО замера, а не украшение
==============================================================
«Ни один факт не произнесён» ничего не значит, если детекторы не умеют видеть
произнесённый факт. Поэтому перед замером живого текста через те же самые
детекторы прогоняется СИНТЕТИЧЕСКОЕ объяснение, собранное дословно из примера
владельца (Aave 2.7 % → Morpho 4.5 %, после хода 4.3 %, стоимость $7.80,
окупаемость 2.6 дня, преимущество держится 36 часов, риск в пределах, ход
$12k). Все восемь обязаны выйти ``SPOKEN`` и ни одного внутреннего токена.

Контроль не прошёл ⇒ ВЕСЬ отчёт ``UNCHECKED``: детектор, не увидевший факт
там, где он заведомо есть, не имеет права утверждать, что где-то его нет.

ADVISORY. Модуль ничего не дописывает во фразу владельцу и не трогает путь
решения: и то и другое — правка money-path (что система говорит о движении
денег и как их двигает), решение владельца, а не агента.
"""
# LLM_FORBIDDEN

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_explainability.json"

SPOKEN = "SPOKEN"
SILENT = "SILENT"
ABSENT = "ABSENT"
UNCHECKED = "UNCHECKED"

#: Восемь фактов §44 в порядке ТЗ. Ключ → дословная строка примера владельца.
OWNER_FACTS: tuple[tuple[str, str], ...] = (
    ("source_rate", "Aave currently earns 2.7%"),
    ("target_expected_rate", "Morpho's conservative expected yield is 4.5%"),
    ("post_move_rate", "After moving $12k the projected Morpho yield remains 4.3%"),
    ("switching_cost", "Estimated switching cost is $7.80"),
    ("break_even", "Expected break-even is 2.6 days"),
    ("advantage_persistence", "The yield advantage has persisted for 36 hours"),
    ("risk_within_limits", "Risk remains inside existing limits"),
    ("recommendation", "Recommendation: move $12k"),
)

#: Плохая форма, названная владельцем дословно.
OWNER_BAD_SHAPE = "utility score 0.7234"

#: Поля брифа, которые ЧИТАЕТ владелец. Служебные (`verdict`, `policy_version`,
#: `decision_id`) сюда не входят намеренно: это метки записи, а не объяснение.
_OWNER_TEXT_FIELDS = ("where", "how_much", "why", "why_now")

#: Книги в порядке cio_brief._BOOKS.
_BOOKS: tuple[tuple[str, Optional[str]], ...] = (
    ("conservative", None),
    ("balanced", "balanced"),
    ("aggressive", "aggressive"),
)


# ───────────────────────────── поиск числа в тексте ─────────────────────────

def _renderings(value: float, kind: str) -> list[str]:
    """Формы, в которых проза брифа могла бы напечатать это число.

    Список закрытый и повторяет форматы, которыми пользуется
    :mod:`spa_core.paper_trading.cio_brief` (``:,.0f`` для денег, ``:.1%`` для
    долей) плюс обычные одна-две цифры после запятой. Расширять его «на всякий
    случай» нельзя: чем больше форм, тем выше шанс случайного совпадения, а
    ошибка здесь идёт в ЩЕДРУЮ сторону — в «произнесено».
    """
    v = float(value)
    out: list[str] = []
    if kind == "usd":
        a = abs(v)
        out += [f"{a:,.2f}", f"{a:,.0f}", f"{a:.2f}", f"{a:.0f}"]
    elif kind == "pct":
        out += [f"{v:.2f}", f"{v:.1f}"]
    elif kind == "days":
        out += [f"{v:.2f}", f"{v:.1f}", f"{v:.0f}"]
    elif kind == "hours":
        out += [f"{v:.1f}", f"{v:.0f}"]
    # дубли убираем, порядок сохраняем — первым совпавшим отчитываемся
    seen: set[str] = set()
    uniq: list[str] = []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def _find_number(text: str, rendering: str) -> Optional[str]:
    """Стои́т ли в тексте ИМЕННО это число, а не кусок более длинного.

    Границы проверяются вручную, а не ``\\b``: у ``\\b`` цифра и точка по
    разные стороны от границы, поэтому ``4.8`` нашлось бы внутри ``14.87``
    (и это не гипотеза — ``pendle`` сегодня 14.0048, а ``compound_v3`` 4.8179).
    """
    pat = re.escape(rendering)
    for m in re.finditer(pat, text):
        i, j = m.start(), m.end()
        before = text[i - 1] if i > 0 else ""
        after = text[j] if j < len(text) else ""
        # Сравнение с КОРТЕЖЕМ, а не `in ".,"`: пустая строка является
        # подстрокой любой строки, поэтому `before in ".,"` истинно на
        # НАЧАЛЕ текста — и число, стоящее первым, не находилось никогда.
        # Найдено мутацией: снятие соседнего ограждения ничего не меняло,
        # потому что до него не доходило.
        if before.isdigit() or before in (".", ","):
            continue
        if after.isdigit():
            continue
        if after == "." and j + 1 < len(text) and text[j + 1].isdigit():
            continue
        if after == "," and j + 1 < len(text) and text[j + 1].isdigit():
            continue
        return text[max(0, i - 30):min(len(text), j + 12)]
    return None


def _speaks(text: str, values: list[float], kind: str) -> Optional[dict]:
    """Первое значение из ``values``, произнесённое в тексте, + контекст."""
    for v in values:
        for r in _renderings(v, kind):
            hit = _find_number(text, r)
            if hit is not None:
                return {"value": v, "rendering": r, "matched": hit}
    return None


# ───────────────────────────── внутренние токены ────────────────────────────

#: Токен вида ``snake_case`` — форма, которую владелец назвал плохой
#: (``utility score 0.7234``: внутреннее имя вместо фразы). Требуется
#: подчёркивание: одиночное английское слово в русской прозе — это чаще
#: имя протокола или единица, а не утечка ключа.
_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _machine_tokens(text: str, known_names: set[str]) -> list[str]:
    """Внутренние ключи, утёкшие в текст владельцу.

    ``known_names`` — имена, которые в этом тексте законны: протоколы книги.
    Они тоже пишутся ``snake_case`` (``compound_v3``, ``fluid_usdc``), но это
    НАЗВАНИЯ ПРЕДМЕТОВ, а не ключи кода; смешать их — значит объявить находкой
    то, что владелец сам читает как имя пула.
    """
    found: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok in known_names or tok in found:
            continue
        found.append(tok)
    return found


# ─────────────────────────────── чтение входа ───────────────────────────────

def _load_sibling(ddir: Path, name: str) -> Optional[dict]:
    """Соседний артефакт из КАТАЛОГА СОСТОЯНИЯ, а не из корня дерева.

    Каталог передаётся аргументом (``--data-dir``) намеренно: иначе замер
    читал бы живой ``data/`` того дерева, из которого запущен, и вердикт
    зависел бы от хоста, а не от входа.
    """
    try:
        with open(ddir / name, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _leg_protocols(rec: dict, direction: str) -> list[str]:
    return [str(l.get("protocol")) for l in (rec.get("legs") or [])
            if l.get("direction") == direction and l.get("protocol")]


def _known_names(rec: dict) -> set[str]:
    names: set[str] = set()
    for key in ("current_positions", "target_positions", "apy_evidenced_pct"):
        val = rec.get(key)
        if isinstance(val, dict):
            names.update(str(k) for k in val)
    names.update(str(l.get("protocol")) for l in (rec.get("legs") or [])
                 if l.get("protocol"))
    return names


# ──────────────────────────────── восемь проб ───────────────────────────────
#
# Каждая проба возвращает (outcome, detail, source, evidence). Пробе НЕ
# передаётся вердикт соседней: восемь фактов независимы, и «объяснение
# неполное» не должно каскадом красить те, что произнесены.

def _fact(key: str, outcome: str, detail: str, *, source: str = "",
          evidence: Any = None) -> dict:
    return {
        "fact": key,
        "owner_wording": dict(OWNER_FACTS)[key],
        "outcome": outcome,
        "detail": detail,
        "source": source,
        "evidence": evidence,
    }


def _probe_rate(key: str, text: str, rec: dict, direction: str,
                fallback_field: str, human: str) -> dict:
    """Ставка пула, из которого выходим (``decrease``) или в который входим
    (``increase``). Гранулярность — ПОУЛЬНАЯ: владелец назвал «Aave earns
    2.7%», а не «книга зарабатывает 4.5%»."""
    apys = rec.get("apy_evidenced_pct")
    protos = _leg_protocols(rec, direction)
    values = []
    if isinstance(apys, dict):
        values = [float(apys[p]) for p in protos if isinstance(apys.get(p), (int, float))]
    if not values:
        book_level = rec.get(fallback_field)
        if isinstance(book_level, (int, float)):
            hit = _speaks(text, [float(book_level)], "pct")
            if hit:
                return _fact(key, SPOKEN,
                             f"{human} произнесена только на уровне КНИГИ "
                             f"({fallback_field}={book_level}); поуольной ставки "
                             f"в записи нет", source=fallback_field, evidence=hit)
            return _fact(key, SILENT,
                         f"поуольной ставки в записи нет; на уровне книги "
                         f"{fallback_field}={book_level} — и она тоже не произнесена",
                         source=fallback_field)
        return _fact(key, ABSENT,
                     f"{human} не считает никто: ни поуольной ставки, ни "
                     f"{fallback_field} в записи решения нет")
    hit = _speaks(text, values, "pct")
    rates: dict = apys if isinstance(apys, dict) else {}
    named = ", ".join(f"{p}={rates[p]}" for p in protos
                      if isinstance(rates.get(p), (int, float)))
    if hit:
        return _fact(key, SPOKEN, f"{human} произнесена: {hit['matched']}",
                     source="allocation_rationale_history:apy_evidenced_pct",
                     evidence=hit)
    return _fact(key, SILENT,
                 f"{human} измерена и лежит в ТОЙ ЖЕ записи, из которой "
                 f"построена фраза ({named}), но во фразу не попала",
                 source="allocation_rationale_history:apy_evidenced_pct",
                 evidence={"values": named})


def _probe_post_move_rate(text: str, marginal: Optional[dict]) -> dict:
    """«After moving $12k the projected Morpho yield remains 4.3%» — ставка
    цели ПОСЛЕ того, как в неё зашёл наш размер."""
    if marginal is None:
        return _fact("post_move_rate", ABSENT,
                     "ставки цели после захода нашего размера не считает "
                     "никто: оптимизатор линеен по ставке (размер позиции на "
                     "ставку не влияет, ADR-242), артефакта "
                     "data/marginal_apy_at_size.json на диске нет",
                     source="")
    values: list[float] = []
    for m in (marginal.get("measurements") or []):
        for field in ("apy_at_size_pct", "marginal_apy_pct", "apy_after_pct"):
            v = m.get(field)
            if isinstance(v, (int, float)):
                values.append(float(v))
    hit = _speaks(text, values, "pct") if values else None
    if hit:
        return _fact("post_move_rate", SPOKEN,
                     f"ставка после захода размера произнесена: {hit['matched']}",
                     source="data/marginal_apy_at_size.json", evidence=hit)
    return _fact("post_move_rate", SILENT,
                 "величина считается СОСЕДНИМ артефактом "
                 "(data/marginal_apy_at_size.json, ADR-242), но ни в запись "
                 "решения, ни во фразу владельцу не попадает; сам оптимизатор "
                 "линеен по ставке и её не спрашивает",
                 source="data/marginal_apy_at_size.json",
                 evidence={"measurements": len(marginal.get("measurements") or [])})


def _probe_cost(text: str, rec: dict, cost_evidence: Optional[dict]) -> dict:
    cost = rec.get("cost_usd")
    if not isinstance(cost, (int, float)):
        return _fact("switching_cost", ABSENT,
                     "стоимости хода в записи решения нет")
    hit = _speaks(text, [float(cost)], "usd")
    prov = ""
    if isinstance(cost_evidence, dict):
        charged = (cost_evidence.get("charged") or {}).get("total_usd")
        obs = (cost_evidence.get("observed_gas") or {}).get("total_usd")
        if isinstance(charged, (int, float)) and isinstance(obs, (int, float)):
            prov = (f" Провенанс (ADR-243): заряжено ${charged:,.2f} против "
                    f"наблюдённого газа ${obs:,.4f}")
    if hit:
        return _fact("switching_cost", SPOKEN,
                     f"стоимость произнесена: {hit['matched']}.{prov}",
                     source="allocation_rationale_history:cost_usd", evidence=hit)
    return _fact("switching_cost", SILENT,
                 f"стоимость ${float(cost):,.2f} лежит в записи, но во фразу "
                 f"не попала.{prov}",
                 source="allocation_rationale_history:cost_usd")


def _probe_break_even(text: str, rec: dict) -> dict:
    days = rec.get("payback_days")
    if not isinstance(days, (int, float)):
        return _fact("break_even", ABSENT,
                     "срока окупаемости в записи решения нет")
    hit = _speaks(text, [float(days)], "days")
    if hit:
        return _fact("break_even", SPOKEN,
                     f"окупаемость произнесена: {hit['matched']}",
                     source="allocation_rationale_history:payback_days", evidence=hit)
    return _fact("break_even", SILENT,
                 f"окупаемость посчитана и лежит в той же записи "
                 f"(payback_days={days}), но во фразу не попала",
                 source="allocation_rationale_history:payback_days")


#: Имена, под которыми длительность преимущества лежала бы в записи решения,
#: если бы её кто-нибудь считал. Список объявлен ЗАРАНЕЕ и намеренно: без него
#: проба не могла бы вернуть ``SPOKEN`` ни при каком входе, то есть была бы
#: проверкой, которая не умеет менять вердикт, — ровно тем дефектом, ради
#: которого ниже стои́т положительный контроль.
_PERSISTENCE_FIELDS = ("advantage_persist_hours", "persistence_hours",
                       "advantage_age_hours")


def _probe_persistence(text: str, rec: dict, params_fields: set[str]) -> dict:
    """«The yield advantage has persisted for 36 hours».

    Не путать со счётчиком в ``why_now``: там ДЛИТЕЛЬНОСТЬ НЕИЗМЕННОГО
    ВЕРДИКТА («5-й день подряд без изменений»), то есть «мы столько дней
    ничего не делали». Владелец спрашивает про длительность самого
    ПРЕИМУЩЕСТВА — сколько времени цель обгоняет источник. Это разные
    величины: вердикт может не меняться именно потому, что преимущества нет.
    """
    values = [float(rec[f]) for f in _PERSISTENCE_FIELDS
              if isinstance(rec.get(f), (int, float))]
    if values:
        hit = _speaks(text, values, "hours")
        if hit:
            return _fact("advantage_persistence", SPOKEN,
                         f"длительность преимущества произнесена: {hit['matched']}",
                         source="allocation_rationale_history:"
                                + ",".join(_PERSISTENCE_FIELDS),
                         evidence=hit)
        return _fact("advantage_persistence", SILENT,
                     f"длительность преимущества посчитана ({values[0]} ч), но "
                     f"во фразу не попала",
                     source="allocation_rationale_history")
    if any("persist" in f for f in params_fields):
        return _fact("advantage_persistence", SILENT,
                     "порог устойчивости объявлен в TriggerParams, но самой "
                     "длительности в записи решения нет и во фразу она не "
                     "попадает", source="TriggerParams")
    return _fact("advantage_persistence", ABSENT,
                 "длительность преимущества не считает никто: среди дилов "
                 "TriggerParams (ADR-060) порога устойчивости нет, и в записи "
                 "решения нет ни одного из полей "
                 + "/".join(_PERSISTENCE_FIELDS)
                 + ". Счётчик в why_now отвечает на ДРУГОЙ вопрос — сколько "
                 "дней не менялся ВЕРДИКТ. Тот же факт назван владельцем "
                 "второй раз в §41 как «minimum persistence» — обязательный "
                 "лимит авто-исполнения")


def _probe_risk_within_limits(text: str, rec: dict,
                              risk_check: Optional[dict]) -> dict:
    """«Risk remains inside existing limits» — вердикт RiskPolicy, а не
    экономические гейты ADR-060.

    Разница существенна: сегодняшняя фраза перечисляет «оборот хода в
    бюджете» и «недельный оборот в бюджете» — это дилы ADR-060, решающие,
    сто́ит ли делать РАЗРЕШЁННЫЙ ход. Вопрос владельца — про сам запрет:
    внутри ли потолков концентрации, пола TVL и буфера кэша.
    """
    gates = rec.get("gates")
    gate_names = sorted(gates) if isinstance(gates, dict) else []
    if risk_check is None:
        return _fact("risk_within_limits", ABSENT,
                     "вердикта RiskPolicy нет ни в записи решения, ни на диске "
                     f"(data/risk_limits_check.json); во фразе перечислены "
                     f"экономические гейты ADR-060 ({', '.join(gate_names)}), "
                     "которые отвечают на другой вопрос")
    verdict = risk_check.get("gate")
    hit = None
    if isinstance(verdict, str) and verdict:
        # вердикт словесный, не числовой — ищем само слово
        hit = verdict if verdict.lower() in text.lower() else None
    if hit:
        return _fact("risk_within_limits", SPOKEN,
                     f"вердикт лимитов произнесён: {verdict}",
                     source="data/risk_limits_check.json", evidence={"gate": verdict})
    return _fact("risk_within_limits", SILENT,
                 f"вердикт лимитов считается и лежит рядом "
                 f"(data/risk_limits_check.json: gate={verdict}), но во фразу "
                 f"не попадает; вместо него перечислены экономические гейты "
                 f"ADR-060 ({', '.join(gate_names)}) — это ответ на другой вопрос",
                 source="data/risk_limits_check.json",
                 evidence={"gate": verdict, "gates_in_text": gate_names})


def _probe_recommendation(text: str, rec: dict) -> dict:
    legs = rec.get("legs") or []
    values = [abs(float(l.get("delta_usd") or 0.0)) for l in legs
              if l.get("delta_usd")]
    if not values:
        return _fact("recommendation", UNCHECKED,
                     "у книги нет предложенного хода — рекомендации, которую "
                     "надо объяснять, сегодня не существует")
    hit = _speaks(text, values, "usd")
    if hit:
        return _fact("recommendation", SPOKEN,
                     f"ход назван суммой: {hit['matched']}",
                     source="allocation_rationale_history:legs", evidence=hit)
    return _fact("recommendation", SILENT,
                 f"ноги хода записаны ({len(values)} шт.), но сумм во фразе нет",
                 source="allocation_rationale_history:legs")


# ─────────────────────────────── замер одной книги ──────────────────────────

def measure_brief(brief: dict, rec: Optional[dict], *,
                  marginal: Optional[dict] = None,
                  cost_evidence: Optional[dict] = None,
                  risk_check: Optional[dict] = None,
                  params_fields: Optional[set[str]] = None) -> dict:
    """Чистая функция: бриф + запись, из которой он построен → восемь исходов.

    Ввода-вывода нет намеренно — ровно это позволяет прогнать по ней и живой
    текст, и синтетический пример владельца ОДНИМИ И ТЕМИ ЖЕ детекторами.
    Разойдись они хоть на строку, положительный контроль перестал бы быть
    контролем.
    """
    params_fields = params_fields or set()
    if not brief.get("available"):
        reason = str(brief.get("reason") or "бриф недоступен")
        return {
            "text": "",
            "facts": [_fact(k, UNCHECKED, f"объяснения нет: {reason}")
                      for k, _ in OWNER_FACTS],
            "machine_tokens": [],
            "has_recommendation": False,
        }
    text = " ".join(str(brief.get(f) or "") for f in _OWNER_TEXT_FIELDS)
    rec = rec or {}
    has_legs = bool(rec.get("legs"))

    facts = [
        _probe_rate("source_rate", text, rec, "decrease", "book_apy_pp",
                    "ставка пула, из которого выходим"),
        _probe_rate("target_expected_rate", text, rec, "increase", "target_apy_pp",
                    "ставка пула, в который входим"),
        _probe_post_move_rate(text, marginal),
        _probe_cost(text, rec, cost_evidence),
        _probe_break_even(text, rec),
        _probe_persistence(text, rec, params_fields),
        _probe_risk_within_limits(text, rec, risk_check),
        _probe_recommendation(text, rec),
    ]
    # Книга без предложенного хода: факты, описывающие ХОД, объяснять нечего.
    # Это не провал §44 — это отсутствие предмета, и оно обязано читаться
    # иначе, чем «объяснение неполно».
    if not has_legs:
        move_facts = {"source_rate", "target_expected_rate", "post_move_rate",
                      "switching_cost", "break_even", "advantage_persistence",
                      "recommendation"}
        facts = [f if f["fact"] not in move_facts
                 else _fact(f["fact"], UNCHECKED,
                            "у книги нет предложенного хода — объяснять нечего")
                 for f in facts]
    return {
        "text": text,
        "facts": facts,
        "machine_tokens": _machine_tokens(text, _known_names(rec)),
        "has_recommendation": has_legs,
    }


# ───────────────────────────── положительный контроль ───────────────────────

#: Объяснение владельца, собранное дословно из его же примера §44. Числа —
#: его: 2.7 / 4.5 / 4.3 / 7.80 / 2.6 / 36 / $12k.
CONTROL_BRIEF: dict = {
    "available": True,
    "where": "Держит: aave ($40,000). Предложенный ход: −aave ($12,000), "
             "+morpho ($12,000).",
    "how_much": "Aave сейчас зарабатывает 2.70%. Консервативная ожидаемая "
                "доходность morpho — 4.50%. После захода $12,000 ожидаемая "
                "доходность morpho остаётся 4.30%. Оценочная стоимость "
                "перехода $7.80.",
    "why": "Окупаемость 2.6 дня. Преимущество держится 36 часов. Риск в "
           "пределах действующих лимитов: PASS.",
    "why_now": "преимущество устойчиво.",
}

CONTROL_RECORD: dict = {
    "cycle_date": "2026-01-01",
    "legs": [{"protocol": "aave", "direction": "decrease", "delta_usd": -12000.0},
             {"protocol": "morpho", "direction": "increase", "delta_usd": 12000.0}],
    "apy_evidenced_pct": {"aave": 2.7, "morpho": 4.5},
    "book_apy_pp": 2.7,
    "target_apy_pp": 4.5,
    "cost_usd": 7.80,
    "payback_days": 2.6,
    "current_positions": {"aave": 40000.0},
    "gates": {"gain_above_band": True},
    # Владелец в примере называет «persisted for 36 hours» — значит в контроле
    # эта величина ЕСТЬ. Живая запись такого поля не несёт, и разница между
    # контролем и живым замером здесь именно та, которую §44 и меряет.
    "advantage_persist_hours": 36.0,
}

CONTROL_MARGINAL: dict = {"measurements": [{"apy_at_size_pct": 4.3}]}
CONTROL_RISK_CHECK: dict = {"gate": "PASS"}


def run_control() -> dict:
    """Прогнать детекторы по примеру владельца. Все восемь обязаны SPOKEN."""
    got = measure_brief(CONTROL_BRIEF, CONTROL_RECORD,
                        marginal=CONTROL_MARGINAL,
                        cost_evidence=None,
                        risk_check=CONTROL_RISK_CHECK,
                        params_fields=set())
    spoken = [f["fact"] for f in got["facts"] if f["outcome"] == SPOKEN]
    missed = [f["fact"] for f in got["facts"] if f["outcome"] != SPOKEN]
    ok = not missed and not got["machine_tokens"]
    return {
        "passed": ok,
        "spoken": len(spoken),
        "expected": len(OWNER_FACTS),
        "missed": missed,
        "machine_tokens": got["machine_tokens"],
        "reason": ("" if ok else
                   f"детекторы не увидели факт(ы) в примере владельца: "
                   f"{', '.join(missed) or '—'}"
                   + (f"; ложные токены: {got['machine_tokens']}"
                      if got["machine_tokens"] else "")),
    }


# ─────────────────────────────────── прогон ─────────────────────────────────

def _params_fields() -> set[str]:
    try:
        from spa_core.allocator.rebalance_economics import TriggerParams
        return set(getattr(TriggerParams, "__dataclass_fields__", {}))
    except Exception:  # noqa: BLE001 — недоступность дилов это не крах замера
        return set()


def run(*, root: str = REPO_ROOT, data_dir: Optional[str] = None,
        now: dt.datetime | None = None, write: bool = True) -> dict:
    """Замерить §44 по каждой книге и записать отчёт."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ddir = Path(data_dir) if data_dir else Path(root) / "data"

    control = run_control()
    from spa_core.paper_trading.shadow_trigger_eval import load_history

    marginal = _load_sibling(ddir, "marginal_apy_at_size.json")
    cost_evidence = _load_sibling(ddir, "rebalance_cost_evidence.json")
    risk_check = _load_sibling(ddir, "risk_limits_check.json")
    params_fields = _params_fields()

    books: list[dict] = []
    subject: Optional[dict] = None
    try:
        from spa_core.paper_trading.cio_brief import build_books_brief
        briefs = build_books_brief(ddir)
    except Exception as exc:  # noqa: BLE001
        briefs = {}
        control = dict(control, passed=False,
                       reason=f"объяснительный слой не поднялся: "
                              f"{type(exc).__name__}: {exc}")

    for key, book_id in _BOOKS:
        brief = (briefs or {}).get(key) or {"available": False,
                                            "reason": "бриф не построен"}
        rec = None
        if brief.get("available"):
            try:
                records, _ = load_history(ddir, book_id=book_id)
                rec = records[-1] if records else None
            except Exception as exc:  # noqa: BLE001
                rec = None
                brief = {"available": False,
                         "reason": f"журнал решений не прочитан: {exc}"}
        got = measure_brief(brief, rec, marginal=marginal,
                            cost_evidence=cost_evidence, risk_check=risk_check,
                            params_fields=params_fields)
        tally = {o: sum(1 for f in got["facts"] if f["outcome"] == o)
                 for o in (SPOKEN, SILENT, ABSENT, UNCHECKED)}
        entry = {
            "book": key,
            "has_recommendation": got["has_recommendation"],
            "cycle_date": (rec or {}).get("cycle_date"),
            "verdict": (rec or {}).get("verdict"),
            "tally": tally,
            "facts": got["facts"],
            "machine_tokens": got["machine_tokens"],
            "owner_text": got["text"],
        }
        books.append(entry)
        if subject is None and got["has_recommendation"]:
            subject = entry

    consumers = _brief_consumers(root)
    findings, unchecked = _findings(books, subject, control, consumers)
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    overall = ("UNCHECKED" if not control["passed"]
               else "CRITICAL" if counts["critical"]
               else "WARN" if counts["warn"]
               else "UNCHECKED" if counts["unchecked"]
               else "OK")
    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "owner_criterion": ("§44 ТЗ «Portfolio CIO»: для КАЖДОЙ recommendation "
                            "объяснение владельцу простое; восемь фактов "
                            "названы владельцем, плохая форма — внутренний "
                            "токен вместо фразы"),
        "facts_total": len(OWNER_FACTS),
        "owner_bad_shape": OWNER_BAD_SHAPE,
        "control": control,
        "subject_book": (subject or {}).get("book"),
        "tally": (subject or {}).get("tally"),
        "books": books,
        "explanation_layer": {
            "producer": "spa_core/paper_trading/cio_brief.py::build_books_brief",
            "consumers": consumers,
            "daily_channel": _DAILY_CHANNEL,
            "in_daily_channel": _DAILY_CHANNEL in consumers,
        },
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: ни одно предложение во фразу владельцу этим "
                     "модулем не дописывается — что система говорит о движении "
                     "денег меняет money-path, это решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _brief_consumers(root: str) -> list[str]:
    """Кто РЕАЛЬНО показывает бриф. Замер, а не список из головы: §44 про то,
    что владелец ЧИТАЕТ, и объяснение без читателя объяснением не является.

    Ищется УПОМИНАНИЕ В КОДЕ (узел дерева), а не подстрока в файле. Разница
    измерена: ``hy_cycle.py`` и ``lp_cycle.py`` называют ``build_books_brief``
    в КОММЕНТАРИИ (объясняют, зачем пишут журнал под своим ``book_id``), а
    этот модуль — в собственной документации; брифа не показывает ни один.

    Но и «узел вызова» здесь мало: единственный настоящий потребитель,
    ``api/routers/live.py``, функцию не ВЫЗЫВАЕТ — он передаёт её объектом в
    ``asyncio.to_thread(build_books_brief, _dd)``. Проверка по форме вызова
    объявила бы объяснительный слой вовсе без читателей, то есть соврала бы в
    ту же сторону, что и подстрока, только тише. Считается любое обращение к
    имени в коде; себя модуль исключает — измеритель не потребитель.
    """
    import ast
    hits: list[str] = []
    for sub in ("spa_core", "scripts"):
        base = os.path.join(root, sub)
        for dirpath, _subdirs, files in os.walk(base):
            if "tests" in dirpath.split(os.sep):
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, root)
                if rel.endswith(os.path.join("paper_trading", "cio_brief.py")):
                    continue
                # realpath, а не abspath: символические ссылки abspath не
                # разворачивает, а рабочие деревья живут в `/tmp`, который на
                # macOS есть ссылка на `/private/tmp`. Измеритель, найденный
                # по одному написанию пути и исключаемый по другому, попадал
                # в собственный список читателей — и объяснение выглядело
                # прочитанным ровно тем, что проверяет, читают ли его.
                if os.path.realpath(path) == os.path.realpath(__file__):
                    continue          # измеритель себе не читатель
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        src = fh.read()
                except OSError:
                    continue
                if "build_books_brief" not in src:
                    continue          # дешёвый отсев, вердикт выносит разбор
                try:
                    tree = ast.parse(src)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    named = (node.id if isinstance(node, ast.Name)
                             else node.attr if isinstance(node, ast.Attribute)
                             else None)
                    if named == "build_books_brief":
                        hits.append(rel)
                        break
    return sorted(hits)


#: Канал, которым владелец читает систему каждый день. Проверяется отдельно от
#: числа потребителей: «читателей 1» и «в ежедневном отчёте объяснения нет» —
#: разные утверждения, и второе владельцу важнее.
_DAILY_CHANNEL = "spa_core/alerts/daily_report.py"


def _findings(books: list[dict], subject: Optional[dict], control: dict,
              consumers: list[str]) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []

    if not control["passed"]:
        unchecked.append(
            "положительный контроль не пройден — детекторы не увидели факт(ы) "
            "в примере САМОГО владельца, поэтому отсутствие факта в живом "
            "тексте не доказано: " + control["reason"])
        return findings, unchecked

    if subject is None:
        unchecked.append(
            "ни у одной книги нет предложенного хода — recommendation, которую "
            "§44 требует объяснять, сегодня не существует; счёт по фактам хода "
            "не снимается")
        return findings, unchecked

    t = subject["tally"]
    spoken, silent, absent = t[SPOKEN], t[SILENT], t[ABSENT]
    findings.append({
        "severity": "CRITICAL" if spoken * 2 < len(OWNER_FACTS) else "WARN",
        "code": "explanation_incomplete",
        "message": (f"книга «{subject['book']}»: из {len(OWNER_FACTS)} фактов, "
                    f"названных владельцем, объяснение произносит {spoken}; "
                    f"{silent} измерены и лежат рядом, но до фразы не доходят; "
                    f"{absent} не считает никто"),
    })
    if silent:
        names = [f["fact"] for f in subject["facts"] if f["outcome"] == SILENT]
        findings.append({
            "severity": "WARN",
            "code": "measured_but_unspoken",
            "message": ("величины ЕСТЬ, но владелец их не видит: "
                        + ", ".join(names)
                        + " — это разрыв отображения, а не измерения"),
        })
    for f in subject["facts"]:
        if f["outcome"] == ABSENT:
            findings.append({
                "severity": "WARN",
                "code": f"no_producer:{f['fact']}",
                "message": (f"«{f['owner_wording']}» — {f['detail']}"),
            })
    if not consumers:
        findings.append({
            "severity": "CRITICAL",
            "code": "explanation_has_no_reader",
            "message": ("объяснительный слой не показывает никто — объяснение "
                        "без читателя объяснением не является"),
        })
    elif _DAILY_CHANNEL not in consumers:
        findings.append({
            "severity": "WARN",
            "code": "explanation_absent_from_daily_channel",
            "message": ("объяснение доходит только до " + ", ".join(consumers)
                        + f"; ежедневного отчёта ({_DAILY_CHANNEL}), которым "
                        "владелец читает систему каждый день, среди читателей "
                        "нет — за объяснением решения надо идти в дашборд"),
        })
    if subject["machine_tokens"]:
        findings.append({
            "severity": "WARN",
            "code": "machine_tokens_in_owner_text",
            "message": ("во фразе владельцу стоя́т внутренние ключи — та самая "
                        f"форма, которую он назвал плохой («{OWNER_BAD_SHAPE}»): "
                        + ", ".join(subject["machine_tokens"][:8])),
        })
    for b in books:
        if not b["has_recommendation"]:
            unchecked.append(
                f"книга «{b['book']}»: предложенного хода нет — объяснять "
                f"нечего (это не провал §44)")
    return findings, unchecked


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="§44 ТЗ CIO — explainability")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, data_dir=args.data_dir, write=not args.no_write)
    c = doc["counts"]
    t = doc.get("tally") or {}
    print(f"cio_explainability: {doc['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']})")
    if t:
        print(f"  из {doc['facts_total']} фактов владельца: произносится "
              f"{t.get(SPOKEN)} · измерено, но молчим {t.get(SILENT)} · "
              f"не считает никто {t.get(ABSENT)} · не измерено {t.get(UNCHECKED)}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
