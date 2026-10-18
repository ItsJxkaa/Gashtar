import copy

import pytest

from cashguard.config import Settings
from cashguard.departure import DepartureReview, DepartureScan, supported_rules
from cashguard.pipeline import analyze
from cashguard.schemas import Scan
from test_service import video


def review_data():
    return dict(departure_observation='Synthetic cashier departure.',
        cashier_departed='yes', same_workstation_continuity='yes', supervision='none_visible',
        departure_time_sec=1., after_time_sec=2.5, sequence_confidence=.9,
        laptop=dict(state='unlocked_application', confidence=.9, observation='Synthetic visible desktop.'),
        safe=dict(state='open_cash_safe', confidence=.9, observation='Synthetic open safe.'),
        desk_cash=dict(state='cash_bag', identification='money_put_into_same_bag',
            confidence=.9, observation='Synthetic identified cash bag.'))


@pytest.mark.parametrize('field,value', [
    ('cashier_departed','no'), ('cashier_departed','unknown'),
    ('same_workstation_continuity','unknown'),
    ('supervision','supervising_worker_visible'), ('supervision','unknown'),
    ('sequence_confidence',.7), ('after_time_sec',.5),
])
def test_departure_requires_temporal_attendance_and_continuity(field, value):
    d=review_data();d[field]=value
    assert supported_rules(DepartureReview(**d), .75)==[]


@pytest.mark.parametrize('obj,state', [
    ('laptop','unreadable'), ('laptop','lock_screen'), ('laptop','off_or_closed'),
    ('safe','ordinary_cabinet'), ('safe','closed_cash_safe'), ('safe','unknown'),
    ('desk_cash','unidentified_bag'), ('desk_cash','unknown'),
])
def test_safe_or_unresolved_object_never_creates_its_flag(obj,state):
    d=review_data();d[obj]['state']=state
    expected={'laptop':'departure_unlocked_laptop','safe':'departure_open_safe','desk_cash':'departure_cash_or_bag'}
    assert expected[obj] not in {r[0] for r in supported_rules(DepartureReview(**d),.75)}


def test_opaque_bag_does_not_prove_money():
    d=review_data();d['desk_cash']['identification']='unverified'
    assert 'departure_cash_or_bag' not in {r[0] for r in supported_rules(DepartureReview(**d),.75)}


def test_departure_events_use_real_after_frames_and_checklist_provenance(video):
    class Model:
        def ask(self,prompt,frames,schema,deadline):
            if schema is Scan:return Scan(candidates=[])
            if schema is DepartureScan:return DepartureScan(departures=[dict(timecode_sec=1.,observation='Synthetic walk-away transition.')])
            d=review_data()
            d['departure_time_sec']=min(frames,key=lambda f:abs(f.timestamp-1)).timestamp
            d['after_time_sec']=min(frames,key=lambda f:abs(f.timestamp-2.5)).timestamp
            return DepartureReview(**d)
    result=analyze(video,Settings(identity_checks=False,workflow_context=False,screen_recheck=False,storage_detail=False),model=Model())
    assert result['verdict']=='violation' and len(result['violations'])==3
    for event in result['violations']:
        ts=[f['timestamp_sec'] for f in event['evidence_frames']]
        assert event['timecode_sec'] in ts and min(ts)<event['timecode_sec']
        assert event['rule']['basis_type']=='workplace_review_check'
        assert event['rule']['url'] is None
        assert '231' not in event['rule']['document']


def test_disabling_departures_preserves_legacy_model_call_contract(video):
    class LegacyOnly:
        def ask(self,prompt,frames,schema,deadline):
            assert schema is Scan
            assert 'departure_unlocked_laptop' not in prompt
            return Scan(candidates=[])
    result=analyze(video,Settings(identity_checks=False,departure_checks=False,workflow_context=False),model=LegacyOnly())
    assert result['verdict']=='no_violation'
    assert result['analysis']['departure_checks']=={'enabled':False}
