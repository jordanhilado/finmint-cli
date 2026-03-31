"""Teller API client — fetch accounts, transactions, and manage accounts via mTLS."""

from contextlib import contextmanager

import httpx


BASE_URL = "https://api.teller.io"
DEFAULT_PAGE_SIZE = 100


class TellerAuthError(Exception):
    """Raised when Teller returns a 401 (unauthorized)."""


class TellerAccountClosedError(Exception):
    """Raised when Teller returns a 410 (account closed/gone)."""


@contextmanager
def create_client(config: dict, access_token: str):
    """Create an httpx.Client configured for Teller mTLS and Basic Auth.

    Args:
        config: The full finmint config dict (needs teller.cert_path, teller.key_path).
        access_token: Teller access token used as the Basic Auth username.

    Yields:
        httpx.Client configured with mTLS cert and Basic Auth.
    """
    teller_cfg = config["teller"]
    cert_path = teller_cfg["cert_path"]
    key_path = teller_cfg["key_path"]

    with httpx.Client(
        base_url=BASE_URL,
        cert=(cert_path, key_path),
        auth=(access_token, ""),
    ) as client:
        yield client


def _raise_for_status(response: httpx.Response) -> None:
    """Check response status and raise domain-specific errors."""
    if response.status_code == 401:
        raise TellerAuthError(
            "Teller API returned 401 Unauthorized. "
            "Check that your access token is valid and not expired."
        )
    if response.status_code == 410:
        raise TellerAccountClosedError(
            "Teller API returned 410 Gone. "
            "The account may have been closed or disconnected."
        )
    response.raise_for_status()


def fetch_accounts(client: httpx.Client) -> list[dict]:
    """Fetch all accounts from Teller.

    Args:
        client: An httpx.Client from create_client.

    Returns:
        List of account dicts as returned by the Teller API.
    """
    response = client.get("/accounts")
    _raise_for_status(response)
    return response.json()


def _amount_to_cents(amount_str: str) -> int:
    """Convert a string dollar amount to integer cents.

    Examples:
        "-67.42" -> -6742
        "100.00" -> 10000
        "5.1"    -> 510
    """
    return round(float(amount_str) * 100)


def fetch_transactions(
    client: httpx.Client,
    account_id: str,
    start_date: str,
    end_date: str,
    count: int = DEFAULT_PAGE_SIZE,
) -> list[dict]:
    """Fetch all transactions for an account within a date range, paginating automatically.

    Args:
        client: An httpx.Client from create_client.
        account_id: Teller account ID.
        start_date: Start date (inclusive) in YYYY-MM-DD format.
        end_date: End date (inclusive) in YYYY-MM-DD format.
        count: Number of transactions per page (default 100).

    Returns:
        List of transaction dicts with amounts converted to integer cents.
    """
    all_transactions: list[dict] = []
    from_id: str | None = None

    while True:
        params: dict = {"count": count}
        if from_id is not None:
            params["from_id"] = from_id

        response = client.get(
            f"/accounts/{account_id}/transactions",
            params=params,
        )
        _raise_for_status(response)
        page = response.json()

        if not page:
            break

        for txn in page:
            txn["amount"] = _amount_to_cents(txn["amount"])

        all_transactions.extend(page)

        # If we got fewer than `count` items, we've reached the last page
        if len(page) < count:
            break

        # Use the last transaction's ID as the cursor for the next page
        from_id = page[-1]["id"]

    return all_transactions


def delete_account(client: httpx.Client, account_id: str) -> None:
    """Delete (disconnect) an account from Teller.

    Args:
        client: An httpx.Client from create_client.
        account_id: Teller account ID to delete.

    Raises:
        TellerAuthError: If the API returns 401.
        httpx.HTTPStatusError: For other non-success status codes.
    """
    response = client.delete(f"/accounts/{account_id}")
    _raise_for_status(response)
    # 204 No Content is the expected success response — nothing to return
