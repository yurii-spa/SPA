/**
 * SPA site-wide i18n runtime (vanilla JS, no deps).
 *
 * Mechanism (decoupled — any agent can translate any page by tagging elements):
 *   - Any element carrying a `data-ru="<russian text>"` attribute is translatable.
 *   - English is the default visible textContent in the markup.
 *   - On first switch to RU, the element's original EN text is cached in `data-en-orig`.
 *   - setLang('ru') swaps textContent -> data-ru.
 *   - setLang('en') restores textContent <- data-en-orig.
 *   - Choice persists in localStorage under 'spa_lang' (default 'en').
 *   - <html lang> is kept in sync.
 *   - A fixed top-right "EN | RU" pill toggle is wired (or injected if absent).
 *
 * Idempotent and robust: safe to load on every page, safe to call setLang() repeatedly,
 * and it re-applies the saved language on DOMContentLoaded so SSR pages render correct.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "spa_lang";
  var SUPPORTED = ["en", "ru"];

  function getLang() {
    try {
      var v = window.localStorage.getItem(STORAGE_KEY);
      if (v && SUPPORTED.indexOf(v) !== -1) return v;
    } catch (e) { /* localStorage may be unavailable */ }
    return "en";
  }

  function storeLang(lang) {
    try { window.localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* ignore */ }
  }

  // Apply RU/EN text to all tagged elements.
  function applyTranslations(lang) {
    var nodes = document.querySelectorAll("[data-ru]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      // Cache the original EN text exactly once.
      if (!el.hasAttribute("data-en-orig")) {
        el.setAttribute("data-en-orig", el.textContent);
      }
      if (lang === "ru") {
        var ru = el.getAttribute("data-ru");
        if (ru != null) el.textContent = ru;
      } else {
        var en = el.getAttribute("data-en-orig");
        if (en != null) el.textContent = en;
      }
    }
  }

  // Reflect active language on the toggle pill.
  function updateToggleState(lang) {
    var toggle = document.getElementById("spa-lang-toggle");
    if (!toggle) return;
    var btns = toggle.querySelectorAll("[data-lang]");
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      var active = b.getAttribute("data-lang") === lang;
      b.setAttribute("aria-pressed", active ? "true" : "false");
      b.classList.toggle("spa-lang-active", active);
    }
  }

  // Public global: switch language everywhere.
  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) === -1) lang = "en";
    storeLang(lang);
    try {
      var htmlEl = document.documentElement;
      if (htmlEl) htmlEl.setAttribute("lang", lang);
    } catch (e) { /* ignore */ }
    applyTranslations(lang);
    updateToggleState(lang);
  }

  // Inject the fixed top-right pill toggle if the page didn't ship one.
  function ensureToggle() {
    if (document.getElementById("spa-lang-toggle")) return;
    if (!document.body) return;

    var style = document.getElementById("spa-lang-toggle-style");
    if (!style) {
      style = document.createElement("style");
      style.id = "spa-lang-toggle-style";
      style.textContent =
        "#spa-lang-toggle{position:fixed;top:14px;right:14px;z-index:9999;display:inline-flex;" +
        "align-items:center;gap:1px;padding:2px;border-radius:9999px;" +
        "background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);" +
        "backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);" +
        "font-family:Inter,system-ui,sans-serif;font-size:11px;line-height:1;" +
        "box-shadow:0 2px 8px rgba(0,0,0,0.3)}" +
        "#spa-lang-toggle button{appearance:none;background:transparent;border:0;cursor:pointer;" +
        "color:rgba(255,255,255,0.5);font-weight:600;letter-spacing:0.04em;" +
        "padding:5px 10px;border-radius:9999px;transition:color .15s,background .15s}" +
        "#spa-lang-toggle button:hover{color:rgba(255,255,255,0.85)}" +
        "#spa-lang-toggle button.spa-lang-active{color:#fff;background:rgba(255,255,255,0.12)}" +
        "#spa-lang-toggle .spa-lang-sep{color:rgba(255,255,255,0.2);padding:0 1px;user-select:none}";
      document.head.appendChild(style);
    }

    var toggle = document.createElement("div");
    toggle.id = "spa-lang-toggle";
    toggle.setAttribute("role", "group");
    toggle.setAttribute("aria-label", "Language");
    toggle.innerHTML =
      '<button type="button" data-lang="en" aria-pressed="true">EN</button>' +
      '<span class="spa-lang-sep" aria-hidden="true">|</span>' +
      '<button type="button" data-lang="ru" aria-pressed="false">RU</button>';
    document.body.appendChild(toggle);
  }

  // Wire click handlers (delegated; idempotent via a flag on the node).
  function wireToggle() {
    var toggle = document.getElementById("spa-lang-toggle");
    if (!toggle || toggle.getAttribute("data-wired") === "1") return;
    toggle.setAttribute("data-wired", "1");
    toggle.addEventListener("click", function (ev) {
      var t = ev.target;
      while (t && t !== toggle && !t.getAttribute("data-lang")) t = t.parentNode;
      if (t && t.getAttribute && t.getAttribute("data-lang")) {
        setLang(t.getAttribute("data-lang"));
      }
    });
  }

  function init() {
    ensureToggle();
    wireToggle();
    setLang(getLang());
  }

  // Expose globals.
  window.setLang = setLang;
  window.spaI18n = { setLang: setLang, getLang: getLang, apply: applyTranslations };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
