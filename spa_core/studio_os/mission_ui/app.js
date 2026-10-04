/* spa_core/studio_os/mission_ui/app.js — Mission Control v1 (ADR-552)
 *
 * Read-only renderer for mission.json. No framework, no build step, ES2020.
 *
 * SECURITY (enforced by spa_core/tests/test_mission_ui_static.py):
 *  - DOM is built with document.createElement + textContent only: no markup-from-string
 *    sink of any kind, and no dynamic code construction of any kind.
 *  - Any href taken from the model is only ever set through safeLink(), which requires
 *    the exact prefix 'https://t.me/'. Internal navigation hrefs ('#overview' etc.) are
 *    hardcoded string literals, never built from model data.
 */
"use strict";

(function () {
  var t = window.MC_I18N.t;
  var AREAS = ["overview", "capital", "studio", "decisions", "system"];
  var NAV_ICON = { overview: "◉", capital: "◈", studio: "⚙", decisions: "✉", system: "⌂" };
  var LINEAGE_STAGES = ["IDEA", "TASK", "ASSIGNED", "RUN", "ARTIFACT", "REVIEW", "DECISION", "RELEASE", "OUTCOME", "MEMORY"];
  var REFRESH_MS = 60000;
  var STALE_AFTER_MIN = 15;
  var TELEGRAM_PREFIX = "https://t.me/";

  var currentModel = null;
  var fetchFailed = false;
  var staleFlag = false;

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

  // ── routing ─────────────────────────────────────────────────────────────────────────────
  function currentArea() {
    var h2 = (location.hash || "").replace("#", "");
    return AREAS.indexOf(h2) >= 0 ? h2 : "overview";
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
    nav.appendChild(telegramButton(intake.ask, t("header.ask")));
    nav.appendChild(telegramButton(intake.idea, t("header.idea")));
    nav.appendChild(telegramButton(intake.voice, t("header.voice")));
    nav.appendChild(telegramButton(intake.report, t("header.report")));
    if (intake.how) {
      var details = h("details", { class: "intake-how" });
      details.appendChild(h("summary", {}, [t("header.how_toggle")]));
      details.appendChild(h("p", {}, [intake.how]));
      nav.appendChild(details);
    }
  }

  function renderLegend() {
    var el = document.getElementById("legend");
    clear(el);
    el.appendChild(h("p", { class: "legend-note" }, [t("legend.note")]));
  }

  function renderStatusStrip() {
    var strip = document.getElementById("status-strip");
    clear(strip);
    if (fetchFailed || !currentModel) {
      strip.appendChild(h("div", { class: "status-banner status-banner--alert" }, [t("status.no_connection")]));
      return;
    }
    if (staleFlag) {
      strip.appendChild(h("div", { class: "status-banner status-banner--warn" }, [t("status.stale_banner")]));
    }
    var sysState = get(currentModel, "overview.system.state", null);
    var needsOwner = get(currentModel, "overview.needs_owner.count", null);
    var ageMin = dataAgeMin(currentModel);
    var ageText = ageMin === null ? t("common.not_measured") : Math.round(ageMin) + " " + t("common.minutes_ago");
    var row = h("div", { class: "status-row" }, [
      renderBadge(sysState, staleFlag),
      h("span", { class: "chip" }, [t("status.needs_you") + ": " + textOrNM(needsOwner)]),
      h("span", { class: "chip" }, [t("status.age") + ": " + ageText]),
    ]);
    strip.appendChild(row);
  }

  // ── OVERVIEW ───────────────────────────────────────────────────────────────────────────
  function card(titleText, extra) {
    var c = h("section", { class: "card" });
    var head = h("div", { class: "card-head" });
    head.appendChild(h("h2", { class: "card-title" }, [titleText]));
    if (extra) head.appendChild(extra);
    c.appendChild(head);
    return c;
  }

  function renderOverview(root, model) {
    var ov = model.overview || {};
    var grid = h("div", { class: "grid" });
    grid.appendChild(renderOverviewSystem(ov.system));
    grid.appendChild(renderOverviewNeedsOwner(ov.needs_owner));
    grid.appendChild(renderOverviewNow(ov.now));
    grid.appendChild(renderOverviewCapital(ov.capital));
    grid.appendChild(renderOverviewToday(ov.today));
    grid.appendChild(renderOverviewResources(ov.resources));
    root.appendChild(grid);
  }

  function renderOverviewSystem(sys) {
    sys = sys || {};
    var c = card(t("overview.system.title"), renderBadge(sys.state, isStaleGlobal()));
    var counts = sys.counts || {};
    var row = h("div", { class: "chip-row" });
    Object.keys(counts).forEach(function (k) {
      row.appendChild(h("span", { class: "chip" }, [k + ": " + counts[k]]));
    });
    c.appendChild(row);
    if (sys.reason) c.appendChild(h("p", { class: "note" }, [t("overview.system.why") + ": " + sys.reason]));
    c.appendChild(renderListField("overview.system.critical_alerts", sys.critical_alerts));
    c.appendChild(renderListField("overview.system.alerts", sys.alerts));
    return c;
  }

  function renderOverviewNeedsOwner(no) {
    no = no || {};
    var c = card(t("overview.needs_owner.title"));
    c.appendChild(kv("overview.needs_owner.count", no.count));
    c.appendChild(kv("overview.needs_owner.accepted", no.accepted_in_work));
    var top = no.top;
    if (top === null || top === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
    } else if (!Array.isArray(top) || top.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
    } else {
      var ul = h("ul", { class: "plain-list" });
      top.forEach(function (item) {
        var li = h("li", {});
        li.appendChild(h("a", { class: "link-item", href: "#decisions" }, [item.title || item.id]));
        ul.appendChild(li);
      });
      c.appendChild(ul);
      c.appendChild(h("a", { class: "btn btn-link", href: "#decisions" }, [t("overview.needs_owner.open_all")]));
    }
    return c;
  }

  function renderOverviewNow(now) {
    now = now || {};
    var c = card(t("overview.now.title"));
    var epic = now.current_epic;
    c.appendChild(kv("overview.now.current_epic", epic ? epic.epic + " — " + t("vocab.work." + epic.state) : null));
    c.appendChild(kv("overview.now.in_progress", now.in_progress));
    c.appendChild(kv("overview.now.blocked", now.blocked));
    c.appendChild(kv("overview.now.workers", now.claude_workers));
    c.appendChild(kv("overview.now.heavy_jobs", now.heavy_jobs));
    return c;
  }

  function renderOverviewCapital(cap) {
    cap = cap || {};
    var c = card(t("overview.capital.title"));
    var rc = cap.real_capital || {};
    var box = h("div", { class: "real-capital-box" });
    box.appendChild(h("strong", {}, [t("overview.capital.real_capital") + ": "]));
    box.appendChild(renderCapitalMode(rc));
    var det = h("details", { class: "basis-details" });
    det.appendChild(h("summary", {}, [t("common.details")]));
    det.appendChild(h("p", {}, [rc.basis === null || rc.basis === undefined ? t("common.not_measured") : rc.basis]));
    box.appendChild(det);
    c.appendChild(box);
    var lrv = cap.live_readiness || {};
    c.appendChild(kv("live.short", t("live.prohibited") + " · $0"));
    var ci = cap.investment_cio || {};
    c.appendChild(kv("cio.short", ci.stance ? t("cio.stance." + ci.stance) +
      (ci.confidence ? " · " + t("cio.confidence." + ci.confidence) : "") : null));
    var pkgs = cap.packages || {};
    var rows = h("div", { class: "package-rows" });
    Object.keys(pkgs).forEach(function (key) {
      var p = pkgs[key] || {};
      var row = h("div", { class: "package-row" });
      row.appendChild(h("span", { class: "package-name" }, [t("capital.package.name." + key)]));
      row.appendChild(renderBadge(p.state, isStaleGlobal()));
      row.appendChild(h("span", { class: "chip" }, [t("capital.package.work") + ": " + textOrNM(p.work)]));
      row.appendChild(h("span", { class: "chip" }, [t("capital.package.decision") + ": " + textOrNM(p.decision)]));
      row.appendChild(h("span", { class: "chip" }, [t("capital.package.evidence") + ": " + textOrNM(p.evidence)]));
      row.appendChild(h("span", { class: "chip" }, [t("capital.package.live") + ": " + textOrNM(p.live)]));
      rows.appendChild(row);
    });
    c.appendChild(rows);
    var tr = cap.trading_research || {};
    var trRow = h("div", { class: "kv-list" });
    trRow.appendChild(renderBadge(tr.state, isStaleGlobal()));
    trRow.appendChild(kv("capital.trading.forward_paper", tr.forward_paper));
    trRow.appendChild(kv("capital.trading.candidates", tr.candidates));
    c.appendChild(trRow);
    return c;
  }

  function renderOverviewToday(today) {
    today = today || {};
    var c = card(t("overview.today.title"));
    c.appendChild(kv("overview.today.releases", today.releases));
    c.appendChild(renderListField("overview.today.releases", today.release_items, function (it) {
      return (it.kind || "?") + " — " + (it.summary || "");
    }));
    c.appendChild(renderListField("overview.today.incidents", today.incidents, function (it) {
      return (it.event || "?") + " · " + (it.since || "?");
    }));
    return c;
  }

  function renderOverviewResources(res) {
    res = res || {};
    var c = card(t("overview.resources.title"), renderBadge(res.state, isStaleGlobal()));
    c.appendChild(kv("overview.resources.disk_free", res.disk_free_gb));
    c.appendChild(kv("overview.resources.memory_pressure", res.pressure_level));
    c.appendChild(kv("overview.resources.swap", res.swap_used_pct));
    return c;
  }

  // ── CAPITAL ────────────────────────────────────────────────────────────────────────────
  function renderCapital(root, model) {
    var cap = model.capital || {};
    root.appendChild(h("p", { class: "area-label" }, [cap.boundary || t("capital.boundary")]));
    var grid = h("div", { class: "grid" });
    grid.appendChild(renderInvestmentCioCard(cap.investment_cio));
    grid.appendChild(renderLiveReadinessCard(cap.live_readiness));
    var pkgs = get(cap, "packages.items", {}) || {};
    Object.keys(pkgs).forEach(function (key) {
      grid.appendChild(renderPackageCard(key, pkgs[key]));
    });
    grid.appendChild(renderTradingResearchCard(cap.trading_research));
    grid.appendChild(renderRealCapitalCard(cap.real_capital));
    grid.appendChild(renderResearchUniverseCard(cap.research_universe));
    root.appendChild(grid);
  }

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

  // ── STUDIO ─────────────────────────────────────────────────────────────────────────────
  function renderStudio(root, model) {
    var studio = model.studio || {};
    root.appendChild(h("p", { class: "area-label" }, [t("studio.title")]));
    var grid = h("div", { class: "grid" });
    grid.appendChild(renderEpicsCard(studio.epics));
    grid.appendChild(renderBoardCard(studio.board, studio.lineage));
    grid.appendChild(renderAgentsCard(studio.agents, "studio.agents.title"));
    grid.appendChild(renderOrphansCard(studio.orphans));
    grid.appendChild(renderReleaseFeedCard(model.release_feed));
    root.appendChild(grid);
  }

  function renderEpicsCard(epics) {
    epics = epics || {};
    var c = card(t("studio.epics.title"));
    var items = epics.items;
    if (items === null || items === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
    } else if (!Array.isArray(items) || items.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
    } else {
      var curN = epics.current ? epics.current.n : null;
      var ul = h("ul", { class: "plain-list" });
      items.forEach(function (it) {
        var li = h("li", { class: "epic-item" + (it.n === curN ? " epic-item--current" : "") });
        li.appendChild(h("span", { class: "epic-n" }, ["#" + it.n + " "]));
        li.appendChild(h("span", {}, [it.epic]));
        li.appendChild(renderWorkChip(it.state));
        if (it.note) li.appendChild(h("div", { class: "epic-note" }, [it.note]));
        ul.appendChild(li);
      });
      c.appendChild(ul);
    }
    c.appendChild(kv("studio.epics.confirmed", epics.roadmap_confirmed));
    return c;
  }

  function renderCardList(labelKey, items, lineage) {
    var wrap = h("div", { class: "list-section" });
    wrap.appendChild(h("div", { class: "k" }, [t(labelKey)]));
    if (items === null || items === undefined) {
      wrap.appendChild(h("div", { class: "v" }, [t("common.not_measured")]));
      return wrap;
    }
    if (!Array.isArray(items) || items.length === 0) {
      wrap.appendChild(h("div", { class: "v" }, [t("common.none")]));
      return wrap;
    }
    var ul = h("ul", { class: "plain-list" });
    items.forEach(function (it) {
      var li = h("li", { class: "card-row" });
      var hasLineage = lineage && Object.prototype.hasOwnProperty.call(lineage, it.id);
      var panel = h("div", { class: "lineage-panel", hidden: true });
      if (hasLineage) {
        var btn = h("button", { type: "button", class: "list-item-btn" }, [it.title || it.id]);
        btn.addEventListener("click", function () {
          if (panel.hidden) {
            clear(panel);
            panel.appendChild(renderLineage(lineage[it.id]));
          }
          panel.hidden = !panel.hidden;
        });
        li.appendChild(btn);
      } else {
        li.appendChild(h("span", { class: "card-row-text" }, [it.title || it.id]));
      }
      li.appendChild(panel);
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    return wrap;
  }

  function renderLineageStateChip(state) {
    var cls = state === "DONE" ? "chip--ok" : state === "MISSING" ? "chip--warn" : "chip--unknown";
    return h("span", { class: "chip " + cls }, [state || t("common.unknown")]);
  }

  function renderLineage(stages) {
    stages = stages || {};
    var ol = h("ol", { class: "lineage-list" });
    LINEAGE_STAGES.forEach(function (stage) {
      var s = stages[stage] || { state: "UNKNOWN", evidence: null };
      var li = h("li", { class: "lineage-stage" });
      li.appendChild(h("span", { class: "stage-name" }, [t("studio.lineage.stage." + stage)]));
      li.appendChild(renderLineageStateChip(s.state));
      li.appendChild(h("div", { class: "stage-evidence" }, [s.evidence === null || s.evidence === undefined ? t("common.not_measured") : String(s.evidence)]));
      ol.appendChild(li);
    });
    return ol;
  }

  function renderBoardCard(board, lineage) {
    board = board || {};
    lineage = lineage || {};
    var c = card(t("studio.board.title"));
    var counts = board.counts || {};
    var row = h("div", { class: "chip-row" });
    Object.keys(counts).forEach(function (k) {
      row.appendChild(h("span", { class: "chip" }, [k + ": " + counts[k]]));
    });
    c.appendChild(row);
    if (board.review_note) c.appendChild(h("p", { class: "note" }, [board.review_note]));
    c.appendChild(renderCardList("studio.board.in_progress", board.in_progress, lineage));
    c.appendChild(renderCardList("studio.board.blocked", board.blocked, lineage));
    c.appendChild(renderCardList("studio.board.recently_done", board.recently_done, lineage));
    c.appendChild(kv("studio.board.queued", board.queued));
    return c;
  }

  function renderAgentsCard(agents, titleKey) {
    agents = agents || {};
    var c = card(t(titleKey || "studio.agents.title"), renderBadge(get(agents, "_meta.state", null), isStaleGlobal()));
    c.appendChild(kv("studio.agents.ok", agents.ok));
    c.appendChild(kv("studio.agents.warning", agents.warning));
    c.appendChild(kv("studio.agents.critical", agents.critical));
    c.appendChild(kv("studio.agents.total", agents.total));
    c.appendChild(renderListField("studio.agents.critical_list", agents.critical_agents));
    c.appendChild(renderListField("studio.agents.warning_list", agents.warning_agents));
    c.appendChild(renderListField("studio.agents.paused", agents.paused_intentionally));
    return c;
  }

  function renderOrphansCard(orphans) {
    orphans = orphans || {};
    var c = card(t("studio.orphans.title"), renderBadge(get(orphans, "_meta.state", null), isStaleGlobal()));
    c.appendChild(kv("studio.orphans.total", orphans.total));
    var counts = orphans.counts;
    if (counts && typeof counts === "object") {
      var row = h("div", { class: "chip-row" });
      Object.keys(counts).forEach(function (k) {
        row.appendChild(h("span", { class: "chip" }, [k + ": " + counts[k]]));
      });
      c.appendChild(row);
    } else {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
    }
    return c;
  }

  function renderReleaseFeedCard(feed) {
    feed = feed || {};
    var c = card(t("studio.release_feed.title"), renderBadge(get(feed, "_meta.state", null), isStaleGlobal()));
    if (feed.release_note) c.appendChild(h("p", { class: "note" }, [feed.release_note]));
    var items = feed.items;
    if (items === null || items === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
      return c;
    }
    if (!Array.isArray(items) || items.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
      return c;
    }
    var ul = h("ul", { class: "plain-list" });
    items.forEach(function (it) {
      var li = h("li", { class: "release-row" });
      li.appendChild(h("span", { class: "release-date" }, [it.at || ""]));
      li.appendChild(h("span", { class: "chip" }, [it.kind || ""]));
      li.appendChild(h("span", { class: "release-summary" }, [it.summary || ""]));
      li.appendChild(h("span", { class: "chip" }, [it.release || ""]));
      var det = h("details", { class: "release-details" });
      det.appendChild(h("summary", {}, [t("studio.release_feed.commit")]));
      var p = h("p", {});
      p.appendChild(document.createTextNode(t("studio.release_feed.commit") + ": " + (it.commit || "—")));
      p.appendChild(h("br"));
      p.appendChild(document.createTextNode(t("studio.release_feed.producer") + ": " + (it.producer || "—")));
      p.appendChild(h("br"));
      p.appendChild(document.createTextNode(t("studio.release_feed.adrs") + ": " + ((it.adrs && it.adrs.length) ? it.adrs.join(", ") : t("common.none"))));
      det.appendChild(p);
      li.appendChild(det);
      ul.appendChild(li);
    });
    c.appendChild(ul);
    return c;
  }

  // ── DECISIONS ──────────────────────────────────────────────────────────────────────────
  function renderDecisions(root, model) {
    var dec = model.decisions || {};
    root.appendChild(h("p", { class: "area-label" }, [dec.how_to_answer || t("decisions.how_to_answer")]));
    root.appendChild(renderDecisionsPending(dec.pending));
    root.appendChild(renderDecisionsResolved(dec.recently_resolved));
  }

  function renderDecisionsPending(items) {
    var c = card(t("decisions.pending.title"));
    if (items === null || items === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
      return c;
    }
    if (!Array.isArray(items) || items.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
      return c;
    }
    var list = h("div", { class: "decision-list" });
    items.forEach(function (d) {
      list.appendChild(renderDecisionCard(d));
    });
    c.appendChild(list);
    return c;
  }

  function renderDecisionCard(d) {
    d = d || {};
    var dc = h("div", { class: "decision-card" });
    dc.appendChild(h("h3", { class: "decision-title" }, [d.title || d.id]));
    var meta = h("div", { class: "chip-row" });
    meta.appendChild(h("span", { class: "chip" }, [t("vocab.decision." + d.state) || d.state || t("common.unknown")]));
    meta.appendChild(h("span", { class: "chip" }, [d.risk_class || t("common.unknown")]));
    meta.appendChild(h("span", { class: "chip" }, [d.created_at || t("common.unknown")]));
    dc.appendChild(meta);
    var det1 = h("details", { class: "decision-reason" });
    det1.appendChild(h("summary", {}, [t("decisions.fields.reason")]));
    det1.appendChild(h("p", {}, [d.reason || t("common.unknown")]));
    dc.appendChild(det1);
    var det2 = h("details", { class: "decision-action" });
    det2.appendChild(h("summary", {}, [t("decisions.fields.requested_action")]));
    det2.appendChild(h("p", {}, [d.requested_action || t("common.unknown")]));
    dc.appendChild(det2);
    dc.appendChild(kv("decisions.fields.done_when", d.done_when));
    dc.appendChild(kv("decisions.fields.source", d.source));
    dc.appendChild(kv("decisions.fields.evidence", d.evidence));
    dc.appendChild(kv("decisions.fields.scope", d.scope));
    dc.appendChild(renderListField("decisions.fields.affected_artifacts", d.affected_artifacts));
    if (d.missing_fields && d.missing_fields.length) {
      dc.appendChild(h("div", { class: "warning-chip" }, [t("decisions.fields.missing_fields") + ": " + d.missing_fields.join(", ")]));
    }
    var href = safeLink(d.telegram_link);
    if (href) {
      dc.appendChild(h("a", { class: "btn btn-primary btn-answer", href: safeLink(d.telegram_link), target: "_blank", rel: "noopener noreferrer" }, [t("decisions.answer_button")]));
    } else {
      dc.appendChild(h("button", { class: "btn btn-disabled", disabled: true, type: "button" }, [t("decisions.answer_unavailable")]));
      if (d.telegram_link_note) dc.appendChild(h("p", { class: "note" }, [d.telegram_link_note]));
    }
    return dc;
  }

  function renderDecisionsResolved(items) {
    var c = card(t("decisions.recently_resolved.title"));
    if (items === null || items === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
      return c;
    }
    if (!Array.isArray(items) || items.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
      return c;
    }
    var ul = h("ul", { class: "plain-list" });
    items.forEach(function (d) {
      var li = h("li", {});
      li.appendChild(h("div", { class: "resolved-title" }, [d.title || d.id]));
      li.appendChild(kv("decisions.fields.owner_answer", d.owner_answer));
      li.appendChild(kv("decisions.fields.answered_at", d.answered_at));
      ul.appendChild(li);
    });
    c.appendChild(ul);
    return c;
  }

  // ── SYSTEM ─────────────────────────────────────────────────────────────────────────────
  function renderSystem(root, model) {
    var sys = model.system || {};
    var grid = h("div", { class: "grid" });
    grid.appendChild(renderSystemResources(sys.resources));
    grid.appendChild(renderHeavyJobsCard(sys.heavy_jobs));
    grid.appendChild(renderCleanupCard(sys.cleanup));
    grid.appendChild(renderBackupsCard(sys.backups));
    grid.appendChild(renderCodeCard(sys.code));
    grid.appendChild(renderServicesCard(sys.services));
    grid.appendChild(renderAgentsCard(sys.agents, "studio.agents.title"));
    grid.appendChild(renderIncidentsCard(sys.incidents));
    grid.appendChild(renderKillSwitchCard(sys.kill_switch, sys.derisk));
    root.appendChild(grid);
  }

  function renderSystemResources(res) {
    res = res || {};
    var c = card(t("system.resources.title"), renderBadge(get(res, "_meta.state", null), isStaleGlobal()));
    var disk = res.disk || {};
    var mem = res.memory || {};
    c.appendChild(kv("system.resources.disk", disk.free_gb));
    c.appendChild(kv("system.resources.memory", mem.pressure_level));
    c.appendChild(kv("system.resources.swap", mem.swap_used_pct));
    var rss = res.rss_mb_by_class;
    if (rss && typeof rss === "object") {
      var row = h("div", { class: "chip-row" });
      Object.keys(rss).forEach(function (k) {
        row.appendChild(h("span", { class: "chip" }, [k + ": " + rss[k] + " MB"]));
      });
      c.appendChild(row);
    } else {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
    }
    c.appendChild(renderListField("system.resources.top_processes", res.top, function (p) {
      return (p.name || "?") + " · " + (p.class || "?") + " · " + (p.rss_mb !== null && p.rss_mb !== undefined ? p.rss_mb + " MB" : t("common.not_measured"));
    }));
    return c;
  }

  function renderHeavyJobsCard(leases) {
    var c = card(t("system.heavy_jobs.title"));
    if (leases === null || leases === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
    } else if (!Array.isArray(leases) || leases.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
    } else {
      var ul = h("ul", { class: "plain-list" });
      leases.forEach(function (l) {
        ul.appendChild(h("li", {}, [(l.kind || "?") + " · " + (l.tree || "?") + " · " + (l.since || "?")]));
      });
      c.appendChild(ul);
    }
    return c;
  }

  function renderCleanupCard(cleanup) {
    cleanup = cleanup || {};
    var c = card(t("system.cleanup.title"), renderBadge(get(cleanup, "_meta.state", null), isStaleGlobal()));
    c.appendChild(kv("system.cleanup.last_run", cleanup.last_run));
    c.appendChild(kv("system.cleanup.removed", cleanup.removed_logged));
    c.appendChild(kv("system.cleanup.gb", cleanup.gb_logged));
    return c;
  }

  function renderBackupsCard(b) {
    b = b || {};
    var c = card(t("system.backups.title"), renderBadge(get(b, "_meta.state", null), isStaleGlobal()));
    c.appendChild(kv("system.backups.last_local", b.last_local_archive));
    c.appendChild(kv("system.backups.offsite_verified", b.offsite_verified));
    c.appendChild(kv("system.backups.offsite_real_remote", b.offsite_is_real_remote));
    c.appendChild(kv("system.backups.restore_drill", b.restore_drill));
    if (b.note) c.appendChild(h("p", { class: "note" }, [b.note]));
    return c;
  }

  function renderCodeCard(code) {
    code = code || {};
    var c = card(t("system.code.title"), renderBadge(get(code, "_meta.state", null), isStaleGlobal()));
    c.appendChild(kv("system.code.production_commit", code.production_commit));
    c.appendChild(kv("system.code.sync_result", code.sync_result));
    c.appendChild(kv("system.code.deployment_acceptance", code.deployment_acceptance));
    c.appendChild(kv("system.code.approved_release", code.approved_release));
    return c;
  }

  function renderServicesCard(services) {
    services = services || {};
    var c = card(t("system.services.title"), renderBadge(get(services, "_meta.state", null), isStaleGlobal()));
    var items = services.items;
    if (items === null || items === undefined) {
      c.appendChild(h("p", {}, [t("common.not_measured")]));
    } else if (!Array.isArray(items) || items.length === 0) {
      c.appendChild(h("p", {}, [t("common.none")]));
    } else {
      var ul = h("ul", { class: "plain-list" });
      items.forEach(function (s) {
        ul.appendChild(h("li", {}, [(s.name || "?") + " — " + (s.running ? t("common.yes") : t("common.no"))]));
      });
      c.appendChild(ul);
    }
    return c;
  }

  function renderIncidentsCard(inc) {
    inc = inc || {};
    var c = card(t("system.incidents.title"), renderBadge(get(inc, "_meta.state", null), isStaleGlobal()));
    c.appendChild(renderListField("system.incidents.title", inc.open, function (it) {
      return (it.event || "?") + " · " + (it.since || "?");
    }));
    return c;
  }

  function renderKillSwitchCard(ks, derisk) {
    var c = card(t("system.kill_switch.title"));
    var stale = isStaleGlobal();
    var label, cls;
    if (ks === true) { label = t("system.kill_switch.on"); cls = "badge--alert"; }
    else if (ks === false && !stale) { label = t("system.kill_switch.off"); cls = "badge--ok"; }
    else if (ks === false) { label = t("system.kill_switch.off") + " · " + t("vocab.health.STALE"); cls = "badge--warn"; }
    else { label = t("system.kill_switch.unknown"); cls = "badge--unknown"; }
    c.appendChild(h("span", { class: "badge " + cls }, [label]));
    var dl, dc;
    if (derisk === true) { dl = t("system.derisk.on"); dc = "badge--warn"; }
    else if (derisk === false) { dl = t("system.derisk.off"); dc = stale ? "badge--warn" : "badge--ok"; }
    else { dl = t("system.derisk.unknown"); dc = "badge--unknown"; }
    c.appendChild(h("div", { class: "kv-row" }, [h("span", { class: "k" }, [t("system.derisk.title")]),
      h("span", { class: "badge " + dc }, [dl])]));
    return c;
  }

  // ── top-level render ───────────────────────────────────────────────────────────────────
  function renderArea(area) {
    var container = document.getElementById("area-" + area);
    if (!container) return;
    clear(container);
    if (fetchFailed || !currentModel) {
      container.appendChild(h("p", { class: "empty-note" }, [t("status.no_connection")]));
      return;
    }
    if (area === "overview") renderOverview(container, currentModel);
    else if (area === "capital") renderCapital(container, currentModel);
    else if (area === "studio") renderStudio(container, currentModel);
    else if (area === "decisions") renderDecisions(container, currentModel);
    else if (area === "system") renderSystem(container, currentModel);
  }

  function renderAll() {
    renderHeaderStaticText();
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
