import pytest

from cashguard.config import Settings
from cashguard.departure import DepartureScan, DepartureReview
from cashguard.pipeline import analyze
from cashguard.schemas import Scan
from cashguard.screen import ScreenReview, ScreenLocation, unlocked_supported, verify_screen
from test_departure import review_data
from test_service import video


def screen_data():
    return dict(state='unlocked_application',lock_or_login_indicator='no',
        desktop_or_application_controls='yes',confidence=.9,observation='Synthetic desktop controls')


@pytest.mark.parametrize('field,value', [
    ('state','lock_screen'),('state','unknown'),('state','off_or_closed'),
    ('lock_or_login_indicator','yes'),('lock_or_login_indicator','unknown'),
    ('desktop_or_application_controls','no'),('desktop_or_application_controls','unknown'),
    ('confidence',.7),
])
def test_lock_screen_or_unresolved_controls_reject_unlock_claim(field,value):
    d=screen_data();d[field]=value
    assert not unlocked_supported(ScreenReview(**d),.75)


def test_visible_controls_without_lock_indicators_supported():
    assert unlocked_supported(ScreenReview(**screen_data()),.75)


def test_screen_crops_use_image_mode_even_in_native_video_pipeline(video,monkeypatch):
    import json,time,httpx
    from cashguard.inference import LocalModel
    from cashguard.video import sample
    client=httpx.Client
    def handle(request):
        body=json.loads(request.content)
        assert body['native_video'] is False
        assert body['schema']['title']=='ScreenReview'
        return httpx.Response(200,json={'text':json.dumps(screen_data())})
    monkeypatch.setattr('cashguard.inference.httpx.Client',lambda **kwargs:client(transport=httpx.MockTransport(handle),**kwargs))
    answer=LocalModel(Settings(native_video=True)).ask('Synthetic screen check',sample(video,[1]),ScreenReview,time.monotonic()+50)
    assert unlocked_supported(answer,.75)


def test_bad_localization_never_becomes_an_unlock_flag(video):
    class Model:
        def ask(self,prompt,frames,schema,deadline):
            assert schema is ScreenLocation
            return ScreenLocation(found=True,confidence=.95,x1=700,y1=200,x2=100,y2=800)
    result,detail=verify_screen(video,1.,Settings(),Model(),100)
    assert result is None and detail['state']=='unknown'


def test_rounded_final_pts_can_be_reopened_for_screen_crop(tmp_path):
    import av,numpy as np
    path=tmp_path/'rounding.mov'
    with av.open(str(path),'w') as out:
        stream=out.add_stream('mpeg4',rate=30)
        stream.width=160;stream.height=96;stream.pix_fmt='yuv420p'
        for _ in range(3):
            for packet in stream.encode(av.VideoFrame.from_ndarray(np.zeros((96,160,3),dtype=np.uint8),format='rgb24')):out.mux(packet)
        for packet in stream.encode():out.mux(packet)
    class Model:
        def ask(self,prompt,frames,schema,deadline):
            assert frames[0].timestamp == .0667
            return ScreenLocation(found=False,confidence=0,x1=0,y1=0,x2=0,y2=0)
    result,detail=verify_screen(path,.0667,Settings(),Model(),100)
    assert result is None and detail['reason']=='screen_not_located'


def test_locked_screen_rejects_laptop_but_preserves_other_departure_evidence(video):
    class Model:
        def ask(self,prompt,frames,schema,deadline):
            if schema is Scan:return Scan(candidates=[])
            if schema is DepartureScan:return DepartureScan(departures=[dict(timecode_sec=1.,observation='Synthetic walk-away transition')])
            if schema is ScreenLocation:return ScreenLocation(found=True,confidence=.9,x1=100,y1=100,x2=700,y2=700)
            if schema is ScreenReview:
                assert frames[0].timestamp == frames[1].timestamp
                assert frames[1].image.width < frames[0].image.width
                d=screen_data();d.update(state='lock_screen',lock_or_login_indicator='yes',desktop_or_application_controls='no')
                return ScreenReview(**d)
            d=review_data()
            d['departure_time_sec']=min(frames,key=lambda f:abs(f.timestamp-1)).timestamp
            d['after_time_sec']=min(frames,key=lambda f:abs(f.timestamp-2.5)).timestamp
            return DepartureReview(**d)
    result=analyze(video,Settings(identity_checks=False,workflow_context=False,storage_detail=False),model=Model())
    assert {e['rule']['id'] for e in result['violations']}=={'departure_open_safe','departure_cash_or_bag'}
    assert result['analysis']['departure_checks']['screen_reviews'][0]['state']=='lock_screen'
