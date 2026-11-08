"""Evidence-first local workplace memory API for the ShiftLens demo."""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
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
      note TEXT NOT NULL, confidence REAL NOT NULL, frame TEXT, origin TEXT NOT NULL
    )""")
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
            con.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)", (
                f"demo-{offset+1}", observed.isoformat(), worker,
                area, equipment, kind, note, confidence, None, "illustrative demo data"))
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


def _event(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["frame_url"] = f"/memory/frames/{item.pop('frame')}" if item.get("frame") else None
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
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", item.frame_data_url)
        if not match:
            raise HTTPException(400, "Frame must be a PNG, JPEG, or WebP data URL")
        data = base64.b64decode(match.group(2), validate=True)
        if len(data) > 8_000_000:
            raise HTTPException(413, "Frame exceeds 8 MB")
        FRAMES.mkdir(parents=True, exist_ok=True)
        suffix = {"jpeg": "jpg"}.get(match.group(1), match.group(1))
        frame_name = f"{uuid.uuid4().hex}.{suffix}"
        (FRAMES / frame_name).write_bytes(data)
    event_id = uuid.uuid4().hex
    observed = item.observed_at or datetime.now(timezone.utc).isoformat()
    with _db() as con:
        con.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)", (
            event_id, observed, item.worker.strip(), item.area.strip(), item.equipment.strip(),
            item.kind.strip(), item.note.strip(), item.confidence, frame_name, "captured by worker"))
        row = con.execute("SELECT * FROM observations WHERE id=?", (event_id,)).fetchone()
    return _event(row)


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
    return {"service": "ShiftLens local workplace memory", "storage": "local SQLite", "nemotron_configured": bool(os.getenv("NEMOTRON_ENDPOINT")), "vision_extraction": False, "note": "Observations are worker-entered or illustrative demo seeds; frame capture is separate from AI interpretation."}
