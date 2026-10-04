"""Зов ПРОИЗВОДИТЕЛЯ объявленного артефакта — отдельным процессом, с пином часов.

Заказ **G97 приказа владельца «Portfolio CIO»**, пункт 3 (поставлен ADR-510).

## Что делает зонд

Одно плечо — один процесс. В процессе: подменить класс ``datetime.datetime`` ДО
первого импорта ``spa_core`` (``pin_clock`` соседа ``_http_reader_probe``), затем
по очереди для каждого производителя:

1. снять байты объявленного артефакта и **удалить** файл — иначе «написал
   отметку» неотличимо от «отметка лежала тут и раньше» (урок
   ``assert_markup_produced`` в ``scripts/cycle_analytics_audit.py``);
2. позвать точку инъекции — без ``now=`` (плечо A) либо с ``now=<якорь>``
   (плечо B);
3. прочитать отметку, которую производитель написал САМ;
4. вернуть байты артефакта на место — вход соседа по населению не должен
   зависеть от порядка обхода.

Отметка плеча A обязана оказаться подменённым моментом: это ЗАМЕР у двери, а не
вера в переданный флаг. Не оказалась ⇒ у этой двери часы не подменились (своё
``time.time()``, свой класс, отметка из чужого файла), и строка обязана быть
**НЕ ИЗМЕРЕНО**, а не находкой.

## Почему по ПУТИ, а не ``-m``

``-m spa_core.monitoring...`` импортировал бы пакет ``spa_core`` раньше, чем
зонд успел бы что-нибудь закрепить, и плечо B стало бы копией плеча A — ложный
ноль, то есть fail-OPEN тише красной строки.

## Почему ответ пишется ПОСЛЕ КАЖДОГО модуля

Производитель — чужой код: он вправе уйти в сеть, зависнуть или уронить процесс.
Ответ, записанный один раз в конце, в этом случае теряет и то, что уже измерено,
а «арм умер» становится неотличимо от «ничего не измерено». Поэтому файл ответа
дописывается на каждом шаге, а срок каждого зова ограничен ``SIGALRM``.

Зонд только ЗОВЁТ и ЧИТАЕТ: капитал не двигается, пороги RiskPolicy v1.0,
стоп-кран, живой трек и ``landing/`` не трогаются. Зов идёт в ОДНОРАЗОВОМ дереве
(это проверяет родитель), поэтому запись производителя в его собственный
``data/`` безвредна по построению.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import sys

# Запуск ПО ПУТИ кладёт каталог скрипта первым в `sys.path`, и сосед
# `spa_core/monitoring/signal.py` затеняет стандартный `signal`. Снимать ДО
# остальных импортов (урок ADR-405): в `__main__` уже поздно. Сравниваются
# РАЗРЕШЁННЫЕ пути — дерево под `/tmp` на macOS есть ссылка на `/private/tmp`.
if __name__ == "__main__" and sys.path and (
        os.path.realpath(sys.path[0])
        == os.path.dirname(os.path.realpath(__file__))):
    del sys.path[0]

import importlib
import importlib.util
import json
import pathlib
import signal
from typing import Dict, List, Optional

#: Подменённые стенные часы (ISO-8601 с поясом) — ответ двери в ОБОИХ плечах.
FAKE_WALL_ENV = "SPA_STAMP_FAKE_WALL"

#: Якорь инъекции — значение ``now=`` в плече B (ISO-8601 с поясом).
ANCHOR_ENV = "SPA_STAMP_ANCHOR"

#: ``1`` ⇒ плечо B (звать с ``now=<якорь>``); иначе плечо A (звать без ``now``).
INJECT_ENV = "SPA_STAMP_INJECT"

#: Корень одноразового дерева, против которого идёт зов.
TREE_ENV = "SPA_STAMP_TREE"

#: Сколько ждать ОДНОГО производителя. Предел на зов, а не на плечо: иначе один
#: ушедший в сеть сосед забрал бы ответ у всех, кто стоит за ним в обходе.
CALL_TIMEOUT_S = 90

#: Ключи отметки, в порядке опроса. ``generated_at`` — канон (ADR-158); остальные
#: встречаются у более старых производителей. Какой ключ прочитан — ЧАСТЬ ответа:
#: «отметки нет вовсе» и «отметка лежит под другим именем» суть разные факты.
STAMP_KEYS = ("generated_at", "as_of", "timestamp", "generated", "measured_at")


class _CallTimeout(Exception):
    """Производитель не уложился в ``CALL_TIMEOUT_S``."""


def _load_pin_clock():
    """``pin_clock`` соседа — ПО ПУТИ, чтобы не импортировать пакет ``spa_core``.

    Обычный импорт втянул бы пакет целиком, то есть связал бы ``datetime`` в
    десятках модулей РАНЬШЕ подмены: плечо A и плечо B стали бы одним и тем же,
    а разность — нулём, который читается как ответ.
    """
    path = pathlib.Path(__file__).resolve().with_name("_http_reader_probe.py")
    spec = importlib.util.spec_from_file_location("_spa_http_reader_probe", path)
    if spec is None or spec.loader is None:            # pragma: no cover
        raise ImportError(f"сосед не загружен: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pin_clock


def door_answer() -> Optional[str]:
    """Что отвечает дверь часов ПОСЛЕ пина. Замер, а не вера в флаг."""
    import datetime as _dt

    try:
        return _dt.datetime.now(_dt.timezone.utc).isoformat()
    except BaseException as exc:                       # noqa: BLE001  # pragma: no cover
        return f"ERR {type(exc).__name__}: {exc}"


def read_stamp(doc) -> tuple[Optional[str], Optional[str]]:
    """Отметка документа и ИМЯ ключа, под которым она найдена.

    Документ не словарь либо ни одного известного ключа ⇒ ``(None, None)``:
    отсутствие отметки есть самостоятельное значение, а не пустая строка.
    """
    if not isinstance(doc, dict):
        return None, None
    for key in STAMP_KEYS:
        if key in doc and doc[key] is not None:
            return str(doc[key]), key
    return None, None


def _load_doc(path: pathlib.Path):
    """Прочитать артефакт. JSONL — ПОСЛЕДНЯЯ строка (отметку несёт она)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise ValueError("журнал пуст")
        return json.loads(lines[-1])
    return json.loads(text)


def call_producer(module: str, entry: str, artifact: pathlib.Path,
                  anchor, *, inject: bool) -> Dict[str, object]:
    """Один производитель: снять артефакт, позвать, прочитать отметку, вернуть.

    Возвращает запись замера. Ни одно исключение производителя наружу не идёт:
    упавший зов — исход с НАЗВАННОЙ причиной, а не конец обхода.
    """
    backup = artifact.read_bytes() if artifact.exists() else None
    row: Dict[str, object] = {"module": module, "entry": entry,
                              "artifact_existed_before": backup is not None,
                              "stamp": None, "stamp_key": None,
                              "wrote_artifact": False, "error": None}
    try:
        if artifact.exists():
            artifact.unlink()
    except OSError as exc:
        row["error"] = f"артефакт не удалён: {type(exc).__name__}: {exc}"
        return row

    previous = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.alarm(CALL_TIMEOUT_S)
    try:
        mod = importlib.import_module(module)
        func = getattr(mod, entry)
        if inject:
            func(now=anchor)
        else:
            func()
    except _CallTimeout:
        row["error"] = f"зов не уложился в {CALL_TIMEOUT_S} с"
    except BaseException as exc:                       # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"[:400]
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    if artifact.exists():
        row["wrote_artifact"] = True
        try:
            stamp, key = read_stamp(_load_doc(artifact))
            row["stamp"], row["stamp_key"] = stamp, key
        except (OSError, ValueError) as exc:
            row["error"] = (row["error"] or "") + \
                f" | артефакт не разобран: {type(exc).__name__}: {exc}"
    try:
        if backup is not None:
            artifact.write_bytes(backup)
        elif artifact.exists():
            artifact.unlink()
    except OSError as exc:                             # pragma: no cover
        row["error"] = (row["error"] or "") + f" | артефакт не возвращён: {exc}"
    return row


def _raise_timeout(signum, frame):                     # noqa: ARG001
    raise _CallTimeout()


def probe_plan(plan: List[dict], tree: pathlib.Path, anchor, *, inject: bool,
               out: pathlib.Path) -> Dict[str, dict]:
    """Обойти план, дописывая ответ ПОСЛЕ КАЖДОГО модуля."""
    answers: Dict[str, dict] = {}
    for item in plan:
        module = str(item["module"])
        row = call_producer(module, str(item["entry"]),
                            tree / str(item["artifact"]), anchor, inject=inject)
        answers[module] = row
        out.write_text(json.dumps({"door": door_answer(), "rows": answers},
                                  ensure_ascii=False), encoding="utf-8")
    return answers


def main(argv: List[str]) -> int:
    """``_artifact_stamp_clock_probe <plan.json> <out.json>``."""
    if len(argv) != 3:
        sys.stderr.write(
            "usage: _artifact_stamp_clock_probe <plan.json> <out.json>\n")
        return 2
    fake = os.environ.get(FAKE_WALL_ENV, "")
    anchor_iso = os.environ.get(ANCHOR_ENV, "")
    tree = pathlib.Path(os.environ.get(TREE_ENV) or ".").resolve()
    if not fake or not anchor_iso:
        sys.stderr.write(f"{FAKE_WALL_ENV}/{ANCHOR_ENV} не переданы\n")
        return 2

    pin_clock = _load_pin_clock()
    pin_clock(fake)                      # ДО первого импорта `spa_core`
    import datetime as _dt
    anchor = _dt.datetime.fromisoformat(anchor_iso)

    plan = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))
    out = pathlib.Path(argv[2])
    out.write_text(json.dumps({"door": door_answer(), "rows": {}},
                              ensure_ascii=False), encoding="utf-8")
    probe_plan(plan, tree, anchor,
               inject=os.environ.get(INJECT_ENV) == "1", out=out)
    return 0


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main(sys.argv))
