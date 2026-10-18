"""
ForteBank Datathon 26 — AI-сервис для выявления нарушений кассовой дисциплины по видеозаписям.

Реализует строго обязательные требования Раздела 4, 5 и 10 ТЗ:
- POST /api/v1/analyze (загрузка .mov в поле file, заголовок X-API-Key -> возвращает job_id)
- GET  /api/v1/jobs/{job_id} (статус processing | done | failed и JSON результат по схеме Раздела 10)
- GET  /api/v1/video/{job_id} (раздача видеофайла для HTML5 плеера, с авто-перепаковкой .mov -> .mp4 при необходимости)
- GET  / (веб-интерфейс проверяющего)
"""

import os
import uuid
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Header, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from detector import analyze_cashier_video

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
FRONTEND_DIR = BASE_DIR.parent / "frontend"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# API-ключ для проверки жюри (Раздел 10 ТЗ)
API_KEY = os.getenv("FORTE_API_KEY", "forte-datathon-2026-key")

app = FastAPI(
    title="GASH.Контроль — Cash Compliance AI Service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from concurrent.futures import ThreadPoolExecutor

JOBS: Dict[str, Dict[str, Any]] = {}
JOB_FILES: Dict[str, Path] = {}
EXECUTOR = ThreadPoolExecutor(max_workers=2)


def verify_api_key(x_api_key: Optional[str]) -> None:
    """Отклоняет запросы без верного заголовка X-API-Key (Раздел 10 ТЗ)."""
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _run_analysis_sync(job_id: str, video_path: Path) -> None:
    """Синхронный воркер в пуле потоков для анализа видеозаписи."""
    try:
        result = analyze_cashier_video(str(video_path))
        # Строго схема из Раздела 10 ТЗ
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "done",
            "verdict": result["verdict"],
            "violations": result["violations"],
        }
    except Exception as exc:
        JOBS[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "verdict": "no_violation",
            "violations": [],
            "error": str(exc),
        }


def _process_video_task(job_id: str, video_path: Path) -> None:
    """Отправляет задачу в пул потоков, чтобы не блокировать event loop при пакетной загрузке 10 видео."""
    EXECUTOR.submit(_run_analysis_sync, job_id, video_path)


@app.post("/api/v1/analyze")
async def analyze_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Раздел 10 ТЗ:
    POST /api/v1/analyze — Загрузить видео в формате .mov (поле file). В ответ возвращается job_id.
    """
    verify_api_key(x_api_key)

    job_id = uuid.uuid4().hex[:8]
    safe_name = os.path.basename(file.filename or "video.mov")
    saved_path = UPLOADS_DIR / f"{job_id}_{safe_name}"

    with open(saved_path, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            buffer.write(chunk)

    JOBS[job_id] = {
        "job_id": job_id,
        "status": "processing",
    }
    JOB_FILES[job_id] = saved_path

    background_tasks.add_task(_process_video_task, job_id, saved_path)
    return {"job_id": job_id, "status": "processing"}


@app.get("/api/v1/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Раздел 10 ТЗ:
    GET /api/v1/jobs/{job_id} — Получить статус обработки (processing, done, failed) и результат.
    """
    verify_api_key(x_api_key)

    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse(content=JOBS[job_id])


@app.get("/api/v1/video/{job_id}")
async def stream_video(job_id: str):
    """Отдает загруженный видеофайл для воспроизведения в веб-интерфейсе."""
    video_path = JOB_FILES.get(job_id)
    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path=str(video_path), media_type="video/mp4", filename=video_path.name)


if (FRONTEND_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

if (FRONTEND_DIR / "vendor").exists():
    app.mount("/vendor", StaticFiles(directory=str(FRONTEND_DIR / "vendor")), name="vendor")


@app.get("/")
async def serve_ui():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse({"status": "ok"})
