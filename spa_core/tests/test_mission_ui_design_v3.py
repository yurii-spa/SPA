"""DIRECTOR-OS-UX-03/04 — design-system guards (static, no browser).

* dark ONLY since 15.10 (owner: «белая тема вообще не нужна»; journaled inv. #16 — the light-theme
  half of these checks was replaced by a check that no light theme exists);
* the active bottom tab is visible in BOTH themes: accent on the active pill ≥ 4.5:1, inactive tab text on
  the nav background ≥ 4.5:1 (owner 13.10: «в светлой теме нижние кнопки плохо различимы»);
* the test-only refresh hook never reaches the production shell.
"""
import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "spa_core" / "studio_os" / "mission_ui"
CSS = (UI / "styles.css").read_text(encoding="utf-8")
JS = (UI / "app.js").read_text(encoding="utf-8")
V3 = CSS[CSS.index("DIRECTOR-OS-UX-03 — design system"):]


def _block(selector_start: str) -> dict:
    i = V3.index(selector_start)
    body = V3[V3.index("{", i) + 1: V3.index("}", i)]
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))


V4 = CSS[CSS.index("DIRECTOR-OS-UX-04 — the owner's mockup"):]
DARK = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", V4[V4.index(":root {"):V4.index("}", V4.index(":root {"))]))


def _rgb(hexv: str):
    h = hexv.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(c):
    def ch(x):
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _blend(fg_rgba: str, bg_hex: str):
    m = re.match(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)", fg_rgba)
    if not m:
        return _rgb(fg_rgba)
    r, g, b, a = int(m[1]) / 255, int(m[2]) / 255, int(m[3]) / 255, float(m[4])
    bg = _rgb(bg_hex)
    return (r * a + bg[0] * (1 - a), g * a + bg[1] * (1 - a), b * a + bg[2] * (1 - a))


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_dark_is_the_only_theme():
    assert "THEME_KEY" not in JS and "data-theme" not in JS
    assert 'data-theme="light"' not in CSS
    assert DARK["--bg"].startswith("#07")


def test_active_tab_and_inactive_tabs_are_readable_in_both_themes():
    for name, t in (("dark", DARK),):
        bg = t["--bg"]
        nav_bg = _blend(t["--nav-bg"], bg) if t["--nav-bg"].startswith("rgba") else _rgb(t["--nav-bg"])
        nav_hex = "#%02x%02x%02x" % tuple(round(x * 255) for x in nav_bg)
        pill = _blend(t["--accent-soft"], nav_hex) if t["--accent-soft"].startswith("rgba") else _rgb(t["--accent-soft"])
        assert _ratio(_rgb(t["--accent"]), pill) >= 4.5, (name, "active tab")
        assert _ratio(_rgb(t["--nav-fg"]), nav_bg) >= 4.5, (name, "inactive tab")
        assert _ratio(_rgb(t["--text-dim"]), _rgb(t["--bg-elevated"])) >= 4.5, (name, "secondary text")


def test_active_tab_has_a_shape_not_only_a_colour():
    assert re.search(r"\.nav-item\.active,\s*\.nav-item\[aria-current=\"page\"\]\s*\{[^}]*background:\s*var\(--accent-soft\)", V3)
    assert ".nav-item.active::before" in V3
    assert '"aria-current": a === active ? "page" : null' in JS


def test_refresh_hook_is_test_only():
    assert "dos-refresh-ms" in JS
    assert "dos-refresh-ms" not in (UI / "index.html").read_text(encoding="utf-8")


def test_refresh_keeps_open_cards_by_stable_keys():
    assert "renderAll({ keepState: true });" in JS
    assert 'data-decision-id' in JS and "captureState" in JS and "restoreState" in JS
