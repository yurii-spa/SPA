#!/usr/bin/env python3
"""gen_onboarding_modules.py — regenerate landing/src/data/onboarding_modules.json from the single
source of truth spa_core/academy/content/modules.py. Keeps the build-time static module content
(theory/practice/spa-connection, RU + EN) in sync with the backend. stdlib-only, deterministic.
Run from repo root or via the landing prebuild. LLM_FORBIDDEN (static content only)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from spa_core.academy.content.modules import MODULES  # noqa: E402

_KEYS = ("id", "title_ru", "title_en", "description_ru", "description_en", "practice_type", "chain",
         "wallet_limit_usd",
         "theory_html_ru", "theory_html_en", "practice_html_ru", "practice_html_en",
         "spa_connection_html_ru", "spa_connection_html_en")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "landing", "src", "data", "onboarding_modules.json")


def main():
    mods = [{k: MODULES[i].get(k, MODULES[i].get(k.replace("_en", "_ru")) if k.endswith("_en") else None)
             for k in _KEYS} for i in sorted(MODULES)]
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mods, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print(f"onboarding_modules.json regenerated: {len(mods)} modules "
          f"({sum(1 for m in mods if m.get('theory_html_en'))} with EN theory)")


if __name__ == "__main__":
    main()
