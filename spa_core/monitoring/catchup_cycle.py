"""spa_core/monitoring/catchup_cycle.py — ДОГОНЯЮЩИЙ дневной цикл (вариант A владельца).

Решение владельца **2026-09-17** (дословно «вариант A», карточка
`owner-decision-segodnyashnii-tsikl-treka-ne-zapuskalsya`, задание
`inbox-dogonyayuschii-dnevnoi-tsikl-storozh-pro`):

> выключенный в 08:00 Мак не должен стоить дня трека. Сторож пропусков сам запускает
> ДОГОНЯЮЩИЙ дневной цикл, если к 10:00 UTC цикла за текущие сутки ещё не было.

**Почему этого не делал существующий код, и почему это не дубль.** Самолечение
(`spa_core/monitoring/self_heal.py`, правило 3) и `gap_monitor --recover` (MP-101) уже
умеют догонять пропуск, но их порог — ВОЗРАСТ РАЗРЫВА (`CYCLE_GAP_HOURS = 28.0`), а не
ЧАС СУТОК. Ровно поэтому 17.09 день и повис: Мак загрузился в 16:56 местного,
`com.spa.daily_cycle` (`RunAtLoad=false`) пропуск не догоняет, `hours_since` дополз до
**26,3 ч** (`WARNING`, то есть НИЖЕ порога действия 28 ч), и день закрыла рука владельца
`launchctl kickstart` в 16:13Z. Возраст разрыва и час суток — два РАЗНЫХ вопроса: первый
отвечает «давно ли был цикл», второй — «есть ли цикл за СЕГОДНЯ», и только второй
закрывает пропуск в тот же день.

Второе отличие: `gap_monitor --recover` зовёт `cycle_runner.run_cycle` ПРЯМО В СВОЁМ
ПРОЦЕССЕ, а владелец назвал рамку «через ту же обёртку, что и плановый» — то есть
`launchctl kickstart` сервиса, чтобы замок цикла и `CYCLE_CALLER` были те же. Здесь
действие ровно одно: `launchctl kickstart -k gui/<uid>/com.spa.daily_cycle`.

Три исхода различимы (инв. #17) и за «чисто» ни один не выдаётся:

* **измерено, цикл за сегодня ЕСТЬ** ⇒ `cycle_present`, ничего не делать;
* **измерено, цикла за сегодня НЕТ** ⇒ `not_due` до порога, `launched` после него,
  `already_attempted` на повторном прогоне тех же суток;
* **НЕ ИЗМЕРЕНО** (снимок не прочитан · поля нет · отметка не разобрана) ⇒
  `not_measured`: ТРЕВОГА и НОЛЬ запусков. Запуск вслепую здесь был бы хуже молчания —
  он двигал бы трек по неизвестному состоянию.

**Не чаще одного догоняющего запуска в сутки**, и попытка учитывается по ПОПЫТКЕ, а не по
её успеху: неудачный `kickstart`, не оставляющий записи, превратил бы сторожа, который
крутится каждые 5 минут, в kickstart-петлю (тот же класс, что чинили ADR-400/R5/R6 в
`self_heal`). Неудача при этом не замолчана — она отдельный вердикт `launch_failed` с
тревогой.

Время — ВХОД (`now=`), и вход доходит до CLI (`--now`, ADR-897): обе стороны сравнения
(отметка снимка и «сколько сейчас») закрепляются сценой, иначе проверка краснела бы от
календаря. Неразбираемый `--now` — ОТКАЗ, а не молчаливый возврат к стенным часам.

LLM здесь запрещён; RiskPolicy, сам цикл и его содержимое не меняются — меняется только,
КТО его будит. Только stdlib, записи атомарные.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from spa_core.utils.observation import observed

_ROOT = Path(__file__).resolve().parents[2]

#: Час UTC, к которому цикл за текущие сутки обязан существовать. ЗНАЧЕНИЕ РЕШЕНИЯ
#: владельца от 17.09 («к 10:00 UTC»), а не настройка: менять его — новым ADR.
CATCHUP_HOUR_UTC = 10

#: Служба, которую будит догоняющий запуск. Та же, что ведёт плановый цикл.
DAILY_CYCLE_LABEL = "com.spa.daily_cycle"

#: Снимок, по которому судится «был ли цикл за сегодня». Тот же файл, по которому
#: `self_heal` считает возраст разрыва, — чтобы у двух правил был ОДИН источник.
CYCLE_STATUS_NAME = "paper_trading_status.json"

#: Журнал догоняющих запусков (своя запись, живой трек не трогается).
CATCHUP_STATUS_NAME = "catchup_cycle_status.json"

NOT_MEASURED = "not_measured"
CYCLE_PRESENT = "cycle_present"
NOT_DUE = "not_due"
ALREADY_ATTEMPTED = "already_attempted"
LAUNCHED = "launched"
LAUNCH_FAILED = "launch_failed"


class NotMeasured(Exception):
    """Вход назван, но не разобран — отвечать стенными часами ЗАПРЕЩЕНО."""


def parse_now(raw: str | None) -> _dt.datetime | None:
    """Момент, относительно которого судится «к 10:00 UTC», — ВХОД.

    ``None`` — входа не было, судят стенные часы: это БОЕВОЙ путь (сторож спрашивает
    «сколько сейчас» у машины). Пустое и неразбираемое значение — ОТКАЗ: подстановка
    календаря вместо названного момента и есть тот дефект, против которого вход написан
    (ADR-897).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        raise NotMeasured("--now дан пустым: момент НЕ НАЗВАН, а стенные часы "
                          "вместо названного момента не подставляются")
    try:
        moment = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NotMeasured(f"--now не разобран ({text!r}): {exc} — ожидается ISO-8601") from exc
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=_dt.timezone.utc)


def _data_dir(data_dir: str | os.PathLike[str] | None) -> Path:
    return Path(data_dir) if data_dir is not None else _ROOT / "data"


def observe_last_cycle_day(
        data_dir: str | os.PathLike[str] | None = None) -> tuple[str | None, str | None]:
    """UTC-день последнего цикла — либо ``None`` с НАЗВАННОЙ причиной «не измерено».

    Возвращает ``(день, None)`` при наблюдении и ``(None, причина)``, когда наблюдения
    НЕТ. ``None`` здесь никогда не значит «цикла не было»: «цикл был вчера» — это
    ЗНАЧЕНИЕ (день), а «снимка нет» — отсутствие наблюдения, и склеивать их значило бы
    разбудить цикл по неизвестному состоянию.
    """
    path = _data_dir(data_dir) / CYCLE_STATUS_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"снимок {path} не прочитан ({exc.__class__.__name__}: {exc})"
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        return None, f"снимок {path} не разобран как JSON ({exc})"
    ts = observed(doc, "last_cycle_ts", kind=str)
    if ts is None:
        return None, f"в снимке {path.name} нет наблюдения last_cycle_ts"
    try:
        moment = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError as exc:
        return None, f"last_cycle_ts={ts!r} не разобран как ISO-8601 ({exc})"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return moment.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d"), None


def read_last_attempt_day(
        data_dir: str | os.PathLike[str] | None = None) -> str | None:
    """UTC-день последней ПОПЫТКИ догоняющего запуска, или ``None``.

    Отсутствие журнала здесь — законное «попыток не было», а не «не измерено»: журнал
    ведёт только этот модуль, и до первого запуска его нет по построению.
    """
    path = _data_dir(data_dir) / CATCHUP_STATUS_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return observed(doc, "last_attempt_day", kind=str)


def decide(*, now: _dt.datetime, last_cycle_day: str | None,
           unmeasured_reason: str | None = None,
           last_attempt_day: str | None = None) -> dict[str, Any]:
    """Чистое решение: что делать и почему. Ничего не читает и ничего не пишет.

    Вынесено в отдельную функцию намеренно: вердикт обязан быть проверяем сценой без
    диска, launchd и сети, иначе «почему он не сработал 17.09» снова меряли бы глазами.
    """
    moment = now if now.tzinfo is not None else now.replace(tzinfo=_dt.timezone.utc)
    moment = moment.astimezone(_dt.timezone.utc)
    today = moment.strftime("%Y-%m-%d")
    base = {
        "now": moment.isoformat(),
        "today": today,
        "threshold_hour_utc": CATCHUP_HOUR_UTC,
        "last_cycle_day": last_cycle_day,
        "last_attempt_day": last_attempt_day,
        "launch": False,
    }
    if last_cycle_day is None:
        return {**base, "verdict": NOT_MEASURED, "alarm": True,
                "reason": ("состояние цикла НЕ ИЗМЕРЕНО: "
                           + (unmeasured_reason or "причина не названа")
                           + " — запуск вслепую не делается (инв. #17)")}
    if last_cycle_day >= today:
        return {**base, "verdict": CYCLE_PRESENT, "alarm": False,
                "reason": f"цикл за {today} уже есть (последний {last_cycle_day})"}
    if moment.hour < CATCHUP_HOUR_UTC:
        return {**base, "verdict": NOT_DUE, "alarm": False,
                "reason": (f"порог {CATCHUP_HOUR_UTC}:00 UTC ещё не наступил "
                           f"({moment.strftime('%H:%M')} UTC) — плановый цикл не опоздал")}
    if last_attempt_day == today:
        return {**base, "verdict": ALREADY_ATTEMPTED, "alarm": False,
                "reason": f"догоняющий запуск за {today} уже делался — не чаще одного в сутки"}
    return {**base, "verdict": LAUNCHED, "alarm": False, "launch": True,
            "reason": (f"цикла за {today} нет (последний {last_cycle_day}), "
                       f"{moment.strftime('%H:%M')} UTC ≥ {CATCHUP_HOUR_UTC}:00 — "
                       f"один догоняющий запуск {DAILY_CYCLE_LABEL}")}


def _uid() -> str:
    return str(os.getuid())


def _kickstart(label: str) -> bool:
    """Та же обёртка, что у планового цикла: сервис, а не прямой ``python -m``."""
    try:
        r = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{label}"],
                           capture_output=True, text=True, timeout=25)
        return r.returncode == 0
    except Exception:  # noqa: BLE001 — сторож не падает от действия
        return False


def _alert(message: str) -> None:
    """Тревога идёт через ЕДИНСТВЕННУЮ полномочную дверь push (как в self_heal)."""
    try:
        from spa_core.telegram import push_policy
        push_policy.push_critical(
            "core_agent_down", "CRITICAL", "SPA Catch-up cycle", message,
            dedup_key="catchup_cycle_unmeasured",
        )
    except Exception:  # noqa: BLE001
        pass


def _record_attempt(data_dir: Path, record: dict[str, Any]) -> None:
    path = data_dir / CATCHUP_STATUS_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        history = doc.get("history") if isinstance(doc, dict) else None
    except (OSError, ValueError):
        history = None
    history = [h for h in (history or []) if isinstance(h, dict)][-19:]
    history.append(record)
    from spa_core.utils.atomic import atomic_save
    atomic_save({
        "ts": record["now"],
        "last_attempt_day": record["today"],
        "last_verdict": record["verdict"],
        "threshold_hour_utc": CATCHUP_HOUR_UTC,
        "label": DAILY_CYCLE_LABEL,
        "history": history,
        "LLM_FORBIDDEN": True,
    }, str(path))


def run(*, now: _dt.datetime | None = None,
        data_dir: str | os.PathLike[str] | None = None,
        kickstart: Callable[[str], bool] | None = None,
        alert: Callable[[str], None] | None = None,
        write: bool = True) -> dict[str, Any]:
    """Одно наблюдение → одно решение → не больше одного действия.

    ``kickstart``/``alert`` — входы: сцена подменяет их и мерит ИСХОД (сколько запусков
    и каких), а не структуру кода. ``write=False`` — сухой прогон: журнал не трогается,
    действие не выполняется.
    """
    moment = now or _dt.datetime.now(_dt.timezone.utc)
    root = _data_dir(data_dir)
    day, why = observe_last_cycle_day(root)
    verdict = decide(now=moment, last_cycle_day=day, unmeasured_reason=why,
                     last_attempt_day=read_last_attempt_day(root))
    verdict["dry_run"] = not write
    if verdict["verdict"] == NOT_MEASURED:
        # Тревога — ДЕЙСТВИЕ наружу, поэтому сухой прогон её не отправляет: иначе
        # `--dry-run` писал бы владельцу, а «показать решение» и «разбудить человека»
        # перестали бы различаться. Вердикт при этом тот же, и код возврата тот же.
        if write:
            (alert or _alert)(
                f"догоняющий дневной цикл НЕ ИЗМЕРЕН: {verdict['reason']}")
        return verdict
    if not verdict["launch"]:
        return verdict
    if not write:
        return verdict
    _record_attempt(root, verdict)      # попытка учтена ДО действия: не kickstart-петля
    ok = (kickstart or _kickstart)(DAILY_CYCLE_LABEL)
    if not ok:
        verdict["verdict"] = LAUNCH_FAILED
        verdict["alarm"] = True
        verdict["reason"] = (f"kickstart {DAILY_CYCLE_LABEL} НЕ УДАЛСЯ — догоняющий цикл "
                             f"за {verdict['today']} не запущен; повтора сегодня не будет")
        (alert or _alert)(verdict["reason"])
        _record_attempt(root, verdict)
    return verdict


_EXIT = {
    CYCLE_PRESENT: 0,
    NOT_DUE: 0,
    ALREADY_ATTEMPTED: 0,
    LAUNCHED: 1,
    NOT_MEASURED: 2,
    LAUNCH_FAILED: 3,
}


def main(argv: list[str] | None = None) -> int:
    """Коды возврата: 0 — делать нечего · 1 — догоняющий цикл запущен ·
    2 — НЕ ИЗМЕРЕНО (тревога, ноль запусков) · 3 — запуск не удался."""
    p = argparse.ArgumentParser(
        prog="catchup_cycle",
        description="Догоняющий дневной цикл: если к 10:00 UTC цикла за сегодня не "
                    "было — ОДИН запуск через ту же обёртку (решение владельца 17.09).")
    p.add_argument("--data-dir", default=None,
                   help="каталог данных (умолчание — data/ своего дерева; ПЕЧАТАЕТСЯ)")
    p.add_argument("--now", default=None,
                   help="момент ISO-8601, относительно которого судится порог "
                        "(умолчание — стенные часы)")
    p.add_argument("--dry-run", action="store_true",
                   help="решение напечатать, действие НЕ выполнять")
    args = p.parse_args(argv)
    try:
        moment = parse_now(args.now)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    root = _data_dir(args.data_dir)
    print(f"каталог данных: {root}" + (" (УМОЛЧАНИЕ)" if args.data_dir is None else ""))
    verdict = run(now=moment, data_dir=root, write=not args.dry_run)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return _EXIT.get(str(verdict.get("verdict")), 2)


if __name__ == "__main__":
    sys.exit(main())
