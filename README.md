# ShiftLens

**A shared, evidence-backed memory for industrial shift teams.**

ShiftLens turns observations made during a shift into a searchable team timeline. Workers can ask where a tool was last seen, what was observed around a piece of equipment, or what the previous shift tried. Answers link back to the observations and source frames they use.

## HackUTD prototype

The current local demo includes:

- A persistent SQLite observation timeline shared by browser sessions on this machine.
- Optional still-frame capture from a browser camera, attached to a worker-entered observation.
- Search and question answering with supporting observation links.
- An OpenAI-compatible NVIDIA Nemotron endpoint hook for evidence-grounded reasoning.
- Clearly labeled illustrative sample events when the database is first created.

The current prototype **does not** continuously record video, automatically understand frames, identify people, diagnose equipment, or verify that a repair was completed. Sample events are illustrative. Worker-entered observations are shown as worker-entered, not as AI-verified facts. Review source footage and follow approved procedures.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Camera capture requires localhost or HTTPS and browser permission. Observation metadata and captured frames are stored locally in `data/`.

## Optional Nemotron endpoint

Set the endpoint base URL and model in the server environment:

```bash
export NEMOTRON_ENDPOINT=http://127.0.0.1:8001/v1
export NEMOTRON_MODEL=nvidia/nemotron-3-nano
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The endpoint must implement OpenAI-compatible `/chat/completions`. If it is unavailable, ShiftLens uses evidence retrieval and an extractive local fallback. The status badge distinguishes these paths. The endpoint powers text reasoning only; visual frame extraction is not wired up yet.

## API

- `GET /memory/events` — list observations.
- `POST /memory/events` — save a worker-entered observation and optional captured frame data URL.
- `POST /memory/ask` — retrieve relevant observations and answer with supporting evidence.
- `GET /memory/status` — report memory and model integration status.

## Design principles

- Keep answers traceable to observations and frames.
- Separate what a camera visibly captured from what a worker inferred.
- Show uncertainty and ask for human review on maintenance questions.
- Capture only with worker consent and site approval; use access controls and retention limits before any real deployment.
- Do not use the prototype to issue safety-critical commands or to evaluate worker performance.

The previous ShiftOS energy-arbitrage prototype remains in Git history while this branch pivots to ShiftLens.
