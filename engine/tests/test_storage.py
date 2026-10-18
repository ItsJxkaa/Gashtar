import pytest
from cashguard.config import Settings
from cashguard.departure import DepartureScan,DepartureReview
from cashguard.pipeline import analyze
from cashguard.schemas import Scan
from cashguard.storage import StorageDetail,StorageLocations,key_supported,detail_states
from test_departure import review_data
from test_service import video


def detail_data():
    return dict(safe_identity='cash_safe',safe_door='open',safe_confidence=.9,safe_observation='Synthetic open safe',
        key_in_storage_lock='yes',key_confidence=.9,key_observation='Synthetic key visibly inserted in lock',
        desk_cash='loose_banknotes',cash_identification='banknotes_visible',cash_confidence=.9,cash_observation='Synthetic exposed banknotes')


@pytest.mark.parametrize('field,value',[
    ('safe_identity','ordinary_cabinet'),('safe_identity','unknown'),('safe_identity','not_visible'),
    ('key_in_storage_lock','unknown'),('key_in_storage_lock','no'),('key_confidence',.7),('safe_confidence',.7),
])
def test_unresolved_or_wrong_object_does_not_prove_unattended_key(field,value):
    d=detail_data();d[field]=value
    assert not key_supported(StorageDetail(**d),.75)


def test_closed_safe_does_not_imply_key_removed_or_safe_locked():
    d=detail_data();d['safe_door']='closed';detail=StorageDetail(**d)
    assert detail_states(detail)['safe']['state']=='closed_cash_safe'
    assert key_supported(detail,.75)


@pytest.mark.parametrize('departed',['yes','no'])
def test_detail_pass_can_find_risk_but_never_without_departure(video,departed):
    class Model:
        def ask(self,prompt,frames,schema,deadline):
            if schema is Scan:return Scan(candidates=[])
            if schema is DepartureScan:return DepartureScan(departures=[dict(timecode_sec=1.,observation='Synthetic possible departure')])
            if schema is StorageLocations:
                assert departed=='yes'
                box=dict(found=True,confidence=.9,x1=100,y1=100,x2=800,y2=800)
                return StorageLocations(safe=box,desk=box)
            if schema is StorageDetail:
                assert departed=='yes' and len(frames)==4
                assert frames[2].timestamp==frames[1].timestamp
                return StorageDetail(**detail_data())
            d=review_data();d['cashier_departed']=departed
            d['laptop']['state']='off_or_closed';d['safe']['state']='closed_cash_safe'
            d['desk_cash'].update(state='no_exposed_cash',identification='unverified')
            d['departure_time_sec']=min(frames,key=lambda f:abs(f.timestamp-1)).timestamp
            d['after_time_sec']=min(frames,key=lambda f:abs(f.timestamp-2.5)).timestamp
            return DepartureReview(**d)
    result=analyze(video,Settings(identity_checks=False),model=Model())
    actual={e['rule']['id'] for e in result['violations']}
    assert actual==({'departure_open_safe','departure_cash_or_bag','departure_key_in_lock'} if departed=='yes' else set())
