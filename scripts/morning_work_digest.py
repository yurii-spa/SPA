#!/usr/bin/env python3
"""morning_work_digest — «что сделано за вчера», простым языком, в Telegram каждое утро.

Owner-requested 2026-07-16: широкими мазками, человеческим языком (не тех-жаргон), в 09:00.
Отдельно от торгового daily_report — это дайджест РАБОТЫ/девелопмента, не портфеля.

Собирает вчерашнюю активность из трёх источников (источник правды — git/файлы):
  1. docs/journal/<ISO-week>.md — записи оркестратора/сессий за вчера,
  2. data/session_changes.jsonl — координационный лог (кто что делал),
  3. git-коммиты origin/main за вчера — что реально уехало.
Превращает в короткую сводку ПРОСТЫМ русским через локальный headless `claude -p`
(LLM здесь допустим — это репортинг, НЕ risk/execution), и шлёт единым TelegramBot.

Fail-safe: нет активности → «вчера тихо». LLM недоступен → отправляем сырой bullet-fallback,
НЕ молчим. LLM здесь не в risk-пути (инвариант соблюдён).

Честность (цикл #77 — карточка ``agent-morning-digest-claims-delivery-it-never-made``)
------------------------------------------------------------------------------------
Три места, где модуль утверждал больше, чем измерил, и как это устроено теперь:

1. **Доставка.** ``TelegramBot.send_message`` объявлен ``-> Optional[Dict]`` и НИКОГДА не
   бросает: ``_api_call`` ловит ``HTTPError``/``URLError``/``TimeoutError``/``OSError``/
   ``ValueError`` и отдаёт ``None``; к ``None`` ведут ещё flood-guard и пустой ``chat_id``.
   Старый ``main()`` возвращаемое значение выбрасывал и печатал «digest sent» безусловно —
   это видно в живом логе ``/tmp/spa_work_digest.log`` за 2026-07-26, где строкой выше стоит
   ``API call sendMessage failed: <urlopen error [Errno 65] No route to host>``. Теперь
   вердикт даёт :func:`delivery_verdict`: «отправлено» — только при ``ok: true`` от Telegram,
   всё остальное (включая незнакомый ответ) — отказ с ВЕРБАТИМ-причиной и ненулевым кодом.
2. **«Вчера было тихо».** Все три сборщика на ошибке чтения возвращали ``""``, неотличимо от
   «активности не было». Теперь каждый отдаёт ``(текст, [причины-не-прочтения])``; пустая
   сводка при непустом списке причин печатается как «не могу сказать» + причины вербатим, а
   «тихо» публикуется только когда все три источника РЕАЛЬНО прочитаны (fail-CLOSED, инв. #2).
   Блок причин добавляется ДЕТЕРМИНИРОВАННО после LLM — модель не может его потерять.
3. **Окно «вчера».** ``data/session_changes.jsonl`` пишется в UTC
   (``log_session_change.py``: ``datetime.now(timezone.utc)`` + ``Z``), а границы строились из
   наивного ЛОКАЛЬНОГО ``datetime.now()`` и сравнивались с UTC-метками как с локальными ⇒ окно
   съезжало на смещение пояса (в CEST — 2ч в обе стороны). Теперь границы приводятся к UTC
   (:func:`_utc_window`), и «вчера» означает один интервал для всех трёх источников.

Радиус правки: только этот файл. ``spa_core/telegram/bot.py`` НЕ трогается — его fail-safe
``send_message`` обслуживает ~20 потребителей. ``scripts/agent_work_digest.sh`` НЕ трогается —
он заканчивается ``exit 0`` независимо от кода возврата, а код агента читает
launchd/``agent_health`` (домен деплоя, автономному циклу запрещён).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CLAUDE = os.environ.get("SPA_CLAUDE_BIN") or "/Users/yuriikulieshov/.local/bin/claude"
_CLAUDE_TIMEOUT_S = 180


def _yesterday_bounds(now: datetime) -> tuple[datetime, datetime, str]:
    """Return (start, end, human-date) for 'yesterday' in local time."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=1)
    return start, today, start.strftime("%Y-%m-%d")


def _utc_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """The same two instants as ``[start, end)``, expressed as aware UTC.

    ``_yesterday_bounds`` speaks LOCAL time (the digest headline carries a local date, and
    ``git log --since`` reads local time too), while ``session_changes.jsonl`` is stamped in
    UTC. Comparing the two naively slid the window by the UTC offset — 2h in CEST — so work
    done just after local midnight was filed under the wrong day in BOTH directions.
    A naive bound is interpreted as local (``astimezone()`` semantics since 3.6); an aware
    bound is simply converted, so callers may pass either.
    """
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _parse_log_ts(value: str) -> datetime | None:
    """Parse a ``session_changes.jsonl`` timestamp as an AWARE UTC instant, else ``None``.

    The writer emits ``%Y-%m-%dT%H:%M:%SZ`` (``log_session_change.py``); a bare naive stamp
    from an older writer is read as UTC for the same reason — that is what produced it.
    """
    text = str(value).strip()
    if not text:
        return None
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


def _gather_journal(day: str) -> tuple[str, list[str]]:
    """Journal lines whose section/date matches yesterday.

    Returns ``(text, unread)``. ``unread`` names — verbatim — every journal source that could
    not be READ; an empty ``text`` with an empty ``unread`` therefore means "read it, nothing
    there", which is a different statement from "could not look".
    """
    wk_dir = _REPO / "docs" / "journal"
    if not wk_dir.is_dir():
        return "", [f"docs/journal: каталога нет ({wk_dir})"]
    out: list[str] = []
    unread: list[str] = []
    try:
        files = sorted(wk_dir.glob("*.md"))
    except OSError as exc:
        return "", [f"docs/journal: каталог не читается ({exc})"]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unread.append(f"docs/journal/{f.name}: {exc}")
            continue
        # keep blocks under a "## <day>" heading (and their following lines until next ##)
        keep, cur = [], False
        for line in text.splitlines():
            if line.startswith("## "):
                cur = day in line
            if cur:
                keep.append(line)
        if keep:
            out.append("\n".join(keep))
    return "\n".join(out)[:8000], unread


def _gather_session_changes(start: datetime, end: datetime) -> tuple[str, list[str]]:
    """session_changes.jsonl summaries stamped within ``[start, end)``.

    Returns ``(text, unread)``; the window is compared in UTC (see :func:`_utc_window`).
    A line that cannot be parsed is COUNTED, not silently dropped — an announce we failed to
    read is an announce we cannot claim was absent.
    """
    f = _REPO / "data" / "session_changes.jsonl"
    if not f.is_file():
        return "", [f"data/session_changes.jsonl: файла нет ({f})"]
    try:
        raw_text = f.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "", [f"data/session_changes.jsonl: {exc}"]
    start_utc, end_utc = _utc_window(start, end)
    lines: list[str] = []
    skipped = 0
    for raw in raw_text.splitlines():
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not isinstance(d, dict):
            skipped += 1
            continue
        t = _parse_log_ts(d.get("ts", ""))
        if t is None:
            skipped += 1
            continue
        if start_utc <= t < end_utc:
            s = str(d.get("summary", "")).strip()
            if s:
                lines.append(f"- {s}")
    unread = ([f"data/session_changes.jsonl: {skipped} записей не разобрано "
               f"(битый JSON или метка времени) — их содержимое в дайджест не попало"]
              if skipped else [])
    return "\n".join(lines[-60:])[:6000], unread


def _gather_commits(day: str) -> tuple[str, list[str]]:
    """git commits on origin/main authored on yesterday (subject lines).

    Returns ``(text, unread)``. A failed ``fetch`` is reported (the ref may be behind, so an
    empty list would not mean "nothing shipped"), and so is a non-zero ``git log`` — that exit
    code used to be discarded, leaving an unread ref indistinguishable from a quiet day.
    """
    unread: list[str] = []
    try:
        fetched = subprocess.run(["git", "fetch", "origin", "main"], cwd=str(_REPO),
                                 capture_output=True, timeout=30)
        if fetched.returncode != 0:
            # ``fetch`` runs without ``text=True``, so stderr arrives as bytes here and as str
            # from a stubbed run — decode defensively rather than formatting a b'…' repr.
            raw_err = fetched.stderr or b""
            err = (raw_err.decode("utf-8", "replace")
                   if isinstance(raw_err, bytes) else str(raw_err))
            unread.append("git fetch origin main не прошёл (exit "
                          f"{fetched.returncode}): {err.strip()[:200]} — список коммитов "
                          "может быть неполным")
        out = subprocess.run(
            ["git", "log", "origin/main", "--since", f"{day} 00:00",
             "--until", f"{day} 23:59", "--pretty=%s"],
            cwd=str(_REPO), capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0:
            return "", unread + [f"git log origin/main не прошёл (exit {out.returncode}): "
                                 f"{(out.stderr or '').strip()[:200]}"]
        subjects = [l for l in out.stdout.splitlines() if l.strip()]
        return "\n".join(f"- {s}" for s in subjects[:80])[:6000], unread
    except (OSError, subprocess.SubprocessError) as exc:
        return "", unread + [f"git: {exc}"]


_PROMPT = """Ты пишешь УТРЕННИЙ дайджест владельцу проекта: «что сделано за вчера».
ПРАВИЛА: простой человеческий русский, ШИРОКИМИ мазками, без тех-жаргона и без имён файлов/
коммитов. Пиши, ЧТО это дало (ценность), а не как. 5-9 коротких буллетов максимум, каждый с
эмодзи. В конце — одна строка-итог. Если данных мало — честно скажи «вчера было тихо».
Формат — обычный текст (не markdown-таблицы). Заголовок: «☀️ Что сделано вчера (<дата>)».

Вот сырые данные за вчерашний день (журнал, лог изменений, коммиты) — переведи их для человека:

<DATA>
"""


def _unread_block(unread: list[str]) -> str:
    """The verbatim 'not read' footer. Deterministic — never routed through the LLM."""
    if not unread:
        return ""
    return ("\n\n⚠️ Прочитано не всё — по этим источникам утверждать нечего:\n"
            + "\n".join(f"• {r}" for r in unread))


def build_digest(now: datetime | None = None) -> tuple[str, str]:
    """Return (raw_bullets_fallback, human_text). human_text via claude; fallback if it fails."""
    now = now or datetime.now()
    start, end, day = _yesterday_bounds(now)
    journal, u_journal = _gather_journal(day)
    changes, u_changes = _gather_session_changes(start, end)
    commits, u_commits = _gather_commits(day)
    unread = u_journal + u_changes + u_commits

    raw = "\n\n".join(x for x in [
        ("ЖУРНАЛ:\n" + journal) if journal else "",
        ("ИЗМЕНЕНИЯ:\n" + changes) if changes else "",
        ("КОММИТЫ:\n" + commits) if commits else "",
    ] if x).strip()

    if not raw:
        # fail-CLOSED: «тихо» — вывод из ПРОЧИТАННЫХ источников. Если что-то прочитать не
        # удалось, тишина не измерена, и говорить о ней нельзя (инв. #2).
        if unread:
            txt = (f"☀️ Что сделано вчера ({day})\n\n"
                   "Не могу сказать, что было вчера: активности не найдено, но источники "
                   "прочитаны не все — «тихо» это НЕ значит." + _unread_block(unread))
        else:
            txt = (f"☀️ Что сделано вчера ({day})\n\n"
                   "Вчера было тихо — существенных изменений нет.")
        return raw, txt

    # plain-language via headless `claude -p` — PURE TEXT SUMMARIZATION, no tools, so it
    # runs WITHOUT --dangerously-skip-permissions (verified: a summarize-this-text prompt
    # invokes no tools → no permission prompt → exits cleanly). Reporting path, not a risk
    # path. Deliberately NOT skip-permissions: nothing here should read files or run commands.
    try:
        proc = subprocess.run(
            [_CLAUDE, "-p", _PROMPT.replace("<DATA>", raw[:12000])],
            capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT_S,
            env={**os.environ},
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return raw, proc.stdout.strip() + _unread_block(unread)
    except (OSError, subprocess.SubprocessError):
        pass

    # fallback: raw bullets, honest (never silent)
    fallback = (f"☀️ Что сделано вчера ({day}) — сырьём (авто-сводка недоступна):\n\n"
                + raw[:2500] + _unread_block(unread))
    return raw, fallback


def delivery_verdict(resp: object) -> tuple[bool, str]:
    """Was the message ACTUALLY delivered? ``(delivered, verbatim reason)``.

    ``TelegramBot.send_message`` is fail-safe by contract: it returns ``None`` on a network
    error, an HTTP error, a flood-guard drop or a missing ``chat_id``, and never raises. Only
    Telegram's own ``{"ok": true, ...}`` is evidence of delivery; anything else — including a
    shape we do not recognise — is «не измерено», which is reported, not rounded up to success.

    The repo has two sender contracts — ``TelegramBot.send_message`` answers with the parsed
    Telegram document, ``alerts.telegram_client.send_message`` with a bool — so both are read
    explicitly rather than by truthiness, which would silently bless anything non-empty.
    """
    if resp is True:
        return True, ""
    if resp is False:
        return False, "отправитель вернул False — сообщение НЕ ушло"
    if resp is None:
        return False, ("Telegram API вернул None — сообщение НЕ ушло (сеть/HTTP-ошибка, "
                       "flood-guard или пустой chat_id). Точная причина — в строке "
                       "'API call sendMessage failed: …' выше в этом же логе")
    if isinstance(resp, dict):
        ok = resp.get("ok")
        if ok is True:
            return True, ""
        if ok is False:
            return False, (f"Telegram ответил ok=false: "
                           f"{str(resp.get('description', ''))[:200]!r}")
        return False, (f"ответ Telegram без поля ok — доставка НЕ подтверждена: "
                       f"{str(resp)[:200]!r}")
    return False, f"неизвестный ответ отправителя, доставка НЕ подтверждена: {str(resp)[:200]!r}"


def main() -> int:
    _, text = build_digest()
    if "--dry-run" in sys.argv:
        print(text)
        return 0
    try:
        from spa_core.telegram.bot import TelegramBot

        resp = TelegramBot().send_message(text)
    except Exception as exc:  # noqa: BLE001
        print(f"digest send failed: {exc}", file=sys.stderr)
        return 1
    delivered, reason = delivery_verdict(resp)
    if delivered:
        print("digest sent")
        return 0
    print(f"digest NOT sent: {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
