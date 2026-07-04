"""
spa_core/academy/manage.py

Academy management CLI (stdlib argparse only — NO click).

Commands:
  init-db          Apply migrations (requires SPA_ACADEMY_DB to be set).
  create-owner     Create an is_owner=1 user.
  gen-invite       Generate an invite code (secrets.token_urlsafe(12)).
  list-users       Print users (never the password_hash).
  reset-password   Reset an existing user's password.

Passwords are NEVER logged or echoed. They are supplied via one of:
  --password VALUE          (INSECURE — for tests/local only)
  --password-env ENVVAR     (read from os.environ[ENVVAR])
  <interactive>             getpass prompt when neither flag is given

Usage:
  python3 -m spa_core.academy.manage init-db
  python3 -m spa_core.academy.manage create-owner --email a@b.co --password-env PW
  python3 -m spa_core.academy.manage gen-invite --max-uses 5
  python3 -m spa_core.academy.manage list-users
  python3 -m spa_core.academy.manage reset-password --email a@b.co

LLM FORBIDDEN in this module.
Academy stage 1.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
from typing import Optional

from spa_core.academy.db import AcademyDB

# ── Password hashing (stdlib pbkdf2_hmac) ──────────────────────────────────
# Stored format:  pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """Return a self-describing PBKDF2-SHA256 hash string for *password*."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_ALGO}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify *password* against a stored hash string."""
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
    except (ValueError, AttributeError):
        return False
    if algo != _PBKDF2_ALGO:
        return False
    try:
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


# ── Password resolution (never logged) ─────────────────────────────────────


def _resolve_password(args: argparse.Namespace, prompt: str) -> str:
    """Resolve a password from --password / --password-env / getpass."""
    if getattr(args, "password", None) is not None:
        pw = args.password
    elif getattr(args, "password_env", None):
        envvar = args.password_env
        if envvar not in os.environ:
            _die(f"environment variable {envvar!r} is not set")
        pw = os.environ[envvar]
    else:
        pw = getpass.getpass(prompt)
    if not pw:
        _die("password must not be empty")
    return pw


def _die(msg: str, code: int = 1) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _db() -> AcademyDB:
    try:
        return AcademyDB()
    except ValueError as exc:
        _die(str(exc))


# ── Commands ───────────────────────────────────────────────────────────────


def cmd_init_db(args: argparse.Namespace) -> None:
    db = _db()
    applied = db.run_migrations()
    if applied:
        print(f"applied migrations: {applied}")
    else:
        print("no new migrations (already current)")
    print(f"schema_version = {db.schema_version()}")


def cmd_create_owner(args: argparse.Namespace) -> None:
    db = _db()
    db.run_migrations()
    password = _resolve_password(args, f"Password for owner {args.email}: ")
    pw_hash = hash_password(password)
    try:
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, is_owner) VALUES (?,?,1)",
                (args.email, pw_hash),
            )
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        _die(f"a user with email {args.email!r} already exists")
    print(f"created owner id={user_id} email={args.email}")


def cmd_gen_invite(args: argparse.Namespace) -> None:
    db = _db()
    db.run_migrations()
    code = secrets.token_urlsafe(12)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO invite_codes(code, max_uses) VALUES (?, ?)",
            (code, args.max_uses),
        )
    print(code)


def cmd_list_users(args: argparse.Namespace) -> None:
    db = _db()
    db.run_migrations()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, email, is_owner, invite_code_used, created_at "
            "FROM users ORDER BY id"
        ).fetchall()
    if not rows:
        print("(no users)")
        return
    header = f"{'id':>4}  {'owner':>5}  {'email':<32}  {'invite':<16}  created_at"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['id']:>4}  {r['is_owner']:>5}  {r['email']:<32}  "
            f"{(r['invite_code_used'] or ''):<16}  {r['created_at']}"
        )


def cmd_reset_password(args: argparse.Namespace) -> None:
    db = _db()
    db.run_migrations()
    password = _resolve_password(args, f"New password for {args.email}: ")
    pw_hash = hash_password(password)
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (pw_hash, args.email),
        )
        if cur.rowcount == 0:
            _die(f"no user with email {args.email!r}")
    print(f"password reset for {args.email}")


# ── Argument parsing ───────────────────────────────────────────────────────


def _add_password_flags(p: argparse.ArgumentParser) -> None:
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--password",
        help="password value (INSECURE — visible in argv/history; use for tests only)",
    )
    grp.add_argument(
        "--password-env",
        metavar="ENVVAR",
        help="name of an environment variable holding the password",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.academy.manage",
        description="Academy management CLI (requires SPA_ACADEMY_DB).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="apply migrations")
    p_init.set_defaults(func=cmd_init_db)

    p_owner = sub.add_parser("create-owner", help="create an is_owner=1 user")
    p_owner.add_argument("--email", required=True)
    _add_password_flags(p_owner)
    p_owner.set_defaults(func=cmd_create_owner)

    p_inv = sub.add_parser("gen-invite", help="generate an invite code")
    p_inv.add_argument("--max-uses", type=int, default=1)
    p_inv.set_defaults(func=cmd_gen_invite)

    p_list = sub.add_parser("list-users", help="list users (no password_hash)")
    p_list.set_defaults(func=cmd_list_users)

    p_reset = sub.add_parser("reset-password", help="reset a user's password")
    p_reset.add_argument("--email", required=True)
    _add_password_flags(p_reset)
    p_reset.set_defaults(func=cmd_reset_password)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
