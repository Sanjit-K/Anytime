"""Evidence-first local workplace memory API for Anytime."""
from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.request
import uuid
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/memory", tags=["Anytime workplace memory"])
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("SHIFTLENS_DATA_DIR", str(ROOT / "data")))
FRAMES = DATA / "frames"
DB = DATA / "shiftlens.sqlite3"
_TRAIN_STATE: dict[str, Any] = {"status": "idle", "message": "No training run"}
_TRAIN_LOCK = threading.Lock()
_TOOL_MODEL = None
_TOOL_MODEL_PATH: Optional[str] = None
_TOOL_MODEL_LOCK = threading.Lock()


def _db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS observations (
      id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, worker TEXT NOT NULL,
      area TEXT NOT NULL, equipment TEXT NOT NULL, kind TEXT NOT NULL,
      note TEXT NOT NULL, confidence REAL NOT NULL, frame TEXT, origin TEXT NOT NULL,
      camera_id TEXT NOT NULL DEFAULT 'local-manual', source_data_json TEXT
    )""")
    columns = {row[1] for row in con.execute("PRAGMA table_info(observations)")}
    if "source_data_json" not in columns:
        con.execute("ALTER TABLE observations ADD COLUMN source_data_json TEXT")
    if "camera_id" not in columns:
        con.execute("ALTER TABLE observations ADD COLUMN camera_id TEXT NOT NULL DEFAULT 'local-manual'")
        # Recover device labels from records created before camera IDs were stored separately.
        for row in con.execute("SELECT id, origin FROM observations WHERE origin LIKE 'ShiftLens camera · %'").fetchall():
            device_id = str(row[1]).split(" · ")[1].strip()
            con.execute("UPDATE observations SET camera_id=? WHERE id=?", (device_id, row[0]))
    con.execute("CREATE INDEX IF NOT EXISTS observations_timeline_idx ON observations(camera_id, worker, observed_at DESC)")
    con.execute("DELETE FROM observations WHERE origin='illustrative demo data'")
    con.execute("""CREATE TABLE IF NOT EXISTS camera_registry (
      camera_id TEXT PRIMARY KEY, worker TEXT NOT NULL, camera_type TEXT NOT NULL DEFAULT 'pi',
      stream_url TEXT, area TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'registered',
      map_x REAL, map_y REAL, map_yaw REAL NOT NULL DEFAULT 0, mount_yaw REAL NOT NULL DEFAULT 0,
      hfov_deg REAL, camera_height_m REAL, updated_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS camera_poses (
      id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL, worker TEXT NOT NULL,
      observed_at TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL, yaw REAL NOT NULL,
      tag_count INTEGER, source TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS camera_poses_time_idx ON camera_poses(observed_at DESC)")
    con.execute("""CREATE TABLE IF NOT EXISTS tool_samples (
      id TEXT PRIMARY KEY, class_name TEXT NOT NULL, filename TEXT NOT NULL,
      width INTEGER NOT NULL, height INTEGER NOT NULL, boxes_json TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS tool_classes (
      class_name TEXT PRIMARY KEY, width_m REAL, updated_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS site_map (
      id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, width_m REAL NOT NULL,
      height_m REAL NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL
    )""")
    if not con.execute("SELECT id FROM site_map WHERE id=1").fetchone():
        con.execute("INSERT INTO site_map(id,name,width_m,height_m,tags_json,updated_at) VALUES(1,'Work area',10,8,'[]',?)", (datetime.now(timezone.utc).isoformat(),))
    return con


class ObservationIn(BaseModel):
    worker: str = Field(default="Worker 01", max_length=80)
    area: str = Field(min_length=1, max_length=120)
    equipment: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="observation", max_length=40)
    note: str = Field(min_length=3, max_length=2000)
    confidence: float = Field(default=1, ge=0, le=1)
    frame_data_url: Optional[str] = None
    observed_at: Optional[str] = None
    origin: str = Field(default="captured by worker", max_length=160)
    camera_id: str = Field(default="local-manual", max_length=100)
    source_data: Optional[dict[str, Any]] = None


class FrameDescriptionIn(BaseModel):
    frames: list[str] = Field(min_length=1, max_length=5)
    observed_at: Optional[str] = None
    limelight_hints: Optional[dict[str, Any]] = None
    auto_triage: bool = False
    task_context: Optional[str] = Field(default=None, max_length=8000)


class FrameIngestIn(FrameDescriptionIn):
    worker: str = Field(default="Worker 01", max_length=80)
    area: str = Field(default="Unspecified area", max_length=120)
    device_id: str = Field(default="shiftlens-pi", max_length=80)
    camera_id: Optional[str] = Field(default=None, max_length=100)
    limelight_results: Optional[dict[str, Any]] = None


class QuestionIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    scope: str = Field(default="team", pattern="^team$")
    camera_id: Optional[str] = Field(default=None, max_length=100)
    worker: Optional[str] = Field(default=None, max_length=80)


class CameraIn(BaseModel):
    camera_id: str = Field(min_length=2, max_length=100)
    worker: str = Field(min_length=1, max_length=80)
    camera_type: str = Field(default="pi", pattern="^(pi|limelight|browser)$")
    stream_url: Optional[str] = Field(default=None, max_length=300)
    area: str = Field(default="", max_length=120)
    map_x: Optional[float] = Field(default=None, ge=0, le=1000)
    map_y: Optional[float] = Field(default=None, ge=0, le=1000)
    map_yaw: float = Field(default=0, ge=-360, le=360)
    mount_yaw: float = Field(default=0, ge=-360, le=360)
    hfov_deg: Optional[float] = Field(default=None, gt=1, lt=179)
    camera_height_m: Optional[float] = Field(default=None, gt=0, le=20)


class ToolSampleIn(BaseModel):
    class_name: str = Field(min_length=1, max_length=80)
    image_data_url: str


class ToolBoxesIn(BaseModel):
    boxes: list[list[float]] = Field(max_length=100)


class ToolClassIn(BaseModel):
    class_name: str = Field(min_length=1, max_length=80)
    width_m: Optional[float] = Field(default=None, gt=0, le=5)


class ToolDetectIn(BaseModel):
    camera_id: str = Field(min_length=1, max_length=100)
    frame_data_url: str


class MapIn(BaseModel):
    name: str = Field(default="Work area", max_length=100)
    width_m: float = Field(gt=0, le=1000)
    height_m: float = Field(gt=0, le=1000)
    tags: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


def _image_url(value: str) -> str:
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", value)
    if not match:
        raise HTTPException(400, "Frame must be a PNG, JPEG, or WebP data URL")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise HTTPException(400, "Invalid base64 frame") from exc
    if len(data) > 8_000_000:
        raise HTTPException(413, "Frame exceeds 8 MB")
    return value


def _event(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["frame_url"] = f"/memory/frames/{item.pop('frame')}" if item.get("frame") else None
    source = item.pop("source_data_json", None)
    try:
        item["source_data"] = json.loads(source) if source else None
    except (TypeError, json.JSONDecodeError):
        item["source_data"] = None
    return item


@router.get("/events")
def events(limit: int = 100, camera_id: Optional[str] = None, worker: Optional[str] = None):
    where, params = [], []
    if camera_id:
        where.append("camera_id=?"); params.append(camera_id)
    if worker:
        where.append("worker=?"); params.append(worker)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    with _db() as con:
        rows = con.execute(f"SELECT * FROM observations{where_sql} ORDER BY observed_at DESC LIMIT ?", (*params, max(1, min(limit, 300)))).fetchall()
        count = con.execute(f"SELECT COUNT(*) FROM observations{where_sql}", params).fetchone()[0]
    return {"events": [_event(r) for r in rows], "total": count, "demo_seeded": True}


@router.get("/cameras")
def cameras():
    """List registered devices and live status inferred from recent ingests."""
    with _db() as con:
        rows = con.execute("""SELECT camera_id, worker, COUNT(*) AS event_count,
            MAX(observed_at) AS latest FROM observations
            GROUP BY camera_id, worker ORDER BY latest DESC""").fetchall()
        registered = {r["camera_id"]: dict(r) for r in con.execute("SELECT * FROM camera_registry").fetchall()}
    grouped: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for row in rows:
        item = grouped.setdefault(row["camera_id"], {
            **registered.get(row["camera_id"], {}), "camera_id": row["camera_id"], "workers": [], "event_count": 0,
            "last_observation": row["latest"], "connected": False,
        })
        if row["worker"] not in item["workers"]:
            item["workers"].append(row["worker"])
        item["event_count"] += row["event_count"]
        if row["latest"] and row["latest"] > item["last_observation"]:
            item["last_observation"] = row["latest"]
    for item in grouped.values():
        try:
            stamp = datetime.fromisoformat(item["last_observation"].replace("Z", "+00:00"))
            item["connected"] = (now - stamp).total_seconds() <= 45
        except (TypeError, ValueError):
            pass
    for camera_id, info in registered.items():
        grouped.setdefault(camera_id, {**info, "workers": [info["worker"]], "event_count": 0, "last_observation": None, "connected": False})
    return {"cameras": sorted(grouped.values(), key=lambda x: x.get("last_observation") or "", reverse=True)}


def _private_camera_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        allowed = ip.is_loopback or (ip.is_private and not ip.is_link_local and not ip.is_reserved)
    except ValueError:
        allowed = host.endswith(".local") or host == "localhost"
    if parsed.scheme not in {"http", "https"} or not allowed or parsed.username or parsed.password:
        raise HTTPException(400, "Camera URLs must use a private LAN address or .local hostname")
    return value


@router.post("/cameras")
def register_camera(payload: CameraIn):
    now = datetime.now(timezone.utc).isoformat()
    stream = _private_camera_url(payload.stream_url) if payload.stream_url else None
    with _db() as con:
        con.execute("""INSERT INTO camera_registry(camera_id,worker,camera_type,stream_url,area,status,map_x,map_y,map_yaw,mount_yaw,hfov_deg,camera_height_m,updated_at)
          VALUES(?,?,?,?,?,'registered',?,?,?,?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET
          worker=excluded.worker,camera_type=excluded.camera_type,stream_url=excluded.stream_url,area=excluded.area,
          map_x=excluded.map_x,map_y=excluded.map_y,map_yaw=excluded.map_yaw,mount_yaw=excluded.mount_yaw,
          hfov_deg=excluded.hfov_deg,camera_height_m=excluded.camera_height_m,updated_at=excluded.updated_at""",
          (payload.camera_id.strip(), payload.worker.strip(), payload.camera_type, stream, payload.area.strip(),
           payload.map_x, payload.map_y, payload.map_yaw, payload.mount_yaw, payload.hfov_deg, payload.camera_height_m, now))
    return {"registered": True, "camera_id": payload.camera_id, "status": "registered"}


@router.post("/cameras/{camera_id}/check")
def check_camera(camera_id: str):
    with _db() as con:
        row = con.execute("SELECT stream_url FROM camera_registry WHERE camera_id=?", (camera_id,)).fetchone()
    if not row or not row["stream_url"]:
        raise HTTPException(422, "Register a LAN stream URL for this camera first")
    url = _private_camera_url(row["stream_url"])
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Anytime/1.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = bytearray(); deadline = time.monotonic() + 4
            while len(data) < 4_000_000 and time.monotonic() < deadline:
                chunk = response.read1(65536)
                if not chunk: break
                data.extend(chunk)
                start = data.find(b"\xff\xd8")
                if start >= 0 and data.find(b"\xff\xd9", start + 2) >= 0: break
        ok = b"\xff\xd8" in data and b"\xff\xd9" in data
        if not ok:
            raise ValueError("Stream did not yield a JPEG frame")
    except Exception as exc:
        with _db() as con:
            con.execute("UPDATE camera_registry SET status='offline',updated_at=? WHERE camera_id=?", (datetime.now(timezone.utc).isoformat(), camera_id))
        raise HTTPException(502, f"Camera connection failed: {exc}") from exc
    with _db() as con:
        con.execute("UPDATE camera_registry SET status='online',updated_at=? WHERE camera_id=?", (datetime.now(timezone.utc).isoformat(), camera_id))
    return {"connected": True, "camera_id": camera_id, "frame_received": True}


@router.get("/map")
def get_map():
    with _db() as con:
        site = con.execute("SELECT * FROM site_map WHERE id=1").fetchone()
        cameras_now = con.execute("""SELECT c.camera_id,c.worker,c.map_x,c.map_y,c.map_yaw,c.hfov_deg,c.camera_height_m,
          p.x,p.y,p.yaw,p.tag_count,p.observed_at,p.source FROM camera_registry c LEFT JOIN camera_poses p
          ON p.id=(SELECT id FROM camera_poses WHERE camera_id=c.camera_id ORDER BY observed_at DESC LIMIT 1)""").fetchall()
        poses = [dict(r) for r in con.execute("SELECT * FROM camera_poses ORDER BY observed_at DESC LIMIT 200").fetchall()]
        observations = con.execute("SELECT camera_id,worker,observed_at,source_data_json FROM observations WHERE source_data_json IS NOT NULL ORDER BY observed_at DESC LIMIT 200").fetchall()
    result = dict(site); result["tags"] = json.loads(result.pop("tags_json") or "[]")
    result["cameras"] = [dict(r) for r in cameras_now]
    result["poses"] = poses
    items = []
    for row in observations:
        try: data = json.loads(row["source_data_json"] or "{}")
        except json.JSONDecodeError: continue
        for detection in data.get("tool_detections", []):
            if detection.get("location"):
                items.append({**detection["location"],"label":detection.get("label"),"camera_id":row["camera_id"],"worker":row["worker"],"observed_at":row["observed_at"]})
    result["items"] = items[:100]
    return result


@router.put("/map")
def save_map(payload: MapIn):
    tags = []
    for tag in payload.tags:
        try:
            tag_id, x, y = int(tag["id"]), float(tag["x"]), float(tag["y"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, "Each AprilTag needs numeric id, x, and y")
        if not (0 <= x <= payload.width_m and 0 <= y <= payload.height_m):
            raise HTTPException(422, "AprilTag coordinates must fit inside the map")
        tags.append({"id": tag_id, "x": x, "y": y})
    with _db() as con:
        con.execute("UPDATE site_map SET name=?,width_m=?,height_m=?,tags_json=?,updated_at=? WHERE id=1",
                    (payload.name, payload.width_m, payload.height_m, json.dumps(tags), datetime.now(timezone.utc).isoformat()))
    return {"saved": True, "tag_count": len(tags)}


@router.get("/tools/samples")
def tool_samples():
    with _db() as con:
        rows = con.execute("SELECT * FROM tool_samples ORDER BY created_at DESC").fetchall()
        classes = [dict(r) for r in con.execute("SELECT * FROM tool_classes ORDER BY class_name").fetchall()]
    return {"samples": [{**dict(r), "boxes": json.loads(r["boxes_json"]), "image_url": f"/memory/tool-images/{r['filename']}"} for r in rows], "classes": classes}


@router.put("/tools/classes")
def save_tool_class(payload: ToolClassIn):
    with _db() as con:
        con.execute("""INSERT INTO tool_classes(class_name,width_m,updated_at) VALUES(?,?,?)
          ON CONFLICT(class_name) DO UPDATE SET width_m=excluded.width_m,updated_at=excluded.updated_at""",
          (payload.class_name.strip(), payload.width_m, datetime.now(timezone.utc).isoformat()))
    return {"saved": True, "class_name": payload.class_name, "width_m": payload.width_m}


@router.post("/tools/detect")
def detect_tool_frame(payload: ToolDetectIn):
    value = _image_url(payload.frame_data_url)
    raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    try:
        import cv2, numpy as np
        from ultralytics import YOLO
    except ImportError as exc:
        raise HTTPException(503, "Install vision dependencies with pip install -r vision-requirements.txt") from exc
    with _db() as con:
        cam = con.execute("SELECT * FROM camera_registry WHERE camera_id=?", (payload.camera_id,)).fetchone()
        pose = con.execute("SELECT * FROM camera_poses WHERE camera_id=? ORDER BY observed_at DESC LIMIT 1", (payload.camera_id,)).fetchone()
        sizes = {r["class_name"]: r["width_m"] for r in con.execute("SELECT * FROM tool_classes")}
    if not cam: raise HTTPException(404, "Register this camera first")
    active = DATA / "tools" / "active_model.txt"
    if not active.is_file(): raise HTTPException(409, "Train a tool detector first")
    model_path = Path(active.read_text().strip())
    if not model_path.is_file(): raise HTTPException(409, "Active detector weights are missing")
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None: raise HTTPException(400, "Could not decode image")
    model = _get_tool_model(YOLO, model_path); results = model.predict(image, conf=.25, verbose=False)[0]
    height, width = image.shape[:2]; detections = []
    import math
    for box in results.boxes or []:
        cls_id = int(box.cls.item()); label = model.names.get(cls_id, str(cls_id)); xyxy = box.xyxy[0].tolist()
        x1,y1,x2,y2 = xyxy; confidence = float(box.conf.item()); loc = None
        known_width = sizes.get(label)
        if pose and cam["hfov_deg"] and known_width:
            fx = (width / 2) / math.tan(math.radians(float(cam["hfov_deg"])) / 2)
            distance = fx * float(known_width) / max(1, x2 - x1)
            bearing = math.radians(((((x1+x2)/2) / width) - .5) * float(cam["hfov_deg"]) + float(cam["mount_yaw"] or 0) + float(pose["yaw"]))
            loc = {"x": round(float(pose["x"]) + distance * math.sin(bearing), 2), "y": round(float(pose["y"]) + distance * math.cos(bearing), 2),
                   "distance_m": round(distance, 2), "method": "known-width monocular estimate", "uncertainty_m": round(max(.5, distance * .3), 2)}
        detections.append({"label":label,"confidence":round(confidence,3),"box":[round(x1/width,5),round(y1/height,5),round(x2/width,5),round(y2/height,5)],"location":loc})
    return {"camera_id":payload.camera_id,"model":str(model_path),"detections":detections,"pose_available":bool(pose)}


@router.post("/tools/samples")
def add_tool_sample(payload: ToolSampleIn):
    value = _image_url(payload.image_data_url)
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", value)
    raw = base64.b64decode(match.group(2), validate=True)
    try:
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        height, width = image.shape[:2]
    except Exception as exc:
        raise HTTPException(400, "Could not decode uploaded image") from exc
    directory = DATA / "tools" / "images"; directory.mkdir(parents=True, exist_ok=True)
    ext = {"jpeg": "jpg"}.get(match.group(1), match.group(1))
    sample_id, filename = uuid.uuid4().hex, f"{uuid.uuid4().hex}.{ext}"
    (directory / filename).write_bytes(raw)
    with _db() as con:
        con.execute("INSERT INTO tool_samples(id,class_name,filename,width,height,created_at) VALUES(?,?,?,?,?,?)",
                    (sample_id, payload.class_name.strip(), filename, width, height, datetime.now(timezone.utc).isoformat()))
    return {"id": sample_id, "class_name": payload.class_name, "width": width, "height": height, "image_url": f"/memory/tool-images/{filename}", "boxes": []}


@router.put("/tools/samples/{sample_id}/boxes")
def save_tool_boxes(sample_id: str, payload: ToolBoxesIn):
    clean = []
    for box in payload.boxes:
        if len(box) != 4 or any(v < 0 or v > 1 for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise HTTPException(422, "Boxes must be normalized [x1,y1,x2,y2] coordinates")
        clean.append([round(float(v), 6) for v in box])
    with _db() as con:
        changed = con.execute("UPDATE tool_samples SET boxes_json=? WHERE id=?", (json.dumps(clean), sample_id)).rowcount
    if not changed:
        raise HTTPException(404, "Image sample not found")
    return {"saved": True, "box_count": len(clean)}


@router.get("/tool-images/{name}")
def tool_image(name: str):
    path = DATA / "tools" / "images" / Path(name).name
    if not path.is_file(): raise HTTPException(404, "Tool sample not found")
    return FileResponse(path)


def _train_tools_job(epochs: int):
    global _TRAIN_STATE
    try:
        from ultralytics import YOLO
        dataset = DATA / "tools" / "dataset"
        for folder in ("images/train", "images/val", "labels/train", "labels/val"):
            target_dir = dataset / folder; target_dir.mkdir(parents=True, exist_ok=True)
            for old in target_dir.iterdir():
                if old.is_file(): old.unlink()
        with _db() as con: rows = con.execute("SELECT * FROM tool_samples ORDER BY class_name,created_at").fetchall()
        classes = sorted({r["class_name"] for r in rows}); class_ids = {name: i for i, name in enumerate(classes)}
        labeled = []
        for r in rows:
            boxes = json.loads(r["boxes_json"] or "[]")
            if not boxes: continue
            image_path = DATA / "tools" / "images" / r["filename"]
            label_lines = []
            for x1,y1,x2,y2 in boxes:
                label_lines.append(f"{class_ids[r['class_name']]} {(x1+x2)/2:.6f} {(y1+y2)/2:.6f} {x2-x1:.6f} {y2-y1:.6f}")
            labeled.append((r, image_path, "\n".join(label_lines)+"\n"))
        if len(classes) < 1 or len(labeled) < 5: raise ValueError(f"Need annotated boxes on at least 5 images; found {len(labeled)} labeled images")
        import random
        random.Random(42).shuffle(labeled); val_count=max(1,round(len(labeled)*.2)); val_ids={entry[0]["id"] for entry in labeled[:val_count]}
        for row, image_path, labels in labeled:
            split="val" if row["id"] in val_ids else "train"
            (dataset / "images" / split / f"{row['id']}{image_path.suffix}").write_bytes(image_path.read_bytes())
            (dataset / "labels" / split / f"{row['id']}.txt").write_text(labels)
        yaml_path = dataset / "tools.yaml"
        yaml_path.write_text(f"path: {dataset}\ntrain: images/train\nval: images/val\nnames:\n" + "".join(f"  {i}: {json.dumps(name)}\n" for name,i in class_ids.items()))
        run = datetime.now().strftime("tools_%Y%m%d_%H%M%S")
        _TRAIN_STATE = {"status":"running","message":f"Training on {len(labeled)} labeled images","run":run}
        model = YOLO("yolov8n.pt"); result = model.train(data=str(yaml_path), epochs=epochs, imgsz=640, project=str(DATA / "tool_models"), name=run, device="cpu", verbose=False)
        best = Path(result.save_dir) / "weights" / "best.pt"
        (DATA / "tools" / "active_model.txt").write_text(str(best))
        _TRAIN_STATE = {"status":"complete","message":f"Trained {len(classes)} classes on {len(labeled)} images","model":str(best),"run":run}
    except Exception as exc:
        _TRAIN_STATE = {"status":"failed","message":str(exc)}


@router.post("/tools/train")
def train_tools(epochs: int = 20):
    global _TRAIN_STATE
    if not 1 <= epochs <= 100: raise HTTPException(422, "epochs must be 1 to 100")
    if not _TRAIN_LOCK.acquire(blocking=False): raise HTTPException(409, "Training already running")
    _TRAIN_STATE = {"status":"queued","message":"Preparing labeled dataset"}
    def run():
        try: _train_tools_job(epochs)
        finally: _TRAIN_LOCK.release()
    threading.Thread(target=run, daemon=True).start()
    return _TRAIN_STATE


@router.get("/tools/train-status")
def tools_train_status(): return _TRAIN_STATE


def _get_tool_model(yolo_class, path: Path):
    global _TOOL_MODEL, _TOOL_MODEL_PATH
    with _TOOL_MODEL_LOCK:
        if _TOOL_MODEL is None or _TOOL_MODEL_PATH != str(path):
            _TOOL_MODEL = yolo_class(str(path)); _TOOL_MODEL_PATH = str(path)
        return _TOOL_MODEL


@router.post("/events")
def add_event(item: ObservationIn):
    frame_name = None
    if item.frame_data_url:
        image_url = _image_url(item.frame_data_url)
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", image_url)
        data = base64.b64decode(match.group(2), validate=True)
        FRAMES.mkdir(parents=True, exist_ok=True)
        suffix = {"jpeg": "jpg"}.get(match.group(1), match.group(1))
        frame_name = f"{uuid.uuid4().hex}.{suffix}"
        (FRAMES / frame_name).write_bytes(data)
    event_id = uuid.uuid4().hex
    observed = item.observed_at or datetime.now(timezone.utc).isoformat()
    with _db() as con:
        con.execute("INSERT INTO observations (id,observed_at,worker,area,equipment,kind,note,confidence,frame,origin,camera_id,source_data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            event_id, observed, item.worker.strip(), item.area.strip(), item.equipment.strip(),
            item.kind.strip(), item.note.strip(), item.confidence, frame_name, item.origin,
            item.camera_id.strip(),
            json.dumps(item.source_data) if item.source_data else None))
        row = con.execute("SELECT * FROM observations WHERE id=?", (event_id,)).fetchone()
    return _event(row)


@router.post("/describe-frame")
def describe_frame(payload: FrameDescriptionIn):
    endpoint = os.getenv("NEMOTRON_VISION_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        raise HTTPException(503, "Vision endpoint is not configured")
    url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
    model = os.getenv("NEMOTRON_VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl")
    images = [_image_url(frame) for frame in payload.frames]
    hints = payload.limelight_hints
    hint_text = ("\nObject-detection output (unverified candidates; verify against the images): "
                 + json.dumps(hints, ensure_ascii=True)[:4000]) if hints else ""
    prompt = (
        f"These are {len(images)} ordered frames sampled from one worker-camera moment. "
        "Describe only what is visibly supported across the frames. "
        "Return JSON with keys: objects (array of visible tools/equipment), area_clues (array), "
        "visible_action (short description of changes/actions visible across frames; if only one frame, "
        "say 'cannot determine from one frame'), observation (short factual sentence), uncertainty (string). "
        "Do not infer identity, intent, "
        "repair completion, hazard severity, or safe operating state. Mark obscured details as unknown."
        + hint_text
    )
    if payload.auto_triage:
        prompt += (
            " Also return importance_score as a number from 0 to 1 and importance_reason as one short sentence. "
            "Score high only for a meaningful work-related action, equipment-state change, or unusual condition "
            "clearly supported by the frames. A static room, ordinary background, camera movement, or lighting "
            "change alone should score below 0.3. Do not call a scene important merely because it is visually novel."
        )
    if payload.task_context:
        prompt += "\n" + payload.task_context
    content = [{"type": "text", "text": prompt}]
    for index, image in enumerate(images, 1):
        content.extend([{"type": "text", "text": f"Frame {index} in time order."},
                        {"type": "image_url", "image_url": {"url": image}}])
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}],
                       "temperature": 0.1, "max_tokens": 500 if payload.task_context else 350}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read())
        text = data["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        return {"description": str(text).strip(), "model": model, "review_required": True,
                "observed_at": payload.observed_at or datetime.now(timezone.utc).isoformat()}
    except Exception as exc:
        raise HTTPException(502, f"Vision model request failed: {exc}") from exc


@router.get("/limelight-frame")
def limelight_frame(url: str = "http://172.29.0.1:5800/"):
    """Read one JPEG from the local USB-connected Limelight MJPEG feed."""
    parsed = urlsplit(url)
    try:
        host_ip = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        host_ip = None
    allowed_host = parsed.hostname == "limelight.local" or (
        host_ip is not None and host_ip.version == 4
        and str(host_ip).split(".")[:2] in (["172", "28"], ["172", "29"])
        and str(host_ip).split(".")[-1] == "1"
    )
    if (parsed.scheme != "http" or parsed.port != 5800 or not allowed_host
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise HTTPException(400, "Use the Limelight MJPEG URL on port 5800")

    process = subprocess.Popen(
        ["curl", "--noproxy", "*", "--silent", "--show-error", "--max-time", "8", url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    buffer = bytearray()
    frame = None
    try:
        while len(buffer) < 8_000_000:
            chunk = process.stdout.read(8192) if process.stdout else b""
            if not chunk:
                break
            buffer.extend(chunk)
            start = buffer.find(b"\xff\xd8")
            end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
            if end >= 0:
                frame = bytes(buffer[start:end + 2])
                break
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    if not frame:
        raise HTTPException(502, "No camera frame received from the Limelight")
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/auto-analyze")
def auto_analyze(payload: FrameDescriptionIn):
    """Analyze one short clip for automatic importance triage; persist nothing here."""
    if not payload.auto_triage:
        payload = payload.model_copy(update={"auto_triage": True})
    return describe_frame(payload)


@router.post("/ingest-frames")
def ingest_frames(payload: FrameIngestIn, authorization: Optional[str] = Header(default=None)):
    """Analyze a short sampled clip from a trusted Anytime edge device."""
    expected = os.getenv("SHIFTLENS_INGEST_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Set SHIFTLENS_INGEST_TOKEN on the server before enabling Pi ingestion")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid Anytime device token")
    ll = _limelight_summary(payload.limelight_results or {}) if payload.limelight_results else None
    camera_id = (payload.camera_id or payload.device_id).strip()
    with _db() as con:
        con.execute("""INSERT OR IGNORE INTO camera_registry(camera_id,worker,camera_type,area,status,updated_at)
          VALUES(?,?,?,?, 'active',?)""", (camera_id, payload.worker, "limelight" if payload.limelight_results else "pi", payload.area,
          datetime.now(timezone.utc).isoformat()))
    frame_match = re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", _image_url(payload.frames[-1]))
    frame_raw = base64.b64decode(frame_match.group(1), validate=True)
    tool_detections = _tool_detections_for_frame(frame_raw, camera_id, ll)
    try:
        described = describe_frame(FrameDescriptionIn(frames=payload.frames, observed_at=payload.observed_at, limelight_hints=ll))
        raw = described["description"].strip(); model = described["model"]
    except HTTPException:
        raw = "The camera uploaded a frame. Nemotron visual description is unavailable; review the image manually."
        model = "Unavailable"
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        facts = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError):
        facts = {"observation": raw, "objects": [], "area_clues": [], "visible_action": ""}
    objects = facts.get("objects", [])
    if isinstance(objects, str):
        objects = [objects]
    objects = [str(x).strip() for x in objects if str(x).strip()]
    clues = facts.get("area_clues", [])
    if isinstance(clues, str):
        clues = [clues]
    observation = str(facts.get("observation", "")).strip()
    action = str(facts.get("visible_action", "")).strip()
    note_parts = [part for part in (observation, f"Visible action: {action}" if action and action.lower() not in {"unknown", "cannot determine from one frame"} else "") if part]
    note = " ".join(note_parts) or "The visual model returned no concise observation; review the attached frame."
    detected_labels = [str(item.get("class", "")).strip() for item in (ll or {}).get("detectors", []) if item.get("class")]
    equipment = ", ".join(objects or detected_labels) if (objects or detected_labels) else "Unidentified equipment or surroundings"
    area = payload.area if payload.area != "Unspecified area" else (", ".join(map(str, clues)) or payload.area)
    result = add_event(ObservationIn(
        worker=payload.worker, area=area, equipment=equipment, kind="AI visual draft",
        note=note, confidence=0.5, frame_data_url=payload.frames[-1], observed_at=payload.observed_at,
        camera_id=camera_id, source_data={"camera_id": camera_id, "device_id": payload.device_id,
          "limelight": ll, "tool_detections": tool_detections} if ll else {"camera_id": camera_id, "device_id": payload.device_id, "tool_detections": tool_detections},
    ))
    result["origin"] = f"Anytime camera · {payload.device_id} · AI draft; review required"
    with _db() as con:
        con.execute("""INSERT OR IGNORE INTO camera_registry(camera_id,worker,camera_type,area,status,updated_at)
          VALUES(?,?,? ,?,'active',?)""", (camera_id, payload.worker, "limelight" if payload.limelight_results else "pi", area, datetime.now(timezone.utc).isoformat()))
        con.execute("UPDATE observations SET origin=?, camera_id=?, source_data_json=? WHERE id=?",
                    (result["origin"], camera_id, json.dumps(result["source_data"]), result["id"]))
        pose = (ll or {}).get("botpose")
        if isinstance(pose, dict) and all(k in pose for k in ("x", "y", "yaw")):
            x, y, yaw = float(pose["x"]), float(pose["y"]), float(pose["yaw"])
            reg = con.execute("SELECT map_x,map_y,map_yaw FROM camera_registry WHERE camera_id=?", (camera_id,)).fetchone()
            if reg:
                # Optional site alignment offset; it can translate/rotate Limelight's field frame.
                angle = __import__("math").radians(float(reg["map_yaw"] or 0))
                x, y = x * __import__("math").cos(angle) - y * __import__("math").sin(angle), x * __import__("math").sin(angle) + y * __import__("math").cos(angle)
                x += float(reg["map_x"] or 0); y += float(reg["map_y"] or 0); yaw += float(reg["map_yaw"] or 0)
            con.execute("INSERT INTO camera_poses(camera_id,worker,observed_at,x,y,yaw,tag_count,source) VALUES(?,?,?,?,?,?,?,?)",
                        (camera_id, payload.worker, payload.observed_at or datetime.now(timezone.utc).isoformat(), x, y, yaw, pose.get("tag_count"), "Limelight botpose"))
        row = con.execute("SELECT * FROM observations WHERE id=?", (result["id"],)).fetchone()
    result = _event(row)
    return {"event": result, "model": model, "review_required": True,
            "area_clues": clues, "limelight": ll,
            "uncertainty": facts.get("uncertainty", "Model output requires human review")}


def _limelight_summary(results: dict[str, Any]) -> dict[str, Any]:
    """Keep a small, known subset of Limelight's CV output; never store arbitrary payloads."""
    def selected(key: str, fields: tuple[str, ...], limit: int = 12) -> list[dict[str, Any]]:
        values = results.get(key, [])
        if not isinstance(values, list):
            return []
        return [{field: item[field] for field in fields if field in item
                 and isinstance(item[field], (str, int, float, bool))}
                for item in values[:limit] if isinstance(item, dict)]
    pose = results.get("botpose_wpiblue") or results.get("botpose") or results.get("botpose_orb")
    if isinstance(pose, list) and len(pose) >= 6:
        pose = {"x": pose[0], "y": pose[1], "z": pose[2], "roll": pose[3], "pitch": pose[4], "yaw": pose[5],
                "tag_count": int(pose[7]) if len(pose) > 7 and isinstance(pose[7], (int, float)) else None}
    elif isinstance(pose, dict):
        pose = {k: pose[k] for k in ("x", "y", "z", "roll", "pitch", "yaw", "tag_count") if k in pose and isinstance(pose[k], (int, float))}
    else:
        pose = None
    return {
        "pipeline_id": results.get("pID"),
        "pipeline_type": results.get("pTYPE"),
        "frame_index": results.get("fidx"),
        "detectors": selected("Detector", ("class", "classID", "conf", "tx", "ty", "ta")),
        "fiducials": selected("Fiducial", ("fID", "fam", "tx", "ty", "ta")),
        "barcodes": selected("Barcode", ("fam", "data", "tx", "ty", "ta")),
        "botpose": pose,
    }


def _tool_detections_for_frame(raw: bytes, camera_id: str, ll: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    active = DATA / "tools" / "active_model.txt"
    if not active.is_file(): return []
    try:
        import cv2, numpy as np
        from ultralytics import YOLO
        model_path = Path(active.read_text().strip())
        if not model_path.is_file(): return []
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None: return []
        model = _get_tool_model(YOLO, model_path); result = model.predict(image, conf=.3, verbose=False)[0]
        height,width = image.shape[:2]
        with _db() as con:
            camera = con.execute("SELECT * FROM camera_registry WHERE camera_id=?", (camera_id,)).fetchone()
            classes = {r["class_name"]:r["width_m"] for r in con.execute("SELECT * FROM tool_classes")}
        pose = (ll or {}).get("botpose")
        if not camera or not pose or not camera["hfov_deg"]: return []
        import math
        # Apply configured site-frame alignment to the Limelight field pose.
        angle=math.radians(float(camera["map_yaw"] or 0)); px=float(pose["x"]); py=float(pose["y"])
        pose_x=px*math.cos(angle)-py*math.sin(angle)+float(camera["map_x"] or 0)
        pose_y=px*math.sin(angle)+py*math.cos(angle)+float(camera["map_y"] or 0)
        pose_yaw=float(pose["yaw"])+float(camera["map_yaw"] or 0)
        fx=(width/2)/math.tan(math.radians(float(camera["hfov_deg"]))/2); out=[]
        for box in result.boxes or []:
            cls_id=int(box.cls.item()); label=model.names.get(cls_id,str(cls_id)); known=classes.get(label)
            if not known: continue
            x1,y1,x2,y2=box.xyxy[0].tolist(); dist=fx*float(known)/max(1,x2-x1)
            bearing=math.radians(((((x1+x2)/2)/width)-.5)*float(camera["hfov_deg"])+float(camera["mount_yaw"] or 0)+pose_yaw)
            out.append({"label":label,"confidence":round(float(box.conf.item()),3),"box":[round(x1/width,5),round(y1/height,5),round(x2/width,5),round(y2/height,5)],
              "location":{"x":round(pose_x+dist*math.sin(bearing),2),"y":round(pose_y+dist*math.cos(bearing),2),"distance_m":round(dist,2),"method":"known-width monocular estimate","uncertainty_m":round(max(.5,dist*.3),2)}})
        return out
    except Exception:
        return []


@router.get("/frames/{name}")
def get_frame(name: str):
    path = FRAMES / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "Frame not found")
    return FileResponse(path)


@router.post("/ask")
def ask(payload: QuestionIn):
    question = payload.question.strip()
    is_last_seen = bool(re.search(r"\b(last|most recent|where did .* put|where .* last seen|where is .* last)\b", question.lower()))
    stop = {"where", "was", "were", "did", "you", "put", "the", "last", "seen", "find", "left", "most", "recent", "is", "are", "have", "has", "been", "in", "on", "at", "of", "a", "an", "it", "this", "that", "me", "we", "they", "our", "their"}
    terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9]+", question) if len(t) > 2 and t.lower() not in stop}
    clauses, params = [], []
    if payload.camera_id:
        clauses.append("camera_id=?"); params.append(payload.camera_id)
    if payload.worker:
        clauses.append("worker=?"); params.append(payload.worker)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _db() as con:
        db_rows = con.execute(f"SELECT * FROM observations{where} ORDER BY observed_at DESC LIMIT 500", params).fetchall()
    candidates = [_event(row) for row in db_rows]

    scored = []
    for event in candidates:
        text = " ".join(str(event.get(k, "")) for k in ("area", "equipment", "kind", "note", "worker", "camera_id")).lower()
        score = sum(1 for term in terms if term in text)
        if score:
            timestamp = event.get("observed_at", "")
            scored.append((score, timestamp, event))

    last_sighting = None
    evidence = [item[2] for item in sorted(scored, key=lambda x: (x[0], x[1]), reverse=True)[:6]]
    if not evidence:
        return {"question": question, "answer": "I couldn't find a matching observation in this timeline.",
                "engine": "Evidence retrieval", "evidence": [], "scope": payload.scope,
                "review_required": True}

    endpoint = os.getenv("NEMOTRON_ENDPOINT", "").strip().rstrip("/") or os.getenv("NEMOTRON_VISION_ENDPOINT", "").strip().rstrip("/")
    if os.getenv("NEMOTRON_ENDPOINT", "").strip():
        model = os.getenv("NEMOTRON_MODEL", "nvidia/nemotron-3-nano")
    else:
        model = os.getenv("NEMOTRON_VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl")
    answer, engine = None, "Evidence retrieval"
    if endpoint:
        url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
        records = []
        for event in evidence:
            records.append({k: event.get(k) for k in ("id", "observed_at", "worker", "camera_id", "area", "equipment", "kind", "note")})
        last_context = ""
        prompt = ("You answer questions about a team's recorded workplace observations. Use only the records below. "
                  "For last-seen questions, identify the newest matching sighting and give its recorded location, time, employee, and camera when available. "
                  "Distinguish a visible object from an action: an object being present does not prove it was used. If evidence is missing, say so. "
                  "Keep the answer short and cite the observation IDs in square brackets.\n\nQUESTION: " + question +
                  "\n\nEVIDENCE RECORDS:\n" + json.dumps(records, ensure_ascii=False) + last_context)
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.1, "max_tokens": 280}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=55) as response:
                data = json.loads(response.read())
            content = data["choices"][0]["message"]["content"]
            answer = "".join(part.get("text", "") for part in content if isinstance(part, dict)) if isinstance(content, list) else str(content)
            answer = answer.strip()
            engine = "Nemotron"
        except Exception:
            answer = None
    if not answer:
        if is_last_seen:
            event = evidence[0]
            where = event.get("area", "the recorded area")
            when = event.get("time_label") or event.get("observed_at", "")
            answer = (f"The latest matching record places {event.get('equipment', 'the item')} at {where} "
                      f"at {when} [{event.get('id')}].")
        else:
            answer = "Related observations are listed below. The evidence does not support a more specific answer."
    return {"question": question, "answer": answer, "engine": engine, "evidence": evidence,
            "scope": payload.scope, "review_required": True}


@router.get("/status")
def status():
    return {"service": "Anytime local workplace memory", "storage": "local SQLite",
            "nemotron_configured": bool(os.getenv("NEMOTRON_ENDPOINT") or os.getenv("NEMOTRON_VISION_ENDPOINT")),
            "vision_configured": bool(os.getenv("NEMOTRON_VISION_ENDPOINT")),
            "vision_model": os.getenv("NEMOTRON_VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl"),
            "note": "Queries use retrieved observations as evidence; visual and text model output requires review."}
