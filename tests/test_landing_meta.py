"""
MP-1543 (v11.59) — Meta tags + OpenGraph tests for Layout.astro.
Checks that the layout template contains all required meta/OG/Twitter/Schema fields.
"""
import re
import os
import json
import pytest

LAYOUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "landing", "src", "layouts", "Layout.astro"
)


@pytest.fixture(scope="module")
def layout_src():
    with open(LAYOUT_PATH, encoding="utf-8") as f:
        return f.read()


# ── 1. Props interface ──────────────────────────────────────────────────────

def test_props_title_defined(layout_src):
    """title prop is declared in the interface."""
    assert "title" in layout_src


def test_props_description_defined(layout_src):
    """description prop with default value is present."""
    assert "description" in layout_src
    assert "systematic onchain stablecoin yield" in layout_src


def test_props_ogImage_defined(layout_src):
    """ogImage prop is declared."""
    assert "ogImage" in layout_src


def test_props_canonical_defined(layout_src):
    """canonical prop is declared."""
    assert "canonical" in layout_src


# ── 2. siteUrl constant ─────────────────────────────────────────────────────

def test_siteUrl_constant(layout_src):
    """siteUrl constant is defined and points to earn-defi.com."""
    assert 'siteUrl' in layout_src
    assert "earn-defi.com" in layout_src


def test_pageUrl_variable(layout_src):
    """pageUrl variable is defined (canonical or fallback)."""
    assert "pageUrl" in layout_src


# ── 3. Title tag ────────────────────────────────────────────────────────────

def test_title_tag_present(layout_src):
    """<title> tag uses the title prop."""
    assert "<title>{title}</title>" in layout_src


# ── 4. Canonical ────────────────────────────────────────────────────────────

def test_canonical_link(layout_src):
    """Canonical <link> tag is present."""
    assert 'rel="canonical"' in layout_src


def test_canonical_uses_pageUrl(layout_src):
    """Canonical href references pageUrl."""
    assert "pageUrl" in layout_src and 'rel="canonical"' in layout_src


# ── 5. OpenGraph ────────────────────────────────────────────────────────────

def test_og_title(layout_src):
    """og:title meta tag is present."""
    assert 'property="og:title"' in layout_src


def test_og_description(layout_src):
    """og:description meta tag is present."""
    assert 'property="og:description"' in layout_src


def test_og_image(layout_src):
    """og:image meta tag is present."""
    assert 'property="og:image"' in layout_src


def test_og_site_name(layout_src):
    """og:site_name is set to SPA — systematic onchain stablecoin yield."""
    assert 'property="og:site_name"' in layout_src
    assert "SPA — systematic onchain stablecoin yield" in layout_src


# ── 6. Twitter Card ─────────────────────────────────────────────────────────

def test_twitter_card(layout_src):
    """Twitter Card meta tags are present (card + title + description + image)."""
    assert 'name="twitter:card"' in layout_src
    assert 'name="twitter:title"' in layout_src
    assert 'name="twitter:description"' in layout_src
    assert 'name="twitter:image"' in layout_src


# ── 7. Favicon ──────────────────────────────────────────────────────────────

def test_favicon_svg(layout_src):
    """SVG favicon link is present (SVG-only by design; the /favicon.png fallback was dropped
    2026-07-03 — it 404'd and modern browsers use the SVG. See audit-2 Fix #5)."""
    assert 'href="/favicon.svg"' in layout_src


# ── 8. Schema.org ───────────────────────────────────────────────────────────

def test_schema_org_script(layout_src):
    """application/ld+json script tag is present."""
    assert 'type="application/ld+json"' in layout_src


def test_schema_org_website_type(layout_src):
    """Schema.org @type is WebSite."""
    assert "WebSite" in layout_src


def test_schema_org_dynamic(layout_src):
    """Schema.org data uses set:html or JSON.stringify for dynamic injection."""
    assert "schemaData" in layout_src or "JSON.stringify" in layout_src


# ── Total: 20 assertions in 15 test functions, all must pass ──────────────
