"""Сторож «профинансирован протокол, которого нет в реестре» — остаточная дыра ADR-062.

ADR-062 ввёл кэпы по цепочкам (Base 20 %, L2 суммарно 50 %, одна цепочка 90 %).
Цепочка протокола берётся из ``data/adapter_registry.json``. Протокол, которого
в реестре нет, честно помечается как UNCHECKED — и **именно поэтому** сам ADR-062
записал остаточную дыру дословно: незарегистрированный протокол может раздуть
реальную экспозицию сверх кэпа, а правило этого не увидит. Догадываться внутри
кэп-правила («а вдруг он на Base») запрещено там же: это превратило бы отсутствие
данных в вердикт и создало вечный замок. Нужен ОТДЕЛЬНЫЙ сторож — вот он.

**Сторож НИЧЕГО не пишет и не гейтит.** Ни одного байта в ``data/``, ни одного
лимита. Он отвечает на один вопрос: *есть ли в книге деньги под протоколом, о
котором реестр молчит?* Уровень CRITICAL для монитора (так требует карточка),
но книгу он не блокирует — блокировка осталась бы за RiskPolicy, и трогать её
здесь нельзя.

Почему он читает реестр НАПРЯМУЮ, а не только ``chain_unresolved``
--------------------------------------------------------------------
Карточка предлагала более дешёвый путь: ``policy_enforcer`` уже публикует в
``portfolio_summary`` поля ``chain_unresolved`` / ``chain_unresolved_pct`` —
сторожу достаточно их прочитать. Замер 2026-08-16 показал, что этого НЕ хватает,
и оба довода измеримы, а не умозрительны:

1. **Резервная карта маскирует отсутствие в реестре.** ``_resolve_chain_map``
   после реестра подмешивает статическую ``chain_limits.get_default_chain_map()``,
   и та знает два имени, которых в реестре НЕТ: ``aave_v3_arbitrum`` и
   ``compound_v3_base``. Профинансируй любое из них — цепочка разрешится,
   ``chain_unresolved`` останется ПУСТЫМ, и сторож, читающий только это поле,
   промолчит о протоколе без записи в реестре. Второе имя — на Base, то есть
   ровно тот случай, ради которого дыру и записали.
2. **Опубликованное поле некому обновлять.** Кольцевой буфер
   ``data/policy_violations.json``, куда ``position_validator --write`` кладёт
   ``portfolio_summary``, на живом проде 16.08 лежал в ДОпрежней форме (один
   объект вместо списка записей) с отметкой 2026-06-22 — 55 суток. Сторож,
   построенный на нём, читал бы труп и молчал бы уверенно.

Поэтому источник здесь — живая книга (``paper_trading_status.json``) и живой
реестр. Вопрос «покрывает ли реестр деньги» шире, чем «разрешилась ли цепочка»:
из реестра берут не только ``chain``, но и тир, и ``per_protocol_cap``.

Fail-CLOSED
-----------
Нечитаемый реестр — это ``unchecked`` со своим голосом, а НЕ «покрыто». Ровно так
же нечитаемая книга: «не измерено» никогда не хранится как «в порядке». И
наоборот — пустой/нечитаемый реестр не объявляется «ни один протокол не покрыт»:
это был бы ложный CRITICAL на всю книгу.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

__all__ = [
    "BOOK_FILE",
    "REGISTRY_FILE",
    "RegistryCoverageVerdict",
    "check_registry_coverage",
    "STATE_COVERED",
    "STATE_GAP",
    "STATE_NO_BOOK",
    "STATE_UNCHECKED",
]

BOOK_FILE = "paper_trading_status.json"
REGISTRY_FILE = "adapter_registry.json"

STATE_COVERED = "covered"      # каждый профинансированный протокол есть в реестре
STATE_GAP = "gap"              # деньги под протоколом, которого реестр не знает
STATE_NO_BOOK = "no_book"      # книга пуста — сторожить нечего
STATE_UNCHECKED = "unchecked"  # измерить не удалось (НЕ «в порядке»)

OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"


@dataclass
class RegistryCoverageVerdict:
    """Вердикт сторожа. ``issue`` пуст ⇒ говорить не о чем."""

    state: str
    severity: str
    detail: str
    funded: list = field(default_factory=list)
    missing_from_registry: list = field(default_factory=list)
    without_chain: list = field(default_factory=list)
    uncovered_usd: float = 0.0
    uncovered_pct: Optional[float] = None
    issue: Optional[str] = None
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "severity": self.severity,
            "detail": self.detail,
            "funded": list(self.funded),
            "missing_from_registry": list(self.missing_from_registry),
            "without_chain": list(self.without_chain),
            "uncovered_usd": round(self.uncovered_usd, 2),
            "uncovered_pct": (
                None if self.uncovered_pct is None else round(self.uncovered_pct, 2)
            ),
            "notes": list(self.notes),
        }


_ABSENT = "нет файла"


def _read_json(path: Path):
    """``(payload, error)``. Разделяет «нет файла» и «файл есть, но не читается».

    Разделение принципиальное и то же, что у соседа ``cycle_lock_watch``: файла НЕТ —
    сторожить нечего (в песочнице/на свежем дереве книги просто не существует, и
    кричать об этом значит завести сторожа, который всегда красный, то есть немой).
    Файл ЕСТЬ, но не читается — за ним могут стоять деньги, и это уже «не измерено».
    """
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, _ABSENT
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _funded_positions(book: dict) -> dict:
    """Протокол → USD, только СТРОГО ПОЛОЖИТЕЛЬНЫЕ позиции.

    Карточка говорит «любой протокол с НЕНУЛЕВОЙ позицией»: нулевая строка — след
    закрытой позиции, денег под ней нет, и поднимать из-за неё CRITICAL значило бы
    приучить читателя к шуму. Мусор в значении (не число) НЕ отбрасывается молча —
    он считается профинансированным, потому что «не разобрал сумму» не означает
    «денег там нет».
    """
    out: dict = {}
    raw = book.get("current_positions") or {}
    if not isinstance(raw, dict):
        return out
    for proto, usd in raw.items():
        try:
            val = float(usd)
        except (TypeError, ValueError):
            out[str(proto)] = 0.0     # сумма неизвестна — протокол всё равно в книге
            continue
        if val > 0:
            out[str(proto)] = val
    return out


def check_registry_coverage(
    data_dir: str | Path,
    *,
    book_file: str = BOOK_FILE,
    registry_file: str = REGISTRY_FILE,
) -> RegistryCoverageVerdict:
    """Покрывает ли ``adapter_registry.json`` каждый профинансированный протокол?

    Ничего не пишет. Часов здесь нет намеренно: вопрос «есть ли запись в реестре»
    не имеет отношения к свежести — за свежесть книги отвечают другие сторожа,
    и второй ответ на чужой вопрос только размыл бы этот.
    """
    ddir = Path(data_dir)

    book, book_err = _read_json(ddir / book_file)
    if book is None and book_err == _ABSENT:
        return RegistryCoverageVerdict(
            state=STATE_NO_BOOK, severity=OK,
            detail=f"книги ({book_file}) в этом дереве нет — покрывать нечего",
        )
    if not isinstance(book, dict):
        return RegistryCoverageVerdict(
            state=STATE_UNCHECKED, severity=WARNING,
            detail=f"книга не прочитана ({book_err or 'не объект'}) — покрытие НЕ ИЗМЕРЕНО",
            issue=("registry coverage UNCHECKED: книга позиций не прочитана "
                   f"({book_err or 'не объект'}) — «не измерено» не означает «покрыто»"),
        )

    funded = _funded_positions(book)
    if not funded:
        return RegistryCoverageVerdict(
            state=STATE_NO_BOOK, severity=OK,
            detail="профинансированных позиций нет — покрывать нечего",
        )

    total_usd = sum(funded.values())
    names = sorted(funded)

    registry, reg_err = _read_json(ddir / registry_file)
    adapters = registry.get("adapters") if isinstance(registry, dict) else None
    if not isinstance(adapters, dict) or not adapters:
        # Ни в коем случае не «все протоколы не покрыты»: пустой реестр — это
        # отказ измерения, а не приговор книге.
        why = reg_err or "раздел adapters пуст или не объект"
        return RegistryCoverageVerdict(
            state=STATE_UNCHECKED, severity=WARNING, funded=names,
            detail=f"реестр адаптеров не прочитан ({why}) — покрытие НЕ ИЗМЕРЕНО",
            issue=(f"registry coverage UNCHECKED: {registry_file} не прочитан ({why}) "
                   f"— покрытие {len(names)} профинансированных протоколов не измерено"),
        )

    missing: list = []
    no_chain: list = []
    for proto in names:
        entry = adapters.get(proto)
        if not isinstance(entry, dict):
            missing.append(proto)
            continue
        chain = entry.get("chain")
        if not (isinstance(chain, str) and chain.strip()):
            no_chain.append(proto)

    uncovered = sorted(set(missing) | set(no_chain))
    if not uncovered:
        return RegistryCoverageVerdict(
            state=STATE_COVERED, severity=OK, funded=names, uncovered_pct=0.0,
            detail=(f"реестр покрывает все {len(names)} профинансированных протоколов "
                    "(запись есть, цепочка названа)"),
        )

    uncovered_usd = sum(funded.get(p, 0.0) for p in uncovered)
    uncovered_pct = (uncovered_usd / total_usd * 100.0) if total_usd > 0 else None
    pct_words = (
        "доля капитала НЕ ИЗМЕРЕНА" if uncovered_pct is None
        else f"{uncovered_pct:.1f}% капитала"
    )
    parts = []
    if missing:
        parts.append(f"нет записи в реестре: {missing}")
    if no_chain:
        parts.append(f"запись есть, цепочка не названа: {no_chain}")
    what = "; ".join(parts)

    return RegistryCoverageVerdict(
        state=STATE_GAP, severity=CRITICAL, funded=names,
        missing_from_registry=missing, without_chain=no_chain,
        uncovered_usd=uncovered_usd, uncovered_pct=uncovered_pct,
        detail=(f"деньги под протоколом, которого реестр не знает ({pct_words}): {what}"),
        issue=(f"registry coverage GAP: профинансировано {len(uncovered)} протокол(ов) "
               f"без записи о цепочке в {registry_file} ({pct_words}) — {what}; "
               "кэпы по цепочкам (ADR-062) проверены НЕ на всём капитале"),
    )
