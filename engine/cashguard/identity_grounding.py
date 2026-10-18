"""Independently ground service roles and an observed customer episode."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .video import sample,uniform

class IdentityGrounding(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    new_customer_entry_visible: Literal['yes','no','unknown']
    cashier_present_before_customer: Literal['yes','no','unknown']
    customer_exit_visible: Literal['yes','no','unknown']
    entry_time_sec: float|None=Field(ge=0)
    cash_time_sec: float|None=Field(ge=0)
    exit_time_sec: float|None=Field(ge=0)
    cash_source: Literal['customer','cashier','equipment_or_storage','unknown']
    cash_destination: Literal['customer','cashier','equipment_or_storage','unknown']
    separate_service_roles_resolved: Literal['yes','no','unknown']
    physical_id_presentation: Literal['visible','none_visible','unknown']
    digital_id_check: Literal['visible','plausible_or_obscured','none_visible','unknown']
    document_or_role_ambiguity: Literal['yes','no']
    confidence: float=Field(ge=0,le=1)
    observation: str=Field(max_length=500)

def grounded_customer_transfer(g,candidate_time,duration,threshold):
    if None in [g.entry_time_sec,g.cash_time_sec,g.exit_time_sec]:return False
    return (g.new_customer_entry_visible=='yes' and g.cashier_present_before_customer=='yes'
        and g.customer_exit_visible=='yes' and g.separate_service_roles_resolved=='yes'
        and 0<=g.entry_time_sec<g.cash_time_sec<g.exit_time_sec<duration
        and abs(g.cash_time_sec-candidate_time)<=3
        and {g.cash_source,g.cash_destination}=={'customer','cashier'}
        and g.physical_id_presentation=='none_visible' and g.digital_id_check=='none_visible'
        and g.document_or_role_ambiguity=='no' and g.confidence>=threshold)

def ground_identity(path,duration,candidate_time,settings,model,deadline):
    count=min(16,96-settings.overview_frames) if settings.native_video else min(8,32-settings.overview_frames)
    frames=sample(path,uniform(0,duration-.05,settings.overview_frames)+
        uniform(max(0,candidate_time-3),min(duration-.05,candidate_time+3),count))
    g=model.ask(f'''Independently reconstruct the observable service episode
around {candidate_time:.4f} seconds. No previous model observations are provided.
Track the employee who operates the workstation, then the separate customer's
visible entry, their interaction, and their exit. Use positions and continuous
actions, never faces. A person arriving to operate their own workstation is not
automatically a customer. Cash taken from a folder/safe or counting machine is
employee-only handling unless a distinct customer transfer is actually visible.

For the action near the requested time, report cash source and destination roles,
and the supplied timestamp of the actual customer-to-cashier (or reverse)
transfer. Do not substitute a different later transaction for an internal cash
movement at the requested time. Give customer entry and exit timestamps only
when those transitions are visible. If the customer was already in the room,
the transaction is unfinished, or role continuity is unresolved, report unknown
or no; use null for unobserved timestamps.

Actively look for any physical ID presentation anywhere in this customer episode,
including brief card/paper handling before cash and document return after cash.
A document that could be ID but is unreadable is uncertainty, not proven absence.
Check visible or plausibly obscured digital ID. Laptop use alone does not prove
identification. Give factual states and uncertainty; do not decide legal guilt.
All timestamps must come from the supplied frames.''',frames,IdentityGrounding,deadline)
    return g,frames
