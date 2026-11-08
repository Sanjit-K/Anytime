const $ = (selector) => document.querySelector(selector);
const seed = window.ANYTIME_SEED;
const state = { scenario: "oil", worker: "all", type: "all", visible: 18 };
let queryVersion = 0;

function scenario() { return seed[state.scenario]; }
function scopedEvents() { return scenario().observations.filter(event => state.worker === "all" || event.workerId === state.worker); }
function openEvents(events) {
  const latest = new Map();
  events.filter(event => event.state === "open" || event.state === "resolved").forEach(event => {
    if (!latest.has(event.equipment)) latest.set(event.equipment, event);
  });
  return [...latest.values()].filter(event => event.state === "open");
}
function make(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
function workerById(id) { return scenario().workers.find(worker => worker.id === id); }

function renderWorkers() {
  const current = scenario();
  $("#worker-count").textContent = `${current.workers.length} workers`;
  $("#all-count").textContent = current.observations.length;
  document.querySelector('[data-worker="all"]').classList.toggle("active", state.worker === "all");
  const list = $("#worker-list"); list.replaceChildren();
  const term = $("#worker-search").value.trim().toLowerCase();
  current.workers.filter(worker => `${worker.name} ${worker.role} ${worker.area}`.toLowerCase().includes(term)).forEach(worker => {
    const button = make("button", `worker-button${state.worker === worker.id ? " active" : ""}`);
    button.type = "button"; button.dataset.worker = worker.id;
    button.append(make("span", "worker-avatar", worker.name.split(" ").map(part => part[0]).join("")));
    const copy = make("span", "worker-copy"); copy.append(make("strong", "", worker.name), make("small", "", `${worker.role} · ${worker.area}`));
    button.append(copy, make("span", "worker-events", current.observations.filter(event => event.workerId === worker.id).length));
    button.addEventListener("click", () => selectWorker(worker.id)); list.append(button);
  });
  const mobile = $("#mobile-worker");
  if (mobile) { mobile.replaceChildren(new Option("Entire team", "all"), ...current.workers.map(worker => new Option(worker.name, worker.id))); mobile.value = state.worker; }
}

function renderMetrics() {
  const events = scopedEvents();
  $("#metric-events").textContent = events.length;
  $("#metric-workers").textContent = state.worker === "all" ? scenario().workers.length : 1;
  $("#metric-flags").textContent = openEvents(events).length;
  $("#metric-tools").textContent = new Set(events.filter(event => event.kind === "tool").map(event => event.equipment)).size;
}

function renderPrompts() {
  const row = $("#prompt-row"); row.replaceChildren();
  scenario().prompts.forEach(prompt => {
    const button = make("button", "", prompt); button.type = "button";
    button.addEventListener("click", () => { $("#query-input").value = prompt; runQuery(); }); row.append(button);
  });
}

function renderInsights() {
  const events = scopedEvents();
  const flags = $("#open-flags"); flags.replaceChildren();
  const seen = new Set();
  openEvents(events).forEach(event => {
    if (seen.has(event.equipment) || seen.size >= 5) return;
    seen.add(event.equipment); const row = make("div", "flag-row");
    row.append(make("strong", "", event.equipment), make("p", "", event.note), make("div", "flag-time", `${event.time} · ${event.worker}`)); flags.append(row);
  });
  if (!flags.children.length) flags.append(make("p", "empty", "No open flags in this scope."));
  const tools = $("#tool-locations"); tools.replaceChildren();
  const toolNames = new Set();
  events.filter(event => event.kind === "tool").forEach(event => {
    if (toolNames.has(event.equipment) || toolNames.size >= 5) return;
    toolNames.add(event.equipment); const row = make("div", "tool-row");
    row.append(make("strong", "", event.equipment), make("p", "", `${event.area} · last record ${event.time}`)); tools.append(row);
  });
  if (!tools.children.length) tools.append(make("p", "empty", "No tool sightings in this scope."));
}

function renderTimeline() {
  const events = scopedEvents().filter(event => state.type === "all" || event.kind === state.type);
  const list = $("#timeline"); list.replaceChildren();
  events.slice(0, state.visible).forEach(event => {
    const row = make("article", "event"); row.append(make("time", "event-time", event.time));
    const body = make("div", "event-body"); const title = make("div", "event-title");
    title.append(make("span", "", event.equipment), make("span", `kind ${event.kind}`, event.kind));
    body.append(title, make("p", "event-note", event.note), make("div", "event-meta", `${event.worker} · ${event.area} · ${event.id} · ${event.camera}`));
    row.append(body); list.append(row);
  });
  if (!events.length) list.append(make("div", "empty", "No observations match this filter."));
  $("#more-events").hidden = events.length <= state.visible;
  $("#timeline-title").textContent = state.worker === "all" ? "Team timeline" : `${workerById(state.worker).name}'s timeline`;
  $("#timeline-subtitle").textContent = `${events.length} observations in this view, newest first.`;
}

async function runQuery() {
  const question = $("#query-input").value.trim(); if (!question) return;
  const version = ++queryVersion;
  const container = $("#query-result"); container.replaceChildren();
  container.append(make("p", "overline", "ASKING NVIDIA NEMOTRON"), make("h3", "", "Retrieving relevant shift records and reasoning over them…"));
  const button = $("#query-form button"); button.disabled = true;
  try {
    const response = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, scenario: state.scenario, workerId: state.worker }) });
    const data = await response.json();
    if (version !== queryVersion) return;
    if (!response.ok) throw new Error(data.error || "Nemotron could not answer right now.");
    container.replaceChildren(make("p", "overline", `${data.engine.toUpperCase()} · ${data.evidence.length} SOURCE RECORD${data.evidence.length === 1 ? "" : "S"}`), make("h3", "", data.answer));
    container.append(make("p", "result-sub", state.worker === "all" ? `Across all ${scenario().workers.length} workers` : `From ${workerById(state.worker).name}'s records`));
    const list = make("div", "evidence-list");
    data.evidence.forEach(event => { const row = make("div", "evidence-row"); row.append(make("div", "evidence-top", `${event.id}  /  ${event.time}  /  ${event.worker}`), make("p", "", event.note)); list.append(row); });
    container.append(list);
  } catch (error) {
    if (version !== queryVersion) return;
    container.replaceChildren(make("p", "overline", "NEMOTRON UNAVAILABLE"), make("h3", "", error.message));
  } finally {
    if (version === queryVersion) button.disabled = false;
  }
}

function selectWorker(id) {
  state.worker = id; state.visible = 18;
  renderWorkers(); renderMetrics(); renderInsights(); renderTimeline();
  $("#query-scope").textContent = id === "all" ? "Searching the entire team" : `Searching ${workerById(id).name}'s observations`;
  if ($("#query-input").value.trim()) runQuery();
}

function selectScenario(id) {
  state.scenario = id; state.worker = "all"; state.type = "all"; state.visible = 18;
  $("#type-filter").value = "all"; $("#worker-search").value = "";
  document.querySelectorAll("[data-scenario]").forEach(button => { const active = button.dataset.scenario === id; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  const current = scenario();
  $("#scenario-label").textContent = current.title.toUpperCase();
  $("#scenario-title").textContent = `${current.title} memory`;
  $("#scenario-description").textContent = current.subtitle;
  renderWorkers(); renderMetrics(); renderInsights(); renderTimeline(); renderPrompts();
  $("#query-scope").textContent = "Searching the entire team";
  queryVersion++;
  $("#query-form button").disabled = false;
  $("#query-input").value = "";
  $("#query-result").replaceChildren(make("p", "result-sub", "Ask Nemotron about a tool, asset, worker, or shift handoff."));
}

document.querySelectorAll("[data-scenario]").forEach(button => button.addEventListener("click", () => selectScenario(button.dataset.scenario)));
document.querySelector('[data-worker="all"]').addEventListener("click", () => selectWorker("all"));
$("#worker-search").addEventListener("input", renderWorkers);
$("#type-filter").addEventListener("change", event => { state.type = event.target.value; state.visible = 18; renderTimeline(); });
$("#more-events").addEventListener("click", () => { state.visible += 20; renderTimeline(); });
$("#query-form").addEventListener("submit", event => { event.preventDefault(); runQuery(); });
selectScenario("oil");
