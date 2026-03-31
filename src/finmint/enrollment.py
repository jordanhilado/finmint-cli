"""Teller enrollment via local HTTP callback server.

Spins up a temporary HTTP server on 127.0.0.1, serves an HTML page embedding
the Teller Connect JS widget, and captures the access token via a POST callback.
"""

import json
import secrets
import socket
import sqlite3
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class EnrollmentError(Exception):
    """Raised when enrollment fails or times out."""


class EnrollmentTimeoutError(EnrollmentError):
    """Raised when enrollment times out waiting for callback."""


def _find_available_port() -> int:
    """Find a random available port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_html(application_id: str, environment: str, port: int, state: str) -> str:
    """Build the HTML page that embeds the Teller Connect JS widget."""
    return f"""\
<!DOCTYPE html>
<html>
<head>
    <title>Finmint - Connect Your Bank</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: #f5f5f5;
        }}
        .container {{
            text-align: center;
            padding: 2rem;
        }}
        h1 {{ color: #333; }}
        p {{ color: #666; }}
        #status {{ margin-top: 1rem; font-weight: bold; }}
        .success {{ color: #22c55e; }}
        .error {{ color: #ef4444; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Finmint</h1>
        <p>Connecting to your bank...</p>
        <p id="status">Loading Teller Connect...</p>
    </div>
    <script src="https://cdn.teller.io/connect/connect.js"></script>
    <script>
        var tellerConnect = TellerConnect.setup({{
            applicationId: "{application_id}",
            environment: "{environment}",
            onSuccess: function(enrollment) {{
                document.getElementById("status").textContent = "Enrolling...";
                fetch("http://127.0.0.1:{port}/callback", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{
                        accessToken: enrollment.accessToken,
                        enrollment: {{
                            id: enrollment.enrollment.id,
                            institution: enrollment.enrollment.institution
                        }},
                        state: "{state}"
                    }})
                }}).then(function(resp) {{
                    if (resp.ok) {{
                        document.getElementById("status").className = "success";
                        document.getElementById("status").textContent =
                            "Account connected! You can close this tab.";
                    }} else {{
                        document.getElementById("status").className = "error";
                        document.getElementById("status").textContent =
                            "Error: enrollment rejected. Please try again.";
                    }}
                }}).catch(function(err) {{
                    document.getElementById("status").className = "error";
                    document.getElementById("status").textContent = "Error: " + err.message;
                }});
            }},
            onExit: function() {{
                document.getElementById("status").textContent =
                    "Enrollment cancelled. You can close this tab.";
            }}
        }});
        tellerConnect.open();
    </script>
</body>
</html>"""


def _store_enrollment(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    """Store the enrollment data in the accounts table.

    Returns a dict with the stored account info.
    """
    now = datetime.now(timezone.utc).isoformat()
    access_token = data["accessToken"]
    enrollment = data.get("enrollment", {})
    enrollment_id = enrollment.get("id", "")
    institution = enrollment.get("institution", {})
    institution_name = (
        institution.get("name", "Unknown")
        if isinstance(institution, dict)
        else str(institution)
    )

    # Use enrollment_id as a placeholder account id until we fetch real accounts
    account_id = enrollment_id or secrets.token_urlsafe(8)

    conn.execute(
        "INSERT OR REPLACE INTO accounts "
        "(id, enrollment_id, institution_name, access_token, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (account_id, enrollment_id, institution_name, access_token, now),
    )
    conn.commit()

    return {
        "id": account_id,
        "enrollment_id": enrollment_id,
        "institution_name": institution_name,
        "access_token": access_token,
        "created_at": now,
    }


def _make_handler(
    state: str,
    html: str,
    conn: sqlite3.Connection,
    result: dict[str, Any],
    done_event: threading.Event,
):
    """Create a request handler class with the given enrollment state."""

    class EnrollmentHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            """Serve the Teller Connect HTML page."""
            if self.path == "/" or self.path == "":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):  # noqa: N802
            """Handle the enrollment callback from Teller Connect."""
            if self.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid JSON")
                return

            # Validate state nonce (CSRF protection)
            received_state = data.get("state", "")
            if not received_state or received_state != state:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Invalid state nonce")
                return

            if "accessToken" not in data:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing accessToken")
                return

            # Store enrollment and signal completion
            try:
                account_info = _store_enrollment(conn, data)
                result.update(account_info)
            except Exception:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Failed to store enrollment")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            done_event.set()

        def log_message(self, format, *args):
            """Suppress default HTTP server logging."""
            pass

    return EnrollmentHandler


def start_enrollment(
    config: dict,
    conn: sqlite3.Connection,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Start the Teller enrollment flow.

    Opens the browser to a local page with the Teller Connect widget.
    Blocks until the user completes enrollment or the timeout is reached.

    Args:
        config: The finmint config dict (needs teller.application_id, teller.environment).
        conn: SQLite connection with initialized schema.
        timeout: Seconds to wait for enrollment callback (default 120).

    Returns:
        Dict with enrolled account info (id, enrollment_id, institution_name,
        access_token, created_at).

    Raises:
        EnrollmentTimeoutError: If no callback is received within the timeout.
    """
    teller_cfg = config["teller"]
    application_id = teller_cfg["application_id"]
    environment = teller_cfg["environment"]

    port = _find_available_port()
    state = secrets.token_urlsafe(32)

    html = _build_html(application_id, environment, port, state)

    done_event = threading.Event()
    result: dict[str, Any] = {}

    handler_class = _make_handler(state, html, conn, result, done_event)
    server = HTTPServer(("127.0.0.1", port), handler_class)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        url = f"http://127.0.0.1:{port}/"
        webbrowser.open(url)

        if not done_event.wait(timeout=timeout):
            raise EnrollmentTimeoutError(
                f"Enrollment timed out after {timeout} seconds. "
                "No callback was received from Teller Connect. "
                "Please try again with 'finmint accounts'."
            )
    finally:
        server.shutdown()
        server_thread.join(timeout=5)

    return result
