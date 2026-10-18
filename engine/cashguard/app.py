import asyncio
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile

from .config import Settings
from .inference import LocalModel
from .pipeline import CATALOGUE


class UploadTooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        total = 0
        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.limit:
                raise UploadTooLarge()
            return message
        await self.app(scope, limited_receive, send)


class Store:
    def __init__(self, path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL, error TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, job_id):
        with self.connect() as c:
            c.execute("INSERT INTO jobs VALUES (?, 'processing', ?, NULL)", (job_id, time.time()))

    def set_status(self, job_id, status, error=None):
        with self.connect() as c:
            c.execute("UPDATE jobs SET status=?,error=? WHERE id=?", (status, error, job_id))

    def get(self, job_id):
        with self.connect() as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def create_app(settings=None, model=None, runner=None):
    settings = settings or Settings()
    settings.data_dir = settings.data_dir.resolve()
    model = model or LocalModel(settings)
    store = Store(settings.data_dir / "jobs.sqlite3")
    slot = threading.Lock()
    static = Path(__file__).with_name("static")
    tasks = set()

    def cleanup():
        with store.connect() as c:
            expired = c.execute("SELECT id FROM jobs WHERE status!='processing' AND created < ?", (time.time() - settings.retention_hours * 3600,)).fetchall()
            for (job_id,) in expired:
                if len(job_id) == 32 and all(x in "0123456789abcdef" for x in job_id):
                    shutil.rmtree(settings.data_dir / "jobs" / job_id, ignore_errors=True)
                    c.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    @asynccontextmanager
    async def lifespan(app):
        with store.connect() as c:
            c.execute("UPDATE jobs SET status='failed',error='Service restarted during processing. Resubmit video.' WHERE status='processing'")
        cleanup()
        yield
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="CashGuard Local", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.add_middleware(BodyLimit, limit=settings.max_upload_mb * 1024 * 1024 + 65536)

    @app.exception_handler(UploadTooLarge)
    async def too_large(request, exc):
        return JSONResponse({"detail": "Upload exceeds the configured size limit"}, status_code=413)

    async def authenticate(request: Request):
        if not settings.api_key:
            raise HTTPException(503, "Set CASHGUARD_API_KEY before analyzing videos")
        supplied = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(supplied.encode(), settings.api_key.encode()):
            raise HTTPException(401, "Invalid or missing X-API-Key")

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/":
            response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; media-src blob: 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get("/health")
    async def health():
        ready = await asyncio.to_thread(model.ready)
        return {"service": "ok", "model_ready": ready, "configured": bool(settings.api_key),
                "local_only": True, "busy": slot.locked()}

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/docs")
    def docs():
        return FileResponse(static / "docs.html")

    @app.get("/api/v1/rules", dependencies=[Depends(authenticate)])
    def rules():
        return {**CATALOGUE, "disabled_rule_ids": list(settings.disabled_rule_ids),
                "rules": [{**r, "enabled": r["id"] not in settings.disabled_rule_ids and (r.get("pipeline_stage") != "departure" or settings.departure_checks) and (r.get("pipeline_stage") != "identity" or settings.identity_checks)} for r in CATALOGUE["rules"]]}

    def run_job(job_id, video):
        folder = video.parent
        try:
            if runner:
                result = runner(video, settings)
                (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            else:
                env = os.environ.copy()
                for key, value in settings.model_dump(mode="json").items():
                    env["CASHGUARD_" + key.upper()] = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                # Worker needs no API credential and cannot access the training labels.
                env.pop("CASHGUARD_API_KEY", None)
                env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
                with (folder / "worker.log").open("w", encoding="utf-8") as log:
                    process = subprocess.run([sys.executable, "-m", "cashguard.worker", str(video),
                                              str(folder / "result.json"), str(folder / "progress.json")],
                                             stdout=log, stderr=log, env=env,
                                             timeout=settings.deadline_sec, check=False,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if process.returncode:
                    raise RuntimeError("Analysis failed. Check the local worker log; no verdict was produced.")
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            if result.get("verdict") not in {"violation", "no_violation"}:
                raise ValueError("Invalid result")
            store.set_status(job_id, "done")
        except subprocess.TimeoutExpired:
            store.set_status(job_id, "failed", "Processing exceeded the time budget; no verdict was produced.")
        except Exception as exc:
            store.set_status(job_id, "failed", str(exc)[:300])
        finally:
            video.unlink(missing_ok=True)
            slot.release()

    @app.post("/api/v1/analyze", status_code=202, dependencies=[Depends(authenticate)])
    async def upload(request: Request):
        if not await asyncio.to_thread(model.ready):
            raise HTTPException(503, "Local model is not ready. Start the GPU model server.")
        if not slot.acquire(blocking=False):
            raise HTTPException(429, "GPU is busy. Retry after the current job completes.", headers={"Retry-After": "15"})
        job_id = secrets.token_hex(16)
        folder = settings.data_dir / "jobs" / job_id
        submitted = False
        try:
            await asyncio.to_thread(cleanup)
            async with request.form(max_files=1, max_fields=0, max_part_size=settings.max_upload_mb * 1024 * 1024) as form:
                file = form.get("file")
                if not isinstance(file, UploadFile):
                    raise HTTPException(422, "Multipart field 'file' is required")
                suffix = Path(file.filename or "").suffix.lower()
                if suffix not in {".mov", ".mp4", ".m4v"}:
                    raise HTTPException(415, "Supported formats: .mov, .mp4, .m4v")
                folder.mkdir(parents=True)
                video = folder / ("input" + suffix)
                count = 0
                with video.open("wb") as destination:
                    while chunk := await file.read(1024 * 1024):
                        count += len(chunk)
                        if count > settings.max_upload_mb * 1024 * 1024:
                            raise HTTPException(413, "File exceeds upload limit")
                        destination.write(chunk)
                if not count:
                    raise HTTPException(422, "Empty file")
            store.create(job_id)
            task = asyncio.create_task(asyncio.to_thread(run_job, job_id, video))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            submitted = True
            return {"job_id": job_id}
        finally:
            if not submitted:
                shutil.rmtree(folder, ignore_errors=True)
                slot.release()

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(authenticate)])
    def job(job_id: str):
        row = store.get(job_id)
        if not row:
            raise HTTPException(404, "Job not found or expired")
        payload = {"job_id": job_id, "status": row["status"]}
        folder = settings.data_dir / "jobs" / job_id
        if row["status"] == "done":
            payload.update(json.loads((folder / "result.json").read_text(encoding="utf-8")))
        elif row["status"] == "failed":
            payload["error"] = row["error"]
        else:
            try:
                payload.update(json.loads((folder / "progress.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                payload.update(stage="preparing", progress=0)
        return payload

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app()

