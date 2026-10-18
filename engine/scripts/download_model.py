"""One-time download of public weights. No video/data upload is performed."""
import argparse
from huggingface_hub import snapshot_download

p = argparse.ArgumentParser()
p.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
p.add_argument("--output", default="models/qwen3-vl-8b")
p.add_argument("--revision", default="main", help="Use a pinned commit for reproducibility")
a = p.parse_args()
snapshot_download(a.model, local_dir=a.output, revision=a.revision,
                  allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja", "*.model", "LICENSE*", "README.md"])
print("Weights downloaded. Inference uses local_files_only and offline mode.")

