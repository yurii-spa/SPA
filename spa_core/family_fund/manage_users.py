"""CLI для управления users.json (Family Fund API).

Хеши паролей (bcrypt) хранятся в users.json. САМ ПАРОЛЬ В ФАЙЛ НЕ ПИШЕТСЯ.

Примеры:
    # добавить/обновить пользователя (пароль спросит интерактивно):
    python -m spa_core.family_fund.manage_users set --username owner \\
        --email yuriycooleshov@gmail.com --role owner

    # пароль из переменной окружения (для скриптов):
    FF_PW='...' python -m spa_core.family_fund.manage_users set \\
        --username admin --role admin --password-env FF_PW

    # список пользователей (без хешей):
    python -m spa_core.family_fund.manage_users list

    # удалить:
    python -m spa_core.family_fund.manage_users delete --username readonly
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path

from spa_core.family_fund.api.auth import hash_password
from spa_core.family_fund.api.models import UserRole

_USERS_PATH = Path(__file__).resolve().parent / "users.json"
_ROLES = [r.value for r in UserRole]


def _load() -> dict:
    try:
        return json.loads(_USERS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": []}


def _atomic_write(data: dict) -> None:
    dir_ = _USERS_PATH.parent
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        tmp = f.name
    os.replace(tmp, _USERS_PATH)


def cmd_set(args: argparse.Namespace) -> int:
    if args.role not in _ROLES:
        print(f"Invalid role {args.role!r}. Choose from: {_ROLES}", file=sys.stderr)
        return 2
    if args.password_env:
        password = os.environ.get(args.password_env, "")
        if not password:
            print(f"Env var {args.password_env} is empty", file=sys.stderr)
            return 2
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm:  "):
            print("Passwords do not match", file=sys.stderr)
            return 2
    if len(password) < 8:
        print("Password must be at least 8 characters", file=sys.stderr)
        return 2

    data = _load()
    users = [u for u in data.get("users", []) if u.get("username") != args.username]
    users.append({
        "username": args.username,
        "email": args.email or "",
        "role": args.role,
        "password_hash": hash_password(password),
    })
    data["users"] = users
    _atomic_write(data)
    print(f"User {args.username!r} ({args.role}) saved to {_USERS_PATH}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    data = _load()
    for u in data.get("users", []):
        print(f"  {u.get('username'):<16} {u.get('role'):<10} {u.get('email','')}")
    if not data.get("users"):
        print("  (no users)")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    data = _load()
    before = len(data.get("users", []))
    data["users"] = [
        u for u in data.get("users", []) if u.get("username") != args.username
    ]
    _atomic_write(data)
    removed = before - len(data["users"])
    print(f"Removed {removed} user(s) named {args.username!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Family Fund API users")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="add or update a user")
    p_set.add_argument("--username", required=True)
    p_set.add_argument("--email", default="")
    p_set.add_argument("--role", required=True, choices=_ROLES)
    p_set.add_argument("--password-env", default=None)
    p_set.set_defaults(func=cmd_set)

    p_list = sub.add_parser("list", help="list users (no hashes)")
    p_list.set_defaults(func=cmd_list)

    p_del = sub.add_parser("delete", help="delete a user")
    p_del.add_argument("--username", required=True)
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
