#!/usr/bin/env python3
"""Экран «Мои решения»: открытые карточки владельца прямо в боте.

Задание владельца 2026-08-08 (перед отъездом на 10 дней): *«чтобы всё, что требует моего
решения, приходило в телеграм с вариантами и рекомендацией — чтобы я мог частично управлять
разработкой из телефона»*. Пуш решает половину: сообщение уезжает в ленте вверх за сутки,
а решение остаётся открытым. Этот экран — вторая половина: список можно ОТКРЫТЬ САМОМУ,
в любой момент, ничего не дожидаясь.

Два правила, оба ради того, чтобы два входа не разъехались (урок экрана «Проблемы»):

* **Реестр вариантов не дублируется.** Клавиатура берётся у
  ``owner_decisions.build_keyboard`` целиком; здесь к ней лишь дописывается навигация.
  Свой список вариантов рядом с существующим — это два реестра, расходящихся молча.
* **Маячок обработчика тут НЕ спрашиваем, и это не послабление.** Интерлок ADR-069 защищает
  от того, что кнопки уедут РАНЬШЕ обработчика (короткоживущий монитор уже с новым кодом,
  долгоживущий бот — ещё со старым). Здесь отправитель и обработчик — ОДИН процесс: экран
  рисует тот же бот, чей роутер обработает нажатие. Бот, не умеющий обработать нажатие,
  не умеет и нарисовать этот экран.

Read-only по трекеру, stdlib, детерминированно, без LLM.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from spa_core.telegram import menus, owner_decisions

# Экран — не архив: он нужен, чтобы дотянуться до открытых решений, а их единицы.
DECISIONS_SHOWN = 10


def _short(text: str, limit: int = 34) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def render_list(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    """Список открытых решений владельца: каждая строка — кнопка."""
    try:
        pending = owner_decisions.pending_decisions()[:DECISIONS_SHOWN]
    except Exception:  # noqa: BLE001 — сломанный трекер не имеет права уронить меню
        pending = []

    body: List[str] = ["🧑‍⚖️  <b>Мои решения</b>", ""]
    buttons: List[List[Dict]] = []
    if not pending:
        body.append("Открытых решений нет — всё разобрано.")
    for item in pending:
        n = len(item["options"])
        # Карточка без разобранных вариантов честно помечается: нажатие откроет её текст,
        # но кнопок выбора не будет — мы их не выдумываем.
        mark = "•" if n else "📄"
        body.append(f" {mark} {_short(item['title'], 60)}")
        body.append(f"    вариантов: {n}" if n else "    вариантов в карточке нет")
        buttons.append([{
            "text": f"{mark} {_short(item['title'])}",
            "callback_data": f"nav:decisions.item|{item['pid']}",
        }])

    text = "\n".join(body)
    return text, menus.standard_keyboard("decisions", lang, extra_rows=buttons)


def render_item(arg: str = "", lang: str = "en", page: int = 0,
                prefs: Dict = None) -> Tuple[str, Dict]:
    """Одно решение: суть + ТЕ ЖЕ варианты ответа, что и в пуше.

    ``arg`` — ``pid`` из ``nav:decisions.item|<pid>``. Карточки нет (её закрыли, переименовали,
    журнал вытеснил) → честно об этом говорим и кнопок НЕ показываем: нажатие всё равно
    получило бы отказ, и лучше сказать это до нажатия, а не после.
    """
    pid = str(arg or "").strip()
    rec = owner_decisions.find_push(pid) if pid else None
    if rec is None:
        return ("🧑‍⚖️  <b>Решение не найдено</b>\n\n"
                "Карточку закрыли или журнал её уже не помнит.",
                menus.standard_keyboard("decisions", lang))

    options = [
        owner_decisions.ParsedOption(
            num=str(o.get("num")), label=str(o.get("label") or ""),
            recommended=bool(o.get("recommended")),
        )
        for o in (rec.get("options") or [])
    ]
    title = str(rec.get("title") or "")
    text = owner_decisions.card_details(pid)
    if rec.get("choice"):
        text += (f"\n\n✅ Уже отвечено: вариант {rec['choice']}"
                 f" — {rec.get('choice_label') or ''}")
        return text, menus.standard_keyboard("decisions", lang)

    if options:
        extra = owner_decisions.build_keyboard(pid, options)["inline_keyboard"]
    elif rec.get("ack"):
        # Карточка-поручение: выбора в ней нет, но ответить с телефона обязано быть ЧЕМ
        # (#274). Реестр кнопок не дублируется — клавиатура берётся у `owner_decisions`
        # целиком, как и у вариантов. Признак `ack` берём из журнала (он ИЗМЕРЕН в момент
        # отправки), а не пересчитываем здесь: два места счёта разъехались бы молча.
        extra = owner_decisions.build_ack_keyboard(pid)["inline_keyboard"]
        text += ("\n\n📌 Выбора в этой карточке нет — это поручение. "
                 f"«{owner_decisions.ACK_BUTTON_RU}» закроет её твоим подтверждением, "
                 f"«{owner_decisions.LATER_BUTTON_RU}» оставит открытой.")
    else:
        extra = []
        text += "\n\n⚠️ Вариантов в карточке не нашёл — реши её в трекере."
    return text, menus.standard_keyboard("decisions", lang, extra_rows=extra)
