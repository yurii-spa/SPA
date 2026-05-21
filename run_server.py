#!/usr/bin/env python3
"""
SPA local server quick-start.

Usage:
    python run_server.py

Starts the FastAPI server on http://localhost:8765
Swagger UI: http://localhost:8765/docs
WebSocket:  ws://localhost:8765/ws/agents

The dashboard (index.html) auto-detects this server and switches
from static JSON polling to the live API.
"""
import subprocess
import sys
import os

# Always run from the project root so relative paths resolve correctly
os.chdir(os.path.dirname(os.path.abspath(__file__)))

subprocess.run([
    sys.executable, "-m", "uvicorn",
    "spa_core.api.server:app",
    "--reload",
    "--port", "8765",
    "--host", "0.0.0.0",
])
