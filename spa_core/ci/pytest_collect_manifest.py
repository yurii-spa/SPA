#!/usr/bin/env python3
"""Перечень собранного: какие тесты pytest СОБРАЛ и какие файлы собрать НЕ СМОГ.

**Зачем (контрольный прогон по шардам, `.github/workflows/ci-control.yml`).** Полный набор
(~106 000 тестов) не помещается в одну джобу Actions: прогон `SPA CI` 38873867566 (джоба
116884127339, `9b7e6442f`) шёл 6 ч и был снят пределом джобы на `[ 94%]`, шаг
`spa_core/tests/` в `SPA Tests` 38877303508 — снят `timeout-minutes: 240`. Поэтому набор
режется на шарды, и тогда вопрос «не потерялся ли кто-то по дороге» становится главным:
союз шардов обязан равняться населению, иначе зелёный итог — это зелёный ПОДНАБОР.

Ответ на этот вопрос нельзя брать из текста `--collect-only -q`: формат вывода — интерфейс
для глаз, он меняется между версиями pytest, а ошибки сборки печатаются отдельным разделом.
Плагин пишет то, что pytest действительно держит в руках: `session.items` после сборки и
каждый отчёт сборки с ошибкой.

**Пишет ДВАЖДЫ, и это существенно.** Строки ошибок сборки ложатся на диск сразу (по мере
сборки, со сбросом буфера), а итоговый перечень — в `pytest_collection_finish`. Шард,
снятый ПОСЛЕ сборки, оставляет полный перечень собранного; шард, снятый ВО ВРЕМЯ сборки,
оставляет файл без итоговой записи — и читатель обязан назвать это «перечня нет», а не
«собрано ноль».

Инертен без переменной ``SPA_PYTEST_MANIFEST`` (тот же договор, что у
``spa_core.ci.pytest_stream_record``). Вердикта не выносит. Только stdlib (инв. #4).

Формат файла — JSON Lines:

    {"e":"collect_error","n":"<путь/nodeid>","msg":"<первая строка>"}
    {"e":"collected","count":N,"nodeids":[...]}
"""
from __future__ import annotations

import json
import os

MANIFEST_ENV = "SPA_PYTEST_MANIFEST"
_MSG_LIMIT = 300

_FH = None


def _emit(event: dict) -> None:
    if _FH is None:
        return
    _FH.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    _FH.flush()


def _last_line(text: object) -> str:
    s = str(text).strip()
    return s.splitlines()[-1][:_MSG_LIMIT] if s else ""


def pytest_configure(config) -> None:                        # noqa: ANN001, ARG001
    global _FH
    path = os.environ.get(MANIFEST_ENV)
    if not path:
        _FH = None
        return
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Перезапись, а не дозапись: перечень — свойство ОДНОЙ сессии; склеить две значило бы
    # сосчитать один тест дважды и выдать удвоенное население за полное.
    _FH = open(path, "w", encoding="utf-8")


def pytest_collectreport(report) -> None:                    # noqa: ANN001
    if _FH is None or not report.failed:
        return
    _emit({"e": "collect_error", "n": report.nodeid,
           "msg": _last_line(getattr(report, "longrepr", "") or "")})


def pytest_collection_finish(session) -> None:               # noqa: ANN001
    if _FH is None:
        return
    nodeids = [item.nodeid for item in session.items]
    _emit({"e": "collected", "count": len(nodeids), "nodeids": nodeids})


def pytest_unconfigure(config) -> None:                      # noqa: ANN001, ARG001
    global _FH
    if _FH is not None:
        try:
            _FH.close()
        finally:
            _FH = None


def read_manifest(path: str) -> dict:
    """Разобрать файл плагина. Нет итоговой строки ⇒ ``collected`` = ``None`` (не ноль).

    Возвращает ``{"collected": list | None, "collect_errors": [{"n", "msg"}], "why": str}``;
    ``why`` непуст, когда перечня нет, и называет причину словами (инв. #17).
    """
    out: dict = {"collected": None, "collect_errors": [], "why": ""}
    if not os.path.exists(path):
        out["why"] = f"файла перечня нет: {path}"
        return out
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                out["why"] = f"битая строка перечня в {path}"
                continue
            if ev.get("e") == "collect_error":
                out["collect_errors"].append({"n": ev.get("n", ""), "msg": ev.get("msg", "")})
            elif ev.get("e") == "collected":
                out["collected"] = list(ev.get("nodeids") or [])
    if out["collected"] is None and not out["why"]:
        out["why"] = f"сборка не дошла до конца: итоговой строки в {path} нет"
    return out
