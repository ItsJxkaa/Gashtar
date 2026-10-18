# Gashtar + CashGuard — NVIDIA GPU deployment

This integrates the frontend and FastAPI backend from
https://github.com/ItsJxkaa/Gashtar (commit dd6609ca8cbf16a2eda2c365d963e0fc6368ae28)
with the frozen CashGuard 2026-10-18.28 detection pipeline. The original visual
interface is retained. Its motion-peak detector is replaced with calls to the
tested GPU service. No additional model training was performed.

## Presentation

[Project presentation (PowerPoint)](GASH_Control_Pitch_Deck.pptx) is maintained
separately. This deployment update does not modify the presentation.

## Architecture

Browser/API client → Cloudflare Tunnel container → Gashtar FastAPI backend
→ CashGuard analyzer → Qwen3.5-9B BF16 on the NVIDIA GPU.

The backend serves the frontend and forwards authenticated analysis requests.
The analyzer owns persistent job state, deadlines, evidence and upload cleanup.
The model listens on loopback inside a network namespace shared with the
analyzer. No GPU or analyzer port is published on the host. Only the web service
has a host binding, at 127.0.0.1:8080. The Cloudflare container reaches web:8080.

The software runs on the Brev NVIDIA VM; Cloudflare supplies HTTPS transport.
This setup uses a temporary Quick Tunnel, not the Cloudflare Containers product.
No external AI inference API receives recordings. Browser uploads still travel
through Cloudflare to the chosen VM, so use only data allowed on that route.

## Start on Brev

Requirements: x86_64 Linux, one NVIDIA GPU with at least 32 GB VRAM (L40S 48 GB
is the selected target), enough free RAM and disk space (100 GB recommended),
Python 3, Docker Engine with Compose v2 and NVIDIA Container Toolkit configured.
The model uses PyTorch 2.11.0 CUDA 12.8, matching Torchvision 0.26.0 and Transformers 5.20.1.
The target driver's CUDA compatibility must support those wheels.

1. Upload `Gashtar-NVIDIA.zip` to the instance using Brev SSH/SCP or Jupyter.
2. In the instance terminal:

```bash
python3 -m zipfile -e Gashtar-NVIDIA.zip .
cd Gashtar-NVIDIA
bash deploy/up.sh
```

The script creates `.env` with a random API key, verifies the frozen detector
hashes, builds containers, downloads the pinned model revision, and starts the
services. Initial image and model downloads can take time. Subsequent launches
reuse the weights volume. It does not create or purchase a Brev instance.

```bash
docker compose ps
docker compose logs --tail=50 model
docker compose logs cloudflared
```

The tunnel log contains the `https://...trycloudflare.com` URL. Open it, then
read `.env` privately and enter its `CASHGUARD_API_KEY` value in the UI. The key
is kept only in browser memory and must be re-entered after a page reload.
Do not publish `.env` or share a Brev account credential as the service key.

The UI queues up to 10 videos and submits them sequentially. Simultaneous API
clients receive HTTP 429 while the single GPU is occupied. The UI retries that
condition. Files larger than 95 MiB are rejected in the UI to leave room below
the common 100 MB public-proxy request limit. Direct API limit is 150 MiB.

## API

```bash
curl -X POST "https://YOUR-URL/api/v1/analyze" \
  -H "X-API-Key: YOUR-CASHGUARD-KEY" -F "file=@clip.mov"

curl "https://YOUR-URL/api/v1/jobs/JOB_ID" \
  -H "X-API-Key: YOUR-CASHGUARD-KEY"
```

The upload returns HTTP 202 with a job ID. Poll for `processing`, `done`, or
`failed`. A failed analysis has no verdict; it is never reported as compliant.
Evidence timestamps and rule provenance are passed through unchanged. Departure
and missing-ID criteria are explicitly labeled as workplace review checks.
No blanket legal citation is fabricated when a result lacks one.

## Checks and limits

- 13 gateway tests pass (authentication, multipart forwarding, busy status,
  result/evidence preservation, failure semantics, size limit and private video).
- Frontend compiled and tested in the browser, including a synthetic upload
  through the actual existing Qwen GPU service; the UI displayed its result.
- The same live API test passed: correct v28 pipeline, no violation on synthetic
  input, HTTP 401 without a key. See `deploy/LIVE_CHECK.json`.
- `docker compose config --quiet`, shell syntax and Python compilation pass.
- The frozen detector's code hashes are unchanged; its 117 prior tests and
  40-video results are recorded under `engine/`.
- On 18 October 2026, all four containers started on the Brev L40S. Model,
  analyzer and web health checks passed, and a synthetic video completed through
  the public HTTPS API with the correct v28 pipeline. Unauthenticated API access
  returned 401. See `deploy/BREV_DEPLOYMENT_CHECK.json`. Real-video latency and
  accuracy on the L40S have not been measured by this deployment smoke test.
- The first container build omitted Torchvision and failed while loading the
  video processor. The image now installs matching Torchvision 0.26.0 CUDA 12.8
  and checks its import and the video processor during the build.

The 40-video development benchmark remains 10 TP, 3 FP, 11 FN, 16 TN and zero
processing failures. X19 and X39 normal labels are disputed by the user; original
labels remain unchanged in these scores. This UI integration does not establish
better detection accuracy or independent validation. It must not be presented
as a newly trained model.

Quick Tunnel URLs can change after a tunnel restart and are intended for demos.
For a stable endpoint, configure a named Cloudflare Tunnel and domain for the
same `http://web:8080` origin. Keep the instance and containers running during
judging. `docker compose down` stops containers but does not stop Brev billing.
Do not use `down -v` unless you intend to delete stored weights and results.

## Development

```bash
pip install -r backend/requirements.txt pytest
python -m pytest tests -q
node build-ui.cjs
python deploy/verify_engine.py
pip install -e engine pytest
python -m pytest engine/tests -q
```

Frontend assets are bundled locally; no font/CDN request is needed. JSX is
compiled to JavaScript ahead of time. Model code is in `engine/cashguard/`;
changing it invalidates the recorded source provenance and requires retesting.
The ZIP excludes recordings, private reviews, credentials and model weights.
The repository includes the integrated application, frozen inference source,
deployment configuration and development evaluation reports.
Use `deploy/up.sh` for the current GPU deployment. The old Render manifest and
Windows launch scripts belong to the earlier prototype and are not the current
deployment entry points.

References:
- https://docs.nvidia.com/brev/guides/console-reference
- https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- https://docs.docker.com/compose/how-tos/gpu-support/
- https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
