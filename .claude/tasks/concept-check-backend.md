# ConceptCheck Backend — Implementation Plan

## Goal (MVP scope)
A FastAPI backend with 3 endpoints that:
1. Takes a concept + user explanation, asks Groq (llama-3.3-70b-versatile) for ONE gap + ONE follow-up question, stores it in Supabase.
2. Takes the user's follow-up answer + a human-marked gap_closed verdict, stores it, and returns brief AI feedback.
3. Health check.

No new abstractions beyond what's needed to call Groq, talk to Supabase, and verify a Supabase JWT.

---

## Decisions (confirmed)

These came from a mismatch between the listed Outputs and the existing DB schema. The table `concept_check_sessions` has no columns for `reason_for_gap` or `brief_feedback`, only:
`id, user_id, concept, explanation, gap_found, followup_question, user_second_answer, gap_closed, created_at`.

1. **Reason for gap** → response-only, not persisted. `gap_found` column stores just the gap sentence.
2. **Brief feedback** → response-only, not persisted.
3. **`gap_closed` verdict** → comes in the same request as `user_second_answer`, one endpoint (`/submit-answer`), no separate reviewer endpoint.
4. **Auth** → required (Supabase JWT) on both `/analyze` and `/submit-answer`; 401 if missing/invalid.
5. **Session ownership** → `/submit-answer` returns 403 if the JWT's `user_id` doesn't match the session's stored `user_id`.

---

## Tech decisions

- **Groq SDK**: use the official `groq` Python package (OpenAI-compatible client), not raw `httpx`, for simplicity and built-in retries.
- **Groq output reliability**: use Groq's JSON mode (`response_format={"type": "json_object"}`) with a strict system prompt so the model returns parseable JSON (`{"gap_sentence": ..., "reason": ..., "follow_up_question": ...}`). Validate with a Pydantic model; on parse failure, retry the Groq call once, then return 502 if it still fails.
- **Supabase access from backend**: use `supabase-py` client initialized with the **service role key** (server-side secret), so the backend itself does the DB write/read and bypasses RLS — RLS is not needed server-side since we already authenticate the caller via JWT ourselves.
- **JWT verification**: decode the Supabase-issued JWT locally with `PyJWT` using `SUPABASE_JWT_SECRET` (HS256, audience `"authenticated"`), extract `sub` as `user_id`. No network round-trip to Supabase Auth needed. Implemented as a FastAPI dependency (`get_current_user`) used on `/analyze` and `/submit-answer`.
- **Config**: `pydantic-settings` reading from environment / `.env` (`GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`).
- **Deployment**: Render web service, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, env vars set in Render dashboard (not committed).

---

## File structure

```
app/
  __init__.py
  main.py                  # FastAPI() app, mounts routers, CORS
  core/
    config.py              # Settings (pydantic-settings)
    security.py            # get_current_user JWT dependency
  schemas/
    analyze.py             # AnalyzeRequest / AnalyzeResponse
    submit_answer.py       # SubmitAnswerRequest / SubmitAnswerResponse
  services/
    groq_service.py        # find_gap(), generate_feedback() — prompt + call + validate
    supabase_service.py    # create_session(), get_session(), update_session()
  routers/
    analyze.py             # POST /analyze
    submit_answer.py       # POST /submit-answer
    health.py              # GET /health
requirements.txt
.env.example
```

---

## Endpoint contracts

### `GET /health`
- No auth.
- Returns `{"status": "ok"}`.

### `POST /analyze`
- Auth: required (JWT bearer).
- Request: `{"concept": str, "explanation": str}`
- Process:
  1. Validate non-empty strings.
  2. Call `groq_service.find_gap(concept, explanation)` → `{gap_sentence, reason, follow_up_question}`.
  3. Insert row into `concept_check_sessions`: `user_id` (from JWT), `concept`, `explanation`, `gap_found=gap_sentence`, `followup_question`. `user_second_answer`/`gap_closed` left null.
  4. Return `{session_id, gap_found, reason_for_gap, followup_question}`.
- Errors: 401 (bad/missing JWT), 502 (Groq failure/unparseable output), 500 (DB insert failure).

### `POST /submit-answer`
- Auth: required (JWT bearer); session must belong to caller.
- Request: `{"session_id": str, "user_second_answer": str, "gap_closed": bool}`
- Process:
  1. Fetch session by `session_id`; 404 if missing, 403 if `user_id` mismatch.
  2. Call `groq_service.generate_feedback(concept, explanation, gap_found, followup_question, user_second_answer, gap_closed)` → `{feedback}`.
  3. Update row: `user_second_answer`, `gap_closed`.
  4. Return `{session_id, gap_closed, brief_feedback}`.
- Errors: 401, 403, 404, 502 (Groq), 500 (DB update failure).

---

## Task breakdown

1. Scaffold project: `app/` package structure, `requirements.txt`, `.env.example`, `.gitignore` entry for `.env`.
2. `core/config.py` — `Settings` class loading `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` from env.
3. `core/security.py` — `get_current_user` dependency: extract bearer token, decode with PyJWT + `SUPABASE_JWT_SECRET`, return `user_id`; raise 401 on any failure.
4. `services/supabase_service.py` — Supabase client init, `create_session(...)`, `get_session(session_id)`, `update_session(session_id, ...)`.
5. `services/groq_service.py` — Groq client init, `find_gap(concept, explanation)` and `generate_feedback(...)`, both using JSON-mode prompts + Pydantic validation + single retry on parse failure.
6. `schemas/analyze.py`, `schemas/submit_answer.py` — request/response Pydantic models.
7. `routers/health.py`, `routers/analyze.py`, `routers/submit_answer.py` — wire endpoints to services, map exceptions to HTTP status codes.
8. `main.py` — create app, include routers, basic CORS config.
9. Manual smoke test: run locally with `uvicorn`, hit all 3 endpoints with `curl`/Postman against a real Groq key and Supabase project (you'll need to supply a valid test JWT or I'll add a short local-dev note on how to mint one from Supabase Auth for testing).
10. Render deploy notes: document required env vars and start command (no `render.yaml` unless you want IaC — default is dashboard-configured service).

---

## Out of scope for this MVP (explicitly not doing)
- No rate limiting, no caching, no streaming responses.
- No retry/backoff beyond a single Groq retry on bad JSON.
- No automated test suite (manual curl verification only) — can add later if you want.
- No admin/reviewer-specific endpoint — verdict is submitted by the same caller in `/submit-answer`.

---

## Implementation notes (tasks 1–8, done)

All files created under `app/`:
- `core/config.py` — `Settings` (pydantic-settings), reads `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` from `.env`/env.
- `core/security.py` — `get_current_user` dependency, decodes bearer JWT with `PyJWT` (HS256, `aud="authenticated"`), returns `sub` as `user_id`; 401 on missing/invalid/expired token.
- `services/supabase_service.py` — `create_client` with the service-role key (bypasses RLS); `create_session`, `get_session`, `update_session` against `concept_check_sessions`.
- `services/groq_service.py` — Groq client, JSON-mode chat completion, one retry on unparseable JSON, then raises `GroqServiceError`. `find_gap()` returns `gap_sentence`/`reason`/`follow_up_question`; `generate_feedback()` returns `feedback`.
- `schemas/analyze.py`, `schemas/submit_answer.py` — request/response Pydantic models matching the contracts above.
- `routers/health.py`, `routers/analyze.py`, `routers/submit_answer.py` — wire it together; `submit_answer` does session lookup → 404 if missing, 403 if `user_id` mismatch, then Groq feedback (502 on failure) → DB update (500 on failure).
- `main.py` — `FastAPI()` app, permissive CORS (`*`), all 3 routers mounted.
- `requirements.txt`, `.env.example`, `.gitignore` at repo root.

Reviewed statically (no execution) — this sandbox has no Python interpreter installed, only a Windows Store stub `python.exe` alias with no real install behind it. Code was not run here.

## How to smoke test locally (task 9 — run this yourself)

1. `python -m venv .venv && .venv\Scripts\activate` (PowerShell) then `pip install -r requirements.txt`.
2. Copy `.env.example` → `.env` and fill in `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` (the JWT secret is under Supabase dashboard → Project Settings → API → JWT Settings).
3. Run `uvicorn app.main:app --reload`.
4. Health check: `curl http://localhost:8000/health` → expect `{"status":"ok"}`.
5. Get a real JWT to test with — easiest path is the Supabase JS/Python client signing in a test user (`supabase.auth.sign_in_with_password(...)`) and copying `session.access_token`; or mint one manually with PyJWT signed with the same `SUPABASE_JWT_SECRET` for a throwaway `sub` (only works because RLS is bypassed server-side via service role — a manually-signed token will pass `get_current_user` but won't exist as a real Supabase user, which is fine for testing this backend in isolation).
6. `POST /analyze`:
   ```
   curl -X POST http://localhost:8000/analyze \
     -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" \
     -d '{"concept":"REST APIs","explanation":"APIs let the frontend talk to a database directly using HTTP."}'
   ```
   Expect 200 with `session_id`, `gap_found`, `reason_for_gap`, `followup_question`.
7. `POST /submit-answer` using the `session_id` from step 6:
   ```
   curl -X POST http://localhost:8000/submit-answer \
     -H "Authorization: Bearer <JWT>" -H "Content-Type: application/json" \
     -d '{"session_id":"<id>","user_second_answer":"...","gap_closed":true}'
   ```
   Expect 200 with `session_id`, `gap_closed`, `brief_feedback`. Confirm the row in Supabase now has `user_second_answer` and `gap_closed` populated.
8. Negative checks worth doing once: call `/analyze` with no `Authorization` header (expect 401); call `/submit-answer` with a JWT for a different `sub` than the session owner (expect 403); call `/submit-answer` with a bogus `session_id` (expect 404).

## Render deployment (task 10)

1. Push this repo to GitHub (if not already).
2. In Render: New → Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`.
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. Environment variables (Render dashboard → Environment), same names as `.env.example`: `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`. Never commit these — `.gitignore` already excludes `.env`.
6. Instance type: free/starter tier is fine for MVP demo load.
7. After first deploy, hit `https://<service>.onrender.com/health` to confirm it's live, then repeat the `/analyze` → `/submit-answer` smoke test against the deployed URL.
