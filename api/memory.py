"""Evidence-first local workplace memory API for the ShiftLens demo."""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import sqlite3
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/memory", tags=["ShiftLens workplace memory"])
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("SHIFTLENS_DATA_DIR", str(ROOT / "data")))
FRAMES = DATA / "frames"
DB = DATA / "shiftlens.sqlite3"


def _db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS observations (
      id TEXT PRIMARY KEY, observed_at TEXT NOT NULL, worker TEXT NOT NULL,
      area TEXT NOT NULL, equipment TEXT NOT NULL, kind TEXT NOT NULL,
      note TEXT NOT NULL, confidence REAL NOT NULL, frame TEXT, origin TEXT NOT NULL,
      source_data_json TEXT
    )""")
    columns = {row[1] for row in con.execute("PRAGMA table_info(observations)")}
    if "source_data_json" not in columns:
        con.execute("ALTER TABLE observations ADD COLUMN source_data_json TEXT")
    if con.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0:
        examples = [
          ("Worker 03", "Pump Bay B", "Pump B", "condition", "A small fluid patch was visible beneath the Pump B coupling during the walkaround.", .91),
          ("Worker 01", "Pump Bay B", "Pump B", "action", "Worker inspected the lower coupling and used a wrench on the near-side fitting. The footage does not confirm torque or repair completion.", .78),
          ("Worker 02", "Tool Crib", "Adjustable wrench", "tool sighting", "Adjustable wrench placed on Workbench B beside the red toolbox.", .88),
          ("Worker 01", "Pump Bay B", "Pump B", "condition", "Fluid was again visible below the same coupling on the next pass.", .86),
          ("Worker 03", "Pump Bay A", "Pump A", "handoff", "Guard was in place; no visible warning indicator noted during the visual check.", .73),
        ]
        now = datetime.now(timezone.utc)
        for offset, row in enumerate(examples):
            worker, area, equipment, kind, note, confidence = row
            observed = (now - timedelta(minutes=(len(examples) - offset) * 17)).replace(microsecond=0)
            con.execute("INSERT INTO observations (id,observed_at,worker,area,equipment,kind,note,confidence,frame,origin,source_data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                f"demo-{offset+1}", observed.isoformat(), worker,
                area, equipment, kind, note, confidence, None, "illustrative demo data", None))
        con.commit()
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


class FrameDescriptionIn(BaseModel):
    frames: list[str] = Field(min_length=1, max_length=5)
    observed_at: Optional[str] = None
    limelight_hints: Optional[dict[str, Any]] = None


class FrameIngestIn(FrameDescriptionIn):
    worker: str = Field(default="Worker 01", max_length=80)
    area: str = Field(default="Unspecified area", max_length=120)
    device_id: str = Field(default="shiftlens-pi", max_length=80)
    limelight_results: Optional[dict[str, Any]] = None


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
def events(limit: int = 100):
    with _db() as con:
        rows = con.execute("SELECT * FROM observations ORDER BY observed_at DESC LIMIT ?", (max(1, min(limit, 300)),)).fetchall()
        count = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    return {"events": [_event(r) for r in rows], "total": count, "demo_seeded": True}


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
        con.execute("INSERT INTO observations (id,observed_at,worker,area,equipment,kind,note,confidence,frame,origin,source_data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            event_id, observed, item.worker.strip(), item.area.strip(), item.equipment.strip(),
            item.kind.strip(), item.note.strip(), item.confidence, frame_name, "captured by worker", None))
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
    hint_text = ("\nLimelight machine-vision detections (unverified hints; verify against images): "
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
    content = [{"type": "text", "text": prompt}]
    for index, image in enumerate(images, 1):
        content.extend([{"type": "text", "text": f"Frame {index} in time order."},
                        {"type": "image_url", "image_url": {"url": image}}])
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}],
                       "temperature": 0.1, "max_tokens": 350}).encode()
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


@router.post("/ingest-frames")
def ingest_frames(payload: FrameIngestIn, authorization: Optional[str] = Header(default=None)):
    """Analyze a short sampled clip from a trusted ShiftLens edge device."""
    expected = os.getenv("SHIFTLENS_INGEST_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Set SHIFTLENS_INGEST_TOKEN on the server before enabling Pi ingestion")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid ShiftLens device token")
    ll = _limelight_summary(payload.limelight_results or {}) if payload.limelight_results else None
    described = describe_frame(FrameDescriptionIn(frames=payload.frames, observed_at=payload.observed_at,
                                                   limelight_hints=ll))
    raw = described["description"].strip()
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
    ))
    result["origin"] = f"ShiftLens camera · {payload.device_id} · AI draft; review required"
    with _db() as con:
        con.execute("UPDATE observations SET origin=?, source_data_json=? WHERE id=?",
                    (result["origin"], json.dumps({"limelight": ll}) if ll else None, result["id"]))
        row = con.execute("SELECT * FROM observations WHERE id=?", (result["id"],)).fetchone()
    result = _event(row)
    return {"event": result, "model": described["model"], "review_required": True,
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
    return {
        "pipeline_id": results.get("pID"),
        "pipeline_type": results.get("pTYPE"),
        "frame_index": results.get("fidx"),
        "detectors": selected("Detector", ("class", "classID", "conf", "tx", "ty", "ta")),
        "fiducials": selected("Fiducial", ("fID", "fam", "tx", "ty", "ta")),
        "barcodes": selected("Barcode", ("fam", "data", "tx", "ty", "ta")),
    }


@router.get("/frames/{name}")
def get_frame(name: str):
    path = FRAMES / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "Frame not found")
    return FileResponse(path)


@router.post("/ask")
def ask(payload: dict):
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "Enter a question")
    terms = {t.lower() for t in re.findall(r"[a-zA-Z0-9]+", question) if len(t) > 2}
    with _db() as con:
        rows = con.execute("SELECT * FROM observations ORDER BY observed_at DESC").fetchall()
    scored = []
    for row in rows:
        event = _event(row)
        text = " ".join(str(event[k]) for k in ("area", "equipment", "kind", "note", "worker")).lower()
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, event))
    evidence = [x[1] for x in sorted(scored, key=lambda x: (x[0], x[1]["observed_at"]), reverse=True)[:6]]
    if not evidence:
        evidence = [_event(r) for r in rows[:3]]

    answer, engine = None, "evidence-only"
    endpoint = os.getenv("NEMOTRON_ENDPOINT", "").strip().rstrip("/")
    if endpoint and evidence:
        url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
        model = os.getenv("NEMOTRON_MODEL", "nvidia/nemotron-3-nano")
        prompt = ("Answer using only the workplace observations below. Distinguish directly observed facts from inference. "
                  "Do not claim a repair is complete or give safety-critical instructions. If evidence is insufficient, say so. "
                  "Cite supporting observation IDs in brackets.\n\nQUESTION: " + question +
                  "\n\nOBSERVATIONS:\n" + json.dumps([{k: e[k] for k in ("id", "observed_at", "worker", "area", "equipment", "kind", "note")} for e in evidence]))
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 350}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as response:
                data = json.loads(response.read())
            answer = data["choices"][0]["message"]["content"].strip()
            engine = "Nemotron"
        except Exception:
            answer = None
    if not answer:
        if "where" in question.lower() and "wrench" in question.lower():
            hit = next((e for e in evidence if "wrench" in e["equipment"].lower()), None)
            answer = f"{hit['equipment']} was last recorded at {hit['area']}: {hit['note']} [{hit['id']}]." if hit else "I couldn't find a wrench sighting in the recorded observations."
        elif "pump b" in question.lower() or "leak" in question.lower():
            hits = [e for e in evidence if "pump b" in e["equipment"].lower()]
            answer = ("The observations mention fluid below Pump B's coupling on more than one pass. A worker was seen using a wrench on the fitting, but the record does not confirm that a repair was completed. Review the cited footage and have an authorized worker assess it." if hits else "I couldn't find enough recorded evidence about Pump B to answer.")
        else:
            answer = "I found related observations below. Review the source frames; this local fallback summarizes recorded notes and has not called Nemotron."
    return {"question": question, "answer": answer, "engine": engine, "evidence": evidence, "review_required": True}


@router.get("/status")
def status():
    return {"service": "ShiftLens local workplace memory", "storage": "local SQLite",
            "nemotron_configured": bool(os.getenv("NEMOTRON_ENDPOINT")),
            "vision_configured": bool(os.getenv("NEMOTRON_VISION_ENDPOINT")),
            "vision_model": os.getenv("NEMOTRON_VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl"),
            "note": "Vision descriptions are drafts from sampled frames and require worker review."}
