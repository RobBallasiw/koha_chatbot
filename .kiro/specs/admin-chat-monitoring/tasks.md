# Tasks — Admin Chat Monitoring

## Task 1: Data Models and Session Store

- [x] 1.1 Add new Pydantic models (`MessageRecord`, `SessionSummary`, `SessionDetail`, `SessionListResponse`, `SessionStatsResponse`) to `app/models.py`
- [x] 1.2 Create `app/session_store.py` with SQLite-backed `SessionStore` class: init DB schema, `save_message()`, `get_sessions()`, `get_session()`, `get_stats()`, `search_sessions()`
- [x] 1.3 Write property-based tests for SessionStore (Properties 1, 2, 3, 7) in `tests/test_session_store.py`
  - [x] 1.3.1 Property 1: Message persistence round-trip — save messages then retrieve, verify order and content match
  - [x] 1.3.2 Property 2: Persisted message structure invariant — verify role, content, timestamp on all saved messages
  - [x] 1.3.3 Property 3: Session list ordered by most recent activity — verify descending last_activity order
  - [x] 1.3.4 Property 7: Messages in chronological order — verify ascending timestamp order in detail response

## Task 2: Admin Authentication

- [x] 2.1 Add `ADMIN_API_KEY` to config: update `app/config.py` to optionally read `ADMIN_API_KEY` env var
- [x] 2.2 Create `app/admin_auth.py` with FastAPI dependency that validates `X-Admin-Key` header
- [x] 2.3 Write property-based tests for auth (Property 10) in `tests/test_admin_auth.py`
  - [x] 2.3.1 Property 10: Authentication gate — missing/wrong key returns 401, correct key does not

## Task 3: Admin API Endpoints

- [x] 3.1 Create `app/admin_routes.py` with APIRouter: GET `/admin/api/sessions`, GET `/admin/api/sessions/{session_id}`, GET `/admin/api/stats`
- [x] 3.2 Mount admin router in `app/main.py`, initialize `SessionStore` at startup
- [x] 3.3 Write property-based tests for admin API (Properties 4, 5, 6, 8, 9) in `tests/test_admin_api.py`
  - [x] 3.3.1 Property 4: Session metadata completeness — verify all required fields present
  - [x] 3.3.2 Property 5: Status filter correctness — filtered results match requested status
  - [x] 3.3.3 Property 6: Keyword search returns matching sessions — results contain keyword in messages
  - [x] 3.3.4 Property 8: Pagination respects page size — response size ≤ page_size, total is accurate
  - [x] 3.3.5 Property 9: Non-existent session returns 404

## Task 4: Admin Statistics Endpoint

- [x] 4.1 Implement `get_stats()` in `SessionStore` returning aggregate counts
- [x] 4.2 Write property-based tests for stats (Property 11) in `tests/test_admin_stats.py`
  - [x] 4.2.1 Property 11: Statistics accuracy — totals match actual session/message counts

## Task 5: Integrate Persistence into Chat Endpoint

- [x] 5.1 Modify `app/main.py` chat endpoint to persist messages to `SessionStore` after in-memory storage
- [x] 5.2 Add graceful degradation: wrap persistence in try/except, log errors, don't affect patron response
- [x] 5.3 Write unit tests for persistence integration: verify chat works when DB is unavailable (Req 1.5), verify persistence survives in-memory cleanup (Req 1.3)

## Task 6: Admin Dashboard Frontend

- [x] 6.1 Create `app/static/admin.html` with session list view, detail view, stats panel, pagination, search, and status filter
- [x] 6.2 Add route in `app/main.py` to serve admin dashboard at `/admin/`
- [x] 6.3 Write unit test verifying GET `/admin/` returns HTML content (Req 7.1)

## Task 7: Configuration and Documentation

- [x] 7.1 Add `ADMIN_API_KEY` and `SESSION_DB_PATH` to `.env.example`
- [x] 7.2 Update `README.md` with admin dashboard setup instructions
