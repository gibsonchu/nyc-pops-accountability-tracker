"use strict";
const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const REPO = "https://github.com/gibsonchu/nyc-pops-accountability-tracker";
const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "amount not stated" : "$" + n.toLocaleString("en-US"));
const when = (e) => `${MONTHS[e.m - 1]} ${e.y}`;
const title = (s) => String(s || "").toLowerCase().replace(/(^|[\s(\/-])([a-z])/g, (m, a, b) => a + b.toUpperCase());
const tagCat = (c) => `<span class="tag">${esc(c)}</span>`;
const AUDIT_LABEL = { no: "Not fully compliant (audit: No)", yes: "Full compliance (audit: Yes)", construction: "Marked “Construction” (not a compliance finding)", "": "Not in the audit" };

let POPS = [], S = null, map = null, layer = null;

async function load() {
  const [p, s] = await Promise.all([fetch("data/pops.json").then((r) => r.json()), fetch("data/summary.json").then((r) => r.json())]);
  POPS = p; S = s;
  $("#prelim").innerHTML = `<b>Preliminary.</b> ${esc(S.n_open_review)} automated matches are awaiting human review. Data through the ${esc(S.latest_bulletin)} bulletin.`;
  $("#disclaimer-foot").textContent = S.disclaimer;
  route();
}

function state() { // hash query: #/?q=..&boro=..&audit=..&rec=1
  const [, qs = ""] = location.hash.split("?");
  const p = new URLSearchParams(qs);
  return { q: p.get("q") || "", boro: p.get("boro") || "", audit: p.get("audit") || "", rec: p.get("rec") === "1" };
}
function setState(patch) {
  const s = { ...state(), ...patch }, p = new URLSearchParams();
  if (s.q) p.set("q", s.q); if (s.boro) p.set("boro", s.boro); if (s.audit) p.set("audit", s.audit); if (s.rec) p.set("rec", "1");
  history.replaceState(null, "", "#/" + (p.toString() ? "?" + p : ""));
}

function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const path = h.split("?")[0];
  document.querySelectorAll("nav a").forEach((a) => a.classList.remove("on"));
  const main = $("#main");
  let page = "home";
  if (path.startsWith("/pops/")) { page = "home"; detail(decodeURIComponent(path.slice(6))); }
  else if (path === "/audit") { page = "audit"; auditPage(); }
  else if (path === "/analysis") { page = "analysis"; mdPage("data/analysis.md"); }
  else if (path === "/method") { page = "method"; mdPage("data/METHODOLOGY.md"); }
  else if (path === "/data") { page = "data"; dataPage(); }
  else { home(); }
  const el = document.querySelector(`nav a[data-nav="${page}"]`); if (el) el.classList.add("on");
  if (!(path === "/" || path === "")) window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

/* ---------------------------------------------------------------- home */
function home() {
  const r = S.res;
  $("#main").innerHTML = `
  <h1>Are NYC’s private public spaces actually public?</h1>
  <p class="lede">New York has allowed developers to build extra private floor area in exchange for providing publicly accessible space. In 2017 the City Comptroller inspected ${esc(r.audit_status_counts.No + r.audit_status_counts.Yes + r.audit_status_counts.Construction)} of these spaces and found that <b>${esc(r.audit_status_counts.No)} failed to provide required public amenities</b>. The information about what happened next is scattered across PDFs, databases and government sites. This tracker puts it in one place.</p>
  <div class="callout" role="note"><b>What this can and cannot tell you</b>${esc(S.disclaimer)} Absence from the bulletins is not evidence of compliance.</div>
  <div class="cards">
    <div class="card"><div class="n">${POPS.length}</div><div class="l">POPS in the city’s dataset</div><div class="s">${POPS.filter((p) => p.boro === "Manhattan").length} in Manhattan</div></div>
    <div class="card"><div class="n">${esc(r.tier_A_pops)}</div><div class="l">with a confirmed DOB bulletin record</div><div class="s">the bulletin text names the POPS and the property matches with high confidence</div></div>
    <div class="card"><div class="n">${esc(r.tier_A_actions)}</div><div class="l">confirmed enforcement actions</div><div class="s">${esc(S.res.span.replace(" to ", " – "))}; ${esc(r.n_actions_all.toLocaleString())} bulletin highlights read</div></div>
    <div class="card"><div class="n">$${esc(r.tier_A_penalty_total.toLocaleString())}</div><div class="l">penalties identified</div><div class="s">median $${esc(r.tierA_penalty_median.toLocaleString())}; only what the bulletins state</div></div>
  </div>
  <h2 id="explore">Find a POPS</h2>
  <div class="filters">
    <div><label for="q">Search address, building name or POPS ID</label><input id="q" type="search" placeholder="e.g. 776 Sixth Avenue, Trump Tower, M050107" autocomplete="off"></div>
    <div><label for="boro">Borough</label><select id="boro"><option value="">All</option>${["Manhattan","Brooklyn","Queens","Bronx","Staten Island"].map((b) => `<option>${b}</option>`).join("")}</select></div>
    <div><label for="audit">2017 audit result</label><select id="audit"><option value="">Any</option><option value="no">Not fully compliant (No)</option><option value="yes">Full compliance (Yes)</option><option value="construction">Marked Construction</option><option value="none">Not in the audit</option></select></div>
    <div><label class="check" style="margin:0"><input id="rec" type="checkbox"> <span>Only POPS with a DOB record</span></label></div>
  </div>
  <div id="map" role="img" aria-label="Map of privately owned public spaces, coloured by whether a DOB bulletin record exists"></div>
  <p class="legend"><span><i class="dot" style="background:var(--confirmed)"></i>Confirmed DOB bulletin record</span><span><i class="dot" style="background:var(--pending)"></i>Record awaiting review, or another DOB action at the property</span><span><i class="dot" style="background:var(--none)"></i>No bulletin record (this is <b>not</b> evidence of compliance)</span></p>
  <div class="count" id="count" aria-live="polite"></div>
  <div class="tablewrap"><table><caption class="muted small" style="text-align:left;padding:0 0 6px">Select a row to open the property page</caption><thead><tr><th>Address</th><th>Building</th><th>Borough</th><th class="num">Built</th><th>2017 audit</th><th class="num">DOB records</th></tr></thead><tbody id="rows"></tbody></table></div>
  <h2>Latest confirmed enforcement</h2>
  <ul class="feed" id="feed"></ul>
  <p class="muted small" style="margin-top:10px">The most recent bulletin that mentions a POPS is <b>${esc(monthName(r.last_pops_wording_bulletin))}</b>; none of the ${esc(r.bulletins_after_last_pops_wording)} bulletins since mention one. The data cannot show whether DOB stopped enforcing POPS rules or stopped highlighting them.</p>
  <h2>Confirmed actions by bulletin year</h2>
  <div id="chart"></div>
  <p class="muted small">Bulletin counts differ by year: ${esc(S.missing_months.join(", "))} are missing from DOB’s index, and the latest year is partial. Bars show only what DOB chose to publish.</p>`;
  const st = state();
  $("#q").value = st.q; $("#boro").value = st.boro; $("#audit").value = st.audit; $("#rec").checked = st.rec;
  ["q", "boro", "audit", "rec"].forEach((id) => $("#" + id).addEventListener("input", () => { setState({ q: $("#q").value, boro: $("#boro").value, audit: $("#audit").value, rec: $("#rec").checked }); applyFilters(); }));
  feed(); chart(); initMap(); applyFilters();
}
function monthName(ym) { const [y, m] = String(ym).split("-"); return `${MONTHS[+m - 1]} ${y}`; }

function auditKey(p) { return p.audit.inspected ? (p.audit.status || "unknown") : "none"; }
function applyFilters() {
  const s = { q: $("#q").value.trim().toLowerCase(), boro: $("#boro").value, audit: $("#audit").value, rec: $("#rec").checked };
  const list = POPS.filter((p) =>
    (!s.q || (p.addr + " " + p.name + " " + p.id).toLowerCase().includes(s.q)) && (!s.boro || p.boro === s.boro) &&
    (!s.audit || auditKey(p) === s.audit) && (!s.rec || p.n_conf + p.n_pend + p.n_prop > 0));
  $("#count").textContent = `${list.length} of ${POPS.length} POPS`;
  const shown = list.slice(0, 150);
  $("#rows").innerHTML = shown.map((p) => `<tr><td><a href="#/pops/${encodeURIComponent(p.id)}">${esc(title(p.addr.split(",")[0]))}</a></td><td>${esc(p.name)}</td><td>${esc(p.boro)}</td><td class="num">${esc(p.year) || "–"}</td><td>${esc(AUDIT_LABEL[p.audit.inspected ? p.audit.status : ""].split(" (")[0])}</td><td class="num">${p.n_conf ? `<b>${p.n_conf}</b>` : "0"}${p.n_pend + p.n_prop ? ` <span class="muted small">+${p.n_pend + p.n_prop}</span>` : ""}</td></tr>`).join("") +
    (list.length > shown.length ? `<tr><td colspan="6" class="muted">Showing the first ${shown.length}. Narrow the search to see the rest.</td></tr>` : "") ||
    `<tr><td colspan="6" class="muted">No POPS match these filters.</td></tr>`;
  drawMarkers(list);
}
function feed() {
  const items = [];
  POPS.forEach((p) => p.e.filter((e) => e.tier === "confirmed").forEach((e) => items.push({ p, e })));
  items.sort((a, b) => b.e.y - a.e.y || b.e.m - a.e.m);
  $("#feed").innerHTML = items.slice(0, 8).map(({ p, e }) => `<li><span class="when">${esc(when(e))}</span> · <a href="#/pops/${encodeURIComponent(p.id)}">${esc(title(p.addr.split(",")[0]))}</a> · <span class="pen">${esc(money(e.pen))}</span><div>${e.cat.map(tagCat).join("")}</div><div class="small muted">${esc(e.text.length > 230 ? e.text.slice(0, 230) + "…" : e.text)}</div></li>`).join("");
}
function chart() {
  const yrs = S.by_year.filter((y) => y.year >= 2018), max = Math.max(1, ...yrs.map((y) => y.tierA_actions));
  $("#chart").innerHTML = `<div class="bars" role="img" aria-label="Confirmed POPS enforcement actions per bulletin year">${yrs.map((y) => `<div class="bar ${y.tierA_actions ? "" : "zero"}" title="${y.year}: ${y.tierA_actions} confirmed actions in ${y.bulletins} bulletins"><span>${y.tierA_actions}</span><i style="height:${Math.max(2, 100 * y.tierA_actions / max)}%"></i><span>${y.year}</span></div>`).join("")}</div>`;
}

/* ---------------------------------------------------------------- map */
function initMap() {
  if (map) { map.remove(); map = null; }
  if (typeof L === "undefined") { $("#map").innerHTML = '<p class="muted" style="padding:16px">The map library could not be loaded. The list below still works.</p>'; return; }
  map = L.map("map", { scrollWheelZoom: false }).setView([40.7527, -73.9772], 12);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors &copy; CARTO' }).addTo(map);
  layer = L.layerGroup().addTo(map);
}
function drawMarkers(list) {
  if (!map) return;
  layer.clearLayers();
  const css = getComputedStyle(document.documentElement);
  const col = (p) => css.getPropertyValue(p.n_conf ? "--confirmed" : (p.n_pend + p.n_prop ? "--pending" : "--none")).trim();
  list.filter((p) => p.lat != null && p.lon != null).forEach((p) => {
    const m = L.circleMarker([p.lat, p.lon], { radius: p.n_conf ? 8 : 6, color: "#fff", weight: 1, fillColor: col(p), fillOpacity: .92 }).addTo(layer);
    m.bindTooltip(`${title(p.addr.split(",")[0])}${p.name ? " — " + p.name : ""}`);
    m.on("click", () => { location.hash = "#/pops/" + encodeURIComponent(p.id); });
  });
}

/* ---------------------------------------------------------------- detail */
function detail(id) {
  const p = POPS.find((x) => x.id === id);
  if (!p) { $("#main").innerHTML = `<p>No POPS with ID ${esc(id)}. <a href="#/">Back to search</a></p>`; return; }
  const a = p.audit, groups = [["confirmed", "Confirmed POPS enforcement", "The bulletin text refers to the POPS and the property matches this POPS with high confidence."],
    ["pending", "Probable, awaiting human review", "The bulletin text refers to a POPS, but the link to this property is not yet high-confidence."],
    ["property_only", "Other DOB actions at this property", "This property contains a POPS, but the paragraph does not mention the public space. It may concern the building or a construction site, not the POPS."]];
  const amen = (s) => s ? `<div class="chips">${s.split(";").map((x) => `<span>${esc(x.trim())}</span>`).join("")}</div>` : '<span class="muted">Not listed in the city’s dataset</span>';
  const ev = groups.map(([t, h, note]) => { const es = p.e.filter((e) => e.tier === t); return es.length ? `<h3 style="margin-top:22px">${h} <span class="muted">(${es.length})</span></h3><p class="muted small">${note}</p>` + es.map((e) => `
    <article class="event ${t}"><div><span class="when">${esc(when(e))}</span>${e.dup ? ' <span class="tag">possible repeat of an earlier entry</span>' : ""}</div>
    <div style="margin-top:6px">${e.cat.map(tagCat).join("")}</div>
    <blockquote>${esc(e.text)}</blockquote>
    <div class="meta"><span class="pen">Penalty: ${esc(money(e.pen))}</span>${e.who ? ` · Issued to: ${esc(e.who)}` : ""}<br>Source: <a href="${esc(e.pdf)}" rel="noopener">NYC Dept. of Buildings Monthly Enforcement Action Bulletin, ${esc(when(e))}, page ${e.page}</a><br>Matched by ${esc(e.how)}. Categories are automated labels; the quoted text is DOB’s own.</div></article>`).join("") : ""; }).join("");
  $("#main").innerHTML = `
  <p class="crumb"><a href="#/">← All POPS</a></p>
  <h1>${esc(title(p.addr.split(",")[0]))}</h1>
  <p class="lede" style="margin-top:0">${esc(p.name)}${p.name ? " · " : ""}${esc(p.boro)} · ${esc(p.type || "POPS")}${p.year ? " · completed " + esc(p.year) : ""}</p>
  <div class="two">
   <div>
    <h2 style="margin-top:8px">POPS requirements <span class="muted small">(NYC Dept. of City Planning)</span></h2>
    <div class="box"><dl class="req">
      <dt>Required hours</dt><dd>${esc(p.hours) || '<span class="muted">Not listed</span>'}</dd>
      <dt>Required size</dt><dd>${esc(p.size) || '<span class="muted">Not listed</span>'}</dd>
      <dt>Required amenities</dt><dd>${amen(p.amen)}</dd>
      <dt>Other required</dt><dd>${amen(p.other)}</dd>
      <dt>Permitted amenities</dt><dd>${amen(p.perm)}</dd>
      <dt>Accessibility</dt><dd>${esc(p.access) || '<span class="muted">Not listed</span>'}</dd>
      <dt>Developer</dt><dd>${esc(p.dev) || '<span class="muted">Not listed</span>'}</dd>
      <dt>Identifiers</dt><dd class="small">${esc(p.id)} · BBL ${esc(p.bbl) || "n/a"} · BIN ${esc(p.bin) || "n/a"}</dd></dl></div>
    <h2>Enforcement history</h2>
    ${ev || `<div class="box"><b>No record in DOB’s Monthly Enforcement Action Bulletins.</b> That is not a finding that this POPS is compliant.</div>`}
    <div class="callout" role="note" style="margin-top:22px">${esc(S.disclaimer)}</div>
   </div>
   <aside>
    <h2 style="margin-top:8px">2017 Comptroller audit</h2>
    <div class="box">${a.inspected ? `<b>${esc(AUDIT_LABEL[a.status] || a.status)}</b><p class="small muted">Status exactly as printed in audit SR16-102A (April 2017), based on visits in 2016. “Construction” is not evidence of compliance.</p>${a.findings ? `<p class="small"><b>Named in the report text:</b> ${esc(a.findings)}</p>` : '<p class="small muted">The appendix gives no per-location detail for this address.</p>'}` : `<b>Not in the audit</b><p class="small muted">We could not link this POPS to a location the auditors visited (many were created later, or the audit’s address could not be matched). This says nothing about compliance.</p>`}</div>
    <h2>Location</h2>
    <div class="box small">${esc(p.addr)}${p.lat ? `<br><a href="https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=18/${p.lat}/${p.lon}" rel="noopener">Open on OpenStreetMap</a>` : ""}${p.flags.length ? `<br><span class="muted">Data notes: ${esc(p.flags.join(", ").replace(/_/g, " "))}</span>` : ""}</div>
   </aside></div>`;
}

/* ---------------------------------------------------------------- other pages */
function auditPage() {
  const META = { no: ["Audit: not fully compliant (No)", "no", 0], yes: ["Audit: full compliance (Yes)", "yes", 1],
    construction: ["Audit: marked \u201CConstruction\u201D", "construction", 2], not_in_audit: ["Not in the audit", "none", 3] };
  const rows = S.audit.filter((g) => META[g.audit_group]).map((g) => ({ ...g, label: META[g.audit_group][0], key: META[g.audit_group][1], ord: META[g.audit_group][2] })).sort((x, y) => x.ord - y.ord);
  const r = S.res;
  $("#main").innerHTML = `
  <h1>What happened after the 2017 audit?</h1>
  <p class="lede">The Comptroller’s audit (SR16-102A, 18 April 2017) visited ${r.audit_status_counts.No + r.audit_status_counts.Yes + r.audit_status_counts.Construction} POPS in 2016 and listed each with a compliance status. We linked those locations to today’s POPS list and checked which later appear in DOB’s enforcement bulletins.</p>
  <div class="callout" role="note"><b>Read carefully</b>Bulletins are selective, so a POPS that never appears may still have problems, or may have been fixed. All bulletins (from December 2017) come after the audit, so this shows what DOB later chose to highlight, not cause and effect.</div>
  <div class="tablewrap"><table><thead><tr><th>Audit result</th><th class="num">POPS</th><th class="num">With a confirmed DOB record</th><th class="num">Share</th><th></th></tr></thead><tbody>${rows.map((g) => `<tr><td>${esc(g.label)}</td><td class="num">${g.pops}</td><td class="num">${g.tierA}</td><td class="num">${g.tierA_pct}%</td><td><a href="#/?audit=${g.key}">Browse</a></td></tr>`).join("")}</tbody></table></div>
  <ul>
   <li>Of the <b>${r.q10_no_n}</b> POPS the audit marked not fully compliant, <b>${r.q10_no_A}</b> (${(100 * r.q10_no_A / r.q10_no_n).toFixed(1)}%) later appear in a confirmed bulletin action, versus ${r.q10_yes_A} of ${r.q10_yes_n} (${(100 * r.q10_yes_A / r.q10_yes_n).toFixed(1)}%) of those marked compliant.</li>
   <li><b>${r.q10_no_n - r.q10_no_A} of ${r.q10_no_n}</b> audit-flagged POPS never appear in a confirmed bulletin action. That is not evidence they were fixed, and not evidence they were not.</li>
   <li>${r.audit_unlinked_rows} audit row could not be linked to a current POPS and is left unlinked rather than guessed.</li></ul>
  <p class="muted small">Counts as of the latest run; still preliminary. See <a href="#/analysis">the full analysis</a> and <a href="#/method">methodology</a>.</p>`;
}
async function mdPage(url) {
  $("#main").innerHTML = '<p class="muted">Loading…</p>';
  const t = await fetch(url).then((r) => r.text());
  $("#main").innerHTML = `<div class="md">${typeof marked !== "undefined" ? marked.parse(t) : "<pre>" + esc(t) + "</pre>"}</div><p><a href="${REPO}/blob/main/${url.includes("METHOD") ? "METHODOLOGY.md" : "reports/analysis.md"}">View on GitHub</a></p>`;
}
function dataPage() {
  const files = [["pops_enforcement.csv", "POPS-related enforcement records (main dataset), with match method/confidence and review status"], ["pops_accountability.csv", "One row per POPS: requirements, 2017 audit result, enforcement counts"], ["pops_master.csv", "Normalised POPS list (all city fields plus join keys and quality flags)"], ["comptroller_2017_audit.csv", "The audit’s 333 locations linked to the POPS list"], ["enforcement_actions_all.csv", "Every parsed bulletin highlight (2,600+), POPS or not"], ["pops_enforcement.json", "Main dataset as JSON"]];
  $("#main").innerHTML = `<h1>Data</h1><p class="lede">Everything on this site is generated from public records by an open pipeline that re-checks DOB’s bulletin page every week.</p>
  <div class="callout" role="note"><b>Before you use the data</b>${esc(S.disclaimer)} Read the <a href="#/method">methodology</a> and the <a href="data/data_quality_report.md">data-quality report</a>. Rows with <code>manual_review_status = needs_review</code> are unconfirmed.</div>
  <ul class="feed">${files.map(([f, d]) => `<li><a href="data/download/${f}" download><b>${f}</b></a><div class="small muted">${esc(d)}</div></li>`).join("")}</ul>
  <p>Code, raw PDFs, registry and review queue: <a href="${REPO}">${REPO.replace("https://", "")}</a>. Data generated ${esc(S.generated)}.</p>`;
}

load().catch((e) => { $("#main").innerHTML = `<p>Could not load the data (${esc(e.message)}). <a href="${REPO}">See the repository</a>.</p>`; });
