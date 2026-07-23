"use strict";

// ---- Field metadata (labels + input types) --------------------------------
const FIELDS = [
  { key: "poly", label: "Agreement / Policy #", type: "text" },
  { key: "vendor", label: "Vendor", type: "text" },
  { key: "cat", label: "Category", type: "text" },
  { key: "sub", label: "Subcategory", type: "text" },
  { key: "college", label: "Campus", type: "select", options: ["", "Foothill", "De Anza", "District"] },
  { key: "value", label: "Value ($)", type: "number" },
  { key: "start", label: "Start Date", type: "date" },
  { key: "end", label: "End Date", type: "date" },
  { key: "po", label: "PO Number", type: "text" },
  { key: "poEnd", label: "PO End Date", type: "date" },
  { key: "ins", label: "Insurance Expiry", type: "date" },
  { key: "addl", label: "Additional Insured", type: "select", options: ["", "Yes", "No"] },
  { key: "scope", label: "Scope of Work", type: "textarea", full: true },
  { key: "summary", label: "AI Summary", type: "textarea", full: true },
];

// ---- State ----------------------------------------------------------------
const state = {
  contracts: [],
  documents: [],
  alerts: [],
  stats: null,
  pendingDoc: null, // { document, fields } from an upload awaiting save
  docScope: "current",
  docQuery: "",
};

// ---- Small helpers ---------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) =>
  n == null ? "-" : "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
const fmtDate = (d) => (d ? d : "-");

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((body && body.error) || res.statusText);
  return body;
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}

function statusBadge(status) {
  const label = { active: "Active", expiring: "Expiring Soon", expired: "Expired", unknown: "Unknown" }[status] || status;
  return `<span class="badge dot ${status}">${label}</span>`;
}

// ---- Navigation ------------------------------------------------------------
const VIEW_META = {
  dashboard: ["Dashboard", "Overview of contracts, insurance, and purchase orders"],
  upload: ["Upload & Extract", "Add a document and let AI fill in the details"],
  alerts: ["Alerts", "Insurance and contracts expiring within 30 days"],
  documents: ["Document Hub", "Search current and archived documents"],
};

function showView(name) {
  $$(".view").forEach((v) => v.classList.remove("active"));
  $("#view-" + name).classList.add("active");
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  const [title, sub] = VIEW_META[name];
  $("#viewTitle").textContent = title;
  $("#viewSub").textContent = sub;
}

$("#nav").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-view]");
  if (btn) showView(btn.dataset.view);
});
$("#quickUpload").addEventListener("click", () => showView("upload"));

// ---- Data loading ----------------------------------------------------------
async function loadAll() {
  try {
    const [contracts, documents, stats, alerts] = await Promise.all([
      api("/api/contracts"),
      api("/api/documents"),
      api("/api/stats"),
      api("/api/alerts"),
    ]);
    state.contracts = contracts;
    state.documents = documents;
    state.stats = stats;
    state.alerts = alerts;
    renderDashboard();
    renderAlerts();
    renderDocuments();
  } catch (e) {
    toast("Failed to load data: " + e.message, true);
    $("#pairRows").innerHTML = `<tr><td colspan="7" class="empty">Could not reach the backend.<br><span class="muted">${esc(e.message)}</span></td></tr>`;
  }
}

// ---- Dashboard -------------------------------------------------------------
function renderDashboard() {
  const s = state.stats || {};
  $("#kpis").innerHTML = `
    ${kpi("Total Contracts", s.total_contracts ?? 0, "")}
    ${kpi("Active", s.active ?? 0, "green")}
    ${kpi("Expiring Soon", s.expiring ?? 0, "amber")}
    ${kpi("Total Value", money(s.total_value), "")}`;

  $("#catBars").innerHTML = bars(s.by_category || {});
  $("#collegeBars").innerHTML = bars(s.by_college || {});

  const rows = state.contracts;
  $("#pairCount").textContent = `${rows.length} pairing${rows.length === 1 ? "" : "s"}`;
  $("#pairRows").innerHTML =
    rows.length === 0
      ? `<tr><td colspan="7" class="empty">No contracts yet. Upload one to get started.</td></tr>`
      : rows
          .map(
            (c) => `<tr data-id="${esc(c.id)}">
        <td><b>${esc(c.poly || "-")}</b></td>
        <td>${esc(c.vendor || "-")}</td>
        <td>${esc(c.college || "-")}</td>
        <td class="mono">${esc(c.po || "-")}</td>
        <td class="mono">${money(c.value)}</td>
        <td class="mono">${fmtDate(c.end)}</td>
        <td>${statusBadge(c.status)}</td>
      </tr>`
          )
          .join("");
  $$("#pairRows tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => openContract(tr.dataset.id))
  );

  const n = state.alerts.length;
  $("#alertCount").textContent = n ? `(${n})` : "";
}

const kpi = (label, num, cls) =>
  `<div class="card kpi"><div class="label">${label}</div><div class="num ${cls}">${num}</div></div>`;

function bars(obj) {
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return `<div class="muted">No data</div>`;
  const max = Math.max(...entries.map((e) => e[1]));
  return entries
    .map(
      ([name, val]) => `<div class="bar-row">
      <div class="name">${esc(name)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(val / max) * 100}%"></div></div>
      <div class="val">${val}</div></div>`
    )
    .join("");
}

// ---- Contract detail drawer ------------------------------------------------
let drawerEditing = false;

async function openContract(id) {
  let contract;
  try {
    contract = await api("/api/contracts/" + id);
  } catch (e) {
    return toast(e.message, true);
  }
  drawerEditing = false;
  renderDrawer(contract);
  $("#backdrop").classList.add("open");
  $("#drawer").classList.add("open");
}

function closeDrawer() {
  $("#backdrop").classList.remove("open");
  $("#drawer").classList.remove("open");
}
$("#drawerClose").addEventListener("click", closeDrawer);
$("#backdrop").addEventListener("click", closeDrawer);

function renderDrawer(c) {
  $("#drawerTitle").textContent = c.vendor || "Contract";
  $("#drawerSub").innerHTML = `${esc(c.poly || "")} &nbsp; ${statusBadge(c.status)}`;

  if (drawerEditing) {
    $("#drawerBody").innerHTML = `<div class="form-grid">${FIELDS.map((f) =>
      fieldInput(f, c[f.key])
    ).join("")}</div>`;
    $("#drawerFoot").innerHTML = `
      <button class="btn ghost" id="cancelEdit">Cancel</button>
      <button class="btn" id="saveEdit">Save Changes</button>`;
    $("#cancelEdit").addEventListener("click", () => { drawerEditing = false; renderDrawer(c); });
    $("#saveEdit").addEventListener("click", () => saveEdit(c.id));
    return;
  }

  const docs = c.document_records || [];
  $("#drawerBody").innerHTML = `
    <div class="kv">
      ${row("Category", `${esc(c.cat || "-")}${c.sub ? " / " + esc(c.sub) : ""}`)}
      ${row("Campus", esc(c.college || "-"))}
      ${row("Value", money(c.value))}
      ${row("Term", `${fmtDate(c.start)} &rarr; ${fmtDate(c.end)}`)}
      ${row("PO Number", `${esc(c.po || "-")}`)}
      ${row("PO End", fmtDate(c.poEnd))}
      ${row("Insurance Expiry", `${fmtDate(c.ins)} ${dayHint(c.days_to_insurance)}`)}
      ${row("Additional Insured", esc(c.addl || "-"))}
    </div>
    <div style="margin-top:16px">
      <div class="muted" style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.4px">Scope</div>
      <p style="margin:6px 0 0">${esc(c.scope || "-")}</p>
    </div>
    <div style="margin-top:14px">
      <div class="muted" style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.4px">AI Summary</div>
      <p style="margin:6px 0 0">${esc(c.summary || "-")}</p>
    </div>
    <div style="margin-top:16px">
      <div class="muted" style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.4px">Documents</div>
      <div style="margin-top:6px">
        ${docs.length ? docs.map((d) => `<span class="doc-chip" data-doc="${esc(d.id)}">📄 ${esc(d.filename)}</span>`).join("") : '<span class="muted">None linked</span>'}
      </div>
    </div>`;
  $("#drawerFoot").innerHTML = `
    ${docs.length ? `<button class="btn ghost view-docs-btn" id="viewDocsBtn">View ${docs.length} document${docs.length > 1 ? "s" : ""}</button>` : ""}
    <button class="btn" id="editBtn">Edit</button>`;
  $("#editBtn").addEventListener("click", () => { drawerEditing = true; renderDrawer(c); });
  if (docs.length) {
    $("#viewDocsBtn").addEventListener("click", () => openViewer(docs, 0));
  }
  $$("#drawerBody .doc-chip").forEach((chip) =>
    chip.addEventListener("click", () => openDoc(chip.dataset.doc))
  );
}

const row = (k, v) => `<div class="k">${k}</div><div>${v}</div>`;
const dayHint = (d) =>
  d == null ? "" : d < 0 ? `<span class="badge expired">expired</span>` : d <= 30 ? `<span class="badge expiring">${d}d</span>` : "";

async function saveEdit(id) {
  const payload = collectForm("#drawerBody");
  try {
    const updated = await api("/api/contracts/" + id, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    toast("Contract updated");
    drawerEditing = false;
    await loadAll();
    // reopen fresh
    const fresh = await api("/api/contracts/" + id);
    renderDrawer(fresh);
  } catch (e) {
    toast(e.message, true);
  }
}

// ---- Form building ---------------------------------------------------------
function fieldInput(f, value) {
  const v = value == null ? "" : value;
  let input;
  if (f.type === "select") {
    input = `<select data-key="${f.key}">${f.options
      .map((o) => `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${o || "-"}</option>`)
      .join("")}</select>`;
  } else if (f.type === "textarea") {
    input = `<textarea data-key="${f.key}">${esc(v)}</textarea>`;
  } else {
    input = `<input type="${f.type}" data-key="${f.key}" value="${esc(v)}" />`;
  }
  return `<label class="field" ${f.full ? 'style="grid-column:1/-1"' : ""}><span>${f.label}</span>${input}</label>`;
}

function collectForm(rootSel) {
  const out = {};
  $$(`${rootSel} [data-key]`).forEach((el) => {
    let val = el.value;
    if (el.type === "number") val = val === "" ? null : Number(val);
    else if (val === "") val = null;
    out[el.dataset.key] = val;
  });
  return out;
}

// ---- Upload & Extract ------------------------------------------------------
const drop = $("#drop");
const fileInput = $("#fileInput");
drop.addEventListener("click", () => fileInput.click());
["dragover", "dragenter"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); })
);
drop.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]); });
fileInput.addEventListener("change", () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });

async function uploadFile(file) {
  $("#uploadStatus").innerHTML = `<span class="spinner"></span> Uploading & parsing <b>${esc(file.name)}</b>...`;
  $("#extractCard").classList.add("hidden");
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await api("/api/upload", { method: "POST", body: fd });
    state.pendingDoc = res;
    $("#uploadStatus").innerHTML = `✅ Stored <b>${esc(file.name)}</b>. Review the extracted fields beside the document.`;
    renderExtractForm(res.fields || {});
    embedPreview(res.document);
    await loadAll(); // refresh doc hub
  } catch (e) {
    $("#uploadStatus").innerHTML = `<span class="badge expired">Upload failed</span> <span class="muted">${esc(e.message)}</span>`;
    toast(e.message, true);
  }
}

function renderExtractForm(fields) {
  const meta = fields._meta || {};
  $("#extractMethod").textContent = meta.ok === false
    ? "(AI parse unavailable - fill in manually)"
    : meta.method ? `(via ${meta.method.replace("_", " ")})` : "";
  $("#extractForm").innerHTML = FIELDS.map((f) => fieldInput(f, fields[f.key])).join("");
  $("#extractCard").classList.remove("hidden");
  $("#extractCard").scrollIntoView({ behavior: "smooth" });
}

$("#discardBtn").addEventListener("click", () => {
  state.pendingDoc = null;
  $("#extractCard").classList.add("hidden");
  $("#uploadStatus").innerHTML = "";
  $("#extractPreview").innerHTML = '<div class="placeholder">Document preview</div>';
});

$("#saveContractBtn").addEventListener("click", async () => {
  const payload = collectForm("#extractForm");
  if (!payload.vendor) return toast("Vendor is required", true);
  if (state.pendingDoc && state.pendingDoc.document) {
    payload.document_id = state.pendingDoc.document.id;
  }
  try {
    await api("/api/contracts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    toast("Contract saved");
    state.pendingDoc = null;
    $("#extractCard").classList.add("hidden");
    $("#uploadStatus").innerHTML = "";
    await loadAll();
    showView("dashboard");
  } catch (e) {
    toast(e.message, true);
  }
});

// ---- Alerts ----------------------------------------------------------------
function renderAlerts() {
  const list = state.alerts;
  const el = $("#alertList");
  if (!list.length) {
    el.innerHTML = `<div class="card empty">🎉 Nothing expiring in the next 30 days.</div>`;
    return;
  }
  const kindLabel = { insurance: "Insurance / COI", contract: "Contract end", po: "Purchase order" };
  el.innerHTML = list
    .map((a) => {
      const cls = a.days <= 7 ? "crit" : "warn";
      return `<div class="alert-item ${cls}" data-id="${esc(a.contract_id)}">
        <div class="days">${a.days}<small>DAYS</small></div>
        <div class="meta">
          <b>${esc(a.vendor || "Unknown vendor")}</b> &nbsp;<span class="muted">${esc(a.poly || "")}</span>
          <div class="sub">${kindLabel[a.kind]} expires ${esc(a.date)} · ${esc(a.college || "")}</div>
        </div>
        <span class="badge ${a.kind === "insurance" ? "expiring" : "expired"}">${a.kind}</span>
      </div>`;
    })
    .join("");
  $$("#alertList .alert-item").forEach((it) =>
    it.addEventListener("click", () => openContract(it.dataset.id))
  );
}

// ---- Document Hub ----------------------------------------------------------
$("#docSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-scope]");
  if (!b) return;
  state.docScope = b.dataset.scope;
  $$("#docSeg button").forEach((x) => x.classList.toggle("active", x === b));
  renderDocuments();
});
$("#docSearch").addEventListener("input", (e) => {
  state.docQuery = e.target.value.toLowerCase().trim();
  renderDocuments();
});

function vendorForContract(cid) {
  const c = state.contracts.find((x) => x.id === cid);
  return c ? c.vendor : "";
}

function renderDocuments() {
  let docs = state.documents.slice();
  if (state.docScope === "current") docs = docs.filter((d) => !d.archived);
  else if (state.docScope === "archived") docs = docs.filter((d) => d.archived);

  if (state.docQuery) {
    docs = docs.filter((d) => {
      const hay = [d.filename, d.type, vendorForContract(d.contract_id)]
        .join(" ")
        .toLowerCase();
      return hay.includes(state.docQuery);
    });
  }

  $("#docRows").innerHTML = docs.length
    ? docs
        .map(
          (d) => `<tr>
        <td><b>📄 ${esc(d.filename)}</b></td>
        <td><span class="doc-type">${esc(d.type || "doc")}</span></td>
        <td>${esc(vendorForContract(d.contract_id) || "-")}</td>
        <td class="mono">${esc((d.uploaded_at || "").slice(0, 10))}</td>
        <td>${d.archived ? '<span class="badge expired">Archived</span>' : '<span class="badge active">Current</span>'}</td>
        <td style="text-align:right">
          <button class="btn ghost sm" data-open="${esc(d.id)}">Open</button>
          <button class="btn ghost sm" data-arch="${esc(d.id)}">${d.archived ? "Restore" : "Archive"}</button>
        </td>
      </tr>`
        )
        .join("")
    : `<tr><td colspan="6" class="empty">No documents match.</td></tr>`;

  $$("#docRows [data-open]").forEach((b) =>
    b.addEventListener("click", () => openDoc(b.dataset.open))
  );
  $$("#docRows [data-arch]").forEach((b) =>
    b.addEventListener("click", () => toggleArchive(b.dataset.arch))
  );
}

// Open a document in the embedded viewer. If the doc belongs to a contract,
// include its siblings (e.g. agreement + COI) as tabs.
function openDoc(id) {
  const doc = state.documents.find((d) => d.id === id);
  let docs;
  if (doc && doc.contract_id) {
    docs = state.documents.filter((d) => d.contract_id === doc.contract_id);
  } else {
    docs = doc ? [doc] : [{ id, filename: id }];
  }
  docs.sort((a, b) => (a.type === "coi" ? 1 : 0) - (b.type === "coi" ? 1 : 0));
  const idx = Math.max(0, docs.findIndex((d) => d.id === id));
  openViewer(docs, idx);
}

async function toggleArchive(id) {
  const doc = state.documents.find((d) => d.id === id);
  if (!doc) return;
  try {
    await api(`/api/documents/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived: !doc.archived }),
    });
    toast(doc.archived ? "Restored" : "Archived");
    await loadAll();
  } catch (e) {
    toast(e.message, true);
  }
}

// ---- Document viewer -------------------------------------------------------
const isImage = (f) => /\.(png|jpe?g|gif|tiff?)$/i.test(f || "");
const mediaTag = (filename, url) =>
  isImage(filename)
    ? `<img src="${url}" alt="${esc(filename)}" />`
    : `<iframe src="${url}" title="${esc(filename)}"></iframe>`;

function openViewer(docs, index = 0) {
  if (!docs || !docs.length) return toast("No document to view", true);
  state.viewerDocs = docs;
  showViewerDoc(index);
  $("#viewerBackdrop").classList.add("open");
  $("#viewer").classList.add("open");
}

async function showViewerDoc(index) {
  const docs = state.viewerDocs || [];
  const d = docs[index];
  if (!d) return;
  $("#viewerTabs").innerHTML = docs
    .map(
      (doc, i) =>
        `<button class="vtab ${i === index ? "active" : ""}" data-i="${i}">${
          doc.type === "coi" ? "📋 COI" : "📄 Contract"
        } · ${esc(doc.filename)}</button>`
    )
    .join("");
  $$("#viewerTabs .vtab").forEach((b) =>
    b.addEventListener("click", () => showViewerDoc(+b.dataset.i))
  );
  const body = $("#viewerBody");
  body.innerHTML = `<div class="empty" style="color:#e2e8f0"><span class="spinner"></span> Loading ${esc(d.filename)}...</div>`;
  $("#viewerOpen").removeAttribute("href");
  try {
    const { url } = await api(`/api/documents/${d.id}/url`);
    body.innerHTML = mediaTag(d.filename, url);
    $("#viewerOpen").href = url;
  } catch (e) {
    body.innerHTML = `<div class="empty" style="color:#e2e8f0">Could not load: ${esc(e.message)}</div>`;
  }
}

function closeViewer() {
  $("#viewerBackdrop").classList.remove("open");
  $("#viewer").classList.remove("open");
  $("#viewerBody").innerHTML = "";
}
$("#viewerClose").addEventListener("click", closeViewer);
$("#viewerBackdrop").addEventListener("click", closeViewer);
document.addEventListener("keydown", (e) => e.key === "Escape" && closeViewer());

async function embedPreview(doc) {
  const box = $("#extractPreview");
  if (!doc) {
    box.innerHTML = `<div class="placeholder">Document preview</div>`;
    return;
  }
  box.innerHTML = `<div class="placeholder"><span class="spinner"></span></div>`;
  try {
    const { url } = await api(`/api/documents/${doc.id}/url`);
    box.innerHTML = mediaTag(doc.filename, url);
  } catch (e) {
    box.innerHTML = `<div class="placeholder">Preview unavailable<br>${esc(e.message)}</div>`;
  }
}

// ---- Boot ------------------------------------------------------------------
loadAll();
