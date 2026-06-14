"""SPA Orchestrator package.

Содержит:
  * M4 LangGraph-style граф агентов (``SPAOrchestrator``, ``SPAState``) — legacy,
    импортируется как top-level пакет ``orchestrator`` (со ``spa_core`` на sys.path);
  * SPA-V386 adapter-оркестратор (``run_orchestrator``, ``OrchestratorResult``) —
    импортируется как ``spa_core.orchestrator.adapter_orchestrator``.

Legacy-импорты обёрнуты в try/except, чтобы пакет грузился под обоими именами
(``orchestrator`` и ``spa_core.orchestrator``) — иначе адаптерный оркестратор
нельзя было бы импортировать как ``spa_core.orchestrator.*``.
"""

__all__ = []

try:  # legacy M4 граф — доступен только при импорте пакета как ``orchestrator``.
    from orchestrator.graph import SPAOrchestrator
    from orchestrator.state import SPAState, initial_state

    __all__ += ["SPAOrchestrator", "SPAState", "initial_state"]
except Exception:  # noqa: BLE001 — под ``spa_core.orchestrator`` top-level пакета нет.
    pass
