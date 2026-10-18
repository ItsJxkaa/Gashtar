from pydantic import BaseModel, ConfigDict, Field


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    rule_id: str
    timecode_sec: float = Field(ge=0)
    observation: str = Field(min_length=10, max_length=1200)
    confidence: float = Field(ge=0, le=1)
    complete_sequence: bool


class Scan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[Candidate] = Field(max_length=12)


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    confirmed: bool
    rule_id: str
    timecode_sec: float = Field(ge=0)
    observation: str = Field(min_length=5, max_length=1200)
    counterevidence: str = Field(max_length=1200)
    confidence: float = Field(ge=0, le=1)
    complete_sequence: bool


class Evidence(BaseModel):
    timestamp_sec: float = Field(ge=0)
    image_base64: str


class Violation(BaseModel):
    type: str
    timecode_sec: float = Field(ge=0)
    description: str
    evidence_frames: list[Evidence] = Field(min_length=1, max_length=3)
    rule: dict
    confidence: float

