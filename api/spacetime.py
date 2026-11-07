"""Minimal SpacetimeDB HTTP bridge for the Python optimizer service."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def call_reducer(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Call a reducer when SPACETIME_URI and SPACETIME_DATABASE are configured.

    The optimizer remains usable without a remote database, which keeps local
    judging and offline development deterministic.
    """

    base = os.getenv("SPACETIME_URI")
    database = os.getenv("SPACETIME_DATABASE")
    if not base or not database:
        return None
    url = f"{base.rstrip('/')}/v1/database/{database}/call/{name}"
    headers = {"Content-Type": "application/json"}
    token = os.getenv("SPACETIME_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(args).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read().decode()
    return json.loads(body) if body else {}
