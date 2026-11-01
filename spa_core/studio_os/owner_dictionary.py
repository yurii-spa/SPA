"""Детерминированный словарь пульта владельца (DIRECTOR-OS-UX-02, ARB 09.10, RFC-690 §4).

Зачем отдельный модуль. План работ (``docs/ROADMAP.md``) написан по-английски, а основные
экраны пульта — только по-русски. Машинный перевод на лету недетерминирован и может исказить
смысл; поэтому названия этапов переводятся ЗАКРЫТЫМ словарём: известный этап — русское
название, неизвестный — нейтральная русская подпись, а исходное название уходит в
«Технические подробности». Ничего не угадывается.

Ключ — код этапа («RM-TRUTH-01», «ARB-CONTINUITY-01» …), если он есть в начале названия,
иначе — английское название целиком (без регистра и лишних пробелов). Словарь — данные,
не логика: новый этап без строки здесь показывается нейтрально, а тест
``test_owner_view.py`` называет его поимённо, чтобы строку дописали.
"""
from __future__ import annotations

import re
from typing import Optional

# Код этапа в начале названия: «RM-TRUTH-01 · …», «ARB-CONTINUITY-01 · …».
_CODE = re.compile(r"^\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\s*(?:·|:|—|-)\s*")
_LATIN = re.compile(r"[A-Za-z]")
_CYRILLIC = re.compile(r"[А-Яа-яЁё]")

# Этапы плана: код или английское название → русское название для владельца.
ROADMAP_RU = {
    "memory & context architecture v1": "Память и контекст студии",
    "defi architecture gap audit": "Аудит разрывов в устройстве DeFi",
    "defi engine vnext": "Новое поколение DeFi-движка: три бумажных портфеля",
    "build loop / remaining workflow gaps": "Цикл сборки: оставшиеся разрывы в процессе",
    "owner remote / mission control v1": "Пульт владельца, первая версия",
    "capital allocator / portfolio cio v1 (rm-cap)": "Распределение капитала и советник по портфелю (Oracle)",
    "RM-LIVE-01": "Теневое исполнение и готовность к пилоту с реальными деньгами",
    "RM-EXPAND-01": "Расширение источников доходности и фабрика исследований",
    "RM-EVIDENCE-01": "Доказательства исследований и допуск на бумагу",
    "RM-TRUTH-01": "Сверка правды компании и восстановление пульта",
    "ARB-CONTINUITY-01": "Непрерывность архитектуры, управление и восстановление",
    "PRODUCT-TRUTH-02": "Воспроизводимая публикация и правда продукта на сайте",
    "CAPITAL-SOURCES-01": "Торговый рукав и портфель источников доходности",
    "PRODUCT-UX-01": "Опыт пользователя на сайте Earn DeFi",
    "later engines: traditional markets, volatility / options (scope decided inside rm-expand-01)":
        "Будущие движки: традиционные рынки, волатильность и опционы",
    "GOVERNANCE-UX-RECOVERY-01": "Аудит продуктового управления и пульта",
    "DIRECTOR-OS-UX-02": "Понятный пульт владельца",
    "STUDIO-OS-NEXT-01": "Следующий этап студии по плану ARB",
    "STUDIO-AUTONOMY-01": "Управление студией с телефона; агенты работают в доказанных границах",
}

UNKNOWN_STAGE = "Этап плана (название только на английском — см. подробности)"

#: «Сдано, ждёт приёмки» — НЕ «в работе» (ADR-890). ОДНА копия: её читают и пульт (``mission_control._roadmap``),
#: и генератор контекст-пакета (``memory.continuity.roadmap_view``); две копии правила уже разошлись однажды.
AWAITING_REVIEW = re.compile(r"awaiting ARB|handed to ARB|NOT ARB-accepted|ждёт приёмки|ждёт ARB", re.I)
_IN_PROGRESS = re.compile(r"\bin progress\b|в работе", re.I)


def roadmap_item_state(raw: str) -> str:
    """Состояние пункта roadmap — ОДНА функция для пульта и генератора контекста, на ОДНОМ тексте:
    заголовок пункта до первой строки шага (``- step``). Шаги и их причины состояния пункта не меняют
    (ревью S4: «ждёт ARB» в причине шага роняло активный эпик у одного читателя и не у другого)."""
    head = re.split(r"\s-\s+step\s", raw or "", maxsplit=1)[0]
    if head.strip().startswith("~~"):
        return "DONE"
    note = head.split("—", 1)[1] if "—" in head else ""
    if AWAITING_REVIEW.search(note):
        return "REVIEW"
    return "IN_PROGRESS" if _IN_PROGRESS.search(note) else "QUEUED"


def _key(title: str) -> tuple:
    m = _CODE.match(title)
    code = m.group(1) if m else None
    norm = re.sub(r"\s+", " ", title.strip().lower())
    return code, norm


def stage_title(title: Optional[str]) -> dict:
    """Русское название этапа плана: ``{"text", "known", "original"}`` — детерминированно.

    Уже русское название показывается как есть. Английское без строки в словаре — нейтральная
    подпись ``UNKNOWN_STAGE`` (``known=False``), исходник — в ``original`` для подробностей."""
    if not isinstance(title, str) or not title.strip():
        return {"text": None, "known": False, "original": title}
    code, norm = _key(title)
    if code and code in ROADMAP_RU:
        return {"text": ROADMAP_RU[code], "known": True, "original": title}
    if norm in ROADMAP_RU:
        return {"text": ROADMAP_RU[norm], "known": True, "original": title}
    if _CYRILLIC.search(title) and not (_LATIN.search(title) and len(_LATIN.findall(title)) > len(_CYRILLIC.findall(title))):
        return {"text": title.strip(), "known": True, "original": title}
    return {"text": UNKNOWN_STAGE, "known": False, "original": title}


# Заметка этапа, которая говорит «сделано», при состоянии «в очереди» — противоречие в плане,
# а не повод выбрать одно из двух. Слова — из самого плана (``docs/ROADMAP.md``).
_DONE_NOTE = re.compile(r"^\s*(done|delivered|published)\b", re.I)


def note_says_done(note: Optional[str]) -> bool:
    return isinstance(note, str) and bool(_DONE_NOTE.search(note))
