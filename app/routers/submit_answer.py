from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.schemas.submit_answer import SubmitAnswerRequest, SubmitAnswerResponse
from app.services import groq_service, supabase_service
from app.services.groq_service import GroqServiceError

router = APIRouter()


@router.post("/submit-answer", response_model=SubmitAnswerResponse)
def submit_answer(body: SubmitAnswerRequest, user_id: str = Depends(get_current_user)) -> SubmitAnswerResponse:
    session = supabase_service.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session does not belong to this user")

    try:
        feedback = groq_service.generate_feedback(
            concept=session["concept"],
            explanation=session["explanation"],
            gap_found=session["gap_found"],
            followup_question=session["followup_question"],
            user_second_answer=body.user_second_answer,
            gap_closed=body.gap_closed,
        )
    except GroqServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    try:
        supabase_service.update_session(
            session_id=body.session_id,
            user_second_answer=body.user_second_answer,
            gap_closed=body.gap_closed,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return SubmitAnswerResponse(
        session_id=body.session_id,
        gap_closed=body.gap_closed,
        brief_feedback=feedback.feedback,
    )
