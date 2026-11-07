# ShiftOS

ShiftOS is a local hardware-in-the-loop electricity arbitrage experiment. A bounded SHA-256 compute job runs on an attached Arduino UNO Q. The dashboard pairs its measured runtime with clearly editable wattage assumptions, current published ERCOT HB_NORTH prices, and a virtual battery model. It visualizes the difference between grid-only and simulated storage dispatch.

This proof of concept estimates power and energy; it has no power meter and does not switch electrical power. Its virtual battery is independent of the MacBook battery. Mac charge percentage and power source are read from macOS, but never controlled. ERCOT hub prices are a wholesale reference, not a residential tariff or actual electricity trade. Storage begins with a nonzero charge, whose replacement cost is included in the modeled comparison. If prices are missing or stale, cost and savings are unavailable instead of extrapolated.

## Project layout

- `engine/` — scheduling and optimization logic
- `api/` — FastAPI service for scenarios and schedules
- `index.html` — self-contained operator dashboard
- `signals/` — local-demand and Nemotron-compatible news signal adapters
- `spacetime/` — SpacetimeDB TypeScript module for live schedules and telemetry

## Run the API

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload
```

Open http://127.0.0.1:8000. Connect the UNO Q with USB debugging (ADB) enabled. The dashboard will identify an Arduino Linux processor before it permits a board job; it never silently substitutes Mac compute. Press **Start job** to launch a bounded job (5–300 active seconds). Pause, resume, or stop are sent to the worker and acknowledged from device telemetry.

## Local physical proof of concept

The application reads the current day's public ERCOT 15-minute HB_NORTH settlement point intervals and refreshes every five minutes. The background clock integrates the experiment once per second; browser refreshes only read a snapshot. Price data older than 45 minutes pauses arbitrage. The automatic dispatch rule uses observed price quartiles and an explicit round-trip efficiency input; it is a heuristic, not a forecast or optimizer.

```bash
uvicorn api.main:app
```

Job measurements are hash counts, active time and CPU time. Idle/active watts and battery capacity are assumptions and editable in the dashboard. Experiment costs use `USD/MWh × Wh / 1,000,000`; the baseline and storage case model the same estimated work at the observed wholesale price. The ledger includes losses and the cost to replace depleted initial battery energy. It represents modeled energy costs, not demonstrated savings on a real bill.

To save sanitized experiment snapshots to the existing public SpacetimeDB module, start the API with:

```bash
SPACETIME_URI=https://maincloud.spacetimedb.com SPACETIME_DATABASE=shiftos uvicorn api.main:app
```

The dashboard reports the last confirmed saved sample and any write error. Snapshots omit serial numbers, process IDs and local file paths. No cloud connection is claimed when those environment variables are absent.

The repo also includes an experimental ERCOT actual-load trend endpoint. Its trend output is not a market price forecast and does not control this comparison.

## Optional live Nemotron news scoring through Brev

Deploy or start an NVIDIA NIM with a Nemotron model on a Brev instance, then forward its port to this Mac. Brev NIM serves an OpenAI-compatible chat API on port 8000. Keep ShiftOS on port 8000 and forward the remote NIM to a different local port, for example:

```bash
brev port-forward <your-instance> --port 8001:8000
cp .env.example .env
set -a; source .env; set +a
uvicorn api.main:app
```

`cp` only provides a starting file; edit `.env` to set the endpoint URL and actual model served by your Brev NIM. The documented NIM chat route is OpenAI-compatible, and Brev exposes it through port forwarding or a tunnel ([Brev NIM deployment guide](https://docs.nvidia.com/brev/guides/inference-deployment/deploying-nims)). If the NIM requires authentication, set `NEMOTRON_API_KEY` in the environment; do not place a key in the dashboard or commit it. `/nemotron/status` reports configuration without revealing the endpoint, while **Fetch headlines & score with Nemotron** makes a real inference request. An unconfigured, unreachable, or invalid response is shown as unavailable; headline context remains qualitative and is not used as a numeric load or price forecast.

### Brev L40S Nemotron NIM

For a Brev L40S instance (48 GB VRAM), forward local port `8001` to remote port `8000`. To finish the NIM setup:

1. Generate an NGC API key in the NVIDIA NGC account, under profile → Setup → Generate API Key. NVIDIA exposes this key once. Do not send it through chat or put it in Git.
2. In a Mac Terminal, run `brev shell <your-instance-name>`, then `bash /home/ubuntu/setup_brev_nemotron.sh`. Enter the key at the hidden prompt. The script logs into `nvcr.io`, downloads `nvcr.io/nim/nvidia/nemotron-3-nano:latest`, starts the NIM, and waits for its ready check. The key is used by the container to fetch model files and is retained in its Docker environment on the Brev VM.
3. Once ready, set `NEMOTRON_ENDPOINT=http://127.0.0.1:8001/v1` and `NEMOTRON_MODEL=nvidia/nemotron-3-nano` in the local ignored `.env`, restart the ShiftOS API with that shell environment, and use **Fetch headlines & score with Nemotron**.

Brev's current listing for the chosen stoppable L40S is $1.74/hour. Stop the instance in Brev when you are finished; the port-forward and local app need it running to call Nemotron.

Live signal commands:

```bash
PYTHONPATH=. python scripts/ingest_ercot.py --database shiftos --zone HB_NORTH
curl 'http://127.0.0.1:8000/ercot/prices?zone=HB_NORTH'
curl 'http://127.0.0.1:8000/forecast?zone=TOTAL&horizon=8&include_news=false'
```

Because the module lives in `spacetime/`, publish from the repository root with `spacetime publish -p spacetime shiftos`, or from inside that directory with `spacetime publish -p . shiftos`.
