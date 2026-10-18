import json
from pathlib import Path
from cashguard.worker import atomic_json

def test_transient_windows_sharing_error_preserves_atomic_output(tmp_path,monkeypatch):
    actual=Path.replace;calls=[]
    def replace(self,target):
        calls.append(target)
        if len(calls)<3:raise PermissionError('Synthetic Windows sharing race')
        return actual(self,target)
    monkeypatch.setattr(Path,'replace',replace)
    monkeypatch.setattr('cashguard.worker.time.sleep',lambda _:None)
    target=tmp_path/'progress.json'
    atomic_json(target,{'stage':'identity','progress':95})
    assert len(calls)==3 and json.loads(target.read_text())=={'stage':'identity','progress':95}
    assert not target.with_suffix('.json.tmp').exists()
