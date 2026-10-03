"""spa_core/studio_os/mission_server.py — Mission Control v1 serving layer (ADR-552).

Mirrors the Director server's hardened design (``scripts/cartographer/director_server.py``):
a FIXED route map with no path translation (a requested string either matches a dictionary key
dollar-for-dollar or gets 404 — ``..``/``%2e%2e``/symlinks cannot reach outside the bundle because
the request string never becomes a filesystem path), GET/HEAD only, the whole bundle held in
memory and swapped in one atomic assignment when the pointer changes.

Two listeners, not one (security-review finding #1)
=====================================================
A loopback ``Host`` exemption on a SINGLE socket is not safe once a Cloudflare tunnel exists:
``cloudflared`` connects to its local service from 127.0.0.1 and can be configured
(``httpHostHeader``) to rewrite the ``Host`` header to whatever the local service expects — and a
misconfigured catch-all ingress could route an external request to this socket too. Either one
would make an unauthenticated public request look, from inside this process, exactly like a
request from the Mac itself.

So there are two independent sockets, both loopback-only, never one socket wearing two hats:

* **LOCAL listener** (default ``127.0.0.1:8790``) — always on. Serves ONLY when ``Host`` is one of
  the bare loopback forms for ITS OWN port; it carries no Cloudflare Access configuration at all
  (``access_cfg=None`` is wired into its handler), so it CANNOT serve the public host even if a
  request's ``Host`` header claims to be it. It additionally refuses (403, connection closed) ANY
  request carrying a Cloudflare/proxy header (``Cf-Connecting-Ip``, ``Cf-Ray``,
  ``Cf-Access-Jwt-Assertion``, ``Cf-Visitor``, ``Cdn-Loop``, ``X-Forwarded-For``) — such a request
  came through a proxy or tunnel and must never reach the no-JWT loopback path, regardless of what
  its ``Host`` header says.
* **PUBLIC listener** (``MC_PUBLIC_PORT``, default 8792) — started ONLY when ``MC_PUBLIC_HOST`` (and
  its three companions, see below) are configured. On it, EVERY request on EVERY route — including
  ``/healthz`` and ``HEAD /`` — requires BOTH a valid ``Cf-Access-Jwt-Assertion`` JWT (verified by
  :mod:`access_jwt`) AND ``Host == MC_PUBLIC_HOST`` exactly; a loopback-looking ``Host`` on this
  listener gets no exemption and is refused like any other mismatch.

Both listeners bind loopback only (``ALLOWED_BIND_HOSTS``) and serve the same in-memory bundle —
the tunnel's ingress is what exposes the public listener's port to the outside world; this process
never binds anything but 127.0.0.1/::1 itself.

Fail-CLOSED on configuration, not just on requests
====================================================
If ``MC_PUBLIC_HOST`` is set but any of ``MC_ACCESS_AUD`` / ``MC_ACCESS_TEAM`` / ``MC_OWNER_EMAILS``
is missing (from env OR from the access-config file, see :func:`load_access_config`), the server
REFUSES TO START (exit 2) rather than silently falling back to "loopback only" — a half-configured
Access gate would look like a working public remote while quietly trusting everyone.

Owner e-mails never land in the git-tracked plist
===================================================
``--access-config <path>`` (default ``~/studio-os-serve/mission_access.json``, outside the repo)
carries ``{public_host, public_port, aud, team, owner_emails}`` as JSON. If present it MUST be mode
``0600`` and owned by the current user, or the server refuses to start — a world/group-readable
file with the owner's e-mail in it is exactly the kind of thing that should never happen quietly.
Env vars (``MC_*``) remain supported and take priority, mainly so tests can override without
touching the filesystem. Neither file nor env present ⇒ local-only (today's default).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from spa_core.studio_os import access_jwt

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8790
DEFAULT_PUBLIC_PORT = 8792
#: Finding #8: a public port outside this range is refused outright (BundleError, exit 2) —
#: below 1024 needs root (this process never runs as root) and above 65535 is not a port at all.
MIN_PUBLIC_PORT = 1024
MAX_PUBLIC_PORT = 65535
DEFAULT_ROOT = Path.home() / "studio-os-serve" / "mission"
DEFAULT_ACCESS_CONFIG_PATH = Path.home() / "studio-os-serve" / "mission_access.json"
POINTER_FILE = "current.json"
#: The pointer is re-checked at most this often; a swap in between is invisible until the next tick.
POINTER_RECHECK_S = 5.0
ALLOWED_METHODS = ("GET", "HEAD")
#: Hosts the socket itself is allowed to bind to. Naming "0.0.0.0" / "" here would be the exact
#: 2026-08-30 com.spa.dashboard incident (whole-repo raised to the local network). Finding #9:
#: AF_INET only — ``ThreadingHTTPServer.address_family`` is ``socket.AF_INET``, so "::1" never
#: actually worked here; naming it as "allowed" was a dead, misleading entry, not a real option.
ALLOWED_BIND_HOSTS = ("127.0.0.1", "localhost")
HEALTHZ_PATH = "/healthz"
#: A request carrying any of these on the LOCAL listener came through a proxy/tunnel, never
#: directly from the machine itself — case handled by ``headers.get`` (already case-insensitive).
#: Finding #11 (second review round) widened this beyond the Cloudflare-specific set: a Tailscale
#: funnel/ingress or any other reverse proxy would leave the SAME kind of evidence behind.
PROXY_HEADER_NAMES = ("Cf-Connecting-Ip", "Cf-Ray", "Cf-Access-Jwt-Assertion", "Cf-Visitor",
                      "Cdn-Loop", "X-Forwarded-For", "Forwarded", "X-Forwarded-Host",
                      "X-Forwarded-Proto", "X-Real-Ip", "True-Client-Ip", "Via")
#: Any header whose name starts with this (case-insensitive) is also a proxy-header hit — the
#: specific Tailscale header names are not fixed enough to enumerate (finding #11).
PROXY_HEADER_PREFIXES = ("tailscale-",)
#: Request-handling timeout (finding #12) — a slow/stalled client must not pin a handler thread
#: forever.
REQUEST_TIMEOUT_S = 15

#: The ONE route map. Nothing outside this dict can ever be served — there is no code path that
#: turns an arbitrary request string into a filesystem path. ``mission_build.py`` derives the set
#: of UI files it must ship from this map (finding #13).
ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/i18n.js": ("i18n.js", "application/javascript; charset=utf-8"),
    "/mission.json": ("mission.json", "application/json; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}

#: Strict headers on EVERY response — success, error, or refusal alike (including whatever
#: ``send_error`` emits for requests this handler never got to dispatch — finding #12).
SECURITY_HEADERS = (
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
     "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("X-Frame-Options", "DENY"),
    ("X-Robots-Tag", "noindex"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)


class BundleError(Exception):
    """Startup/config refusal (fail-CLOSED) or a bundle that cannot be loaded whole."""


# ── bundle: loaded whole into memory, swapped atomically ──────────────────────────────────────────
def read_pointer(root: Path) -> Optional[dict]:
    """Which bundle directory is current. Missing/unreadable/malformed pointer is an honest
    ``None`` (finding #11: a pointer file holding, say, ``[1, 2]`` must not reach ``.get()``)."""
    p = Path(root) / POINTER_FILE
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    name = doc.get("bundle")
    if not name or "/" in str(name) or str(name).startswith("."):
        return None  # the pointer must name a bare directory NAME, never a path
    return {"bundle": str(name), "built_at": doc.get("built_at"),
            "schema": doc.get("schema"), "system_state": doc.get("system_state")}


def load_bundle(root: Path, pointer: dict) -> dict:
    """The bundle, whole, or not at all: no code path serves a half-read directory. Any OSError
    while reading becomes ``BundleError`` (finding #11), never an uncaught crash."""
    base = (Path(root) / pointer["bundle"]).resolve()
    root_resolved = Path(root).resolve()
    if root_resolved not in base.parents and base != root_resolved:
        raise BundleError("bundle directory escapes the serving root")
    files = {}
    for route, (name, ctype) in ROUTES.items():
        f = base / name
        try:
            if not f.exists() or f.resolve().parent != base:
                raise BundleError(f"bundle file missing or escapes its directory: {name}")
            data = f.read_bytes()
        except OSError as exc:
            raise BundleError(f"bundle file unreadable: {name}: {exc}") from exc
        files[route] = (data, ctype)
    return {"files": files, "bundle": pointer["bundle"], "built_at": pointer.get("built_at"),
            "schema": pointer.get("schema"), "system_state": pointer.get("system_state")}


class Serving:
    """The in-memory copy currently served. Swapping it is one attribute assignment."""

    def __init__(self, root):
        self.root = Path(root)
        self.state: Optional[dict] = None
        self.pointer: Optional[dict] = None
        self._last_check = 0.0
        self.reloads = 0
        self.errors = 0

    def refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_check) < POINTER_RECHECK_S:
            return
        self._last_check = now
        pointer = read_pointer(self.root)
        if pointer is None:
            return  # no pointer yet — keep whatever (possibly nothing) we already have
        if pointer == self.pointer and self.state is not None:
            return
        try:
            new_state = load_bundle(self.root, pointer)
        except Exception:  # noqa: BLE001 — fail-SAFE: keep the previous good copy, never crash
            self.errors += 1
            return
        self.state, self.pointer = new_state, pointer  # ← atomic swap
        self.reloads += 1

    def get(self, path: str):
        if self.state is None:
            return None
        return self.state["files"].get(path)


# ── Cloudflare Access gate (only active when MC_PUBLIC_HOST is set) ───────────────────────────────
@dataclass
class AccessConfig:
    public_host: str
    public_port: int
    audience: str
    team_domain: str
    owner_emails: set = field(default_factory=set)
    #: Not a constructor argument — one cache per server lifetime, shared by every request thread
    #: (finding #3: certs must NOT be re-fetched on every request). NO disk cache (finding #4):
    #: :class:`access_jwt.CertsCache` is purely in-memory.
    certs_cache: "access_jwt.CertsCache" = field(init=False, repr=False, default=None)

    def __post_init__(self):
        self.certs_cache = access_jwt.CertsCache(self.team_domain)

    @property
    def issuer(self) -> str:
        return f"https://{self.team_domain}"


#: A refusal to trust the config file's content past this size is plenty for
#: {public_host, public_port, aud, team, owner_emails[]} and stops a maliciously huge file from
#: being read into memory whole.
MAX_ACCESS_CONFIG_BYTES = 1 << 20  # 1 MiB


def _read_access_config_file(path: Path) -> Optional[dict]:
    """``None`` when the file does not exist (the normal, local-only default). Raises
    ``BundleError`` if it exists but is unsafe (not 0600 / not owned by us / a symlink) or
    unparsable — a config file that might carry owner e-mails is never trusted half-way.

    Finding #7 (second review round): open ONCE with ``O_NOFOLLOW`` (refuses a symlink outright —
    an owner config has no business being one) and ``fstat``/read from that SAME file descriptor,
    so there is no window between "check the mode/owner" and "read the content" in which the path
    could be swapped for something else (TOCTOU) — a separate ``Path.stat()`` + ``Path.read_text()``
    pair (the previous version) checks one thing and reads a possibly different one.
    """
    p = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(str(p), flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BundleError(f"cannot open access config {p}: {exc}") from exc
    try:
        st = os.fstat(fd)
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o600:
            raise BundleError(
                f"access config {p} must be mode 0600 (found {oct(mode)}) — refusing to start "
                "rather than trust a group/world-readable file that may carry the owner's e-mail"
            )
        getuid = getattr(os, "getuid", None)
        if getuid is not None and st.st_uid != getuid():
            raise BundleError(
                f"access config {p} is not owned by the current user — refusing to start")
        raw = os.read(fd, MAX_ACCESS_CONFIG_BYTES)
        if len(raw) >= MAX_ACCESS_CONFIG_BYTES:
            raise BundleError(f"access config {p} is implausibly large — refusing to start")
    finally:
        os.close(fd)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BundleError(f"cannot read access config {p}: {exc}") from exc
    if not isinstance(doc, dict):
        raise BundleError(f"access config {p} must be a JSON object, got {type(doc).__name__}")
    return doc


def _env_as_config_doc(env: dict) -> dict:
    """Reshape ``MC_*`` env vars into the same doc shape the access-config FILE uses, so both
    sources feed one piece of code (below) and neither can partially leak into the other."""
    doc: dict = {}
    if env.get("MC_PUBLIC_HOST"):
        doc["public_host"] = env["MC_PUBLIC_HOST"]
    if env.get("MC_ACCESS_AUD"):
        doc["aud"] = env["MC_ACCESS_AUD"]
    if env.get("MC_ACCESS_TEAM"):
        doc["team"] = env["MC_ACCESS_TEAM"]
    if env.get("MC_OWNER_EMAILS"):
        doc["owner_emails"] = [e.strip() for e in env["MC_OWNER_EMAILS"].split(",") if e.strip()]
    if env.get("MC_PUBLIC_PORT"):
        doc["public_port"] = env["MC_PUBLIC_PORT"]
    return doc


def load_access_config(env: Optional[dict] = None, config_path=None,
                        allow_env_config: bool = False) -> Optional[AccessConfig]:
    """``None`` when Mission Control is loopback-only (the default). Raises ``BundleError`` — a
    startup refusal, fail-CLOSED — if a public host is named without its companions.

    Finding #6 (second review round): the FILE and env vars are never mixed. If the access-config
    FILE exists, it is the ONLY source — env vars are not consulted for so much as one field, even
    if ``allow_env_config`` is set; a stray ``MC_PUBLIC_PORT`` left in some shell's environment must
    not silently combine with the file's owner e-mails into a config nobody wrote down anywhere.
    If the file does NOT exist, env vars are read ONLY when the caller explicitly passes
    ``allow_env_config=True`` — production (``main()``) never does; it exists so tests can
    configure a public listener without writing a file to disk.
    """
    file_doc = _read_access_config_file(Path(config_path)) if config_path else None
    if file_doc is not None:
        source = file_doc
    elif allow_env_config:
        source = _env_as_config_doc(os.environ if env is None else env)
    else:
        source = {}

    public_host = str(source.get("public_host") or "").strip()
    if not public_host:
        return None
    aud = str(source.get("aud") or "").strip()
    team = str(source.get("team") or "").strip()
    emails_raw = source.get("owner_emails") or []
    emails = {str(e).strip().lower() for e in emails_raw if str(e).strip()}
    missing = [n for n, v in (("aud", aud), ("team", team)) if not v]
    if not emails:
        missing.append("owner_emails")
    if missing:
        raise BundleError(
            f"public_host={public_host!r} is set but missing: {', '.join(missing)} — "
            "refusing to start rather than silently serving the public host unauthenticated"
        )
    port_raw = source.get("public_port") or DEFAULT_PUBLIC_PORT
    try:
        public_port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise BundleError(f"invalid public_port: {port_raw!r}") from exc
    if not (MIN_PUBLIC_PORT <= public_port <= MAX_PUBLIC_PORT):
        raise BundleError(
            f"public_port {public_port} is outside the allowed range "
            f"[{MIN_PUBLIC_PORT}, {MAX_PUBLIC_PORT}]"
        )
    return AccessConfig(public_host=public_host, public_port=public_port, audience=aud,
                         team_domain=team, owner_emails=emails)


# ── handler ─────────────────────────────────────────────────────────────────────────────────────
def make_handler(serving: Serving, port: int, listener_kind: str,
                  access_cfg: Optional[AccessConfig]):
    """``listener_kind`` is ``"local"`` or ``"public"``. The LOCAL handler is built with
    ``access_cfg=None`` ALWAYS (even if a public host is configured elsewhere) — it has no idea
    the public host exists, so it cannot be tricked into serving it."""
    assert listener_kind in ("local", "public")
    loopback_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    class MissionHandler(BaseHTTPRequestHandler):
        server_version = "mission/1"
        sys_version = ""
        protocol_version = "HTTP/1.1"
        timeout = REQUEST_TIMEOUT_S  # finding #12: never let a stalled client pin a thread forever
        #: Finding #3 (second review round): the stdlib default is "HTTP/0.9" — a request line
        #: with no recognisable version (malformed, or genuinely HTTP/0.9) is then handled as
        #: HTTP/0.9, and ``send_response``/``send_header`` become silent no-ops for it (see
        #: ``http.server.BaseHTTPRequestHandler.send_response_only``): the client gets a body with
        #: NO status line and NO headers at all — including none of ``SECURITY_HEADERS``. Naming
        #: HTTP/1.0 here instead means any such request is answered with a full status line and
        #: headers, same as everything else.
        default_request_version = "HTTP/1.0"

        # -- low-level response helpers --------------------------------------------------------
        def _send_headers(self, status, ctype, length, close=False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            if close:
                self.send_header("Connection", "close")
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        def _body(self, status, ctype, body: bytes, head_only: bool):
            # Finding #2: any non-2xx response closes the connection — a half-authenticated or
            # malformed request must never leave a keep-alive socket in a state the client and
            # server disagree about (request smuggling / desync).
            close = not (200 <= status < 300)
            self._send_headers(status, ctype, len(body), close=close)
            if not head_only:
                self.wfile.write(body)
            if close:
                self.close_connection = True

        def _json(self, status, obj, head_only=False):
            self._body(status, "application/json; charset=utf-8",
                       json.dumps(obj, ensure_ascii=False).encode("utf-8"), head_only)

        def _text(self, status, message: str, head_only=False):
            self._body(status, "text/plain; charset=utf-8", message.encode("utf-8"), head_only)

        def _log(self, status, reason: Optional[str] = None):
            # Exactly method, path, status, [reason] — NEVER headers, NEVER the token, NEVER
            # query/body. ``reason`` (finding #12) is the server-log-only explanation of a 403;
            # it is built from access_jwt's AccessDenied messages, which never embed the token.
            try:
                path = (self.path or "?").split("?", 1)[0].split("#", 1)[0]
            except AttributeError:
                path = "?"
            cmd = getattr(self, "command", None) or "?"
            msg = f"mission/1 {cmd} {path} {status}"
            if reason:
                msg += f" reason={reason}"
            sys.stderr.write(msg + "\n")

        # -- request-smuggling guard (finding #2, widened in the second review round) -----------
        def _header_all(self, name: str) -> list:
            """``self.headers`` is normally an ``email.message.Message`` (has ``get_all``), but
            for an HTTP/0.9-shaped request line (no recognisable version AND no headers at all —
            ``http.server`` hands those a bare ``{}``) it is a plain ``dict``. Either way, this
            returns every value seen for ``name`` — at most one for the ``dict`` case."""
            getter = getattr(self.headers, "get_all", None)
            if getter is not None:
                return getter(name) or []
            v = self.headers.get(name)
            return [v] if v is not None else []

        def _framing_is_suspicious(self) -> bool:
            if self.headers.get("Transfer-Encoding") is not None:
                return True
            # Finding #1 (second review round): TWO Content-Length headers (e.g. "0" then a real
            # length) is a classic smuggling shape — some front-ends honour the first, some the
            # last, and ``self.headers.get`` only ever returns ONE of them, so the two sides of a
            # chain can each read a different request out of the same bytes.
            cls = self._header_all("Content-Length")
            if len(cls) > 1:
                return True
            if cls and cls[0].strip() != "0":
                return True
            return False

        def _header_parse_is_suspicious(self) -> bool:
            """Finding #2 (second review round): a header BLOCK the parser itself flagged as
            malformed (e.g. ``"X-A : b"`` — a space before the colon) can make the stdlib parser
            drop every header AFTER the bad line silently — so a header this handler relies on
            (``Host``, a proxy header) may simply not be there, and nothing says why. A non-empty
            ``.defects`` list is exactly that signal (absent entirely on the HTTP/0.9 ``dict``
            case — ``getattr`` handles that). A duplicate ``Host`` is a related but different
            defect (nothing marks it malformed; ``.get`` just silently returns the FIRST one) —
            checked the same way, by count, not by trusting ``.get``."""
            if getattr(self.headers, "defects", None):
                return True
            if len(self._header_all("Host")) != 1:
                return True
            return False

        def _proxy_header_on_local(self) -> Optional[str]:
            if listener_kind != "local":
                return None
            for name in PROXY_HEADER_NAMES:
                if self.headers.get(name) is not None:
                    return name
            for name in self.headers.keys():
                lname = name.lower()
                if any(lname.startswith(prefix) for prefix in PROXY_HEADER_PREFIXES):
                    return name
            return None

        def _pre_dispatch_guard(self, head_only: bool) -> bool:
            """Checks that apply to EVERY method, before any routing decision. Returns True if a
            response was already sent (caller must stop)."""
            if self._framing_is_suspicious():
                self._log(400, reason="unexpected request body (Content-Length/Transfer-Encoding)")
                self._text(400, "request body not allowed", head_only)
                return True
            if self._header_parse_is_suspicious():
                self._log(400, reason="malformed header block (parser defect or duplicate Host)")
                self._text(400, "malformed headers", head_only)
                return True
            bad_header = self._proxy_header_on_local()
            if bad_header is not None:
                self._log(403, reason=f"proxy/tunnel header on local listener: {bad_header}")
                self._text(403, "forbidden", head_only)
                return True
            return False

        # -- host / Access gate -----------------------------------------------------------------
        def _local_access_denied_reason(self) -> Optional[str]:
            host = (self.headers.get("Host") or "").strip()
            if host not in loopback_hosts:
                return f"unrecognised Host on local listener: {host!r}"
            return None

        def _public_access_denied_reason(self) -> Optional[str]:
            """Public listener: Host MUST equal the configured public host exactly — a
            loopback-looking Host gets NO exemption here (that is the whole point of a second
            listener). Every failure mode (host mismatch, missing/invalid JWT, or an unexpected
            exception anywhere in the check) collapses to the same reason shape: 403, never a
            crash (finding #3)."""
            try:
                host = (self.headers.get("Host") or "").strip()
                if host != access_cfg.public_host:
                    return f"host mismatch on public listener: {host!r}"
                token = self.headers.get("Cf-Access-Jwt-Assertion")
                if not token:
                    return "missing Cf-Access-Jwt-Assertion"
                kid_hint = access_jwt.peek_kid(token)
                certs = access_cfg.certs_cache.get(kid=kid_hint)
                access_jwt.verify(token, certs=certs, audience=access_cfg.audience,
                                   issuer=access_cfg.issuer, allowed_emails=access_cfg.owner_emails,
                                   now=time.time())
                return None
            except Exception as exc:  # noqa: BLE001 — ANY failure in the check is a 403, never a crash
                return f"{type(exc).__name__}: {exc}"

        # -- GET / HEAD ---------------------------------------------------------------------------
        def _serve(self, head_only=False):
            if self._pre_dispatch_guard(head_only):
                return
            path = self.path.split("?", 1)[0].split("#", 1)[0]

            if listener_kind == "public":
                reason = self._public_access_denied_reason()
            else:
                reason = self._local_access_denied_reason()
            if reason is not None:
                status = 403 if listener_kind == "public" else 421
                self._log(status, reason=reason)
                self._text(status, "forbidden" if status == 403 else "unrecognised Host", head_only)
                return

            serving.refresh()

            if path == HEALTHZ_PATH:
                st = serving.state
                age_s = None
                built_at = (st or {}).get("built_at")
                if built_at:
                    try:
                        dt = datetime.fromisoformat(str(built_at).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        age_s = round((datetime.now(timezone.utc) - dt).total_seconds(), 1)
                    except ValueError:
                        age_s = None
                self._log(200)
                self._json(200, {"ok": st is not None, "bundle": (st or {}).get("bundle"),
                                  "built_at": built_at, "age_s": age_s}, head_only)
                return

            if serving.state is None:
                self._log(503)
                self._text(503, "mission bundle unavailable — nothing built yet", head_only)
                return

            found = serving.get(path)
            if found is None:
                self._log(404)
                self._text(404, "not found", head_only)
                return
            body, ctype = found
            self._log(200)
            self._body(200, ctype, body, head_only)

        def do_GET(self):
            self._serve()

        def do_HEAD(self):
            self._serve(head_only=True)

        # -- everything else: one branch, no "execute" path exists at all ----------------------
        def _method_not_allowed(self):
            if self._pre_dispatch_guard(head_only=False):
                return
            self._log(405)
            self.close_connection = True
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", ", ".join(ALLOWED_METHODS))
            self.send_header("Connection", "close")
            self.send_header("Content-Length", "0")
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed
        do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed

        # -- finding #12: malformed requests that never reach do_* also carry security headers --
        def send_error(self, code, message=None, explain=None):
            self.close_connection = True
            try:
                self._log(int(code))
            except Exception:  # noqa: BLE001 — logging must never itself raise
                pass
            try:
                shortmsg, longmsg = self.responses[code]
            except KeyError:
                shortmsg, longmsg = "???", "???"
            if message is None:
                message = shortmsg
            if explain is None:
                explain = longmsg
            body = None
            self.send_response(code, message)
            self.send_header("Connection", "close")
            if code >= 200 and code not in (HTTPStatus.NO_CONTENT, HTTPStatus.NOT_MODIFIED,
                                             HTTPStatus.PARTIAL_CONTENT):
                content = f"{code} {message}: {explain}".encode("utf-8", "replace")
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                body = content
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()
            if body is not None and getattr(self, "command", None) != "HEAD":
                try:
                    self.wfile.write(body)
                except Exception:  # noqa: BLE001 — client may already be gone
                    pass

        def log_message(self, format, *args):  # noqa: A002 — base class signature
            pass  # suppressed: _log() above is the only line we ever print, and it is safe

    return MissionHandler


def serve(root, port: int = DEFAULT_PORT, bind: str = LOOPBACK, serve_forever: bool = True,
           env: Optional[dict] = None, access_config_path=None, allow_env_config: bool = False):
    """Start serving: the LOCAL listener always, the PUBLIC listener only if configured. Raises
    ``BundleError`` (fail-CLOSED) for a bad bind host, a half-configured Access gate, or a
    public port that collides with the local one — BEFORE any socket is opened. May also raise
    a bare ``OSError`` from the actual ``bind()`` call (e.g. the port is already in use); callers
    that want a clean exit code rather than a traceback catch that too (``main()`` does).

    ``allow_env_config`` must be explicit (finding #6) — production never passes it; it exists so
    tests can configure a public listener without writing a file to disk. Even when true, env is
    read only if the access-config FILE does not exist; the two sources are never mixed (see
    :func:`load_access_config`).

    Returns ``({"local": httpd, "public": httpd_or_None}, serving)``.
    """
    if bind not in ALLOWED_BIND_HOSTS:
        raise BundleError(f"refusing to bind outside loopback: bind={bind!r}")
    access_cfg = load_access_config(env, config_path=access_config_path,
                                     allow_env_config=allow_env_config)  # may raise BundleError
    if access_cfg is not None and int(access_cfg.public_port) == int(port):
        raise BundleError(
            f"public_port {access_cfg.public_port} collides with the local listener port {port}"
        )

    serving = Serving(root)
    serving.refresh(force=True)

    local_httpd = ThreadingHTTPServer((bind, int(port)), make_handler(serving, port, "local", None))
    local_httpd.daemon_threads = True

    public_httpd = None
    if access_cfg is not None:
        public_httpd = ThreadingHTTPServer(
            (bind, int(access_cfg.public_port)),
            make_handler(serving, access_cfg.public_port, "public", access_cfg),
        )
        public_httpd.daemon_threads = True
        public_httpd.access_cfg = access_cfg  # test/introspection only — not read by the handler

    servers = {"local": local_httpd, "public": public_httpd}

    if serve_forever:
        threads = []
        if public_httpd is not None:
            t = threading.Thread(target=public_httpd.serve_forever, daemon=True)
            t.start()
            threads.append(t)
        print(f"mission/1 local listening on http://{bind}:{port}/ root={root} "
              f"public={'http://%s:%s/' % (bind, access_cfg.public_port) if access_cfg else None}",
              flush=True)
        try:
            local_httpd.serve_forever()
        finally:
            local_httpd.server_close()
            if public_httpd is not None:
                public_httpd.shutdown()
                public_httpd.server_close()
    return servers, serving


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Mission Control v1 server (ADR-552)")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="LOCAL listener port")
    ap.add_argument("--bind", default=LOOPBACK, help="must be a loopback host; anything else is refused")
    ap.add_argument("--access-config", default=str(DEFAULT_ACCESS_CONFIG_PATH),
                     help="JSON file {public_host, public_port, aud, team, owner_emails} outside "
                          "the repo; must be mode 0600 and owned by the current user if present. "
                          "This is the ONLY production source — see --allow-env-config. Neither "
                          "present ⇒ local-only (default: %(default)s)")
    ap.add_argument("--allow-env-config", action="store_true",
                     help="finding #6: read MC_* env vars as a config source WHEN THE FILE DOES "
                          "NOT EXIST. Never set this in production — it exists for tests only; "
                          "the wrapper script explicitly unsets every MC_* var before exec'ing "
                          "this module so a stray environment variable can never reach here.")
    a = ap.parse_args(argv)
    config_path = Path(a.access_config) if a.access_config else None
    try:
        serve(a.root, a.port, bind=a.bind, access_config_path=config_path,
              allow_env_config=a.allow_env_config)
    except BundleError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # Finding #9 (second review round): a bind failure (e.g. "Address already in use") used
        # to propagate as a bare traceback — a crash and a refusal are both fail-CLOSED in effect,
        # but only the refusal is the documented contract (clean message, exit 2).
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
