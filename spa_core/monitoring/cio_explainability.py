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

from spa_core.utils.observation import observed, observed_number

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_explainability.json"
#: Собственный путь измерителя в дереве — для самоисключения из списка читателей.
SELF_REL = "spa_core/monitoring/cio_explainability.py"

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

#: Критерий §49 приказа «Portfolio CIO», мерой ПОЛОВИНЫ которого модуль себя
#: объявляет. Якорь читается как НАЧАЛО строки (ADR-333).
#:
#: Половина — потому что критерий владельца назван ДВУМЯ словами: «Каждое
#: решение имеет snapshot и explanation». Объяснение меряет этот модуль (§44),
#: снимок — сосед `decision_audit_trail` (§43). Населения у половин РАЗНЫЕ
#: (рекомендации книг против перекладок живого трека), и слить их в один
#: знаменатель значило бы соврать о том, сколько решений вообще судится.
CRITERION = (
    "§49 Auditability (половина «explanation») приказа владельца «Portfolio CIO» "
    "— дословно: «Каждое решение имеет snapshot и explanation». Объяснение здесь "
    "это восемь фактов §44 во фразе владельцу И отсутствие формы, которую он "
    "назвал плохой (внутренний токен вместо фразы)"
)

CRITERION_SATISFIED = "SATISFIED"
CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
CRITERION_UNMEASURED = "UNMEASURED"

# ── §44, вторая ось (ADR-990): объяснение — О ТОМ ЛИ ходе, который книга исполнила? ──
#
# Восемь фактов выше отвечают на вопрос «из чего состоит фраза». Они молчат о
# другом: о ТОМ ли решении эта фраза. Объяснительный слой строится из записи
# ТЕНИ (ADR-060 shadow: советник, чьи ходы никто не исполняет), а деньги книги
# двигает цикл — другой писатель, другой журнал (`data/audit_trail.jsonl`,
# та же дверь, что у §43 ADR-989). Фраза «HOLD», произнесённая в день, когда
# книга переложила $40 000, безупречна по восьми фактам и объясняет не тот
# ход. Это ось §43 «решение ↔ исполнено», увиденная с стороны владельца:
# там спрашивали «записано ли исполненное», здесь — «о нём ли ему рассказали».
EXECUTED_AXIS_PROVENANCE = (
    "§44 ТЗ CIO, ось ADR-990: объяснение владельцу судится против ИСПОЛНЕННОГО "
    "книгой хода (трейл `data/audit_trail.jsonl`, событие `trade_executed`, та "
    "же дверь, что у §43 ADR-989), а не только по составу фразы; контрапункты — "
    "трим ADR-850 (ADR-987/988) и стадия/взвод (ADR-986) во фразе"
)
#: Имя трейла в каталоге состояния. Путь берётся из ЕДИНСТВЕННОГО владельца
#: (`decision_audit_trail.TRAIL_REL`), здесь — только его базовое имя.
TRAIL_NAME = "audit_trail.jsonl"
DAY_CONSISTENT = "consistent"
DAY_HOLD_WHILE_BOOK_MOVED = "hold_while_book_moved"
DAY_MOVE_NOT_EXECUTED = "move_not_executed"
DAY_DIFFERENT_MOVE = "different_move"
DAY_UNMEASURED = "unmeasured"
DAY_OUTCOMES: tuple[str, ...] = (DAY_CONSISTENT, DAY_HOLD_WHILE_BOOK_MOVED,
                                 DAY_MOVE_NOT_EXECUTED, DAY_DIFFERENT_MOVE,
                                 DAY_UNMEASURED)
HELD_MATCHES, HELD_DIFFERS, HELD_UNMEASURED = "matches", "differs", "unmeasured"
#: Вердикт записи тени, означающий «ничего не делать». Любой другой — ход.
HOLD_VERDICTS: frozenset = frozenset({"HOLD", "KEEP", "DO_NOTHING"})
#: Поля записи трима ADR-850, которыми фраза могла бы назвать урезание.
TRIM_RECORD_KEY = "admissible_trim"


def criterion_verdict(doc: dict) -> dict:
    """Вердикт о ПОЛОВИНЕ критерия §49 `Auditability` — по уже снятому отчёту.

    Правило живёт здесь, у производителя чисел; читатель его ПЕРЕНОСИТ
    (ADR-220). Своего порога нет ни одного: «для КАЖДОЙ recommendation» и
    перечень из восьми фактов — слова владельца, а не выбранная нами доля.

    **Положительный контроль — предпосылка вердикта, а не украшение.** Пример
    владельца прогоняется теми же детекторами и обязан дать 8 из 8. Не дал ⇒
    детекторы сломаны, и тогда ни «произносится», ни «молчит» не значат ничего:
    вердикт `UNMEASURED`, а не «молчит». Это ровно то различение, из-за которого
    у отчёта есть `control`.

    Три исхода разведены (инв. #17):

    * `SATISFIED` — есть хотя бы одна книга с recommendation, и у КАЖДОЙ такой
      книги произнесены все восемь фактов, и ни в одной фразе нет формы,
      названной владельцем плохой;
    * `NOT_SATISFIED` — факт не произнесён либо во фразе стои́т внутренний
      токен; книги и числа НАЗВАНЫ;
    * `UNMEASURED` — контроль не прошёл / разделов отчёта нет / **ни одна книга
      не несёт recommendation**. Последнее не «чисто»: «для каждой
      recommendation объяснение полно» при нуле recommendation верно ПО
      ПОСТРОЕНИЮ.
    """
    control = observed(doc, "control", kind=dict)
    if control is None:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("в отчёте нет раздела `control` — без положительного "
                           "контроля «молчит» неотличимо от «детектор сломан»")}
    if not control.get("passed"):
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"положительный контроль НЕ ПРОШЁЛ "
                           f"({control.get('reason') or 'причина не названа'}; "
                           f"произнесено {control.get('spoken')} из "
                           f"{control.get('expected')}) — детекторы не судят, и "
                           f"их молчание о живых книгах не значит ничего")}
    total = observed_number(doc, "facts_total")
    if total is None:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("в отчёте не читается `facts_total` — знаменателя "
                           "владельца НЕТ, и доля произнесённого НЕ ИЗМЕРЕНА")}
    books = observed(doc, "books", kind=list)
    if books is None:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("в отчёте нет списка `books` — население "
                           "рекомендаций НЕ ПРОЧИТАНО")}
    with_rec = [b for b in books
                if isinstance(b, dict) and b.get("has_recommendation")]
    if not with_rec:
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"ни одна из {len(books)} книг не несёт recommendation — "
                           f"«для КАЖДОЙ recommendation объяснение полно» при нуле "
                           f"recommendation верно ПО ПОСТРОЕНИЮ и ответом не "
                           f"является")}

    silent: list[str] = []
    tokens: list[str] = []
    unread: list[str] = []
    for book in with_rec:
        name = book.get("book") or "книга не названа"
        tally = observed(book, "tally", kind=dict)
        spoken = observed_number(tally, SPOKEN) if tally is not None else None
        if spoken is None:
            unread.append(f"{name}: счёт произнесённого НЕ ПРОЧИТАН")
            continue
        if spoken < total:
            silent.append(f"{name}: произносится {spoken:.0f} из {total:.0f}")
        machine = book.get("machine_tokens")
        if isinstance(machine, list) and machine:
            tokens.append(f"{name}: " + ", ".join(str(t) for t in machine[:4]))

    # Ось ADR-990: о ТОМ ли ходе фраза. Артефакт прежней версии раздела не несёт
    # — он судится как прежде и ВСЛУХ говорит, что ось не снята (не «снята и
    # чиста»). Раздел есть, но ось НЕ ИЗМЕРЕНА — конъюнкция с неизвестным
    # членом неизвестна: иначе-SATISFIED становится UNMEASURED с причиной.
    wrong_move: list[str] = []
    axis_note = ""
    axis_unmeasured = ""
    axis = observed(doc, "executed_move", kind=dict)
    if axis is None:
        axis_note = (" Ось ADR-990 «о том ли ходе объяснение» этим артефактом "
                     "НЕ СНЯТА (артефакт до ADR-990)")
    elif axis.get("status") != "measured":
        axis_unmeasured = (f"ось ADR-990 «о том ли ходе объяснение» НЕ ИЗМЕРЕНА: "
                           f"{axis.get('reason') or 'причина не названа'}")
    else:
        days = observed(axis, "days", kind=dict)
        hold_moved = observed_number(days, DAY_HOLD_WHILE_BOOK_MOVED) if days is not None else None
        different = observed_number(days, DAY_DIFFERENT_MOVE) if days is not None else None
        with_moves = observed_number(axis, "days_with_executed_moves")
        if hold_moved is None or different is None or with_moves is None:
            axis_unmeasured = ("ось ADR-990: счёт дней не прочитан из раздела "
                               "`executed_move` — «о том ли ходе» НЕ ИЗМЕРЕНО")
        elif hold_moved or different:
            wrong_move.append(
                f"из {int(with_moves)} дней, когда книга исполняла ход, объяснение "
                f"владельцу в {int(hold_moved)} говорило HOLD, в {int(different)} "
                f"описывало другой ход — фраза объясняет решение ТЕНИ, а не ход книги")

    if silent or tokens or wrong_move:
        parts = []
        if silent:
            parts.append("фраза владельцу не произносит названные им факты — "
                         + "; ".join(silent))
        if tokens:
            parts.append("во фразе стои́т форма, названная владельцем плохой "
                         "(внутренний токен вместо фразы) — " + "; ".join(tokens))
        parts.extend(wrong_move)
        reason = ". ".join(parts) + axis_note
        if axis_unmeasured:
            reason += ". " + axis_unmeasured
        return {"status": CRITERION_NOT_SATISFIED, "reason": reason,
                "books_judged": len(with_rec)}
    if unread:
        return {"status": CRITERION_UNMEASURED,
                "reason": ("у части книг с recommendation счёт не прочитан: "
                           + "; ".join(unread))}
    if axis_unmeasured:
        return {"status": CRITERION_UNMEASURED,
                "reason": (f"восемь фактов произнесены у каждой из {len(with_rec)} книг, "
                           f"но {axis_unmeasured} — конъюнкция с неизвестным членом "
                           f"неизвестна")}
    return {"status": CRITERION_SATISFIED,
            "reason": (f"у каждой из {len(with_rec)} книг с recommendation "
                       f"произнесены все {total:.0f} фактов владельца, и формы, "
                       f"названной им плохой, во фразе нет"
                       + (", а в дни исполненных ходов фраза говорила о них"
                          if not axis_note and not axis_unmeasured else "")
                       + axis_note),
            "books_judged": len(with_rec)}

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
        obs = (observed(cost_evidence, "observed_gas", kind=dict) or {}).get("total_usd")
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
    values = [abs(observed_number(l, "delta_usd") or 0.0) for l in legs
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


# ───────────── контрапункты ADR-990: трим и стадия во фразе ─────────────────
#
# Это НЕ девятый и десятый факт владельца — список OWNER_FACTS его и не растёт.
# Это две величины, появившиеся в записи решения ПОСЛЕ его примера (трим
# ADR-850 с 28.10, словарь стадии ADR-986), от которых зависит, о каком ходе
# фраза вообще говорит: урезанный до k ход — другой ход, а запись тени —
# другая стадия, чем исполнение. Исходы те же четыре, и считаются они ОТДЕЛЬНО
# от восьми.

def _axis_fact(key: str, wording: str, outcome: str, detail: str, *,
               source: str = "", evidence: Any = None) -> dict:
    return {"fact": key, "owner_wording": wording, "outcome": outcome,
            "detail": detail, "source": source, "evidence": evidence}


_TRIM_WORDING = "ход урезан до k от предложенного (ADR-850; §41/§42 — ADR-987/988)"
_STAGE_WORDING = "стадия/взвод решения (§40 — ADR-986): тень или исполнение"


def _probe_trim(text: str, rec: dict) -> dict:
    """Назван ли во фразе ТРИМ: что ход урезан до k и от какой суммы.

    Запись тени с 28.10 несёт ``admissible_trim`` (ADR-850): ``k``,
    ``target_before``/``target_after``, ``cost.full_turnover_usd``,
    ``damper_reason``. Ноги хода и его стоимость во фразе — УЖЕ урезанные;
    если k < 1 и фраза не называет ни k, ни полной суммы, владелец читает
    стоимость и окупаемость ДРУГОГО хода, чем тот, что советник оптимизировал,
    и не узнаёт, что дорогим его сделал сам трим (запись это говорит
    дословно: «трим дороже на +N бп за доллар хода»).
    """
    trim = rec.get(TRIM_RECORD_KEY)
    if not isinstance(trim, dict):
        return _axis_fact("trim", _TRIM_WORDING, ABSENT,
                          "записи трима ADR-850 (`admissible_trim`) в записи решения "
                          "нет — урезан ли ход, из записи не узнать",
                          source="allocation_rationale_history:" + TRIM_RECORD_KEY)
    k = observed_number(trim, "k")
    if k is None:
        return _axis_fact("trim", _TRIM_WORDING, UNCHECKED,
                          "запись трима есть, но `k` в ней не число — урезан ли "
                          "ход, НЕ ИЗМЕРЕНО",
                          source="allocation_rationale_history:" + TRIM_RECORD_KEY)
    cost = observed(trim, "cost", kind=dict)
    full = observed_number(cost, "full_turnover_usd") if cost is not None else None
    trimmed = observed_number(cost, "final_turnover_usd") if cost is not None else None
    if k >= 1.0:
        return _axis_fact("trim", _TRIM_WORDING, UNCHECKED,
                          "ход не урезан (k = 1) — объяснять нечего",
                          source="allocation_rationale_history:" + TRIM_RECORD_KEY,
                          evidence={"k": k})
    # Число, совпадающее с ДРУГОЙ величиной той же записи, свидетельством не
    # является: 12.11 полная сумма предложения ($40,000) равнялась позиции
    # «держит compound_v3 ($40,000)», и поиск по значению объявил бы трим
    # произнесённым. Коллизия выключает денежный путь — остаётся только k.
    others: list[float] = []
    for container in (rec.get("current_positions"), rec.get("target_positions")):
        if isinstance(container, dict):
            others += [abs(float(v)) for v in container.values() if isinstance(v, (int, float))]
    others += [abs(float(l.get("delta_usd"))) for l in (rec.get("legs") or [])
               if isinstance(l.get("delta_usd"), (int, float))]
    others += [abs(float(rec[f])) for f in ("turnover_usd", "cost_usd")
               if isinstance(rec.get(f), (int, float))]
    collides = full is not None and any(abs(full - o) <= 0.01 for o in others)
    values_usd = [full] if (full is not None and not collides) else []
    hit = _speaks(text, values_usd, "usd") if values_usd else None
    if hit is None:
        for r in (f"{k * 100:.0f}", f"{k * 100:.1f}", f"{k:.2f}", f"{k:.3f}"):
            found = _find_number(text, r)
            if found is not None:
                hit = {"value": k, "rendering": r, "matched": found}
                break
    named = (f"k = {k:.3f}"
             + (f", предложено ${full:,.0f}" if full is not None else "")
             + (" (совпадает с другой величиной записи — числом не свидетельствует)"
                if collides else "")
             + (f", объясняется ${trimmed:,.0f}" if trimmed is not None else "")
             + (f", демпфер {trim.get('damper_reason')}" if trim.get("damper_reason") else ""))
    if hit:
        return _axis_fact("trim", _TRIM_WORDING, SPOKEN,
                          f"трим произнесён ({named}): {hit['matched']}",
                          source="allocation_rationale_history:" + TRIM_RECORD_KEY,
                          evidence=dict(hit, k=k))
    return _axis_fact("trim", _TRIM_WORDING, SILENT,
                      f"ход урезан ({named}), и это лежит в ТОЙ ЖЕ записи, из которой "
                      f"построена фраза, — но фраза не называет ни k, ни полной суммы: "
                      f"владелец читает стоимость и окупаемость урезанного хода как "
                      f"стоимость предложения",
                      source="allocation_rationale_history:" + TRIM_RECORD_KEY,
                      evidence={"k": k, "full_turnover_usd": full,
                                "final_turnover_usd": trimmed,
                                "damper_reason": trim.get("damper_reason")})


def _probe_stage(text: str, rec: dict,
                 stage_fields: Optional[tuple[str, ...]]) -> dict:
    """Названа ли во фразе СТАДИЯ решения — тень это или исполнение.

    Словарь полей стадии ввозится у ЕДИНСТВЕННОГО владельца
    (`release_stage_census.STAGE_RECORD_FIELDS`, ADR-986), не копией. Словаря
    нет ⇒ третий исход. Поле ``mode`` стадией НЕ является: это режим книги
    (paper/live), а не ступень взвода советника — ADR-986 § словарь.
    """
    if stage_fields is None:
        return _axis_fact("stage", _STAGE_WORDING, UNCHECKED,
                          "словарь полей стадии (release_stage_census."
                          "STAGE_RECORD_FIELDS) не ввезён — НЕ ИЗМЕРЕНО",
                          source="spa_core/analytics/release_stage_census.py")
    carried = {f: rec.get(f) for f in stage_fields if f in rec}
    mode = rec.get("mode")
    if not carried:
        return _axis_fact("stage", _STAGE_WORDING, ABSENT,
                          "ни одно поле стадии (" + ", ".join(stage_fields) + ") в "
                          "записи решения нет — фраза не может назвать стадию, "
                          "которой запись не несёт (ADR-986: 0 носителей)"
                          + (f"; `mode={mode}` рядом есть, но это режим книги, "
                             f"а не стадия советника" if mode is not None else ""),
                          source="allocation_rationale_history",
                          evidence={"mode": mode})
    low = text.lower()
    for field, value in carried.items():
        if isinstance(value, str) and value and value.lower() in low:
            return _axis_fact("stage", _STAGE_WORDING, SPOKEN,
                              f"стадия произнесена: {field}={value}",
                              source="allocation_rationale_history:" + field,
                              evidence={field: value})
        if isinstance(value, bool):
            word = "взведён" if value else "не взведён"
            if word in low:
                return _axis_fact("stage", _STAGE_WORDING, SPOKEN,
                                  f"взвод произнесён: {field}={value} → «{word}»",
                                  source="allocation_rationale_history:" + field,
                                  evidence={field: value})
    named = ", ".join(f"{f}={v}" for f, v in carried.items())
    return _axis_fact("stage", _STAGE_WORDING, SILENT,
                      f"стадия записана ({named}), но во фразу не попала",
                      source="allocation_rationale_history:" + ",".join(carried),
                      evidence=carried)


# ──────────── ось ADR-990: объяснение против исполненного хода ─────────────

def _day_of(ts: Any) -> Optional[str]:
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None


def moves_by_day(trail_rows: list[dict]) -> dict[str, list[dict]]:
    """События ``trade_executed`` трейла, сгруппированные по дню."""
    out: dict[str, list[dict]] = {}
    for r in trail_rows:
        if r.get("event_type") != "trade_executed":
            continue
        day = _day_of(r.get("timestamp"))
        if day is None:
            continue
        out.setdefault(day, []).append(r)
    return out


def book_as_of(day: str, by_day: dict[str, list[dict]]) -> Optional[dict]:
    """Книга трейла на конец дня: ``to_allocation`` последнего хода не позже дня.
    ``None`` — хода до этого дня трейл не несёт (книга НЕ ИЗМЕРЕНА, а не пуста)."""
    prior = sorted(d for d in by_day if d <= day)
    if not prior:
        return None
    last = by_day[prior[-1]][-1]
    book = (last.get("data") or {}).get("to_allocation")
    return book if isinstance(book, dict) else None


def explained_vs_executed_day(rec: dict, day_moves: list[dict]) -> dict:
    """Один день: о том ли ходе фраза, что книга исполнила.

    Пять исходов (инв. #17):
    * ``consistent`` — HOLD и ход не исполнен · либо ход советника равен
      исполненной книге с точностью до цента;
    * ``hold_while_book_moved`` — фраза говорила HOLD, книга переложила деньги;
    * ``move_not_executed`` — фраза советовала ход, книга не двигалась;
    * ``different_move`` — фраза советовала ход, исполнено другое;
    * ``unmeasured`` — вердикт не строка / цель не словарь — сравнение не поставлено.
    """
    from spa_core.monitoring.decision_audit_trail import _books_equal
    verdict = rec.get("verdict")
    date = rec.get("cycle_date")
    legs = rec.get("legs") or []
    executed_n = len(day_moves)
    diffs = [observed_number(observed(m, "data", kind=dict) or {}, "diff_usd") for m in day_moves]
    diff_sum = sum(d for d in diffs if d is not None) if any(d is not None for d in diffs) else None
    base = {"date": date, "verdict": verdict, "legs": len(legs),
            "executed_moves": executed_n, "executed_diff_usd": diff_sum}
    if not isinstance(verdict, str) or not verdict:
        return dict(base, status=DAY_UNMEASURED,
                    detail="у записи тени нет вердикта — сравнивать с исполненным нечего")
    if verdict.upper() in HOLD_VERDICTS:
        if executed_n == 0:
            return dict(base, status=DAY_CONSISTENT,
                        detail="фраза говорила HOLD, и книга не двигалась")
        return dict(base, status=DAY_HOLD_WHILE_BOOK_MOVED,
                    detail=(f"фраза говорила HOLD, а книга исполнила {executed_n} ход(а) "
                            + (f"на ${diff_sum:,.2f}" if diff_sum is not None
                               else "(сумма не записана)")))
    if executed_n == 0:
        return dict(base, status=DAY_MOVE_NOT_EXECUTED,
                    detail=f"фраза советовала ход ({verdict}), книга не двигалась")
    target = rec.get("target_positions")
    executed_book = (day_moves[-1].get("data") or {}).get("to_allocation")
    if not isinstance(target, dict) or not isinstance(executed_book, dict):
        return dict(base, status=DAY_UNMEASURED,
                    detail="цель советника или исполненная книга не словарь — сравнение не поставлено")
    eq = _books_equal(target, executed_book)
    if eq is None:
        return dict(base, status=DAY_UNMEASURED,
                    detail="в цели или в исполненной книге не число — сравнение не поставлено")
    if eq:
        return dict(base, status=DAY_CONSISTENT,
                    detail="ход советника равен исполненной книге")
    return dict(base, status=DAY_DIFFERENT_MOVE,
                detail="фраза советовала один ход, книга исполнила другой")


def held_book_vs_trail(rec: dict, trail_book: Optional[dict]) -> dict:
    """«Держит: …» во фразе — та ли книга, что у трейла на этот день."""
    from spa_core.monitoring.decision_audit_trail import _books_equal
    held = rec.get("current_positions")
    if trail_book is None:
        return {"status": HELD_UNMEASURED,
                "detail": "трейл не несёт хода до этого дня — книга трейла НЕ ИЗМЕРЕНА"}
    if not isinstance(held, dict):
        return {"status": HELD_UNMEASURED,
                "detail": "запись тени не несёт `current_positions`"}
    eq = _books_equal(trail_book, held)
    if eq is None:
        return {"status": HELD_UNMEASURED, "detail": "в книге не число — сравнение не поставлено"}
    if eq:
        return {"status": HELD_MATCHES, "detail": "держимая книга фразы равна книге трейла"}
    diff = {p for p in set(trail_book) | set(held)
            if abs(float(trail_book.get(p, 0.0) or 0.0) - float(held.get(p, 0.0) or 0.0)) > 0.01}
    return {"status": HELD_DIFFERS, "positions_differing": len(diff),
            "detail": (f"«держит» во фразе описывает книгу, которой у трейла в этот день "
                       f"не было: расходятся {len(diff)} позиц.")}


def explained_vs_executed(records: list[dict], trail_rows: Optional[list[dict]]) -> dict:
    """Ось ADR-990 по всей истории тени ОДНОЙ книги против трейла.

    Чистая функция. ``trail_rows is None`` — трейла нет ⇒ ``unmeasured``.
    Население — ДНИ записей тени; дни трейла вне истории тени не судятся
    (о них фразы не было). Худший день — максимум исполненной суммы среди
    ``hold_while_book_moved``; «не измерено» в выбор не участвует.
    """
    if trail_rows is None:
        return {"status": "unmeasured",
                "reason": f"трейл {TRAIL_NAME} в каталоге состояния не прочитан — "
                          f"о том ли ходе фраза, сравнить нечем"}
    if not records:
        return {"status": "unmeasured",
                "reason": "история тени пуста — ни одной фразы, которую можно судить"}
    by_day = moves_by_day(trail_rows)
    days = {s: 0 for s in DAY_OUTCOMES}
    held = {s: 0 for s in (HELD_MATCHES, HELD_DIFFERS, HELD_UNMEASURED)}
    held_differs_span: list[str] = []
    worst: Optional[dict] = None
    per_day: list[dict] = []
    for rec in records:
        date = rec.get("cycle_date")
        day_moves = by_day.get(date, []) if isinstance(date, str) else []
        d = explained_vs_executed_day(rec, day_moves)
        h = held_book_vs_trail(rec, book_as_of(date, by_day) if isinstance(date, str) else None)
        days[d["status"]] += 1
        held[h["status"]] += 1
        if h["status"] == HELD_DIFFERS and isinstance(date, str):
            held_differs_span.append(date)
        if d["status"] == DAY_HOLD_WHILE_BOOK_MOVED:
            cur = observed_number(d, "executed_diff_usd")
            best = observed_number(worst, "executed_diff_usd") if worst is not None else None
            if cur is not None and (best is None or cur > best):
                worst = {"date": date, "executed_diff_usd": cur,
                         "executed_moves": d["executed_moves"], "legs_in_phrase": d["legs"]}
        if d["status"] != DAY_CONSISTENT or h["status"] != HELD_MATCHES:
            per_day.append({**d, "held": h})
    latest = explained_vs_executed_day(records[-1], by_day.get(str(records[-1].get("cycle_date")), []))
    latest_held = held_book_vs_trail(records[-1], book_as_of(str(records[-1].get("cycle_date")), by_day))
    return {
        "status": "measured",
        "trail_moves_total": sum(len(v) for v in by_day.values()),
        "trail_move_days_total": len(by_day),
        "shadow_days": len(records),
        "shadow_span": [records[0].get("cycle_date"), records[-1].get("cycle_date")],
        "days_with_executed_moves": sum(1 for r in records
                                        if isinstance(r.get("cycle_date"), str)
                                        and r.get("cycle_date") in by_day),
        "days": days,
        "held_book": held,
        "held_differs_span": ([held_differs_span[0], held_differs_span[-1]]
                              if held_differs_span else None),
        "worst": worst,
        "latest": {**latest, "held": latest_held},
        "exceptions": per_day[:40],
    }


# Сцены положительного контроля оси: каждая ломает ровно одну координату.
_AXIS_CONTROL_SCENES: tuple[tuple[str, dict, list[dict], str], ...] = (
    ("hold_and_quiet", {"cycle_date": "2026-01-02", "verdict": "HOLD", "legs": []},
     [], DAY_CONSISTENT),
    ("hold_while_moved",
     {"cycle_date": "2026-01-02", "verdict": "HOLD", "legs": []},
     [{"event_type": "trade_executed", "timestamp": "2026-01-02T08:00:00+00:00",
       "data": {"diff_usd": 40000.0, "to_allocation": {"aave": 60000.0}}}],
     DAY_HOLD_WHILE_BOOK_MOVED),
    ("move_matches",
     {"cycle_date": "2026-01-02", "verdict": "MOVE",
      "legs": [{"protocol": "morpho", "direction": "increase", "delta_usd": 12000.0}],
      "target_positions": {"aave": 28000.0, "morpho": 12000.0}},
     [{"event_type": "trade_executed", "timestamp": "2026-01-02T08:00:00+00:00",
       "data": {"diff_usd": 24000.0, "to_allocation": {"aave": 28000.0, "morpho": 12000.0}}}],
     DAY_CONSISTENT),
    ("move_differs",
     {"cycle_date": "2026-01-02", "verdict": "MOVE",
      "legs": [{"protocol": "morpho", "direction": "increase", "delta_usd": 12000.0}],
      "target_positions": {"aave": 28000.0, "morpho": 12000.0}},
     [{"event_type": "trade_executed", "timestamp": "2026-01-02T08:00:00+00:00",
       "data": {"diff_usd": 6000.0, "to_allocation": {"aave": 37000.0, "morpho": 3000.0}}}],
     DAY_DIFFERENT_MOVE),
    ("move_not_executed",
     {"cycle_date": "2026-01-02", "verdict": "MOVE",
      "legs": [{"protocol": "morpho", "direction": "increase", "delta_usd": 12000.0}],
      "target_positions": {"aave": 28000.0, "morpho": 12000.0}},
     [], DAY_MOVE_NOT_EXECUTED),
)

CONTROL_TRIM_RECORD: dict = {
    TRIM_RECORD_KEY: {"k": 0.272727, "damper_reason": "weekly_turnover_budget",
                      "cost": {"full_turnover_usd": 55000.0, "final_turnover_usd": 15000.0}},
}
CONTROL_TRIM_TEXT = "Ход урезан до 27% от предложенного ($15,000 из $55,000)."
CONTROL_STAGE_RECORD: dict = {"stage": "shadow"}
CONTROL_STAGE_TEXT = "Это решение тени (shadow): его никто не исполняет."


def run_axis_control() -> dict:
    """Положительный контроль оси ADR-990 и двух контрапунктов.

    Пять сцен исполненного хода обязаны дать ПЯТЬ названных исходов; трим и
    стадия, произнесённые дословно, обязаны выйти ``SPOKEN``. Не вышли ⇒ ось
    НЕ ИЗМЕРЕНА: детектор, не увидевший исход там, где он заведомо есть, не
    вправе утверждать о живых днях ничего.
    """
    failed: list[str] = []
    for name, rec, moves, want in _AXIS_CONTROL_SCENES:
        got = explained_vs_executed_day(rec, moves)["status"]
        if got != want:
            failed.append(f"{name}: ждали {want}, получили {got}")
    if _probe_trim(CONTROL_TRIM_TEXT, CONTROL_TRIM_RECORD)["outcome"] != SPOKEN:
        failed.append("trim_spoken: трим, названный дословно, не увиден")
    if _probe_stage(CONTROL_STAGE_TEXT, CONTROL_STAGE_RECORD, ("stage",))["outcome"] != SPOKEN:
        failed.append("stage_spoken: стадия, названная дословно, не увидена")
    return {"passed": not failed, "scenes": len(_AXIS_CONTROL_SCENES) + 2,
            "failed": failed,
            "reason": "" if not failed else "контроль оси не пройден: " + "; ".join(failed)}


def _stage_fields() -> Optional[tuple[str, ...]]:
    """Словарь стадии — у ЕДИНСТВЕННОГО владельца (ADR-986); нет ⇒ None."""
    try:
        from spa_core.analytics.release_stage_census import STAGE_RECORD_FIELDS
    except Exception:  # noqa: BLE001 — словарь не ввезён ⇒ третий исход
        return None
    return tuple(str(f) for f in STAGE_RECORD_FIELDS)


# ─────────────────────────────── замер одной книги ──────────────────────────

def measure_brief(brief: dict, rec: Optional[dict], *,
                  marginal: Optional[dict] = None,
                  cost_evidence: Optional[dict] = None,
                  risk_check: Optional[dict] = None,
                  params_fields: Optional[set[str]] = None,
                  stage_fields: Optional[tuple[str, ...]] = None) -> dict:
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
            "trim": _axis_fact("trim", _TRIM_WORDING, UNCHECKED, f"объяснения нет: {reason}"),
            "stage": _axis_fact("stage", _STAGE_WORDING, UNCHECKED, f"объяснения нет: {reason}"),
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
    # Контрапункты ADR-990 — ОТДЕЛЬНО от восьми фактов владельца: трим судится
    # только у книги с ходом (урезать нечего, если хода нет), стадия — у любой.
    trim = (_probe_trim(text, rec) if has_legs
            else _axis_fact("trim", _TRIM_WORDING, UNCHECKED,
                            "у книги нет предложенного хода — урезать нечего"))
    return {
        "text": text,
        "facts": facts,
        "machine_tokens": _machine_tokens(text, _known_names(rec)),
        "has_recommendation": has_legs,
        "trim": trim,
        "stage": _probe_stage(text, rec, stage_fields),
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
    stage_fields = _stage_fields()
    # Ось ADR-990: трейл читается ТОЙ ЖЕ дверью, что у §43 (ADR-989), из
    # каталога состояния — не из корня дерева (герметичность, см. _load_sibling).
    from spa_core.monitoring.decision_audit_trail import _read_jsonl
    trail = _read_jsonl(str(ddir / TRAIL_NAME))
    trail_rows = trail[0] if trail is not None else None
    histories: dict[str, list[dict]] = {}

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
                histories[key] = list(records)
                rec = records[-1] if records else None
            except Exception as exc:  # noqa: BLE001
                rec = None
                brief = {"available": False,
                         "reason": f"журнал решений не прочитан: {exc}"}
        got = measure_brief(brief, rec, marginal=marginal,
                            cost_evidence=cost_evidence, risk_check=risk_check,
                            params_fields=params_fields, stage_fields=stage_fields)
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
            # Замер книги, не вернувший раздел (чужая/прежняя мерка), — это
            # «НЕ ИЗМЕРЕНО» с причиной, а не отказ всего отчёта и не «чисто».
            "trim": observed(got, "trim", kind=dict) or _axis_fact(
                "trim", _TRIM_WORDING, UNCHECKED, "замер книги не вернул раздел `trim`"),
            "stage": observed(got, "stage", kind=dict) or _axis_fact(
                "stage", _STAGE_WORDING, UNCHECKED, "замер книги не вернул раздел `stage`"),
        }
        books.append(entry)
        if subject is None and got["has_recommendation"]:
            subject = entry

    # Ось ADR-990 — по книге, которую трейл НЕСЁТ: трейл цикла пишет только
    # живую книгу (conservative, book_id=None); у рукавов трейла нет, и о них
    # ось молчит честно, а не нулём.
    axis_control = run_axis_control()
    if not axis_control["passed"]:
        executed_move = {"status": "unmeasured", "reason": axis_control["reason"]}
    else:
        executed_move = explained_vs_executed(histories.get("conservative") or [], trail_rows)
    executed_move = {"provenance": EXECUTED_AXIS_PROVENANCE, "book": "conservative",
                     "trail": str(Path("data") / TRAIL_NAME), "control": axis_control,
                     **executed_move}

    consumers = _brief_consumers(root)
    findings, unchecked = _findings(books, subject, control, consumers,
                                    executed_move=executed_move)
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
        "executed_move": executed_move,
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
    # Вердикт о критерии владельца кладётся в САМ отчёт: иначе читателю пришлось
    # бы вывести его из чисел, то есть завести ВТОРУЮ копию правила (ADR-220).
    doc["criterion"] = criterion_verdict(doc)
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
                # …и КОПИЯ измерителя в ЧУЖОМ дереве — тоже не читатель. Замер
                # #1107: прибор, запущенный из рабочего дерева с `--root <прод>`,
                # нашёл по тому же относительному пути прод-копию самого себя и
                # записал её читателем объяснения. Личность здесь — путь в
                # дереве, а не инод файла.
                if rel.replace(os.sep, "/") == SELF_REL:
                    continue
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
              consumers: list[str],
              executed_move: Optional[dict] = None) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    unchecked: list[str] = []
    # Ось ADR-990 судится ДО вопроса о составе фразы: она не про recommendation
    # сегодняшнего дня, а про все дни тени, и книга без хода её не гасит.
    _axis_findings(executed_move, findings, unchecked)

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
    # Контрапункты ADR-990 у книги с ходом: трим и стадия.
    # Раздела нет (прежняя мерка) — это «не измерено», и находки о нём нет;
    # пустой словарь выдал бы отсутствие раздела за «трим не урезал».
    trim = observed(subject, "trim", kind=dict) or {"outcome": UNCHECKED}
    if trim.get("outcome") == SILENT:
        ev = observed(trim, "evidence", kind=dict)
        k = observed_number(ev, "k") if ev is not None else None
        findings.append({
            "severity": "WARN",
            "code": "trim_unspoken",
            "message": (f"книга «{subject['book']}»: ход урезан демпфером ADR-850 до "
                        f"k = {k:.3f} от предложенного" if k is not None else
                        f"книга «{subject['book']}»: ход урезан демпфером ADR-850")
                       + " — фраза объясняет стоимость и окупаемость УРЕЗАННОГО хода "
                         "и не называет ни k, ни полной суммы; владелец читает цену "
                         "трима как цену предложения",
        })
    elif trim.get("outcome") == ABSENT:
        findings.append({
            "severity": "INFO",
            "code": "trim_not_recorded",
            "message": (f"книга «{subject['book']}»: запись решения не несёт "
                        f"`{TRIM_RECORD_KEY}` — урезался ли ход, из записи не узнать"),
        })
    stage = observed(subject, "stage", kind=dict) or {"outcome": UNCHECKED}
    if stage.get("outcome") in (SILENT, ABSENT):
        findings.append({
            "severity": "WARN",
            "code": "stage_unspoken" if stage.get("outcome") == SILENT else "stage_not_recorded",
            "message": (f"книга «{subject['book']}»: фраза не говорит владельцу, что это "
                        f"решение ТЕНИ, которое никто не исполняет — {stage.get('detail')}"),
        })
    elif stage.get("outcome") == UNCHECKED and str(stage.get("source") or "").endswith("release_stage_census.py"):
        unchecked.append("стадия во фразе: " + str(stage.get("detail")))
    for b in books:
        if not b["has_recommendation"]:
            unchecked.append(
                f"книга «{b['book']}»: предложенного хода нет — объяснять "
                f"нечего (это не провал §44)")
    return findings, unchecked


def _axis_findings(axis: Optional[dict], findings: list[dict], unchecked: list[str]) -> None:
    """Находки оси ADR-990 — из уже снятого раздела, ничего не пересчитывая."""
    if axis is None:
        return
    if axis.get("status") != "measured":
        unchecked.append("о том ли ходе объяснение (ось ADR-990) — НЕ ИЗМЕРЕНО: "
                         + str(axis.get("reason") or "причина не названа"))
        return
    days = observed(axis, "days", kind=dict)
    if days is None:
        unchecked.append("о том ли ходе объяснение (ось ADR-990): раздел `days` не прочитан "
                         "— счёт дней НЕ ИЗМЕРЕН")
        return
    with_moves = observed_number(axis, "days_with_executed_moves")
    hold_moved = observed_number(days, DAY_HOLD_WHILE_BOOK_MOVED)
    different = observed_number(days, DAY_DIFFERENT_MOVE)
    not_exec = observed_number(days, DAY_MOVE_NOT_EXECUTED)
    if hold_moved:
        worst = observed(axis, "worst", kind=dict) or {}
        w = observed_number(worst, "executed_diff_usd") if worst else None
        findings.append({
            "severity": "CRITICAL",
            "code": "explanation_says_hold_while_book_moved",
            "message": (f"из {int(with_moves or 0)} дней тени, когда книга исполняла ход, "
                        f"объяснение владельцу в {int(hold_moved)} говорило HOLD — фраза "
                        f"строится из записи ТЕНИ (ADR-060 shadow), а деньги двигает цикл; "
                        f"худший день {worst.get('date')}: книга переложила "
                        + (f"${w:,.2f}" if w is not None else "сумму без записи")
                        + f" за {worst.get('executed_moves')} ход(а), во фразе ног "
                          f"{worst.get('legs_in_phrase')}"),
        })
    if different:
        findings.append({
            "severity": "CRITICAL",
            "code": "explanation_describes_a_different_move",
            "message": (f"в {int(different)} дн. фраза советовала один ход, а книга "
                        f"исполнила другой"),
        })
    if not_exec:
        findings.append({
            "severity": "WARN",
            "code": "explained_move_not_executed",
            "message": (f"в {int(not_exec)} дн. фраза советовала ход, которого книга не "
                        f"исполнила — объяснение о решении, которого не было"),
        })
    held = observed(axis, "held_book", kind=dict)
    differs = observed_number(held, HELD_DIFFERS) if held is not None else None
    if differs:
        span = observed(axis, "held_differs_span", kind=list) or [None, None]
        findings.append({
            "severity": "WARN",
            "code": "explained_held_book_never_existed",
            "message": (f"в {int(differs)} из {axis.get('shadow_days')} записей тени «держит» "
                        f"описывает книгу, которой у трейла в тот день не было "
                        f"({span[0]} … {span[1]}) — владелец читал позиции, которых "
                        f"трек не держал"),
        })
    latest = observed(axis, "latest", kind=dict)
    latest_held = observed(latest, "held", kind=dict) if latest is not None else None
    if latest is not None and latest_held is not None \
            and latest.get("status") == DAY_CONSISTENT and latest_held.get("status") == HELD_MATCHES:
        findings.append({
            "severity": "INFO",
            "code": "latest_explanation_is_about_the_executed_book",
            "message": (f"сегодня ({latest.get('date')}): фраза и книга согласны — "
                        f"{latest.get('detail')}; держимая книга равна книге трейла"),
        })


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
    ax = observed(doc, "executed_move", kind=dict)
    if ax is not None and ax.get("status") == "measured":
        d = observed(ax, "days", kind=dict) or {}
        h = observed(ax, "held_book", kind=dict) or {}
        print(f"  о том ли ходе (ADR-990): дней тени {ax.get('shadow_days')}, с исполненным "
              f"ходом {ax.get('days_with_executed_moves')}, из них HOLD во фразе "
              f"{d.get(DAY_HOLD_WHILE_BOOK_MOVED)} · другой ход {d.get(DAY_DIFFERENT_MOVE)} · "
              f"держимая книга расходится с трейлом у {h.get(HELD_DIFFERS)} · сегодня: "
              f"{(ax.get('latest') or {}).get('status')}")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
