"""Owner Remote shared logic — one intent classifier + investment-slice read model.

The classifier here is the AUTHORITATIVE safety gate for every server-side/Telegram decision.
The web UI's JS mirror (studio_shell/surfaces.js::classifyIntent) is a client-side hint locked to
this module by a parity test (studio_shell/test_mobile_surfaces.py). RED must win over YELLOW/GREEN.
"""
from .intent import ZONES, classify  # noqa: F401
