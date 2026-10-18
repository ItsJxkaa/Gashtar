from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1]/'engine'
provenance=json.loads((root/'EXPERIMENT_PROVENANCE.json').read_text())
for name,digest in provenance['code_sha256'].items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
        raise SystemExit('Frozen engine mismatch: '+name)
print('Frozen v28 detector hashes verified')
