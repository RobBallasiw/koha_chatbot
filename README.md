# Library AI Chatbot

A conversational assistant that integrates with the Koha ILS and Groq Cloud LLM (Llama 3) to help library patrons search the catalog, check book availability, and get answers about library hours, policies, and fines.

## Prerequisites

- Python 3.11+
- A [Groq Cloud](https://console.groq.com) API key
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

Add the following iframe snippet to your Koha OPAC system preferences (e.g. `OPACUserJS` or a custom HTML block):

```html
<iframe
  src="http://your-chatbot-host:8000/static/index.html"
  style="position:fixed;bottom:0;right:0;width:400px;height:500px;border:none;z-index:9999;"
  title="Library Chatbot">
</iframe>
```

Adjust the `src` URL and dimensions to match your deployment.

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `KOHA_API_URL` | Base URL of the Koha REST API | `http://your-koha-server:8080` |
| `GROQ_API_KEY` | Groq Cloud API key | `gsk_...` |
| `GROQ_API_URL` | Groq Cloud API base URL | `https://api.groq.com` |
| `LIBRARY_INFO_PATH` | Path to the library info JSON file | `data/library_info.json` |

All variables are required. The application will exit with an error if any are missing.

## Project Structure

```
app/
  main.py                 # FastAPI app, /api/chat endpoint, startup lifecycle
  config.py               # Environment variable loading and validation
  models.py               # Pydantic data models
  groq_client.py          # Groq Cloud LLM client wrapper
  query_classifier.py     # Intent classification (catalog search vs. library info)
  catalog_handler.py      # Catalog search via Koha REST API
  library_info_handler.py # Library hours, policies, and fines handler
  session_manager.py      # In-memory conversation session management
  static/
    index.html            # Chat widget frontend
data/
  library_info.json       # Library information (hours, policies, fines)
tests/                    # Unit and property-based tests
requirements.txt          # Python dependencies
.env.example              # Environment variable template
```
