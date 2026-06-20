"""
SPA API package — v0.17 (MP-1530).

Public surface:
  app          — FastAPI application (uvicorn spa_core.api.server:app)
  SPAApiClient — REST client with HTTP + file fallback (stdlib only)
  APIAuth      — HMAC token generation/verification
  get_auth     — module-level APIAuth singleton

Note: 'app' requires fastapi installed; SPAApiClient/APIAuth use only stdlib.
"""

from .client import SPAApiClient
from .auth import APIAuth, get_auth

try:
    from .server import app
except ImportError:
    app = None  # fastapi not installed; install: pip install fastapi uvicorn

__all__ = [
    "app",
    "SPAApiClient",
    "APIAuth",
    "get_auth",
]
