from dataclasses import dataclass

import cv2

from .config import MAX_FRAMES


@dataclass
class Frame:
    index: int
    time: float
    jpeg: bytes
    width: int
    height: int


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    interval: float


def _open_video(path: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("Could not open video file")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total / fps if total > 0 else 0.0
    if duration <= 0:
        cap.release()
        raise ValueError("Video has no readable frames")

    return cap, VideoInfo(round(duration, 2), width, height, round(max(1.0, duration / MAX_FRAMES), 2))


def video_info(path: str) -> VideoInfo:
    """Read metadata without extracting or encoding frames for speech-only checks."""
    cap, info = _open_video(path)
    cap.release()
    return info


def sample_frames(path: str, max_side: int = 768) -> tuple[VideoInfo, list[Frame]]:
    cap, info = _open_video(path)
    duration, width, height = info.duration, info.width, info.height
    interval = max(1.0, duration / MAX_FRAMES)
    times = []
    t = 0.0
    while t < duration and len(times) < MAX_FRAMES:
        times.append(round(t, 2))
        t += interval

    scale = min(1.0, max_side / max(width, height))
    frames: list[Frame] = []
    for i, t in enumerate(times):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        if not ok:
            continue
        if scale < 1.0:
            img = cv2.resize(img, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            frames.append(Frame(i, t, buf.tobytes(), img.shape[1], img.shape[0]))
    cap.release()

    if not frames:
        raise ValueError("Could not decode any frames")
    return info, frames
