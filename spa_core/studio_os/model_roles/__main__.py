"""python -m spa_core.studio_os.model_roles --role R --provider P --context FILE --task-id T --instruction TEXT
       [--fixture F.json] [--config C.json] [--out RECORD.json]

# LLM_FORBIDDEN

Runs ONE request under the provider contract with an EXPLICITLY named provider (production routing is
off: the repository configuration assigns none). Exit 0 ok · 1 provider outcome other than ok · 2 refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles.contract import ConfigError, Request, execute, load_config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.model_roles")
    ap.add_argument("--role", required=True)
    ap.add_argument("--provider", default=None, help="explicit provider id (no default routing)")
    ap.add_argument("--context", type=Path, required=True, help="context pack (e.g. role-pack pack.md)")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--instruction", required=True)
    ap.add_argument("--fixture", type=Path, default=None, help="answers for the TEST adapter")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
    except ConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2
    adapters = {"claude_cli": ad.claude_cli()}
    if a.fixture:
        adapters["fixture"] = ad.fixture_from_file(a.fixture)
    req = Request(a.role, a.task_id, a.instruction, a.context.read_text(encoding="utf-8"), str(a.context))
    res = execute(req, config=cfg, provider_id=a.provider, adapters=adapters)
    doc = res.to_dict()
    if a.out:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(a.out))
    print(json.dumps({k: doc[k] for k in ("status", "role", "provider_id", "real_provider", "model",
                                          "attempts", "elapsed_s", "usage", "reason")},
                     ensure_ascii=False))
    print(doc["text"])
    return 0 if res.status == "ok" else (2 if res.status == "refused" else 1)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
