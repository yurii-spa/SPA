"""consumption_receipts.py — квитанции потребления артефактов (ADR-066, Фаза 2).

Протокол, превращающий «кто-то читает отчёты» из надежды в проверяемый факт:
потребитель, УСПЕШНО прочитавший артефакт, дописывает строку в append-only
журнал `data/consumption_receipts.jsonl`:

    {"artifact": "data/investment_os/quant.json",
     "consumer": "orchestrator_protocol",
     "consumed_at": "<UTC ISO>",
     "producer_generated_at": "<отметка свежести прочитанного>"}

Правила честности:
  - ресит пишется ТОЛЬКО после фактического успешного чтения — никогда авансом
    и никогда за отсутствующий файл (иначе B3 сторожа превращается в театр);
  - журнал append-only: одна строка = одно событие потребления; никто не
    редактирует и не переписывает историю;
  - отказ записи НЕ валит потребителя (fail-open на границе: цикл/дайджест
    важнее квитанции) — но возвращается False, молчаливого успеха нет.

Читатель журнала — spa_core.monitoring.architecture_conformance.load_receipts
(проверка B3). LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os

from spa_core.monitoring.architecture_conformance import REPO_ROOT, artifact_timestamp

RECEIPTS_REL = os.path.join("data", "consumption_receipts.jsonl")


def receipts_path(root: str = REPO_ROOT) -> str:
    return os.path.join(root, RECEIPTS_REL)


def write_receipt(artifact_rel: str, consumer: str, *,
                  root: str = REPO_ROOT,
                  now: dt.datetime | None = None) -> bool:
    """Записать квитанцию о СОСТОЯВШЕМСЯ потреблении artifact_rel.

    Возвращает True при успехе. Если артефакта нет на диске — квитанция НЕ
    пишется (False): нельзя заквитовать то, чего не читал.
    """
    try:
        produced = artifact_timestamp(artifact_rel, root)
        if produced is None:
            return False
        rec = {
            "artifact": artifact_rel.replace(os.sep, "/"),
            "consumer": consumer,
            "consumed_at": (now or dt.datetime.now(dt.timezone.utc)).isoformat(),
            "producer_generated_at": produced.isoformat(),
        }
        path = receipts_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False)
        # O_APPEND: одна короткая строка — атомарно на POSIX
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception:  # noqa: BLE001 — квитанция не смеет валить потребителя
        return False
