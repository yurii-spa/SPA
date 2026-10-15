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
  // DIRECTOR-OS-UX-02 (RFC-690): five owner sections. The v2 areas live on as «Технические
  // подробности» inside them, and their old hashes still resolve (LEGACY_AREA) — nothing removed.
  var AREAS = ["overview", "decisions", "work", "money", "protection"];
  var LEGACY_AREA = { home: "overview", capital: "money", studio: "work", product: "work", system: "protection" };
  // Simple line icons (stroke only), always shown WITH a text label.
  var NAV_ICON_PATH = {
    overview: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H10v6H4a1 1 0 0 1-1-1z",
    decisions: "M8 12l3 3 5-6M12 3a9 9 0 1 0 0.01 0",
    work: "M9 6h11M9 12h11M9 18h11M4 6h1M4 12h1M4 18h1",
    money: "M3 7h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7l12-4v4M16 13h2",
    protection: "M12 3l8 3v6c0 5-3.5 8-8 9c-4.5-1-8-4-8-9V6z",
  };
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

  // ── owner time (ADR-660): a stamp is SHOWN in Europe/Madrid, CET/CEST automatic; data stays UTC.
  // Unparseable ⇒ the raw value, never a guessed time.
  function ownerTime(iso) {
    if (iso === null || iso === undefined || iso === "") return iso;
    var d = new Date(String(iso));
    if (isNaN(d.getTime())) return iso;
    try {
      var parts = {};
      new Intl.DateTimeFormat("en-GB", {
        timeZone: "Europe/Madrid", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short",
      }).formatToParts(d).forEach(function (x) { parts[x.type] = x.value; });
      var city = (window.MC_I18N && window.MC_I18N.getLang() === "en") ? "Madrid" : "Мадрид";
      return parts.year + "-" + parts.month + "-" + parts.day + " " + parts.hour + ":" + parts.minute +
        " " + city + (parts.timeZoneName ? " (" + parts.timeZoneName + ")" : "");
    } catch (e) {
      return iso;
    }
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
    body.appendChild(evRow(t("common.as_of"), ownerTime(cell.as_of)));
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
  // ONE clock for every staleness judgement on the page. In production it is the clock of the reader.
  // A fixture/preview page may pin it with <meta name="dos-fixed-now" content="ISO"> so the header
  // and the sections judge freshness against the SAME instant (DIRECTOR-OS-UX-02 E). The production
  // index.html carries no such meta (guarded by test_mission_ui_static), so the pin cannot reach prod.
  function readerNowMs() {
    var meta = document.querySelector("meta[name=dos-fixed-now]");
    if (meta) {
      var pinned = new Date(meta.getAttribute("content") || "").getTime();
      if (!isNaN(pinned)) return pinned;
    }
    return Date.now();
  }

  function dataAgeMin(model) {
    var gen = get(model, "generated_at", null);
    if (!gen) return null;
    var ts = new Date(gen).getTime();
    if (isNaN(ts)) return null;
    return (readerNowMs() - ts) / 60000;
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
        renderAll({ keepState: true });
      })
      .catch(function () {
        fetchFailed = true;
        currentModel = null;
        staleFlag = true;
        renderAll({ keepState: true });
      });
  }

  function truth() {
    return get(currentModel, "truth", null) || {};
  }

  // ── routing ─────────────────────────────────────────────────────────────────────────────
  function currentArea() {
    var hsh = (location.hash || "").replace("#", "").split("/")[0];
    if (AREAS.indexOf(hsh) >= 0) return hsh;
    if (hsh.indexOf("dev-") === 0) return "dev";   // DIRECTOR-OS-UX-04: a mockup section «в разработке»
    return LEGACY_AREA[hsh] || "overview";
  }

  function devKey() {
    var hsh = (location.hash || "").replace("#", "").split("/")[0];
    return hsh.indexOf("dev-") === 0 ? hsh.slice(4) : null;
  }

  function showArea(area) {
    AREAS.concat(["dev"]).forEach(function (a) {
      var sec = document.getElementById("area-" + a);
      if (sec) sec.hidden = a !== area;
    });
  }

  function navIcon(a) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "nav-icon");
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", NAV_ICON_PATH[a] || NAV_ICON_PATH.overview);
    svg.appendChild(path);
    return svg;
  }

  // DIRECTOR-OS-UX-04 (owner mockup): on a phone the bar shows ONLY the five sections; on a desktop the
  // same element is the mockup's sidebar — brand, grouped sections with count badges, and the mockup's
  // other sections marked «в разработке» (from owner_view.in_development — one registry, no invention).
  function renderNav() {
    var nav = document.getElementById("bottom-nav");
    clear(nav);
    var active = currentArea();
    var counts = get(currentModel, "owner_view.nav_counts", {}) || {};
    nav.appendChild(h("div", { class: "nav-brand", "aria-hidden": "true" }, [
      h("span", { class: "nav-brandmark" }, ["E"]),
      h("span", { class: "nav-brandtext" }, [h("b", {}, [t("v4.brand")]), h("small", {}, [t("v4.brand_sub")])]),
    ]));
    nav.appendChild(h("p", { class: "nav-group-title" }, [t("v4.group.command")]));
    AREAS.forEach(function (a) {
      var n = counts[a];
      var link = h("a", { class: "nav-item" + (a === active ? " active" : ""), href: "#" + a,
                          "aria-current": a === active ? "page" : null }, [
        navIcon(a),
        h("span", { class: "nav-label" }, [t("nav." + a)]),
        (typeof n === "number" && n > 0) ? h("span", { class: "nav-badge", "aria-label": String(n) }, [String(n)]) : null,
      ]);
      nav.appendChild(link);
    });
    var dev = (get(currentModel, "owner_view.in_development", []) || []).filter(function (d) { return d.nav; });
    var groups = {};
    dev.forEach(function (d) { (groups[d.nav_group] = groups[d.nav_group] || []).push(d); });
    Object.keys(groups).forEach(function (g) {
      nav.appendChild(h("p", { class: "nav-group-title nav-dev-only" }, [g]));
      groups[g].forEach(function (d) {
        var on = active === "dev" && devKey() === d.key;
        nav.appendChild(h("a", { class: "nav-item nav-item--dev nav-dev-only" + (on ? " active" : ""), href: "#dev-" + d.key,
                                 "aria-current": on ? "page" : null,
                                 "aria-label": d.nav_title + " — " + t("v4.in_dev_badge") }, [
          h("span", { class: "nav-dot", "aria-hidden": "true" }, []),
          h("span", { class: "nav-label" }, [d.nav_title]),
          h("span", { class: "nav-soon" }, [t("v4.in_dev_badge")]),
        ]));
      });
    });
    nav.appendChild(h("div", { class: "nav-safebox nav-dev-only" }, [
      h("p", { class: "nav-safehead" }, [h("span", { class: "dot dot--ok", "aria-hidden": "true" }, []), t("v4.safe_title")]),
      h("p", {}, [t("v4.safe_text")]),
    ]));
  }

  function renderHeaderStaticText() {
    var title = document.querySelector(".app-title");
    if (title) title.textContent = t("header.title");
  }

  function renderIntake(nav) {
    nav = nav || document.getElementById("intake-actions");
    if (!nav) return;
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

  // Header money chip — permanent on every section. Source: owner_view (ADR-762 §3) which reads
  // ONLY capital.real_capital; the legacy truth.home.money_chip is the fallback. No literal sum here:
  // an absent sum is «не измерено», never "$0" (the v2 fallback that printed "$0" is gone).
  function renderMoneyChip() {
    var el = document.getElementById("money-chip");
    if (!el) return;
    clear(el);
    if (currentArea() === "money") return;   // owner 15.10: «Настоящие деньги: $0» once per screen
    var real = get(currentModel, "owner_view.sections.money.real", null);
    var text;
    if (real && real.confidence === "MEASURED" && typeof real.text === "string") {
      var st = get(real, "technical.state", null);
      text = t("ux.real_money") + ": " + real.text.split(" — ")[0] +
        (st === "LIVE_NOT_APPROVED" ? " · " + t("ux.not_approved") : "");
    } else if (real) {
      text = t("ux.real_money") + ": " + (real.confidence_ru || t("state.NOT_MEASURED")).toLowerCase();
    } else {
      var mc = get(truth(), "home.money_chip", null);
      if (!mc || isUnknownState(mc.state) || typeof mc.usd !== "number") {
        text = (mc && bi(mc.unknown_ru, mc.unknown_en)) || t("header.money_chip.unknown");
      } else {
        text = tf("header.money_chip", { usd: "$" + mc.usd });
      }
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

  function renderIntakeBar(root) {
    // ADR-760: one contained entry point to the composer (a modal outside the areas, so the 60-s
    // refresh that rebuilds this area never wipes what the owner is typing or dictating).
    var bar = h("section", { class: "card intake-bar", "aria-labelledby": "intake-bar-title" });
    bar.appendChild(h("h2", { class: "card-title", id: "intake-bar-title" }, [t("intake.bar.title")]));
    bar.appendChild(h("p", { class: "intake-bar-lead" }, [t("intake.bar.lead")]));
    var voice = h("button", { class: "mk-btn mk-btn--primary", type: "button" }, [t("intake.bar.voice")]);
    voice.addEventListener("click", function () { openComposer({ startRecording: true }); });
    var text = h("button", { class: "mk-btn", type: "button" }, [t("intake.bar.text")]);
    text.addEventListener("click", function () { openComposer({}); });
    bar.appendChild(h("div", { class: "intake-bar-actions" }, [voice, text]));
    root.appendChild(bar);
  }

  function renderHome(root) {
    var home = get(truth(), "home", {}) || {};
    renderIntakeBar(root);
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
      if (book.period_return_ru) {
        // Wave 2 method (same Company Truth cell): the period return first; the annualised figure is
        // only an estimated equivalent — never a bar-count explanation (ARB 09.10).
        c.appendChild(h("p", { class: "cell-text" }, [tf("capital.book.period", { ret: bi(book.period_return_ru, book.period_return_en), start: book.period_start || "—", end: book.period_end || "—", dd: bi(book.dd_ru, book.dd_en) })]));
        if (book.rate_ru) c.appendChild(h("p", { class: "note" }, [tf("capital.book.equivalent", { rate: bi(book.rate_ru, book.rate_en) })]));
      } else {
        c.appendChild(h("p", { class: "cell-text" }, [tf("home.tile.yield.value", { rate: bi(book.rate_ru, book.rate_en), dd: bi(book.dd_ru, book.dd_en) })]));
      }
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
    // ARB 09.10 round 5: Oracle's annualised figure is a DIFFERENT method from the site/«Деньги»
    // estimate (bar count vs valuation dates) — say so next to the number, not elsewhere.
    if (get(row, "annualized_return.state", null) === "MEASURED") {
      box.appendChild(h("p", { class: "note ux-oracle-method" }, [t("capital.sources.oracle_method")]));
    }
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
        // UX-02: the capital tabs now live inside «Деньги → Подробно»; re-render just this block
        // so the open details stay open (the old renderArea("capital") target no longer exists).
        clear(root);
        renderCapital(root);
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
    c.appendChild(kv("capital.package.last_run_at", ownerTime(p.last_run_at)));
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
    // A copy verified only inside the sync folder (remote_upload NOT_MEASURED) is amber too: the
    // folder lives on this Mac, and reaching the provider's servers was never observed (inv. #17).
    var uploadUnmeasured = cell.is_real_remote && (cell.remote_upload == null || cell.remote_upload === "NOT_MEASURED");
    var cls = cell.is_real_remote && !uploadUnmeasured ? "ok" : "warn";
    var badge = h("span", { class: "badge badge--" + cls }, [t("state." + cell.state)]);
    var text = !cell.is_real_remote ? t("studio.backups.same_host")
      : (uploadUnmeasured ? t("studio.backups.off_host_upload_unmeasured") : t("studio.backups.off_host_ok"));
    return backupRow(badge, text, cell);
  }

  function renderBackupRecovery(cell) {
    cell = cell || {};
    if (isUnknownState(cell.state) && cell.drill_result === undefined) return backupRow(stateBadge(cell), unknownText(cell), cell);
    var text;
    if (cell.drill_result === "OK") text = tf("studio.backups.recovery_ok", { date: /T\d/.test(String(cell.date || "")) ? ownerTime(cell.date) : cell.date });  // a full stamp ⇒ Madrid (ADR-660); a bare date stays a date
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

  function renderDecisionItem(d, gated) {
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
    if (gated) {
      // DIRECTOR-OS-UX-02 E: an owner-queue question is answered ONLY from its card in «Решения», where
      // the version, readiness and an earlier answer are checked. The previous view must not offer a
      // second, unchecked way in — it points there instead (the function moved, it was not removed).
      dc.appendChild(h("p", { class: "ux-note" }, [t("ux.dec.answer_in_card")]));
    } else if (href) {
      // ARB 09.10: every answer path the cockpit offers carries the SAME honest sentence — no path
      // promises a version-bound confirmation the system does not have.
      dc.appendChild(h("p", { class: "ux-note" }, [t("ux.dec.honest_path")]));
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
      p.appendChild(document.createTextNode(ownerTime(d.answered_at)));
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

  function renderDecisions(root, gateOwnerQueue) {
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
          else list.appendChild(renderDecisionItem(d, !!gateOwnerQueue && key === "owner"));
        });
        sec.appendChild(list);
      }
      root.appendChild(sec);
    });
  }

  // ════════════════════════════════════════════════════════════════════════════════════════
  // DIRECTOR-OS-UX-02 — owner sections rendered from `owner_view` (ADR-762). The browser does not
  // decide what a number means: it draws the view's text, names the confidence in WORDS, and
  // keeps source / time / unit / raw codes behind «Технические подробности».
  // ════════════════════════════════════════════════════════════════════════════════════════
  var CONF_CLASS = { MEASURED: "ok", STALE: "warn", PARTIAL: "warn", NOT_MEASURED: "unknown", INTERPRETATION_PROBLEM: "alert" };

  function ov() {
    return get(currentModel, "owner_view.sections", null);
  }

  function techLines(m) {
    var lines = [];
    if (m.source) lines.push(t("ux.source") + ": " + m.source);
    if (m.measured_at_ru) lines.push(t("ux.measured_at") + ": " + m.measured_at_ru);
    if (m.updated_at) lines.push(t("ux.updated_at") + ": " + ownerTime(m.updated_at));
    if (m.unit) lines.push(t("ux.unit") + ": " + m.unit);
    if (m.confidence_ru) lines.push(t("ux.confidence") + ": " + m.confidence_ru);
    var tech = m.technical || {};
    Object.keys(tech).forEach(function (k) {
      var v = tech[k];
      if (v === null || v === undefined || v === "") return;
      lines.push(k + ": " + (typeof v === "object" ? JSON.stringify(v) : String(v)));
    });
    return lines;
  }

  // ``context`` names WHICH card the details belong to for screen readers (ARB 09.10 keyboard check:
  // a row of identical «Технические подробности» names was ambiguous); the visible text is unchanged.
  function uxDetails(lines, title, context) {
    lines = (lines || []).filter(function (x) { return x !== null && x !== undefined && x !== ""; });
    if (!lines.length) return null;
    var det = h("details", { class: "ux-details" });
    var label = title || t("ux.tech_details");
    var sattrs = context ? { "aria-label": label + ": " + context } : {};
    det.appendChild(h("summary", sattrs, [label]));
    var body = h("div", { class: "ux-details-body" });
    lines.forEach(function (l) { body.appendChild(h("p", { class: "ux-tech-line" }, [String(l)])); });
    det.appendChild(body);
    return det;
  }

  function confWord(m) {
    if (!m || m.confidence === "MEASURED") return null;
    return h("span", { class: "ux-state ux-state--" + (CONF_CLASS[m.confidence] || "alert") }, [m.confidence_ru || t("ux.interp")]);
  }

  function metricRow(m, opts) {
    opts = opts || {};
    if (!m) return null;
    var row = h("div", { class: "ux-metric ux-metric--" + (CONF_CLASS[m.confidence] || "alert") + (opts.strong ? " ux-metric--strong" : "") });
    var head = h("div", { class: "ux-metric-head" }, [h("span", { class: "ux-metric-label" }, [m.label || ""])]);
    var w = confWord(m);
    if (w) head.appendChild(w);
    row.appendChild(head);
    row.appendChild(h("p", { class: "ux-metric-text" }, [m.text || t("state.NOT_MEASURED")]));
    // ARB 09.10: a secondary figure (the estimated annualised equivalent) is one short line; its
    // honest explanation opens on tap — never a wall of text, never hidden.
    if (m.secondary_short) {
      var sd = h("details", { class: "ux-details ux-secondary" });
      sd.appendChild(h("summary", { "aria-label": m.secondary_short + ": " + t("ux.explain") }, [m.secondary_short]));
      sd.appendChild(h("p", { class: "ux-note" }, [m.secondary || ""]));
      row.appendChild(sd);
    }
    if (m.data_date_ru) row.appendChild(h("p", { class: "ux-snapshot" }, [m.data_date_ru]));
    var d = uxDetails(techLines(m), null, m.label);
    if (d) row.appendChild(d);
    return row;
  }

  function uxCard(title, extraClass) {
    var c = h("section", { class: "ux-card" + (extraClass ? " " + extraClass : "") });
    if (title) c.appendChild(h("h2", { class: "ux-card-title" }, [title]));
    return c;
  }

  function legacyDetails(title, builder) {
    var det = h("details", { class: "ux-details ux-legacy" });
    det.appendChild(h("summary", {}, [title]));
    var body = h("div", { class: "ux-legacy-body" });
    builder(body);
    det.appendChild(body);
    return det;
  }

  function viewMissing(root) {
    root.appendChild(h("p", { class: "ux-banner ux-banner--warn" }, [t("ux.view_missing")]));
  }

  function snapshotLine() {
    var at = get(currentModel, "owner_view.snapshot_generated_at_ru", null);
    return h("p", { class: "ux-snapshot" }, [at ? tf("ux.data_as_of", { time: at }) : t("ux.data_as_of_unknown")]);
  }

  // ── KPI tile (DIRECTOR-OS-UX-03): a big number, one caption, a status pill in WORDS, and a bar only
  // when the owner view carries a measurable denominator. The whole tile is the link to its section.
  var PILL_TONE = { ok: "ok", info: "info", warn: "warn", problem: "alert", unknown: "unknown" };

  function kpiTile(m, extraClass) {
    if (!m) return null;
    var unknown = m.confidence !== "MEASURED" && m.confidence !== "STALE" && m.confidence !== "PARTIAL";
    var label = (m.label || "") + ": " + (unknown ? (m.text || t("state.NOT_MEASURED")) : ((m.big || "") + ", " + (m.text || "")));
    var cls = "kpi" + (extraClass ? " " + extraClass : "") + (unknown ? " kpi--unknown" : "");
    var area = AREAS.indexOf(m.link_area) >= 0 ? m.link_area : null;   // only our own sections
    var tile = area ? h("a", { class: cls, href: "#" + area, "aria-label": label })
                    : h("div", { class: cls, "aria-label": label });
    var head = h("div", { class: "kpi-head" }, [h("span", { class: "kpi-label" }, [m.label || ""])]);
    if (m.state_pill) head.appendChild(h("span", { class: "pill pill--" + (PILL_TONE[m.state_pill.tone] || "unknown") }, [m.state_pill.text]));
    else if (unknown) head.appendChild(h("span", { class: "pill pill--unknown" }, [m.confidence_ru || t("state.NOT_MEASURED")]));
    tile.appendChild(head);
    tile.appendChild(h("p", { class: "kpi-value" }, [unknown ? "—" : (m.big || "—")]));
    tile.appendChild(h("p", { class: "kpi-caption" }, [m.text || t("state.NOT_MEASURED")]));
    if (m.bar && typeof m.bar.ratio === "number") {
      var bar = h("div", { class: "kpi-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(m.bar.max),
                           "aria-valuenow": String(m.bar.value), "aria-label": m.bar.text || "" });
      bar.appendChild(h("span", { style: "width:" + Math.round(m.bar.ratio * 100) + "%" }));
      tile.appendChild(bar);
      if (m.bar.text) tile.appendChild(h("p", { class: "kpi-bar-text" }, [m.bar.text]));
    }
    return tile;
  }

  function kpiGrid(list, cls) {
    var g = h("div", { class: "kpi-grid" + (cls ? " " + cls : "") });
    list.forEach(function (m) { var tl = kpiTile(m); if (tl) g.appendChild(tl); });
    return g;
  }

  // ── DIRECTOR-OS-UX-04: the owner's mockup («SPA Director OS», 30.08) as the spec ──────────────────────
  // hero → «напиши или продиктуй» → 4 KPI tiles → «что сейчас происходит» | «модельные пакеты» →
  // «требует твоего внимания» | «в разработке». Every number comes from owner_view; a mockup block with
  // no data is shown with the badge «в разработке» and its reason — never hidden, never a demo number.
  var TILE_ICON = { total: "◆", health: "✚", trading: "↗", decisions: "!" };
  var TILE_TONE = { total: "violet", health: "green", trading: "teal", decisions: "amber" };

  function mockKpi(m, key) {
    if (!m) return null;
    var unknown = m.confidence !== "MEASURED" && m.confidence !== "STALE" && m.confidence !== "PARTIAL";
    var area = AREAS.indexOf(m.link_area) >= 0 ? m.link_area : null;
    var label = (m.label || "") + ": " + (unknown ? (m.text || t("state.NOT_MEASURED")) : ((m.big || "") + ", " + (m.text || "")));
    var tile = area ? h("a", { class: "mk-kpi mk-kpi--" + TILE_TONE[key] + (unknown ? " mk-kpi--unknown" : ""), href: "#" + area, "aria-label": label })
                    : h("div", { class: "mk-kpi mk-kpi--" + TILE_TONE[key], "aria-label": label });
    tile.appendChild(h("span", { class: "mk-kpi-icon", "aria-hidden": "true" }, [TILE_ICON[key] || "•"]));
    tile.appendChild(h("p", { class: "mk-kpi-label" }, [m.label || ""]));
    tile.appendChild(h("p", { class: "mk-kpi-value" }, [unknown ? "—" : (m.big || "—")]));
    var cap = h("p", { class: "mk-kpi-caption" }, [m.text || t("state.NOT_MEASURED")]);
    tile.appendChild(cap);
    if (m.state_pill) tile.appendChild(h("span", { class: "pill pill--" + (PILL_TONE[m.state_pill.tone] || "unknown") }, [m.state_pill.text]));
    else if (unknown) tile.appendChild(h("span", { class: "pill pill--unknown" }, [m.confidence_ru || t("state.NOT_MEASURED")]));
    if (m.bar && typeof m.bar.ratio === "number") {
      var bar = h("div", { class: "mk-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(m.bar.max),
                           "aria-valuenow": String(m.bar.value), "aria-label": m.bar.text || "" });
      bar.appendChild(h("span", { style: "width:" + Math.round(m.bar.ratio * 100) + "%" }));
      tile.appendChild(bar);
    }
    return tile;
  }

  function mkCard(title, sub, linkText, linkArea, extra) {
    var c = h("section", { class: "mk-card" + (extra ? " " + extra : "") });
    var head = h("div", { class: "mk-card-head" }, [
      h("div", {}, [h("h2", { class: "mk-card-title" }, [title]), sub ? h("p", { class: "mk-card-sub" }, [sub]) : null]),
    ]);
    if (linkText && linkArea) head.appendChild(h("a", { class: "mk-btn mk-btn--small", href: "#" + linkArea }, [linkText]));
    c.appendChild(head);
    return c;
  }

  function mkRow(r, leadNode) {
    var area = AREAS.indexOf(r.link_area) >= 0 ? r.link_area : null;
    var row = area ? h("a", { class: "mk-row", href: "#" + area }) : h("div", { class: "mk-row" });
    row.appendChild(leadNode);
    row.appendChild(h("div", { class: "mk-row-main" }, [
      h("p", { class: "mk-row-title" }, [r.title || ""]),
      r.sub ? h("p", { class: "mk-row-sub" }, [r.sub]) : null,
    ]));
    var side = h("div", { class: "mk-row-side" });
    if (r.pill) side.appendChild(h("span", { class: "pill pill--" + (PILL_TONE[r.pill.tone] || "unknown") }, [r.pill.text]));
    if (r.meta) side.appendChild(h("span", { class: "mk-row-meta" }, [r.meta]));
    row.appendChild(side);
    return row;
  }

  function quickCreate() {
    var bar = h("div", { class: "mk-quick", role: "group", "aria-label": t("v4.quick_label") });
    var input = h("input", { class: "mk-quick-input", type: "text", id: "quick-text", placeholder: t("v4.quick_placeholder"),
                             "aria-label": t("v4.quick_label"), autocomplete: "off" });
    var mic = h("button", { class: "mk-iconbtn", type: "button", "aria-label": t("v4.quick_mic"), title: t("v4.quick_mic") }, ["🎙"]);
    var go = h("button", { class: "mk-btn mk-btn--primary", type: "button" }, [t("v4.quick_go")]);
    mic.addEventListener("click", function () { openComposer({ text: input.value, startRecording: true }); });
    go.addEventListener("click", function () { openComposer({ text: input.value }); });
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") openComposer({ text: input.value }); });
    bar.appendChild(input);
    bar.appendChild(mic);
    bar.appendChild(go);
    return bar;
  }

  function devCard(items, title, sub) {
    // phone: folded (one line + count) so the first screen stays short; desktop: open, like the mockup
    var c = h("section", { class: "mk-card mk-card--dev" });
    var fold = h("details", { class: "mk-devfold" });
    if (window.innerWidth >= 1024) fold.open = true;
    fold.appendChild(h("summary", { "aria-label": (title || t("v4.in_dev")) + ": " + (items || []).length }, [
      h("div", {}, [h("h2", { class: "mk-card-title" }, [(title || t("v4.in_dev")) + " · " + (items || []).length]),
                    h("p", { class: "mk-card-sub" }, [sub || t("v4.in_dev_sub")])]),
    ]));
    c.appendChild(fold);
    var list = h("div", { class: "mk-list" });
    (items || []).forEach(function (d) {
      list.appendChild(h("div", { class: "mk-dev" }, [
        h("div", { class: "mk-dev-head" }, [h("p", { class: "mk-row-title" }, [d.title]),
                                             h("span", { class: "pill pill--dev" }, [t("v4.in_dev_badge")])]),
        h("p", { class: "mk-row-sub" }, [d.line]),
      ]));
    });
    fold.appendChild(list);
    return c;
  }

  function renderOverview(root) {
    var s = ov();
    var o = s && s.overview;
    if (!o) { viewMissing(root); legacyHomeDetails(root); return; }
    var hl = o.headline || {};
    var head = h("div", { class: "mk-pagehead" }, [
      h("div", {}, [
        h("h1", { class: "mk-hero-title" }, [t("v4.hero_title")]),
        h("p", { class: "mk-hero-sub" }, [hl.mode_line || t("state.NOT_MEASURED")]),
        h("p", { class: "mk-hero-next" }, [h("b", {}, [hl.main || t("state.NOT_MEASURED")]), " · ",
                                           h("span", {}, [t("ux.next_step") + ": " + (hl.next || t("state.NOT_MEASURED"))])]),
      ]),
    ]);
    root.appendChild(head);
    root.appendChild(quickCreate());

    var k = o.kpis || {};
    var grid = h("div", { class: "mk-kpis" });
    [["total", k.total], ["health", k.health], ["trading", k.trading], ["decisions", k.decisions]].forEach(function (x) {
      var tile = mockKpi(x[1], x[0]);
      if (tile) grid.appendChild(tile);
    });
    root.appendChild(grid);

    var two = h("div", { class: "mk-two" });
    var hp = o.happening || {};
    var c1 = mkCard(t("v4.happening"), t("v4.happening_sub"), t("v4.all_work"), "work");
    var l1 = h("div", { class: "mk-list" });
    (hp.rows || []).filter(function (r) { return (r.title || "").indexOf("Пакет «") !== 0; }).forEach(function (r) {
      l1.appendChild(mkRow(r, h("span", { class: "mk-avatar mk-avatar--" + (r.tone || "violet"), "aria-hidden": "true" }, [r.abbr || "•"])));
    });
    c1.appendChild(l1);
    two.appendChild(c1);

    var c2 = mkCard(t("v4.packages"), t("v4.packages_sub"), t("v4.to_money"), "money");
    var l2 = h("div", { class: "mk-list" });
    (k.packages || []).forEach(function (m) {
      var abbr = { "Консервативный": "КС", "Сбалансированный": "СБ", "Агрессивный": "АГ" }[m.label] || "•";
      l2.appendChild(mkRow({ title: m.label, sub: m.text || t("state.NOT_MEASURED"), pill: m.state_pill,
                             meta: m.big && m.big !== "—" ? m.big : null, link_area: "money" },
                           h("span", { class: "mk-avatar mk-avatar--" + ((m.state_pill || {}).tone === "ok" ? "green" : "teal"), "aria-hidden": "true" }, [abbr])));
    });
    c2.appendChild(l2);
    if (k.note) c2.appendChild(h("p", { class: "mk-note" }, [k.note]));
    two.appendChild(c2);
    root.appendChild(two);

    var three = h("div", { class: "mk-two mk-two--equal" });
    var at = o.attention || {};
    var c3 = mkCard(at.title || t("v4.attention_open"), at.sub, t("v4.attention_open"), "decisions");
    var l3 = h("div", { class: "mk-list" });
    var maxRows = window.innerWidth < 600 ? 4 : 6;   // phone: the first four; the rest is one tap away
    var shown = (at.rows || []).slice(0, maxRows);
    var hiddenN = (at.rows || []).length - shown.length + (at.more || 0);
    shown.forEach(function (r) {
      l3.appendChild(mkRow(r, h("span", { class: "mk-numbadge mk-numbadge--" + (r.tone || "amber"),
                                           "aria-label": r.badge + " " + (r.badge_hint || "") }, [r.badge])));
    });
    if (!(at.rows || []).length) l3.appendChild(h("p", { class: "mk-note" }, [at.sub || t("state.NOT_MEASURED")]));
    c3.appendChild(l3);
    if (hiddenN > 0) c3.appendChild(h("p", { class: "mk-note" }, [tf("v4.more", { n: hiddenN })]));
    if ((o.questions || {}).note) c3.appendChild(h("p", { class: "mk-note" }, [o.questions.note]));
    three.appendChild(c3);
    three.appendChild(devCard(o.in_development));
    root.appendChild(three);
    root.appendChild(snapshotLine());
    legacyHomeDetails(root);
  }

  function renderDevArea(root) {
    var key = devKey();
    var all = get(currentModel, "owner_view.in_development", []) || [];
    var d = all.filter(function (x) { return x.key === key; })[0];
    root.appendChild(h("h1", { class: "ux-area-title" }, [d ? (d.nav_title || d.title) : t("v4.dev_title")]));
    root.appendChild(h("p", { class: "mk-hero-sub" }, [t("v4.dev_lead")]));
    if (!d) { root.appendChild(h("p", { class: "ux-banner ux-banner--warn" }, [t("state.NOT_MEASURED")])); return; }
    var c = mkCard(d.title, null, null, null, "mk-card--dev");
    c.appendChild(h("span", { class: "pill pill--dev" }, [t("v4.in_dev_badge")]));
    c.appendChild(h("p", { class: "mk-row-sub" }, [d.line]));
    c.appendChild(h("p", { class: "mk-dev-k" }, [t("v4.needs") + ": " + d.needs]));
    c.appendChild(h("p", { class: "mk-dev-k" }, [t("v4.priority") + ": " + d.priority]));
    root.appendChild(c);
  }

  function legacyHomeDetails(root) {
    root.appendChild(legacyDetails(t("ux.legacy_title"), function (b) {
      renderHome(b);
      b.appendChild(h("p", { class: "legend-note" }, [t("legend.colour")]));
      var dict = get(currentModel, "owner_view.dictionary", []) || [];
      if (dict.length) {
        b.appendChild(h("h3", { class: "ux-sub" }, [t("ux.dictionary")]));
        var ul = h("ul", { class: "ux-list" });
        dict.forEach(function (d) { ul.appendChild(h("li", {}, [d.term + " → " + d.owner + " — " + d.explain])); });
        b.appendChild(ul);
      }
    }));
  }

  function renderWorkArea(root) {
    var s = ov();
    var w = s && s.work;
    if (!w) { viewMissing(root); }
    else {
      var c1 = uxCard((w.now && w.now.title) || "");
      ((w.now && w.now.items) || []).forEach(function (m) { c1.appendChild(metricRow(m)); });
      root.appendChild(c1);
      var c2 = uxCard(w.blocking && w.blocking.title, w.blocking && !w.blocking.known_reason ? "ux-card--quiet" : "");
      c2.appendChild(h("p", { class: "ux-metric-text" }, [(w.blocking && w.blocking.text) || t("state.NOT_MEASURED")]));
      // ARB 09.10: WHICH tasks are stopped and what their card says — reason / next step in words,
      // «не указано в карточке» when the card is silent; card ids only in technical details.
      var stopped = (w.blocking && w.blocking.stopped) || [];
      if (stopped.length) {
        var sl = h("ul", { class: "ux-list ux-stopped" });
        stopped.forEach(function (x) {
          var li = h("li", { class: "ux-stopped-item" }, [
            h("p", { class: "ux-item-title" }, [x.title]),
            h("p", { class: "ux-metric-text" }, [x.reason_text]),
            h("p", { class: "ux-metric-text" }, [x.next_text]),
            h("p", { class: "ux-note" }, [x.updated_ru])]);
          var xd = uxDetails(techLines(x), null, x.title);
          if (xd) li.appendChild(xd);
          sl.appendChild(li);
        });
        c2.appendChild(sl);
      }
      var btd = w.blocking ? uxDetails(techLines(w.blocking), null, w.blocking.title) : null;
      if (btd) c2.appendChild(btd);
      c2.appendChild(h("h3", { class: "ux-sub" }, [(w.next && w.next.title) || ""]));
      c2.appendChild(h("p", { class: "ux-metric-text" }, [(w.next && w.next.text) || t("state.NOT_MEASURED")]));
      root.appendChild(c2);
      var plan = w.plan || {};
      var c3 = uxCard(plan.title);
      if (plan.groups && plan.groups.length) {
        c3.appendChild(h("p", { class: "ux-note" }, [t("ux.plan.groups") + ": " + plan.groups.map(function (g) { return g.title + " — " + g.count; }).join(" · ")]));
      }
      var ul = h("ul", { class: "ux-list ux-plan" });
      (plan.rows || []).forEach(function (r) {
        var li = h("li", { class: "ux-plan-row" }, [
          h("span", { class: "ux-plan-state ux-plan-state--" + (r.state_known ? "ok" : "alert") }, [r.state]),
          h("span", { class: "ux-plan-title" }, [r.title]),
        ]);
        ul.appendChild(li);
      });
      var orig = [];
      (plan.rows || []).forEach(function (r) { var tl = techLines(r); if (tl.length) orig = orig.concat([r.title + ":"], tl); });
      var od = uxDetails(orig, null, plan.title);
      c3.appendChild(ul);
      if (plan.note) c3.appendChild(h("p", { class: "ux-note" }, [plan.note]));
      if (od) c3.appendChild(od);
      root.appendChild(c3);
      var done = w.done || {};
      var c4 = uxCard(done.title);
      if (done.summary) c4.appendChild(metricRow(done.summary));
      var dl = h("ul", { class: "ux-list" });
      (done.items || []).forEach(function (it) {
        var li = h("li", { class: "ux-done" }, [h("span", { class: "ux-done-at" }, [it.at_ru || t("state.NOT_MEASURED")]), h("span", {}, [it.title])]);
        var itd = uxDetails(techLines(it), null, it.title);   // the original (possibly English) description lives here
        if (itd) li.appendChild(itd);
        dl.appendChild(li);
      });
      c4.appendChild(dl);
      root.appendChild(c4);
    }
    root.appendChild(legacyDetails(t("ux.legacy_work"), function (b) {
      var studio = get(truth(), "studio", {}) || {};
      var grid = h("div", { class: "grid" });
      grid.appendChild(renderClaudeWork(studio.claude_work));
      grid.appendChild(renderRoadmap(studio.roadmap));
      grid.appendChild(renderTasks(studio.tasks));
      grid.appendChild(renderReleases(studio.releases));
      grid.appendChild(renderDecisionsSummary(studio.decisions_summary));
      b.appendChild(grid);
    }));
    root.appendChild(legacyDetails(t("ux.legacy_product"), function (b) { renderProduct(b); }));
  }

  function renderMoneyArea(root) {
    var s = ov();
    var m = s && s.money;
    if (!m) { viewMissing(root); }
    else {
      // ARB 09.10 round 5: two plain lines first — «Настоящие деньги: $0» and the mode; the mode's
      // explanation is said ONCE, behind a tap, together with the real-money and readiness metrics
      // (their source/time/confidence stay reachable there, nothing removed).
      var hd = m.head || {};
      var c1 = uxCard(null, "ux-card--hero");
      c1.appendChild(h("p", { class: "ux-hero-money" }, [hd.real_line || t("state.NOT_MEASURED")]));
      c1.appendChild(h("p", { class: "ux-hero-mode" }, [hd.mode_line || t("state.NOT_MEASURED")]));
      var md = h("details", { class: "ux-details ux-more" });
      md.appendChild(h("summary", { "aria-label": t("ux.money.mode_more") }, [t("ux.money.mode_more")]));
      if (hd.mode_detail) md.appendChild(h("p", { class: "ux-note" }, [hd.mode_detail]));
      // the limitation is said once (mode_detail); the two canonical metrics keep only their
      // provenance here — source, measurement time, confidence — not a second copy of the sentence
      [m.real, m.readiness].forEach(function (x) {
        if (!x) return;
        var d = uxDetails([x.text ? t("ux.money.value_at_source") + ": " + x.text : null].concat(techLines(x)),
                          t("ux.money.source_of") + " «" + (x.label || "") + "»", x.label);
        if (d) md.appendChild(d);
      });
      c1.appendChild(md);
      root.appendChild(c1);
      var sm = m.summary || null;
      if (sm) {
        var cs = uxCard(sm.title, "ux-card--flat");
        cs.appendChild(kpiGrid([sm.total].concat(sm.packages || []).filter(Boolean), "kpi-grid--packages kpi-grid--money"));
        if (sm.total && sm.total.secondary_short) {
          var td = h("details", { class: "ux-details ux-secondary" });
          td.appendChild(h("summary", { "aria-label": sm.total.secondary_short + ": " + t("ux.explain") }, [sm.total.secondary_short]));
          td.appendChild(h("p", { class: "ux-note" }, [sm.total.secondary || ""]));
          cs.appendChild(td);
        }
        root.appendChild(cs);
      }
      var p = m.paper || {};
      var c2 = uxCard(p.title);
      // the «virtual capital» limitation is already said once in the head (round 5) — not repeated here
      (p.items || []).forEach(function (x) { c2.appendChild(metricRow(x)); });
      if (p.limitations && p.limitations.length) {
        c2.appendChild(h("h3", { class: "ux-sub" }, [t("ux.limitations")]));
        var ul = h("ul", { class: "ux-list" });
        p.limitations.forEach(function (l) { ul.appendChild(h("li", {}, [l])); });
        c2.appendChild(ul);
      }
      root.appendChild(c2);
      var r = m.research || {};
      var c3 = uxCard(r.title, "ux-card--quiet");
      if (r.note) c3.appendChild(h("p", { class: "ux-note ux-note--lead" }, [r.note]));
      if (sm && sm.trading) c3.appendChild(kpiGrid([sm.trading], "kpi-grid--single"));
      (r.items || []).forEach(function (x) { c3.appendChild(metricRow(x)); });
      root.appendChild(c3);
      root.appendChild(snapshotLine());
    }
    root.appendChild(legacyDetails(t("ux.legacy_capital"), function (b) { renderCapital(b); }));
  }

  function renderProtectionArea(root) {
    var s = ov();
    var p = s && s.protection;
    if (!p) { viewMissing(root); }
    else {
      // Phone-first order (task E): the verdict, then what to do, then backups — all visible; the
      // individual checks and the problems beyond the first few fold into named details.
      var c1 = uxCard(t("ux.prot.checks"), "ux-card--hero");
      if (p.level) c1.appendChild(h("p", { class: "ux-hero-main" }, [p.level]));
      c1.appendChild(metricRow(p.verdict, { strong: true }));
      if (p.check_groups && p.check_groups.length) {
        var gl = h("ul", { class: "ux-list ux-check-groups", "aria-label": t("ux.prot.groups") });
        p.check_groups.forEach(function (g) {
          gl.appendChild(h("li", { class: "ux-check-group ux-check-group--" + g.key }, [
            h("span", { class: "ux-check-group-title" }, [g.title + ": " + g.count]),
            h("span", { class: "ux-note" }, [g.items.length ? " — " + g.items.join(", ") : ""]),
          ]));
        });
        c1.appendChild(gl);
      }
      var checks = p.checks || [];
      if (checks.length) {
        var cd = h("details", { class: "ux-details ux-more" });
        cd.appendChild(h("summary", {}, [tf("ux.prot.all_checks", { n: checks.length })]));
        checks.forEach(function (m) { cd.appendChild(metricRow(m)); });
        c1.appendChild(cd);
      }
      root.appendChild(c1);
      var pr = p.problems || {};
      var c3 = uxCard(t("ux.prot.problems"));
      if (pr.counts_ru && pr.summary && pr.summary.confidence === "MEASURED") {
        c3.appendChild(h("p", { class: "ux-hero-next" }, [h("b", {}, [pr.summary.text]), " · " + pr.counts_ru]));
      } else if (pr.summary) c3.appendChild(metricRow(pr.summary));
      if (pr.actions_note) {
        // write actions are NOT approved (owner 14.10): shown disabled, with the reason in words
        var acts = h("div", { class: "ux-actions-row" }, [
          h("button", { class: "ux-btn ux-btn--disabled", type: "button", disabled: true, "aria-disabled": "true" }, [t("ux.prot.check")]),
          h("button", { class: "ux-btn ux-btn--disabled", type: "button", disabled: true, "aria-disabled": "true" }, [t("ux.prot.fix")]),
        ]);
        c3.appendChild(acts);
        c3.appendChild(h("p", { class: "ux-note" }, [pr.actions_note]));
      }
      var PROBLEMS_VISIBLE = 3;
      var SEV_TONE = { critical: "alert", important: "warn", info: "info" };
      function problemItem(r) {
        var li = h("li", { class: "ux-problem ux-problem--" + (r.severity || "important") }, [
          h("div", { class: "ux-problem-head" }, [
            r.severity_ru ? h("span", { class: "pill pill--" + (SEV_TONE[r.severity] || "warn") }, [r.severity_ru]) : null,
            r.status_ru ? h("span", { class: "ux-problem-status" }, [r.status_ru]) : null,
          ].filter(Boolean)),
          h("p", { class: "ux-problem-what" }, [r.what]),
          r.threat ? h("p", { class: "ux-problem-threat" }, [h("span", { class: "ux-hero-next-label" }, [t("ux.prot.threat") + ": "]), r.threat]) : null,
          h("p", { class: "ux-problem-action" }, [h("span", { class: "ux-hero-next-label" }, [t("ux.prot.what_to_do") + ": "]), r.action]),
        ].filter(Boolean));
        var d = uxDetails(techLines(r), t("ux.prot.view_details"), r.what);
        if (d) li.appendChild(d);
        return li;
      }
      var rows = pr.rows || [];
      var ul = h("ul", { class: "ux-list" });
      rows.slice(0, PROBLEMS_VISIBLE).forEach(function (r) { ul.appendChild(problemItem(r)); });
      c3.appendChild(ul);
      if (rows.length > PROBLEMS_VISIBLE) {
        var more = h("details", { class: "ux-details ux-more" });
        more.appendChild(h("summary", {}, [tf("ux.prot.more_problems", { n: rows.length - PROBLEMS_VISIBLE })]));
        var ul2 = h("ul", { class: "ux-list" });
        rows.slice(PROBLEMS_VISIBLE).forEach(function (r) { ul2.appendChild(problemItem(r)); });
        more.appendChild(ul2);
        c3.appendChild(more);
      }
      root.appendChild(c3);
      var b = p.backups || {};
      var c2 = uxCard(t("ux.prot.backups"));
      ["local", "off_host", "recovery"].forEach(function (k) { if (b[k]) c2.appendChild(metricRow(b[k])); });
      root.appendChild(c2);
      if (p.in_development && p.in_development.length) root.appendChild(devCard(p.in_development));
      root.appendChild(snapshotLine());
    }
    root.appendChild(legacyDetails(t("ux.prot.legacy"), function (b2) {
      var studio = get(truth(), "studio", {}) || {};
      var grid = h("div", { class: "grid" });
      grid.appendChild(renderBackups(studio.backups));
      grid.appendChild(renderProblems(studio.problems));
      grid.appendChild(renderIncidents(studio.incidents));
      grid.appendChild(renderFleet(studio.fleet));
      grid.appendChild(renderScopes(studio.scopes));
      grid.appendChild(cellCard("studio.selfheal.title", studio.self_heal));
      grid.appendChild(renderMachine(studio.machine));
      grid.appendChild(renderMemory(studio.memory));
      grid.appendChild(cellCard("product.health.title", get(truth(), "product.website_health", null)));
      b2.appendChild(grid);
    }));
  }

  // ── decisions: the version the owner READ is remembered per viewer (a convenience, never an approval) ──
  var SEEN_KEY = "dos_decision_seen";

  function readSeen() {
    try {
      var raw = localStorage.getItem(SEEN_KEY);
      var v = raw ? JSON.parse(raw) : {};
      return v && typeof v === "object" ? v : {};
    } catch (e) {
      return {};
    }
  }

  function writeSeen(id, fp) {
    try {
      var v = readSeen();
      v[id] = fp;
      localStorage.setItem(SEEN_KEY, JSON.stringify(v));
    } catch (e) { /* storage unavailable: the conflict check simply cannot remember — answering stays possible */ }
  }

  function decField(label, text) {
    if (text === null || text === undefined || text === "") return null;
    return h("div", { class: "ux-dec-field" }, [h("p", { class: "ux-dec-label" }, [label]), h("p", { class: "ux-dec-text" }, [text])]);
  }

  // The canonical card text, presented — not rewritten (ARB 09.10): hard-wrapped lines of one paragraph
  // are joined, blank lines split paragraphs, «1.»/«-» lines become list items, **…** bold and `…` code.
  // Built with text nodes only (no HTML parsing at all), so the card text cannot inject markup.
  function inlineMd(text) {
    var out = [];
    String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach(function (part) {
      if (!part) return;
      if (/^\*\*[^*]+\*\*$/.test(part)) out.push(h("b", {}, [part.slice(2, -2)]));
      else if (/^`[^`]+`$/.test(part)) out.push(h("code", { class: "ux-dec-code" }, [part.slice(1, -1)]));
      else out.push(part);
    });
    return out;
  }

  function canonicalText(text) {
    var box = h("div", { class: "ux-dec-text" });
    var para = [], list = null;
    function flushPara() { if (para.length) { box.appendChild(h("p", {}, inlineMd(para.join(" ")))); para = []; } }
    function flushList() { if (list) { box.appendChild(list); list = null; } }
    String(text || "").split("\n").forEach(function (raw) {
      var ln = raw.trim();
      if (!ln) { flushPara(); flushList(); return; }
      var m = ln.match(/^(\d+\.|[-*•])\s+(.*)$/);
      if (m) {
        flushPara();
        if (!list) list = h(/^\d/.test(m[1]) ? "ol" : "ul", { class: "ux-dec-list" });
        list.appendChild(h("li", {}, inlineMd(m[2])));
        return;
      }
      if (list && list.lastChild && /^\s/.test(raw)) {   // an indented continuation of a list item
        list.lastChild.appendChild(document.createTextNode(" "));
        inlineMd(ln).forEach(function (n) { list.lastChild.appendChild(typeof n === "string" ? document.createTextNode(n) : n); });
        return;
      }
      if (list && list.lastChild && !para.length) {        // an unindented wrap of the last item
        list.lastChild.appendChild(document.createTextNode(" "));
        inlineMd(ln).forEach(function (n) { list.lastChild.appendChild(typeof n === "string" ? document.createTextNode(n) : n); });
        return;
      }
      para.push(ln);
    });
    flushPara(); flushList();
    return box;
  }

  function renderDecisionCard(it) {
    var det = h("details", { class: "ux-dec", "data-decision-id": it.id || "" });
    var sum = h("summary", { class: "ux-dec-summary" }, [
      h("span", { class: "ux-q-title" }, [it.title]),
      h("span", { class: "ux-q-meta" + (it.subject_known ? "" : " ux-q-meta--warn") }, [it.subject + (it.age_days !== null && it.age_days !== undefined ? " · " + tf("ux.age_days", { days: it.age_days }) : "")]),
      it.short_why ? h("span", { class: "ux-dec-short" }, [h("b", {}, [t("ux.dec.why") + ": "]), it.short_why]) : null,
      it.short_next ? h("span", { class: "ux-dec-short" }, [h("b", {}, [t("ux.next_step") + ": "]), it.short_next]) : null,
    ].filter(Boolean));
    det.appendChild(sum);
    var body = h("div", { class: "ux-dec-body" });
    if (it.full_available && it.full && it.full.length) {
      // owner 13.10: the meaning first, in plain words (the owner view's cleaned fields); the WHOLE
      // canonical card — exactly as written, with file names and document numbers — one tap further
      // (ARB 09.10: never shortened or rewritten, only moved behind «Полный текст»).
      // the whole card in plain words — complete, never cut mid-sentence
      var plainBox = h("div", { class: "ux-dec-full", role: "region", "aria-label": t("ux.dec.plain") + ": " + it.title });
      (it.full_plain || []).forEach(function (sec) {
        if (sec.heading) plainBox.appendChild(h("h3", { class: "ux-dec-h" }, [sec.heading]));
        plainBox.appendChild(canonicalText(sec.text));
      });
      body.appendChild(plainBox);
      var fullDet = h("details", { class: "ux-details ux-dec-fulldet" });
      fullDet.appendChild(h("summary", { "aria-label": t("ux.dec.full_open") + ": " + it.title }, [t("ux.dec.full_open")]));
      var fullBox = h("div", { class: "ux-dec-full", role: "region", "aria-label": t("ux.dec.full") + ": " + it.title });
      it.full.forEach(function (sec) {
        if (sec.heading) fullBox.appendChild(h("h3", { class: "ux-dec-h" }, [sec.heading]));
        fullBox.appendChild(canonicalText(sec.text));
      });
      fullDet.appendChild(fullBox);
      body.appendChild(fullDet);
    } else {
      [["ux.dec.proposal", it.proposal], ["ux.dec.why", it.why]].forEach(function (p) { var f = decField(t(p[0]), p[1]); if (f) body.appendChild(f); });
    }
    if (!(it.full_available) && it.options && it.options.length) {
      var ol = h("ol", { class: "ux-dec-options" });
      it.options.forEach(function (o) { ol.appendChild(h("li", {}, [String(o.n) + ". " + o.text])); });
      body.appendChild(h("div", { class: "ux-dec-field" }, [h("p", { class: "ux-dec-label" }, [t("ux.dec.options")]), ol]));
    }
    // with the full text on screen only what the text cannot say stays as a field (what blocks the
    // answer); the fingerprint wording lives in technical details — no repeated warnings
    (it.full_available ? [["ux.dec.blocking", it.blocking]] :
     [["ux.dec.alternatives", it.alternatives], ["ux.dec.consequences", it.consequences], ["ux.dec.checked", it.checked],
      ["ux.dec.blocking", it.blocking], ["ux.dec.scope", it.scope], ["ux.dec.limitations", it.limitations],
      ["ux.dec.rollback", it.rollback], ["ux.dec.version", it.version && it.version.text]]).forEach(function (p) {
      var f = decField(t(p[0]), p[1]); if (f) body.appendChild(f);
    });
    var ans = it.answer || {};
    var fp = it.version && it.version.fingerprint;
    var box = h("div", { class: "ux-dec-answer" });
    function paintAnswer() {
      clear(box);
      if (ans.kind === "READY") {
        var seen = readSeen()[it.id];
        if (fp && seen && seen !== fp) {
          box.appendChild(h("p", { class: "ux-banner ux-banner--warn", role: "status" }, [t("ux.dec.changed")]));
          box.appendChild(h("button", { class: "ux-btn ux-btn--disabled", type: "button", disabled: true, "aria-disabled": "true" }, [ans.text]));
          var re = h("button", { class: "ux-btn", type: "button" }, [t("ux.dec.reread")]);
          re.addEventListener("click", function () { writeSeen(it.id, fp); paintAnswer(); });
          box.appendChild(re);
          return;
        }
        if (fp) box.appendChild(h("p", { class: "ux-note" }, [tf("ux.dec.answering_version", { v: it.version.short })]));
        if (safeLink(ans.link)) box.appendChild(h("a", { class: "ux-btn ux-btn--primary", href: safeLink(ans.link), target: "_blank", rel: "noopener noreferrer" }, [ans.text]));
        if (ans.reason) box.appendChild(h("p", { class: "ux-note" }, [ans.reason]));
      } else {
        box.appendChild(h("p", { class: "ux-state ux-state--" + (ans.kind === "ANSWERED" ? "ok" : "alert") }, [ans.text || t("ux.interp")]));
        box.appendChild(h("button", { class: "ux-btn ux-btn--disabled", type: "button", disabled: true, "aria-disabled": "true" }, [ans.kind === "ANSWERED" ? ans.text : t("ux.dec.blocking")]));
        if (ans.reason) box.appendChild(h("p", { class: "ux-note" }, [ans.reason]));
      }
    }
    paintAnswer();
    body.appendChild(box);
    var techs = [];
    if (it.id) techs.push("id: " + it.id);
    if (it.version && it.version.text) techs.push(it.version.text);
    if (fp) techs.push("отпечаток (sha256): " + fp);
    if (it.version && it.version.fields) techs.push("поля отпечатка: " + it.version.fields.join(", ") + " (это не версия полного решения)");
    var td = uxDetails(techs.concat(it.summary ? techLines(it.summary) : []), null, it.title);
    if (td) body.appendChild(td);
    det.appendChild(body);
    // Opening = reading. The FIRST read remembers the version; a later different version is never
    // overwritten silently — the owner has to press «перечитал(а)».
    det.addEventListener("toggle", function () {
      if (det.open && fp && !readSeen()[it.id]) { writeSeen(it.id, fp); }
    });
    return det;
  }

  function renderDecisionsArea(root) {
    var s = ov();
    var d = s && s.decisions;
    if (!d) { viewMissing(root); }
    else {
      var counted = d.summary && d.summary.confidence === "MEASURED";
      var c1 = uxCard(counted ? d.summary.text : null, "ux-card--hero");
      if (d.summary && !counted) c1.appendChild(metricRow(d.summary, { strong: true }));
      if (d.note) c1.appendChild(h("p", { class: "ux-note" }, [d.note]));
      if (d.owner && d.owner.length) d.owner.forEach(function (it) { c1.appendChild(renderDecisionCard(it)); });
      // «Вопросов нет» only when the queue was actually read — an unread queue is «не измерено», never zero (inv #17).
      else if (d.summary && d.summary.confidence === "MEASURED") c1.appendChild(h("p", { class: "ux-note" }, [t("ux.dec.none")]));
      root.appendChild(c1);
      var c2 = uxCard(t("ux.dec.other_groups"), "ux-card--quiet");
      if (!(d.groups && d.groups.length)) c2.appendChild(h("p", { class: "ux-note" }, [t("state.NOT_MEASURED")]));
      (d.groups || []).forEach(function (g) {
        var det = h("details", { class: "ux-details" });
        det.appendChild(h("summary", {}, [g.title + " · " + g.count]));
        var b = h("div", { class: "ux-details-body" });
        b.appendChild(h("p", { class: "ux-note" }, [g.explain]));
        var ul = h("ul", { class: "ux-list" });
        (g.items || []).forEach(function (x) { ul.appendChild(h("li", {}, [x.title])); });
        b.appendChild(ul);
        det.appendChild(b);
        c2.appendChild(det);
      });
      root.appendChild(c2);
      var c3 = uxCard(t("ux.dec.history"));
      if (d.history && d.history.length) {
        var hl = h("ul", { class: "ux-list" });
        d.history.forEach(function (x) {
          hl.appendChild(h("li", { class: "ux-done" }, [h("span", { class: "ux-done-at" }, [x.at_ru]), h("span", {}, [x.title + " — " + x.answer + " · " + x.version])]));
        });
        c3.appendChild(hl);
      } else if (d.summary && d.summary.confidence === "MEASURED") c3.appendChild(h("p", { class: "ux-note" }, [t("ux.dec.history_empty")]));
      else c3.appendChild(h("p", { class: "ux-note" }, [t("state.NOT_MEASURED")]));
      root.appendChild(c3);
      root.appendChild(snapshotLine());
    }
    root.appendChild(legacyDetails(t("ux.dec.legacy"), function (b2) { renderDecisions(b2, true); }));
  }

  function initWriteButton() {
    var btn = document.getElementById("write-btn");
    if (!btn) return;
    btn.textContent = t("v4.write");
    btn.setAttribute("aria-label", t("intake.title"));
    btn.addEventListener("click", function () { openComposer({}); });
  }

  // ── theme: owner 15.10 — dark only («белая тема вообще не нужна»); no toggle, nothing stored ──
  // ── top-level render ───────────────────────────────────────────────────────────────────
  // ── ADR-760: the ONE write action — a new inbox record, typed or dictated ─────────────────────────────
  // Voice is recorded in the browser, transcribed on the owner's Mac by the SAME offline whisper the
  // Telegram bot uses, shown for editing, and sent ONLY when the owner presses «Отправить» with a kind
  // chosen. The server creates a NEW inbox card and nothing else (no execution, no answers, no money).
  var INTAKE_CSRF = "/api/intake/csrf";
  var INTAKE_TRANSCRIBE = "/api/intake/transcribe";
  var INTAKE_SUBMIT = "/api/intake/submit";
  var MAX_RECORD_MS = 120000;
  var composer = null;

  function intakeHeaders(ct) {
    var hd = { "Content-Type": ct };
    if (composer && composer.token) hd["X-Intake-Token"] = composer.token;
    return hd;
  }

  function setComposerStatus(text, tone) {
    if (!composer) return;
    composer.status.textContent = text || "";
    composer.status.className = "mk-status" + (tone ? " mk-status--" + tone : "");
  }

  function refreshSendState() {
    if (!composer) return;
    var ok = !composer.unavailable && !composer.busy && composer.kind && composer.text.value.trim().length > 0;
    composer.send.disabled = !ok;
  }

  function closeComposer() {
    if (!composer) return;
    try { if (composer.recorder && composer.recorder.state !== "inactive") composer.recorder.stop(); } catch (e) { /* already stopped */ }
    if (composer.stream) composer.stream.getTracks().forEach(function (tr) { tr.stop(); });
    var back = composer.opener;
    clear(document.getElementById("composer-root"));
    document.removeEventListener("keydown", composer.onKey);
    composer = null;
    if (back && back.focus) back.focus();
  }

  function stopRecording() {
    if (composer && composer.recorder && composer.recorder.state !== "inactive") composer.recorder.stop();
  }

  function startRecording() {
    if (!composer) return;
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)) {
      setComposerStatus(t("intake.no_mic"), "warn");
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      if (!composer) { stream.getTracks().forEach(function (tr) { tr.stop(); }); return; }
      var type = window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "audio/webm";
      var rec;
      try { rec = new window.MediaRecorder(stream, { mimeType: type }); }
      catch (e) { rec = new window.MediaRecorder(stream); }   // Safari may refuse an explicit mimeType
      var chunks = [];
      composer.stream = stream;
      composer.recorder = rec;
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      // iPhone Safari (2026-10-15, owner's first real try): a recorder started without a timeslice
      // can deliver its only data chunk AFTER onstop, so the posted blob was 0 bytes (server: 411
      // LENGTH «Пустой запрос»). Collect every second, wait a beat for the last chunk, and never
      // post an empty recording.
      rec.onstop = function () {
        setTimeout(function () { finishRecording(); }, 300);
      };
      function finishRecording() {
        stream.getTracks().forEach(function (tr) { tr.stop(); });
        if (!composer) return;
        clearTimeout(composer.timer);
        composer.rec.textContent = t("intake.record");
        composer.rec.setAttribute("aria-pressed", "false");
        var sentType = ((rec.mimeType || type).split(";")[0]) || type;
        var blob = new Blob(chunks, { type: sentType });
        if (!blob.size) {
          setComposerStatus(t("intake.empty_recording"), "warn");
          return;
        }
        type = sentType;
        composer.busy = true;
        refreshSendState();
        setComposerStatus(t("intake.transcribing"), "info");
        fetch(INTAKE_TRANSCRIBE, { method: "POST", headers: intakeHeaders(type), body: blob, cache: "no-store" })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
          .then(function (res) {
            if (!composer) return;
            composer.busy = false;
            if (res.ok && res.d && res.d.text) {
              composer.text.value = (composer.text.value.trim() ? composer.text.value.trim() + "\n" : "") + res.d.text;
              composer.transcript = res.d.text;
              setComposerStatus(t("intake.transcribed"), "ok");
            } else {
              setComposerStatus(tf("intake.error", { reason: (res.d && res.d.message) || t("state.NOT_MEASURED") }), "problem");
            }
            refreshSendState();
          })
          .catch(function () {
            if (!composer) return;
            composer.busy = false;
            setComposerStatus(tf("intake.error", { reason: t("header.no_connection") }), "problem");
            refreshSendState();
          });
      }
      rec.start(1000);
      composer.rec.textContent = t("intake.stop");
      composer.rec.setAttribute("aria-pressed", "true");
      setComposerStatus(t("intake.recording"), "info");
      composer.timer = setTimeout(stopRecording, MAX_RECORD_MS);
    }).catch(function () {
      setComposerStatus(t("intake.mic_denied"), "warn");
    });
  }

  function submitComposer() {
    if (!composer) return;
    var text = composer.text.value.trim();
    if (!text) { setComposerStatus(t("intake.need_text"), "warn"); return; }
    if (!composer.kind) { setComposerStatus(t("intake.need_kind"), "warn"); return; }
    composer.busy = true;
    refreshSendState();
    setComposerStatus(t("intake.sending"), "info");
    var payload = { text: text, kind: composer.kind };
    if (composer.transcript) payload.transcript = composer.transcript;
    fetch(INTAKE_SUBMIT, { method: "POST", headers: intakeHeaders("application/json"), body: JSON.stringify(payload), cache: "no-store" })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!composer) return;
        composer.busy = false;
        if (res.ok && res.d && res.d.ok) {
          setComposerStatus(tf("intake.sent", { title: res.d.title, kind: (res.d.kind_ru || "").toLowerCase() }), "ok");
          composer.text.value = "";
          composer.transcript = null;
          var q = document.getElementById("quick-text");
          if (q) q.value = "";
          composer.send.disabled = true;
          composer.cancel.textContent = t("intake.close");
        } else {
          setComposerStatus(tf("intake.error", { reason: (res.d && res.d.message) || t("state.NOT_MEASURED") }), "problem");
          refreshSendState();
        }
      })
      .catch(function () {
        if (!composer) return;
        composer.busy = false;
        setComposerStatus(tf("intake.error", { reason: t("header.no_connection") }), "problem");
        refreshSendState();
      });
  }

  function openComposer(opts) {
    opts = opts || {};
    if (composer) closeComposer();
    var root = document.getElementById("composer-root");
    if (!root) return;
    clear(root);
    composer = { kind: null, transcript: null, token: null, unavailable: false, busy: false, opener: document.activeElement };
    var backdrop = h("div", { class: "mk-backdrop" });
    backdrop.addEventListener("click", closeComposer);
    var dlg = h("div", { class: "mk-modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "composer-title" });
    var closeBtn = h("button", { class: "mk-iconbtn", type: "button", "aria-label": t("intake.close") }, ["✕"]);
    closeBtn.addEventListener("click", closeComposer);
    dlg.appendChild(h("div", { class: "mk-modal-head" }, [h("h2", { id: "composer-title", class: "mk-card-title" }, [t("intake.title")]), closeBtn]));
    var body = h("div", { class: "mk-modal-body" });
    body.appendChild(h("p", { class: "mk-card-sub" }, [t("intake.lead")]));
    composer.text = h("textarea", { class: "mk-textarea", id: "composer-text", rows: "5", maxlength: "4000" });
    composer.text.value = opts.text || "";
    composer.text.addEventListener("input", refreshSendState);
    body.appendChild(h("label", { class: "mk-field-label", for: "composer-text" }, [t("intake.text_label")]));
    body.appendChild(composer.text);
    composer.rec = h("button", { class: "mk-btn mk-btn--voice", type: "button", "aria-pressed": "false" }, [t("intake.record")]);
    composer.rec.addEventListener("click", function () {
      if (composer.recorder && composer.recorder.state === "recording") stopRecording();
      else startRecording();
    });
    body.appendChild(composer.rec);
    body.appendChild(h("p", { class: "mk-field-label", id: "composer-kind-label" }, [t("intake.kind_label")]));
    var kinds = h("div", { class: "mk-kinds", role: "group", "aria-labelledby": "composer-kind-label" });
    ["idea", "task", "note"].forEach(function (k) {
      var b = h("button", { class: "mk-kind", type: "button", "aria-pressed": "false", "data-kind": k }, [t("intake.kind." + k)]);
      b.addEventListener("click", function () {
        composer.kind = k;
        Array.prototype.forEach.call(kinds.children, function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        refreshSendState();
      });
      kinds.appendChild(b);
    });
    body.appendChild(kinds);
    body.appendChild(h("p", { class: "mk-note" }, [t("intake.privacy")]));
    dlg.appendChild(body);
    composer.status = h("p", { class: "mk-status", role: "status", "aria-live": "polite" });
    composer.cancel = h("button", { class: "mk-btn", type: "button" }, [t("intake.cancel")]);
    composer.cancel.addEventListener("click", closeComposer);
    composer.send = h("button", { class: "mk-btn mk-btn--primary", type: "button", disabled: true }, [t("intake.send")]);
    composer.send.addEventListener("click", submitComposer);
    dlg.appendChild(h("div", { class: "mk-modal-foot" }, [composer.status, h("div", { class: "mk-modal-actions" }, [composer.cancel, composer.send])]));
    root.appendChild(backdrop);
    root.appendChild(dlg);
    composer.onKey = function (e) { if (e.key === "Escape") closeComposer(); };
    document.addEventListener("keydown", composer.onKey);
    composer.text.focus();
    fetch(INTAKE_CSRF, { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(function (d) {
        if (!composer) return;
        composer.token = d && d.token;
        if (!composer.token) throw new Error("no token");
        if (opts.startRecording) startRecording();
        refreshSendState();
      })
      .catch(function () {
        if (!composer) return;
        composer.unavailable = true;
        composer.rec.disabled = true;
        setComposerStatus(t("intake.unavailable"), "warn");
        refreshSendState();
      });
  }

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
    if (area !== "overview" && area !== "dev") container.appendChild(h("h1", { class: "ux-area-title" }, [t("nav." + area)]));
    if (window.MC_I18N.getLang() === "en") {
      container.appendChild(h("p", { class: "ux-banner ux-banner--warn", role: "note" }, [t("ux.ru_only")]));
    }
    if (area === "overview") renderOverview(container);
    else if (area === "decisions") renderDecisionsArea(container);
    else if (area === "work") renderWorkArea(container);
    else if (area === "money") renderMoneyArea(container);
    else if (area === "protection") renderProtectionArea(container);
    else if (area === "dev") renderDevArea(container);
  }

  // ── keep what the owner opened (owner 13.10: «карточка сворачивается во время чтения») ──────────
  // The 60-s refresh re-renders the area. Before it, every open <details> is remembered by a STABLE key
  // (decision id, else its summary text + occurrence) together with its text; after it, the same keys
  // are re-opened and the scroll position is restored. If an open card's text changed, a quiet note
  // «Данные обновились» is shown inside it — the owner is never moved silently.
  function detailsKeys(container) {
    var seen = {};
    var out = [];
    Array.prototype.forEach.call(container.querySelectorAll("details"), function (d) {
      var id = d.getAttribute("data-decision-id");
      var sum = d.querySelector("summary");
      var base = id ? "dec:" + id : "sum:" + (sum ? sum.textContent.trim() : "");
      seen[base] = (seen[base] || 0) + 1;
      out.push({ key: base + "#" + seen[base], el: d });
    });
    return out;
  }

  function captureState(area) {
    var container = document.getElementById("area-" + area);
    var st = { area: area, scrollY: window.scrollY || 0, open: {} };
    if (!container) return st;
    detailsKeys(container).forEach(function (x) {
      if (x.el.open) st.open[x.key] = x.el.textContent;
    });
    return st;
  }

  function restoreState(st) {
    if (!st) return;
    var container = document.getElementById("area-" + st.area);
    if (!container) return;
    detailsKeys(container).forEach(function (x) {
      if (!Object.prototype.hasOwnProperty.call(st.open, x.key)) return;
      x.el.open = true;
      if (st.open[x.key] !== x.el.textContent) {
        var sum = x.el.querySelector("summary");
        var note = h("p", { class: "ux-updated", role: "status" }, [t("ux.updated")]);
        if (sum && sum.nextSibling) x.el.insertBefore(note, sum.nextSibling);
        else x.el.appendChild(note);
      }
    });
    window.scrollTo(0, st.scrollY);
  }

  function renderAll(opts) {
    opts = opts || {};
    var area = currentArea();
    var st = opts.keepState ? captureState(area) : null;
    renderHeaderStaticText();
    renderMoneyChip();
    renderStatusStrip();
    renderNav();
    showArea(area);
    renderArea(area);
    if (st) restoreState(st);
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
      renderAll({ keepState: true });
    });
    paint();
  }

  window.addEventListener("hashchange", function () { if (composer) closeComposer(); renderAll(); window.scrollTo(0, 0); });
  initWriteButton();
  initLangToggle();
  loadModel();
  // A test/preview page may shorten the refresh with <meta name="dos-refresh-ms" content="N"> (≥ 200) to
  // prove the open-card state survives several refreshes; production index.html carries no such meta.
  (function () {
    var meta = document.querySelector("meta[name=dos-refresh-ms]");
    var n = meta ? parseInt(meta.getAttribute("content") || "", 10) : NaN;
    setInterval(loadModel, !isNaN(n) && n >= 200 ? n : REFRESH_MS);
  })();
})();
