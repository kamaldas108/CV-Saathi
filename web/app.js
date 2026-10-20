"use strict";

const $ = (id) => document.getElementById(id);
const STEPS = ["interview", "template", "design", "review", "export"];
const SECTION_ORDER = [
  ["contact", "Contact"], ["trade", "Trade"], ["summary", "Profile"], ["experience", "Apprenticeship and work"],
  ["skills", "Skills"], ["tools", "Tools and equipment"], ["education", "Education"], ["projects", "Projects and training"],
  ["languages", "Languages"],
];

let S = null;              // latest state from the server
const partials = {};       // live transcript turns still being spoken, by id
let ws = null;
let wsReady = null;
let audioCtx = null, micStream = null, micNode = null, micSource = null, micBuffer = [];
let playTime = 0;
const playing = new Set();
let editing = null;        // fact id open for editing in the review step

// ----- helpers ---------------------------------------------------------------------------

async function api(path, options = {}) {
  const res = await fetch(path, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : {},
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: "same-origin",
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.detail) || `Request failed (${res.status})`);
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function status(text) { $("status").textContent = text || ""; }
const base = () => `/api/sessions/${S.session_id}`;
const previewKey = () => `${S.notebook.revision}-${S.design_revision}`;
function storeId(id) { try { sessionStorage.setItem("cvs_session", id || ""); } catch (_) {} }
function storedId() { try { return sessionStorage.getItem("cvs_session"); } catch (_) { return null; } }

// ----- consent ---------------------------------------------------------------------------

function updateStart() { $("startBtn").disabled = !($("agree").checked && $("adult").checked); }
$("agree").addEventListener("change", updateStart);
$("adult").addEventListener("change", updateStart);
$("startBtn").addEventListener("click", async () => {
  $("consentError").textContent = "";
  try {
    const st = await api("/api/sessions", { method: "POST", body: { consent: $("agree").checked, adult: $("adult").checked } });
    storeId(st.session_id);
    showApp(st);
  } catch (err) { $("consentError").textContent = err.message; }
});

function showApp(st) {
  $("consent").hidden = true;
  $("app").hidden = false;
  setState(st);
  if (st.mode === "live") status("Tap the microphone and start talking.");
  else $("textInput").focus();
}

// ----- rendering -------------------------------------------------------------------------

function setState(st) {
  const stepChanged = !S || S.step !== st.step;
  S = st;
  $("modeBadge").hidden = false;
  $("modeBadge").textContent = st.mode === "live" ? "Voice" : "Sample mode";
  $("sampleBanner").hidden = st.mode !== "sample";
  $("micBtn").hidden = st.mode !== "live";
  for (const btn of document.querySelectorAll(".steps button")) btn.classList.toggle("active", btn.dataset.step === st.step);
  for (const step of STEPS) $(`step-${step}`).hidden = step !== st.step;
  renderChat();
  renderNotebook();
  if (st.step === "template") renderTemplates();
  if (st.step === "design") renderDesign();
  if (st.step === "review") renderReview();
  if (st.step === "export") $("exportPreview").src = `${base()}/preview.png?w=720&v=${previewKey()}`;
  if (stepChanged) window.scrollTo(0, 0);
}

function renderChat() {
  const chat = $("chat");
  const atBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 40;
  chat.replaceChildren(
    ...S.transcript.map((t) => el("div", { class: `msg ${t.speaker}` }, t.text)),
    ...Object.values(partials).map((t) => el("div", { class: `msg ${t.speaker} partial` }, t.text)),
  );
  if (atBottom && S.step === "interview") window.scrollTo(0, document.body.scrollHeight);
}

function factText(f) {
  if (f.field === "experience") return [f.value, f.extra.employer, f.extra.duration].filter(Boolean).join(" · ");
  return f.value;
}

function tagFor(f) {
  if (f.status === "suggested") return el("span", { class: "tag suggest" }, "suggested");
  if (f.status === "needs_spelling") return el("span", { class: "tag spell" }, "check spelling");
  if (f.source === "student_edit") return el("span", { class: "tag edit" }, "edited by you");
  if (f.status === "confirmed") return el("span", { class: "tag ok" }, "spelling ok");
  return null;
}

function linesBySection(editable) {
  const facts = S.notebook.facts;
  const out = [];
  for (const [section, title] of SECTION_ORDER) {
    const items = facts.filter((f) => f.section === section && f.field !== "duty");
    if (!items.length) continue;
    const box = el("div", { class: "section" }, el("h3", {}, title));
    for (const f of items) {
      box.append(lineFor(f, editable));
      if (f.field === "experience") for (const d of facts.filter((x) => x.field === "duty" && x.parent === f.id)) box.append(lineFor(d, editable, "duty"));
    }
    out.push(box);
  }
  return out;
}

function lineFor(f, editable, extraClass = "") {
  if (editable && editing === f.id) return editBox(f);
  const showLabel = !["skill", "tool", "duty", "project", "language", "certification", "summary"].includes(f.field);
  const content = [showLabel ? el("span", { class: "label" }, f.label) : null, el("span", { class: "value" }, factText(f)), tagFor(f)];
  if (!editable) return el("div", { class: `line ${extraClass} ${f.status === "suggested" ? "suggested" : ""}` }, ...content);
  if (f.status === "suggested" || f.status === "needs_spelling") {
    // Lines the student must act on: suggestions to keep, names to check.
    const keepLabel = f.status === "suggested" ? "✓ Keep" : "✓ Spelled right";
    return el("div", { class: `pending ${extraClass}` },
      el("div", { class: "line-text" }, ...content),
      el("div", { class: "btns" },
        el("button", { class: "keep", onclick: () => keep(f.id) }, keepLabel),
        el("button", { onclick: () => { editing = f.id; renderReview(); } }, "✎ Fix"),
        f.status === "suggested" ? el("button", { class: "del", onclick: () => removeLine(f.id) }, "✕ Remove") : null));
  }
  return el("button", { class: `line ${extraClass}`, onclick: () => { editing = f.id; renderReview(); } }, ...content);
}

async function keep(id) {
  try { setState(await api(`${base()}/lines/${id}/keep`, { method: "POST" })); status(""); }
  catch (err) { status(err.message); }
}

async function removeLine(id) {
  try { setState(await api(`${base()}/lines/${id}`, { method: "DELETE" })); status("Removed."); }
  catch (err) { status(err.message); }
}

function editBox(f) {
  const parts = f.field === "experience"
    ? [["value", "Role", f.value], ["employer", "Employer", f.extra.employer || ""], ["duration", "How long", f.extra.duration || ""]]
    : [["value", f.label, f.value]];
  const inputs = parts.map(([part, label, value]) => [part, value, el("input", { value, "aria-label": label, placeholder: label })]);
  const save = async () => {
    try {
      let st = null;
      for (const [part, old, input] of inputs) {
        const value = input.value.trim();
        if (value && value !== old) st = await api(`${base()}/lines/${f.id}`, { method: "PATCH", body: { value, part } });
      }
      editing = null;
      if (st) setState(st); else renderReview();
      status("Saved.");
    } catch (err) { status(err.message); }
  };
  const remove = async () => {
    try { editing = null; setState(await api(`${base()}/lines/${f.id}`, { method: "DELETE" })); status("Removed."); }
    catch (err) { status(err.message); }
  };
  setTimeout(() => inputs[0][2].focus(), 0);
  return el("div", { class: "editbox" },
    ...inputs.map(([, , input]) => input),
    el("div", { class: "btns" },
      el("button", { class: "save", onclick: save }, "Save"),
      el("button", { onclick: () => { editing = null; renderReview(); } }, "Cancel"),
      el("button", { class: "del", onclick: remove }, "Remove")));
}

function renderNotebook() {
  const nb = S.notebook;
  $("draftBtn").hidden = !(S.mode === "live" && nb.checklist.every((c) => c.done));
  const done = nb.checklist.filter((c) => c.done).length;
  $("progress").textContent = `${done}/${nb.checklist.length}`;
  $("checklist").replaceChildren(...nb.checklist.map((c) => el("li", { class: c.done ? "done" : "" }, (c.done ? "✓ " : "") + c.label)));
  const lines = linesBySection(false);
  $("notebookLines").replaceChildren(...(lines.length ? lines : [el("p", { class: "hint" }, "Your answers will appear here.")]));
}

function renderTemplates() {
  const key = previewKey();
  $("templates").replaceChildren(...Object.entries(S.options.templates).map(([id, name]) =>
    el("button", { class: `tpl ${S.design.template === id ? "selected" : ""}`, onclick: () => pickTemplate(id) },
      el("img", { src: `${base()}/preview.png?template=${id}&w=320&v=${key}`, alt: `${name} template`, loading: "lazy" }),
      el("span", {}, name))));
}

async function pickTemplate(id) {
  try {
    await api(`${base()}/design`, { method: "POST", body: { changes: { template: id } } });
    setState(await api(`${base()}/step`, { method: "POST", body: { step: "design" } }));
  } catch (err) { status(err.message); }
}

async function design(changes) {
  try {
    const res = await api(`${base()}/design`, { method: "POST", body: { changes } });
    setState(res.state);
    status(res.result.refused.join(" ") || "Updated.");
  } catch (err) { status(err.message); }
}

function renderDesign() {
  const d = S.design, o = S.options;
  $("designPreview").src = `${base()}/preview.png?w=720&v=${previewKey()}`;
  $("accentRow").replaceChildren(...Object.entries(o.accents).map(([name, hex]) =>
    el("button", { class: `swatch ${d.accent === name ? "selected" : ""}`, style: `background:${hex}`, title: name, "aria-label": name, onclick: () => design({ accent_color: name }) })));
  $("fontRow").replaceChildren(...Object.entries(o.font_pairs).map(([id, label]) =>
    el("button", { class: `chip ${d.font_pair === id ? "selected" : ""}`, onclick: () => design({ font_pair: id }) }, label)));
  $("densityRow").replaceChildren(
    ...Object.entries(o.templates).map(([id, name]) => el("button", { class: `chip ${d.template === id ? "selected" : ""}`, onclick: () => design({ template: id }) }, name)),
    ...["comfortable", "compact"].map((id) => el("button", { class: `chip ${d.density === id ? "selected" : ""}`, onclick: () => design({ density: id }) }, id === "compact" ? "Tight spacing" : "Roomy spacing")));
  $("orderList").replaceChildren(...d.section_order.map((sec, i) => el("li", {},
    el("span", {}, o.sections[sec]),
    el("button", { "aria-label": `Move ${sec} up`, disabled: i === 0, onclick: () => design({ move_section: sec, place: "above", relative_to: d.section_order[i - 1] }) }, "↑"),
    el("button", { "aria-label": `Move ${sec} down`, disabled: i === d.section_order.length - 1, onclick: () => design({ move_section: sec, place: "below", relative_to: d.section_order[i + 1] }) }, "↓"))));
}

function renderReview() {
  const blockers = S.notebook.export_blockers.filter((b) => !b.startsWith("The student has not reviewed"));
  $("blockers").replaceChildren(...blockers.map((b) => el("li", {}, b)));
  $("reviewLines").replaceChildren(...linesBySection(true));
  $("reviewPreview").src = `${base()}/preview.png?w=720&v=${previewKey()}`;
  $("approveBtn").disabled = blockers.length > 0;
}

// ----- navigation and actions -----------------------------------------------------------

for (const btn of document.querySelectorAll(".steps button, [data-goto]")) {
  btn.addEventListener("click", async () => {
    try { setState(await api(`${base()}/step`, { method: "POST", body: { step: btn.dataset.step || btn.dataset.goto } })); status(""); }
    catch (err) { status(err.message); }
  });
}

$("draftBtn").addEventListener("click", async () => {
  $("draftBtn").disabled = true;
  status("Writing your CV… about 20 seconds.");
  try { const res = await api(`${base()}/draft`, { method: "POST" }); setState(res.state); status(res.message); }
  catch (err) { status(err.message); }
  finally { $("draftBtn").disabled = false; }
});

$("approveBtn").addEventListener("click", async () => {
  try { setState(await api(`${base()}/approve`, { method: "POST" })); status("Checked. Now pick a style."); }
  catch (err) { status(err.message); }
});

$("downloadBtn").addEventListener("click", (event) => {
  event.preventDefault();
  window.location.href = `${base()}/cv.pdf`;
});

$("shareBtn").addEventListener("click", async () => {
  try {
    const { url } = await api(`${base()}/share`, { method: "POST" });
    if (navigator.share) {
      await navigator.share({ title: "My CV", text: "My CV:", url }).catch(() => {});
    }
    $("shareResult").replaceChildren(
      "Link (works for 7 days): ", el("a", { href: url, target: "_blank", rel: "noopener" }, url), " · ",
      el("a", { href: `https://wa.me/?text=${encodeURIComponent("My CV: " + url)}`, target: "_blank", rel: "noopener" }, "WhatsApp"), " · ",
      el("a", { href: `mailto:?subject=${encodeURIComponent("My CV")}&body=${encodeURIComponent(url)}` }, "Email"));
  } catch (err) { status(err.message); }
});

$("copyTextBtn").addEventListener("click", async () => {
  try {
    const text = await api(`${base()}/cv.txt`);
    await navigator.clipboard.writeText(text);
    status("Copied. Paste it into the job portal.");
  } catch (err) { status(err.message.includes("clipboard") ? "Copy is blocked by the browser." : err.message); }
});

$("resetBtn").addEventListener("click", async () => {
  if (!confirm("Start over? This clears your notebook and design.")) return;
  stopMic();
  closeLive();
  for (const k of Object.keys(partials)) delete partials[k];
  try { setState(await api(`${base()}/reset`, { method: "POST" })); status("Started over."); }
  catch (err) { status(err.message); }
});

async function sendText() {
  const text = $("textInput").value.trim();
  if (!text) return;
  $("textInput").value = "";
  if (/^(start over|restart|new cv)$/i.test(text)) { $("resetBtn").click(); return; }
  try {
    if (S.mode === "live") {
      await ensureLive();
      ws.send(JSON.stringify({ type: "text", text }));
    } else {
      const res = await api(`${base()}/message`, { method: "POST", body: { text } });
      setState(res.state);
      status(S.step === "interview" ? "" : res.reply);
    }
  } catch (err) { status(err.message); }
}
$("sendBtn").addEventListener("click", sendText);
$("textInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendText(); });

// ----- live voice -----------------------------------------------------------------------

function ensureLive() {
  if (ws && ws.readyState === WebSocket.OPEN && wsReady === true) return Promise.resolve();
  if (wsReady instanceof Promise) return wsReady;
  wsReady = new Promise((resolve, reject) => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/live?session_id=${S.session_id}`);
    status("Connecting…");
    let refusal = "";
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "ready") { wsReady = true; status("Connected. Talk now."); resolve(); }
      else { if (msg.type === "error") refusal = msg.message; onLiveMessage(msg); }
    };
    ws.onclose = () => {
      if (wsReady !== true) reject(new Error(refusal || "Could not connect to the voice service."));
      ws = null; wsReady = null;
      stopMic();
      for (const k of Object.keys(partials)) delete partials[k];
      if (S) renderChat();
    };
  });
  return wsReady;
}

function closeLive() {
  if (ws) { try { ws.send(JSON.stringify({ type: "close" })); ws.close(); } catch (_) {} }
  ws = null; wsReady = null;
}

function onLiveMessage(msg) {
  if (msg.type === "state") setState(msg.state);
  else if (msg.type === "transcript") {
    if (msg.final) {
      delete partials[msg.id];
      if (!S.transcript.some((t) => t.id === msg.id)) S.transcript.push({ id: msg.id, speaker: msg.speaker, text: msg.text });
    } else partials[msg.id] = { speaker: msg.speaker, text: msg.text };
    renderChat();
  } else if (msg.type === "audio") playPcm(msg.data);
  else if (msg.type === "interrupted") stopPlayback();
  else if (msg.type === "tool") status(msg.ok ? "Notebook updated." : `Not saved: ${msg.message}`);
  else if (msg.type === "drafting") status(msg.active ? "Writing your CV… about 20 seconds." : "Your draft CV is ready. Check the highlighted lines.");
  else if (msg.type === "ended") { status(msg.message); stopMic(); closeLive(); }
  else if (msg.type === "error") status(msg.message);
}

async function startMic() {
  if (!navigator.mediaDevices?.getUserMedia) { status("This browser cannot use the microphone. Type instead."); return; }
  try {
    await ensureLive();
    audioCtx = audioCtx || new AudioContext();
    await audioCtx.resume();
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    await audioCtx.audioWorklet.addModule("audio-worklet.js");
    micSource = audioCtx.createMediaStreamSource(micStream);
    micNode = new AudioWorkletNode(audioCtx, "mic-capture");
    micNode.port.onmessage = (event) => onMicFrames(event.data);
    micSource.connect(micNode);
    $("micBtn").classList.add("on");
    status("Listening… tap the mic again to pause.");
  } catch (err) {
    stopMic();
    status(err.name === "NotAllowedError" ? "Microphone permission was refused. You can type instead." : err.message);
  }
}

function stopMic() {
  try { micSource?.disconnect(); micNode?.disconnect(); } catch (_) {}
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = micNode = micSource = null;
  micBuffer = [];
  $("micBtn").classList.remove("on");
}

function onMicFrames(frames) {
  // Downsample to 16 kHz by averaging, then send about every 100 ms.
  const ratio = audioCtx.sampleRate / 16000;
  for (let i = 0; i < frames.length / ratio; i++) {
    const start = Math.floor(i * ratio), end = Math.min(frames.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += frames[j];
    micBuffer.push(sum / Math.max(1, end - start));
  }
  if (micBuffer.length >= 1600 && ws && ws.readyState === WebSocket.OPEN) {
    const pcm = new Int16Array(micBuffer.length);
    micBuffer.forEach((v, i) => { pcm[i] = Math.max(-1, Math.min(1, v)) * 0x7fff; });
    micBuffer = [];
    let binary = "";
    const bytes = new Uint8Array(pcm.buffer);
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    ws.send(JSON.stringify({ type: "audio", data: btoa(binary) }));
  }
}

function playPcm(b64) {
  audioCtx = audioCtx || new AudioContext();
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const pcm = new Int16Array(bytes.buffer, 0, Math.floor(bytes.length / 2));
  const buffer = audioCtx.createBuffer(1, pcm.length, 24000);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) data[i] = pcm[i] / 0x8000;
  const source = audioCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(audioCtx.destination);
  const at = Math.max(audioCtx.currentTime, playTime);
  source.start(at);
  playTime = at + buffer.duration;
  playing.add(source);
  source.onended = () => playing.delete(source);
}

function stopPlayback() {
  for (const s of playing) { try { s.stop(); } catch (_) {} }
  playing.clear();
  playTime = audioCtx ? audioCtx.currentTime : 0;
}

$("micBtn").addEventListener("click", () => {
  if (micStream) { stopMic(); closeLive(); status("Paused. Tap the mic to continue."); }
  else startMic();
});

// ----- resume within this tab -----------------------------------------------------------

(async () => {
  const id = storedId();
  if (!id) return;
  try { showApp(await api(`/api/sessions/${id}`)); } catch (_) { storeId(""); }
})();
