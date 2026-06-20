from supabase import Client, create_client

from app.core.config import settings

TABLE = "concept_check_sessions"

_client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def create_session(user_id: str, concept: str, explanation: str, gap_found: str, followup_question: str) -> dict:
    response = (
        _client.table(TABLE)
        .insert(
            {
                "user_id": user_id,
                "concept": concept,
                "explanation": explanation,
                "gap_found": gap_found,
                "followup_question": followup_question,
            }
        )
        .execute()
    )
    return response.data[0]


def get_session(session_id: str) -> dict | None:
    response = _client.table(TABLE).select("*").eq("id", session_id).execute()
    if not response.data:
        return None
    return response.data[0]


def update_session(session_id: str, user_second_answer: str, gap_closed: bool) -> dict:
    response = (
        _client.table(TABLE)
        .update({"user_second_answer": user_second_answer, "gap_closed": gap_closed})
        .eq("id", session_id)
        .execute()
    )
    return response.data[0]
