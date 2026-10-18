import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app

KEY='test-secret'
JOB='a'*32

def make(handler,key=KEY):
    return TestClient(create_app(api_key=key,transport=httpx.MockTransport(handler)))

def test_no_secret_or_external_assets_in_public_ui():
    with make(lambda r:httpx.Response(200,json={})) as c:
        r=c.get('/')
        assert r.status_code==200
        assert 'script-src \'self\'' in r.headers['content-security-policy']
        assert 'fonts.googleapis.com' not in r.text
        js=c.get('/assets/app.js').text
        assert 'forte-datathon-2026-key' not in js
        assert 'localStorage' not in js

@pytest.mark.parametrize('path',['/api/v1/jobs/'+JOB,'/api/v1/rules'])
def test_unauthenticated_requests_never_reach_upstream(path):
    def handler(r):raise AssertionError('Should not contact analyzer')
    with make(handler) as c:assert c.get(path).status_code==401

def test_upload_requires_auth_before_reading_body():
    with make(lambda r:pytest.fail('Unexpected upload')) as c:
        assert c.post('/api/v1/analyze',content=b'x').status_code==401

def test_missing_configuration_is_not_a_default_public_key():
    with make(lambda r:pytest.fail('Unexpected request'),key='') as c:
        assert c.get('/api/v1/rules',headers={'X-API-Key':KEY}).status_code==503

def test_streamed_upload_preserves_multipart_and_accepted_status():
    def handler(r):
        assert r.headers['x-api-key']==KEY
        assert 'multipart/form-data; boundary=' in r.headers['content-type']
        assert b'synthetic-video' in r.read()
        return httpx.Response(202,json={'job_id':JOB})
    with make(handler) as c:
        r=c.post('/api/v1/analyze',headers={'X-API-Key':KEY},files={'file':('random.mov',b'synthetic-video')})
        assert r.status_code==202 and r.json()=={'job_id':JOB}

def test_busy_status_is_preserved_for_sequential_ui_retry():
    with make(lambda r:httpx.Response(429,json={'detail':'GPU busy'},headers={'Retry-After':'15'})) as c:
        r=c.post('/api/v1/analyze',headers={'X-API-Key':KEY},files={'file':('test.mov',b'x')})
        assert r.status_code==429 and r.headers['retry-after']=='15'

def test_evidence_and_workplace_provenance_are_not_rewritten():
    data={'job_id':JOB,'status':'done','verdict':'violation','violations':[{'timecode_sec':6.5667,
          'rule':{'id':'customer_cash_no_visible_id','basis_type':'workplace_review_check','url':None},
          'evidence_frames':[{'timestamp_sec':6.5667,'image_base64':'synthetic'}]}]}
    with make(lambda r:httpx.Response(200,json=data)) as c:
        assert c.get('/api/v1/jobs/'+JOB,headers={'X-API-Key':KEY}).json()==data

def test_failed_job_never_becomes_no_violation():
    data={'job_id':JOB,'status':'failed','error':'GPU timeout'}
    with make(lambda r:httpx.Response(200,json=data)) as c:
        result=c.get('/api/v1/jobs/'+JOB,headers={'X-API-Key':KEY}).json()
        assert result==data and 'verdict' not in result

def test_upstream_connection_failure_is_explicit():
    def handler(r):raise httpx.ConnectError('unavailable',request=r)
    with make(handler) as c:
        r=c.get('/api/v1/jobs/'+JOB,headers={'X-API-Key':KEY})
        assert r.status_code==503 and 'verdict' not in r.json()

def test_recordings_are_not_publicly_served():
    with make(lambda r:pytest.fail('Unexpected request')) as c:
        assert c.get('/api/v1/video/'+JOB).status_code==404

def test_invalid_job_id_cannot_change_upstream_route():
    with make(lambda r:pytest.fail('Unexpected request')) as c:
        assert c.get('/api/v1/jobs/not-a-job',headers={'X-API-Key':KEY}).status_code==404

def test_large_upload_rejected_before_upstream():
    with make(lambda r:pytest.fail('Unexpected request')) as c:
        assert c.post('/api/v1/analyze',content=b'x',headers={'X-API-Key':KEY,
            'Content-Type':'multipart/form-data; boundary=x','Content-Length':str(151*1024**2)}).status_code==413
