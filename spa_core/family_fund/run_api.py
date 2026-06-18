"""Launch script для Family Fund API (uvicorn, порт 8766).

    python -m spa_core.family_fund.run_api
    python -m spa_core.family_fund.run_api --port 8766 --reload

Эквивалент:
    python -m uvicorn spa_core.family_fund.api.app:app --port 8766
"""
from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Family Fund API (uvicorn)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        "spa_core.family_fund.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
