"""Tests for finmint.teller — Teller API client with mocked httpx responses."""

import httpx
import pytest
import respx

from finmint.teller import (
    TellerAccountClosedError,
    TellerAuthError,
    create_client,
    delete_account,
    fetch_accounts,
    fetch_transactions,
)


BASE_URL = "https://api.teller.io"

SAMPLE_CONFIG = {
    "teller": {
        "cert_path": "/tmp/test-cert.pem",
        "key_path": "/tmp/test-key.pem",
        "environment": "sandbox",
        "application_id": "test_app_id",
    },
}


@pytest.fixture
def mock_client():
    """Create an httpx.Client pointing at the Teller base URL without real mTLS."""
    client = httpx.Client(base_url=BASE_URL, auth=("test_token", ""))
    yield client
    client.close()


# --- fetch_accounts ---


@respx.mock
def test_fetch_accounts_happy_path(mock_client):
    """fetch_accounts returns parsed account list from mock response."""
    accounts_data = [
        {
            "id": "acc_123",
            "enrollment_id": "enr_456",
            "name": "My Checking",
            "type": "depository",
            "subtype": "checking",
            "currency": "USD",
            "last_four": "1234",
            "status": "open",
            "institution": {"id": "ins_abc", "name": "Test Bank"},
        },
        {
            "id": "acc_789",
            "enrollment_id": "enr_456",
            "name": "My Savings",
            "type": "depository",
            "subtype": "savings",
            "currency": "USD",
            "last_four": "5678",
            "status": "open",
            "institution": {"id": "ins_abc", "name": "Test Bank"},
        },
    ]
    respx.get(f"{BASE_URL}/accounts").mock(
        return_value=httpx.Response(200, json=accounts_data)
    )

    result = fetch_accounts(mock_client)

    assert len(result) == 2
    assert result[0]["id"] == "acc_123"
    assert result[1]["name"] == "My Savings"
    assert result[0]["institution"]["name"] == "Test Bank"


# --- fetch_transactions ---


def _make_txn(txn_id: str, amount: str, date: str = "2026-03-15") -> dict:
    """Helper to build a Teller-style transaction dict."""
    return {
        "id": txn_id,
        "account_id": "acc_123",
        "amount": amount,
        "date": date,
        "description": "Some Merchant",
        "status": "posted",
        "type": "card_payment",
        "details": {
            "category": "food",
            "counterparty": {"name": "Some Merchant"},
        },
    }


@respx.mock
def test_fetch_transactions_pagination(mock_client):
    """fetch_transactions paginates across 2 pages correctly."""
    page1 = [_make_txn(f"txn_{i}", "-10.00") for i in range(3)]
    page2 = [_make_txn("txn_last", "-5.50")]

    route = respx.get(f"{BASE_URL}/accounts/acc_123/transactions")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ]

    result = fetch_transactions(
        mock_client, "acc_123", "2026-03-01", "2026-03-31", count=3
    )

    assert len(result) == 4
    # Verify pagination made 2 requests
    assert route.call_count == 2


@respx.mock
def test_fetch_transactions_converts_amounts_to_cents(mock_client):
    """fetch_transactions converts string amounts to integer cents."""
    txns = [
        _make_txn("txn_1", "-67.42"),
        _make_txn("txn_2", "100.00"),
        _make_txn("txn_3", "5.10"),
        _make_txn("txn_4", "-0.01"),
    ]
    respx.get(f"{BASE_URL}/accounts/acc_123/transactions").mock(
        return_value=httpx.Response(200, json=txns)
    )

    result = fetch_transactions(
        mock_client, "acc_123", "2026-03-01", "2026-03-31"
    )

    assert result[0]["amount"] == -6742
    assert result[1]["amount"] == 10000
    assert result[2]["amount"] == 510
    assert result[3]["amount"] == -1


@respx.mock
def test_fetch_transactions_empty(mock_client):
    """fetch_transactions with no results returns empty list."""
    respx.get(f"{BASE_URL}/accounts/acc_123/transactions").mock(
        return_value=httpx.Response(200, json=[])
    )

    result = fetch_transactions(
        mock_client, "acc_123", "2026-03-01", "2026-03-31"
    )

    assert result == []


# --- Error paths ---


@respx.mock
def test_fetch_accounts_401_raises_auth_error(mock_client):
    """401 response raises TellerAuthError."""
    respx.get(f"{BASE_URL}/accounts").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(TellerAuthError, match="401 Unauthorized"):
        fetch_accounts(mock_client)


@respx.mock
def test_fetch_transactions_401_raises_auth_error(mock_client):
    """401 on transactions endpoint raises TellerAuthError."""
    respx.get(f"{BASE_URL}/accounts/acc_123/transactions").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(TellerAuthError):
        fetch_transactions(mock_client, "acc_123", "2026-03-01", "2026-03-31")


@respx.mock
def test_fetch_transactions_410_raises_account_closed(mock_client):
    """410 response raises TellerAccountClosedError."""
    respx.get(f"{BASE_URL}/accounts/acc_123/transactions").mock(
        return_value=httpx.Response(410, json={"error": "gone"})
    )

    with pytest.raises(TellerAccountClosedError, match="410 Gone"):
        fetch_transactions(mock_client, "acc_123", "2026-03-01", "2026-03-31")


# --- delete_account ---


@respx.mock
def test_delete_account_204(mock_client):
    """delete_account sends DELETE and handles 204 response."""
    route = respx.delete(f"{BASE_URL}/accounts/acc_123").mock(
        return_value=httpx.Response(204)
    )

    delete_account(mock_client, "acc_123")

    assert route.called
    assert route.call_count == 1


@respx.mock
def test_delete_account_401_raises_auth_error(mock_client):
    """delete_account raises TellerAuthError on 401."""
    respx.delete(f"{BASE_URL}/accounts/acc_123").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(TellerAuthError):
        delete_account(mock_client, "acc_123")


# --- create_client ---


def test_create_client_is_context_manager():
    """create_client yields an httpx.Client via context manager."""
    # We can't actually use mTLS certs in tests, but we can verify
    # the context manager protocol works with a patched Client.
    # The real integration test would need actual cert files.
    # Here we just verify the function signature and that it's a generator.
    import inspect

    assert inspect.isgeneratorfunction(create_client.__wrapped__  # contextmanager wraps it
                                        if hasattr(create_client, "__wrapped__")
                                        else create_client)
