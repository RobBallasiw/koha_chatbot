"""Vercel serverless entry point — exposes the FastAPI app as a handler."""

import sys
import os

# Add the project root to the Python path so `app.*` imports work.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402

# Vercel's Python runtime looks for an `app` variable (ASGI) in this module.
# The variable is already named `app` from the import above.
