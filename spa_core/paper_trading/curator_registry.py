"""Кто управляет протоколом — разметка как ДАННЫЕ, а не как догадка в коде.

**Решение владельца 2026-08-25 (вариант Б)** по карточке «Потолок концентрации не
видит общего куратора — половина книги может лечь под одну команду», ADR-135.

Куратор — команда, которая решает, какие залоги хранилище принимает, под какие
оракулы и с каким запасом. Код Morpho неизменяемый, параметры задаёт живой
человек, поэтому куратор и есть главный риск такого хранилища. Потолок
концентрации считает деньги ПО ИМЕНИ ПРОТОКОЛА и этой связи не видит: замер
2026-08-18 показал, что три разных имени под одной командой дают **50 % книги**
при полностью зелёном отчёте.

Владелец выбрал НЕ вводить потолок поверх пустой разметки: «вводить потолок,
где известны 2 протокола из 36, — значит получить зелёную галочку, которая
ничего не гарантирует». Сначала данные, потом гейт.

Что этот модуль ДЕЛАЕТ: называет по каждому протоколу реестра либо команду с
источником и датой проверки, либо честное «не знаем».
Что он НЕ делает: не гейтит, не двигает капитал, порогов RiskPolicy не касается.

## Три исхода, а не два (инвариант #17)

``confidence`` различает то, что нельзя сваливать в одну кучу:

* ``pinned``  — куратор проверен И адаптер закреплён за конкретным хранилищем;
* ``derived`` — имя ВЫВЕДЕНО из поведения адаптера, а не проверено. Может
  смениться без единого изменения в нашем коде;
* ``unknown`` — не проверяли, источника нет. Это НЕ «куратора нет».

Разница между ``derived`` и ``pinned`` здесь не теоретическая.
``morpho_blue_base`` не закреплён за хранилищем: ``_find_best_usdc_pool``
(``morpho_blue_base_adapter.py``) каждый раз берёт **пул с максимальным TVL**
среди USDC-хранилищ Morpho на Base. Замер карточки 2026-08-18: крупнейшее —
Steakhouse ($587 млн), следом Gauntlet ($428 млн), другая команда. Поменяются
местами — наша метка станет неверной, и сказать об этом будет некому.
Закрепление за конкретным хранилищем — отдельная задача
(``inbox-zakrepit-morpho-blue-base-za-konkretnym``): проверить это можно
только on-chain, а из контейнера живой сети нет, и выдумывать адрес хранилища
запрещено (`docs/37`).
"""
from __future__ import annotations

from typing import Dict, List, Optional

#: Куратор проверен И адаптер закреплён за конкретным хранилищем.
PINNED = "pinned"
#: Имя выведено из поведения адаптера, а не проверено. Может смениться молча.
DERIVED = "derived"
#: Не проверяли / источника нет. НЕ означает «куратора нет».
UNKNOWN = "unknown"


class CuratorEntry:
    """Одна строка разметки. Неизменяемая, без зависимостей."""

    __slots__ = ("protocol", "curator", "confidence", "source", "verified_at", "note")

    def __init__(self, protocol: str, curator: Optional[str], confidence: str,
                 source: Optional[str], verified_at: Optional[str],
                 note: str = "") -> None:
        self.protocol = protocol
        self.curator = curator
        self.confidence = confidence
        self.source = source
        self.verified_at = verified_at
        self.note = note

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "protocol": self.protocol,
            "curator": self.curator,
            "confidence": self.confidence,
            "source": self.source,
            "verified_at": self.verified_at,
            "note": self.note or None,
        }


# Причина, одна на всех неизвестных: у нас нет проверенного источника, и
# выдумывать его нельзя. Это честное «не знаем», а не «куратора нет».
_UNKNOWN_NOTE = (
    "куратор не проверен: проверенного источника нет, on-chain из контейнера "
    "не проверяется (инв. #17 — не измерено ≠ измерено и пусто)"
)

# ── Разметка ────────────────────────────────────────────────────────────────
# Известные записи перенесены из `concentration_analytics._CURATOR_OF` вместе с
# их происхождением; всё остальное — честное «не знаем».
_KNOWN: List[CuratorEntry] = [
    CuratorEntry(
        protocol="morpho_steakhouse",
        curator="steakhouse",
        confidence=PINNED,
        source=("spa_core/adapters/morpho_steakhouse_adapter.py (хранилище STEAKUSDC, "
                "Ethereum) + data/protocol_cards/examples/morpho.protocol.md "
                "(evidence L2, «реальный риск per-vault (curator)»)"),
        verified_at="2026-08-05",
        note="адаптер адресует одно конкретное хранилище — метка не плавает",
    ),
    CuratorEntry(
        protocol="morpho_blue_base",
        curator="steakhouse",
        confidence=DERIVED,
        source=("spa_core/adapters/morpho_blue_base_adapter.py::_find_best_usdc_pool — "
                "адаптер берёт USDC-хранилище Morpho на Base с МАКСИМАЛЬНЫМ TVL, "
                "а не закреплённое"),
        verified_at=None,
        note=("метка выведена, а не проверена: 2026-08-18 крупнейшим было Steakhouse "
              "($587 млн), следом Gauntlet ($428 млн) — другая команда; смена мест "
              "делает метку неверной молча"),
    ),
]

_KNOWN_BY_PROTOCOL: Dict[str, CuratorEntry] = {e.protocol: e for e in _KNOWN}


def _adapter_protocols() -> List[str]:
    """Имена протоколов реестра адаптеров.

    Реестр — ``ADAPTER_REGISTRY`` из ``spa_core.adapters`` (`.claude/rules/adapters.md`:
    одно имя — один объект; ``ADAPTER_METADATA`` здесь НЕ подходит, её состав
    другой). Импорт ленивый и защищённый: разметка не обязана падать вместе с
    реестром — она обязана честно сказать, что реестр не прочитан.
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception:  # noqa: BLE001 — advisory: реестр недоступен, не падаем
        return []
    names: List[str] = []
    for row in ADAPTER_REGISTRY:
        try:
            names.append(str(row[0]))
        except Exception:  # noqa: BLE001
            continue
    return names


def entry_for(protocol: str) -> CuratorEntry:
    """Строка разметки по протоколу. Неизвестный — тоже строка, а не ``None``."""
    known = _KNOWN_BY_PROTOCOL.get(protocol)
    if known is not None:
        return known
    return CuratorEntry(protocol=protocol, curator=None, confidence=UNKNOWN,
                        source=None, verified_at=None, note=_UNKNOWN_NOTE)


def registry() -> Dict[str, CuratorEntry]:
    """Разметка по ВСЕМ протоколам реестра адаптеров плюс все известные записи.

    Известная запись включается, даже если протокол выпал из реестра адаптеров:
    иначе разметка молча потеряла бы знание вместе с адаптером.
    """
    out: Dict[str, CuratorEntry] = {}
    for name in _adapter_protocols():
        out[name] = entry_for(name)
    for name, e in _KNOWN_BY_PROTOCOL.items():
        out.setdefault(name, e)
    return out


def curator_of(confidences: Optional[tuple] = None) -> Dict[str, str]:
    """Отображение ``протокол → куратор`` для метрики концентрации.

    По умолчанию включает и ``pinned``, и ``derived``: занизить концентрацию,
    выбросив выведенную метку, было бы хуже, чем показать её — при условии, что
    рядом сказано, что она выведена (это делает :func:`coverage`).
    """
    allowed = confidences if confidences is not None else (PINNED, DERIVED)
    return {name: e.curator for name, e in registry().items()
            if e.curator and e.confidence in allowed}


def coverage() -> Dict[str, object]:
    """Чего разметка НЕ знает — числом, а не на словах.

    Отчёт обязан называть размер собственного незнания: «известны 2 из 36» — это
    и есть причина, по которой владелец отказался вводить потолок сегодня.
    """
    reg = registry()
    pinned = sorted(n for n, e in reg.items() if e.confidence == PINNED)
    derived = sorted(n for n, e in reg.items() if e.confidence == DERIVED)
    unknown = sorted(n for n, e in reg.items() if e.confidence == UNKNOWN)
    return {
        "total": len(reg),
        "pinned": pinned,
        "derived": derived,
        "unknown_count": len(unknown),
        "unknown": unknown,
        "known_pct": (round(100.0 * (len(pinned) + len(derived)) / len(reg), 2)
                      if reg else 0.0),
        "gate_ready": False,
        "gate_ready_reason": (
            "потолок на куратора НЕ вводится, пока разметка покрывает "
            f"{len(pinned) + len(derived)} из {len(reg)} протоколов — решение "
            "владельца 2026-08-25, вариант Б (ADR-135): сначала данные, потом гейт"
        ),
    }
