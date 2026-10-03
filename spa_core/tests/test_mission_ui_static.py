"""spa_core/tests/test_mission_ui_static.py — Mission Control v1 UI static checks (ADR-552).

Stdlib-only. Verifies the no-build web app under spa_core/studio_os/mission_ui/ against the
CSP and security rules fixed by the architecture gate:
  - index.html is a shell only (no inline <script>/<style> content, no on*= handlers).
  - app.js never touches innerHTML/outerHTML/insertAdjacentHTML/eval/new Function, and every
    href it assigns is either a hardcoded internal '#area' link or passes through safeLink(),
    the one helper allowed to approve a model-derived https://t.me/ URL.
  - i18n.js carries one RU+EN dictionary with an identical key set for every UI label.
  - styles.css declares the dark/light split and a desktop breakpoint.
"""
import json
import re
import unittest
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[2] / "spa_core" / "studio_os" / "mission_ui"

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


if __name__ == "__main__":
    unittest.main()
