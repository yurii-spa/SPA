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
import os
import secrets
import sqlite3
import sys
from typing import Optional

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import users as auth_users

# ── Password hashing ───────────────────────────────────────────────────────
# argon2id lives in spa_core.academy.auth.passwords; user creation / password
# reset go through spa_core.academy.auth.users so the CLI shares the exact
# validation, hashing and audit-logging path as the web layer.


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
    try:
        user_id = auth_users.create_user(
            db, args.email, password, invite_code=None, is_owner=True
        )
    except sqlite3.IntegrityError:
        _die(f"a user with email {args.email!r} already exists")
    except ValueError as exc:
        _die(str(exc))
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
    row = auth_users.get_user_by_email(db, args.email)
    if row is None:
        _die(f"no user with email {args.email!r}")
    try:
        auth_users.update_password(db, row["id"], password)
    except ValueError as exc:
        _die(str(exc))
    print(f"password reset for {args.email}")


def cmd_delete_user(args: argparse.Namespace) -> None:
    """GDPR account deletion — remove a user and ALL linked rows (cascade).

    The ``events`` audit table is append-only (two triggers block UPDATE/DELETE). Deleting an account
    is the ONE sanctioned exception: we drop the ``events_no_delete`` guard for this single transaction,
    purge the user's events, then recreate the guard — so a "delete my account" request genuinely erases
    the PII (email, wallet, progress, and the user's audit rows) rather than leaving it forever.
    """
    db = _db()
    db.run_migrations()
    row = auth_users.get_user_by_email(db, args.email)
    if row is None:
        _die(f"no user with email {args.email!r}")
    uid = row["id"]
    is_owner = ("is_owner" in row.keys() and row["is_owner"])  # sqlite3.Row has no .get()
    if is_owner and not args.force:
        _die("refusing to delete an owner account without --force")
    with db.connect() as c:
        c.execute("DROP TRIGGER IF EXISTS events_no_delete")  # sanctioned lift for account erasure
        try:
            for tbl, col in (("sessions", "user_id"), ("progress", "user_id"),
                             ("wallets", "user_id"), ("siwe_nonces", "user_id"),
                             ("quiz_results", "user_id"), ("notes", "user_id"),
                             ("used_tx_hashes", "user_id"), ("events", "user_id")):
                try:
                    c.execute(f"DELETE FROM {tbl} WHERE {col} = ?", (uid,))
                except Exception:
                    pass  # table/column may not exist in older schemas
            # invite_codes references users via created_by AND used_by — null them, keep the code rows
            for col in ("created_by", "used_by"):
                try:
                    c.execute(f"UPDATE invite_codes SET {col} = NULL WHERE {col} = ?", (uid,))
                except Exception:
                    pass
            c.execute("DELETE FROM users WHERE id = ?", (uid,))
        finally:
            c.execute("CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events "
                      "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END")
        c.commit()
    print(f"deleted user {args.email!r} (id={uid}) and all linked rows")


# \u2500\u2500 Argument parsing ───────────────────────────────────────────────────────


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

    p_del = sub.add_parser("delete-user", help="GDPR: delete a user and all linked rows (cascade)")
    p_del.add_argument("--email", required=True, help="email of the account to delete")
    p_del.add_argument("--force", action="store_true", help="allow deleting an is_owner account")
    p_del.set_defaults(func=cmd_delete_user)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
