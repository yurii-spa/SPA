"""Аллокатор образца 09.11 — ДО ADR-976 — как СЦЕНА, а не как память.

ADR-969 (ось C §26) нашёл источник доказательности, который не старел вовсе:
ветка снимка оркестратора в ``_load_evidenced_apy`` окна свежести не применяла.
ADR-975/976 исполнили ответ владельца 10.11 (вариант 1), и живой аллокатор этот
дефект больше не несёт. Чтобы прибор §26 и проба ``snapshot_evidence_ages_out``
сохранили контроль В ОБЕ СТОРОНЫ (правило ``.claude/rules/acceptance.md`` п. 3),
прежний исход обязан оставаться ДОСТИЖИМЫМ — и достигается он не памятью о старом
коде, а этой подменой: ветка снимка здесь намеренно игнорирует ``now``, ветка
``adapter_status`` идёт через настоящую дверь.

Использование::

    from spa_core.tests._never_aging_allocator import install
    install(monkeypatch)          # прибор §26 увидит «аллокатор до ADR-976»
"""
from __future__ import annotations

import json
from pathlib import Path

from spa_core.allocator import allocator as _real


class NeverAgingAllocator:
    """Двойник ``spa_core.allocator.allocator`` с нестареющей веткой снимка."""

    _EVIDENCE_MAX_AGE_H = _real._EVIDENCE_MAX_AGE_H

    @staticmethod
    def _load_evidenced_apy(orchestrator_path, adapter_status_path=None, now=None):
        out = {}
        try:
            doc = json.loads(Path(orchestrator_path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — сцена, как и оригинал, не падает
            doc = {}
        for a in (doc.get("adapters") or []) if isinstance(doc, dict) else []:
            if isinstance(a, dict) and a.get("live_data") and a.get("protocol"):
                try:
                    out[str(a["protocol"])] = (float(a["apy_pct"]) / 100.0, "orchestrator_live")
                except (TypeError, ValueError):
                    continue
        if adapter_status_path is not None:
            real = _real._load_evidenced_apy(orchestrator_path, adapter_status_path, now=now)
            for name, (dec, src) in real.items():
                if src != "orchestrator_live":
                    out[name] = (dec, src)
        return out

    @staticmethod
    def _load_evidenced_tvl(adapter_status_path, now=None):
        return _real._load_evidenced_tvl(adapter_status_path, now=now)


def install(monkeypatch) -> NeverAgingAllocator:
    """Подставить двойника туда, откуда прибор §26 берёт аллокатор."""
    import spa_core.allocator as pkg
    stub = NeverAgingAllocator()
    monkeypatch.setattr(pkg, "allocator", stub)
    return stub
