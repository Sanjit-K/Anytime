#!/usr/bin/env python3
"""ShiftLens Raspberry Pi USB-camera edge agent.

Samples a short, in-memory frame window and posts it to the ShiftLens API for
human-reviewed Nemotron description. Audio is never captured or transmitted.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone

import cv2
import requests

LOG = logging.getLogger("shiftlens-pi")
RUNNING = True


def stop(_signum, _frame):
    global RUNNING
    RUNNING = False


def setting(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def main() -> int:
    logging.basicConfig(level=setting("SHIFTLENS_LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    api_url = setting("SHIFTLENS_API_URL", "").rstrip("/")
    token = setting("SHIFTLENS_INGEST_TOKEN", "")
    if not api_url or not token:
        LOG.error("Set SHIFTLENS_API_URL and SHIFTLENS_INGEST_TOKEN before starting.")
        return 2

    camera_index = int(setting("SHIFTLENS_CAMERA_INDEX", "0"))
    interval_s = max(5, int(setting("SHIFTLENS_ANALYZE_EVERY_SECONDS", "15")))
    sample_every_s = max(1, int(setting("SHIFTLENS_SAMPLE_EVERY_SECONDS", "1")))
    worker = setting("SHIFTLENS_WORKER", "Worker 01")
    area = setting("SHIFTLENS_AREA", "Unspecified area")
    device_id = setting("SHIFTLENS_DEVICE_ID", "shiftlens-pi-01")
    max_width = max(320, int(setting("SHIFTLENS_FRAME_WIDTH", "640")))
    api_ingest = f"{api_url}/memory/ingest-frames"

    camera = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, max_width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not camera.isOpened():
        LOG.error("Could not open USB camera index %s. Check /dev/video* and the video group.", camera_index)
        return 3

    samples: deque[tuple[str, str]] = deque(maxlen=5)
    last_sample = 0.0
    last_attempt = 0.0
    LOG.info("CAMERA ACTIVE · sampling enabled · audio disabled · device=%s", device_id)
    LOG.info("At most five JPEG frames remain in RAM; they are sent only to %s", api_ingest)

    try:
        while RUNNING:
            ok, frame = camera.read()
            if not ok:
                LOG.warning("Camera frame unavailable; retrying")
                time.sleep(1)
                continue
            now = time.monotonic()
            if now - last_sample >= sample_every_s:
                height, width = frame.shape[:2]
                if width > max_width:
                    new_height = max(1, round(height * max_width / width))
                    frame = cv2.resize(frame, (max_width, new_height), interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 55])
                if ok:
                    data_url = "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
                    timestamp = datetime.now(timezone.utc).isoformat()
                    samples.append((timestamp, data_url))
                last_sample = now

            if len(samples) == samples.maxlen and now - last_attempt >= interval_s:
                payload = {
                    "frames": [value for _, value in samples],
                    "observed_at": samples[-1][0],
                    "worker": worker,
                    "area": area,
                    "device_id": device_id,
                }
                last_attempt = now
                try:
                    response = requests.post(api_ingest, json=payload,
                                             headers={"Authorization": f"Bearer {token}"}, timeout=(5, 120))
                    response.raise_for_status()
                    result = response.json()
                    event = result.get("event", {})
                    LOG.info("Observation draft saved · id=%s · model=%s · review required",
                             event.get("id", "unknown"), result.get("model", "unknown"))
                    samples.clear()
                except requests.RequestException as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    LOG.warning("Upload failed%s; retaining only the latest in-memory frame window: %s",
                                f" (HTTP {status})" if status else "", exc)
                except (ValueError, json.JSONDecodeError) as exc:
                    LOG.warning("API returned an unreadable response; retaining frame window: %s", exc)
    finally:
        camera.release()
        LOG.info("Camera stopped; in-memory frame window discarded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
