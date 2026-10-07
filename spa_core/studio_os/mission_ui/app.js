/* spa_core/studio_os/mission_ui/app.js — Director OS v2 (ADR-571, RM-TRUTH-01 WP2)
 *
 * Read-only renderer for the `truth` key of mission.json (§2.0 of DIRECTOR_OS_V2_DESIGN.md).
 * No framework, no build step, ES2020. The five areas are Главная (home) · Капитал (capital) ·
 * Студия (studio) · Продукт (product) · Решения (decisions).
 *
 * TEXT SOURCES (two, never a third):
 *  - A "cell" {state, display_ru, display_en, metric_type, as_of, canon, freshness, unknown_ru,
 *    unknown_en} carries an ALREADY-COMPOSED sentence (WP1 builds display_ru/display_en from the
 *    same copy deck server-side); this file shows it verbatim and never recomputes it.
 *  - A bare field next to a `state` (no display_ru of its own) is RAW data, and this file composes
 *    the sentence itself with the matching copy-deck template via MC_I18N.tf(key, vars) — i18n.js
 *    is the copy deck (scratchpad/rmtruth/D/copy_deck_ru.json) imported verbatim, so no UI sentence
 *    here is invented outside it.
 *  - Whenever state is NOT_MEASURED / STALE / CORRUPT / NOT_ENOUGH_HISTORY, the unknown_ru/unknown_en
 *    (or the matching *.unknown copy-deck key) is shown INSTEAD of the composed value — never 0,
 *    never a dash, never green (CLAUDE.md inv. #17).
 *
 * SECURITY (enforced by spa_core/tests/test_mission_ui_static.py, extended for v2):
 *  - DOM is built with document.createElement + textContent only: no markup-from-string sink of
 *    any kind, and no dynamic code construction of any kind.
 *  - Any href taken from the model is only ever set through safeLink(), which requires the exact
 *    prefix 'https://t.me/'. Every INTERNAL navigation href is "#" + a variable that can only ever
 *    hold one of a small hardcoded literal set (chosen by closed ternaries over a fixed vocabulary,
 *    e.g. a tile's `key` or an attention item's `kind`) — never a raw model string copied into the
 *    href, even after validation. This mirrors the original v1 pattern (`href: "#" + a` over the
 *    fixed AREAS array) and extends it to every v2 call site.
 *  - No <form>, no fetch() or XHR with a non-GET method, no act:/pause/resume/kill/
 *    set_status/record_owner_answer anywhere in this file: the page is read-only end to end.
 */
"use strict";

(function () {
  var t = window.MC_I18N.t;
  var tf = window.MC_I18N.tf;
  var AREAS = ["home", "capital", "studio", "product", "decisions"];
  var NAV_ICON = { home: "⌂", capital: "◈", studio: "⚙", product: "◉", decisions: "✉" };
  var STAGE_KEYS = ["IDEA", "TASK", "ASSIGNED", "RUN", "ARTIFACT", "REVIEW", "DECISION", "RELEASE", "OUTCOME", "MEMORY"];
  var REFRESH_MS = 60000;
  var STALE_AFTER_MIN = 15;
  var TELEGRAM_PREFIX = "https://t.me/";
  var CAPITAL_TABS = ["sources", "defi", "trading_lab", "btc", "basis", "treasury", "sherlock", "oracle", "readiness"];

  var currentModel = null;
  var fetchFailed = false;
  var staleFlag = false;
  var capitalSubTab = "sources";

  // ── tiny DOM builder — createElement + textContent only ──────────────────────────────────
  function h(tag, opts, children) {
    var node = document.createElement(tag);
    if (opts) {
      Object.keys(opts).forEach(function (k) {
        var v = opts[k];
        if (v === undefined || v === null) return;
        if (k === "class") node.className = v;
        else if (k === "disabled") { if (v) node.disabled = true; }
        else if (k === "hidden") { if (v) node.hidden = true; }
        else node.setAttribute(k, v);
      });
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      if (typeof c === "string" || typeof c === "number") node.appendChild(document.createTextNode(String(c)));
      else node.appendChild(c);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function get(obj, path, def) {
    try {
      var cur = obj;
      var parts = path.split(".");
      for (var i = 0; i < parts.length; i++) {
        if (cur === null || cur === undefined) return def;
        cur = cur[parts[i]];
      }
      return cur === undefined ? def : cur;
    } catch (e) {
      return def;
    }
  }

  // ── the one guard every model-derived href must pass through ──────────────────────────────
  function safeLink(url) {
    if (typeof url === "string" && url.indexOf(TELEGRAM_PREFIX) === 0) return url;
    return null;
  }

  function telegramButton(url, label) {
    var href = safeLink(url);
    if (!href) return h("button", { class: "btn btn-disabled", disabled: true, type: "button" }, [label]);
    return h("a", { class: "btn", href: safeLink(url), target: "_blank", rel: "noopener noreferrer" }, [label]);
  }

  // ── LEGACY v1 helpers (ADR-552) — kept verbatim, unused by the v2 routing below ───────────
  // spa_core/tests/test_mission_control_contract.py (WP1's exclusive file, not touched here) still
  // pins these functions and the v1 Capital-area cards (Oracle/live-readiness/research-universe/
  // Sherlock/candidate-evidence) by literal source text and runs some of them under node — they
  // exercised real "[object Object]" / no-action-control regressions and are still valid guards.
  // The v2 Capital tab (renderOracle/renderSherlock/renderReadiness/renderTradingLab above) is the
  // live UI; this block is dead code on purpose, kept only so that contract does not regress while
  // WP1/integration journals its own amendment of that file (inv. #16) to retire it for v2.
  // ── formatting ──────────────────────────────────────────────────────────────────────────
  function textOrNM(v) {
    if (v === null || v === undefined) return t("common.not_measured");
    if (Array.isArray(v)) return v.length ? v.map(textOrNM).join(", ") : t("common.none");
    if (typeof v === "object") {
      return Object.keys(v).map(function (k) { return k + ": " + textOrNM(v[k]); }).join(" · ");
    }
    return String(v);
  }

  function kv(labelKey, value) {
    if (value === "UNKNOWN") {
      return h("div", { class: "kv-row" }, [
        h("span", { class: "k" }, [t(labelKey)]),
        h("span", { class: "v chip chip--unknown" }, [t("common.unknown_named")]),
      ]);
    }
    return h("div", { class: "kv-row" }, [
      h("span", { class: "k" }, [t(labelKey)]),
      h("span", { class: "v" }, [textOrNM(value)]),
    ]);
  }

  function renderListField(labelKey, arr, mapFn) {
    var wrap = h("div", { class: "list-section" });
    wrap.appendChild(h("div", { class: "k" }, [t(labelKey)]));
    if (arr === null || arr === undefined) {
      wrap.appendChild(h("div", { class: "v" }, [t("common.not_measured")]));
      return wrap;
    }
    if (!Array.isArray(arr) || arr.length === 0) {
      wrap.appendChild(h("div", { class: "v" }, [t("common.none")]));
      return wrap;
    }
    var ul = h("ul", { class: "plain-list" });
    arr.forEach(function (item) {
      var text = mapFn ? mapFn(item) : (typeof item === "string" ? item : JSON.stringify(item));
      ul.appendChild(h("li", {}, [text]));
    });
    wrap.appendChild(ul);
    return wrap;
  }

  // ── health badge — colour comes ONLY from the health vocabulary (ADR-537) ─────────────────
  var BADGE_COLOUR = { HEALTHY: "ok", DEGRADED: "warn", STALE: "warn", NOT_MEASURED: "unknown", CRITICAL: "alert", UNKNOWN: "unknown" };

  function renderBadge(state, forceStale) {
    var known = state || "NOT_MEASURED";
    // An old model shows «stale» — but a last-known CRITICAL is never repainted as a mild warning
    // (WP-A05 #9): it keeps its colour and gains the «stale» mark.
    var effective = forceStale && known !== "CRITICAL" ? "STALE" : known;
    var colourClass = BADGE_COLOUR[effective] || "unknown";
    var label = t("vocab.health." + effective);
    if (forceStale && known === "CRITICAL") label += " · " + t("vocab.health.STALE");
    return h("span", { class: "badge badge--" + colourClass }, [label]);
  }

  function renderWorkChip(state) {
    var label = state ? (t("vocab.work." + state) || state) : t("common.unknown");
    return h("span", { class: "chip chip--work" }, [label]);
  }
  // ── end legacy formatting helpers ─────────────────────────────────────────────────────────

  // ── language pick: RU first, EN falls back to RU, RU falls back to EN ────────────────────
  function bi(ru, en) {
    var lang = window.MC_I18N.getLang();
    if (lang === "ru") return (ru === null || ru === undefined || ru === "") ? en : ru;
    return (en === null || en === undefined || en === "") ? ru : en;
  }

  // ── §2.0 cell vocabulary ───────────────────────────────────────────────────────────────────
  function isUnknownState(state) {
    return !state || state === "NOT_MEASURED" || state === "STALE" || state === "CORRUPT" || state === "NOT_ENOUGH_HISTORY";
  }

  function stateBadgeClass(state) {
    if (state === "MEASURED" || state === "MEASURED_ZERO") return "ok";
    if (state === "NOT_ENOUGH_HISTORY" || state === "STALE") return "warn";
    if (state === "CORRUPT") return "alert";
    return "unknown"; // NOT_MEASURED / missing
  }

  function stateBadge(cell) {
    var state = (cell && cell.state) || "NOT_MEASURED";
    return h("span", { class: "badge badge--" + stateBadgeClass(state) }, [t("state." + state) || state]);
  }

  function metricChip(cell) {
    var mt = cell && cell.metric_type;
    if (!mt) return null;
    return h("span", { class: "chip chip--metric" }, [t("metric_type." + mt) || mt]);
  }

  function unknownText(cell) {
    return bi(cell && cell.unknown_ru, cell && cell.unknown_en) || t("state.NOT_MEASURED");
  }

  function composedText(cell) {
    return bi(cell && cell.display_ru, cell && cell.display_en) || null;
  }

  function kvPlain(label, value) {
    return h("div", { class: "kv-row" }, [
      h("span", { class: "k" }, [label]),
      h("span", { class: "v" }, [value === null || value === undefined || value === "" ? t("state.NOT_MEASURED") : value]),
    ]);
  }

  // ── evidence drawer — every card's only place for canon / as_of / freshness rule (§2.5) ────
  function evRow(label, value) {
    return h("div", { class: "kv-row evidence-row" }, [
      h("span", { class: "k" }, [label]),
      h("span", { class: "v" }, [value === null || value === undefined || value === "" ? "—" : String(value)]),
    ]);
  }

  function evidenceDrawer(cell) {
    if (!cell || (!cell.canon && !cell.as_of && !cell.freshness)) return null;
    var det = h("details", { class: "evidence" });
    det.appendChild(h("summary", {}, [t("common.evidence")]));
    var body = h("div", { class: "evidence-body" });
    body.appendChild(evRow(t("common.canon"), cell.canon));
    body.appendChild(evRow(t("common.as_of"), cell.as_of));
    var fr = cell.freshness || {};
    var ruleText = fr.rule === "fallback" ? t("common.fallback_rule") : (fr.rule || null);
    var extra = [];
    if (fr.age_min !== null && fr.age_min !== undefined) extra.push("age_min=" + fr.age_min);
    if (fr.stale_after_min !== null && fr.stale_after_min !== undefined) extra.push("stale_after_min=" + fr.stale_after_min);
    body.appendChild(evRow(t("common.fresh_rule"), [ruleText].concat(extra).filter(Boolean).join(" · ")));
    det.appendChild(body);
    return det;
  }

  // ── owner layer vs evidence layer (ADR-612) ─────────────────────────────────────────────
  // The model field ``plain_ru`` is the owner sentence (no codes); the technical text it was made
  // from stays one tap away. ``plain_tone`` never upgrades a state: "ok" only where the producer
  // itself said OK — an unknown code arrives as "unknown" and is rendered grey, never green.
  function toneClass(tone) {
    return tone === "ok" || tone === "warn" || tone === "alert" ? tone : "unknown";
  }

  function techDetails(lines) {
    lines = (lines || []).filter(function (x) { return x !== null && x !== undefined && x !== ""; });
    if (!lines.length) return null;
    var det = h("details", { class: "evidence tech-details" });
    det.appendChild(h("summary", {}, [t("common.tech_details")]));
    var body = h("div", { class: "evidence-body" });
    lines.forEach(function (l) { body.appendChild(h("p", { class: "note mono-wrap" }, [String(l)])); });
    det.appendChild(body);
    return det;
  }

  // ── generic card shell ─────────────────────────────────────────────────────────────────────
  function card(titleText, badgeNode) {
    var c = h("section", { class: "card" });
    var head = h("div", { class: "card-head" });
    head.appendChild(h("h2", { class: "card-title" }, [titleText]));
    if (badgeNode) head.appendChild(badgeNode);
    c.appendChild(head);
    return c;
  }

  // Covers the common shape: title (i18n key) + state badge + metric-type chip + composed/unknown
  // text + an optional extra body builder + the evidence drawer. Most cards use this unchanged.
  function cellCard(titleKey, cell, extraBuilder) {
    cell = cell || {};
    var c = card(t(titleKey), stateBadge(cell));
    var mc = metricChip(cell);
    if (mc) c.appendChild(h("div", { class: "chip-row" }, [mc]));
    if (isUnknownState(cell.state)) {
      c.appendChild(h("p", { class: "cell-text cell-text--unknown" }, [unknownText(cell)]));
    } else {
      var txt = composedText(cell);
      if (txt) c.appendChild(h("p", { class: "cell-text" }, [txt]));
    }
    if (extraBuilder) extraBuilder(c, cell);
    var ev = evidenceDrawer(cell);
    if (ev) c.appendChild(ev);
    return c;
  }

  // ── time / staleness (reader's clock, per ADR-552) ─────────────────────────────────────────
  function dataAgeMin(model) {
    var gen = get(model, "generated_at", null);
    if (!gen) return null;
    var ts = new Date(gen).getTime();
    if (isNaN(ts)) return null;
    return (Date.now() - ts) / 60000;
  }

  function isStaleGlobal() {
    return staleFlag;
  }

  // ── fetch loop ──────────────────────────────────────────────────────────────────────────
  function loadModel() {
    fetch("mission.json", { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("http " + res.status);
        return res.json();
      })
      .then(function (data) {
        currentModel = data;
        fetchFailed = false;
        var age = dataAgeMin(currentModel);
        staleFlag = age === null || age > STALE_AFTER_MIN;
        renderAll();
      })
      .catch(function () {
        fetchFailed = true;
        currentModel = null;
        staleFlag = true;
        renderAll();
      });
  }

  function truth() {
    return get(currentModel, "truth", null) || {};
  }

  // ── routing ─────────────────────────────────────────────────────────────────────────────
  function currentArea() {
    var hsh = (location.hash || "").replace("#", "").split("/")[0];
    return AREAS.indexOf(hsh) >= 0 ? hsh : "home";
  }

  function showArea(area) {
    AREAS.forEach(function (a) {
      var sec = document.getElementById("area-" + a);
      if (sec) sec.hidden = a !== area;
    });
  }

  function renderNav() {
    var nav = document.getElementById("bottom-nav");
    clear(nav);
    var active = currentArea();
    AREAS.forEach(function (a) {
      var link = h("a", { class: "nav-item" + (a === active ? " active" : ""), href: "#" + a }, [
        h("span", { class: "nav-icon", "aria-hidden": "true" }, [NAV_ICON[a] || "•"]),
        h("span", { class: "nav-label" }, [t("nav." + a)]),
      ]);
      nav.appendChild(link);
    });
  }

  function renderHeaderStaticText() {
    var title = document.querySelector(".app-title");
    if (title) title.textContent = t("header.title");
  }

  function renderIntake() {
    var nav = document.getElementById("intake-actions");
    clear(nav);
    var intake = get(currentModel, "intake", {}) || {};
    nav.appendChild(telegramButton(intake.ask, t("intake.ask")));
    nav.appendChild(telegramButton(intake.idea, t("intake.idea")));
    nav.appendChild(telegramButton(intake.voice, t("intake.voice")));
    if (intake.how) {
      var details = h("details", { class: "intake-how" });
      details.appendChild(h("summary", {}, [t("intake.how")]));
      details.appendChild(h("p", {}, [intake.how]));
      nav.appendChild(details);
    }
  }

  function renderLegend() {
    var el = document.getElementById("legend");
    clear(el);
    el.appendChild(h("p", { class: "legend-note" }, [t("legend.colour")]));
  }

  // Header money chip — permanent on every tab (design §2.1). Source: truth.home.money_chip.
  function renderMoneyChip() {
    var el = document.getElementById("money-chip");
    if (!el) return;
    clear(el);
    var mc = get(truth(), "home.money_chip", null);
    var text;
    if (!mc || isUnknownState(mc.state)) {
      text = (mc && bi(mc.unknown_ru, mc.unknown_en)) || t("header.money_chip.unknown");
    } else {
      var usd = "$" + (mc.usd === null || mc.usd === undefined ? "0" : mc.usd);
      text = tf("header.money_chip", { usd: usd });
    }
    el.appendChild(h("span", { class: "chip chip--money" }, [text]));
  }

  function renderStatusStrip() {
    var strip = document.getElementById("status-strip");
    clear(strip);
    if (fetchFailed || !currentModel) {
      strip.appendChild(h("div", { class: "status-banner status-banner--alert" }, [t("header.no_connection")]));
      return;
    }
    if (staleFlag) {
      var ageMin = dataAgeMin(currentModel);
      var unit = window.MC_I18N.getLang() === "ru" ? " мин" : " min";
      var ageText = ageMin === null ? t("state.NOT_MEASURED") : Math.round(ageMin) + unit;
      strip.appendChild(h("div", { class: "status-banner status-banner--warn" }, [tf("header.stale", { age: ageText })]));
    }
  }

  // ── HOME ───────────────────────────────────────────────────────────────────────────────
  var HOME_TILE_TITLE_KEY = {
    system: "home.tile.system", yield: "home.tile.yield", product: "home.tile.product",
    claude: "home.tile.claude", needs: "home.tile.needs",
  };

  // Closed ternary over a fixed vocabulary of tile keys — the href can only ever be one of the
  // five literal "#area" strings on the right, never a string copied from the model (see header
  // security note above).
  function homeTileLinkArea(key) {
    if (key === "yield") return "capital";
    if (key === "product") return "product";
    if (key === "needs") return "decisions";
    return "studio"; // system, claude, and any unrecognised key
  }

  function renderHomeTile(tile) {
    tile = tile || {};
    var titleKey = HOME_TILE_TITLE_KEY[tile.key] || "home.tile.system";
    var linkArea = homeTileLinkArea(tile.key);
    var unknown = isUnknownState(tile.state);
    var cls = "home-tile home-tile--" + (unknown ? stateBadgeClass(tile.state) : stateBadgeClass(tile.state));
    var a = h("a", { class: cls, href: "#" + linkArea });
    a.appendChild(h("div", { class: "home-tile-label" }, [t(titleKey)]));
    var text = unknown ? unknownText(tile) : (composedText(tile) || unknownText(tile));
    a.appendChild(h("div", { class: "home-tile-value" + (unknown ? " home-tile-value--unknown" : "") }, [text]));
    return a;
  }

  // Closed vocabulary of attention "kind"s (design §2.1). Never trusts a raw link_area string.
  function attentionLinkArea(kind) {
    if (kind === "old_owner_item" || kind === "problem") return "decisions";
    if (kind === "kill_switch" || kind === "derisk" || kind === "same_host") return "studio";
    return "home";
  }

  function renderAttentionLine(item) {
    item = item || {};
    var kind = item.kind;
    var text;
    if (kind === "same_host") text = t("home.attention.same_host");
    else if (kind === "kill_switch") text = t("home.attention.kill_switch");
    else if (kind === "derisk") text = t("home.attention.derisk");
    else if (kind === "old_owner_item") text = tf("home.attention.old_owner_item", { days: item.days, title: bi(item.title_ru, item.title_en) });
    else if (kind === "problem") text = tf("home.attention.problem", { what: bi(item.what_ru, item.what_en) });
    else if (kind === "corrupt") text = tf("home.attention.corrupt", { what: bi(item.what_ru, item.what_en) });
    else text = t("state.NOT_MEASURED");
    var linkArea = attentionLinkArea(kind);
    return h("a", { class: "link-item", href: "#" + linkArea }, [text]);
  }

  function renderHome(root) {
    var home = get(truth(), "home", {}) || {};
    var stripWrap = h("div", { class: "home-strip" });
    (home.strip || []).forEach(function (tile) { stripWrap.appendChild(renderHomeTile(tile)); });
    if (!home.strip || !home.strip.length) {
      stripWrap.appendChild(h("p", { class: "empty-note" }, [t("state.NOT_MEASURED")]));
    }
    root.appendChild(stripWrap);
    var att = home.attention || [];
    if (att.length) {
      var sec = h("section", { class: "card attention-card" });
      sec.appendChild(h("h2", { class: "card-title" }, [t("home.attention.title")]));
      var ul = h("ul", { class: "plain-list" });
      att.forEach(function (item) { ul.appendChild(h("li", {}, [renderAttentionLine(item)])); });
      sec.appendChild(ul);
      root.appendChild(sec);
    }
  }

  // ── CAPITAL ────────────────────────────────────────────────────────────────────────────
  function renderDefiBook(key, book) {
    book = book || {};
    var c = card(t("capital.book." + key), stateBadge(book));
    var mc = metricChip(book);
    if (mc) c.appendChild(h("div", { class: "chip-row" }, [mc]));
    if (book.state === "NOT_ENOUGH_HISTORY") {
      c.appendChild(h("p", { class: "cell-text" }, [tf("home.tile.yield.accumulating", { book: t("capital.book." + key), n: book.accumulating_days })]));
    } else if (isUnknownState(book.state)) {
      c.appendChild(h("p", { class: "cell-text cell-text--unknown" }, [unknownText(book)]));
    } else {
      c.appendChild(h("p", { class: "cell-text" }, [tf("home.tile.yield.value", { rate: bi(book.rate_ru, book.rate_en), dd: bi(book.dd_ru, book.dd_en) })]));
      if (book.evidenced_days !== undefined) c.appendChild(h("p", { class: "note" }, [tf("capital.book.evidenced_days", { n: book.evidenced_days })]));
      c.appendChild(h("p", { class: "note" }, [t("capital.book.live_not_approved")]));
    }
    var ev = evidenceDrawer(book);
    if (ev) c.appendChild(ev);
    return c;
  }

  function renderTargets(targets) {
    targets = targets || {};
    var c = card(t("capital.target.label"), stateBadge(targets));
    var mc = metricChip(targets);
    if (mc) c.appendChild(h("div", { class: "chip-row" }, [mc]));
    if (isUnknownState(targets.state)) c.appendChild(h("p", { class: "cell-text cell-text--unknown" }, [unknownText(targets)]));
    else c.appendChild(h("p", { class: "cell-text" }, [composedText(targets) || unknownText(targets)]));
    var ev = evidenceDrawer(targets);
    if (ev) c.appendChild(ev);
    return c;
  }

  function renderTradingLab(cell) {
    return cellCard("capital.tab.trading_lab", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      var row = h("div", { class: "chip-row" });
      row.appendChild(h("span", { class: "chip" }, [tf("capital.lab.candidates", { n: cell.candidates })]));
      row.appendChild(h("span", { class: "chip" }, [tf("capital.lab.forward", { n: cell.forward })]));
      row.appendChild(h("span", { class: "chip" }, [tf("capital.lab.champions", { n: cell.champions })]));
      c.appendChild(row);
      c.appendChild(h("p", { class: "note" }, [cell.chain_ok ? t("capital.lab.chain_ok") : t("capital.lab.chain_broken")]));
      c.appendChild(h("p", { class: "note warning-chip" }, [t("capital.lab.backtest_badge")]));
    });
  }

  function renderBtc(cell) {
    return cellCard("capital.tab.btc", cell, function (c, cell) {
      if (cell.no_canon) c.appendChild(h("div", { class: "warning-chip" }, [t("capital.btc.no_canon")]));
      if (isUnknownState(cell.state)) return;
      if (cell.external_product) c.appendChild(h("p", { class: "note" }, [t("capital.btc.external")]));
    });
  }

  function renderBasis(cell) {
    return cellCard("capital.tab.basis", cell, function (c, cell) {
      if (cell.fees_blocked) c.appendChild(h("div", { class: "warning-chip" }, [t("capital.basis.blocked_fees")]));
    });
  }

  function renderTreasury(cell) {
    return cellCard("capital.tab.treasury", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "note" }, [tf("capital.treasury.reference", { n: cell.reference_periods })]));
      if (cell.cash_usd !== undefined && cell.cash_usd !== null) {
        c.appendChild(h("p", { class: "note" }, ["$" + cell.cash_usd]));
      }
    });
  }

  function renderSherlock(cell) {
    return cellCard("capital.tab.sherlock", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "note" }, [tf("capital.sherlock.usable", { usable: cell.usable, total: cell.total })]));
      c.appendChild(h("p", { class: "note" }, [tf("capital.sherlock.awaiting", { n: cell.awaiting_review })]));
    });
  }

  function renderOracle(cell) {
    return cellCard("capital.tab.oracle", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      var stanceKey = cell.stance ? "capital.oracle.stance." + cell.stance : null;
      var stanceText = stanceKey ? t(stanceKey) : null;
      if (stanceText && stanceText !== stanceKey) c.appendChild(h("p", { class: "cell-text" }, [stanceText]));
      c.appendChild(h("p", { class: "note" }, [t("capital.oracle.advisory")]));
    });
  }

  function renderReadiness(cell) {
    return cellCard("capital.tab.readiness", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      if (cell.ready === false) c.appendChild(h("div", { class: "warning-chip" }, [t("capital.readiness.not_ready")]));
      if (cell.conditions_open !== undefined) c.appendChild(h("p", { class: "note" }, [tf("capital.readiness.conditions_open", { n: cell.conditions_open })]));
      if (cell.inventory_passed !== undefined) {
        c.appendChild(h("p", { class: "note" }, [tf("capital.readiness.inventory_note", { p: cell.inventory_passed, t: cell.inventory_total })]));
      }
      var blockers = cell.blockers || [];
      if (blockers.length) {
        var ul = h("ul", { class: "plain-list" });
        blockers.forEach(function (b) { ul.appendChild(h("li", {}, [bi(b.ru, b.en)])); });
        c.appendChild(ul);
      }
    });
  }

  // ── CAPITAL-SOURCES-01 §13: four return sources · Trading Alpha funnel · PAPER portfolio · 10–15 % question ──
  // Every string below is printed VERBATIM from the model (investment_cio.sources_summary — the same
  // projection the Telegram bot prints); nothing is computed or rounded here. Absent ⇒ «не измерено».
  function sourceText(row, key) {
    var tx = (row && row.text) || {};
    return bi(get(tx, "ru." + key, null), get(tx, "en." + key, null));
  }

  function renderSourceRow(row) {
    var box = h("div", { class: "source-row" });
    box.appendChild(h("h3", { class: "source-title" }, [bi(row.name_ru, row.name_en)]));
    var fresh = sourceText(row, "freshness");
    if (fresh) box.appendChild(h("div", { class: "warning-chip" }, [fresh]));
    box.appendChild(kvPlain(t("capital.sources.net"), sourceText(row, "net")));
    box.appendChild(kvPlain(t("capital.sources.drawdown"), sourceText(row, "drawdown")));
    box.appendChild(kvPlain(t("capital.sources.evidence"), sourceText(row, "evidence")));
    box.appendChild(kvPlain(t("capital.sources.confidence"), sourceText(row, "confidence")));
    box.appendChild(kvPlain(t("capital.sources.eligibility"), sourceText(row, "eligibility")));
    box.appendChild(kvPlain(t("capital.sources.paper_weight"), sourceText(row, "paper_weight")));
    var bl = row.blockers_plain || [];
    if (bl.length) {
      var ul = h("ul", { class: "plain-list" });
      bl.forEach(function (b) { ul.appendChild(h("li", { class: "tone-" + toneClass(b.tone) }, [b.text])); });
      box.appendChild(h("p", { class: "note" }, [t("capital.sources.blockers")]));
      box.appendChild(ul);
    }
    var raw = bl.map(function (b) { return b.raw; });
    if (row.statement) raw.unshift(row.statement);
    var td = techDetails(raw);
    if (td) box.appendChild(td);
    return box;
  }

  // A sub-card's badge is its OWN content's state (model ``sub_states``), not the feed's health: a fresh
  // Oracle view of stale sources must not be green. The body still renders (rows carry their own words).
  function subCell(cell, key) {
    cell = cell || {};
    var sub = get(cell, "sub_states." + key, null);
    var out = {};
    Object.keys(cell).forEach(function (k) { out[k] = cell[k]; });
    out.badge_state = sub || cell.state;
    return out;
  }

  function subCard(titleKey, cell, key, builder) {
    var sc = subCell(cell, key);
    var c = card(t(titleKey), stateBadge({ state: (cell && cell.state && isUnknownState(cell.state)) ? cell.state : sc.badge_state }));
    var mc = metricChip(cell);
    if (mc) c.appendChild(h("div", { class: "chip-row" }, [mc]));
    if (!cell || isUnknownState(cell.state)) {
      c.appendChild(h("p", { class: "cell-text cell-text--unknown" }, [unknownText(cell)]));
    } else if (builder) {
      builder(c, cell);
    }
    var ev = evidenceDrawer(cell);
    if (ev) c.appendChild(ev);
    return c;
  }

  function renderSources(cell) {
    return subCard("capital.tab.sources", cell, "sources", function (c, cell) {
      c.appendChild(h("p", { class: "note warning-chip" }, [t("capital.sources.boundary")]));
      var age = bi(get(cell, "view_age_text.ru", null), get(cell, "view_age_text.en", null));
      c.appendChild(h("p", { class: "note" + (cell.view_stale === true ? " warning-chip" : "") },
        [tf("capital.sources.view_age", { age: age }) + (cell.view_stale === true ? " · " + t("state.STALE") : "")]));
      c.appendChild(h("p", { class: "note" }, [tf("capital.sources.eligible_count", { n: cell.eligible_count, total: cell.risk_total })]));
      (cell.groups || []).forEach(function (g) {
        c.appendChild(h("h3", { class: "group-title" }, [bi(g.name_ru, g.name_en)]));
        var rows = g.sources || [];
        if (!rows.length) c.appendChild(h("p", { class: "note" }, [t("common.not_measured")]));
        rows.forEach(function (r) { c.appendChild(renderSourceRow(r)); });
      });
    });
  }

  function renderTradingAlphaFunnel(cell) {
    return subCard("capital.sources.ta.title", cell, "trading_alpha", function (c, cell) {
      var f = cell.trading_alpha || {};
      var row = h("div", { class: "chip-row" });
      row.appendChild(h("span", { class: "chip" }, [tf("capital.sources.ta.research", { n: f.research })]));
      row.appendChild(h("span", { class: "chip" }, [tf("capital.sources.ta.forward", { n: f.forward })]));
      row.appendChild(h("span", { class: "chip" }, [tf("capital.sources.ta.champions", { n: f.champions })]));
      c.appendChild(row);
      var sl = f.sleeve;
      if (sl) {
        c.appendChild(kvPlain(t("capital.sources.ta.sleeve"), sourceText(sl, "net")));
        c.appendChild(kvPlain(t("capital.sources.drawdown"), sourceText(sl, "drawdown")));
        c.appendChild(kvPlain(t("capital.sources.evidence"), sourceText(sl, "evidence")));
      } else {
        c.appendChild(kvPlain(t("capital.sources.ta.sleeve"), null));
      }
      var el = f.oracle_eligible === true ? t("capital.sources.ta.eligible_yes")
        : (f.oracle_eligible === false ? t("capital.sources.ta.eligible_no") : t("common.not_measured"));
      c.appendChild(kvPlain(t("capital.sources.ta.oracle"), el));
      c.appendChild(h("p", { class: "note" }, [t("capital.sources.ta.paper_only")]));
    });
  }

  function renderSourcesPortfolio(cell) {
    return subCard("capital.sources.pf.title", cell, "portfolio", function (c, cell) {
      var pf = cell.portfolio || {};
      c.appendChild(h("p", { class: "cell-text" }, [bi(get(pf, "text.ru.headline", null), get(pf, "text.en.headline", null)) || t("common.not_measured")]));
      var det = bi(get(pf, "text.ru.detail", null), get(pf, "text.en.detail", null));
      if (det) c.appendChild(h("p", { class: "note" }, [det]));
      var ul = h("ul", { class: "plain-list" });
      (cell.rows || []).forEach(function (r) {
        ul.appendChild(h("li", {}, [bi(r.name_ru, r.name_en) + " — " + sourceText(r, "paper_weight")]));
      });
      c.appendChild(h("p", { class: "note" }, [t("capital.sources.pf.weights")]));
      c.appendChild(ul);
      var td = techDetails([pf.basis, pf.reconstruction, pf.reason]);
      if (td) c.appendChild(td);
    });
  }

  function renderResearchQuestion(cell) {
    return subCard("capital.sources.rq.title", cell, "research_question", function (c, cell) {
      var rq = cell.research_question || {};
      c.appendChild(h("p", { class: "cell-text" }, [t("capital.sources.rq.question")]));
      var key = rq.state === "MEASURED" ? "capital.sources.rq.answer." + (rq.answer || "UNKNOWN")
        : "capital.sources.rq.answer.NOT_MEASURED";
      var ans = t(key);
      c.appendChild(h("p", { class: "cell-text" }, [ans === key ? t("capital.sources.rq.answer.UNKNOWN") : ans]));
      c.appendChild(h("p", { class: "note" }, [bi(rq.note_ru, rq.note_en)]));
      var td = techDetails([rq.question, rq.verdict]);
      if (td) c.appendChild(td);
    });
  }

  function renderCapitalPanel(panel, tabKey, cap) {
    if (tabKey === "sources") {
      panel.appendChild(renderSources(cap.sources));
      panel.appendChild(renderTradingAlphaFunnel(cap.sources));
      panel.appendChild(renderSourcesPortfolio(cap.sources));
      panel.appendChild(renderResearchQuestion(cap.sources));
    } else if (tabKey === "defi") {
      var defi = cap.defi || {};
      var books = defi.books || {};
      ["conservative", "balanced", "aggressive"].forEach(function (k) { panel.appendChild(renderDefiBook(k, books[k])); });
      panel.appendChild(renderTargets(defi.targets));
    } else if (tabKey === "trading_lab") panel.appendChild(renderTradingLab(cap.trading_lab));
    else if (tabKey === "btc") panel.appendChild(renderBtc(cap.btc));
    else if (tabKey === "basis") panel.appendChild(renderBasis(cap.basis));
    else if (tabKey === "treasury") panel.appendChild(renderTreasury(cap.treasury_rwa));
    else if (tabKey === "sherlock") panel.appendChild(renderSherlock(cap.sherlock));
    else if (tabKey === "oracle") panel.appendChild(renderOracle(cap.oracle));
    else if (tabKey === "readiness") panel.appendChild(renderReadiness(cap.readiness));
  }

  function renderCapital(root) {
    var cap = get(truth(), "capital", {}) || {};
    var tabsWrap = h("div", { class: "subtabs-scroll" });
    var tabsRow = h("div", { class: "subtabs-row" });
    CAPITAL_TABS.forEach(function (key) {
      var btn = h("button", { type: "button", class: "subtab-chip" + (key === capitalSubTab ? " active" : "") }, [t("capital.tab." + key)]);
      btn.addEventListener("click", function () {
        capitalSubTab = key;
        renderArea("capital");
      });
      tabsRow.appendChild(btn);
    });
    tabsWrap.appendChild(tabsRow);
    root.appendChild(tabsWrap);
    var panel = h("div", { class: "grid" });
    renderCapitalPanel(panel, capitalSubTab, cap);
    root.appendChild(panel);
  }

  // ── LEGACY v1 Capital-area cards (ADR-554/556/560/564) — kept verbatim, unused by v2 ──────
  // Same rationale as the legacy formatting helpers above: test_mission_control_contract.py pins
  // these by literal source text (some run under node) as regression guards for real
  // "[object Object]" and no-action-control bugs. Dead code on purpose pending that file's own
  // journaled retirement for v2.
  // Oracle — Chief Investment Officer (ADR-554). A paper recommendation: no button, nothing executes it.
  function pct(x) {
    return (typeof x === "number") ? Math.round(x * 100) + "%" : t("common.not_measured");
  }

  function renderWeights(labelKey, weights) {
    var wrap = h("div", { class: "list-section" });
    wrap.appendChild(h("div", { class: "k" }, [t(labelKey)]));
    var keys = Object.keys(weights || {});
    if (!keys.length) {
      wrap.appendChild(h("div", { class: "v" }, [t("cio.no_weights")]));
      return wrap;
    }
    var ul = h("ul", { class: "plain-list" });
    keys.sort().forEach(function (k) {
      ul.appendChild(h("li", {}, [t("cio.sleeve." + k) + ": " + pct(weights[k])]));
    });
    wrap.appendChild(ul);
    return wrap;
  }

  function renderInvestmentCioCard(cio) {
    cio = cio || {};
    var c = card(t("cio.title"), renderBadge(get(cio, "_meta.state", null), isStaleGlobal()));
    c.className += " card--prominent";
    c.appendChild(h("p", { class: "note" }, [t("cio.boundary")]));
    if (get(cio, "_meta.state", null) === "NOT_MEASURED") {
      c.appendChild(h("p", {}, [get(cio, "_meta.reason", null) || t("common.not_measured")]));
      return c;
    }
    c.appendChild(kv("cio.stance", cio.stance ? t("cio.stance." + cio.stance) : null));
    c.appendChild(kv("cio.confidence", cio.confidence ? t("cio.confidence." + cio.confidence) : null));
    c.appendChild(kv("cio.date", cio.date));
    c.appendChild(kv("cio.evidence_cutoff", cio.evidence_cutoff));
    if (cio.evidence_cutoff_complete !== true) {
      // N9: the cutoff covers only readable inputs; unreadable or stale ones are named, never hidden
      c.appendChild(h("div", { class: "warning-chip" }, [t("cio.evidence_incomplete") + ": " +
        ((cio.evidence_incomplete_inputs || []).join(", ") || t("common.not_measured"))]));
    }
    c.appendChild(renderWeights("cio.recommended", cio.recommended_weights));
    var alts = cio.alternatives || {};
    if (alts.EVIDENCE_ONLY) c.appendChild(renderWeights("cio.evidence_only", alts.EVIDENCE_ONLY.weights));
    c.appendChild(renderWeights("cio.seed_split", cio.seed_split_weights));
    c.appendChild(renderListField("cio.abstentions", Object.keys(cio.abstentions || {}).sort().map(function (k) {
      return t("cio.sleeve." + k) + " — " + cio.abstentions[k];
    })));
    c.appendChild(renderListField("cio.binding", (cio.binding_constraints || []).map(function (b) {
      return b.constraint + ": " + b.state + (b.detail ? " — " + b.detail : "");
    })));
    // basis is named: with no recommendation the factors are read on the experiments' seed split (review #14)
    c.appendChild(renderListField(cio.major_risks_basis === "recommended" ? "cio.major_risks_rec" : "cio.major_risks_seed",
      (cio.major_risks || []).map(function (r) {
        return r.factor + " — " + (r.sleeves || []).map(function (s) { return t("cio.sleeve." + s); }).join(", ") +
          " · " + t("cio.weight_touching") + " " + pct(r.sleeve_weight_touching);
      })));
    var why = h("details");
    why.appendChild(h("summary", {}, [t("cio.why")]));
    why.appendChild(renderListField("cio.rationale", cio.rationale || []));
    why.appendChild(renderListField("cio.confidence_reasons", cio.confidence_reasons || []));
    why.appendChild(renderListField("cio.unknowns", cio.unknowns || []));
    c.appendChild(why);
    var led = cio.ledger || {};
    c.appendChild(kv("cio.ledger", led.entries === undefined ? null :
      led.entries + " · " + (led.chain_ok ? t("cio.chain_ok") : t("cio.chain_broken")) +
      " · " + t("cio.outcomes") + " " + (cio.outcomes && typeof cio.outcomes.scored === "number"
        ? cio.outcomes.scored + " / " + t("cio.pending") + " " + cio.outcomes.pending : t("common.not_measured"))));
    c.appendChild(kv("cio.real_capital", cio.real_capital_usd === 0 ? "$0" : null));
    // ADR-560 WP-S07: the CIO can SEE the research universe but never ALLOCATE it — counts only,
    // the full list lives in the separate Research Universe card.
    var rview = cio.research_universe || {};
    c.appendChild(kv("cio.research_universe", rview.state ? (rview.state + " · " +
      t("research.observe_only") + "=" + textOrNM(rview.observe_only) + " · " +
      t("research.paper_active") + "=" + textOrNM(rview.paper_active) + " · " +
      t("research.cio_eligible") + "=" + textOrNM(rview.cio_eligible)) : null));
    return c;
  }

  // RM-LIVE-01 (ADR-556): shadow execution + pilot readiness. Read-only; readiness is NOT authorization.
  // No execute / deploy / sign control exists here by design.
  function renderLiveReadinessCard(lr) {
    lr = lr || {};
    var st = get(lr, "_meta.state", null);
    var c = card(t("live.title"), renderBadge(st, isStaleGlobal()));
    c.className += " card--prominent";
    c.appendChild(h("div", { class: "warning-chip" }, [t("live.banner")]));
    c.appendChild(kv("live.automation", t("live.prohibited")));
    c.appendChild(kv("live.real_capital", lr.real_capital_usd === 0 ? "$0" : null));
    if (lr.integrity === "BROKEN") {
      c.appendChild(h("p", {}, [t("live.broken") + ": " + (get(lr, "_meta.reason", null) || "")]));
      return c;
    }
    if (st === "NOT_MEASURED") {
      c.appendChild(h("p", {}, [get(lr, "_meta.reason", null) || t("common.not_measured")]));
      return c;
    }
    c.appendChild(kv("live.mode", lr.execution_mode));
    c.appendChild(kv("live.owner_pending", lr.owner_decisions_pending));
    var sl = lr.sleeves || {};
    c.appendChild(renderListField("live.sleeves", Object.keys(sl).sort().map(function (k) {
      var x = sl[k] || {};
      return t("cio.sleeve." + k) + ": " + t("live.state." + x.state) + " (" + x.passed + "/" + x.gates + ")";
    })));
    c.appendChild(renderListField("live.top_blockers", (lr.top_blockers || []).map(function (b) {
      return b.gate + " × " + b.count;
    })));
    function brief(x) {
      if (!x) return null;
      return Object.keys(x).map(function (k) {
        var v = x[k];
        return k + "=" + (v !== null && typeof v === "object" ? JSON.stringify(v) : v);
      }).join(" · ");
    }
    c.appendChild(kv("live.last_sim", brief(lr.last_simulation)));
    c.appendChild(kv("live.last_shadow", brief(lr.last_shadow_execution)));
    c.appendChild(kv("live.last_rec", brief(lr.last_reconciliation)));
    c.appendChild(kv("live.incidents", lr.open_incidents ? String(lr.open_incidents.count) : null));
    var det = h("details");
    det.appendChild(h("summary", {}, [t("live.blockers_by_sleeve")]));
    Object.keys(sl).sort().forEach(function (k) {
      det.appendChild(renderListField("cio.sleeve." + k, (sl[k] || {}).blockers || []));
    });
    c.appendChild(det);
    return c;
  }

  function renderPackageCard(key, p) {
    p = p || {};
    var lang = window.MC_I18N.getLang();
    var c = card(t("capital.package.name." + key), renderBadge(p.state, isStaleGlobal()));
    var mech = lang === "ru" ? (p.mechanism_ru || p.mechanism) : (p.mechanism || p.mechanism_ru);
    var pos = lang === "ru" ? (p.position_ru || p.position) : p.position;
    c.appendChild(kv("capital.package.mechanism", mech));
    c.appendChild(kv("capital.package.version", p.version));
    c.appendChild(kv("capital.package.work", p.work));
    c.appendChild(kv("capital.package.data", p.data));
    c.appendChild(kv("capital.package.decision", p.decision));
    c.appendChild(kv("capital.package.position", pos));
    c.appendChild(kv("capital.package.evidence", p.evidence));
    c.appendChild(kv("capital.package.valid_periods", p.valid_periods));
    c.appendChild(kv("capital.package.live", p.live));
    var lr = lang === "ru" ? (p.live_reason_ru || p.live_reason) : (p.live_reason || p.live_reason_ru);
    if (lr) c.appendChild(h("p", { class: "note" }, [lr]));
    c.appendChild(kv("capital.package.composition", p.composition));
    c.appendChild(kv("capital.package.last_run_at", p.last_run_at));
    return c;
  }

  function renderTradingResearchCard(tr) {
    tr = tr || {};
    var c = card(t("capital.trading.title"), renderBadge(get(tr, "_meta.state", null), isStaleGlobal()));
    c.appendChild(kv("capital.trading.candidates", tr.candidates));
    c.appendChild(kv("capital.trading.qualified", tr.qualified));
    c.appendChild(kv("capital.trading.forward_paper", tr.forward_paper));
    c.appendChild(kv("capital.trading.observations", tr.observations));
    c.appendChild(kv("capital.trading.evidence_chain", tr.evidence_chain));
    c.appendChild(kv("capital.trading.mode", tr.mode));
    c.appendChild(kv("capital.trading.live_capital", tr.live_capital_usd));
    return c;
  }

  // Real capital is a CAPITAL MODE, not a health state: a neutral chip, never a health colour (ADR-537).
  function renderCapitalMode(rc) {
    var state = rc.state || "UNKNOWN";
    var usd = rc.usd === null || rc.usd === undefined ? t("common.not_measured") : "$" + rc.usd;
    return h("span", { class: "chip chip--mode" }, [usd + " · " + t("vocab.capital_mode." + state)]);
  }

  function renderRealCapitalCard(rc) {
    rc = rc || {};
    var c = card(t("capital.real_capital.title"), renderCapitalMode(rc));
    c.className += " card--prominent";
    var det = h("details");
    det.appendChild(h("summary", {}, [t("capital.real_capital.basis")]));
    det.appendChild(h("p", {}, [rc.basis === null || rc.basis === undefined ? t("common.not_measured") : rc.basis]));
    c.appendChild(det);
    return c;
  }

  // ADR-560 (RM-EXPAND-01): a value CELL (contract.cell()-shaped: {state, value, unit, reason, …})
  // rendered as one string — never string-concatenated with the object directly, which is exactly
  // how "[object Object]" happened on the live phone page (2026-10-04, live_readiness `brief`).
  function cellText(cell) {
    if (cell === null || cell === undefined || typeof cell !== "object") return t("common.not_measured");
    var state = cell.state;
    if (state === "MEASURED" || state === "ESTIMATED_WITH_METHOD" || state === "DOCUMENTED") {
      var v = cell.value;
      var vs = (v === null || v === undefined) ? t("common.not_measured") :
        (typeof v === "object" ? JSON.stringify(v) : String(v));
      return vs + (cell.unit ? " " + cell.unit : "") + " (" + state + ")";
    }
    return (state || t("common.unknown")) + (cell.reason ? ": " + cell.reason : "");
  }

  // ADR-560 WP-S08: research universe — discovered/paper-active/CIO-eligible/observe-only/rejected
  // candidates outside the three DeFi books. RESEARCH / OBSERVE_ONLY / PAPER_ACTIVE / CIO_ELIGIBLE
  // are the factory's own vocabulary and NEVER mean "approved" — the banner says so every time
  // this card renders, whatever its own state. No button, no addEventListener: read-only.
  function renderResearchUniverseCard(ru) {
    ru = ru || {};
    var st = get(ru, "_meta.state", null);
    var c = card(t("research.title"), renderBadge(st, isStaleGlobal()));
    c.appendChild(h("div", { class: "warning-chip" }, [ru.banner || t("research.banner")]));
    if (ru.integrity === "BROKEN") {
      c.appendChild(h("p", {}, [t("research.broken") + ": " + (get(ru, "_meta.reason", null) || "")]));
      return c;
    }
    if (st === "NOT_MEASURED") {
      c.appendChild(h("p", {}, [get(ru, "_meta.reason", null) || t("common.not_measured")]));
      return c;
    }
    c.appendChild(kv("research.real_capital", ru.real_capital_usd === 0 ? "$0" : null));
    var counts = ru.counts || {};
    c.appendChild(renderListField("research.counts", Object.keys(counts).sort().map(function (k) {
      return k + ": " + textOrNM(counts[k]);
    })));
    c.appendChild(renderListField("research.by_domain", Object.keys(ru.by_domain || {}).sort().map(function (k) {
      return k + ": " + ru.by_domain[k];
    })));
    c.appendChild(renderListField("research.by_mechanism", Object.keys(ru.by_mechanism || {}).sort().map(
      function (k) { return k + ": " + ru.by_mechanism[k]; })));
    c.appendChild(renderSherlockBlock(ru.sherlock));
    var topWrap = h("div", { class: "list-section" });
    topWrap.appendChild(h("div", { class: "k" }, [t("research.top_candidates")]));
    var topCands = ru.top_candidates || [];
    if (!topCands.length) {
      topWrap.appendChild(h("div", { class: "v" }, [t("common.none")]));
    } else {
      topCands.forEach(function (x) { topWrap.appendChild(renderResearchCandidateDetail(x)); });
    }
    c.appendChild(topWrap);
    c.appendChild(renderListField("research.rejected", (ru.rejected || []).map(function (x) {
      return (x.candidate_id || "?") + " [" + (x.state || "?") + "]: " + (x.reasons || []).join("; ");
    })));
    c.appendChild(renderListField("research.stale_feeds", (ru.stale_feeds || []).map(function (x) {
      return (x.source_root || "?") + " · " + textOrNM(x.age_h) + "h";
    })));
    c.appendChild(kv("research.counterparty_unknown", ru.counterparty_unknown_count));
    c.appendChild(renderListField("research.domain_decisions", Object.keys(ru.domain_decisions || {}).sort().map(
      function (k) { return k + ": " + ru.domain_decisions[k]; })));
    return c;
  }

  // ADR-564 (RM-EVIDENCE-01): Sherlock — Head of Research. Deterministic research governance
  // only — no capital authority, nothing executes (same read-only boundary as the card around
  // it). Rendered INSIDE the existing Research Universe card, never a separate top-level card.
  // Each guards against a non-string value with typeof — a nested object concatenated into a
  // translation-key lookup ("research.ceiling." + {...}) is exactly how "[object Object]"
  // happened on the live phone page before (2026-10-04, live_readiness `brief`); here the guard
  // falls back to "not measured" instead of ever building that key.
  function evidenceCeilingText(ceiling) {
    if (!ceiling || typeof ceiling !== "string") return t("common.not_measured");
    if (ceiling === "ISSUER_ASSERTED") return t("research.issuer_asserted_label");
    return t("research.ceiling." + ceiling);
  }

  function paperModeText(mode) {
    return (mode && typeof mode === "string") ? t("research.paper_mode." + mode) : t("common.not_measured");
  }

  function decisionText(decision) {
    return (decision && typeof decision === "string") ? t("research.decision." + decision) : t("common.not_measured");
  }

  function renderSherlockBlock(sh) {
    var wrap = h("div", { class: "list-section sherlock-block" });
    wrap.appendChild(h("div", { class: "k" },
      [sh && sh.display_name ? (sh.display_name + " — " + t("sherlock.title")) : t("sherlock.title")]));
    if (!sh) {
      wrap.appendChild(h("div", { class: "v" }, [t("sherlock.not_shown")]));
      return wrap;
    }
    var body = h("div", { class: "v" });
    body.appendChild(h("p", { class: "note" }, [t("sherlock.boundary")]));
    [["sherlock.reviewed_today", sh.reviewed_today], ["sherlock.evidence_ready", sh.evidence_ready],
     ["sherlock.paper_active", sh.paper_active], ["sherlock.cio_eligible", sh.cio_eligible],
     ["sherlock.counterparty_unknown", sh.counterparty_unknown], ["sherlock.conflicts", sh.conflicts],
     ["sherlock.stale_evidence", sh.stale_evidence]].forEach(function (pair) {
      body.appendChild(kv(pair[0], pair[1]));
    });
    body.appendChild(renderListField("sherlock.top_blockers", (sh.top_blockers || []).map(function (b) {
      return b.gate + " × " + textOrNM(b.count);
    })));
    body.appendChild(renderListField("sherlock.decisions_today", (sh.decisions_today || []).map(function (d) {
      var line = (d.instrument || d.candidate_id || "?") + " — " + decisionText(d.decision) +
        " · " + evidenceCeilingText(d.evidence_ceiling) + " · " + paperModeText(d.paper_mode);
      if (d.failed_gates && d.failed_gates.length) {
        line += " · " + t("research.candidate.failed_gates") + "=" + d.failed_gates.join(", ");
      }
      if (d.unknown_gates && d.unknown_gates.length) {
        line += " · " + t("research.candidate.unknown_gates") + "=" + d.unknown_gates.join(", ");
      }
      if (d.required_next_evidence && d.required_next_evidence.length) {
        line += " · " + t("research.candidate.required_next_evidence") + "=" + d.required_next_evidence.join(", ");
      }
      return line;
    })));
    wrap.appendChild(body);
    return wrap;
  }

  // Per-candidate evidence detail: who pays, counterparties (role → state + identity),
  // measured/documented/unknown, blocking gaps, latest decision, paper position NAV and returns.
  function renderCandidateEvidenceDetail(ev) {
    var wrap = h("div", { class: "candidate-evidence" });
    if (!ev) {
      wrap.appendChild(h("p", {}, [t("research.candidate.no_evidence")]));
      return wrap;
    }
    wrap.appendChild(kv("research.candidate.who_pays", ev.who_pays));
    var grades = ev.grades || {};
    wrap.appendChild(renderListField("research.candidate.grades", Object.keys(grades).sort().map(function (k) {
      return k + ": " + grades[k];
    })));
    wrap.appendChild(kv("research.candidate.evidence_ceiling", evidenceCeilingText(ev.evidence_ceiling)));
    wrap.appendChild(renderListField("research.candidate.issuer_asserted_roles", ev.issuer_asserted_roles));
    wrap.appendChild(renderListField("research.candidate.circularity_concerns", ev.circularity_concerns));
    var cps = ev.counterparties || {};
    wrap.appendChild(renderListField("research.candidate.counterparties", Object.keys(cps).sort().map(
      function (role) {
        var cp = cps[role] || {};
        return role + ": " + (cp.state || t("common.unknown")) + (cp.identity ? " — " + cp.identity : "");
      })));
    wrap.appendChild(renderListField("research.candidate.measured", ev.measured));
    wrap.appendChild(renderListField("research.candidate.documented", ev.documented));
    wrap.appendChild(renderListField("research.candidate.unknown", ev.unknown));
    wrap.appendChild(renderListField("research.candidate.blocking_gaps", ev.blocking_gaps));
    wrap.appendChild(kv("research.candidate.paper_mode", paperModeText(ev.paper_mode)));
    if (ev.paper_mode === "REFERENCE_TRACK") {
      wrap.appendChild(h("div", { class: "warning-chip" }, [t("research.reference_track_note")]));
    }
    wrap.appendChild(kv("research.candidate.latest_decision", ev.latest_decision ? decisionText(ev.latest_decision) : null));
    var pos = ev.paper_position;
    if (pos) {
      wrap.appendChild(kv("research.candidate.nav",
        (pos.nav_usd === null || pos.nav_usd === undefined) ? null : "$" + pos.nav_usd));
      wrap.appendChild(kv("research.candidate.realised_return", pos.realised_return));
      wrap.appendChild(kv("research.candidate.unrealised_return", pos.unrealised_return));
      wrap.appendChild(kv("research.candidate.mark_state", pos.mark_state));
    } else {
      wrap.appendChild(kv("research.candidate.paper_position", null));
    }
    return wrap;
  }

  function renderResearchCandidateDetail(x) {
    var det = h("details", { class: "candidate-detail" });
    var summary = (x.instrument || x.venue_or_protocol || x.candidate_id || "?") + " · " + (x.mechanism_id || "?") +
      " · " + t("research.forward_periods") + "=" + textOrNM(x.forward_periods) +
      " · net=" + cellText(x.net_expected_return) + " · " + (x.admission_state || "?");
    det.appendChild(h("summary", {}, [summary]));
    det.appendChild(renderCandidateEvidenceDetail(x.evidence));
    return det;
  }
  // ── end legacy Capital-area cards ─────────────────────────────────────────────────────────

  // ── STUDIO ─────────────────────────────────────────────────────────────────────────────
  function renderClaudeWork(cell) {
    cell = cell || {};
    var c = card(t("studio.claude.title"), stateBadge(cell));
    if (isUnknownState(cell.state)) {
      c.appendChild(h("p", { class: "cell-text cell-text--unknown" }, [unknownText(cell)]));
      var ev0 = evidenceDrawer(cell);
      if (ev0) c.appendChild(ev0);
      return c;
    }
    c.appendChild(kvPlain(t("studio.claude.epic"), cell.epic || t("studio.claude.epic_none")));
    c.appendChild(h("p", { class: "note" }, [tf("studio.claude.sessions", { a: cell.sessions_announced, u: cell.sessions_undeclared })]));
    c.appendChild(kvPlain(t("studio.claude.card"), bi(cell.card_title_ru, cell.card_title_en)));
    c.appendChild(kvPlain(t("studio.claude.stage"), cell.stage_key ? t("stage." + cell.stage_key) : null));
    c.appendChild(kvPlain(t("studio.claude.blocker"), bi(cell.blocker_ru, cell.blocker_en) || t("studio.claude.blocker_none")));
    var nextText = bi(cell.next_step_ru, cell.next_step_en);
    if (!nextText && cell.next_stage_key) nextText = tf("studio.claude.next_stage", { stage: t("stage." + cell.next_stage_key) });
    c.appendChild(kvPlain(t("studio.claude.next"), nextText));
    var ev = evidenceDrawer(cell);
    if (ev) c.appendChild(ev);
    return c;
  }

  function renderRoadmap(cell) {
    return cellCard("studio.roadmap.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      if (cell.confirmed_date) c.appendChild(h("p", { class: "note" }, [tf("studio.roadmap.confirmed", { date: cell.confirmed_date })]));
    });
  }

  function renderTasks(cell) {
    return cellCard("studio.tasks.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      var row = h("div", { class: "chip-row" });
      row.appendChild(h("span", { class: "chip" }, [tf("studio.tasks.queued", { n: cell.queued })]));
      row.appendChild(h("span", { class: "chip" }, [tf("studio.tasks.in_progress", { n: cell.in_progress, stale: cell.in_progress_stale })]));
      row.appendChild(h("span", { class: "chip" }, [tf("studio.tasks.blocked", { n: cell.blocked })]));
      c.appendChild(row);
    });
  }

  var FLEET_TYPES = [
    ["runtime_services", function (x) { return tf("studio.fleet.runtime_services", { loaded: x.loaded, declared: x.declared }); }],
    ["managed_agents", function (x) { return tf("studio.fleet.managed_agents", { loaded: x.loaded, declared: x.declared }); }],
    ["configured_roles", function (x) { return tf("studio.fleet.configured_roles", { n: x.n }); }],
    ["active_workers", function (x) { return tf("studio.fleet.active_workers", { a: x.a, u: x.u }); }],
    ["retired_loaded", function (x) { return tf("studio.fleet.retired_loaded", { n: x.n }); }],
    ["unknown_orphans", function (x) { return tf("studio.fleet.unknown_orphans", { n: x.n }); }],
  ];

  function renderFleet(cell) {
    cell = cell || {};
    var c = card(t("studio.fleet.title"), stateBadge(cell));
    if (isUnknownState(cell.state)) {
      c.appendChild(h("p", { class: "cell-text cell-text--unknown" }, [tf("studio.fleet.headline_unknown", { declared: cell.declared })]));
      var ev0 = evidenceDrawer(cell);
      if (ev0) c.appendChild(ev0);
      return c;
    }
    c.appendChild(h("p", { class: "cell-text" }, [tf("studio.fleet.headline", { ok: cell.ok, declared: cell.declared })]));
    var types = cell.types || {};
    var ul = h("ul", { class: "plain-list" });
    FLEET_TYPES.forEach(function (pair) {
      var x = types[pair[0]];
      if (!x) return;
      ul.appendChild(h("li", { class: x.ok === false ? "fleet-row fleet-row--warn" : "fleet-row" }, [pair[1](x)]));
    });
    c.appendChild(ul);
    var failing = cell.failing || [];
    if (failing.length) {
      c.appendChild(h("div", { class: "warning-chip" }, [failing.map(function (f) { return bi(f.name_ru, f.name_en); }).join(", ")]));
    }
    var ev = evidenceDrawer(cell);
    if (ev) c.appendChild(ev);
    return c;
  }

  function renderIncidents(cell) {
    return cellCard("studio.incidents.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "note" }, [tf("studio.incidents.open", { n: cell.open })]));
      (cell.items || []).forEach(function (it) {
        var raw = bi(it.title_ru, it.title_en) || t("studio.incidents.untitled");
        var title = it.plain_ru || raw;
        var when = it.since_plain_ru || bi(it.since_ru, it.since_en) || "";
        var p = h("p", { class: "note tone--" + toneClass(it.plain_tone) }, [title + (when ? " · " + when : "")]);
        c.appendChild(p);
        var td = techDetails([raw, bi(it.since_ru, it.since_en)]);
        if (td) c.appendChild(td);
      });
    });
  }

  function renderProblems(cell) {
    return cellCard("studio.problems.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      var row = h("div", { class: "chip-row" });
      row.appendChild(h("span", { class: "chip" }, [tf("studio.problems.open", { n: cell.open })]));
      row.appendChild(h("span", { class: "chip" }, [tf("studio.problems.mitigated", { n: cell.mitigated })]));
      row.appendChild(h("span", { class: "chip" }, [tf("studio.problems.closed", { n: cell.closed })]));
      c.appendChild(row);
      (cell.items || []).forEach(function (it) {
        var raw = (it.agent_ru || t("state.NOT_MEASURED")) + " — " + bi(it.cause_ru, it.cause_en);
        var p = h("p", { class: "note tone--" + toneClass(it.plain_tone) });
        p.appendChild(document.createTextNode(it.plain_ru || raw));
        p.appendChild(h("br"));
        p.appendChild(document.createTextNode(tf("studio.problems.occurrences", { n: it.occurrences }) + " · " + (it.rca ? t("studio.problems.rca_yes") : t("studio.problems.rca_no"))));
        c.appendChild(p);
        var td = techDetails(it.plain_ru ? [raw, it.cause_code] : []);
        if (td) c.appendChild(td);
      });
    });
  }

  function renderReleases(cell) {
    return cellCard("studio.releases.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "cell-text" }, [cell.in_prod_ok ? t("studio.releases.in_prod_ok") : t("studio.releases.in_prod_drift")]));
      c.appendChild(h("p", { class: "note" }, [tf("studio.releases.today", { n: cell.today })]));
    });
  }

  function renderMemory(cell) {
    return cellCard("studio.memory.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "cell-text" }, [cell.lag > 0 ? tf("studio.memory.lag", { n: cell.lag }) : t("studio.memory.ok")]));
    });
  }

  function renderMachine(cell) {
    return cellCard("studio.machine.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "cell-text" }, [tf("studio.machine.disk", { gb: cell.disk_free_gb })]));
    });
  }

  // Backups: THREE separate rows, never collapsed to one (CLAUDE.md inv. #17 / design §2.3).
  function backupRow(badge, text, cell) {
    var row = h("div", { class: "backup-row" }, [badge, h("span", {}, [text])]);
    var ev = evidenceDrawer(cell);
    if (ev) row.appendChild(ev);
    return row;
  }

  function renderBackupLocal(cell) {
    cell = cell || {};
    if (isUnknownState(cell.state)) return backupRow(stateBadge(cell), unknownText(cell), cell);
    return backupRow(stateBadge(cell), tf("studio.backups.local", { age: bi(cell.age_ru, cell.age_en) }), cell);
  }

  function renderBackupOffHost(cell) {
    cell = cell || {};
    if (isUnknownState(cell.state)) return backupRow(stateBadge(cell), unknownText(cell), cell);
    // is_real_remote=false is amber, never green, even though the fact itself was measured.
    var cls = cell.is_real_remote ? "ok" : "warn";
    var badge = h("span", { class: "badge badge--" + cls }, [t("state." + cell.state)]);
    var text = cell.is_real_remote ? t("studio.backups.off_host_ok") : t("studio.backups.same_host");
    return backupRow(badge, text, cell);
  }

  function renderBackupRecovery(cell) {
    cell = cell || {};
    if (isUnknownState(cell.state) && cell.drill_result === undefined) return backupRow(stateBadge(cell), unknownText(cell), cell);
    var text;
    if (cell.drill_result === "OK") text = tf("studio.backups.recovery_ok", { date: cell.date });
    else if (cell.drill_result === "STALE") text = t("studio.backups.recovery_stale");
    else if (cell.drill_result === "FAILED") text = t("studio.backups.recovery_failed");
    else if (cell.drill_result === "NEVER_RUN") text = t("studio.backups.recovery_never");
    else text = unknownText(cell);
    return backupRow(stateBadge(cell), text, cell);
  }

  function renderBackups(b) {
    b = b || {};
    var c = card(t("studio.backups.title"));
    c.appendChild(renderBackupLocal(b.local));
    c.appendChild(renderBackupOffHost(b.off_host));
    c.appendChild(renderBackupRecovery(b.recovery));
    return c;
  }

  // Reuses the Home "needs" tile templates — "counts as on Home" per design §2.3.
  function renderDecisionsSummary(ds) {
    ds = ds || {};
    var c = card(t("home.tile.needs"));
    c.appendChild(h("p", { class: "cell-text" }, [tf("home.tile.needs.value", { own: ds.own })]));
    c.appendChild(h("p", { class: "note" }, [tf("home.tile.needs.agent", { undeclared: ds.undeclared })]));
    c.appendChild(h("p", { class: "note" }, [tf("home.tile.needs.answered", { answered: ds.answered })]));
    c.appendChild(h("a", { class: "btn btn-link", href: "#decisions" }, [t("nav.decisions") + " →"]));
    return c;
  }

  var SCOPE_ORDER = ["INVESTMENT_ENGINE_READINESS", "STUDIO_OS_HEALTH", "PRODUCT_DATA_HEALTH", "PUBLICATION_HEALTH", "OWNER_CONTROL_HEALTH", "PUBLIC_SURFACE"];

  function scopeBadgeClass(status) {
    if (status === "OK" || status === "READY") return "ok";
    if (status === "WARN" || status === "DEGRADED" || status === "NOT_READY") return "warn";
    if (status === "CRITICAL" || status === "CORRUPT") return "alert";
    return "unknown";
  }

  // Exactly the six scopes, always side by side, never collapsed into one worst-of badge
  // (test_scoped_readiness_never_collapsed is WP1's; this is the UI-side half of that guarantee).
  function renderScopes(scopes) {
    var c = card(t("studio.scopes.title"));
    var byKey = {};
    (scopes || []).forEach(function (s) { byKey[s.key] = s; });
    var ul = h("ul", { class: "plain-list" });
    SCOPE_ORDER.forEach(function (key) {
      var s = byKey[key] || {};
      var status = s.status || "UNKNOWN";
      var li = h("li", { class: "scope-row" });
      li.appendChild(h("div", { class: "kv-row" }, [
        h("span", { class: "k" }, [t("scope." + key)]),
        h("span", { class: "badge badge--" + scopeBadgeClass(status) }, [t("scope_status." + status)]),
      ]));
      var techReason = bi(s.reason_ru, s.reason_en);
      if (s.plain_ru) {
        li.appendChild(h("p", { class: "note tone--" + toneClass(s.plain_tone) + (status === "UNKNOWN" ? " cell-text--unknown" : "") }, [s.plain_ru]));
      } else if (status === "UNKNOWN") {
        li.appendChild(h("p", { class: "note cell-text--unknown" }, [tf("scope.unknown", { reason: techReason || t("state.NOT_MEASURED") })]));
      } else if (techReason) {
        li.appendChild(h("p", { class: "note" }, [techReason]));
      }
      if (s.blocks_ru || s.blocks_en) li.appendChild(h("p", { class: "note" }, [t("scope.blocks") + ": " + bi(s.blocks_ru, s.blocks_en)]));
      if (s.does_not_block_ru || s.does_not_block_en) li.appendChild(h("p", { class: "note" }, [t("scope.does_not_block") + ": " + bi(s.does_not_block_ru, s.does_not_block_en)]));
      var td = techDetails(s.plain_ru ? [techReason, s.source] : []);
      if (td) li.appendChild(td);
      ul.appendChild(li);
    });
    c.appendChild(ul);
    return c;
  }

  function renderStudio(root) {
    var studio = get(truth(), "studio", {}) || {};
    var grid = h("div", { class: "grid" });
    grid.appendChild(renderClaudeWork(studio.claude_work));
    grid.appendChild(renderRoadmap(studio.roadmap));
    grid.appendChild(renderTasks(studio.tasks));
    grid.appendChild(renderFleet(studio.fleet));
    grid.appendChild(renderDecisionsSummary(studio.decisions_summary));
    grid.appendChild(renderScopes(studio.scopes));
    grid.appendChild(renderIncidents(studio.incidents));
    grid.appendChild(renderProblems(studio.problems));
    grid.appendChild(cellCard("studio.selfheal.title", studio.self_heal));
    grid.appendChild(renderReleases(studio.releases));
    grid.appendChild(renderMemory(studio.memory));
    grid.appendChild(renderBackups(studio.backups));
    grid.appendChild(renderMachine(studio.machine));
    root.appendChild(grid);
  }

  // ── PRODUCT ────────────────────────────────────────────────────────────────────────────
  function renderPublicRelease(cell) {
    return cellCard("product.release.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "cell-text" }, [tf("product.release.value", { measured: bi(cell.measured_ru, cell.measured_en), published: bi(cell.published_ru, cell.published_en) })]));
    });
  }

  function renderProfiles(profiles) {
    profiles = profiles || {};
    var c = card(t("product.profiles.title"));
    ["conservative", "balanced", "aggressive"].forEach(function (k) {
      var cell = profiles[k] || {};
      var row = h("div", { class: "profile-row" }, [
        h("span", { class: "k" }, [t("capital.book." + k)]),
        stateBadge(cell),
      ]);
      var text;
      if (cell.state === "NOT_ENOUGH_HISTORY") text = tf("home.tile.yield.accumulating", { book: t("capital.book." + k), n: cell.accumulating_days });
      else if (isUnknownState(cell.state)) text = unknownText(cell);
      else text = tf("home.tile.yield.value", { rate: bi(cell.rate_ru, cell.rate_en), dd: bi(cell.dd_ru, cell.dd_en) });
      row.appendChild(h("div", { class: "note" }, [text]));
      c.appendChild(row);
    });
    return c;
  }

  function renderPublicMetrics(list) {
    var c = card(t("product.metrics.title"));
    if (!Array.isArray(list) || !list.length) {
      c.appendChild(h("p", { class: "note" }, [t("product.metrics.missing")]));
      return c;
    }
    var ul = h("ul", { class: "plain-list" });
    list.forEach(function (m) {
      m = m || {};
      var li = h("li", {});
      if (isUnknownState(m.state)) {
        li.appendChild(document.createTextNode(bi(m.label_ru, m.label_en) + ": " + t("product.metrics.missing")));
      } else {
        var kind = m.metric_type ? t("metric_type." + m.metric_type) : t("state.NOT_MEASURED");
        li.appendChild(document.createTextNode(tf("product.metrics.row", { label: bi(m.label_ru, m.label_en), value: bi(m.value_ru, m.value_en), kind: kind, date: bi(m.date_ru, m.date_en) })));
      }
      ul.appendChild(li);
    });
    c.appendChild(ul);
    return c;
  }

  function renderProductIncidents(cell) {
    return cellCard("product.incidents.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "cell-text" }, [tf("studio.incidents.open", { n: cell.open })]));
    });
  }

  function renderBacklog(cell) {
    return cellCard("product.backlog.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "note" }, [t("product.backlog.note")]));
      var titles = bi(cell.top_titles_ru, cell.top_titles_en) || [];
      if (titles.length) {
        var ul = h("ul", { class: "plain-list" });
        titles.forEach(function (ti) { ul.appendChild(h("li", {}, [ti])); });
        c.appendChild(ul);
      }
    });
  }

  function renderNextRelease(cell) {
    return cellCard("product.next.title", cell, function (c, cell) {
      if (isUnknownState(cell.state)) return;
      c.appendChild(h("p", { class: "cell-text" }, [tf("product.next.value", { date: bi(cell.date_ru, cell.date_en), gate: bi(cell.gate_ru, cell.gate_en) })]));
    });
  }

  function renderProduct(root) {
    var p = get(truth(), "product", {}) || {};
    var grid = h("div", { class: "grid" });
    grid.appendChild(renderPublicRelease(p.public_release));
    grid.appendChild(cellCard("product.health.title", p.website_health));
    grid.appendChild(renderProfiles(p.profiles));
    grid.appendChild(renderPublicMetrics(p.public_metrics));
    grid.appendChild(renderProductIncidents(p.truth_incidents));
    grid.appendChild(renderBacklog(p.backlog));
    grid.appendChild(renderNextRelease(p.next_release));
    root.appendChild(grid);
  }

  // ── DECISIONS ──────────────────────────────────────────────────────────────────────────
  var DECISION_GROUPS = [
    ["owner", "decisions.group.owner"],
    ["undeclared", "decisions.group.undeclared"],
    ["answered", "decisions.group.answered"],
    ["accepted", "decisions.group.accepted"],
    ["prod_only", "decisions.group.prod_only"],
  ];

  // Карточки решений пишутся в markdown: на первом уровне владельцу нужен текст, а не разметка.
  function plain(s) {
    if (typeof s !== "string") return s;
    return s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\*\*|__|`/g, "").replace(/^\s*>\s?/gm, "").trim();
  }

  function renderDecisionItem(d) {
    d = d || {};
    var dc = h("div", { class: "decision-card" });
    dc.appendChild(h("h3", { class: "decision-title" }, [bi(d.title_ru, d.title_en) || d.id || t("state.NOT_MEASURED")]));
    var meta = h("div", { class: "chip-row" });
    var subjKey = d.subject_key || "UNKNOWN";
    meta.appendChild(h("span", { class: "chip" }, [t("subject." + subjKey)]));
    if (d.age_days !== undefined && d.age_days !== null) meta.appendChild(h("span", { class: "chip" }, [tf("decisions.age", { days: d.age_days })]));
    dc.appendChild(meta);
    dc.appendChild(kvPlain(t("decisions.reason"), plain(bi(d.reason_ru, d.reason_en))));
    dc.appendChild(kvPlain(t("decisions.action"), plain(bi(d.action_ru, d.action_en))));
    dc.appendChild(kvPlain(t("decisions.done_when"), plain(bi(d.done_when_ru, d.done_when_en))));
    var href = safeLink(d.telegram_link);
    if (href) {
      dc.appendChild(h("a", { class: "btn btn-primary", href: safeLink(d.telegram_link), target: "_blank", rel: "noopener noreferrer" }, [t("common.open_telegram")]));
    } else {
      dc.appendChild(h("button", { class: "btn btn-disabled", disabled: true, type: "button" }, [t("common.open_telegram")]));
    }
    return dc;
  }

  function renderAnsweredItem(d) {
    d = d || {};
    var dc = h("div", { class: "decision-card" });
    dc.appendChild(h("h3", { class: "decision-title" }, [bi(d.title_ru, d.title_en) || d.id || t("state.NOT_MEASURED")]));
    var p = h("p", { class: "note" });
    p.appendChild(document.createTextNode(bi(d.owner_answer_ru, d.owner_answer_en) || t("state.NOT_MEASURED")));
    if (d.answered_at) {
      p.appendChild(h("br"));
      p.appendChild(document.createTextNode(d.answered_at));
    }
    dc.appendChild(p);
    return dc;
  }

  function renderAcceptedItem(d) {
    d = d || {};
    var dc = h("div", { class: "decision-card" });
    dc.appendChild(h("h3", { class: "decision-title" }, [bi(d.title_ru, d.title_en) || d.id || t("state.NOT_MEASURED")]));
    if (d.age_days !== undefined && d.age_days !== null) dc.appendChild(h("p", { class: "note" }, [tf("decisions.age", { days: d.age_days })]));
    return dc;
  }

  function renderDecisions(root) {
    var dec = get(truth(), "decisions", null) || {};
    root.appendChild(h("p", { class: "area-label" }, [t("decisions.autonomy")]));
    root.appendChild(h("p", { class: "area-label" }, [t("decisions.how")]));
    var groups = dec.groups;
    if (!groups) {
      root.appendChild(h("p", { class: "empty-note" }, [bi(dec.unknown_ru, dec.unknown_en) || t("decisions.unknown")]));
      return;
    }
    DECISION_GROUPS.forEach(function (pair) {
      var key = pair[0];
      var titleKey = pair[1];
      var items = groups[key] || [];
      var sec = h("section", { class: "card" });
      sec.appendChild(h("h2", { class: "card-title" }, [t(titleKey) + " · " + items.length]));
      if (items.length) {
        var list = h("div", { class: "decision-list" });
        items.forEach(function (d) {
          if (key === "answered") list.appendChild(renderAnsweredItem(d));
          else if (key === "accepted") list.appendChild(renderAcceptedItem(d));
          else list.appendChild(renderDecisionItem(d));
        });
        sec.appendChild(list);
      }
      root.appendChild(sec);
    });
  }

  // ── top-level render ───────────────────────────────────────────────────────────────────
  function renderArea(area) {
    var container = document.getElementById("area-" + area);
    if (!container) return;
    clear(container);
    if (fetchFailed || !currentModel) {
      container.appendChild(h("p", { class: "empty-note" }, [t("header.no_connection")]));
      return;
    }
    if (!get(currentModel, "truth", null)) {
      container.appendChild(h("p", { class: "empty-note" }, [t("state.NOT_MEASURED")]));
      return;
    }
    if (area === "home") renderHome(container);
    else if (area === "capital") renderCapital(container);
    else if (area === "studio") renderStudio(container);
    else if (area === "product") renderProduct(container);
    else if (area === "decisions") renderDecisions(container);
  }

  function renderAll() {
    renderHeaderStaticText();
    renderMoneyChip();
    renderIntake();
    renderStatusStrip();
    renderNav();
    renderLegend();
    var area = currentArea();
    showArea(area);
    renderArea(area);
  }

  function initLangToggle() {
    var btn = document.getElementById("lang-toggle");
    function paint() {
      var lang = window.MC_I18N.getLang();
      btn.textContent = lang === "ru" ? "EN" : "RU";
      btn.setAttribute("aria-label", lang === "ru" ? "Switch to English" : "Переключить на русский");
    }
    btn.addEventListener("click", function () {
      var lang = window.MC_I18N.getLang();
      window.MC_I18N.setLang(lang === "ru" ? "en" : "ru");
      document.documentElement.setAttribute("lang", window.MC_I18N.getLang());
      paint();
      renderAll();
    });
    paint();
  }

  window.addEventListener("hashchange", renderAll);
  initLangToggle();
  loadModel();
  setInterval(loadModel, REFRESH_MS);
})();
