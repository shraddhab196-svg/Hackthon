from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.services import groq_service, supabase_service
from app.services.groq_service import GroqServiceError

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(body: AnalyzeRequest, user_id: str = Depends(get_current_user)) -> AnalyzeResponse:
    try:
        gap = groq_service.find_gap(body.concept, body.explanation)
    except GroqServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    try:
        session = supabase_service.create_session(
            user_id=user_id,
            concept=body.concept,
            explanation=body.explanation,
            gap_found=gap.gap_sentence,
            followup_question=gap.follow_up_question,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return AnalyzeResponse(
        session_id=session["id"],
        gap_found=gap.gap_sentence,
        reason_for_gap=gap.reason,
        followup_question=gap.follow_up_question,
    )
