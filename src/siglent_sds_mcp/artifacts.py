from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_parent(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, data: dict[str, Any]) -> str:
    p = ensure_parent(path)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)


def default_artifact_paths(prefix: str) -> dict[str, str]:
    ts = utc_timestamp()
    safe_prefix = prefix.replace(" ", "_")
    base = f"{ts}_{safe_prefix}"
    return {
        "screenshot_raw": f"artifacts/screenshots/{base}.bmp",
        "screenshot_png": f"artifacts/screenshots/{base}.png",
        "waveform_csv": f"artifacts/waveforms/{base}.csv",
        "analysis_json": f"artifacts/waveforms/{base}_analysis.json",
        "metadata_json": f"artifacts/waveforms/{base}_metadata.json",
    }
