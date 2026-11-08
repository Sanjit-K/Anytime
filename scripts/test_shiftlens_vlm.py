#!/usr/bin/env python3
"""Send a synthetic five-frame tool-placement clip to the local ShiftLens VLM route."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from io import BytesIO

from PIL import Image, ImageDraw


def make_frame(index: int) -> str:
    image = Image.new("RGB", (640, 360), "#c9d3ce")
    draw = ImageDraw.Draw(image)
    # Workshop wall and workbench.
    draw.rectangle((0, 0, 640, 208), fill="#c9d3ce")
    draw.rectangle((0, 208, 640, 360), fill="#74634d")
    draw.rectangle((35, 260, 610, 283), fill="#493d30")
    draw.rectangle((54, 283, 75, 355), fill="#493d30")
    draw.rectangle((570, 283, 591, 355), fill="#493d30")
    # Distinct red toolbox at the right side of the workbench.
    draw.rounded_rectangle((455, 155, 585, 249), radius=8, fill="#b63532", outline="#54201e", width=4)
    draw.rectangle((474, 140, 565, 157), fill="#252a2a", outline="#151818", width=3)
    draw.rectangle((474, 181, 565, 188), fill="#e4b95d")
    draw.rectangle((474, 211, 565, 218), fill="#e4b95d")
    # A simple silver adjustable-wrench silhouette moves toward the toolbox.
    x = 88 + index * 72
    y = 232
    draw.rounded_rectangle((x, y + 4, x + 114, y + 20), radius=8, fill="#dce3df", outline="#323a38", width=3)
    jaw = [(x + 100, y + 5), (x + 119, y - 15), (x + 132, y - 9),
           (x + 119, y + 2), (x + 133, y + 13), (x + 122, y + 25),
           (x + 105, y + 19)]
    draw.polygon(jaw, fill="#dce3df", outline="#323a38")
    draw.ellipse((x + 88, y + 6, x + 102, y + 20), fill="#87928d", outline="#323a38", width=2)
    # Small frame index is a timestamp cue, not identifying information.
    draw.text((18, 17), f"SYNTHETIC FRAME {index + 1} / 5", fill="#27312d")
    output = BytesIO()
    image.save(output, format="JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def main() -> int:
    base = os.getenv("SHIFTLENS_API_URL", "http://127.0.0.1:8000").rstrip("/")
    body = json.dumps({"frames": [make_frame(i) for i in range(5)]}).encode()
    request = urllib.request.Request(base + "/memory/describe-frame", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    print("Synthetic input: a drawn adjustable wrench moving toward a red toolbox across five frames.")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"ShiftLens returned HTTP {exc.code}: {detail}")
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Could not reach ShiftLens VLM endpoint: {exc}")
        return 1
    print(f"Model: {result.get('model')}")
    print("Draft description:")
    print(result.get("description", "<empty response>"))
    print("Review required:", result.get("review_required"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
