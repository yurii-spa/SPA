# LLM_FORBIDDEN
"""
SPA Tournament package.

Exports
-------
TournamentEngine   — daily lifecycle manager (tournament_engine.py)
TournamentTelegram — Telegram notification sender (tournament_telegram.py)
"""
# LLM_FORBIDDEN

from spa_core.tournament.tournament_engine import TournamentEngine, PROMOTION_CRITERIA, PHASES
from spa_core.tournament.tournament_telegram import TournamentTelegram

__all__ = [
    "TournamentEngine",
    "TournamentTelegram",
    "PROMOTION_CRITERIA",
    "PHASES",
]
