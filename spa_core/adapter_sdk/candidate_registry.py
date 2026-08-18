"""candidate_registry.py — ОДНО определение честного чтения реестра кандидатов.

Реестр ``data/candidate_registry.json`` пишет :mod:`spa_core.adapter_sdk.discovery`.
Читателей у него несколько, и до цикла #288 каждый читал его сам, своим кодом,
со своей же аварией: **отсутствующий реестр возвращался как пустой список**, то
есть «мы ни разу не смотрели» приезжало к потребителю неотличимо от «посмотрели
и не нашли ничего достойного».

Цикл #283 вылечил это у ОДНОГО читателя (:func:`spa_core.agents.alpha_agent.candidate_set`)
— и ровно так же, как в классе «сторож отвечает не на тот вопрос», честность
осталась внутри одного модуля: второй читатель
(:func:`spa_core.agents.protocol_research_agent.candidate_set`) продолжал
конфлатить, а третий (:mod:`spa_core.scheduler.loop_scheduler`) выбрасывал уже
готовую честность производителя, считая ``len(candidates)``.

Поэтому чтение живёт ЗДЕСЬ, в одном месте, у семьи писателя (схему определяет
тот, кто её пишет), а читатели делегируют. Прецедент — ``spa_core/risk/tvl_floor.py``
(«у порога TVL одно определение»): две копии одной проверки расходятся не
«если», а «когда».

Замер прода на 2026-08-18 (цикл #288, перепроверен своим прогоном, а не принят
у трёх умерших сессий): ``data/candidate_registry.json`` **не существует**, и ни
один plist в ``launchd/`` и ни один скрипт в ``scripts/`` не запускает
``discovery`` — у реестра нет писателя вовсе. Значит ``measured=False`` — это
не редкий угол, а СЕГОДНЯШНЕЕ состояние прода на каждом прогоне.

Stdlib only. Ничего не пишет — только читает.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = ["REGISTRY_FILENAME", "read_candidate_registry"]

REGISTRY_FILENAME = "candidate_registry.json"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


def read_candidate_registry(data_dir: str | os.PathLike | None = None) -> dict:
    """Кандидаты от discovery ВМЕСТЕ с честностью замера.

    Ключи
    -----
    ``items``    — список кандидатов-словарей (всегда список, даже когда не измерено);
    ``measured`` — False, если реестр не прочитан (нет файла / нечитаем / не та
                   форма). Это **НЕ** «кандидатов ноль»;
    ``reason``   — почему не измерен, словами (пусто при ``measured=True``).

    Присутствующий реестр с пустым списком — ИЗМЕРЕННЫЙ ноль
    (``measured=True``, ``items=[]``), и это другое состояние: там discovery
    отработал и честно никого не принёс.

    Функция никогда не бросает: нечитаемый реестр — это ``measured=False`` с
    названной причиной, а не исключение у потребителя.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / REGISTRY_FILENAME

    if not path.exists():
        return {"items": [], "measured": False,
                "reason": f"реестр кандидатов не найден ({path.name}) — "
                          "discovery ни разу не отработал в этом дереве"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"items": [], "measured": False,
                "reason": f"реестр кандидатов нечитаем ({path.name}: {type(exc).__name__})"}

    if isinstance(doc, list):
        return {"items": [c for c in doc if isinstance(c, dict)],
                "measured": True, "reason": ""}
    if not isinstance(doc, dict):
        return {"items": [], "measured": False,
                "reason": (f"реестр кандидатов не объект и не список "
                           f"({path.name}: {type(doc).__name__})")}

    raw = doc.get("candidates")
    if raw is None:
        return {"items": [], "measured": False,
                "reason": f"в реестре кандидатов нет ключа candidates ({path.name})"}
    if not isinstance(raw, list):
        return {"items": [], "measured": False,
                "reason": (f"ключ candidates не список ({path.name}: "
                           f"{type(raw).__name__})")}
    return {"items": [c for c in raw if isinstance(c, dict)],
            "measured": True, "reason": ""}
