"""Compatibility adapter. Decisions come from the tested GPU pipeline."""
import os
import time
from pathlib import Path
import httpx


def analyze_cashier_video(video_path: str) -> dict:
    key = os.environ.get('CASHGUARD_API_KEY')
    if not key:
        raise RuntimeError('CASHGUARD_API_KEY is required')
    with httpx.Client(base_url=os.environ.get('CASHGUARD_ANALYZER_URL', 'http://127.0.0.1:8000'),
                      headers={'X-API-Key': key}, timeout=90, trust_env=False) as client:
        with Path(video_path).open('rb') as stream:
            response = client.post('/api/v1/analyze', files={'file': (Path(video_path).name, stream)})
        response.raise_for_status()
        job = response.json()['job_id']
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            response = client.get('/api/v1/jobs/' + job)
            response.raise_for_status()
            result = response.json()
            if result['status'] == 'done':
                return result
            if result['status'] == 'failed':
                raise RuntimeError(result.get('error', 'Analysis failed; no verdict produced'))
            time.sleep(2)
        raise TimeoutError('Analysis timed out; no verdict produced')
