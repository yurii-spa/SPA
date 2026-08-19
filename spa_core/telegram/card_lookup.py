"""card_lookup — детерминированные ответы владельцу про карточки и очередь.

Задание владельца (Telegram, 2026-08-19, живой транскрипт в карточке
`inbox-bot-otritsaet-suschestvuyuschuyu-own-kartochku.md`): на вопрос
«есть ли на мне own-54?» бот ответил «в моих записях нет» — при карточке,
стоящей наверху доски. Ответ строился из LLM-контекста, а не из трекера.

Этот модуль отвечает на два класса вопросов БЕЗ LLM (инв. #14: канал решений
владельца — только детерминированный разбор):

* упоминание карточки по имени («own-54», «проверь inbox-actual-costs») →
  найти файл в живом трекере, а если его там нет — достать с origin/main
  (карточки едут на origin из worktree-сессий, в прод-дерево их «не возит
  никто» — замер 10.08) и материализовать в живое дерево;
* вопрос про очередь («что на мне», «мои задачи») → список needs-owner
  карточек из ЖИВОГО трекера, с честной пометкой про расхождение с origin.

Правила: pure stdlib · fail-safe (никогда не бросает наружу) · записи только
атомарные и только в живой трекер · под pytest живое дерево не трогается
(та же дисциплина, что у ``owner_decisions._live_tracker_dir``).
"""
from __future__ import annotations

import html
import logging
import re
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

log = logging.getLogger(__name__)

# Полное имя карточки трекера: слаг из известного семейства префиксов.
# Требуем хотя бы один дефис-сегмент после префикса — голое «own» не ссылка.
_CARD_REF_RE = re.compile(
    r"\b((?:own|inbox|agent|task|owner-decision)(?:-[a-z0-9]+)+)(?:\.md)?\b",
    re.IGNORECASE,
)

# Вопрос про очередь владельца. Строка целиком не требуется — вопрос живёт
# внутри обычной речи («а что на мне сейчас висит?»).
_QUEUE_QUESTION_RE = re.compile(
    r"что\s+(?:сейчас\s+)?на\s+мне"
    r"|мои\s+задач"
    r"|задачи\s+на\s+мне"
    r"|что\s+(?:меня\s+)?ждёт"
    r"|что\s+(?:меня\s+)?ждет"
    r"|очередь\s+владельца"
    r"|ждёт\s+(?:моего\s+)?(?:решения|ответа)"
    r"|ждет\s+(?:моего\s+)?(?:решения|ответа)",
    re.IGNORECASE,
)

_GIT_TIMEOUT_S = 15


def extract_card_ref(text: str) -> Optional[str]:
    """Первое упоминание карточки в тексте (слаг без ``.md``), иначе ``None``."""
    if not text:
        return None
    m = _CARD_REF_RE.search(str(text))
    return m.group(1).lower() if m else None


def is_queue_question(text: str) -> bool:
    """Спрашивает ли владелец, что ждёт его решения."""
    return bool(text) and bool(_QUEUE_QUESTION_RE.search(str(text)))


def find_cards(ref: str, tracker_dir: Path) -> List[Path]:
    """Файлы трекера, соответствующие ссылке: точное имя → префикс → вхождение.

    Возвращает отсортированный список (детерминированно). Пустой список —
    в этом дереве совпадений нет. Никогда не бросает.
    """
    try:
        stem = str(ref or "").strip().lower()
        if stem.endswith(".md"):
            stem = stem[:-3]
        if not stem or not tracker_dir.is_dir():
            return []
        files = sorted(p for p in tracker_dir.glob("*.md") if p.is_file())
        exact = [p for p in files if p.stem.lower() == stem]
        if exact:
            return exact
        prefix = [p for p in files if p.stem.lower().startswith(stem)]
        if prefix:
            return prefix
        return [p for p in files if stem in p.stem.lower()]
    except Exception as exc:  # noqa: BLE001 — поиск не важнее самого ответа
        log.warning("card_lookup.find_cards failed for %r: %s", ref, exc)
        return []


def _default_git(args: List[str], repo_root: Path) -> Optional[str]:
    """``git <args>`` в ``repo_root`` → stdout или ``None``. Никогда не бросает."""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(repo_root), capture_output=True,
            text=True, timeout=_GIT_TIMEOUT_S,
        )
        return proc.stdout if proc.returncode == 0 else None
    except Exception as exc:  # noqa: BLE001 — сеть/git не важнее ответа владельцу
        log.warning("card_lookup git %s failed: %s", args[:2], exc)
        return None


def fetch_origin_card(
    ref: str,
    repo_root: Path,
    git: Callable[[List[str], Path], Optional[str]] = _default_git,
) -> Optional[Tuple[str, str]]:
    """Карточка с ``origin/main``, которой нет в живом дереве: ``(имя, текст)``.

    Причина существования: карточки создаются worktree-сессиями и пушатся на
    origin, а автосинк прод-дерева их не возит — файл в git ЕСТЬ, у бота НЕТ
    (живой промах 2026-08-19: own-54). fetch — best-effort: без сети ищем по
    последнему известному ``origin/main``.
    """
    try:
        stem = str(ref or "").strip().lower()
        if stem.endswith(".md"):
            stem = stem[:-3]
        if not stem:
            return None
        git(["fetch", "origin", "main", "--quiet"], repo_root)  # best-effort
        listing = git(
            ["ls-tree", "--name-only", "origin/main", "nimbalyst-local/tracker/"],
            repo_root,
        )
        if not listing:
            return None
        names = [Path(line).name for line in listing.splitlines()
                 if line.strip().endswith(".md")]
        exact = [n for n in names if Path(n).stem.lower() == stem]
        prefix = [n for n in names if Path(n).stem.lower().startswith(stem)]
        matches = exact or prefix
        if len(matches) != 1:
            return None  # неоднозначность решается локальным списком, не догадкой
        name = matches[0]
        text = git(["show", f"origin/main:nimbalyst-local/tracker/{name}"], repo_root)
        if not text:
            return None
        return name, text
    except Exception as exc:  # noqa: BLE001
        log.warning("card_lookup.fetch_origin_card failed for %r: %s", ref, exc)
        return None


def materialize_text(name: str, text: str, tracker_dir: Path) -> Optional[Path]:
    """Атомарно положить карточку с origin в живой трекер (если её там нет).

    Существующий файл НЕ перезаписывается никогда: в нём может жить ответ
    владельца (тот же инвариант, что у ``owner_decisions.materialize_card``).
    """
    try:
        if not name.endswith(".md") or "/" in name or "\\" in name:
            return None
        target = tracker_dir / name
        if target.is_file():
            return target
        tracker_dir.mkdir(parents=True, exist_ok=True)
        from spa_core.utils.atomic import atomic_save_text

        atomic_save_text(text, str(target))
        return target
    except Exception as exc:  # noqa: BLE001
        log.warning("card_lookup.materialize_text failed for %s: %s", name, exc)
        return None


def _card_line(path: Path) -> str:
    """Одна строка сводки по карточке (title + status) — fail-safe."""
    title, status = path.stem, "?"
    try:
        from spa_core.owner_queue.queue import load_card

        card = load_card(path)
        title = card.title or path.stem
        status = str(card.status or "?")
    except Exception:  # noqa: BLE001 — битая карточка не должна прятать остальные
        pass
    return f"• <b>{html.escape(title)}</b> [{html.escape(status)}] · <code>{html.escape(path.name)}</code>"


def card_summary(path: Path) -> str:
    """Сводка по одной карточке для чата (HTML). Никогда не бросает."""
    try:
        from spa_core.owner_queue.queue import first_instruction_line, load_card

        card = load_card(path)
        title = html.escape(card.title or path.stem)
        status = html.escape(str(card.status or "?"))
        instr = html.escape(first_instruction_line(card))
        return (
            f"📄 <b>{title}</b>\n"
            f"Статус: <b>{status}</b>\n"
            f"➡️ {instr}\n"
            f"<code>nimbalyst-local/tracker/{html.escape(path.name)}</code>"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("card_lookup.card_summary failed for %s: %s", path, exc)
        return f"📄 <code>{html.escape(path.name)}</code> (карточку прочитать не удалось)"


def needs_owner_cards(tracker_dir: Path) -> List[Path]:
    """Карточки ``status: needs-owner`` в дереве — свежесозданные первыми."""
    out: List[Tuple[str, Path]] = []
    try:
        if not tracker_dir.is_dir():
            return []
        from spa_core.owner_queue.queue import load_card

        for p in sorted(tracker_dir.glob("*.md")):
            if p.name.startswith("_"):
                continue
            try:
                card = load_card(p)
            except Exception:  # noqa: BLE001
                continue
            if str(card.status or "").strip().lower() == "needs-owner":
                out.append((str(getattr(card, "created", "") or ""), p))
    except Exception as exc:  # noqa: BLE001
        log.warning("card_lookup.needs_owner_cards failed: %s", exc)
    return [p for _, p in sorted(out, key=lambda t: t[0], reverse=True)]


def queue_answer(tracker_dir: Path) -> str:
    """Ответ на «что на мне?» — из ЖИВОГО трекера, не из памяти (HTML)."""
    cards = needs_owner_cards(tracker_dir)
    if not cards:
        return (
            "📥 В живом трекере нет карточек со статусом <b>needs-owner</b>.\n"
            "Честная оговорка: карточки с origin доезжают сюда не сами — "
            "если ждёшь конкретную, назови её имя (например «проверь own-54»), "
            "я поищу и на origin."
        )
    lines = [f"🟥 Ждут твоего решения — {len(cards)} шт. (по живому трекеру):"]
    lines += [_card_line(p) for p in cards[:15]]
    if len(cards) > 15:
        lines.append(f"… и ещё {len(cards) - 15}.")
    lines.append("Назови карточку («проверь own-54») — пришлю её с вариантами ответа.")
    return "\n".join(lines)
