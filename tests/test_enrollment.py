"""Tests for Teller enrollment flow (local HTTP callback server)."""

import json
import threading
import urllib.request
from unittest.mock import patch

import pytest

from finmint.db import init_db
from finmint.enrollment import (
    EnrollmentTimeoutError,
    _build_html,
    _find_available_port,
    _make_handler,
    _store_enrollment,
    start_enrollment,
)
from http.server import HTTPServer


@pytest.fixture
def config():
    """Minimal config for enrollment tests."""
    return {
        "teller": {
            "application_id": "test_app_id",
            "environment": "sandbox",
            "cert_path": "/tmp/cert.pem",
            "key_path": "/tmp/key.pem",
        },
    }


@pytest.fixture
def conn():
    """In-memory DB with schema initialized (cross-thread safe for testing)."""
    import sqlite3 as _sqlite3

    c = _sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = _sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    from finmint.db import init_db_with_conn

    init_db_with_conn(c)
    return c


@pytest.fixture
def enrollment_server(config, conn):
    """Start an enrollment server on a random port and yield its details.

    Yields a dict with: server, port, state, done_event, result, url.
    """
    port = _find_available_port()
    state = "test_state_nonce_abc123"
    html = _build_html(
        config["teller"]["application_id"],
        config["teller"]["environment"],
        port,
        state,
    )
    done_event = threading.Event()
    result = {}
    handler_class = _make_handler(state, html, conn, result, done_event)
    server = HTTPServer(("127.0.0.1", port), handler_class)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    yield {
        "server": server,
        "port": port,
        "state": state,
        "done_event": done_event,
        "result": result,
        "url": f"http://127.0.0.1:{port}",
    }

    server.shutdown()
    server_thread.join(timeout=5)


class TestFindAvailablePort:
    def test_returns_valid_port(self):
        port = _find_available_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535


class TestBuildHtml:
    def test_contains_teller_connect_script(self):
        html = _build_html("app_123", "sandbox", 8080, "state_nonce")
        assert "https://cdn.teller.io/connect/connect.js" in html

    def test_contains_application_id(self):
        html = _build_html("app_123", "sandbox", 8080, "state_nonce")
        assert "app_123" in html

    def test_contains_environment(self):
        html = _build_html("app_123", "sandbox", 8080, "state_nonce")
        assert "sandbox" in html

    def test_contains_state_nonce(self):
        html = _build_html("app_123", "sandbox", 8080, "state_nonce")
        assert "state_nonce" in html

    def test_contains_callback_url(self):
        html = _build_html("app_123", "sandbox", 9999, "state_nonce")
        assert "http://127.0.0.1:9999/callback" in html


class TestGetServesHtml:
    def test_get_root_serves_html_with_teller_script(self, enrollment_server):
        """GET / serves HTML page containing Teller Connect script tag."""
        url = enrollment_server["url"] + "/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "https://cdn.teller.io/connect/connect.js" in body
            assert "TellerConnect.setup" in body

    def test_get_404_for_unknown_path(self, enrollment_server):
        """GET to unknown path returns 404."""
        url = enrollment_server["url"] + "/unknown"
        req = urllib.request.Request(url)
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 404


class TestPostCallback:
    def _post_json(self, url, data):
        """Helper to POST JSON data and return the response."""
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(req)

    def _post_json_expect_error(self, url, data):
        """Helper to POST JSON and expect an HTTP error."""
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        return exc_info.value

    def test_valid_post_accepts_token(self, enrollment_server):
        """POST with valid state nonce and accessToken is accepted."""
        url = enrollment_server["url"] + "/callback"
        data = {
            "accessToken": "test_token_abc",
            "enrollment": {
                "id": "enr_123",
                "institution": {"name": "Test Bank"},
            },
            "state": enrollment_server["state"],
        }
        resp = self._post_json(url, data)
        assert resp.status == 200

        # Check that done_event was set
        assert enrollment_server["done_event"].is_set()

        # Check that result was populated
        assert enrollment_server["result"]["access_token"] == "test_token_abc"
        assert enrollment_server["result"]["institution_name"] == "Test Bank"
        assert enrollment_server["result"]["enrollment_id"] == "enr_123"

    def test_invalid_state_nonce_rejected(self, enrollment_server):
        """POST with invalid state nonce returns 403."""
        url = enrollment_server["url"] + "/callback"
        data = {
            "accessToken": "test_token_abc",
            "enrollment": {"id": "enr_123", "institution": {"name": "Test Bank"}},
            "state": "wrong_nonce",
        }
        error = self._post_json_expect_error(url, data)
        assert error.code == 403

    def test_missing_state_nonce_rejected(self, enrollment_server):
        """POST with missing state nonce returns 403."""
        url = enrollment_server["url"] + "/callback"
        data = {
            "accessToken": "test_token_abc",
            "enrollment": {"id": "enr_123", "institution": {"name": "Test Bank"}},
        }
        error = self._post_json_expect_error(url, data)
        assert error.code == 403

    def test_missing_access_token_rejected(self, enrollment_server):
        """POST with valid state but missing accessToken returns 400."""
        url = enrollment_server["url"] + "/callback"
        data = {
            "state": enrollment_server["state"],
        }
        error = self._post_json_expect_error(url, data)
        assert error.code == 400

    def test_post_to_wrong_path_returns_404(self, enrollment_server):
        """POST to wrong path returns 404."""
        url = enrollment_server["url"] + "/wrong"
        data = {"state": enrollment_server["state"]}
        error = self._post_json_expect_error(url, data)
        assert error.code == 404


class TestStoreEnrollment:
    def test_stores_account_in_db(self, conn):
        """Enrollment data is stored in the accounts table."""
        data = {
            "accessToken": "tok_abc",
            "enrollment": {
                "id": "enr_456",
                "institution": {"name": "My Bank"},
            },
        }
        result = _store_enrollment(conn, data)
        assert result["access_token"] == "tok_abc"
        assert result["enrollment_id"] == "enr_456"
        assert result["institution_name"] == "My Bank"

        # Verify in DB
        row = conn.execute(
            "SELECT * FROM accounts WHERE enrollment_id = ?", ("enr_456",)
        ).fetchone()
        assert row is not None
        assert row["access_token"] == "tok_abc"
        assert row["institution_name"] == "My Bank"


class TestServerBinding:
    def test_server_bound_to_localhost_only(self, enrollment_server):
        """Server is bound to 127.0.0.1, not 0.0.0.0."""
        server = enrollment_server["server"]
        host, _port = server.server_address
        assert host == "127.0.0.1"


class TestStartEnrollment:
    @patch("finmint.enrollment.webbrowser.open")
    def test_enrollment_timeout_raises_error(self, mock_open, config, conn):
        """Enrollment timeout raises EnrollmentTimeoutError."""
        with pytest.raises(EnrollmentTimeoutError, match="timed out"):
            start_enrollment(config, conn, timeout=0.5)

        # webbrowser.open should have been called
        mock_open.assert_called_once()

    @patch("finmint.enrollment.webbrowser.open")
    def test_enrollment_happy_path(self, mock_open, config, conn):
        """Full enrollment flow: server starts, accepts POST, returns result."""

        def simulate_enrollment(url):
            """Simulate the browser posting back enrollment data."""
            import time
            import urllib.request

            # Give the server a moment to be ready
            time.sleep(0.1)

            # Extract port from URL
            port = int(url.split(":")[2].rstrip("/"))

            # First, verify GET / works
            req = urllib.request.Request(f"http://127.0.0.1:{port}/")
            with urllib.request.urlopen(req) as resp:
                html = resp.read().decode("utf-8")
                # Extract state from the HTML
                import re
                match = re.search(r'state:\s*"([^"]+)"', html)
                assert match is not None, f"Could not find state nonce in HTML"
                state = match.group(1)

            # POST the callback
            callback_data = {
                "accessToken": "test_access_token_xyz",
                "enrollment": {
                    "id": "enr_happy",
                    "institution": {"name": "Happy Bank"},
                },
                "state": state,
            }
            body = json.dumps(callback_data).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/callback",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req)

        mock_open.side_effect = lambda url: threading.Thread(
            target=simulate_enrollment, args=(url,), daemon=True
        ).start()

        result = start_enrollment(config, conn, timeout=10.0)

        assert result["access_token"] == "test_access_token_xyz"
        assert result["institution_name"] == "Happy Bank"
        assert result["enrollment_id"] == "enr_happy"

        # Verify it was stored in the DB
        row = conn.execute(
            "SELECT * FROM accounts WHERE enrollment_id = ?", ("enr_happy",)
        ).fetchone()
        assert row is not None
        assert row["access_token"] == "test_access_token_xyz"

    @patch("finmint.enrollment.webbrowser.open")
    def test_enrollment_opens_browser(self, mock_open, config, conn):
        """start_enrollment calls webbrowser.open with the local URL."""
        mock_open.return_value = None

        with pytest.raises(EnrollmentTimeoutError):
            start_enrollment(config, conn, timeout=0.5)

        mock_open.assert_called_once()
        url = mock_open.call_args[0][0]
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/")

    @patch("finmint.enrollment.webbrowser.open")
    def test_enrollment_starts_on_random_port(self, mock_open, config, conn):
        """Server starts on a random port (not hardcoded)."""
        mock_open.return_value = None

        with pytest.raises(EnrollmentTimeoutError):
            start_enrollment(config, conn, timeout=0.5)

        url = mock_open.call_args[0][0]
        port = int(url.split(":")[2].rstrip("/"))
        assert 1024 <= port <= 65535
