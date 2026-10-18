"""Persistent, loopback-only Transformers backend. No cloud APIs or remote assets."""
import base64
import io
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

state = {}
lock = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    import torch
    import json
    from transformers import AutoProcessor, BitsAndBytesConfig
    model_path = Path(os.environ.get("CASHGUARD_MODEL_PATH", "models/qwen3-vl-8b"))
    if not model_path.is_dir():
        raise RuntimeError("Download model weights first; CASHGUARD_MODEL_PATH must be a local directory")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU required for the inference backend")
    architecture=json.loads((model_path/'config.json').read_text()).get('model_type')
    if architecture=='qwen3_vl':
        from transformers import Qwen3VLForConditionalGeneration as ModelClass
    elif architecture=='qwen3_5':
        from transformers import Qwen3_5ForConditionalGeneration as ModelClass
    else:
        raise RuntimeError('Unsupported local model architecture')
    args = {"local_files_only": True, "trust_remote_code": False,
            "device_map": {"": 0}, "dtype": torch.bfloat16, "attn_implementation": "sdpa"}
    if os.environ.get("CASHGUARD_4BIT", "0") == "1":
        args["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    state["model"] = ModelClass.from_pretrained(str(model_path), **args).eval()
    state["processor"] = AutoProcessor.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
    state["torch"] = torch
    detector_path = os.environ.get("CASHGUARD_DETECTOR_PATH")
    if detector_path:
        from .object_focus import ObjectFocus
        state["focus"] = ObjectFocus(detector_path)
    yield
    state.clear()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class ModelFrame(BaseModel):
    timestamp_sec: float
    image_base64: str = Field(max_length=2000000)


class Request(BaseModel):
    system: str = Field(max_length=8000)
    prompt: str = Field(max_length=30000)
    schema_: dict = Field(alias="schema")
    frames: list[ModelFrame] = Field(min_length=1, max_length=96)
    native_video: bool = False
    max_new_tokens: int = Field(default=1000, ge=32, le=1500)
    max_seconds: float = Field(default=45, ge=1, le=60)


@app.get("/health")
def health():
    return {"ready": "model" in state}


def build_messages(request, focus=None):
    import json
    from PIL import Image
    pictures = []
    for f in request.frames:
        picture = Image.open(io.BytesIO(base64.b64decode(f.image_base64, validate=True))).convert("RGB")
        picture.thumbnail((768, 768))
        pictures.append(picture)
    crops = focus.crops(pictures, min(8, max(0, 32-len(pictures)))) if focus else {}
    content = []
    for index, (f, picture) in enumerate(zip(request.frames, pictures)):
        content.extend([{"type": "text", "text": f"Video timestamp {f.timestamp_sec:.4f} seconds:"},
                        {"type": "image", "image": picture}])
        if index in crops:
            content.extend([{"type": "text", "text": f"Magnified region from the SAME frame at {f.timestamp_sec:.4f}s. This is optional context proposed by a fallible object detector, not proof of an object or action:"},
                            {"type": "image", "image": crops[index]}])
    content.append({"type": "text", "text": request.prompt + "\nOutput validation schema (not the answer):\n" + json.dumps(request.schema_, ensure_ascii=False)
                    + "\nNow answer the visual review task. Return ONE JSON INSTANCE with actual field values. "
                    "Do not reproduce the schema or its properties/type definitions. No commentary outside the JSON."})
    return [{"role": "system", "content": [{"type": "text", "text": request.system}]},
            {"role": "user", "content": content}]


def video_inputs(request, processor):
    """Encode a chronological clip with PTS-derived metadata, without audio."""
    import json
    import numpy as np
    from PIL import Image
    from transformers.video_utils import VideoMetadata
    frames = sorted(request.frames, key=lambda f: f.timestamp_sec)
    pictures = []
    for frame in frames:
        picture = Image.open(io.BytesIO(base64.b64decode(frame.image_base64, validate=True))).convert('RGB')
        picture.thumbnail((768, 768))
        pictures.append(np.asarray(picture))
    indices = [round(frame.timestamp_sec * 1000) for frame in frames]
    metadata = VideoMetadata(total_num_frames=max(indices)+1, fps=1000, frames_indices=indices)
    prompt = (request.prompt + '\nAvailable evidence-frame timestamps (seconds): '
              + json.dumps([frame.timestamp_sec for frame in frames])
              + '\nOutput validation schema (not the answer): ' + json.dumps(request.schema_, ensure_ascii=False)
              + '\nReturn ONE JSON INSTANCE with actual field values, never the schema. No text outside JSON.')
    messages = [{'role':'system','content':[{'type':'text','text':request.system}]},
                {'role':'user','content':[{'type':'video'},{'type':'text','text':prompt}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    return processor(text=[text], videos=[np.stack(pictures)], video_metadata=[metadata],
                     do_sample_frames=False, cap_pixels_per_frame=True, return_tensors='pt')


@app.post("/infer")
def infer(request: Request):
    torch = state["torch"]
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "GPU is processing another request")
    try:
        started = time.monotonic()
        torch.cuda.reset_peak_memory_stats()
        processor, model, torch = state["processor"], state["model"], state["torch"]
        if request.native_video:
            inputs = video_inputs(request, processor).to(model.device)
            crop_count = 0
        else:
            if len(request.frames) > 32:
                raise HTTPException(422, 'Image mode accepts at most 32 frames')
            messages = build_messages(request, state.get("focus"))
            inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                                  return_dict=True, return_tensors="pt", enable_thinking=False).to(model.device)
            crop_count = sum(block["type"] == "image" for block in messages[1]["content"]) - len(request.frames)
        with torch.inference_mode():
            outputs = model.generate(**inputs, do_sample=False, max_new_tokens=request.max_new_tokens,
                                     max_time=request.max_seconds, use_cache=True)
        text = processor.batch_decode(outputs[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
        return {"text": text, "usage": {"elapsed_sec": round(time.monotonic() - started, 3),
                "input_tokens": int(inputs.input_ids.shape[1]),
                "output_tokens": int(outputs.shape[1] - inputs.input_ids.shape[1]),
                "object_crops": crop_count, "native_video": request.native_video,
                "peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1)}}
    except torch.cuda.OutOfMemoryError as error:
        import gc
        # The failed generation traceback may still own CUDA activations.
        # Release those references before emptying the allocator cache.
        error.__traceback__ = None
        inputs = outputs = None
        gc.collect()
        torch.cuda.empty_cache()
        raise HTTPException(503, "GPU out of memory; reduce frames or use 4-bit model") from None
    finally:
        lock.release()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001, workers=1)

