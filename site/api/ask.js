const seed = require("../seed.js");

const stop = new Set(["a", "about", "an", "and", "are", "at", "be", "can", "did", "do", "does", "for", "from", "how", "in", "is", "it", "me", "of", "on", "or", "the", "to", "was", "were", "what", "when", "where", "which", "who", "why", "with", "you"]);
const synonyms = {
  warm: ["temperature", "airflow", "fan", "cooling", "inlet"],
  hot: ["temperature", "airflow", "fan", "cooling", "inlet"],
  leak: ["fluid", "coupling", "seal"],
  leaking: ["fluid", "coupling", "seal"],
  handoff: ["handoff", "open", "next"],
  unresolved: ["open", "issue", "watch", "handoff"],
  changed: ["change", "adjusted", "replaced"],
  find: ["tool", "returned", "last"],
};

function retrieve(question, observations) {
  const words = [...new Set((question.toLowerCase().match(/[a-z0-9]+/g) || [])
    .filter(word => word.length > 1 && !stop.has(word))
    .flatMap(word => [word, ...(synonyms[word] || [])]))];
  const scored = observations.map(event => {
    const equipment = event.equipment.toLowerCase();
    const note = event.note.toLowerCase();
    const area = event.area.toLowerCase();
    const worker = event.worker.toLowerCase();
    let score = 0;
    for (const word of words) {
      if (equipment.includes(word)) score += 8;
      if (note.includes(word)) score += 3;
      if (area.includes(word)) score += 2;
      if (worker.includes(word)) score += 4;
      if (event.kind.includes(word)) score += 2;
    }
    if (/where|last seen|find/i.test(question) && event.kind === "tool" && score) score += 8;
    if (/unresolved|open|handoff|next shift/i.test(question) && event.state === "open") score += 6;
    if (event.kind === "routine") score = Math.max(0, score - 8);
    return { event, score };
  }).filter(item => item.score > 0);
  scored.sort((a, b) => b.score - a.score || b.event.time.localeCompare(a.event.time));
  return scored.slice(0, 18).map(item => item.event).sort((a, b) => a.time.localeCompare(b.time));
}

function send(res, status, data) {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.status(status).json(data);
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return send(res, 405, { error: "Use POST to ask Nemotron." });
  }
  const { question, scenario: scenarioId, workerId = "all" } = req.body || {};
  if (typeof question !== "string" || !question.trim() || question.length > 1000) return send(res, 400, { error: "Enter a question of up to 1,000 characters." });
  const scenario = seed[scenarioId];
  if (!scenario || (workerId !== "all" && !scenario.workers.some(worker => worker.id === workerId))) return send(res, 400, { error: "Select a valid workplace and worker." });
  const endpoint = (process.env.NEMOTRON_ENDPOINT || "https://integrate.api.nvidia.com/v1").replace(/\/+$/, "");
  const key = process.env.NEMOTRON_API_KEY || "";
  if (!process.env.NEMOTRON_ENDPOINT && !key) return send(res, 503, { error: "Nemotron is not configured on the server yet." });
  if (!/^https:\/\//.test(endpoint) && !/^http:\/\/127\.0\.0\.1(?::\d+)?(?:\/|$)/.test(endpoint)) return send(res, 500, { error: "Nemotron endpoint configuration is invalid." });

  const observations = scenario.observations.filter(event => workerId === "all" || event.workerId === workerId);
  const evidence = retrieve(question, observations);
  if (!evidence.length) return send(res, 200, { answer: "I couldn't find a relevant observation in this sample shift.", evidence: [], engine: "Nemotron retrieval" });
  const scope = workerId === "all" ? `all ${scenario.workers.length} workers` : scenario.workers.find(worker => worker.id === workerId).name;
  const context = evidence.map(event => `${event.id} | ${event.time} | ${event.worker} | ${event.area} | ${event.equipment} | ${event.kind} | ${event.state} | ${event.note}`).join("\n");
  const messages = [
    { role: "system", content: "You are Anytime's workplace memory assistant. These are fictional demo observations, not verified real-world facts. Answer the user's question using ONLY the supplied observations. Do not infer that a task was completed from an observed action. If the records do not establish an answer, say what is unknown. Cite specific observation IDs in square brackets, for example [DC-001]. Keep the answer under 140 words. Do not give safety-critical operating instructions. Return only the answer, without reasoning or markdown headings." },
    { role: "user", content: `Workplace: ${scenario.title}\nScope: ${scope}\nQuestion: ${question.trim()}\n\nRelevant observations (chronological):\n${context}` },
  ];
  let upstream;
  try {
    upstream = await fetch(`${endpoint}/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json", ...(key ? { Authorization: `Bearer ${key}` } : {}) },
      body: JSON.stringify({ model: process.env.NEMOTRON_MODEL || "nvidia/nemotron-3-nano-30b-a3b", messages, temperature: 0.2, max_tokens: 550, stream: false }),
      signal: AbortSignal.timeout(28000),
    });
  } catch (error) {
    return send(res, 502, { error: error.name === "TimeoutError" ? "Nemotron timed out. Please try again." : "Nemotron could not be reached. Please try again." });
  }
  if (!upstream.ok) return send(res, 502, { error: `Nemotron returned an error (${upstream.status}). Check the server model configuration.` });
  let payload;
  try { payload = await upstream.json(); } catch { return send(res, 502, { error: "Nemotron returned an unreadable response." }); }
  const content = payload.choices?.[0]?.message?.content;
  const answer = (typeof content === "string" ? content : "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  if (!answer) return send(res, 502, { error: "Nemotron returned an empty answer." });
  const cited = [...answer.matchAll(/\b[A-Z]+-\d+\b/g)].map(match => match[0]);
  const shown = cited.length ? evidence.filter(event => cited.includes(event.id)) : evidence.slice(0, 6);
  return send(res, 200, { answer, evidence: shown, engine: "NVIDIA Nemotron", scope });
};
