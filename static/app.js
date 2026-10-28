const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let pending = [], sourceText = "", allTasks = [], filter = "all";

const step = (n) => ["s1", "s2", "s3"].forEach((id, i) => $(id).classList.toggle("on", i + 1 === n));
const setStatus = (msg, isErr) => { $("status").innerHTML = msg ? `<span class="${isErr ? "err" : "muted"}">${esc(msg)}</span>` : ""; };

async function api(url, opts = {}) {
  let res;
  try { res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts }); }
  catch { throw new Error("Could not reach the server. Check your connection and try again."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.error || "Something went wrong."); e.data = data; throw e; }
  return data;
}

// ---- Input: examples, text, .txt, voice ----
const countUp = () => ($("count").textContent = `${$("note").value.length} / 6000`);
$("note").addEventListener("input", countUp);
$("chips").addEventListener("click", (e) => { if (e.target.dataset.ex) { $("note").value = e.target.dataset.ex; countUp(); $("note").focus(); } });
$("file").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) { $("note").value = (await f.text()).slice(0, 6000); countUp(); } });
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
$("mic").addEventListener("click", () => {
  if (!SR) return setStatus("Voice recording is not supported in this browser. Use Chrome or Edge, or type your note.", true);
  if (rec) { rec.stop(); return; }
  rec = new SR(); rec.continuous = true; rec.interimResults = false; rec.lang = "en-IN";
  const base = $("note").value ? $("note").value + " " : "";
  rec.onresult = (ev) => { $("note").value = base + [...ev.results].map((r) => r[0].transcript).join(" "); countUp(); };
  rec.onerror = (ev) => setStatus(`Microphone error: ${ev.error}. Allow microphone access and try again.`, true);
  rec.onend = () => { rec = null; $("mic").innerHTML = "&#127908; Record voice"; $("mic").classList.remove("rec"); setStatus(""); };
  rec.start(); $("mic").innerHTML = "&#9209; Stop recording"; $("mic").classList.add("rec"); setStatus("Listening…");
});

// ---- Extract ----
function busy(on) { $("extract").disabled = on; document.querySelector(".spin").hidden = !on; $("extract-label").textContent = on ? "Extracting…" : "Extract tasks"; }
$("extract").addEventListener("click", async () => {
  setStatus(""); busy(true); $("confirm").innerHTML = "";
  try {
    const d = await api("/api/extract", { method: "POST", body: JSON.stringify({ text: $("note").value }) });
    pending = d.tasks; sourceText = d.source_text;
    if (!pending.length) { $("preview").hidden = true; step(1); return setStatus("No actionable tasks found in this note. Mention what needs doing and by when.", true); }
    renderPreview(); step(2); $("preview").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { $("preview").hidden = true; step(1); setStatus(e.message, true); }
  finally { busy(false); }
});

function renderPreview() {
  $("preview").hidden = false;
  $("cards").innerHTML = pending.map((p, i) => {
    const t = p.task;
    return `<div class="pcard p-${esc(t.priority)}" data-i="${i}">
      <button class="drop" data-drop="${i}" type="button">Remove</button>
      <label>Title<input data-f="title" value="${esc(t.title)}"></label>
      <div class="grid3">
        <label>Priority<select data-f="priority">${["high", "medium", "low"].map((o) => `<option ${o === t.priority ? "selected" : ""}>${o}</option>`).join("")}</select></label>
        <label>Due date<input type="date" data-f="due_date" value="${esc(t.due_date || "")}"></label>
        <label>Reminder<input type="datetime-local" data-f="reminder_at" value="${esc(t.reminder_at || "")}"></label>
      </div>
      <label>Notes<input data-f="notes" value="${esc(t.notes || "")}"></label>
      ${p.issues.map((x) => `<p class="issue ${x.level}">${x.level === "error" ? "Fix: " : "Check: "}${esc(x.msg)}</p>`).join("")}
    </div>`;
  }).join("");
}
$("cards").addEventListener("input", (e) => { const f = e.target.dataset.f, i = e.target.closest(".pcard")?.dataset.i; if (f && i !== undefined) pending[i].task[f] = e.target.value || null; });
$("cards").addEventListener("click", (e) => {
  if (e.target.dataset.drop === undefined) return;
  pending.splice(+e.target.dataset.drop, 1);
  if (pending.length) renderPreview(); else { $("preview").hidden = true; step(1); }
});

// ---- Save ----
$("save").addEventListener("click", async () => {
  $("save").disabled = true;
  try {
    const d = await api("/api/tasks", { method: "POST", body: JSON.stringify({ tasks: pending.map((p) => p.task), source_text: sourceText }) });
    $("confirm").innerHTML = `<div class="okmsg"><strong>Saved ${d.saved.length} task${d.saved.length > 1 ? "s" : ""} to your workspace</strong><br>${d.saved.map((t) => `#${t.id} ${esc(t.title)}`).join("<br>")}</div>`;
    pending = []; $("preview").hidden = true; $("note").value = ""; countUp(); setStatus(""); step(3);
    await loadBoard(); setTimeout(() => step(1), 4000);
  } catch (e) {
    if (e.data?.problems) { e.data.problems.forEach((p) => (pending[p.index].issues = p.issues)); renderPreview(); }
    setStatus(e.message, true);
  } finally { $("save").disabled = false; }
});

// ---- Board ----
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function bucket(t) {
  if (t.status === "done") return "Done";
  if (!t.due_date) return "No date";
  const n = today(), wk = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  return t.due_date < n ? "Overdue" : t.due_date === n ? "Today" : t.due_date <= wk ? "This week" : "Later";
}
function stats() {
  const open = allTasks.filter((t) => t.status === "open");
  $("st-open").textContent = open.length;
  $("st-high").textContent = open.filter((t) => t.priority === "high").length;
  $("st-today").textContent = open.filter((t) => t.due_date === today()).length;
  $("st-done").textContent = allTasks.length - open.length;
}
function renderBoard() {
  const list = allTasks.filter((t) => filter === "all" ? true : filter === "high" ? t.priority === "high" && t.status === "open" : filter === "today" ? t.due_date === today() && t.status === "open" : t.status === "done");
  if (!list.length) { $("board").innerHTML = `<p class="empty">${allTasks.length ? "Nothing here with this filter." : "No tasks yet. Pick an example or record a note on the left to create your first ones."}</p>`; return; }
  const order = ["Overdue", "Today", "This week", "Later", "No date", "Done"], groups = {};
  list.forEach((t) => (groups[bucket(t)] ||= []).push(t));
  $("board").innerHTML = order.filter((g) => groups[g]).map((g) => `<div class="group"><h3 class="${g === "Overdue" ? "over" : ""}">${g} (${groups[g].length})</h3>${groups[g].map((t) => `
    <div class="task p-${esc(t.priority)} ${t.status === "done" ? "done" : ""}">
      <input type="checkbox" aria-label="Mark done" data-id="${t.id}" ${t.status === "done" ? "checked" : ""}>
      <div class="body"><div class="t">${esc(t.title)}</div>
        <div class="tags"><span class="tag ${esc(t.priority)}">${esc(t.priority)}</span>${t.due_date ? `<span class="tag">Due ${esc(t.due_date)}</span>` : ""}${t.reminder_at ? `<span class="tag">Reminder ${esc(t.reminder_at.replace("T", " "))}</span>` : ""}</div>
        ${t.notes ? `<div class="notes">${esc(t.notes)}</div>` : ""}</div>
      <button class="del" data-del="${t.id}" aria-label="Delete task">Delete</button>
    </div>`).join("")}</div>`).join("");
}
async function loadBoard() {
  try { allTasks = (await api("/api/tasks")).tasks; stats(); renderBoard(); }
  catch (e) { $("board").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}
$("tabs").addEventListener("click", (e) => {
  if (!e.target.dataset.f) return;
  filter = e.target.dataset.f; document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b === e.target)); renderBoard();
});
$("board").addEventListener("change", async (e) => {
  if (!e.target.dataset.id) return;
  try { await api(`/api/tasks/${e.target.dataset.id}`, { method: "PATCH", body: JSON.stringify({ status: e.target.checked ? "done" : "open" }) }); loadBoard(); }
  catch (err) { setStatus(err.message, true); }
});
$("board").addEventListener("click", async (e) => {
  if (!e.target.dataset.del) return;
  try { await api(`/api/tasks/${e.target.dataset.del}`, { method: "DELETE" }); loadBoard(); }
  catch (err) { setStatus(err.message, true); }
});
loadBoard();
