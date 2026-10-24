"""Model-independent roles: one provider contract, explicit role→provider configuration (ADR-OWN-2026-10-23).

# LLM_FORBIDDEN

STUDIO-OS-MODELS-01, increment 2. Not a production router: the repository configuration assigns no
provider to any role, so nothing is routed unless a caller names a provider explicitly. Never used by
risk / execution / monitoring / kill components.
"""
from .contract import (HARD_MAX_ATTEMPTS, STATUSES, UNKNOWN, Request, Result,  # noqa: F401
                       execute, load_config)
