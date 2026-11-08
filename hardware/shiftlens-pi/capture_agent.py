#!/usr/bin/env python3
"""ShiftLens Raspberry Pi camera edge agent (USB/UVC or Limelight).

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


def limelight_results(base_url: str) -> dict | None:
    """Fetch the latest native Limelight CV result; tolerate device/network outages."""
    try:
        response = requests.get(f"{base_url.rstrip('/')}:5807/results", timeout=(1, 2))
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if isinstance(data, dict) and isinstance(data.get("Results"), list):
            data = data["Results"][0] if data["Results"] else {}
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError) as exc:
        LOG.debug("Limelight results unavailable: %s", exc)
        return None


def area_from_fiducials(results: dict | None, tag_map: dict[str, str], fallback: str) -> str:
    for tag in (results or {}).get("Fiducial", []):
        if isinstance(tag, dict):
            area = tag_map.get(str(tag.get("fID", "")))
            if area:
                return area
    return fallback


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
    camera_source = setting("SHIFTLENS_CAMERA_SOURCE", "usb").lower()
    limelight_url = setting("SHIFTLENS_LIMELIGHT_URL", "http://limelight.local").rstrip("/")
    limelight_use_cv = setting("SHIFTLENS_LIMELIGHT_USE_CV", "false").lower() in {
        "1", "true", "yes", "on"
    }
    try:
        tag_map = json.loads(setting("SHIFTLENS_LIMELIGHT_TAG_MAP", "{}"))
        if not isinstance(tag_map, dict):
            raise ValueError("tag map must be a JSON object")
    except ValueError as exc:
        LOG.error("Invalid SHIFTLENS_LIMELIGHT_TAG_MAP: %s", exc)
        return 2
    interval_s = max(5, int(setting("SHIFTLENS_ANALYZE_EVERY_SECONDS", "15")))
    sample_every_s = max(1, int(setting("SHIFTLENS_SAMPLE_EVERY_SECONDS", "1")))
    worker = setting("SHIFTLENS_WORKER", "Worker 01")
    area = setting("SHIFTLENS_AREA", "Unspecified area")
    device_id = setting("SHIFTLENS_DEVICE_ID", "shiftlens-pi-01")
    max_width = max(320, int(setting("SHIFTLENS_FRAME_WIDTH", "640")))
    api_ingest = f"{api_url}/memory/ingest-frames"

    if camera_source == "usb":
        camera = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        source_label = f"USB camera index {camera_index}"
    elif camera_source == "limelight":
        # Limelight 3A serves its MJPEG camera stream on port 5800.
        camera = cv2.VideoCapture(f"{limelight_url}:5800", cv2.CAP_FFMPEG)
        source_label = f"Limelight stream at {limelight_url}:5800"
    else:
        LOG.error("SHIFTLENS_CAMERA_SOURCE must be 'usb' or 'limelight'.")
        return 2
    while RUNNING and not camera.isOpened():
        LOG.warning("Could not open %s; retrying in 5 seconds. Check device IP and network connectivity.", source_label)
        camera.release()
        time.sleep(5)
        if RUNNING:
            camera = (cv2.VideoCapture(camera_index, cv2.CAP_V4L2) if camera_source == "usb"
                      else cv2.VideoCapture(f"{limelight_url}:5800", cv2.CAP_FFMPEG))
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, max_width)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not RUNNING:
        camera.release()
        return 0
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, max_width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    samples: deque[tuple[str, str]] = deque(maxlen=5)
    last_sample = 0.0
    last_attempt = 0.0
    latest_ll: dict | None = None
    LOG.info("CAMERA ACTIVE · source=%s · audio disabled · device=%s", source_label, device_id)
    if camera_source == "limelight":
        LOG.info("Limelight native CV metadata: %s", "enabled" if limelight_use_cv else "disabled (camera-only)")
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
                    if camera_source == "limelight" and limelight_use_cv:
                        latest_ll = limelight_results(limelight_url)
                last_sample = now

            if len(samples) == samples.maxlen and now - last_attempt >= interval_s:
                payload = {
                    "frames": [value for _, value in samples],
                    "observed_at": samples[-1][0],
                    "worker": worker,
                    "area": area,
                    "device_id": device_id,
                }
                if camera_source == "limelight" and limelight_use_cv:
                    latest_ll = limelight_results(limelight_url) or latest_ll
                    if latest_ll:
                        payload["limelight_results"] = latest_ll
                        payload["area"] = area_from_fiducials(latest_ll, tag_map, area)
                last_attempt = now
                try:
                    response = requests.post(api_ingest, json=payload,
                                             headers={"Authorization": f"Bearer {token}"}, timeout=(5, 120))
                    response.raise_for_status()
                    result = response.json()
                    event = result.get("event", {})
                    LOG.info("Observation draft saved · id=%s · model=%s · Limelight CV=%s · review required",
                             event.get("id", "unknown"), result.get("model", "unknown"),
                             "attached" if payload.get("limelight_results") else "unavailable")
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
