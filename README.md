# ShiftOS

Grid-aware scheduling for AI data centers.

ShiftOS reduces electricity cost and peak demand by coordinating battery arbitrage with flexible AI workloads while protecting inference SLAs and emergency reserve.

The engine contains the hackathon MVP scheduler. Run tests with:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

`baseline(scenario)` runs workloads immediately without storage arbitrage. `optimize(scenario)` uses a transparent greedy policy to move flexible workloads into low-price slots and charge/discharge the configured battery.

## Project layout

- `engine/` — scheduling and optimization logic
- `api/` — FastAPI service for scenarios and schedules
- `index.html` — self-contained operator dashboard

## Run the API

```bash
pip install fastapi uvicorn pydantic
uvicorn api.main:app --reload
```

Open `index.html` directly for the dashboard prototype.
