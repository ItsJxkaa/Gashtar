import pytest
from cashguard.identity_grounding import IdentityGrounding,grounded_customer_transfer

def grounding_data():
 return dict(new_customer_entry_visible='yes',cashier_present_before_customer='yes',customer_exit_visible='yes',
  entry_time_sec=.2,cash_time_sec=2.,exit_time_sec=3.5,cash_source='customer',cash_destination='cashier',
  separate_service_roles_resolved='yes',physical_id_presentation='none_visible',digital_id_check='none_visible',
  document_or_role_ambiguity='no',confidence=.9,observation='Synthetic independently grounded customer handover')

@pytest.mark.parametrize('field,value',[
 ('new_customer_entry_visible','no'),('cashier_present_before_customer','unknown'),('customer_exit_visible','no'),
 ('entry_time_sec',None),('entry_time_sec',2.5),('cash_time_sec',None),('exit_time_sec',1.5),('exit_time_sec',5.),
 ('cash_source','equipment_or_storage'),('cash_destination','equipment_or_storage'),('cash_destination','customer'),
 ('separate_service_roles_resolved','unknown'),('physical_id_presentation','visible'),('physical_id_presentation','unknown'),
 ('digital_id_check','plausible_or_obscured'),('document_or_role_ambiguity','yes'),('confidence',.6)])
def test_grounding_rejects_missing_or_conflicting_anchors(field,value):
 d=grounding_data();d[field]=value
 assert not grounded_customer_transfer(IdentityGrounding(**d),2.,4.,.75)

def test_later_real_handover_cannot_validate_earlier_internal_cash_movement():
 d=grounding_data();d.update(entry_time_sec=25.,cash_time_sec=35.,exit_time_sec=45.)
 g=IdentityGrounding(**d)
 assert not grounded_customer_transfer(g,6.,50.,.75)
 assert grounded_customer_transfer(g,35.,50.,.75)
