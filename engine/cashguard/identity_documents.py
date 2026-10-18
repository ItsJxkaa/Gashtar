"""Independent original-resolution search for ID presentation counterevidence."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .screen import ScreenLocation
from .video import sample,uniform,Frame

class IdentityDocumentLocation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    handover_area: ScreenLocation

class IdentityDocumentReview(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    handover_area_resolved: Literal['yes','no','unknown']
    physical_id: Literal['visible_or_plausible','none_visible','unresolvable']
    digital_id: Literal['visible_or_plausible','none_visible','unresolvable']
    confidence: float=Field(ge=0,le=1)
    observation: str=Field(max_length=500)

def no_document_counterevidence(d,threshold):
    return (d.handover_area_resolved=='yes' and d.physical_id=='none_visible'
        and d.digital_id=='none_visible' and d.confidence>=threshold)

def inspect_identity_documents(path,duration,episode,cash_time,settings,model,deadline):
    context=sample(path,[max(0,episode[0]-.0001),max(0,cash_time-.0001)],edge=4096)
    location=model.ask('''Locate the shared document-and-cash handover area
in the LAST full frame. Include the tabletop between cashier and customer and
both participants' hands, not just the counting machine. Return a normalized
0..1000 bounding rectangle, top-left origin. This is a proposed crop, not a
finding. If the shared handover region is obscured or cannot be located, use
found=false. Do not transcribe any personal identifier.''',context,IdentityDocumentLocation,deadline)
    box=location.handover_area
    unknown=IdentityDocumentReview(handover_area_resolved='unknown',physical_id='unresolvable',digital_id='unresolvable',confidence=0,observation='Document area could not be resolved')
    if not box.found or box.confidence<settings.confirmation_threshold or box.x2<=box.x1 or box.y2<=box.y1:return unknown
    frames=sample(path,uniform(max(0,episode[0]-.5),min(duration-.05,episode[1]+.5),30),edge=4096)
    crops=[]
    for frame in frames:
        w,h=frame.image.size
        rect=(max(0,int((box.x1-30)*w/1000)),max(0,int((box.y1-30)*h/1000)),min(w,int((box.x2+30)*w/1000)),min(h,int((box.y2+30)*h/1000)))
        if min(rect[2]-rect[0],rect[3]-rect[1])<12:return unknown
        crops.append(Frame(frame.timestamp,frame.image.crop(rect)))
    return model.ask('''Images 1 and 2 are full-frame context. All remaining
images are chronological original-resolution crops of the proposed handover
region, with their actual timestamps. Independently search this customer's
ENTIRE episode for counterevidence to missing ID presentation. Check the crop
really covers the hands and documents throughout; a wrong or obscured crop is
unresolvable, not absence.

Look for an ID-like card or identification paper presented, examined, retained,
or returned, including before cash and after counting. Do NOT require legible
personal text; do not transcribe identifiers. An unreadable card/document that
could be ID is visible_or_plausible. Distinguish banknotes from a separate
identification item using appearance and handling; cash itself is not ID.
Check phone/screen interaction plausibly used to present digital ID. Generic
laptop typing alone is not an ID check. Use unresolvable where objects or
actions cannot be distinguished. Return none_visible only when the handover
area is resolved and no physical or plausible digital presentation is seen.
Report observations, not legal guilt.''',context+crops,IdentityDocumentReview,deadline)
