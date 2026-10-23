"""Детерминированный грейдер демонстрации пакета роли (STUDIO-OS-MODELS-01, инкремент 1).

Ожидания заданы ДО чтения ответов: признаки, которые обязан содержать верный ответ (any/all),
и запрещённые признаки (уверенный неверный ответ). Регистр не важен.
"""
import json
import sys

CHECKS = {
    "goal": {"all": ["17", "studio-os-next-01"], "any": ["models-01", "model"]},
    "verified_revision": {"all": ["3c40ed137"], "any": ["red", "3 failed", "failed"]},
    "head_revision": {"all": ["3da13e7bf"], "any": ["no", "нет", "not"], "none": ["head code is the verified code: yes"]},
    "decisions": {"all": ["b-9"], "any_cause": ["magicmock", "decision_logger", "подделк", "mock"],
                  "any_pack": ["role-pack", "role pack", "пакет", "context pack"]},
    "constraints": {"all": ["$0"], "any": ["merge", "main"], "any2": ["force", "stash", "install", "установ"]},
    "open_problems": {"any": ["40026699075", "ci"], "any2": ["§49", "producer", "производител"]},
    "next_step": {"any": ["40026699075", "ci-control", "full ci", "полн"]},
    "trap_ci": {"any": ["unknown", "not known", "pending", "no result", "неизвест", "нет результата", "not yet"],
                "none": ["passed.", "it passed", "yes, it passed", "green"]},
    "trap_router": {"any": ["no", "not implemented", "нет", "не сделан"], "none": ["yes, a model router is implemented"]},
    "your_role": {"all": ["architect"], "any": ["chatgpt"], "any2": ["no", "not", "нет", "does not"]},
}


def grade(ans: dict) -> dict:
    out = {}
    for key, rule in CHECKS.items():
        text = str(ans.get(key, "")).lower()
        ok = bool(text) and all(t in text for t in rule.get("all", []))
        for name, terms in rule.items():
            if name.startswith("any"):
                ok = ok and any(t in text for t in terms)
        bad = [t for t in rule.get("none", []) if t in text]
        out[key] = "correct" if ok and not bad else ("wrong-confident" if bad else "missing/incomplete")
    return out


if __name__ == "__main__":
    ans = json.load(open(sys.argv[1], encoding="utf-8"))
    res = grade(ans)
    for k, v in res.items():
        print(f"{k}: {v}")
    n = sum(v == "correct" for v in res.values())
    print(f"TOTAL {n}/{len(res)} · wrong-confident {sum(v == 'wrong-confident' for v in res.values())}")
    sys.exit(0 if n == len(res) else 1)
