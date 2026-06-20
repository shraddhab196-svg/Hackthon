from pydantic import BaseModel, Field


class SubmitAnswerRequest(BaseModel):
    session_id: str
    user_second_answer: str = Field(min_length=1)
    gap_closed: bool


class SubmitAnswerResponse(BaseModel):
    session_id: str
    gap_closed: bool
    brief_feedback: str
