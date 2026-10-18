"""Isolated per-video worker. The parent enforces a hard wall-clock deadline."""
import json
import sys
import time
from pathlib import Path

from .config import Settings
from .pipeline import analyze


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    # Windows may briefly deny replacement while the API reads progress.
    # Keep the write atomic and retry only this transient sharing failure.
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.01 * 2**attempt)


def main():
    video, output, progress_path = map(Path, sys.argv[1:4])
    settings = Settings()
    def progress(stage, pct):
        atomic_json(progress_path, {"stage": stage, "progress": pct})
    result = analyze(video, settings, progress)
    atomic_json(output, result)


if __name__ == "__main__":
    main()

