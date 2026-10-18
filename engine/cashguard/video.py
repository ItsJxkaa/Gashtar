"""PTS-based video decoding. Audio is never decoded or used."""
import base64
import io
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageOps


@dataclass
class Frame:
    timestamp: float
    image: Image.Image

    def jpeg(self, edge=1024, quality=85):
        image = self.image.copy()
        image.thumbnail((edge, edge))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=quality)
        return base64.b64encode(out.getvalue()).decode("ascii")


def metadata(path: Path):
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("No video stream")
        s = container.streams.video[0]
        duration = float(s.duration * s.time_base) if s.duration else float((container.duration or 0) / av.time_base)
        if duration <= 0 or s.width <= 0 or s.height <= 0:
            raise ValueError("Invalid video duration or dimensions")
        if s.width * s.height > 4096 * 4096:
            raise ValueError("Video exceeds supported 4096 x 4096 pixel area")
        return {"duration_sec": duration, "width": s.width, "height": s.height,
                "fps": float(s.average_rate or 0), "codec": s.codec_context.name}


def sample(path: Path, targets, edge=768):
    """Return first actual video frame at/after each target, timestamp from PTS.

    Decode from the preceding keyframe once per window. Preserve aspect ratio,
    container rotation, and true timestamps (including variable frame rate).
    """
    targets = sorted(set(max(0, float(t)) for t in targets))
    if not targets:
        return []
    result = []
    with av.open(str(path)) as container:
        s = container.streams.video[0]
        origin = float((s.start_time or 0) * s.time_base)
        if targets[0] > 0:
            container.seek(int((targets[0] + origin) / float(s.time_base)), stream=s, backward=True)
        index = 0
        for frame in container.decode(s):
            if frame.pts is None:
                continue
            timestamp = float(frame.pts * frame.time_base) - origin
            if timestamp + 1e-6 < targets[index]:
                continue
            image = frame.to_image().convert("RGB")
            rotation = int(round(getattr(frame, "rotation", 0) or 0))
            if rotation:
                image = image.rotate(rotation, expand=True)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((edge, edge))
            result.append(Frame(round(timestamp, 4), image))
            while index < len(targets) and targets[index] <= timestamp + 1e-6:
                index += 1
            if index == len(targets):
                break
    if not result:
        raise ValueError("No decodable frames in requested interval")
    return result


def windows(duration, width, stride):
    start = 0.0
    while True:
        end = min(start + width, max(0, duration - 0.05))
        yield start, end
        if end >= duration - 0.05:
            break
        start += stride


def uniform(start, end, count):
    return np.linspace(start, end, count).tolist()

