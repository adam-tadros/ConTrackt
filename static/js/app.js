"use strict";

/* ===== State ===== */
const state = {
  contracts: [], documents: [], alerts: [],
  sortK: "end", sortDir: 1,
  pendingUpload: null,   // { document, fields } during an upload
  docScope: "current", docQuery: "",
};

/* ===== Helpers ===== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (n) => n == null || n === "" ? "—" : "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
function fmt(d) {
  if (!d) return "—";
  const p = String(d).slice(0, 10).split("-").map(Number);
  if (p.length < 3 || !p[0]) return String(d);
  return new Date(p[0], p[1] - 1, p[2]).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((body && body.error) || res.statusText);
  return body;
}
let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = "toast"), 3400);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ===== Derived status ===== */
const dept = (c) => c.cat || "Uncategorized";
const contractStatus = (c) => ({ active: "Active", expiring: "Expiring", expired: "Expired" }[c.status] || "Unknown");
function insStatus(c) { const d = c.days_to_insurance; if (d == null) return "Unknown"; return d < 0 ? "Lapsed" : d <= 30 ? "Expiring" : "Current"; }
function poStatus(c) { const d = c.days_to_po_end; if (d == null) return "Open"; return d < 0 ? "Closed" : d <= 45 ? "Closing" : "Open"; }
const TAG = { Active: "t-green", Expiring: "t-amber", Expired: "t-red", Unknown: "t-slate", Current: "t-green", Lapsed: "t-red", Open: "t-green", Closing: "t-amber", Closed: "t-slate" };
const docVendor = (cid) => { const c = state.contracts.find((x) => x.id === cid); return c ? c.vendor : ""; };

/* ===== Navigation ===== */
function showView(v, btn) {
  closeDetail();
  $$(".view").forEach((e) => e.classList.remove("on"));
  $("#v-" + v).classList.add("on");
  $$(".sidebar nav button").forEach((b) => b.classList.remove("on"));
  if (btn) btn.classList.add("on");
  else { const nb = $(`.sidebar nav button[onclick*="'${v}'"]`); if (nb) nb.classList.add("on"); }
  // Hero belongs to the dashboard only
  $("#hero").style.display = v === "dashboard" ? "" : "none";
  if (v === "upload") resetUpload();
  if (v === "alerts" && !state.alertsNotified) { state.alertsNotified = true; sendAlertEmails(true); }
}

/* ===== Data load ===== */
async function loadAll() {
  try {
    const [contracts, documents, alerts] = await Promise.all([
      api("/api/contracts"), api("/api/documents"), api("/api/alerts"),
    ]);
    state.contracts = contracts; state.documents = documents; state.alerts = alerts;
    buildDeptFilter(); buildCards(); buildHead(); render();
    buildAlerts(); buildDocHub();
  } catch (e) {
    $("#rows").innerHTML = `<tr><td colspan="7" class="empty">Could not reach the backend.<br><span class="mini">${esc(e.message)}</span></td></tr>`;
    toast("Failed to load: " + e.message, true);
  }
}

/* ===== Hero + cards ===== */
function compactUSD(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return "$" + (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return "$" + Math.round(n / 1e3) + "k";
  return "$" + n.toLocaleString();
}
function buildCards() {
  const C = state.contracts;
  const totalVal = C.reduce((s, c) => s + (Number(c.value) || 0), 0);
  const cells = [
    { n: C.length, l: "Contracts", sub: compactUSD(totalVal) + " total value", f: () => resetF() },
    { n: C.filter((c) => contractStatus(c) === "Active").length, l: "Active", dot: "var(--green)", f: () => setStatus("Active") },
    { n: C.filter((c) => contractStatus(c) === "Expiring").length, l: "Expiring ≤30d", dot: "var(--amber)", f: () => setStatus("Expiring") },
    { n: C.filter((c) => contractStatus(c) === "Expired").length, l: "Expired", dot: "var(--red)", red: true, f: () => setStatus("Expired") },
    { n: C.filter((c) => ["Expiring", "Lapsed"].includes(insStatus(c))).length, l: "COI issues", dot: "var(--crim)", red: true, f: () => setIns() },
  ];
  $("#cards").innerHTML = cells.map((c, i) =>
    `<div class="stat" onclick="_cardf(${i})">
      <div class="n ${c.red ? "red" : ""}">${c.n}</div>
      <div class="l">${c.dot ? `<span class="dot" style="background:${c.dot}"></span>` : ""}${c.l}</div>
      ${c.sub ? `<div class="sub">${c.sub}</div>` : ""}
    </div>`).join("");
  window.__cardf = cells.map((c) => c.f);
}
window._cardf = (i) => window.__cardf[i]();
function setStatus(s) { resetF(); $("#fStatus").value = s; render(); }
function setIns() { resetF(); $("#fIns").value = "__any"; render(); }
function resetF() { $("#search").value = ""; $("#fDept").value = ""; $("#fStatus").value = ""; $("#fIns").value = ""; render(); }

/* ===== Contracts table ===== */
const COLS = [{ k: "vendor", t: "Vendor / Scope" }, { k: "dept", t: "Category" }, { k: "end", t: "Contract ends" },
{ k: "status", t: "Status" }, { k: "ins", t: "Insurance (COI)" }, { k: "poEnd", t: "PO" }, { k: "value", t: "Value" }];
function buildHead() {
  $("#head").innerHTML = COLS.map((c) => {
    const s = c.k === state.sortK ? "sorted" : "";
    const ar = c.k === state.sortK ? (state.sortDir > 0 ? "▲" : "▼") : "▲";
    return `<th class="${s}" onclick="sortBy('${c.k}')">${c.t} <span class="arr">${ar}</span></th>`;
  }).join("");
}
function sortBy(k) { if (state.sortK === k) state.sortDir *= -1; else { state.sortK = k; state.sortDir = 1; } buildHead(); render(); }
function sortVal(c, k) {
  if (k === "vendor") return (c.vendor || "").toLowerCase();
  if (k === "dept") return dept(c).toLowerCase();
  if (k === "status") return { Expired: 0, Expiring: 1, Active: 2, Unknown: 3 }[contractStatus(c)];
  if (k === "ins") return c.ins || "9999";
  if (k === "value") return c.value || 0;
  if (k === "end" || k === "poEnd") return c[k] || "9999";
  return c[k];
}
function render() {
  const q = $("#search").value.toLowerCase();
  const fd = $("#fDept").value, fs = $("#fStatus").value, fi = $("#fIns").value;
  let rows = state.contracts.filter((c) => {
    if (fd && dept(c) !== fd) return false;
    if (fs && contractStatus(c) !== fs) return false;
    if (fi === "__any" && !["Expiring", "Lapsed"].includes(insStatus(c))) return false;
    if (fi && fi !== "__any" && insStatus(c) !== fi) return false;
    if (q && !((c.vendor || "") + " " + (c.scope || "") + " " + (c.po || "") + " " + (c.poly || "")).toLowerCase().includes(q)) return false;
    return true;
  });
  rows.sort((a, b) => { const x = sortVal(a, state.sortK), y = sortVal(b, state.sortK); return (x > y ? 1 : x < y ? -1 : 0) * state.sortDir; });
  const dtxt = (d) => d == null ? "" : d < 0 ? `${-d}d ago` : `in ${d}d`;
  $("#rows").innerHTML = rows.map((c) => {
    const st = contractStatus(c), is = insStatus(c), ps = poStatus(c);
    return `<tr class="row" onclick="openDetail('${esc(c.id)}')">
      <td><div class="vendor">${esc(c.vendor || "—")}</div><div class="scope">${esc(c.scope || "")}</div></td>
      <td>${esc(dept(c))}</td>
      <td>${fmt(c.end)}<div class="days">${dtxt(c.days_to_end)}</div></td>
      <td><span class="tag ${TAG[st]}">${st === "Expiring" ? "Expiring soon" : st}</span></td>
      <td>${fmt(c.ins)}</td>
      <td>${esc(c.po || "—")}</td>
      <td>${usd(c.value)}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="empty">No contracts match these filters.</td></tr>`;
  $("#count").textContent = `${rows.length} of ${state.contracts.length} contracts`;
}
function buildDeptFilter() {
  const sel = $("#fDept"), cur = sel.value;
  const cats = [...new Set(state.contracts.map(dept))].sort();
  sel.innerHTML = `<option value="">All categories</option>` + cats.map((d) => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
  sel.value = cur;
}

/* ===== Contract detail overlay (real fields only) ===== */
async function openDetail(id) {
  let c;
  try { c = await api("/api/contracts/" + id); } catch (e) { return toast(e.message, true); }
  const st = contractStatus(c), is = insStatus(c), ps = poStatus(c);
  const docs = c.document_records || [];
  const agreement = docs.find((d) => d.type !== "coi");
  const coi = docs.find((d) => d.type === "coi");
  const pill = (cls, txt) => `<span class="pill ${cls}">${esc(txt)}</span>`;
  const cCls = st === "Active" ? "ok" : st === "Expiring" ? "warn" : "bad";
  const iCls = is === "Current" ? "ok" : is === "Expiring" ? "warn" : is === "Unknown" ? "warn" : "bad";
  const pCls = ps === "Open" ? "ok" : ps === "Closing" ? "warn" : "bad";

  const rec = [];
  if (st === "Expired") rec.push("Cancel or issue a new agreement — contract is expired.");
  else if (st === "Expiring") rec.push(`Renew or extend the agreement before ${fmt(c.end)}.`);
  if (is === "Lapsed") rec.push("Request a current Certificate of Insurance from the vendor.");
  else if (is === "Expiring") rec.push(`Request an updated COI before ${fmt(c.ins)} to avoid a lapse.`);
  if (String(c.addl).toLowerCase() !== "yes") rec.push("Obtain an additional-insured endorsement naming the District.");
  if (ps === "Closed") rec.push("Confirm a new purchase order for the current fiscal year.");
  else if (ps === "Closing") rec.push(`Renew the purchase order before ${fmt(c.poEnd)}.`);
  if (!rec.length) rec.push("No action needed — contract, insurance, and PO are all current.");

  const docBtn = (d, label) => d
    ? `<button class="btn ghost" onclick="openDoc('${esc(d.id)}')">${label}</button>`
    : `<button class="btn ghost" disabled title="No document on file">${label}</button>`;

  const owner = c.contract_head || "—";
  const ownerEmail = c.contract_head_email || "";

  const kv = (k, v) => `<div class="k">${k}</div><div>${v}</div>`;
  $("#drawer").innerHTML = `
    <div class="dh">
      <button class="close" onclick="closeDetail()">×</button>
      <div class="m">🏢 Foothill–De Anza CCD · ${esc(dept(c))}</div>
      <h2>${esc(c.vendor || "Contract")}</h2>
      <div class="m">${esc(c.scope || "")}</div>
    </div>
    <div class="body">
      <div class="pills" style="margin-bottom:14px">
        ${pill(cCls, st === "Expiring" ? "Expiring soon" : st)}
        ${pill(iCls, is === "Current" ? "COI current" : is === "Lapsed" ? "COI lapsed" : is === "Expiring" ? "COI expiring" : "COI unknown")}
        ${c.po ? pill(pCls, c.po) : ""}
        ${String(c.addl).toLowerCase() === "yes" ? "" : pill("warn", "No add’l insured")}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
        ${docBtn(agreement, "📄 Contract")}
        ${docBtn(coi, "🛡 COI")}
        <button class="btn" onclick="closeDetail();document.getElementById('navNotifBtn').click()">Alerts</button>
      </div>

      <div class="aibox"><div class="lab">✨ AI scope summary</div><p>${esc(c.summary || "No summary extracted.")}</p></div>

      <div class="sec">Key facts</div>
      <div class="kv">
        ${kv("Value", usd(c.value))}
        ${kv("Term", fmt(c.start) + " → " + fmt(c.end))}
        ${kv("PO number", esc(c.po || "—"))}
        ${kv("PO ends", fmt(c.poEnd))}
        ${kv("Campus", esc(c.college || "—"))}
        ${kv("Insurance expiry", fmt(c.ins))}
        ${kv("Additional insured", esc(c.addl || "—"))}
      </div>

      <div class="sec">Lifecycle tracking</div>
      <div class="track">
        <div class="track-row"><div><div class="tt">Contract term</div><div class="ts">Ends ${fmt(c.end)}</div></div>${pill(cCls, st === "Expiring" ? "Expiring soon" : st)}</div>
        <div class="track-row"><div><div class="tt">Insurance / COI</div><div class="ts">${is === "Lapsed" ? "Certificate expired " + fmt(c.ins) : "Valid through " + fmt(c.ins)}</div></div>${pill(iCls, is)}</div>
        <div class="track-row"><div><div class="tt">Purchase order</div><div class="ts">Ends ${fmt(c.poEnd)}</div></div>${c.po ? pill(pCls, c.po) : pill("warn", "No PO")}</div>
      </div>

      <div class="sec">Documents (${docs.length})</div>
      ${docs.length ? docs.map((d) => `<div class="track-row"><div><div class="tt">${d.type === "coi" ? "🛡 Certificate of Insurance" : "📄 " + (d.type || "Document")}</div><div class="ts">${esc(d.filename || "")}</div></div><button class="btn ghost" onclick="openDoc('${esc(d.id)}')">Open</button></div>`).join("") : `<div class="mini">No documents linked.</div>`}

      <div class="sec">Recommended actions</div>
      <ul class="rec-list">${rec.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>

      <div class="sec">Contract head</div>
      <div class="owner-name">👤 ${esc(owner)}</div>
      ${ownerEmail ? `<a class="owner-mail" href="mailto:${esc(ownerEmail)}">✉ ${esc(ownerEmail)}</a>` : `<div class="mini" style="margin-top:8px">No email on file — no alert email is sent.</div>`}
    </div>`;
  $("#ovl").classList.add("show");
  $("#drawer").classList.add("show");
  $("#drawer").scrollTop = 0;
}
function closeDetail() { const d = $("#drawer"), o = $("#ovl"); if (d) d.classList.remove("show"); if (o) o.classList.remove("show"); }

/* ===== Notifications (real /api/alerts) ===== */
function buildAlerts() {
  // group per contract (soonest first)
  const byC = {};
  state.alerts.forEach((a) => {
    const g = byC[a.contract_id] || (byC[a.contract_id] = { ...a, kinds: [] });
    g.kinds.push(a.kind); if (a.days < g.days) g.days = a.days;
  });
  const groups = Object.values(byC).sort((a, b) => a.days - b.days);
  const kindLabel = { insurance: "insurance / COI", contract: "contract", po: "purchase order" };
  $("#emails").innerHTML = groups.map((g) => {
    let statusBadge, click = "";
    if (!g.has_email) statusBadge = `<span class="tag t-slate">No email on file</span>`;
    else if (g.message_status === "sent") { statusBadge = `<span class="tag t-green">✉ Emailed</span>`; click = `onclick="openMessage('${esc(g.message_id)}')"`; }
    else if (g.message_status === "demo") { statusBadge = `<span class="tag t-amber">✉ Prepared (demo)</span>`; click = `onclick="openMessage('${esc(g.message_id)}')"`; }
    else if (g.message_status === "failed") { statusBadge = `<span class="tag t-red">Send failed</span>`; click = `onclick="openMessage('${esc(g.message_id)}')"`; }
    else statusBadge = `<span class="tag t-amber">Queued</span>`;
    const kinds = [...new Set(g.kinds)].map((k) => kindLabel[k]).join(", ");
    return `<div class="email ${click ? "clickable" : ""}" ${click}>
      <div class="eh">
        <div><div class="subj">${esc(g.vendor || "Vendor")} — expires in ${g.days} day${g.days === 1 ? "" : "s"}</div>
        <div class="meta">To: ${esc(g.contract_head || "contract head")}${g.contract_head_email ? " &lt;" + esc(g.contract_head_email) + "&gt;" : ""} · ${esc(g.college || "")}</div></div>
        ${statusBadge}
      </div>
      <div class="eb">This contract (${esc(kinds)}) is within 30 days of expiry. ${g.has_email ? "The contract head is notified at 30 days and again at 2 weeks." : "No contract-head email is on file, so no email is sent — this is an on-screen alert only."} ${click ? "<span class='mini'>Click to view the message sent.</span>" : ""}</div>
    </div>`;
  }).join("") || `<div style="color:var(--muted);padding:20px">No contracts expiring within 30 days.</div>`;
}
async function sendAlertEmails(silent) {
  try {
    const res = await api("/api/alerts/notify", { method: "POST" });
    const s = res.summary || {};
    if (!silent) {
      const parts = [];
      if (s.sent) parts.push(`${s.sent} sent`);
      if (s.already_sent) parts.push(`${s.already_sent} already sent`);
      if (s.skipped_no_email) parts.push(`${s.skipped_no_email} no-email`);
      if (s.failed) parts.push(`${s.failed} failed`);
      toast("Alert emails: " + (parts.join(", ") || "nothing to send"));
    }
    await loadAll();
  } catch (e) { if (!silent) toast(e.message, true); }
}
async function openMessage(mid) {
  if (!mid) return;
  try {
    const m = await api("/api/messages/" + mid);
    $("#msgSubject").textContent = m.subject || "Alert message";
    const status = m.send_status === "sent" ? `sent to ${m.to_actual}` : m.send_status === "failed" ? `failed: ${m.error || ""}` : m.send_status || "";
    $("#msgMeta").textContent = `To: ${m.to_email || "-"} · ${status} · ${(m.sent_at || "").slice(0, 19).replace("T", " ")}`;
    $("#msgBody").innerHTML = m.body_html || `<pre>${esc(m.body_text || "")}</pre>`;
    $("#msgModal").classList.add("show");
  } catch (e) { toast(e.message, true); }
}
function closeMessage() { $("#msgModal").classList.remove("show"); }

/* ===== In-app document viewer (popup, not a new tab) ===== */
async function openDoc(id) {
  const doc = state.documents.find((d) => d.id === id) || {};
  const name = doc.filename || "Document";
  $("#docTitle").textContent = name;
  $("#docViewer").innerHTML = `<div class="empty"><span class="spinner"></span> Loading…</div>`;
  $("#docOpenTab").removeAttribute("href");
  $("#docModal").classList.add("show");
  try {
    const { url } = await api(`/api/documents/${id}/url`);
    $("#docOpenTab").href = url;
    const isImg = /\.(png|jpe?g|gif|tiff?)$/i.test(name);
    $("#docViewer").innerHTML = isImg
      ? `<img src="${url}" alt="${esc(name)}">`
      : `<iframe src="${url}" title="${esc(name)}"></iframe>`;
  } catch (e) {
    $("#docViewer").innerHTML = `<div class="empty">Could not load: ${esc(e.message)}</div>`;
  }
}
function closeDoc() { $("#docModal").classList.remove("show"); $("#docViewer").innerHTML = ""; }

/* ===== Document Hub ===== */
function buildDocHub() {
  let docs = state.documents.slice();
  if (state.docScope === "current") docs = docs.filter((d) => !d.archived);
  else if (state.docScope === "archived") docs = docs.filter((d) => d.archived);
  if (state.docQuery) {
    docs = docs.filter((d) => [d.filename, d.type, docVendor(d.contract_id)].join(" ").toLowerCase().includes(state.docQuery));
  }
  docs.sort((a, b) => (b.uploaded_at || "").localeCompare(a.uploaded_at || ""));
  $("#docRows").innerHTML = docs.length ? docs.map((d) => `<tr>
    <td><div class="vendor">📄 ${esc(d.filename || "—")}</div></td>
    <td><span class="doc-type">${esc(d.type || "doc")}</span></td>
    <td>${esc(docVendor(d.contract_id) || "—")}</td>
    <td>${esc((d.uploaded_at || "").slice(0, 10))}</td>
    <td>${d.archived ? '<span class="tag t-red">Archived</span>' : '<span class="tag t-green">Current</span>'}</td>
    <td style="text-align:right;white-space:nowrap">
      <button class="btn ghost" onclick="openDoc('${esc(d.id)}')">Open</button>
      <button class="btn ghost" onclick="toggleArchive('${esc(d.id)}')">${d.archived ? "Restore" : "Archive"}</button></td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">No documents match.</td></tr>`;
}
async function toggleArchive(id) {
  const d = state.documents.find((x) => x.id === id); if (!d) return;
  try { await api(`/api/documents/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archived: !d.archived }) });
    toast(d.archived ? "Restored" : "Archived"); await loadAll();
  } catch (e) { toast(e.message, true); }
}

/* ===== Upload (real: S3 + Bedrock async parse) ===== */
const FIELDS = [
  { k: "vendor", label: "Vendor", t: "text" },
  { k: "cat", label: "Category", t: "text" },
  { k: "sub", label: "Subcategory", t: "text" },
  { k: "college", label: "Campus", t: "select", opts: ["", "Foothill", "De Anza", "District"] },
  { k: "contract_head", label: "Contract head", t: "text" },
  { k: "contract_head_email", label: "Contract head email", t: "text" },
  { k: "value", label: "Value ($)", t: "number" },
  { k: "start", label: "Start date", t: "date" },
  { k: "end", label: "End date", t: "date" },
  { k: "po", label: "PO number", t: "text" },
  { k: "poEnd", label: "PO end date", t: "date" },
  { k: "ins", label: "Insurance expiry", t: "date" },
  { k: "addl", label: "Additional insured", t: "select", opts: ["", "Yes", "No"] },
  { k: "scope", label: "Scope", t: "textarea" },
  { k: "summary", label: "AI summary", t: "textarea" },
];
function resetUpload() {
  $("#uploadPrompt").style.display = "block";
  $("#extract").classList.remove("show");
  $("#uploadStatus").innerHTML = "";
  $("#pdfframe").src = "";
  $("#fileInput").value = "";
  state.pendingUpload = null;
}

async function uploadFile(file) {
  $("#uploadStatus").innerHTML = `<span class="spinner"></span> Uploading <b>${esc(file.name)}</b>…`;
  const fd = new FormData(); fd.append("file", file);
  let res;
  try { res = await api("/api/upload", { method: "POST", body: fd }); }
  catch (e) { $("#uploadStatus").innerHTML = `<span class="badge badge-bad">Upload failed</span> <span class="mini">${esc(e.message)}</span>`; return toast(e.message, true); }
  state.pendingUpload = res;
  // switch to extract view with the document preview
  $("#uploadPrompt").style.display = "none";
  $("#extract").classList.add("show");
  $("#pdfframe").src = `/api/documents/${res.document.id}/view`;
  await loadAll(); // refresh doc hub
  if (res.async) {
    $("#extractMethod").textContent = "Parsing with Bedrock (Claude Sonnet 4.5)…";
    $("#scan").classList.remove("hidden");
    renderExtractFields({});
    const fields = await pollParse(res.document.id);
    state.pendingUpload.fields = fields;
    $("#scan").classList.add("hidden");
    renderExtractFields(fields);
  } else {
    $("#scan").classList.add("hidden");
    renderExtractFields(res.fields || {});
  }
}
async function pollParse(docId, tries = 40) {
  for (let i = 0; i < tries; i++) {
    await sleep(2000);
    let doc; try { doc = await api("/api/documents/" + docId); } catch (e) { continue; }
    if (doc.parse_status === "done") { $("#extractMethod").textContent = "Extracted by AI — verify & edit."; return doc.parsed_fields || {}; }
    if (doc.parse_status === "error") { $("#extractMethod").innerHTML = `<span class="badge badge-bad">AI parse failed</span> ${esc(doc.parse_error || "")} — fill in manually.`; return {}; }
  }
  $("#extractMethod").innerHTML = `<span class="badge badge-warn">Parsing timed out</span> — fill in manually.`;
  return {};
}
function fieldInput(f, val) {
  const v = val == null ? "" : val;
  if (f.t === "select") return `<select data-key="${f.k}">${f.opts.map((o) => `<option value="${esc(o)}" ${String(o) === String(v) ? "selected" : ""}>${o || "—"}</option>`).join("")}</select>`;
  if (f.t === "textarea") return `<textarea data-key="${f.k}">${esc(v)}</textarea>`;
  return `<input type="${f.t}" data-key="${f.k}" value="${esc(v)}">`;
}
function renderExtractFields(fields) {
  const meta = fields._meta;
  if (meta && meta.method) $("#extractMethod").textContent = `Extracted via ${String(meta.method).replace(/_/g, " ")} — verify & edit.`;
  $("#exrows").innerHTML = FIELDS.map((f) => `<div class="exrow"><div class="k">${f.label}</div><div class="v">${fieldInput(f, fields[f.k])}</div></div>`).join("");
}
function collectFields() {
  const out = {};
  $$("#exrows [data-key]").forEach((el) => { let v = el.value; if (el.type === "number") v = v === "" ? null : Number(v); else if (v === "") v = null; out[el.dataset.key] = v; });
  return out;
}
async function saveContract() {
  const payload = collectFields();
  if (!payload.vendor) return toast("Vendor is required", true);
  if (state.pendingUpload && state.pendingUpload.document) payload.document_id = state.pendingUpload.document.id;
  try {
    await api("/api/contracts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    toast("Contract saved"); resetUpload(); await loadAll();
    const btn = $(`.sidebar nav button[onclick*="'dashboard'"]`); showView("dashboard", btn);
  } catch (e) { toast(e.message, true); }
}

/* ===== Wire up ===== */
{
  const today = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  $("#today").textContent = today;
  const hd = $("#heroDate"); if (hd) hd.textContent = today;
}
["search", "fDept", "fStatus", "fIns"].forEach((id) => $("#" + id).addEventListener("input", render));
$("#docSearch").addEventListener("input", (e) => { state.docQuery = e.target.value.toLowerCase().trim(); buildDocHub(); });
$("#docScope").addEventListener("change", (e) => { state.docScope = e.target.value; buildDocHub(); });
const drop = $("#drop"), fileInput = $("#fileInput");
drop.addEventListener("click", () => fileInput.click());
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.style.borderColor = "var(--crim)"; }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.style.borderColor = ""; }));
drop.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]); });
fileInput.addEventListener("change", () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDetail(); closeMessage(); closeDoc(); } });

loadAll();
