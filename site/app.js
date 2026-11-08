const $ = (selector) => document.querySelector(selector);
const seed = window.ANYTIME_SEED;
const state = { scenario: "oil", worker: "all", type: "all", visible: 18 };
const stopWords = new Set(["the", "a", "an", "to", "of", "in", "on", "at", "is", "was", "were", "are", "did", "do", "does", "what", "which", "how", "why", "can", "you", "me", "about", "this", "that", "there", "with", "after", "before", "from", "for", "have", "has", "who", "where", "when"]);
const synonyms = {
  warm: ["temperature", "airflow", "fan", "cooling", "inlet"], hot: ["temperature", "airflow", "fan", "cooling"],
  leak: ["fluid", "coupling", "seal"], leaking: ["fluid", "coupling", "seal"],
  lost: ["tool", "last", "returned"], find: ["tool", "last", "returned"],
  broken: ["issue", "warning", "open"], changed: ["change", "adjusted", "replaced"],
  handoff: ["handoff", "open", "next"], shift: ["handoff", "open", "next"]
};

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

function terms(question) {
  const basic = (question.toLowerCase().match(/[a-z0-9]+/g) || []).filter(word => word.length > 1 && !stopWords.has(word));
  return [...new Set([...basic, ...basic.flatMap(word => synonyms[word] || [])])];
}

function rank(event, words, question) {
  const equipment = event.equipment.toLowerCase(), note = event.note.toLowerCase(), area = event.area.toLowerCase(), worker = event.worker.toLowerCase();
  let score = 0;
  words.forEach(word => { if (equipment.includes(word)) score += 7; if (note.includes(word)) score += 2; if (area.includes(word)) score += 2; if (worker.includes(word)) score += 4; if (event.kind.includes(word)) score += 2; });
  if (/where|last seen|find/i.test(question) && event.kind === "tool" && score > 0) score += 7;
  if (/unresolved|open|handoff/i.test(question) && event.state === "open") score += 6;
  if (/changed|replaced|adjusted/i.test(question) && event.kind === "change") score += 4;
  if (event.kind === "routine") score = Math.max(0, score - 8);
  return score;
}

function answerFor(question, results, events) {
  const lower = question.toLowerCase();
  const first = results[0];
  if (!first) return "No matching observations were found in this sample shift. Try an asset, worker, tool, or location name.";
  if (/where|last seen|find/i.test(lower)) {
    const tool = results.find(item => item.kind === "tool") || first;
    const latest = events.find(item => item.kind === "tool" && item.equipment === tool.equipment) || tool;
    return `The latest record for ${latest.equipment} places it at ${latest.area} at ${latest.time}. ${latest.note}`;
  }
  if (/who/i.test(lower)) {
    const names = [...new Set(results.map(item => item.worker))].slice(0, 4);
    return `${names.join(", ")} appear in the matching records. Their observations below show what each person documented.`;
  }
  if (/unresolved|open|handoff/i.test(lower)) {
    const open = results.filter(item => item.state === "open");
    if (open.length) return `${open.length} relevant open record${open.length === 1 ? "" : "s"} appear in this result. The latest says: ${open[0].note}`;
  }
  if (state.worker === "all" && state.scenario === "oil" && /pump\s*b/i.test(lower) && /leak|fluid|why/i.test(lower)) {
    return "Fluid remained visible near Pump B after an observed coupling adjustment. The records do not confirm that the repair was completed; the issue was carried into the next shift.";
  }
  if (state.worker === "all" && state.scenario === "datacenter" && /rack\s*d12|\bd12\b/i.test(lower) && /warm|hot|temperature|why/i.test(lower)) {
    return "The records show a fan tray warning and a cold aisle obstruction near D12. After the tray replacement and aisle clearance, the inlet display fell from 31.2 C to 28.7 C; the team kept monitoring it.";
  }
  return `The closest matching observation is from ${first.worker} at ${first.time}: ${first.note}`;
}

function runQuery() {
  const question = $("#query-input").value.trim(); if (!question) return;
  const events = scopedEvents(), words = terms(question);
  const candidateEvents = /unresolved|open|handoff/i.test(question)
    ? [...new Map([...openEvents(events), ...events.filter(event => event.kind === "handoff")].map(event => [event.id, event])).values()]
    : events;
  const ranked = candidateEvents.map(event => ({ event, score: rank(event, words, question) })).filter(result => result.score > 0).sort((a, b) => b.score - a.score || b.event.time.localeCompare(a.event.time));
  const results = ranked.slice(0, 5).map(result => result.event);
  const container = $("#query-result"); container.replaceChildren();
  container.append(make("p", "overline", `SEARCH RESULT · ${ranked.length} MATCHING RECORD${ranked.length === 1 ? "" : "S"}`), make("h3", "", answerFor(question, results, events)));
  container.append(make("p", "result-sub", state.worker === "all" ? `Searching all ${scenario().workers.length} workers` : `Searching ${workerById(state.worker).name}'s records`));
  const list = make("div", "evidence-list");
  results.forEach(event => { const row = make("div", "evidence-row"); row.append(make("div", "evidence-top", `${event.id}  /  ${event.time}  /  ${event.worker}`), make("p", "", event.note)); list.append(row); });
  container.append(list);
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
  $("#query-input").value = current.prompts[0]; runQuery();
}

document.querySelectorAll("[data-scenario]").forEach(button => button.addEventListener("click", () => selectScenario(button.dataset.scenario)));
document.querySelector('[data-worker="all"]').addEventListener("click", () => selectWorker("all"));
$("#worker-search").addEventListener("input", renderWorkers);
$("#type-filter").addEventListener("change", event => { state.type = event.target.value; state.visible = 18; renderTimeline(); });
$("#more-events").addEventListener("click", () => { state.visible += 20; renderTimeline(); });
$("#query-form").addEventListener("submit", event => { event.preventDefault(); runQuery(); });
selectScenario("oil");
