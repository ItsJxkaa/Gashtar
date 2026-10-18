"""Gashtar UI/API gateway to the frozen CashGuard GPU analysis service."""
import hmac
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).resolve().parents[1] / 'frontend'


def create_app(api_key=None, upstream=None, transport=None):
    api_key = api_key if api_key is not None else os.getenv('CASHGUARD_API_KEY', '')
    upstream = upstream or os.getenv('CASHGUARD_ANALYZER_URL', 'http://127.0.0.1:8000')
    client = httpx.AsyncClient(base_url=upstream, transport=transport,
                              timeout=httpx.Timeout(90, connect=5), trust_env=False)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    app = FastAPI(title='GASH.Контроль', version='2026-10-18.28', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(request):
        if not api_key:
            raise HTTPException(503, 'Configure CASHGUARD_API_KEY before using the API')
        supplied = request.headers.get('X-API-Key', '')
        if not hmac.compare_digest(supplied.encode(), api_key.encode()):
            raise HTTPException(401, 'Invalid or missing X-API-Key')

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store',
                                 'X-Content-Type-Options': 'nosniff',
                                 'Referrer-Policy': 'no-referrer'})
        if request.url.path == '/':
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
                "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    async def proxy(request, path, upload=False):
        authenticate(request)
        headers = {'X-API-Key': api_key}
        if upload:
            content_type = request.headers.get('content-type', '')
            if not content_type.lower().startswith('multipart/form-data;'):
                raise HTTPException(415, 'Send a multipart file upload')
            headers['Content-Type'] = content_type
            size = request.headers.get('content-length')
            if size:
                try:
                    if int(size) > 150 * 1024 * 1024 + 65536:
                        raise HTTPException(413, 'Upload exceeds 150 MB')
                except ValueError:
                    raise HTTPException(400, 'Invalid Content-Length')
                headers['Content-Length'] = size
        try:
            response = await client.request('POST' if upload else 'GET', path,
                headers=headers, content=request.stream() if upload else None)
        except httpx.HTTPError:
            raise HTTPException(503, 'Analysis service is unavailable; no verdict was produced')
        forwarded = {'Retry-After': response.headers['retry-after']} if 'retry-after' in response.headers else {}
        return Response(response.content, status_code=response.status_code,
                        media_type='application/json', headers=forwarded)

    @app.get('/health')
    async def health():
        try:
            response = await client.get('/health', timeout=5)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return JSONResponse({'service': 'unavailable', 'model_ready': False}, status_code=503)
        return {**data, 'frontend': 'Gashtar', 'configured': bool(api_key) and data.get('configured', False)}

    @app.post('/api/v1/analyze')
    async def analyze(request: Request):
        return await proxy(request, '/api/v1/analyze', upload=True)

    @app.get('/api/v1/jobs/{job_id}')
    async def job(job_id: str, request: Request):
        authenticate(request)
        if not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise HTTPException(404, 'Job not found')
        return await proxy(request, '/api/v1/jobs/' + job_id)

    @app.get('/api/v1/rules')
    async def rules(request: Request):
        return await proxy(request, '/api/v1/rules')

    @app.get('/')
    def index():
        return FileResponse(FRONTEND_DIR / 'index.html')

    # Playback uses the user's local File object, never a public upload URL.
    app.mount('/vendor', StaticFiles(directory=FRONTEND_DIR / 'vendor'), name='vendor')
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIR / 'assets'), name='assets')
    return app


app = create_app()
