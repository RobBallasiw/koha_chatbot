"""Unit tests for the admin dashboard route.

Validates Requirement 7.1: THE Admin_Dashboard SHALL be served as a static
HTML page by the Backend at a dedicated admin route.
"""

from starlette.testclient import TestClient

from app.main import app


def test_get_admin_returns_html():
    """GET /admin/ returns 200 with text/html content containing the dashboard."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/admin/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Admin Dashboard" in resp.text
