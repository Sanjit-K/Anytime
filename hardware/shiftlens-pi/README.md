# ShiftLens Raspberry Pi camera agent

This edge agent targets a Raspberry Pi 5 (Pi 4 should also work) with a USB/UVC webcam. It samples five still frames at one-second intervals into a RAM-only buffer, submits that short sequence to the ShiftLens API on the Mac every 15 seconds, and then discards the successful batch. The API asks Nemotron Nano 12B v2 VL for a structured observation draft, attaches the latest frame, and adds it to the shared timeline. The worker must review AI drafts.

Audio is not captured. The Pi does not save video to disk. On a network error, only the most recent five frames stay in memory for retry. Do not expose the unauthenticated dashboard/API to the public internet; device ingestion uses a shared bearer token.

## Install on the Pi

Copy this directory onto the Raspberry Pi, connect the webcam, then:

```bash
cd hardware/shiftlens-pi
sudo ./install.sh
sudo nano /etc/shiftlens/shiftlens-pi.env
```

Set `SHIFTLENS_API_URL` to the Mac's IP address on the same trusted Wi-Fi or personal hotspot. Set `SHIFTLENS_INGEST_TOKEN` to the same random token configured on the Mac. Keep the file private (`0600`). Then run:

```bash
sudo systemctl enable --now shiftlens-pi
journalctl -u shiftlens-pi -f
```

The service starts at boot. It logs when camera sampling is active and reports observation IDs, but never logs image contents or the token.

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

See `shiftlens-pi.env.example`. `SHIFTLENS_ANALYZE_EVERY_SECONDS` controls request cadence (minimum 5 seconds); `SHIFTLENS_SAMPLE_EVERY_SECONDS` defaults to 1 second. Each VLM response is a draft—not proof of an action, condition, or repair. Review it in the ShiftLens dashboard.
