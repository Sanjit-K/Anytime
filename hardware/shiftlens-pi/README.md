# Anytime Raspberry Pi camera agent

This edge agent targets a Raspberry Pi 5 (Pi 4 should also work) with either a USB/UVC webcam or a Limelight 3A. It samples five still frames at one-second intervals into a RAM-only buffer, submits that short sequence to the Anytime API on the Mac every 15 seconds, and then discards the successful batch. The API asks Nemotron Nano 12B v2 VL for a structured observation draft, attaches the latest frame, and adds it to the shared timeline. If Nemotron is unavailable, the frame and received Limelight pose are still stored for manual review.

In Limelight mode the Pi reads the camera stream on port `5800` and can poll the JSON results API on port `5807`. Set `SHIFTLENS_LIMELIGHT_USE_CV=true` to send AprilTag and botpose results with sampled frames. Limelight must have its camera mount pose and a matching field map configured in its web interface before it reports a useful field-space botpose. Limelight outputs are not proof of a condition or action.

Audio is not captured. The Pi does not save video to disk. On a network error, only the most recent five frames stay in memory for retry. Do not expose the unauthenticated dashboard/API to the public internet; device ingestion uses a shared bearer token.

## Install on the Pi

Copy this directory onto the Raspberry Pi, connect the webcam or put the Limelight and Pi on the same network, then:

```bash
cd hardware/shiftlens-pi
sudo ./install.sh
sudo nano /etc/shiftlens/shiftlens-pi.env
```

Set `SHIFTLENS_API_URL` to the Mac's IP address on the same trusted Wi-Fi or personal hotspot. Set `SHIFTLENS_INGEST_TOKEN` to the same random token configured on the Mac. Give every physical camera a unique `SHIFTLENS_DEVICE_ID` and set `SHIFTLENS_WORKER` to the employee wearing/using it; use the same device ID when registering it in the dashboard. Multiple devices can point at the same API. For a Limelight, set `SHIFTLENS_CAMERA_SOURCE=limelight`, `SHIFTLENS_LIMELIGHT_URL` to its host/IP without a port, and `SHIFTLENS_LIMELIGHT_USE_CV=true`. Keep the file private (`0600`). Then run:

```bash
sudo systemctl enable --now shiftlens-pi
journalctl -u shiftlens-pi -f
```

The service starts at boot. It logs when camera sampling is active and reports observation IDs, but never logs image contents or the token. The Team timeline combines events from all devices and can filter by employee or camera ID.

## Mac side

Configure these server environment variables in the ignored local `.env`:

```dotenv
NEMOTRON_VISION_ENDPOINT=http://127.0.0.1:8001/v1
NEMOTRON_VISION_MODEL=nvidia/nemotron-nano-12b-v2-vl
SHIFTLENS_INGEST_TOKEN=<same-random-token-as-the-Pi>
```

Start the API so the Pi can reach it over the trusted local network:

```bash
set -a; source .env; set +a
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Forward the Brev NIM port to Mac port 8001. A personal hotspot is often simpler than event Wi-Fi that isolates connected devices. The Pi needs no NVIDIA credentials; the NGC credential stays on the Brev NIM machine.

## Settings

See `shiftlens-pi.env.example`. `SHIFTLENS_ANALYZE_EVERY_SECONDS` controls request cadence (minimum 5 seconds); `SHIFTLENS_SAMPLE_EVERY_SECONDS` defaults to 1 second. Each VLM response is a draft and Limelight detections can be wrong; review them in the Anytime dashboard. USB webcam mode remains the default.

### Example for a second employee camera

Use a separate Pi/service installation and set unique values such as:

```dotenv
SHIFTLENS_WORKER=Worker 02
SHIFTLENS_DEVICE_ID=worker-02-chest-camera
SHIFTLENS_API_URL=http://<mac-lan-ip>:8000
```

Keep the API URL and ingest token shared for this prototype. Each event is indexed by both the worker and device so the UI can show the combined timeline or either individual stream.
