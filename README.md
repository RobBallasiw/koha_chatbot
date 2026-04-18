# Library AI Chatbot

A conversational assistant that integrates with the Koha ILS and a local Ollama LLM (Llama 3.2) to help library patrons search the catalog, check book availability, and get answers about library hours, policies, and fines.

## Prerequisites

- Python 3.11+
- [Ollama](https://ollama.com) installed and running locally
- A running Koha ILS instance with the REST API enabled

## Quick Start

```bash
# Clone the repository
git clone <repo-url> && cd library-ai-chatbot

# Create and activate a virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Pull the LLM model (requires Ollama to be running)
ollama pull llama3.2:3b

# Configure environment
cp .env.example .env
# Edit .env and fill in your values
```

## Running the Application

Development (Windows or Linux):

```bash
uvicorn app.main:app --reload
```

The chat widget is served at `http://localhost:8000/static/index.html`.

Production (Linux):

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Running Tests

```bash
pytest
```

## Embedding in Koha OPAC

There are two ways to add the chatbot to your Koha OPAC. Both require the chatbot backend to be running and reachable from patrons' browsers.

### Option A: JavaScript embed (recommended)

This adds a floating chat button in the bottom-right corner that opens the widget in a popup. Paste the following into Koha's **OPACUserJS** system preference (Administration → System Preferences → OPAC → OPACUserJS):

```js
// Library AI Chatbot — change the URL to your chatbot server
(function(){
  var s = document.createElement("script");
  s.src = "http://your-chatbot-host:8000/static/koha-embed.js";
  document.body.appendChild(s);
})();
```

Then edit `app/static/koha-embed.js` and set `CHATBOT_URL` to your backend's public URL (e.g. `https://chatbot.mylibrary.org`).

### Option B: Simple iframe

Add this to **OPACUserJS** or a custom HTML block for a fixed-position iframe:

```html
<iframe
  src="http://your-chatbot-host:8000/static/index.html"
  style="position:fixed;bottom:0;right:0;width:400px;height:560px;border:none;z-index:9999;"
  title="Library Chat Assistant">
</iframe>
```

Adjust the `src` URL and dimensions to match your deployment.

## Admin Chat Monitoring Dashboard

The admin dashboard lets library staff monitor patron-chatbot conversations, review session transcripts, and view usage statistics.

### Configuration

Add these environment variables to your `.env` file:

| Variable | Description | Default |
|---|---|---|
| `ADMIN_API_KEY` | Shared API key for admin access | *(required)* |
| `SESSION_DB_PATH` | Path to the SQLite session database | `data/sessions.db` |

### Accessing the Dashboard

Navigate to `/admin/` in your browser (e.g. `http://localhost:8000/admin/`). Enter your `ADMIN_API_KEY` value when prompted.

### Admin API Endpoints

All endpoints require the `X-Admin-Key` header set to your configured API key.

| Endpoint | Description |
|---|---|
| `GET /admin/api/sessions` | List sessions (supports `page`, `page_size`, `status`, and `search` query params) |
| `GET /admin/api/sessions/{session_id}` | Full session detail with message transcript |
| `GET /admin/api/stats` | Aggregate usage statistics |

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `KOHA_API_URL` | Base URL of the Koha REST API | `http://your-koha-server:8080` |
| `LIBRARY_INFO_PATH` | Path to the library info JSON file | `data/library_info.json` |
| `OLLAMA_URL` | Ollama OpenAI-compatible API endpoint | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | Ollama model to use | `llama3.2:3b` |
| `ADMIN_API_KEY` | Shared API key for admin dashboard access | `my-secret-key` |
| `SESSION_DB_PATH` | Path to SQLite session database | `data/sessions.db` |

`KOHA_API_URL` and `LIBRARY_INFO_PATH` are required. The application will exit with an error if either is missing. `ADMIN_API_KEY` is required for admin dashboard access. Other variables have sensible defaults.

## Project Structure

```
app/
  main.py                 # FastAPI app, /api/chat endpoint, startup lifecycle
  config.py               # Environment variable loading and validation
  models.py               # Pydantic data models
  groq_client.py          # LLM client wrapper (Ollama via OpenAI-compatible API)
  query_classifier.py     # Intent classification (catalog search vs. library info)
  catalog_handler.py      # Catalog search via Koha REST API
  library_info_handler.py # Library hours, policies, and fines handler
  session_manager.py      # In-memory conversation session management
  session_store.py        # SQLite-backed persistent session storage
  admin_auth.py           # Admin API key authentication dependency
  admin_routes.py         # Admin API endpoints (sessions, stats)
  static/
    index.html            # Chat widget frontend
    admin.html            # Admin monitoring dashboard
    koha-embed.js         # Embeddable script for Koha OPAC integration
data/
  library_info.json       # Library information (hours, policies, fines)
tests/                    # Unit and property-based tests
requirements.txt          # Python dependencies
.env.example              # Environment variable template
```
