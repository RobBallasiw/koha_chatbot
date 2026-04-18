# Implementation Plan: Library AI Chatbot

## Overview

Incremental implementation of the Library AI Chatbot using Python (FastAPI), Groq Cloud LLM (Llama 3), and Koha REST API integration. Each task builds on the previous, starting with configuration and data models, then core components, and finally wiring everything together with the frontend widget.

## Tasks

- [x] 1. Set up project structure, configuration, and data models
  - [x] 1.1 Create project skeleton with FastAPI app, requirements.txt, and directory structure
    - Create `app/` package with `__init__.py`, `main.py`, `config.py`, `models.py`
    - Create `tests/` directory with `__init__.py` and `conftest.py`
    - Create `requirements.txt` with fastapi, uvicorn, httpx, groq, pydantic, python-dotenv, pytest, hypothesis, pytest-asyncio
    - _Requirements: 9.1, 9.2, 9.4_

  - [x] 1.2 Implement configuration module (`app/config.py`)
    - Read `KOHA_API_URL`, `GROQ_API_KEY`, `GROQ_API_URL`, `LIBRARY_INFO_PATH` from environment variables
    - Raise descriptive error and exit with non-zero status if any required variable is missing
    - Support `.env` file loading via python-dotenv
    - _Requirements: 9.1, 9.2, 9.3, 9.5_

  - [x] 1.3 Write property tests for configuration (test_config.py)
    - **Property 17: Configuration reads from environment variables**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - **Property 18: Missing required environment variable causes startup failure**
    - **Validates: Requirements 9.5**

  - [x] 1.4 Implement data models (`app/models.py`)
    - Define Pydantic models: `ChatRequest`, `ChatResponse`, `ErrorResponse`, `ClassificationResult`, `SearchParameters`, `CatalogRecord`, `ItemAvailability`, `LibraryInfo`, `SessionData`
    - _Requirements: 1.1, 2.1, 3.1, 8.4_

- [x] 2. Checkpoint - Ensure project structure and config tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement session manager
  - [x] 3.1 Create session manager module (`app/session_manager.py`)
    - In-memory dictionary keyed by session ID storing `SessionData` objects
    - Retrieve or create conversation history for a given session ID
    - Cap history at 20 most recent messages, dropping oldest when exceeded
    - Expire sessions after 30 minutes of inactivity using `last_accessed` timestamp
    - Periodic cleanup task to purge expired sessions
    - _Requirements: 6.1, 6.3, 6.4, 6.5_

  - [x] 3.2 Write property tests for session manager (test_session_manager.py)
    - **Property 9: Session stores all messages**
    - **Validates: Requirements 6.1**
    - **Property 11: Session history capped at 20 messages**
    - **Validates: Requirements 6.4**
    - **Property 12: New sessions start with empty history**
    - **Validates: Requirements 6.5**

- [x] 4. Implement Groq LLM client
  - [x] 4.1 Create Groq LLM client module (`app/groq_client.py`)
    - Wrap all communication with Groq Cloud API using the `groq` Python SDK
    - Include system prompt constraining responses to library topics in every call
    - Set configurable model name (default: llama3), max_tokens, and temperature
    - Handle API errors, timeouts, and rate limits with fallback messages
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 4.2 Write property tests for Groq LLM client (test_groq_client.py)
    - **Property 13: System prompt always included in LLM calls**
    - **Validates: Requirements 7.2**
    - **Property 14: Token limit always set in LLM calls**
    - **Validates: Requirements 7.4**

- [x] 5. Implement query classifier
  - [x] 5.1 Create query classifier module (`app/query_classifier.py`)
    - Send patron message with conversation context to Groq LLM with a classification prompt
    - Parse LLM response into `ClassificationResult` with intent and confidence
    - Return "unclear" intent when confidence is below threshold
    - _Requirements: 4.1, 4.4, 4.5_

  - [x] 5.2 Write property tests for query classifier (test_query_classifier.py)
    - **Property 7: Query classification returns valid result**
    - **Validates: Requirements 4.1**
    - **Property 8: Routing matches classification intent**
    - **Validates: Requirements 4.2, 4.3**

- [x] 6. Checkpoint - Ensure session, LLM client, and classifier tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement library info handler
  - [x] 7.1 Create library info store and handler (`app/library_info_handler.py`)
    - Load library info from JSON file at configurable path (from environment variable)
    - Parse into `LibraryInfo` model with hours, policies, fines sections
    - Match patron query to relevant info sections
    - Use Groq LLM to generate natural language response from matched data
    - Return "contact staff" message when no relevant info is found
    - Exit with error if file not found or malformed at startup
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 9.3_

  - [x] 7.2 Create sample library info data file (`data/library_info.json`)
    - Include hours, policies, and fines sections matching the design schema
    - _Requirements: 3.5_

  - [x] 7.3 Write property tests for library info handler (test_library_info_handler.py)
    - **Property 6: Library info retrieval returns relevant data**
    - **Validates: Requirements 3.1, 3.2, 3.3**

- [x] 8. Implement catalog search handler
  - [x] 8.1 Create catalog search handler (`app/catalog_handler.py`)
    - Use Groq LLM to extract `SearchParameters` from natural language query
    - Query Koha REST API with extracted parameters using httpx async client
    - Parse Koha API response into `CatalogRecord` and `ItemAvailability` models
    - Format results as natural language via Groq LLM including title, author, call number
    - Group multi-copy results by branch for availability responses
    - Handle Koha API errors with user-friendly fallback messages
    - Return "no results found" message with search refinement suggestions when empty
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 8.2 Write property tests for catalog search handler (test_catalog_handler.py)
    - **Property 1: Search parameter extraction produces valid structure**
    - **Validates: Requirements 1.1**
    - **Property 2: Catalog result formatting includes required fields**
    - **Validates: Requirements 1.3**
    - **Property 3: Available item response includes location details**
    - **Validates: Requirements 2.2**
    - **Property 4: Checked-out item response includes due date**
    - **Validates: Requirements 2.3**
    - **Property 5: Multi-copy availability grouped by branch**
    - **Validates: Requirements 2.4**

- [x] 9. Checkpoint - Ensure handler tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement REST API endpoint and request routing
  - [x] 10.1 Create the main chat endpoint (`app/main.py`)
    - Implement `POST /api/chat` accepting `ChatRequest` and returning `ChatResponse`
    - Validate non-empty message and valid session_id, return 400 with `ErrorResponse` on failure
    - Retrieve session history via session manager
    - Classify query via query classifier
    - Route to catalog search handler or library info handler based on intent
    - Ask clarifying question for "unclear" intent
    - Include conversation history in LLM calls
    - Store user message and assistant reply in session
    - Serve static files for the chat widget
    - _Requirements: 4.2, 4.3, 6.1, 6.2, 8.1, 8.2, 8.3, 8.4_

  - [x] 10.2 Write property tests for API endpoint (test_api_endpoint.py)
    - **Property 15: Invalid requests are rejected with 400**
    - **Validates: Requirements 8.2**
    - **Property 16: Valid responses contain required JSON fields**
    - **Validates: Requirements 8.4**
    - **Property 10: LLM calls include conversation history**
    - **Validates: Requirements 6.2**

- [x] 11. Implement chat widget frontend
  - [x] 11.1 Create chat widget HTML/CSS/JS (`app/static/index.html`)
    - Standalone HTML page with embedded CSS and JS
    - Text input field with send button
    - Scrollable message history area with conversational thread format
    - Generate unique session ID on page load (UUID)
    - Send messages via `POST /api/chat` to the backend
    - Display connection error state when backend is unreachable
    - Responsive layout for desktop and mobile
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 12. Integration wiring and startup validation
  - [x] 12.1 Wire startup lifecycle in `app/main.py`
    - Load and validate configuration on startup
    - Load and validate library info store on startup
    - Start session cleanup background task
    - Add CORS middleware for iframe embedding
    - _Requirements: 9.3, 9.5, 3.5, 5.1_

  - [x] 12.2 Create `.env.example` and `README.md` with setup instructions
    - Document all required environment variables
    - Include instructions for running on Windows (dev) and Linux (production)
    - _Requirements: 9.1, 9.2, 9.4_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use the `hypothesis` library and mock external API calls
- Checkpoints ensure incremental validation throughout implementation
- All external service calls (Groq, Koha) should be mocked in tests
