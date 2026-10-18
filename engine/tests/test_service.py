import base64
import io
import time

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cashguard.app import create_app
from cashguard.config import Settings
from cashguard.pipeline import analyze, merge_candidates
from cashguard.schemas import Candidate, Scan, Verification
from cashguard.departure import DepartureScan
from cashguard.workflow import WorkflowContext
from cashguard.identity import IdentityScan
from cashguard.video import sample, metadata


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "synthetic.mov"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 160, 96, "yuv420p"
        for i in range(40):
            pixels = np.zeros((96, 160, 3), dtype=np.uint8)
            pixels[:, (i * 3) % 140:(i * 3) % 140 + 20] = [180, 130, 30]
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    return path


class Ready:
    def ready(self):
        return True


class Missing:
    def ready(self):
        return False


def wait(client, job_id):
    for _ in range(200):
        r = client.get('/api/v1/jobs/' + job_id, headers={"X-API-Key": "test-secret"}).json()
        if r['status'] != 'processing':
            return r
        time.sleep(.01)
    raise AssertionError("Job did not terminate")


def test_authentication_before_file_parsing(tmp_path):
    with TestClient(create_app(Settings(api_key="test-secret", data_dir=tmp_path), Missing())) as client:
        assert client.post('/api/v1/analyze', content=b'junk').status_code == 401
        assert client.get('/api/v1/jobs/nope').status_code == 401
        assert client.get('/api/v1/rules').status_code == 401
        assert client.post('/api/v1/analyze', headers={"X-API-Key":"test-secret"}).status_code == 503


def test_api_contract_and_cleanup(tmp_path, video):
    def run(path, settings):
        assert path.read_bytes() == video.read_bytes()
        return {"verdict":"no_violation", "violations":[]}
    with TestClient(create_app(Settings(api_key="test-secret", data_dir=tmp_path / "jobs"), Ready(), run)) as client:
        r = client.post('/api/v1/analyze', headers={"X-API-Key":"test-secret"}, files={"file":("../../synthetic.mov", video.read_bytes(), "video/quicktime")})
        assert r.status_code == 202
        result = wait(client, r.json()['job_id'])
        assert result['status'] == 'done' and result['verdict'] == 'no_violation'
        assert result['violations'] == []
        assert not list((tmp_path / "jobs").rglob('input.mov'))


def test_failure_never_means_no_violation(tmp_path, video):
    def fail(*args):
        raise ValueError("Decoder failed")
    with TestClient(create_app(Settings(api_key="test-secret", data_dir=tmp_path / "jobs"), Ready(), fail)) as client:
        r = client.post('/api/v1/analyze', headers={"X-API-Key":"test-secret"}, files={"file":("a.mov",video.read_bytes())})
        result = wait(client,r.json()['job_id'])
        assert result['status'] == 'failed'
        assert 'verdict' not in result


@pytest.mark.parametrize('url',['https://api.openai.com','http://example.com','http://127.0.0.1.evil.test','http://localhost','http://127.0.0.1/proxy','http://user@127.0.0.1','http://127.0.0.1?upstream=cloud'])
def test_cloud_model_endpoints_rejected(url):
    with pytest.raises(ValueError):
        Settings(model_url=url)


def test_true_timestamps_and_jpeg(video):
    info = metadata(video)
    assert 3.9 <= info['duration_sec'] <= 4.1
    frames = sample(video,[0,.35,1.67,3.8])
    assert len(frames) == 4
    assert abs(frames[1].timestamp - .4) < .02
    image = Image.open(io.BytesIO(base64.b64decode(frames[0].jpeg())))
    assert image.format == 'JPEG'


class FakeModel:
    def __init__(self, rule='leave_active_customer', complete=True, confirmed=True):
        self.rule, self.complete, self.confirmed = rule, complete, confirmed
    def ask(self, prompt, frames, schema, deadline):
        if schema is IdentityScan:
            return IdentityScan(transactions=[])
        if schema is WorkflowContext:
            return WorkflowContext(cashier_spatial_role="Unknown synthetic scene", phases=[])
        if schema is DepartureScan:
            return DepartureScan(departures=[])
        if schema is Scan:
            return Scan(candidates=[Candidate(rule_id=self.rule,timecode_sec=2,observation='Synthetic event for contract testing.',confidence=.9,complete_sequence=self.complete)])
        return Verification(confirmed=self.confirmed,rule_id=self.rule,timecode_sec=frames[len(frames)//2].timestamp,observation='Synthetic visible action for test only.',counterevidence='',confidence=.9,complete_sequence=self.complete)


def test_verified_event_has_exact_evidence_timestamp(video):
    result = analyze(video,Settings(),model=FakeModel())
    assert result['verdict'] == 'violation'
    event = result['violations'][0]
    assert event['timecode_sec'] in [f['timestamp_sec'] for f in event['evidence_frames']]
    assert event['rule']['section'] == 'п. 22'


def test_omission_requires_complete_sequence(video):
    result = analyze(video,Settings(),model=FakeModel(rule='deposit_without_count',complete=False))
    assert result['verdict'] == 'no_violation'


def test_unknown_rule_rejected(video):
    with pytest.raises(ValueError, match='unknown rule'):
        analyze(video,Settings(),model=FakeModel(rule='invented_law'))


def test_invalid_format_empty_and_oversize(tmp_path):
    with TestClient(create_app(Settings(api_key='test-secret',data_dir=tmp_path,max_upload_mb=1),Ready())) as client:
        h={'X-API-Key':'test-secret'}
        assert client.post('/api/v1/analyze',headers=h,files={'file':('a.exe',b'a')}).status_code == 415
        assert client.post('/api/v1/analyze',headers=h,files={'file':('a.mov',b'')}).status_code == 422
        assert client.post('/api/v1/analyze',headers=h,files={'file':('a.mov',b'a' * 1200000)}).status_code == 413


def test_subprocess_timeout_returns_failed(tmp_path, video, monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('worker',270)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with TestClient(create_app(Settings(api_key='test-secret',data_dir=tmp_path / 'jobs'),Ready())) as client:
        r=client.post('/api/v1/analyze',headers={'X-API-Key':'test-secret'},files={'file':('a.mov',video.read_bytes())})
        result=wait(client,r.json()['job_id'])
        assert result['status']=='failed' and 'verdict' not in result
        assert 'time budget' in result['error']


def test_concurrent_upload_rejected(tmp_path, video):
    import threading
    entered, release = threading.Event(), threading.Event()
    def run(*args):
        entered.set()
        release.wait(3)
        return {'verdict':'no_violation','violations':[]}
    with TestClient(create_app(Settings(api_key='test-secret',data_dir=tmp_path / 'jobs'),Ready(),run)) as client:
        h={'X-API-Key':'test-secret'}
        r=client.post('/api/v1/analyze',headers=h,files={'file':('a.mov',video.read_bytes())})
        assert entered.wait(2)
        try:
            rejected=client.post('/api/v1/analyze',headers=h,files={'file':('b.mov',video.read_bytes())})
            assert rejected.status_code==429
            assert rejected.headers['Retry-After']=='15'
        finally:
            release.set()
        assert wait(client,r.json()['job_id'])['status']=='done'


def test_restart_does_not_leave_permanent_processing(tmp_path):
    from cashguard.app import Store
    store=Store(tmp_path/'jobs.sqlite3')
    store.create('deadbeef')
    with TestClient(create_app(Settings(api_key='test-secret',data_dir=tmp_path),Ready())) as client:
        result=client.get('/api/v1/jobs/deadbeef',headers={'X-API-Key':'test-secret'}).json()
        assert result['status']=='failed' and 'verdict' not in result


@pytest.mark.parametrize('options',[{'stride_sec':0},{'stride_sec':30,'window_sec':20},{'deadline_sec':400},{'confirmation_threshold':1.1}])
def test_invalid_experiment_settings_rejected(options):
    with pytest.raises(ValueError):
        Settings(**options)


def test_corrupt_video_in_real_worker(tmp_path):
    with TestClient(create_app(Settings(api_key='test-secret',data_dir=tmp_path),Ready())) as client:
        response=client.post('/api/v1/analyze',headers={'X-API-Key':'test-secret'},files={'file':('broken.mov',b'not a video')})
        result=wait(client,response.json()['job_id'])
        assert result['status']=='failed' and 'verdict' not in result


def test_multimodal_messages_use_typed_blocks(video):
    # Transformers' multimodal template iterates content blocks for every role,
    # including system. A plain system string caused the real GPU smoke failure.
    from cashguard.model_server import Request, build_messages
    frames=sample(video,[0,1])
    request=Request(system='Review images',prompt='Return JSON',schema={'type':'object'},
                    frames=[{'timestamp_sec':f.timestamp,'image_base64':f.jpeg()} for f in frames])
    messages=build_messages(request)
    assert all(isinstance(m['content'],list) for m in messages)
    pictures=[b['image'] for m in messages for b in m['content'] if b['type']=='image']
    assert len(pictures)==2
    assert pictures[0].tobytes()!=pictures[1].tobytes()



def test_candidate_observation_reaches_independent_verification(video):
    class ContextSensitive(FakeModel):
        def ask(self, prompt, frames, schema, deadline):
            if schema is Verification:
                # A regression of the original handoff bug would lose this
                # observation and turn the supported proposal into a negative.
                assert 'Synthetic event for contract testing.' in prompt
                assert 'hypothesis to CHECK against pixels, not as truth' in prompt
            return super().ask(prompt, frames, schema, deadline)
    assert analyze(video, Settings(), model=ContextSensitive())['verdict'] == 'violation'


def test_candidate_text_cannot_override_verifier_rejection(video):
    result = analyze(video, Settings(), model=FakeModel(confirmed=False))
    assert result['verdict'] == 'no_violation'
    assert result['violations'] == []
    assert result['analysis']['verification_counts']['rejected'] == 1


def test_backend_releases_failed_generation_and_accepts_next_request(video, monkeypatch):
    import contextlib
    import weakref
    from types import SimpleNamespace
    from fastapi import HTTPException
    from cashguard import model_server as backend

    class FakeOOM(RuntimeError):
        pass

    class Activation:
        pass

    class Inputs(dict):
        @property
        def input_ids(self):
            return self['input_ids']
        def to(self, device):
            return self

    class Model:
        device = 'cpu'
        failed = False
        def generate(self, **kwargs):
            if not self.failed:
                self.failed = True
                activation = Activation()
                self.activation_ref = weakref.ref(activation)
                raise FakeOOM('synthetic allocation failure')
            return np.array([[1, 2, 3, 4]])

    model = Model()
    emptied = []
    def empty_cache():
        # The original except block emptied the cache while its traceback
        # still retained the failed generation's local activations.
        assert model.activation_ref() is None
        emptied.append(True)
    fake_torch = SimpleNamespace(
        OutOfMemoryError=FakeOOM, inference_mode=contextlib.nullcontext,
        cuda=SimpleNamespace(OutOfMemoryError=FakeOOM, reset_peak_memory_stats=lambda: None,
                             empty_cache=empty_cache,
                             max_memory_allocated=lambda: 0))
    processor = SimpleNamespace(
        apply_chat_template=lambda *a, **k: Inputs(input_ids=np.array([[1, 2]])),
        batch_decode=lambda *a, **k: ['{}'])
    monkeypatch.setattr(backend, 'state', {'torch': fake_torch, 'model': model, 'processor': processor})
    frame = sample(video, [0])[0]
    request = backend.Request(system='Synthetic test', prompt='Return JSON', schema={},
        frames=[{'timestamp_sec': frame.timestamp, 'image_base64': frame.jpeg()}])
    with pytest.raises(HTTPException) as caught:
        backend.infer(request)
    assert caught.value.status_code == 503
    assert emptied == [True]
    assert not backend.lock.locked()
    assert backend.infer(request)['text'] == '{}'



def test_disabled_category_cannot_generate_a_verdict(video):
    result = analyze(video, Settings(), model=FakeModel(rule='count_without_customer'))
    assert result['verdict'] == 'no_violation'
    assert result['analysis']['suppressed_unvalidated_events'] == 1
    assert result['analysis']['disabled_rule_ids'] == ['count_without_customer']
    assert result['analysis']['coverage_notice']
    research = analyze(video, Settings(disabled_rule_ids=()), model=FakeModel(rule='count_without_customer'))
    assert research['verdict'] == 'violation'


def test_rules_api_discloses_disabled_category(tmp_path):
    with TestClient(create_app(Settings(api_key='test-secret', data_dir=tmp_path), Ready())) as client:
        data = client.get('/api/v1/rules', headers={'X-API-Key':'test-secret'}).json()
        disabled = [r['id'] for r in data['rules'] if not r['enabled']]
        assert disabled == ['count_without_customer']


def test_real_worker_receives_release_policy(video, tmp_path):
    # Exercise the actual process/environment boundary. In-process runner stubs
    # missed a tuple serialized as Python repr, which Settings cannot parse.
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            answer = {'transactions': []} if request['schema']['title']=='IdentityScan' else {'cashier_spatial_role': 'Synthetic', 'phases': []} if request['schema']['title'] == 'WorkflowContext' else {'departures': []} if request['schema']['title'] == 'DepartureScan' else {'candidates': []}
            body = json.dumps({'text': json.dumps(answer)}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(api_key='test-secret', data_dir=tmp_path / 'worker-jobs',
            model_url=f'http://127.0.0.1:{server.server_port}',
            disabled_rule_ids=('count_without_customer',))
        with TestClient(create_app(settings, Ready())) as client:
            response = client.post('/api/v1/analyze', headers={'X-API-Key':'test-secret'},
                files={'file':('synthetic.mov', video.read_bytes())})
            assert response.status_code == 202
            result = wait(client, response.json()['job_id'])
            assert result['status'] == 'done'
            assert result['verdict'] == 'no_violation'
            assert result['analysis']['disabled_rule_ids'] == ['count_without_customer']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
