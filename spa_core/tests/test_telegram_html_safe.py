"""Guard: every interactive-bot view body must be HTML-safe for parse_mode=HTML.

A stray raw '<' / '>' / '&' in a view body (static text OR live data, e.g.
"<$20M", "RESEARCH -> BACKTEST", a "β<0" pulled from a JSON feed) makes the
Telegram Bot API reject the message (400 can't-parse-entities) → editMessageText
silently fails → the button "does nothing" (the dead-button bug the owner hit).

`Router.render_view` runs every body through `html_safe()`. This test renders
EVERY registered view through the router and asserts the result is HTML-safe, so
the regression can never come back.
"""
import re

from spa_core.telegram.router import Router, html_safe
from spa_core.telegram.views import VIEW_REGISTRY

# Telegram's allowed HTML tag whitelist for parse_mode=HTML.
_ALLOWED = re.compile(r"</?(b|i|u|s|code|pre|a)(\s[^>]*)?>")


class _MockTransport:
    def edit_message_text(self, *a, **k):
        return a

    def send_message(self, *a, **k):
        return a

    def answer_callback(self, *a, **k):
        return None


def _is_html_safe(body: str) -> bool:
    """True iff, after removing allowed tags, no raw < > remains and every & is an entity."""
    stripped = _ALLOWED.sub("", body)
    if re.search(r"[<>]", stripped):
        return False
    if re.search(r"&(?!amp;|lt;|gt;|quot;|#)", body):
        return False
    return True


def test_html_safe_helper_escapes_raw_chars_keeps_tags():
    out = html_safe("Liquidator NO-GO too small (<$20M bar) RESEARCH -> BACKTEST")
    assert "<$20M" not in out and "&lt;$20M" in out
    assert "-&gt;" in out  # the '>' inside '->' is escaped to &gt;
    assert _is_html_safe(out)
    # intentional tags survive
    assert html_safe("a <b>bold</b> & c") == "a <b>bold</b> &amp; c"


def test_every_view_rendered_via_router_is_html_safe():
    r = Router(_MockTransport(), "123")
    offenders = []
    for path in sorted(VIEW_REGISTRY):
        body, _kb = r.render_view(path, "", "en", 0, "123")
        if not _is_html_safe(body):
            offenders.append(path)
        # RU too — live data + RU labels must also stay safe
        body_ru, _ = r.render_view(path, "", "ru", 0, "123")
        if not _is_html_safe(body_ru):
            offenders.append(path + " (ru)")
    assert not offenders, "HTML-unsafe view bodies (dead-button risk): %s" % offenders
