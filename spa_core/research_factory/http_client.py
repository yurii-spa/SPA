"""spa_core/research_factory/http_client.py — the ONE allow-listed HTTP client (ADR-564 review #14).

Every collector (``collectors/*``, Package E3) imports ONLY this module for network access — an
AST test in ``test_research_evidence_core.py`` enforces that. ``fetch()`` enforces
``evidence_contract.HTTP_ALLOW`` (host, method, path prefix, body type), requires ``https`` on
every hop (``evidence_contract.HTTP_SCHEMES``), re-checks the host AND PORT on every redirect hop
(never follows a redirect off the allow-listed host:port — the default transport disables
urllib's OWN automatic redirect-following, which otherwise follows a 30x itself before this
module's loop ever runs, H1 post-implementation review), resolves a RELATIVE ``Location`` against
the current URL before that check (``urljoin``, H1 LOW), caps the response at ``HTTP_MAX_RESPONSE_BYTES``
(overridden per-host by ``HTTP_MAX_RESPONSE_BYTES_BY_HOST`` — a live probe measured
``yields.llama.fi /pools`` at 11.6 MB, over the 8 MB default), times out at ``HTTP_TIMEOUT_S``,
and restricts a Hyperliquid POST to ``HYPERLIQUID_INFO_TYPES``. Fail-CLOSED: anything outside
the allow-list raises :class:`HttpRefused` — there is no degraded/partial fetch path.

stdlib only (``urllib``), no ``requests``. The real network call is behind an injectable
``transport`` callable so tests never touch a socket.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request

from spa_core.research_factory import evidence_contract as ec

#: transport(request, timeout_s) -> an object with .status (or .code), .read(n) -> bytes, and
#: .headers.get(name) -> str|None (for a redirect Location). The default is urllib's urlopen.
Transport = Callable[[Request, float], Any]

#: HTTP redirect status codes this client will follow (after re-checking the host).
_REDIRECT_CODES = (301, 302, 303, 307, 308)


class HttpRefused(Exception):
    """A request outside ``evidence_contract.HTTP_ALLOW``, outside the size/timeout bounds, a
    redirect leaving the allow-listed host, a non-https scheme, or a Hyperliquid POST body
    naming a type outside ``HYPERLIQUID_INFO_TYPES``. Fail-CLOSED — raised, never silently
    degraded."""


class _RefuseAutoRedirect(urllib.request.HTTPRedirectHandler):
    """H1 (post-implementation review, 2026-10-04): ``urllib.request.urlopen``'s DEFAULT opener
    installs this handler's own stock version, which follows a 30x redirect ITSELF, inside the
    call to ``transport()`` — before ``fetch()``'s own per-hop ``_match_allow`` loop below ever
    runs. The reviewer reproduced this concretely: a redirect to an off-list host came back as a
    plain 200, because urlopen had ALREADY followed it and handed back the final response: the
    "re-check every hop" loop in ``fetch()`` was dead code, never reached. Overriding
    ``redirect_request`` to return ``None`` tells urllib's redirect machinery to NOT auto-follow
    — it hands back the raw, unfollowed 3xx response (status + ``Location`` header) instead,
    which is exactly what ``fetch()``'s own loop needs to do the host re-check itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_RefuseAutoRedirect())


def _default_transport(request: Request, timeout_s: float):
    # with _RefuseAutoRedirect in place, urllib's HTTPErrorProcessor still raises HTTPError for
    # the (now unfollowed) 3xx — HTTPError is itself a file-like response object (.code,
    # .headers.get(...), .read()), so fetch()'s own loop handles it exactly like any other
    # response; this is NOT a request failure, it is the raw hop fetch()'s loop needs to see.
    try:
        return _opener.open(request, timeout=timeout_s)  # noqa: S310 - the one, allow-listed network call
    except urllib.error.HTTPError as redirect_response:
        return redirect_response


#: the one scheme this client ever accepts past the top-of-loop scheme check (evidence_contract.
#: HTTP_SCHEMES == ("https",)), so 443 is the only default port a hop can legitimately mean.
_DEFAULT_HTTPS_PORT = 443


def _hop_port(parts) -> int:
    """H1 LOW (post-implementation review, 2026-10-04): the allow-list's redirect host re-check
    compared ``hostname`` alone — a redirect to the SAME host on a DIFFERENT port matched
    unnoticed (``api.example.com`` and ``api.example.com:8443`` are not the same origin). An
    explicit port is honoured; an absent one defaults to the one port this https-only client
    ever means."""
    return parts.port if parts.port is not None else _DEFAULT_HTTPS_PORT


def _match_allow(host: str, method: str, path: str, body_type: Optional[str]) -> bool:
    for allow_host, allow_method, prefix, allow_body_type in ec.HTTP_ALLOW:
        if host == allow_host and method == allow_method and path.startswith(prefix) \
                and allow_body_type == body_type:
            return True
    return False


def _check_hyperliquid_body(body: Optional[bytes]) -> None:
    if not body:
        raise HttpRefused("a Hyperliquid info POST needs a JSON body naming its 'type'")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpRefused(f"Hyperliquid info POST body is not valid JSON: {exc}") from exc
    req_type = parsed.get("type") if isinstance(parsed, dict) else None
    if req_type not in ec.HYPERLIQUID_INFO_TYPES:
        raise HttpRefused(f"Hyperliquid info type {req_type!r} is not in HYPERLIQUID_INFO_TYPES")


def _iso(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, *, method: str = "GET", body: Optional[bytes] = None,
          body_type: Optional[str] = None, headers: Optional[dict] = None,
          now: Optional[datetime] = None, transport: Optional[Transport] = None,
          max_redirects: int = 5) -> tuple[int, bytes, str]:
    """``(status, raw_bytes, fetched_at ISO-8601)``. Raises :class:`HttpRefused` for anything
    outside the allow-list, an oversized response, a redirect leaving the allow-listed host, or
    an unrecognised Hyperliquid info type. Every hop of a redirect chain is re-checked against
    the SAME allow-list (so a same-host redirect to a disallowed path is also refused)."""
    transport = transport or _default_transport
    fetched_at = _iso(now or datetime.now(timezone.utc))
    current_url = url
    current_method = method
    current_body = body

    for _ in range(max_redirects + 1):
        parts = urlsplit(current_url)
        host = parts.hostname or ""
        path = parts.path or "/"
        # H1: require HTTPS on EVERY hop, including a redirect target — an allow-listed host is
        # named by host only, so a redirect (or an initial call) to the SAME host over plain
        # http would otherwise pass _match_allow unnoticed.
        if parts.scheme not in ec.HTTP_SCHEMES:
            raise HttpRefused(f"refused: scheme {parts.scheme!r} not in HTTP_SCHEMES {ec.HTTP_SCHEMES!r} "
                              f"for {host}{path}")
        if current_method == "POST" and body_type == "hyperliquid_info":
            _check_hyperliquid_body(current_body)
        if not _match_allow(host, current_method, path, body_type):
            raise HttpRefused(f"refused: {current_method} {host}{path} (body_type={body_type!r}) "
                              f"is not in HTTP_ALLOW")
        request = Request(current_url, data=current_body, method=current_method, headers=dict(headers or {}))
        response = transport(request, ec.HTTP_TIMEOUT_S)
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "code", None)
        resp_headers = getattr(response, "headers", None)
        location = resp_headers.get("Location") if resp_headers is not None and hasattr(resp_headers, "get") \
            else None

        if status in _REDIRECT_CODES and location:
            # H1 LOW (b): a relative Location (e.g. "/path", common for same-host redirects) has
            # scheme/host '' on its own — urlsplit(location).hostname would be None and the
            # (pre-fix) check below would silently treat `or host` as "same host, trust it",
            # skipping the allow-list re-check on the NEW path entirely. Resolve it against the
            # CURRENT url first so every hop — relative or absolute — gets the full host+port
            # check below on a real, absolute URL.
            absolute_location = urljoin(current_url, location)
            new_parts = urlsplit(absolute_location)
            new_host = new_parts.hostname or host
            # H1 LOW (a): compare host AND port — see _hop_port.
            if new_host != host or _hop_port(new_parts) != _hop_port(parts):
                raise HttpRefused(f"redirect left the allow-listed host: "
                                  f"{host!r}:{_hop_port(parts)} -> {new_host!r}:{_hop_port(new_parts)}")
            current_url = absolute_location
            # a redirect is always re-fetched with GET and no body in this client's model —
            # collectors never POST through a redirect chain (only the Hyperliquid GET-less
            # info endpoint ever POSTs, and it is not expected to redirect).
            current_method, current_body = "GET", None
            continue

        max_bytes = ec.HTTP_MAX_RESPONSE_BYTES_BY_HOST.get(host, ec.HTTP_MAX_RESPONSE_BYTES)
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise HttpRefused(f"response from {host!r} exceeds its max response size ({max_bytes} bytes)")
        return status, raw, fetched_at

    raise HttpRefused(f"too many redirects (> {max_redirects})")


class Client:
    """The ``client`` object ``collectors/*.py`` (Package E3) expect: ``.get(host, path, params)``
    and ``.post_info(info_type, payload)``, both JSON in, JSON out, built on :func:`fetch` (and
    therefore on ``HTTP_ALLOW``). Every collector already wraps these calls in its own
    ``try/except`` and treats ``client=None`` as "no network this run" — this class is the OPT-IN
    real implementation (``run.py`` constructs one only under ``--live-rpc``, never by default)."""

    def __init__(self, *, now: Optional[datetime] = None, transport: Optional[Transport] = None):
        self._now = now
        self._transport = transport

    def _request_json(self, url: str, *, method: str = "GET", body: Optional[bytes] = None,
                      body_type: Optional[str] = None):
        status, raw, _ = fetch(url, method=method, body=body, body_type=body_type, now=self._now,
                               transport=self._transport)
        if status != 200:
            raise ValueError(f"{method} {url} -> HTTP {status}")
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def get(self, host: str, path: str, params: Optional[dict] = None):
        query = f"?{urlencode(params)}" if params else ""
        return self._request_json(f"https://{host}{path}{query}", method="GET")

    def post_info(self, info_type: str, payload: Optional[dict] = None):
        body = dict(payload or {})
        body["type"] = info_type
        host = next(h for h, m, _p, bt in ec.HTTP_ALLOW if bt == "hyperliquid_info" and m == "POST")
        return self._request_json(f"https://{host}/info", method="POST",
                                  body=json.dumps(body).encode("utf-8"), body_type="hyperliquid_info")
