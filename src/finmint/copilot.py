"""Copilot Money GraphQL client -- fetch/mutate accounts, transactions, and categories.

Mutation signatures reverse-engineered from Copilot Money's web app and the
JaviSoto/copilot-money-cli reference project. The API is unofficial and
undocumented; field names may change without notice.
"""

from contextlib import contextmanager

import httpx


BASE_URL = "https://app.copilot.money/api/graphql"
DEFAULT_PAGE_SIZE = 100

ACCOUNTS_QUERY = """
query Accounts {
  accounts { id name type subType mask isUserHidden institutionId }
}
"""

INSTITUTION_QUERY = """
query Institution($id: ID!) {
  institution(id: $id) { id name }
}
"""

TRANSACTIONS_QUERY = """
query Transactions($first: Int, $after: String) {
  transactions(first: $first, after: $after) {
    edges { node { id itemId name amount date type accountId categoryId isReviewed userNotes } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

CATEGORIES_QUERY = """
query Categories {
  categories {
    id name colorName
    icon { ... on EmojiUnicode { unicode __typename } __typename }
    childCategories {
      id name colorName
      icon { ... on EmojiUnicode { unicode __typename } __typename }
      __typename
    }
    __typename
  }
}
"""

EDIT_TRANSACTION_MUTATION = """
mutation EditTransaction($itemId: ID!, $accountId: ID!, $id: ID!, $input: EditTransactionInput) {
  editTransaction(itemId: $itemId, accountId: $accountId, id: $id, input: $input) {
    transaction { id categoryId isReviewed userNotes __typename }
    __typename
  }
}
"""

BULK_EDIT_TRANSACTIONS_MUTATION = """
mutation BulkEditTransactions($input: BulkEditTransactionInput!, $filter: TransactionFilter) {
  bulkEditTransactions(filter: $filter, input: $input) {
    updated { id isReviewed __typename }
    failed { error errorCode __typename }
    __typename
  }
}
"""


class CopilotAuthError(Exception):
    """Raised when the Copilot API returns an UNAUTHENTICATED GraphQL error."""


class CopilotAPIError(Exception):
    """Raised when the Copilot API returns a non-auth GraphQL error."""


def _raise_for_graphql_errors(data: dict) -> None:
    """Inspect a GraphQL response body and raise on errors.

    Copilot returns errors in the response body with HTTP 200, so we must
    check the ``errors`` array rather than the status code.
    """
    errors = data.get("errors")
    if not errors:
        return

    first_error = errors[0]
    code = first_error.get("extensions", {}).get("code", "")
    message = first_error.get("message", str(first_error))

    if code == "UNAUTHENTICATED":
        raise CopilotAuthError(
            "Copilot API returned UNAUTHENTICATED. "
            "Check that your JWT is valid and not expired."
        )

    raise CopilotAPIError(f"Copilot API error: {message}")


@contextmanager
def create_client(token: str):
    """Create an httpx.Client configured for the Copilot Money GraphQL API.

    Args:
        token: JWT bearer token for Copilot Money.

    Yields:
        httpx.Client configured with base_url and Authorization header.
    """
    with httpx.Client(
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


def _amount_to_cents(amount: float) -> int:
    """Convert a float dollar amount to integer cents.

    Examples:
        -30.0   -> -3000
        1840.17 -> 184017
        -0.01   -> -1
    """
    return round(amount * 100)


def _fetch_institution_name(client: httpx.Client, institution_id: str) -> str:
    """Fetch a single institution's name by ID.

    Returns the institution name, or the raw ID as fallback if the query
    returns no data.
    """
    response = client.post(
        BASE_URL,
        json={
            "query": INSTITUTION_QUERY,
            "variables": {"id": institution_id},
        },
    )
    response.raise_for_status()
    data = response.json()
    _raise_for_graphql_errors(data)

    institution = data.get("data", {}).get("institution")
    if institution:
        return institution["name"]
    return institution_id


def fetch_accounts(client: httpx.Client) -> list[dict]:
    """Fetch all accounts from Copilot Money, resolving institution names.

    Args:
        client: An httpx.Client from create_client.

    Returns:
        List of account dicts with keys: id, name, type, sub_type, mask,
        institution_name.
    """
    response = client.post(BASE_URL, json={"query": ACCOUNTS_QUERY})
    response.raise_for_status()
    data = response.json()
    _raise_for_graphql_errors(data)

    raw_accounts = data.get("data", {}).get("accounts", [])

    # Build a cache of institution names to avoid duplicate queries.
    institution_cache: dict[str, str] = {}

    results: list[dict] = []
    for acct in raw_accounts:
        inst_id = acct.get("institutionId")
        if inst_id and inst_id not in institution_cache:
            institution_cache[inst_id] = _fetch_institution_name(client, inst_id)

        results.append({
            "id": acct["id"],
            "name": acct["name"],
            "type": acct["type"],
            "sub_type": acct.get("subType"),
            "mask": acct.get("mask"),
            "institution_name": institution_cache.get(inst_id, ""),
        })

    return results


def fetch_transactions(
    client: httpx.Client,
    start_date: str,
    end_date: str,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict]:
    """Fetch transactions from Copilot Money within a date range.

    Copilot's GraphQL API does not support server-side date filtering, so
    this function paginates through ALL transactions and filters client-side.

    Args:
        client: An httpx.Client from create_client.
        start_date: Start date (inclusive) in YYYY-MM-DD format.
        end_date: End date (inclusive) in YYYY-MM-DD format.
        page_size: Number of transactions per page (default 100).

    Returns:
        List of transaction dicts with keys: id, account_id, amount (int
        cents), date, description, source_type.  Amounts are converted to
        integer cents (positive = debit, negative = credit).
    """
    all_transactions: list[dict] = []
    after: str | None = None

    while True:
        variables: dict = {"first": page_size}
        if after is not None:
            variables["after"] = after

        response = client.post(
            BASE_URL,
            json={"query": TRANSACTIONS_QUERY, "variables": variables},
        )
        response.raise_for_status()
        data = response.json()
        _raise_for_graphql_errors(data)

        txn_data = data.get("data", {}).get("transactions", {})
        edges = txn_data.get("edges", [])
        page_info = txn_data.get("pageInfo", {})

        for edge in edges:
            node = edge["node"]
            txn_date = node["date"]

            # Client-side date filtering (inclusive on both ends).
            if txn_date < start_date or txn_date > end_date:
                continue

            all_transactions.append({
                "id": node["id"],
                "account_id": node["accountId"],
                "item_id": node.get("itemId"),
                "amount": _amount_to_cents(node["amount"]),
                "date": txn_date,
                "description": node["name"],
                "source_type": node["type"],
                "category_id": node.get("categoryId"),
                "is_reviewed": node.get("isReviewed", False),
                "user_notes": node.get("userNotes"),
            })

        if not page_info.get("hasNextPage", False):
            break

        after = page_info.get("endCursor")

    return all_transactions


def fetch_categories(client: httpx.Client) -> list[dict]:
    """Fetch all categories from Copilot Money.

    Returns a flat list of category dicts (parent and child) with keys:
    id, name, color, icon.
    """
    response = client.post(BASE_URL, json={"query": CATEGORIES_QUERY})
    response.raise_for_status()
    data = response.json()
    _raise_for_graphql_errors(data)

    raw_categories = data.get("data", {}).get("categories", [])
    results: list[dict] = []

    for cat in raw_categories:
        results.append(_parse_category(cat))
        for child in cat.get("childCategories", []):
            results.append(_parse_category(child))

    return results


def _parse_category(cat: dict) -> dict:
    """Extract id, name, color, icon from a Copilot Money category node."""
    icon_data = cat.get("icon")
    icon = None
    if icon_data and icon_data.get("__typename") == "EmojiUnicode":
        icon = icon_data.get("unicode")

    return {
        "id": cat["id"],
        "name": cat["name"],
        "color": cat.get("colorName"),
        "icon": icon,
    }


def set_transaction_category(
    client: httpx.Client,
    txn_id: str,
    account_id: str,
    item_id: str,
    category_id: str,
) -> None:
    """Set a transaction's category in Copilot Money."""
    response = client.post(
        BASE_URL,
        json={
            "operationName": "EditTransaction",
            "query": EDIT_TRANSACTION_MUTATION,
            "variables": {
                "id": txn_id,
                "accountId": account_id,
                "itemId": item_id,
                "input": {"categoryId": category_id},
            },
        },
    )
    response.raise_for_status()
    _raise_for_graphql_errors(response.json())


def set_transaction_note(
    client: httpx.Client,
    txn_id: str,
    account_id: str,
    item_id: str,
    note: str | None,
) -> None:
    """Set or clear a transaction's note in Copilot Money."""
    response = client.post(
        BASE_URL,
        json={
            "operationName": "EditTransaction",
            "query": EDIT_TRANSACTION_MUTATION,
            "variables": {
                "id": txn_id,
                "accountId": account_id,
                "itemId": item_id,
                "input": {"userNotes": note or ""},
            },
        },
    )
    response.raise_for_status()
    _raise_for_graphql_errors(response.json())


def set_transaction_reviewed(
    client: httpx.Client,
    txn_id: str,
    account_id: str,
    item_id: str,
    reviewed: bool = True,
) -> None:
    """Mark a transaction as reviewed or unreviewed in Copilot Money."""
    response = client.post(
        BASE_URL,
        json={
            "operationName": "BulkEditTransactions",
            "query": BULK_EDIT_TRANSACTIONS_MUTATION,
            "variables": {
                "filter": {
                    "ids": [
                        {"accountId": account_id, "id": txn_id, "itemId": item_id},
                    ],
                },
                "input": {"isReviewed": reviewed},
            },
        },
    )
    response.raise_for_status()
    data = response.json()
    _raise_for_graphql_errors(data)

    failed = data.get("data", {}).get("bulkEditTransactions", {}).get("failed", [])
    if failed:
        raise CopilotAPIError(
            f"Failed to update review status: {failed[0].get('error', 'unknown')}"
        )
