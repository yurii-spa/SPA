"""spa_core/tests/test_mission_ui_static.py — Mission Control UI static checks.

ADR-552 (v1) + ADR-571/RM-TRUTH-01 WP2 (Director OS v2 — extended here, journaled per inv. #16:
the v1 areas/nav were replaced wholesale by the new IA, so the tests that pinned the old area ids
("overview"/"system") and the old header labels were rewritten rather than left to assert a page
that no longer exists; every assertion that proved a still-true security property was kept as is).

Stdlib-only. Verifies the no-build web app under spa_core/studio_os/mission_ui/ against the
CSP and security rules fixed by the architecture gate:
  - index.html is a shell only (no inline <script>/<style> content, no on*= handlers).
  - app.js never touches innerHTML/outerHTML/insertAdjacentHTML/eval/new Function, and every
    href it assigns is either a hardcoded internal '#area' link or passes through safeLink(),
    the one helper allowed to approve a model-derived https://t.me/ URL.
  - i18n.js carries one RU+EN dictionary with an identical key set for every UI label.
  - styles.css declares the dark/light split and a desktop breakpoint.
  - v2: the five new areas exist, the permanent money chip exists, canon/as_of/freshness (the
    "Доказательства" fields) are read ONLY inside evidenceDrawer(), and the fixture that stands
    in for WP1's output carries no raw identifier outside that one function's reach.
"""
import json
import re
import unittest
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[2] / "spa_core" / "studio_os" / "mission_ui"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "mission_truth_scene.json"

# Fields that are explicitly allowed to carry raw technical identifiers (design §2.5: these live
# ONLY inside the "Доказательства" drawer). Everything else in the fixture is first-level content
# and must be clean of shas / launchd labels / pids / data-file paths.
EVIDENCE_ONLY_KEYS = {"canon", "as_of", "freshness"}

FORBIDDEN_FIRST_LEVEL_PATTERNS = [
    re.compile(r"\bcom\.spa\."),
    re.compile(r"\bcom\.studiobridge\."),
    re.compile(r"\bdata/[\w./\-]*\.json\b"),
    re.compile(r"(?<![\w-])pid(?![\w-])", re.I),
    re.compile(r"\b[0-9a-f]{40}\b"),  # a full git sha
]

REQUIRED_FILES = (
    "index.html",
    "styles.css",
    "i18n.js",
    "app.js",
    "manifest.webmanifest",
    "icon.svg",
)


def _read(name: str) -> str:
    return (UI_DIR / name).read_text(encoding="utf-8")


class TestFilesExist(unittest.TestCase):
    def test_all_required_files_exist(self):
        missing = [name for name in REQUIRED_FILES if not (UI_DIR / name).is_file()]
        self.assertEqual(missing, [], f"missing mission_ui files: {missing}")


class TestIndexHtmlShellOnly(unittest.TestCase):
    def setUp(self):
        self.html = _read("index.html")

    def test_html_lang_ru_and_viewport_fit_cover(self):
        self.assertRegex(self.html, r'<html[^>]*\blang="ru"')
        self.assertIn("viewport-fit=cover", self.html)

    def test_links_to_required_assets(self):
        self.assertIn('rel="manifest" href="manifest.webmanifest"', self.html)
        self.assertIn('rel="stylesheet" href="styles.css"', self.html)
        self.assertIn('icon.svg', self.html)

    def test_no_style_tag_or_inline_style_attribute(self):
        self.assertNotRegex(self.html.lower(), r"<style[\s>]", msg="index.html must not carry a <style> block")
        self.assertNotRegex(self.html, r'\sstyle\s*=\s*"', msg="index.html must not carry inline style= attributes")

    def test_no_inline_script_content_and_scripts_are_deferred(self):
        script_tags = re.findall(r"<script\b([^>]*)>(.*?)</script>", self.html, re.S | re.I)
        self.assertGreaterEqual(len(script_tags), 2, "expected at least i18n.js and app.js script tags")
        seen_src = set()
        for attrs, body in script_tags:
            self.assertEqual(body.strip(), "", f"inline script content found: {body!r}")
            self.assertIn("src=", attrs, "every <script> in index.html must load an external file")
            self.assertIn("defer", attrs, "every <script> in index.html must be deferred")
            m = re.search(r'src="([^"]+)"', attrs)
            if m:
                seen_src.add(m.group(1))
        self.assertIn("i18n.js", seen_src)
        self.assertIn("app.js", seen_src)

    def test_no_event_handler_attributes(self):
        # catches onclick=, onload=, etc. anywhere in the document
        self.assertNotRegex(self.html, r'\son[a-zA-Z]+\s*=\s*"', msg="index.html must not carry on*= event handler attributes")


class TestAppJsSecurity(unittest.TestCase):
    def setUp(self):
        self.js = _read("app.js")

    def test_no_dangerous_dom_sinks(self):
        forbidden = ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function")
        for token in forbidden:
            self.assertNotIn(token, self.js, f"app.js must not use {token}")

    def test_safe_link_helper_exists_and_is_used(self):
        self.assertRegex(self.js, r"function\s+safeLink\s*\(")
        self.assertIn("TELEGRAM_PREFIX", self.js)
        self.assertIn('indexOf(TELEGRAM_PREFIX) === 0', self.js)
        # used at least at the two known call sites (header intake + decision answer button)
        self.assertGreaterEqual(self.js.count("safeLink("), 3)

    def test_every_href_assignment_is_guarded(self):
        # Every `href: <expr>` object-literal assignment in app.js must either be a hardcoded
        # internal hash link ('#...') or route through safeLink(...). This is the static proof
        # that no href is ever set from model data without the t.me prefix check.
        hrefs = re.findall(r"href:\s*([^\n,}]+)", self.js)
        self.assertGreater(len(hrefs), 0, "expected at least one href: assignment in app.js")
        bad = []
        for expr in hrefs:
            expr = expr.strip()
            if re.match(r'^"#|^\'#', expr):
                continue
            if "safeLink(" in expr:
                continue
            bad.append(expr)
        self.assertEqual(bad, [], f"unguarded href assignment(s) in app.js: {bad}")

    def test_no_raw_href_attribute_assignment_outside_helper(self):
        # Guards against a future `.href = someModelField` bypassing the h()/safeLink() path.
        self.assertNotRegex(self.js, r"\.href\s*=\s*(?!safeLink)")


class TestI18nParity(unittest.TestCase):
    def setUp(self):
        self.js = _read("i18n.js")

    def _dict(self):
        m = re.search(r"/\*I18N_START\*/(.*?)/\*I18N_END\*/", self.js, re.S)
        self.assertIsNotNone(m, "i18n.js must carry a dictionary between /*I18N_START*/ and /*I18N_END*/ markers")
        return json.loads(m.group(1))

    def test_dictionary_parses_as_json(self):
        data = self._dict()
        self.assertIn("ru", data)
        self.assertIn("en", data)

    def test_ru_and_en_have_identical_key_sets(self):
        data = self._dict()
        ru_keys = set(data["ru"].keys())
        en_keys = set(data["en"].keys())
        self.assertGreater(len(ru_keys), 0, "ru dictionary must not be empty")
        self.assertEqual(ru_keys, en_keys, f"ru/en key sets diverge: ru-en={ru_keys - en_keys} en-ru={en_keys - ru_keys}")

    def test_localstorage_access_is_wrapped_in_try_catch(self):
        self.assertIn("try {", self.js)
        self.assertIn("localStorage", self.js)
        # crude but effective: every localStorage.* call site is inside a try block somewhere
        # in the same function; we check the two known call sites explicitly.
        self.assertRegex(self.js, r"try\s*{\s*\n\s*var v = localStorage\.getItem")
        self.assertRegex(self.js, r"try\s*{\s*\n\s*localStorage\.setItem")


class TestStylesCss(unittest.TestCase):
    def setUp(self):
        self.css = _read("styles.css")

    def test_prefers_color_scheme_block_present(self):
        self.assertRegex(self.css, r"@media\s*\(\s*prefers-color-scheme:\s*light\s*\)")

    def test_desktop_breakpoint_media_query_present(self):
        self.assertRegex(self.css, r"@media\s*\(\s*min-width:\s*\d+px\s*\)")

    def test_no_horizontal_scroll_safety_net(self):
        self.assertIn("overflow-x: hidden", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)

    def test_no_fixed_width_over_343px_below_600px_breakpoint(self):
        # design §5.5 / acceptance: "no fixed widths > 343px below @media (min-width:600px)".
        # A naive substring grep would also flag a legitimate wide value guarded by a >=600px
        # media query, so this walks brace nesting to know, for every width/max-width/min-width
        # declaration, whether it sits inside a media query and what that query's own min-width
        # is — only a declaration that is unguarded (or guarded below 600px) can violate.
        css = self.css
        n = len(css)
        depth = 0
        # stack of (depth_at_open, media_min_width_or_None) for each currently-open '{' scope
        stack = []
        pending_media_min = "NOT_MEDIA"
        i = 0
        violations = []
        decl_re = re.compile(r"(width|max-width|min-width)\s*:\s*(\d+)px")
        while i < n:
            if css[i] == "@" and css[i : i + 6] == "@media":
                j = css.index("{", i)
                header = css[i:j]
                m = re.search(r"min-width:\s*(\d+)px", header)
                pending_media_min = int(m.group(1)) if m else None
                i = j
                continue
            if css[i] == "{":
                ctx = pending_media_min if pending_media_min != "NOT_MEDIA" else (stack[-1][1] if stack else None)
                stack.append((depth, ctx))
                pending_media_min = "NOT_MEDIA"
                depth += 1
                # scan this rule's own declaration body (up to its matching close) for widths
                close = _matching_brace(css, i)
                body = css[i + 1 : close]
                active_min = stack[-1][1]
                if active_min is None or active_min < 600:
                    for dm in decl_re.finditer(body):
                        px = int(dm.group(2))
                        if px > 343:
                            violations.append((dm.group(1), px, active_min))
                i += 1
                continue
            if css[i] == "}":
                depth -= 1
                if stack and stack[-1][0] == depth:
                    stack.pop()
                i += 1
                continue
            i += 1
        self.assertEqual(violations, [], f"fixed width(s) over 343px unguarded by a >=600px media query: {violations}")


def _matching_brace(text, open_idx):
    depth = 0
    for k in range(open_idx, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(text)


# ── Director OS v2 (ADR-571, RM-TRUTH-01 WP2) ──────────────────────────────────────────────

class TestV2Areas(unittest.TestCase):
    """The new IA replaced the v1 one wholesale (journaled, inv. #16): Главная/Капитал/Студия/
    Продукт/Решения, a permanent money chip, and no more 'overview'/'system' areas."""

    def setUp(self):
        self.html = _read("index.html")
        self.js = _read("app.js")

    def test_five_v2_area_sections_present(self):
        for area in ("home", "capital", "studio", "product", "decisions"):
            self.assertIn(f'id="area-{area}"', self.html)
        self.assertNotIn('id="area-overview"', self.html)
        self.assertNotIn('id="area-system"', self.html)

    def test_money_chip_container_present_and_rendered(self):
        self.assertIn('id="money-chip"', self.html)
        self.assertIn("renderMoneyChip", self.js)
        self.assertIn('getElementById("money-chip")', self.js)

    def test_nav_uses_new_area_keys(self):
        # app.js composes t("nav." + a) over the AREAS array rather than five literal keys;
        # check the array itself carries exactly the five new areas, in the new order.
        m = re.search(r'var AREAS = \[([^\]]*)\]', self.js)
        self.assertIsNotNone(m, "AREAS array not found")
        areas = [a.strip().strip('"') for a in m.group(1).split(",")]
        self.assertEqual(areas, ["home", "capital", "studio", "product", "decisions"])
        self.assertIn('t("nav." + a)', self.js)


class TestEvidenceIsTheOnlyDrawer(unittest.TestCase):
    """canon / as_of / freshness (the raw, technical fields) are read ONLY inside
    evidenceDrawer() — structural proof that the first level can never surface them, whatever
    a given scene's data looks like (design §2.5)."""

    def setUp(self):
        self.js = _read("app.js")

    def _evidence_drawer_span(self):
        start = self.js.index("function evidenceDrawer")
        open_brace = self.js.index("{", start)
        end = _matching_brace(self.js, open_brace)
        return start, end

    def test_canon_as_of_freshness_read_only_inside_evidence_drawer(self):
        start, end = self._evidence_drawer_span()
        for token in (".canon", ".as_of", ".freshness"):
            positions = [m.start() for m in re.finditer(re.escape(token), self.js)]
            self.assertTrue(positions, f"{token} is never read at all — unexpected")
            outside = [p for p in positions if not (start <= p <= end)]
            self.assertEqual(outside, [], f"{token} read outside evidenceDrawer() at offset(s) {outside}")

    def test_no_forbidden_literal_tokens_in_app_js_source(self):
        # app.js must not itself hardcode a launchd label, pid or sha anywhere (positive control:
        # these tokens are only ever supposed to travel as DATA through evidenceDrawer, never as
        # literal source text).
        for pattern in FORBIDDEN_FIRST_LEVEL_PATTERNS:
            self.assertIsNone(pattern.search(self.js), f"forbidden literal token matches {pattern.pattern!r} in app.js")


class TestFixtureFirstLevelHygiene(unittest.TestCase):
    """The fixture stands in for WP1's real output. Combined with
    TestEvidenceIsTheOnlyDrawer (canon/as_of/freshness can only ever reach the drawer), a clean
    fixture here is equivalent to a clean first-level render: nothing else in app.js can promote
    a forbidden token to the first level no matter what the fixture contains."""

    def test_fixture_exists_and_parses(self):
        self.assertTrue(FIXTURE_PATH.is_file(), f"missing fixture: {FIXTURE_PATH}")
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_no_forbidden_token_outside_evidence_only_fields(self):
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        violations = []

        def walk(node, key_path):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in EVIDENCE_ONLY_KEYS or k == "_comment":
                        continue
                    walk(v, key_path + [k])
            elif isinstance(node, list):
                for idx, item in enumerate(node):
                    walk(item, key_path + [str(idx)])
            elif isinstance(node, str):
                for pattern in FORBIDDEN_FIRST_LEVEL_PATTERNS:
                    if pattern.search(node):
                        violations.append((".".join(key_path), node, pattern.pattern))

        walk(data, [])
        self.assertEqual(violations, [], f"forbidden token(s) outside the evidence-only fields: {violations}")

    def test_no_green_badge_for_not_enough_history_or_unknown_states(self):
        # Structural guarantee (inv. #17 — colour follows state, state is honest): app.js's
        # stateBadgeClass() must map every one of NOT_MEASURED / STALE / CORRUPT /
        # NOT_ENOUGH_HISTORY to something other than "ok". A positive control proves the regex
        # below actually looks at the right thing: it must currently report MEASURED -> "ok".
        js = _read("app.js")
        m = re.search(r"function stateBadgeClass\(state\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m, "stateBadgeClass() not found")
        body = m.group(1)
        self.assertIn('"MEASURED"', body)  # positive control: the function does classify states
        branches = re.findall(r'if \(([^)]*)\) return "([a-z]+)";', body)
        default_return = re.search(r'\n\s*return "([a-z]+)";[^\n]*$', body)
        self.assertIsNotNone(default_return, "no unconditional fallback return found")
        for bad_state in ("NOT_MEASURED", "STALE", "CORRUPT", "NOT_ENOUGH_HISTORY"):
            matched_explicitly = False
            for cond, cls in branches:
                if bad_state in cond:
                    matched_explicitly = True
                    self.assertNotEqual(cls, "ok", f"{bad_state} must not map to the ok badge class")
            if not matched_explicitly:
                # falls through to the default branch — that must not be "ok" either
                self.assertNotEqual(default_return.group(1), "ok", f"{bad_state} falls through to the default, which must not be ok")


if __name__ == "__main__":
    unittest.main()
