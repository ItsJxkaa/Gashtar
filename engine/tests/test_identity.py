import pytest
from cashguard.config import Settings
from cashguard.identity import IdentityScan,IdentityReview,missing_id_supported,analyze_identity
from cashguard.pipeline import RULES
from test_service import video
from cashguard.identity_grounding import IdentityGrounding
from test_identity_grounding import grounding_data
from cashguard.identity_documents import IdentityDocumentLocation,IdentityDocumentReview
from test_identity_documents import document_data

def data():
    return dict(customer_cash_transaction='yes',complete_arrival_through_completion='yes',
        handover_and_document_area_visible='yes',cash_transfer_visible='yes',
        physical_id_presentation='none_visible',digital_id_check='none_visible',
        earlier_service_or_role_ambiguity='no',cash_time_sec=2.,confidence=.9,
        observation='Synthetic complete customer transfer without ID presentation',counterevidence='Synthetic unobscured sequence')

@pytest.mark.parametrize('field,value',[
    ('customer_cash_transaction','no'),('customer_cash_transaction','unknown'),
    ('complete_arrival_through_completion','no'),('complete_arrival_through_completion','unknown'),
    ('handover_and_document_area_visible','unknown'),('cash_transfer_visible','no'),
    ('physical_id_presentation','visible_before_cash'),('physical_id_presentation','visible_after_cash'),
    ('physical_id_presentation','unknown'),('digital_id_check','visible'),
    ('digital_id_check','plausible_or_obscured'),('digital_id_check','unknown'),
    ('earlier_service_or_role_ambiguity','yes'),('earlier_service_or_role_ambiguity','unknown'),('confidence',.7),
])
def test_missing_paper_alone_cannot_trigger_id_absence(field,value):
    d=data();d[field]=value
    assert not missing_id_supported(IdentityReview(**d),.75)


def test_complete_no_presentation_sequence_gets_workflow_not_legal_provenance(video):
    class Model:
        def ask(self,prompt,frames,schema,deadline):
            if schema is IdentityScan:return IdentityScan(transactions=[dict(cash_time_sec=2.,observation='Synthetic customer cash transfer')])
            if schema is IdentityGrounding:return IdentityGrounding(**grounding_data())
            if schema is IdentityDocumentLocation:return IdentityDocumentLocation(handover_area=dict(found=True,x1=0,y1=0,x2=1000,y2=1000,confidence=.9))
            if schema is IdentityDocumentReview:return IdentityDocumentReview(**document_data())
            d=data();d['cash_time_sec']=min(frames,key=lambda f:abs(f.timestamp-2)).timestamp
            return IdentityReview(**d)
    events,audit=analyze_identity(video,4.,Settings(),Model(),100,RULES['customer_cash_no_visible_id'])
    assert len(events)==1 and audit['transactions_reviewed']==1
    event=events[0]
    assert event['rule']['url'] is None and event['rule']['basis_type']=='workplace_review_check'
    assert event['timecode_sec'] in [f['timestamp_sec'] for f in event['evidence_frames']]
