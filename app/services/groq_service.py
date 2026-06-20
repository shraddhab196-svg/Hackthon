import json

from groq import Groq
from pydantic import BaseModel, ValidationError

from app.core.config import settings

MODEL = "llama-3.3-70b-versatile"

_client = Groq(api_key=settings.GROQ_API_KEY)


class GroqServiceError(Exception):
    pass


class GapAnalysis(BaseModel):
    gap_sentence: str
    reason: str
    follow_up_question: str


class Feedback(BaseModel):
    feedback: str


def _call_json(system_prompt: str, user_prompt: str) -> dict:
    completion = _client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return json.loads(completion.choices[0].message.content)


def _call_json_with_retry(system_prompt: str, user_prompt: str) -> dict:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return _call_json(system_prompt, user_prompt)
        except (json.JSONDecodeError, AttributeError, IndexError) as exc:
            last_error = exc
    raise GroqServiceError(f"Groq returned unparseable output: {last_error}")


GAP_SYSTEM_PROMPT = (
    "You are a strict technical interviewer checking a learner's explanation of a concept. "
    "Find exactly ONE sentence in the learner's explanation that reveals a genuine gap in "
    "understanding (vague, hand-wavy, or factually shaky). Then write ONE sharp, specific "
    'follow-up question that would expose whether the gap is real. Respond ONLY with JSON of '
    'the form {"gap_sentence": "...", "reason": "...", "follow_up_question": "..."}. '
    "gap_sentence must be a sentence taken from (or closely paraphrased from) the learner's own "
    "explanation. reason is a one-sentence explanation of why that sentence reveals a gap."
)

FEEDBACK_SYSTEM_PROMPT = (
    "You are a concise technical mentor. Given a concept, a learner's explanation, the gap that "
    "was identified, the follow-up question asked, the learner's follow-up answer, and whether a "
    "human reviewer marked the gap as closed, write ONE brief (1-2 sentence) piece of feedback for "
    'the learner. Respond ONLY with JSON of the form {"feedback": "..."}.'
)


def find_gap(concept: str, explanation: str) -> GapAnalysis:
    user_prompt = f"Concept: {concept}\n\nLearner's explanation: {explanation}"
    data = _call_json_with_retry(GAP_SYSTEM_PROMPT, user_prompt)
    try:
        return GapAnalysis.model_validate(data)
    except ValidationError as exc:
        raise GroqServiceError(f"Groq JSON missing expected fields: {exc}")


def generate_feedback(
    concept: str,
    explanation: str,
    gap_found: str,
    followup_question: str,
    user_second_answer: str,
    gap_closed: bool,
) -> Feedback:
    user_prompt = (
        f"Concept: {concept}\n"
        f"Explanation: {explanation}\n"
        f"Gap found: {gap_found}\n"
        f"Follow-up question: {followup_question}\n"
        f"Learner's follow-up answer: {user_second_answer}\n"
        f"Gap closed (human verdict): {'yes' if gap_closed else 'no'}"
    )
    data = _call_json_with_retry(FEEDBACK_SYSTEM_PROMPT, user_prompt)
    try:
        return Feedback.model_validate(data)
    except ValidationError as exc:
        raise GroqServiceError(f"Groq JSON missing expected fields: {exc}")
