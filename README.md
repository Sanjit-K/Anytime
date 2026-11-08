# Anytime

Anytime is a shared, evidence-backed memory for industrial work teams. Camera agents add time-stamped observations and source frames. Workers can search the combined shift history, review individual camera timelines, label tools for a local YOLO detector, and inspect Limelight AprilTag pose data on a floor map.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000`. Set an ingestion bearer token and optional Nemotron endpoint in the server environment:

```dotenv
SHIFTLENS_INGEST_TOKEN=<long-random-token>
NEMOTRON_VISION_ENDPOINT=http://127.0.0.1:8001/v1
NEMOTRON_VISION_MODEL=nvidia/nemotron-nano-12b-v2-vl
```

If Nemotron is offline, camera frames and AprilTag poses are still saved; the observation is marked as needing manual review. Text questions fall back to evidence retrieval.

## Connect cameras

In **Cameras**, register a camera ID and worker. A Limelight can use its LAN MJPEG stream URL (typically `http://limelight.local:5800`) for preview and connection checks. For Raspberry Pi cameras, install [`hardware/shiftlens-pi/`](hardware/shiftlens-pi/README.md), set a unique `SHIFTLENS_DEVICE_ID` and worker name, and point it at this API with the ingestion token. For Limelight capture, set `SHIFTLENS_CAMERA_SOURCE=limelight` and `SHIFTLENS_LIMELIGHT_USE_CV=true` so the edge agent also uploads native AprilTag/pose results.

Every camera ID should match its edge agent's device ID. Each upload is indexed by worker and camera for an overall feed or an individual timeline. SQLite, frames, labeled samples, and trained weights stay in the local `data/` directory.

## AprilTag location and item estimates

The **Map & location** view stores site dimensions and tag anchor coordinates. Configure the same tag map and camera mount pose in the Limelight web interface. Limelight only emits a field-space `botpose` after its camera-to-robot mount pose and AprilTag field map are set. Anytime records that pose and applies the per-camera map translation/rotation. Set the Anytime map offsets to align Limelight's field origin to the floor plan.

The map's green markers are Limelight camera poses; for a wearable camera, this approximates the worker's position. Blue item markers are rough monocular estimates that require a trained detector, known object width, camera horizontal FOV, and a current Limelight pose. The UI shows an uncertainty radius; these are not precision measurements and can be wrong when the object is tilted, occluded, or not at the assumed depth.

## Train a tool detector

Install the optional detector dependencies:

```bash
pip install -r vision-requirements.txt
```

In **Tool detector**, upload varied images for each class and draw a box around each visible item. Save boxes, then start training. Training runs locally with Ultralytics YOLO and writes weights under `data/tool_models/`. At least five labeled images are required by the current training job; more varied images per class will improve results. The active model is applied to later Pi uploads.

## API overview

- `POST /memory/cameras`, `GET /memory/cameras`, `POST /memory/cameras/{id}/check` — register and check cameras.
- `GET /memory/events`, `POST /memory/events`, `POST /memory/ask` — shared events, manual events, and evidence-grounded questions.
- `POST /memory/ingest-frames` — token-protected Pi ingestion, optional Limelight results, observations, frame storage, and detector estimates.
- `GET /memory/map`, `PUT /memory/map` — floor plan and AprilTag anchors.
- `GET/POST /memory/tools/samples`, `PUT /memory/tools/samples/{id}/boxes`, `PUT /memory/tools/classes` — image collection and annotations.
- `POST /memory/tools/train`, `GET /memory/tools/train-status`, `POST /memory/tools/detect` — YOLO training and inference.
- `POST /memory/describe-frame`, `GET /memory/status` — Nemotron visual description and service status.

## Limitations

The current prototype uses one local SQLite database and a shared device token. Use a trusted LAN. A Limelight pose is only meaningful after its map and mount calibration are configured. Video observations are drafts that require human review; do not use Anytime to issue safety-critical instructions or assess employee performance.
