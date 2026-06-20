from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    concept: str = Field(min_length=1)
    explanation: str = Field(min_length=1)


class AnalyzeResponse(BaseModel):
    session_id: str
    gap_found: str
    reason_for_gap: str
    followup_question: str
