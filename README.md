# ShiftOS

Grid-aware scheduling for AI data centers.

ShiftOS reduces electricity cost and peak demand by coordinating battery arbitrage with flexible AI workloads while protecting inference SLAs and emergency reserve.

The system has two optimization loops: a pre-task planner that uses prices, local demand, and Nemotron-scored news signals to place flexible jobs, and a post-task reconciler that compares planned versus actual energy and triggers replanning when execution deviates.

The engine contains the hackathon MVP scheduler. Run tests with:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

`baseline(scenario)` runs workloads immediately without storage arbitrage. `optimize(scenario)` uses a transparent greedy policy to move flexible workloads into low-price slots and charge/discharge the configured battery.

## Project layout

- `engine/` — scheduling and optimization logic
- `api/` — FastAPI service for scenarios and schedules
- `index.html` — self-contained operator dashboard
- `signals/` — local-demand and Nemotron-compatible news signal adapters
- `spacetime/` — SpacetimeDB TypeScript module for live schedules and telemetry

## Run the API

```bash
pip install fastapi uvicorn pydantic
uvicorn api.main:app --reload
```

Open `index.html` directly for the dashboard prototype.

Set `SPACETIME_URI`, `SPACETIME_DATABASE`, and optionally `SPACETIME_TOKEN` to have the API publish schedules and task results to SpacetimeDB. Set `NEMOTRON_ENDPOINT`, `NEMOTRON_MODEL`, and optionally `NEMOTRON_API_KEY` to score news headlines through an OpenAI-compatible Nemotron endpoint.

Live signal commands:

```bash
PYTHONPATH=. python scripts/ingest_ercot.py --database shiftos --zone HB_NORTH
curl 'http://127.0.0.1:8000/ercot/prices?zone=HB_NORTH'
curl 'http://127.0.0.1:8000/forecast?zone=TOTAL&horizon=8&include_news=false'
```

Because the module lives in `spacetime/`, publish from the repository root with `spacetime publish -p spacetime shiftos`, or from inside that directory with `spacetime publish -p . shiftos`.
