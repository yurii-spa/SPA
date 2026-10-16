"""spa_core/tests/test_mission_ui_static.py — Mission Control UI static checks.

ADR-552 (v1) + ADR-571/RM-TRUTH-01 WP2 (Director OS v2 — extended here, journaled per inv. #16:
the v1 areas/nav were replaced wholesale by the new IA, so the tests that pinned the old area ids
("overview"/"system") and the old header labels were rewritten rather than left to assert a page
that no longer exists; every assertion that proved a still-true security property was kept as is).

# FROZEN-DATE-OK: исторический инцидент — «2026-10-15, owner's first real iPhone try» стои́т
# ТОЛЬКО в прозе докстринга класса TestVoiceRecorderNeverPostsAnEmptyRecording и называет день
# аварии, ради которой тест написан. Ни одно утверждение файла этой датой не пользуется: все
# проверки статические (чтение app.js / index.html / i18n.js), понятия свежести в файле нет
# вовсе, поэтому ни сдвиг календаря, ни длительность прогона вердикт изменить не могут. Приём
# №3 `.claude/rules/deployment.md`: дата является предметом, и решение записано, а не умолчано.

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


def _hidden_attribute_wins(css: str) -> bool:
    """True iff a top-level ``[hidden]`` rule forces ``display: none !important``.

    The UA stylesheet's ``[hidden]{display:none}`` loses to any author ``display`` value, so
    without this rule ``.area{display:flex}`` kept every area the router had hidden on screen
    (reproduced live on :8790 (GOVERNANCE-UX-RECOVERY-01 audit): opening "Решения" stacked ~5,650 px of the other
    tabs above it). Comments are stripped first so a commented-out rule does not count.
    """
    no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"(?m)^\[hidden\]\s*\{([^}]*)\}", no_comments):
        if re.search(r"display\s*:\s*none\s*!important", m.group(1)):
            return True
    return False


class TestStylesCss(unittest.TestCase):
    def setUp(self):
        self.css = _read("styles.css")

    def test_hidden_attribute_beats_author_display(self):
        # app.js hides areas (and other nodes) by setting `.hidden`; styles.css gives `.area`
        # (and many classes) an explicit `display`, which defeats the UA rule.
        self.assertIn("sec.hidden = a !== area", _read("app.js"))
        self.assertRegex(self.css, r"(?m)^\.area\s*\{[^}]*display\s*:\s*flex")
        self.assertTrue(_hidden_attribute_wins(self.css),
                        "styles.css must carry a top-level [hidden]{display:none !important}")

    def test_hidden_guard_control_both_ways(self):
        # positive control: the shipped (buggy) shape — no [hidden] rule — is refused,
        # a commented-out rule is refused, a rule without !important is refused.
        self.assertFalse(_hidden_attribute_wins(".area {\n  display: flex;\n}\n"))
        self.assertFalse(_hidden_attribute_wins("/*\n[hidden] { display: none !important; }\n*/"))
        self.assertFalse(_hidden_attribute_wins("[hidden] {\n  display: none;\n}\n"))
        self.assertTrue(_hidden_attribute_wins("[hidden] {\n  display: none !important;\n}\n"))

    def test_dark_only_no_light_theme_anywhere(self):
        # owner 15.10 (journaled inv. #16): «белая тема вообще не нужна» — the light theme and its
        # toggle are gone; this replaces the UX-02 «both themes» checks with their opposite.
        self.assertNotRegex(self.css, r"prefers-color-scheme")
        self.assertNotIn('data-theme="light"', self.css)
        html = _read("index.html")
        self.assertNotIn("theme-toggle", html)
        self.assertIn('<meta name="color-scheme" content="dark">', html)

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

    def test_five_owner_sections_present(self):
        # DIRECTOR-OS-UX-02 (RFC-690 §3, journaled inv. #16): the five owner sections replaced the
        # v2 areas; the v2 areas live on inside them as «Технические подробности», and their old
        # hashes still resolve through LEGACY_AREA (asserted below), so no link dies.
        for area in ("overview", "decisions", "work", "money", "protection"):
            self.assertIn(f'id="area-{area}"', self.html)
        for gone in ("home", "capital", "studio", "product", "system"):
            self.assertNotIn(f'id="area-{gone}"', self.html)
        for old, new in (("home", "overview"), ("capital", "money"), ("studio", "work"), ("product", "work")):
            self.assertRegex(self.js, rf'{old}:\s*"{new}"')

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
        self.assertEqual(areas, ["overview", "decisions", "work", "money", "protection"])
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


class TestOffHostBackupDoesNotOverclaim(unittest.TestCase):
    """P1 recovery: the Studio card said «Копия вне Мака: есть, проверена» while the producer
    (spa_core/dr/offsite_copy.py) records ``remote_upload: NOT_MEASURED`` — the copy is verified
    inside the iCloud sync FOLDER, which lives on this Mac; reaching the servers is not observed.
    The renderer must read ``remote_upload`` and pick the «not measured» wording for it (inv. #17)."""

    def test_renderer_reads_remote_upload(self):
        js = _read("app.js")
        m = re.search(r"function renderBackupOffHost\(cell\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn('cell.remote_upload === "NOT_MEASURED"', body)
        self.assertIn("studio.backups.off_host_upload_unmeasured", body)

    def test_unmeasured_wording_exists_in_both_languages_and_says_so(self):
        i18n = _read("i18n.js")
        rows = re.findall(r'"studio\.backups\.off_host_upload_unmeasured":\s*"([^"]+)"', i18n)
        self.assertEqual(len(rows), 2)
        self.assertIn("не измерено", rows[0])
        self.assertIn("not measured", rows[1])


class TestRecoveryDrillStampIsOwnerTime(unittest.TestCase):
    """ADR-660: the restore-drill stamp printed raw UTC ISO («2026-…T10:56:25.1365») on Studio;
    a full stamp must go through ownerTime (Europe/Madrid), a bare date stays a date."""

    def test_recovery_ok_uses_owner_time_for_a_stamp(self):
        js = _read("app.js")
        line = next(l for l in js.splitlines() if '"studio.backups.recovery_ok"' in l)
        self.assertIn("ownerTime(cell.date)", line)
        self.assertIn("T\\d", line)


class TestVoiceRecorderNeverPostsAnEmptyRecording(unittest.TestCase):
    """2026-10-15, owner's first real iPhone try: Safari delivered the only data chunk after
    onstop, the page posted a 0-byte blob, the server answered 411 «Пустой запрос». The recorder
    must collect with a timeslice, wait for the last chunk, and refuse to post an empty blob."""

    def test_recorder_uses_a_timeslice_and_guards_empty_blob(self):
        js = _read("app.js")
        self.assertIn("rec.start(1000)", js)
        self.assertIn("if (!blob.size)", js)
        self.assertIn('t("intake.empty_recording")', js)
        self.assertIn("setTimeout(function () { finishRecording(); }", js)

    def test_empty_recording_message_exists_in_both_languages(self):
        i18n = _read("i18n.js")
        self.assertEqual(i18n.count('"intake.empty_recording"'), 2)
class TestUx02OwnerSections(unittest.TestCase):
    """DIRECTOR-OS-UX-02 (ADR-762): the page draws `owner_view`; technical fields stay in the
    details helper; no money literal; nav labelled; theme choice stored only as a convenience."""

    def setUp(self):
        self.js = _read("app.js")
        self.html = _read("index.html")
        self.css = _read("styles.css")

    def _span(self, name):
        start = self.js.index("function " + name)
        end = _matching_brace(self.js, self.js.index("{", start))
        return start, end

    def test_owner_view_technical_fields_read_only_in_tech_lines(self):
        # Scope: the UX-02 owner layer (the legacy v2 cards keep their own techDetails() path).
        lo = self.js.index("DIRECTOR-OS-UX-02 — owner sections")
        hi = self.js.index("// ── top-level render")
        start, end = self._span("techLines")
        for token in (".source", ".measured_at_ru", ".technical", ".unit"):
            pos = [m.start() for m in re.finditer(re.escape(token) + r"\b", self.js) if lo <= m.start() <= hi]
            outside = [p for p in pos if not (start <= p <= end)]
            self.assertEqual(outside, [], f"{token} read outside techLines() at {outside}")

    def test_money_chip_has_no_zero_fallback(self):
        start, end = self._span("renderMoneyChip")
        body = self.js[start:end]
        self.assertNotIn('"0"', body)
        self.assertIn("owner_view.sections.money.real", body)
        # positive control: the v2 fallback that printed "$0" would be caught by the same check
        self.assertIn('"0"', 'var usd = "$" + (mc.usd === null ? "0" : mc.usd);')

    def test_nav_is_labelled_and_marks_the_current_section(self):
        self.assertIn('aria-current', self.js)
        self.assertIn('aria-label="Разделы"', self.html)
        self.assertIn('h("span", { class: "nav-label" }', self.js)

    def test_no_theme_choice_is_stored(self):
        # dark only since 15.10 — nothing about a theme is read or written
        self.assertNotIn("THEME_KEY", self.js)
        self.assertNotIn("dos_theme", self.js)

    def test_touch_targets_are_declared_at_least_44px(self):
        for sel in (".nav-item", ".icon-toggle", ".ux-btn", ".ux-details > summary"):
            m = re.search(re.escape(sel) + r"[^{]*\{[^}]*min-height:\s*(\d+)px", self.css)
            self.assertIsNotNone(m, sel)
            self.assertGreaterEqual(int(m.group(1)), 44, sel)

    def test_safe_area_insets_on_header_nav_and_main(self):
        self.assertGreaterEqual(self.css.count("env(safe-area-inset-bottom)"), 2)
        self.assertIn("env(safe-area-inset-top)", self.css)

    def test_desktop_sidebar(self):
        m = re.search(r"@media\s*\(min-width:\s*1024px\)\s*\{(.*)\Z", self.css, re.S)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"\.bottom-nav\s*\{[^}]*flex-direction:\s*column")


class TestUx02DecisionsAndProtection(unittest.TestCase):
    """DIRECTOR-OS-UX-02 · D (ADR-762 §4): opening a card is not approval; the only answer route is
    the existing Telegram link; a changed card blocks the answer until the owner re-reads it; the
    page records nothing (the last-seen version is a per-viewer convenience in wrapped storage)."""

    def setUp(self):
        self.js = _read("app.js")
        self.i18n = _read("i18n.js")
        start = self.js.index("function renderDecisionCard")
        self.card = self.js[start:_matching_brace(self.js, self.js.index("{", start))]

    def test_answer_link_only_when_ready_and_version_not_changed(self):
        self.assertIn('ans.kind === "READY"', self.card)
        self.assertIn("seen !== fp", self.card)
        self.assertIn('t("ux.dec.changed")', self.card)
        # the blocked branches render a DISABLED button, never a link
        self.assertGreaterEqual(self.card.count("disabled: true"), 2)

    def test_reread_is_explicit_and_first_read_never_overwrites_a_different_version(self):
        self.assertIn('t("ux.dec.reread")', self.card)
        self.assertIn("!readSeen()[it.id]", self.card)

    def test_seen_storage_is_wrapped_and_not_an_approval(self):
        self.assertRegex(self.js, r"function readSeen\(\) \{\s*try \{")
        self.assertRegex(self.js, r"function writeSeen\(id, fp\) \{\s*try \{")
        for bad in ("fetch(", "XMLHttpRequest", "method:"):
            self.assertNotIn(bad, self.card)

    def test_not_approval_wording_in_both_languages(self):
        rows = re.findall(r'"ux\.dec\.not_approval":\s*"([^"]+)"', self.i18n)
        self.assertEqual(len(rows), 2)
        self.assertIn("не одобрение", rows[0])
        self.assertIn("not approval", rows[1])

    def test_protection_and_decisions_keep_the_previous_cards_in_details(self):
        self.assertIn('legacyDetails(t("ux.prot.legacy")', self.js)
        # task E: the previous view stays reachable, with the owner-queue answer links gated (see TestUx02TaskE)
        self.assertIn('legacyDetails(t("ux.dec.legacy"), function (b2) { renderDecisions(b2, true); })', self.js)
        for fn in ("renderBackups(", "renderProblems(", "renderIncidents(", "renderFleet(", "renderScopes(",
                   "renderMachine(", "renderMemory("):
            self.assertIn(fn, self.js)

    def test_old_redesign_notes_are_gone(self):
        self.assertNotIn("ux.section_note", self.js)


class TestUx02TaskE(unittest.TestCase):
    """DIRECTOR-OS-UX-02 task E: one injectable clock, honest EN mode, no unchecked answer path,
    a phone-first Защита, and room under the content for the tab bar at any text size."""

    def test_one_reader_clock_and_the_pin_never_reaches_production(self):
        js = _read("app.js")
        self.assertEqual(js.count("Date.now()"), 1, "every staleness judgement goes through readerNowMs()")
        m = re.search(r"function readerNowMs\(\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        self.assertIn('meta[name=dos-fixed-now]', m.group(1))
        self.assertIn("readerNowMs() - ts", js)
        self.assertNotIn("dos-fixed-now", _read("index.html"), "the production shell must not pin the clock")

    def test_previous_decision_view_offers_no_unchecked_answer_for_the_owner_queue(self):
        js = _read("app.js")
        self.assertIn("renderDecisions(b2, true)", js)
        m = re.search(r"function renderDecisionItem\(d, gated\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertLess(body.index("if (gated)"), body.index('h("a"'),
                        "the gate must be checked before any answer link is drawn")
        self.assertIn('t("ux.dec.answer_in_card")', body)
        self.assertIn('key === "owner"', js)

    def test_en_mode_says_the_sections_are_russian_only(self):
        js = _read("app.js")
        self.assertIn('getLang() === "en"', js)
        self.assertIn('t("ux.ru_only")', js)
        i18n = _read("i18n.js")
        rows = re.findall(r'"ux\.ru_only":\s*"([^"]+)"', i18n)
        self.assertEqual(len(rows), 2)
        self.assertIn("Russian only", rows[1])

    def test_protection_keeps_verdict_actions_and_backups_visible_and_folds_the_rest(self):
        js = _read("app.js")
        m = re.search(r"function renderProtectionArea\(root\) \{(.*?)\n  \}\n", js, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("ux.prot.all_checks", body)          # the individual checks fold
        self.assertIn("PROBLEMS_VISIBLE = 3", body)          # first problems with «что делать» stay open
        self.assertLess(body.index("p.verdict"), body.index("ux.prot.problems"))
        self.assertLess(body.index("ux.prot.problems"), body.index("ux.prot.backups"))

    def test_space_under_the_content_grows_with_the_text_size(self):
        css = _read("styles.css")
        self.assertRegex(css, r"main \{[^}]*max\(96px, 2\.5rem \+ 40px\)")


class TestArb0910HonestAnswerPaths(unittest.TestCase):
    """ARB 09.10: no cockpit text promises a version-bound confirmation; every Telegram answer path the
    cockpit offers carries the same honest sentence."""

    def test_i18n_has_no_version_binding_claims(self):
        i18n = _read("i18n.js")
        for claim in ("Вы отвечаете на версию", "проверяются версия", "Ответ заблокирован, пока вы не подтвердите",
                      "Версия карточки", "You are answering version"):
            self.assertNotIn(claim, i18n)
        self.assertEqual(i18n.lower().count("пульт не проверяет ответ в телеграме"), 4)

    def test_every_telegram_answer_anchor_is_next_to_the_honest_sentence(self):
        js = _read("app.js")
        anchors = [m.start() for m in re.finditer(r'common\.open_telegram"\)\]\)\);', js)]
        anchors += [m.start() for m in re.finditer(r'\[ans\.text\]\)\);', js)]
        self.assertTrue(anchors)
        for pos in anchors:
            window = js[max(0, pos - 900):pos + 400]
            line = js[js.rfind("\n", 0, pos) + 1:pos]
            if "disabled: true" in line:          # a disabled button is not an answer path
                continue
            self.assertTrue("ux.dec.honest_path" in window or "ans.reason" in window,
                            f"answer link at {pos} without the honest sentence")


class TestUnreadQueueIsNotZero(unittest.TestCase):
    """ARB 09.10 preview: an unread decision queue printed «Вопросов к вам сейчас нет» under «Не измерено»."""

    def test_no_questions_line_requires_a_measured_queue(self):
        js = _read("app.js")
        i = js.index('t("ux.dec.none")')
        self.assertIn('d.summary.confidence === "MEASURED"', js[max(0, i - 200):i])

    def test_empty_history_line_requires_a_measured_queue(self):
        js = _read("app.js")
        i = js.index('t("ux.dec.history_empty")')
        self.assertIn('d.summary.confidence === "MEASURED"', js[max(0, i - 200):i])


class TestRound4FirstScreenMoneyAndFullDecisionText(unittest.TestCase):
    """ARB 09.10 round 4 (DIRECTOR-OS-UX-02 over Wave 2)."""

    def test_first_screen_opens_with_real_money_and_mode(self):
        # UX-04 (owner 15.10: «Настоящие деньги: $0» once per screen): on the overview the real-money
        # line is the header chip (rendered on every section except «Деньги», whose own block says it);
        # the hero then opens with the mode, before the main event.
        js = _read("app.js")
        m = re.search(r"function renderOverview\(root\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertNotIn("hl.real_line", body)
        self.assertLess(body.index("hl.mode_line"), body.index("hl.main"))
        chip = re.search(r"function renderMoneyChip\(\) \{(.*?)\n  \}", js, re.S).group(1)
        self.assertIn('if (currentArea() === "money") return;', chip)
        self.assertIn("owner_view.sections.money.real", chip)

    def test_full_card_text_rendered_without_html_parsing(self):
        js = _read("app.js")
        self.assertIn("canonicalText(sec.text)", js)
        m = re.search(r"function canonicalText\(text\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("innerHTML", m.group(1))
        self.assertNotIn("insertAdjacentHTML", js)

    def test_legacy_book_uses_the_period_return_not_a_day_count(self):
        js = _read("app.js")
        self.assertIn('tf("capital.book.period"', js)
        self.assertNotIn('tf("capital.book.evidenced_days"', js)
        i18n = _read("i18n.js")
        self.assertIn("не прогноз", i18n)
        self.assertNotIn("4,90", js + i18n)



class TestOracleRateIsLabelledAsAnotherMethod(unittest.TestCase):
    """ARB 09.10 round 5: Oracle's annualised figure (defi_engine apy_contract: (end/start)^(365/bars) − 1,
    days = number of measured BARS) sits next to an explicit «другой метод» note and the comparison
    limit vs the «Деньги» estimate; Oracle's method itself is not changed."""

    def test_source_row_adds_the_method_note_for_a_measured_annual_rate(self):
        js = _read("app.js")
        m = re.search(r"function renderSourceRow\(row\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        self.assertIn('annualized_return.state', m.group(1))
        self.assertIn('capital.sources.oracle_method', m.group(1))

    def test_note_names_the_method_and_the_comparison_limit_in_both_languages(self):
        i18n = _read("i18n.js")
        rows = re.findall(r'"capital\.sources\.oracle_method":\s*"([^"]+)"', i18n)
        self.assertEqual(len(rows), 2)
        self.assertIn("метод Oracle", rows[0])
        self.assertIn("засчитанных дней", rows[0])
        self.assertIn("один к одному", rows[0])
        self.assertIn("not comparable one-to-one", rows[1])

    def test_money_area_says_the_mode_once_behind_a_tap(self):
        js = _read("app.js")
        m = re.search(r"function renderMoneyArea\(root\) \{(.*?)\n  \}", js, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("hd.real_line", body)
        self.assertIn("hd.mode_line", body)
        self.assertIn("ux.money.mode_more", body)
        self.assertNotIn("p.note", body)
        # the limitation sentence is not repeated by full metric rows inside the mode details
        self.assertNotIn("metricRow(m.real)", body)
        self.assertNotIn("metricRow(m.readiness)", body)
        self.assertIn("ux.money.source_of", body)
