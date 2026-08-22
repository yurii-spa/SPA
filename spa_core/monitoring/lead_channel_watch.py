#!/usr/bin/env python3
"""Сторож канала заявок: узнает ли владелец, что кто-то оставил контакт на сайте.

Решение владельца 2026-08-22 (карточка `owner-decision-prover-odno-pole-dohodyat-li-do-tebya-za`,
вариант 1): «канал настроен — поставь сторожа, который закричит, если он ОТВАЛИТСЯ потом».

Почему сторож понадобился, хотя сторожей Телеграма уже два
------------------------------------------------------------------------------
Каждый существующий отвечает ЧЕСТНО и мимо — наш родовой класс (fail-OPEN monitor):

* `telegram_health` (ADR-077) — «бот жив, поллер один, маячок свежий». Про то, доедет ли
  до владельца ЗАЯВКА С САЙТА, не знает ничего: заявку шлёт не бот, а apiserver.
* `agent_health_monitor` — «процесс apiserver жив». Живой процесс с пустой связкой ключей
  принимает заявки и молча их теряет.
* `site_freshness` — «числа на сайте не протухли». Про форму не знает вовсе.

Вопрос ЭТОГО сторожа ровно один: **если человек оставит заявку прямо сейчас, дойдёт ли она
до владельца?** Ответ собирается из трёх измерений, и ни одно не заменяет другие.

Что измеряется — и какую настоящую аварию каждое ловит
------------------------------------------------------------------------------
===================  =========================================================
Проба                Авария, которую она ловит
===================  =========================================================
`credentials`        связка ключей пуста/переименована ⇒ отправитель не достаёт
                     токен ⇒ отправка возвращает False ⇒ заявка ложится в файл,
                     владелец не узнаёт НИЧЕГО. Спрашивается АВТОРИТЕТ
                     (`push_policy.credentials_status`), а не транспорт: инвариант
                     «одна дверь в чат владельца» намеренно запрещает импорт
                     транспорта всем вне списка, и обходить его ради «я же только
                     читаю» — значит открыть дверь следующему «только читающему»
`tier1_key`          `pilot_request` выпал из `TIER1_WHITELIST` ⇒ мгновенный
                     пинг о крупной заявке молча демотится в дайджест
`oneshot_key`        `pilot_request` выпал из `ONESHOT_KEYS` ⇒ ВТОРАЯ заявка
                     глохнет edge-триггером как «всё ещё плохо» (ровно тот
                     дефект, из-за которого `golive_ready` перевели в one-shot)
`wiring`             обработчик `/api/pilot/request` перестал звать
                     `_notify_owner_telegram` — «правь проводку, а не детали»:
                     удалённый вызов оставляет все части исправными и зелёными
===================  =========================================================

Fail-CLOSED и границы честности
------------------------------------------------------------------------------
* Не смогли ИЗМЕРИТЬ (нет `security` — не macOS, ушёл в CI, нет исходника) ⇒ ``UNCHECKED``.
  «Не измерено» никогда не равно ``OK`` и никогда не равно ``BROKEN``.
* Сторож НЕ утверждает, что конкретная заявка доехала: он измеряет МАРШРУТ, а не факт
  доставки одного сообщения. Проверять доставку можно только отправив сообщение, а
  сторож, который ради проверки звонит владельцу, — сам источник спама (ADR-084).
* Секретов наружу не отдаёт: пробы возвращают только булево «достаётся ли», никогда
  значение токена (инвариант #7).

Куда он кричит — и почему по-разному
------------------------------------------------------------------------------
Тяжесть у проб РАЗНАЯ, и это не осторожность, а разные аварии:

* `credentials` — авария ВНЕШНЯЯ и тихая (связку ключей чистит человек или ротация),
  заявки теряются по-настоящему ⇒ CRITICAL. Честная оговорка: если связка пуста, то и
  сам этот крик Телеграмом не доедет — его доставит `push_policy` повтором, когда канал
  вернётся (`entry_pushed=False` ⇒ retry), а про сам факт немоты кричит `telegram_down`.
* `tier1_key` / `oneshot_key` / `wiring` — это НАША доставка, наш собственный рефакторинг.
  Звать владельца на «мы сами себе сломали проводку» запрещено прецедентом ADR-084
  (штатная самопочинка не зовёт владельца) ⇒ WARNING в отчёте здоровья + дайджест,
  плюс красный тест в наборе.

Только stdlib. Не гейт, не money-path, LLM здесь запрещён (инвариант #3).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

log = logging.getLogger("spa.monitoring.lead_channel_watch")

OK = "OK"
BROKEN = "BROKEN"
UNCHECKED = "UNCHECKED"

#: Ключ Tier-1, которым apiserver пингует владельца о крупной заявке (ADR-OWN-2026-07-lead-pings).
LEAD_EVENT_KEY = "pilot_request"

#: Маршрут сайта → владелец: путь эндпойнта и имя функции-уведомителя в нём.
LEAD_ENDPOINT_PATH = "/api/pilot/request"
LEAD_NOTIFIER_NAME = "_notify_owner_telegram"

#: Тяжесть каждой пробы, когда она BROKEN. Разная по построению — см. докстринг модуля.
PROBE_SEVERITY: dict[str, str] = {
    "credentials": "CRITICAL",
    "tier1_key": "WARNING",
    "oneshot_key": "WARNING",
    "wiring": "WARNING",
}

STATUS_FILENAME = "lead_channel_status.json"


@dataclass
class Probe:
    """Один измеренный вопрос. ``detail`` — почему именно такой вердикт."""

    name: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "severity_if_broken": PROBE_SEVERITY.get(self.name, "WARNING")}


@dataclass
class Verdict:
    status: str
    probes: list[Probe] = field(default_factory=list)
    checked_at: str = ""

    # ── читатели ─────────────────────────────────────────────────────────────
    @property
    def broken(self) -> list[Probe]:
        return [p for p in self.probes if p.status == BROKEN]

    @property
    def unchecked(self) -> list[Probe]:
        return [p for p in self.probes if p.status == UNCHECKED]

    @property
    def severity(self) -> Optional[str]:
        """Худшая тяжесть среди СЛОМАННЫХ проб; None — ломать нечего."""
        if any(PROBE_SEVERITY.get(p.name) == "CRITICAL" for p in self.broken):
            return "CRITICAL"
        return "WARNING" if self.broken else None

    def summary(self) -> str:
        if self.status == OK:
            return "канал заявок исправен: креды достаются, ключ Tier-1 на месте, проводка цела"
        parts = [f"{p.name}: {p.detail}" for p in self.broken] or \
                [f"{p.name}: {p.detail}" for p in self.unchecked]
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "severity": self.severity,
            "summary": self.summary(),
            "probes": [p.to_dict() for p in self.probes],
        }


# ── пробы ────────────────────────────────────────────────────────────────────
def probe_credentials(
    *,
    creds_status: Optional[Callable[[], dict]] = None,
    keychain_available: Optional[Callable[[], bool]] = None,
) -> Probe:
    """Достаются ли креды ТЕМ ЖЕ кодом, которым их достаёт настоящий отправитель.

    Спрашивается АВТОРИТЕТ (`push_policy.credentials_status`), а не транспорт напрямую:
    инвариант «одна дверь в чат владельца» (`test_no_rogue_telegram_senders`) намеренно
    запрещает сам импорт транспорта кому бы то ни было вне списка, и обходить его ради
    «я же только читаю» — значит открыть дверь следующему, кто «только читает». Копии
    логики при этом нет: авторитет отвечает своим же кодом, тем, которым отправляет.

    Наружу отдаётся только «достаётся/нет» — значение секрета не возвращается никогда.
    """
    if keychain_available is None:
        keychain_available = lambda: shutil.which("security") is not None  # noqa: E731
    if not keychain_available():
        return Probe("credentials", UNCHECKED,
                     "нет утилиты `security` (не macOS / чужая среда) — связку ключей не спросить")
    if creds_status is None:
        try:
            from spa_core.telegram import push_policy
        except Exception as exc:  # noqa: BLE001
            return Probe("credentials", UNCHECKED, f"push_policy не импортируется: {exc!r}")
        creds_status = push_policy.credentials_status
    try:
        status = creds_status()
    except Exception as exc:  # noqa: BLE001
        return Probe("credentials", UNCHECKED, f"проба сорвалась ({exc!r})")
    ok = (status or {}).get("ok")
    if ok is None:
        return Probe("credentials", UNCHECKED,
                     f"креды не измерены: {(status or {}).get('error')}")
    if not ok:
        missing = ", ".join((status or {}).get("missing") or []) or "не названо какие"
        return Probe("credentials", BROKEN,
                     "в связке ключей нет " + missing +
                     " — заявка ляжет в файл, владелец не узнает")
    return Probe("credentials", OK, "оба ключа достаются из связки")


def probe_route_keys(
    *,
    whitelist: Optional[frozenset] = None,
    oneshot: Optional[frozenset] = None,
) -> list[Probe]:
    """Дожил ли ключ `pilot_request` до Tier-1 и до one-shot набора `push_policy`."""
    if whitelist is None or oneshot is None:
        try:
            from spa_core.telegram import push_policy
        except Exception as exc:  # noqa: BLE001
            detail = f"push_policy не импортируется: {exc!r}"
            return [Probe("tier1_key", UNCHECKED, detail), Probe("oneshot_key", UNCHECKED, detail)]
        whitelist = push_policy.TIER1_WHITELIST if whitelist is None else whitelist
        oneshot = push_policy.ONESHOT_KEYS if oneshot is None else oneshot
    tier1 = (
        Probe("tier1_key", OK, f"{LEAD_EVENT_KEY} в TIER1_WHITELIST")
        if LEAD_EVENT_KEY in whitelist else
        Probe("tier1_key", BROKEN,
              f"{LEAD_EVENT_KEY} выпал из TIER1_WHITELIST — крупная заявка молча уйдёт в дайджест")
    )
    one = (
        Probe("oneshot_key", OK, f"{LEAD_EVENT_KEY} в ONESHOT_KEYS")
        if LEAD_EVENT_KEY in oneshot else
        Probe("oneshot_key", BROKEN,
              f"{LEAD_EVENT_KEY} выпал из ONESHOT_KEYS — ВТОРАЯ заявка заглохнет edge-триггером")
    )
    return [tier1, one]


def _endpoint_source(source: Optional[str], source_path: Optional[Path]) -> tuple[Optional[str], str]:
    if source is not None:
        return source, "<переданный текст>"
    path = source_path
    if path is None:
        try:
            from spa_core.api.routers import interest
            path = Path(interest.__file__)
        except Exception as exc:  # noqa: BLE001
            return None, f"модуль эндпойнта не найден: {exc!r}"
    try:
        return Path(path).read_text(encoding="utf-8"), str(path)
    except Exception as exc:  # noqa: BLE001
        return None, f"исходник эндпойнта не читается ({path}): {exc!r}"


def probe_wiring(*, source: Optional[str] = None, source_path: Optional[Path] = None) -> Probe:
    """Зовёт ли обработчик `/api/pilot/request` уведомитель владельца.

    Проверяется ПРОВОДКА, а не наличие деталей: удалённый вызов оставляет и уведомитель,
    и `push_policy`, и креды в полном порядке — все их тесты остаются зелёными, а владелец
    перестаёт получать заявки. Разбор по AST, не по подстроке: упоминание имени в
    комментарии или в докстринге проводкой не является.
    """
    text, where = _endpoint_source(source, source_path)
    if text is None:
        return Probe("wiring", UNCHECKED, where)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return Probe("wiring", UNCHECKED, f"исходник эндпойнта не разбирается ({where}): {exc!r}")

    handler: Optional[ast.FunctionDef] = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            for arg in dec.args:
                if isinstance(arg, ast.Constant) and arg.value == LEAD_ENDPOINT_PATH:
                    handler = node
                    break
            if handler is not None:
                break
        if handler is not None:
            break
    if handler is None:
        return Probe("wiring", BROKEN,
                     f"в {where} нет обработчика {LEAD_ENDPOINT_PATH} — форма сайта пишет в никуда")
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        if name == LEAD_NOTIFIER_NAME:
            return Probe("wiring", OK,
                         f"{LEAD_ENDPOINT_PATH} зовёт {LEAD_NOTIFIER_NAME}()")
    return Probe("wiring", BROKEN,
                 f"обработчик {LEAD_ENDPOINT_PATH} больше не зовёт {LEAD_NOTIFIER_NAME}() — "
                 "заявка сохранится, владелец не узнает")


# ── сводный вердикт ──────────────────────────────────────────────────────────
def check(
    *,
    now: Optional[datetime] = None,
    creds_status: Optional[Callable[[], dict]] = None,
    keychain_available: Optional[Callable[[], bool]] = None,
    whitelist: Optional[frozenset] = None,
    oneshot: Optional[frozenset] = None,
    source: Optional[str] = None,
    source_path: Optional[Path] = None,
) -> Verdict:
    """Собрать вердикт по каналу заявок. Никогда не бросает.

    Агрегация fail-CLOSED: хоть одна ``BROKEN`` ⇒ ``BROKEN``; иначе хоть одна
    ``UNCHECKED`` ⇒ ``UNCHECKED``; ``OK`` только когда измерено ВСЁ и всё цело.
    """
    probes: list[Probe] = []
    try:
        probes.append(probe_credentials(creds_status=creds_status,
                                        keychain_available=keychain_available))
        probes.extend(probe_route_keys(whitelist=whitelist, oneshot=oneshot))
        probes.append(probe_wiring(source=source, source_path=source_path))
    except Exception as exc:  # noqa: BLE001 — сторож не имеет права ронять вызвавшего
        log.warning("lead_channel_watch: проба сорвалась: %s", exc)
        probes.append(Probe("watch_self", UNCHECKED, f"сторож сорвался: {exc!r}"))
    if any(p.status == BROKEN for p in probes):
        status = BROKEN
    elif any(p.status == UNCHECKED for p in probes):
        status = UNCHECKED
    else:
        status = OK
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return Verdict(status=status, probes=probes, checked_at=stamp)


def write_status(verdict: Verdict, *, data_dir: Optional[Path] = None) -> Optional[Path]:
    """Положить вердикт в `data/lead_channel_status.json` атомарно. Никогда не бросает."""
    try:
        from spa_core.utils.atomic import atomic_save
        root = Path(data_dir) if data_dir is not None else Path(__file__).resolve().parents[2] / "data"
        root.mkdir(parents=True, exist_ok=True)
        path = root / STATUS_FILENAME
        atomic_save(verdict.to_dict(), str(path))
        return path
    except Exception as exc:  # noqa: BLE001
        log.warning("lead_channel_watch: статус не записан: %s", exc)
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI. Коды возврата: 0 — OK, 1 — не измерено, 2 — сломано (fail-CLOSED)."""
    p = argparse.ArgumentParser(description="Сторож канала заявок с сайта (заявка → владелец).")
    p.add_argument("--json", action="store_true", help="печатать вердикт как JSON")
    p.add_argument("--data-dir", default=None, help="куда писать статус (по умолчанию <repo>/data)")
    p.add_argument("--no-write", action="store_true", help="не писать файл статуса")
    a = p.parse_args(argv)
    verdict = check()
    if not a.no_write:
        write_status(verdict, data_dir=Path(a.data_dir) if a.data_dir else None)
    if a.json:
        print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{verdict.status}: {verdict.summary()}")
        for probe in verdict.probes:
            print(f"  [{probe.status:9s}] {probe.name:12s} {probe.detail}")
    return {OK: 0, UNCHECKED: 1, BROKEN: 2}[verdict.status]


if __name__ == "__main__":
    sys.exit(main())
