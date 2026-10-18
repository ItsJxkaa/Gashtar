import pytest
from cashguard.identity_documents import IdentityDocumentReview,no_document_counterevidence

def document_data():
 return dict(handover_area_resolved='yes',physical_id='none_visible',digital_id='none_visible',confidence=.9,observation='Synthetic resolved handover area without ID presentation')

@pytest.mark.parametrize('field,value',[
 ('handover_area_resolved','no'),('handover_area_resolved','unknown'),('physical_id','visible_or_plausible'),
 ('physical_id','unresolvable'),('digital_id','visible_or_plausible'),('digital_id','unresolvable'),('confidence',.5)])
def test_visible_or_unresolved_document_blocks_absence(field,value):
 d=document_data();d[field]=value
 assert not no_document_counterevidence(IdentityDocumentReview(**d),.75)

def test_resolved_absence_survives_countercheck():
 assert no_document_counterevidence(IdentityDocumentReview(**document_data()),.75)
