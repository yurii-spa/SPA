"""MP-015: Telegram client with credentials from macOS Keychain.

Secrets policy (incident 2026-06-10): the bot token and chat id are NEVER
stored in files or env defaults — they are read at runtime from the macOS
Keychain entries ``TELEGRAM_BOT_TOKEN_SPA`` / ``TELEGRAM_CHAT_ID_SPA``
(account ``spa``). Rotation = ``security add-generic-password ... -U``.

Stdlib only: ``subprocess`` for Keychain, ``urllib.request`` for HTTP.

* ``get_bot_token()`` / ``get_chat_id()`` raise ``EnvironmentError`` when the
  Keychain entry is unavailable.
* ``send_message()`` is fail-safe: 10 s timeout, one retry on network error,
  any failure (including missing credentials) → WARNING + ``False``,
  never raises.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.alerts.telegram_client")

KEYCHAIN_ACCOUNT = "spa"
TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"

HTTP_TIMEOUT_S = 10
RETRIES = 1  # one retry on network error → two attempts total

# ── Flood guard ──────────────────────────────────────────────────────────────
# A SHARED, cross-process rate limit. Every SPA agent is a separate process, so the
# counter lives in a state file: the cap bounds TOTAL Telegram volume no matter how many
# agents (or one runaway loop) try to send. Excess is dropped + logged so a flooder is
# visible in the log without spamming the chat. Fail-open (a guard error never blocks sends).
# Флуд-защита обязана быть ОБЩЕЙ на всю машину, а не на дерево.
# Замер 09.08: поток одинаковых сообщений владельцу шёл из сессии, работавшей в своём
# worktree. Файл состояния считался от каталога ОТПРАВИТЕЛЯ, поэтому у каждого дерева
# был СВОЙ бюджет 12 сообщений в минуту: «общий межпроцессный лимит» из докстринга
from spa_core.utils.live_paths import live_data_dir


def _live_state(name: str) -> Path:
    """Путь состояния в ЖИВОМ дереве, разрешаемый В МОМЕНТ ВЫЗОВА, а не на импорте.

    Замер циклов #391/#394: три пути ниже вычислялись на ИМПОРТЕ модуля, а
    ``live_data_dir()`` первым делом читает ``SPA_DATA_DIR``. Импорт случается ОДИН раз —
    на сборе тестов или на первом тесте, который модуль тянет, — поэтому значение
    прибивалось к окружению одного случайного момента и дальше не менялось: под изоляцией
    это песочница ЧУЖОГО теста (следующие тесты видят каталог, которого уже нет), без
    изоляции — прод-дерево владельца. Форма «разрешать каждый вызов» уже живёт в
    ``spa_core/audit/hash_chain.py::_chain_path``; здесь она вдобавок ПЕРЕЧИТЫВАЕТ
    окружение, иначе смена песочницы после импорта остаётся незамеченной.

    В проде поведение НЕ меняется: ``SPA_DATA_DIR`` там не выставлен, и каждый вызов даёт
    ровно тот же живой каталог, что и прежняя константа.
    """
    return live_data_dir(Path(__file__).resolve().parents[2]) / name


# существовал только на словах, а на деле умножался на число деревьев.
#: Точка подмены для тестов. ``None`` ⇒ путь разрешается в момент вызова (``_live_state``);
#: тест, подменивший переменную через ``monkeypatch.setattr``, по-прежнему выигрывает.
_RATE_STATE: Path | None = None


def _rate_state_path() -> Path:
    """Файл общего межпроцессного лимита потока. См. ``_live_state``."""
    return Path(_RATE_STATE) if _RATE_STATE is not None else _live_state(".telegram_rate.json")
MAX_MSGS_PER_MIN = 12

#: Сколько символов текста кладём в историю как «превью». ОДНА константа на модуль:
#: по ней же сравнивается повтор, и разъедься они — дедуп молча перестал бы срабатывать.
_PREVIEW_LEN = 80

#: Хвостовая строка `<i>2026-08-13T13:31:35.522152+00:00</i>`, которую `push_policy`
#: приписывает КАЖДОМУ сообщению (`_format_message`). Для дедупа она — шум.
_TRAILING_STAMP = re.compile(
    r"\s*<i>\s*\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:[+-]\d\d:\d\d|Z)?\s*</i>\s*$"
)


def _dedup_preview(text: str) -> str:
    """Ключ повтора: тот же текст, но БЕЗ нашей же отметки времени в хвосте.

    Замер 13.08 — почему дедуп не срабатывал НИ РАЗУ на коротких тревогах. Сравнивались
    первые 80 символов ГОТОВОГО сообщения, а `push_policy._format_message` дописывает в
    конец `<i>{now}</i>` с точностью до микросекунд. У короткой тревоги эта отметка
    попадает ВНУТРЬ восьмидесяти символов, поэтому два побуквенно одинаковых сообщения
    давали РАЗНЫЕ ключи и совпасть не могли в принципе:

        '✅ <b>Телеграм-бот снова работает</b>\\n\\n<i>2026-08-12T11:12:11.424298+00:00</i>'
        '✅ <b>Телеграм-бот снова работает</b>\\n\\n<i>2026-08-13T04:11:06.923583+00:00</i>'

    Окно в полчаса при этом честно существовало и honest-но не ловило ничего — сторож
    отвечал на свой вопрос, а не на нужный. Снимаем ТОЛЬКО собственный штамп в хвосте:
    любая содержательная разница (другая цифра, другой агент, эскалация) остаётся в ключе
    и проходит немедленно, как и обещает докстринг `_duplicate_recently`.
    """
    return _TRAILING_STAMP.sub("", text or "")[:_PREVIEW_LEN]

# ── Alert history (append-only audit trail) ──────────────────────────────────
# Every send outcome is recorded here for observability: {ts, type, ok, message_id|error}.
# Ring-buffer capped at HISTORY_MAX so the file never grows unbounded. Atomic write via
# os.replace. Fail-open: a history error NEVER blocks or fails a send. Disabled under
# pytest unless SPA_ALERT_HISTORY_TEST is set (so tests don't pollute the live file).
# История — туда же: пока она была по-дереву, поток из чужого дерева НЕ ВИДЕН в проде,
# и разбор «кто это шлёт» упирался в пустоту (потрачено два круга 08–09.08).
#: Точка подмены для тестов — см. ``_RATE_STATE``.
_HISTORY_STATE: Path | None = None


def _history_state_path() -> Path:
    """Файл журнала отправок (он же источник дедупа). См. ``_live_state``."""
    return Path(_HISTORY_STATE) if _HISTORY_STATE is not None else _live_state("alert_history.json")
HISTORY_MAX = 500

# ── Cross-process outbound lock (карточка `inbox-critical-kartochka-goloda-...`, замер
# 26.08 — безопасность 2 параллельных циклов оркестратора) ──────────────────────────
# `guard_outbound` РЕШАЕТ «слать/не слать» ЧТЕНИЕМ `_HISTORY_STATE`, а фиксирует решение
# запись в неё же, которая происходит ПОСЛЕ фактической отправки (`_record_history`).
# Между чтением и записью — окно: при одном процессе-отправителе оно неопасно (следующий
# вызов — от того же процесса, последовательно), но при ДВУХ параллельных процессах оба
# читают «повторов нет» одновременно и оба шлют — владелец получает дубль (класс, который
# уже дважды чинили как «поток одинаковых сообщений», 09.08 и 13.08). Один и тот же
# advisory-лок (POSIX `flock`, блокирующий) вокруг всей последовательности
# guard-решение → HTTP-отправка → `_record_history` у ОБЕИХ дверей (`_post_message` здесь
# и `TelegramBot.send_message`/`edit_message_text` в `spa_core/telegram/bot.py`) убирает
# гонку целиком: держится и под pytest (иначе тест на конкуренцию ничего бы не проверял),
# путь — тем же `live_data_dir`, что и история/лимит потока, так что тест и прод лочатся
# на один и тот же файл своего дерева.
#: Точка подмены для тестов — см. ``_RATE_STATE``.
_OUTBOUND_LOCK_PATH: Path | None = None


def _outbound_lock_path() -> Path:
    """Файл межпроцессного лока отправки. См. ``_live_state``."""
    return (Path(_OUTBOUND_LOCK_PATH) if _OUTBOUND_LOCK_PATH is not None
            else _live_state(".telegram_outbound.lock"))


@contextlib.contextmanager
def outbound_lock():
    """Держит эксклюзивный кросс-процессный лок на время guard-решения+отправки+записи.

    Блокирующий (``LOCK_EX`` без ``LOCK_NB``) — редкая конкурентная отправка подождёт
    доли секунды своей очереди, а не потеряется дублем. Никогда не бросает: ошибка
    открытия/лока (диск недоступен и т.п.) — тот же fail-open принцип, что у остальной
    защиты в этом модуле, поэтому падение лока не имеет права уронить отправку владельцу.
    """
    lock_path = _outbound_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(lock_path, "a+")
    except OSError:
        yield
        return
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass  # не залочилось — шлём как раньше, не блокируя владельца
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def _classify(text: str) -> str:
    """Best-effort alert type from the message text (cheap, prefix-based)."""
    t = (text or "")
    head = t.lstrip()[:64]
    if "Go-Live" in head or "Go-Live" in t[:120]:
        return "golive"
    if "Gap" in head:
        return "gap"
    if "Важные события" in head or "red flag" in t.lower()[:120]:
        return "red_flag"
    if "Tournament" in head or "Турнир" in head:
        return "tournament"
    if "подключён" in t[:120] or "startup" in t.lower()[:64]:
        return "startup"
    if "SPA —" in head or "SPA " in head:
        return "daily_summary"
    return "other"


def _record_history(text: str, ok: bool, message_id=None, error: str | None = None,
                    solicited: bool = False, buttons: bool | None = None) -> None:
    """Append one send outcome to the ring-buffered alert_history.json. Never raises.

    ``solicited`` — владелец САМ это вызвал (ответ на его команду, кнопку, голосовое).
    Такая запись нужна, чтобы вопрос «кто это шлёт» имел ответ, но повтором она НЕ
    считается: иначе ответ на `/status` заглушил бы настоящую тревогу с тем же текстом.

    ``buttons`` — приехала ли с сообщением клавиатура (жалоба владельца 14.08: «пишет
    варианты ответов — кнопок нету»). Мерить это можно ТОЛЬКО здесь, в дверях: `preview`
    в журнале — 80 символов, и блок «Варианты:» в него не помещается по построению, а
    клавиатуры в тексте нет вовсе. ``None`` — дверь не сказала; тогда поля не будет
    совсем, и скан назовёт запись «не измерено», а не «кнопок не было» (fail-CLOSED).
    ``offers_choice`` считается ЗДЕСЬ по полному тексту — чтобы ни один отправитель не
    мог забыть его передать (цикл #229).
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "SPA_ALERT_HISTORY_TEST"
    ):
        return
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": _classify(text),
            "ok": bool(ok),
            "preview": (text or "")[:_PREVIEW_LEN],
            # Ключ повтора хранится ОТДЕЛЬНО от превью: превью — для человека, который
            # разбирает «кто это шлёт», и урезать его до неузнаваемости нельзя.
            "dkey": _dedup_preview(text),
        }
        try:
            from spa_core.telegram.buttonless_audit import history_fields

            entry.update(history_fields(text, buttons))
        except Exception:  # noqa: BLE001 — наблюдение не имеет права уронить журнал
            pass
        if solicited:
            entry["solicited"] = True
        if message_id is not None:
            entry["message_id"] = message_id
        if error:
            entry["error"] = str(error)[:200]

        try:
            doc = json.loads(_history_state_path().read_text())
            if not isinstance(doc, dict):
                doc = {}
        except Exception:
            doc = {}
        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []
        entries.append(entry)
        entries = entries[-HISTORY_MAX:]

        doc = {
            "schema_version": 1,
            "source": "telegram_client",
            "updated_at": entry["ts"],
            "count": len(entries),
            "max_entries": HISTORY_MAX,
            "entries": entries,
        }
        hist_path = _history_state_path()
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(hist_path.parent), prefix=".alerthist_")
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, hist_path)
    except Exception:  # noqa: BLE001 — observability must never break a send
        log.debug("alert_history record failed", exc_info=True)


def _rate_limit_ok(text: str = "") -> bool:
    # Under pytest the guard is disabled: tests must be isolated and are never a real flood
    # source (the shared state file would otherwise leak counts across tests).
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    try:
        now = time.time()
        try:
            hist = json.loads(_rate_state_path().read_text())
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []
        hist = [t for t in hist if isinstance(t, (int, float)) and (now - t) < 60.0]
        if len(hist) >= MAX_MSGS_PER_MIN:
            log.warning("Telegram FLOOD GUARD: dropped message (>%d/min). preview=%r",
                        MAX_MSGS_PER_MIN, (text or "")[:100])
            return False
        hist.append(now)
        rate_path = _rate_state_path()
        rate_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(rate_path.parent), prefix=".tgrate_")
        with os.fdopen(fd, "w") as f:
            json.dump(hist, f)
        os.replace(tmp, rate_path)
        return True
    except Exception:
        return True  # fail-open: never block a legitimate send on a guard error


def flood_guard_ok(text: str = "") -> bool:
    """Public flood-guard check for callers that do their OWN HTTP send.

    Modules that POST to Telegram directly (with their own per-instance or env
    credentials) must still honour the shared cross-process rate limit. They
    call this BEFORE sending: ``False`` → drop the message (already logged).
    Disabled under pytest (see ``_rate_limit_ok``). Fail-open on guard error.
    """
    return _rate_limit_ok(text)


def _read_keychain(service: str) -> str:
    """Read one generic password from the macOS Keychain. Raises EnvironmentError."""
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s", service,
                "-a", KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=HTTP_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentError(
            "Telegram credentials not found in Keychain"
        ) from exc
    value = (proc.stdout or "").strip()
    if proc.returncode != 0 or not value:
        raise EnvironmentError("Telegram credentials not found in Keychain")
    return value


def get_bot_token() -> str:
    """Bot token from Keychain service ``TELEGRAM_BOT_TOKEN_SPA``."""
    return _read_keychain(TOKEN_SERVICE)


def get_chat_id() -> str:
    """Chat id from Keychain service ``TELEGRAM_CHAT_ID_SPA``."""
    return _read_keychain(CHAT_ID_SERVICE)


#: Окно, в котором ПОБУКВЕННО одинаковое сообщение считается повтором и не уходит.
#: Полчаса выбрано так: одинаковый текст за это время не несёт НИ ОДНОГО нового факта —
#: изменилось бы состояние, изменился бы и текст. Значение переопределяется
#: ``SPA_TELEGRAM_DUP_WINDOW_S`` (0 — выключить, для отладки).
DUPLICATE_WINDOW_S = 1800.0


def _duplicate_recently(text: str) -> bool:
    """Уходил ли ПОБУКВЕННО такой же текст недавно. Сомнение → False (лучше послать).

    Зачем поверх дедупа `push_policy`: тот знает только своих отправителей, а мимо него
    шлют скрипты и сессии из чужих деревьев. Замер 09.08: владелец получал одно и то же
    сообщение каждые несколько минут всё утро — «с этим невозможно работать».

    Это НЕ глушилка: гасится только БУКВАЛЬНО тот же текст. Любое изменение — новая
    цифра, другой агент, эскалация — проходит немедленно.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("SPA_TELEGRAM_DUP_TEST"):
        return False
    try:
        window = float(os.environ.get("SPA_TELEGRAM_DUP_WINDOW_S", DUPLICATE_WINDOW_S))
        if window <= 0:
            return False
        doc = json.loads(_history_state_path().read_text())
        entries = doc if isinstance(doc, list) else doc.get("entries") or []
        now = datetime.now(timezone.utc)
        # Окно считаем по ТЕМ ЖЕ записям, среди которых ищем повтор. С #215 в историю
        # пишет и бот, включая ответы на команды владельца, — а он разговорчив: полсотни
        # его нажатий вытолкнули бы настоящий пуш из «последних 60» за считанные минуты, и
        # дедуп ослабило бы ровно то наблюдение, которое я добавил, чтобы его усилить.
        # Поэтому отбор — сначала по признаку (успешные и НЕ солиситированные), и только
        # потом срез: болтовня бота больше не вымывает пуши из поля зрения.
        candidates = [r for r in entries if r.get("ok") and not r.get("solicited")]
        key = _dedup_preview(text)
        for rec in reversed(candidates[-60:]):
            # У записей ДО этой правки поля `dkey` нет — сравниваем с сырым превью.
            # Не совпадёт (в нём остался штамп) ⇒ отправим: сомнение → False, как и
            # обещает докстринг. Через полчаса история обновится и дедуп заработает.
            if (rec.get("dkey") or rec.get("preview") or "") != key:
                continue
            try:
                ts = datetime.fromisoformat(str(rec.get("ts")))
            except Exception:  # noqa: BLE001
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if 0 <= (now - ts).total_seconds() <= window:
                return True
        return False
    except Exception:  # noqa: BLE001 — не смогли проверить ⇒ НЕ подавляем
        return False


def guard_outbound(text: str, *, dedup: bool = True) -> str | None:
    """ЕДИНСТВЕННАЯ проверка перед отправкой владельцу. ``None`` — можно слать.

    Возвращает причину отказа (``"flood_guard_dropped"`` / ``"duplicate_dropped"``) и САМ
    пишет её в историю — чтобы «подавлено» и «канал сломан» никогда не выглядели одинаково.

    Зачем функция, а не два вызова на месте (замер 13.08, цикл #215)
    ------------------------------------------------------------------------------
    Дверей в Телеграм у нас две, и защиту они разобрали ПОПОЛАМ:

    * ``_post_message``            — лимит потока (17.07) И дедуп (09.08);
    * ``TelegramBot.send_message`` — только лимит потока, дедупа нет, и историю она не
      писала ВОВСЕ.

    Владелец жаловался на поток одинаковых сообщений 09.08 — починили ту дверь, в которую
    он не ходит: `notify_needs_owner` и все пуши бота идут второй. 13.08 он пожаловался
    снова, теми же словами. А поскольку вторая дверь не вела журнал, в истории за день
    стояло 3 записи против десятков полученных — вопрос «кто это шлёт» был неотвечаем
    ПО ПОСТРОЕНИЮ.

    Теперь проверка одна на обе двери: третий отправитель унаследует её целиком или не
    получит ничего — половину взять нельзя.

    ``dedup=False`` — сообщение СОЛИЦИТИРОВАНО (ответ на команду/кнопку/голосовое
    владельца). Такое не глушим: спросил дважды — ответить обязаны дважды.
    """
    # FLOOD GUARD: a shared cross-process rate limit so NO sender (any agent) can flood
    # Telegram. Excess messages are DROPPED + logged with a preview (identifies the flooder).
    if not _rate_limit_ok(text):
        _record_history(text, ok=False, error="flood_guard_dropped")
        return "flood_guard_dropped"
    # ПОВТОР: побуквенно тот же текст в окне не несёт новых фактов. Гасим и ГОВОРИМ об
    # этом в лог с превью — молчаливое подавление неотличимо от поломки канала.
    if dedup and _duplicate_recently(text):
        log.warning("Telegram DUPLICATE dropped (same text within %.0fs). preview=%r",
                    DUPLICATE_WINDOW_S, (text or "")[:100])
        _record_history(text, ok=False, error="duplicate_dropped")
        return "duplicate_dropped"
    return None


def _post_message(payload_dict: dict) -> bool:
    """Internal: POST a sendMessage payload. Shared by send_message and
    send_message_with_keyboard. Fail-safe: any failure → WARNING + False.

    Целиком под ``outbound_lock()`` — guard-решение, сама отправка и запись в историю
    должны быть одной атомарной последовательностью межпроцессно (см. докстринг лока)."""
    with outbound_lock():
        text = payload_dict.get("text", "")
        if guard_outbound(text) is not None:
            return False
        try:
            token = get_bot_token()
            chat_id = get_chat_id()
        except EnvironmentError as exc:
            log.warning("Telegram send skipped: %s", exc)
            _record_history(text, ok=False, error=str(exc))
            return False

        payload_dict["chat_id"] = chat_id
        payload_dict.setdefault("parse_mode", "Markdown")
        payload_dict.setdefault("disable_web_page_preview", True)

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps(payload_dict).encode("utf-8")

        last_err: Exception | None = None
        for attempt in range(1 + RETRIES):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                    if resp.status == 200:
                        msg_id = None
                        try:
                            body = json.loads(resp.read().decode("utf-8"))
                            msg_id = (body.get("result") or {}).get("message_id")
                        except Exception:  # noqa: BLE001 — body parse is best-effort
                            pass
                        _record_history(text, ok=True, message_id=msg_id,
                                        buttons="reply_markup" in payload_dict)
                        return True
                    last_err = RuntimeError(f"HTTP status {resp.status}")
            except urllib.error.HTTPError as exc:
                # 400 = parse error (Markdown/HTML choke on '_' in protocol names or '<').
                # Retry ONCE as plain text so the message always delivers (no formatting
                # beats a silently-dropped alert). Fixes the recurring 400 glitch class.
                if exc.code == 400 and "parse_mode" in payload_dict:
                    log.warning("Telegram 400 (parse) — retrying as plain text")
                    payload_dict.pop("parse_mode", None)
                    payload = json.dumps(payload_dict).encode("utf-8")
                    continue
                log.warning("Telegram API error %s: %s", exc.code, exc.reason)
                _record_history(text, ok=False, error=f"HTTP {exc.code}: {exc.reason}")
                return False
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_err = exc
            except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
                last_err = exc

        log.warning("Telegram send failed after %d attempt(s): %s", 1 + RETRIES, last_err)
        _record_history(text, ok=False, error=str(last_err))
        return False


def send_message(text: str, parse_mode: str = "Markdown", actions: bool = True) -> bool:
    """POST the message to the Telegram Bot API.

    ``parse_mode`` defaults to ``"Markdown"`` (back-compat). Pass ``"HTML"`` for
    messages that contain HTML tags such as ``<b>`` — Telegram's legacy Markdown
    parser 400s on the ``_`` in protocol names (e.g. ``aave_v3``) and on ``<>``.

    ``actions`` (owner task 2026-08-07): when the message reads as a PROBLEM, action
    buttons are attached — «Починить» / «Нужно моё решение» / «Наблюдать» / «Так и надо»,
    one of them marked ⭐ рекомендую. A tap creates a tracker card (see
    ``spa_core.telegram.alert_actions``). This is the single wiring point on purpose:
    every SPA monitor sends through here, so buttons appear on ALL problem alerts and
    not only on the one module someone remembered to update.

    **Fail-CLOSED to the old behaviour:** anything not recognised as a problem (digests,
    ✅ pulses, reports) gets NO buttons and is sent byte-identically to before. Pass
    ``actions=False`` to force the old path.

    Fail-safe: missing credentials, HTTP or network errors → WARNING + False.
    One retry on network error. Never raises.
    """
    payload: dict = {"text": text, "parse_mode": parse_mode}
    if actions:
        try:
            from spa_core.telegram.alert_actions import register_alert

            registered = register_alert(text)
            if registered is not None:
                payload["reply_markup"] = json.dumps(registered[1])
        except Exception:  # noqa: BLE001 — кнопки не имеют права помешать тревоге
            log.debug("alert action buttons skipped", exc_info=True)
    return _post_message(payload)


def send_message_with_keyboard(text: str, keyboard: dict) -> bool:
    """POST the message with an inline keyboard to the Telegram Bot API.

    ``keyboard`` must be a dict ready to be JSON-serialised, e.g.::

        {"inline_keyboard": [[{"text": "X", "callback_data": "cmd_x"}]]}

    Fail-safe: any failure → WARNING + False. Never raises.
    """
    return _post_message({"text": text, "reply_markup": json.dumps(keyboard)})
