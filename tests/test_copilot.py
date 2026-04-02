"""Tests for finmint.copilot -- Copilot Money GraphQL client with mocked httpx responses."""

import httpx
import pytest
import respx

from finmint.copilot import (
    CopilotAPIError,
    CopilotAuthError,
    _amount_to_cents,
    create_client,
    fetch_accounts,
    fetch_categories,
    fetch_transactions,
    set_transaction_category,
    set_transaction_note,
    set_transaction_reviewed,
)


BASE_URL = "https://app.copilot.money/api/graphql"


@pytest.fixture
def mock_client():
    """Create an httpx.Client pointing at the Copilot base URL without real auth."""
    client = httpx.Client(
        headers={"Authorization": "Bearer test_jwt_token"},
    )
    yield client
    client.close()


def _graphql_accounts_response(accounts: list[dict]) -> dict:
    """Build a Copilot-style GraphQL accounts response body."""
    return {"data": {"accounts": accounts}}


def _graphql_institution_response(inst_id: str, name: str) -> dict:
    """Build a Copilot-style GraphQL institution response body."""
    return {"data": {"institution": {"id": inst_id, "name": name}}}


def _graphql_transactions_response(
    nodes: list[dict],
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> dict:
    """Build a Copilot-style GraphQL transactions response body."""
    edges = [{"node": n} for n in nodes]
    return {
        "data": {
            "transactions": {
                "edges": edges,
                "pageInfo": {
                    "hasNextPage": has_next_page,
                    "endCursor": end_cursor,
                },
            }
        }
    }


def _make_raw_account(
    acct_id: str = "acc_1",
    name: str = "Chase College",
    acct_type: str = "DEPOSITORY",
    sub_type: str = "checking",
    mask: str = "0709",
    institution_id: str = "ins_56",
) -> dict:
    """Build a raw Copilot account dict as returned by the GraphQL API."""
    return {
        "id": acct_id,
        "name": name,
        "type": acct_type,
        "subType": sub_type,
        "mask": mask,
        "isUserHidden": False,
        "institutionId": institution_id,
    }


def _make_raw_txn(
    txn_id: str = "txn_1",
    name: str = "Spotify",
    amount: float = -30.0,
    date: str = "2026-03-15",
    txn_type: str = "REGULAR",
    account_id: str = "acc_1",
    item_id: str = "item_1",
    category_id: str | None = None,
    is_reviewed: bool = False,
    user_notes: str | None = None,
) -> dict:
    """Build a raw Copilot transaction node as returned by the GraphQL API."""
    return {
        "id": txn_id,
        "name": name,
        "amount": amount,
        "date": date,
        "type": txn_type,
        "accountId": account_id,
        "itemId": item_id,
        "categoryId": category_id,
        "isReviewed": is_reviewed,
        "userNotes": user_notes,
    }


# ---------------------------------------------------------------------------
# fetch_accounts
# ---------------------------------------------------------------------------


class TestFetchAccounts:
    """Tests for the fetch_accounts function."""

    @respx.mock
    def test_happy_path_returns_parsed_accounts_with_institution_names(
        self, mock_client
    ):
        """fetch_accounts returns parsed account list with institution names resolved."""
        accounts = [
            _make_raw_account("acc_1", "Chase College", institution_id="ins_56"),
            _make_raw_account("acc_2", "Savings", institution_id="ins_56"),
        ]

        # First POST: accounts query.
        # Subsequent POSTs: institution query (only one because both share ins_56).
        route = respx.post(BASE_URL)
        route.side_effect = [
            httpx.Response(200, json=_graphql_accounts_response(accounts)),
            httpx.Response(
                200, json=_graphql_institution_response("ins_56", "Chase")
            ),
        ]

        result = fetch_accounts(mock_client)

        assert len(result) == 2
        assert result[0]["id"] == "acc_1"
        assert result[0]["name"] == "Chase College"
        assert result[0]["type"] == "DEPOSITORY"
        assert result[0]["sub_type"] == "checking"
        assert result[0]["mask"] == "0709"
        assert result[0]["institution_name"] == "Chase"
        # Second account shares the same institution -- cache should be used.
        assert result[1]["institution_name"] == "Chase"
        # Only 2 requests: accounts + 1 institution lookup (cached).
        assert route.call_count == 2

    @respx.mock
    def test_empty_accounts_returns_empty_list(self, mock_client):
        """fetch_accounts with no accounts returns empty list."""
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200, json=_graphql_accounts_response([])
            )
        )

        result = fetch_accounts(mock_client)

        assert result == []


# ---------------------------------------------------------------------------
# fetch_transactions
# ---------------------------------------------------------------------------


class TestFetchTransactions:
    """Tests for the fetch_transactions function."""

    @respx.mock
    def test_happy_path_returns_transactions_with_cents_and_date_filter(
        self, mock_client
    ):
        """fetch_transactions returns transactions with amounts in cents, date-filtered."""
        nodes = [
            _make_raw_txn("txn_1", "Spotify", -30.0, "2026-03-15", category_id="cat-1", is_reviewed=True, user_notes="monthly"),
            _make_raw_txn("txn_2", "Paycheck", 1840.17, "2026-03-01", "INCOME"),
        ]

        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200,
                json=_graphql_transactions_response(nodes, has_next_page=False),
            )
        )

        result = fetch_transactions(mock_client, "2026-03-01", "2026-03-31")

        assert len(result) == 2
        assert result[0]["id"] == "txn_1"
        assert result[0]["account_id"] == "acc_1"
        assert result[0]["item_id"] == "item_1"
        assert result[0]["amount"] == -3000
        assert result[0]["date"] == "2026-03-15"
        assert result[0]["description"] == "Spotify"
        assert result[0]["source_type"] == "REGULAR"
        assert result[0]["category_id"] == "cat-1"
        assert result[0]["is_reviewed"] is True
        assert result[0]["user_notes"] == "monthly"
        assert result[1]["amount"] == 184017
        assert result[1]["source_type"] == "INCOME"
        assert result[1]["is_reviewed"] is False

    @respx.mock
    def test_single_page_response_returns_correctly(self, mock_client):
        """Single-page response (hasNextPage=false) returns all transactions."""
        nodes = [_make_raw_txn("txn_1", date="2026-03-10")]

        route = respx.post(BASE_URL)
        route.mock(
            return_value=httpx.Response(
                200,
                json=_graphql_transactions_response(nodes, has_next_page=False),
            )
        )

        result = fetch_transactions(mock_client, "2026-03-01", "2026-03-31")

        assert len(result) == 1
        assert result[0]["id"] == "txn_1"
        # Should have made exactly one request.
        assert route.call_count == 1

    @respx.mock
    def test_empty_transactions_returns_empty_list(self, mock_client):
        """fetch_transactions with no results returns empty list."""
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200,
                json=_graphql_transactions_response([], has_next_page=False),
            )
        )

        result = fetch_transactions(mock_client, "2026-03-01", "2026-03-31")

        assert result == []

    @respx.mock
    def test_pagination_stops_when_has_next_page_is_false(self, mock_client):
        """Pagination stops when hasNextPage is false."""
        page1_nodes = [_make_raw_txn("txn_1", date="2026-03-10")]
        page2_nodes = [_make_raw_txn("txn_2", date="2026-03-12")]

        route = respx.post(BASE_URL)
        route.side_effect = [
            httpx.Response(
                200,
                json=_graphql_transactions_response(
                    page1_nodes, has_next_page=True, end_cursor="cursor_1"
                ),
            ),
            httpx.Response(
                200,
                json=_graphql_transactions_response(
                    page2_nodes, has_next_page=False
                ),
            ),
        ]

        result = fetch_transactions(
            mock_client, "2026-03-01", "2026-03-31", page_size=1
        )

        assert len(result) == 2
        assert result[0]["id"] == "txn_1"
        assert result[1]["id"] == "txn_2"
        # Exactly 2 requests: page 1 + page 2.
        assert route.call_count == 2

    @respx.mock
    def test_transactions_outside_date_range_are_filtered_out(self, mock_client):
        """Transactions outside the requested date range are excluded."""
        nodes = [
            _make_raw_txn("txn_in_range", date="2026-03-15"),
            _make_raw_txn("txn_before", date="2026-02-28"),
            _make_raw_txn("txn_after", date="2026-04-01"),
            _make_raw_txn("txn_on_start", date="2026-03-01"),
            _make_raw_txn("txn_on_end", date="2026-03-31"),
        ]

        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200,
                json=_graphql_transactions_response(nodes, has_next_page=False),
            )
        )

        result = fetch_transactions(mock_client, "2026-03-01", "2026-03-31")

        ids = [t["id"] for t in result]
        assert "txn_in_range" in ids
        assert "txn_on_start" in ids
        assert "txn_on_end" in ids
        assert "txn_before" not in ids
        assert "txn_after" not in ids
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestGraphQLErrors:
    """Tests for GraphQL error handling."""

    @respx.mock
    def test_unauthenticated_error_raises_copilot_auth_error(self, mock_client):
        """UNAUTHENTICATED GraphQL error raises CopilotAuthError."""
        error_body = {
            "errors": [
                {
                    "message": "Not authenticated",
                    "extensions": {"code": "UNAUTHENTICATED"},
                }
            ]
        }
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json=error_body)
        )

        with pytest.raises(CopilotAuthError, match="UNAUTHENTICATED"):
            fetch_accounts(mock_client)

    @respx.mock
    def test_other_graphql_error_raises_copilot_api_error(self, mock_client):
        """Non-auth GraphQL error raises CopilotAPIError."""
        error_body = {
            "errors": [
                {
                    "message": "Something went wrong",
                    "extensions": {"code": "INTERNAL_SERVER_ERROR"},
                }
            ]
        }
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json=error_body)
        )

        with pytest.raises(CopilotAPIError, match="Something went wrong"):
            fetch_transactions(mock_client, "2026-03-01", "2026-03-31")


# ---------------------------------------------------------------------------
# _amount_to_cents
# ---------------------------------------------------------------------------


class TestAmountToCents:
    """Tests for the _amount_to_cents helper."""

    def test_negative_whole_number(self):
        """Negative float with no fractional cents converts correctly."""
        assert _amount_to_cents(-30.0) == -3000

    def test_positive_with_cents(self):
        """Positive float with fractional cents converts correctly."""
        assert _amount_to_cents(1840.17) == 184017

    def test_small_negative(self):
        """Small negative amount converts correctly."""
        assert _amount_to_cents(-0.01) == -1

    def test_zero(self):
        """Zero converts to zero cents."""
        assert _amount_to_cents(0.0) == 0

    def test_positive_whole_number(self):
        """Positive whole dollar amount converts correctly."""
        assert _amount_to_cents(100.0) == 10000

    def test_floating_point_edge_case(self):
        """Handles floating-point imprecision (e.g., 19.99)."""
        assert _amount_to_cents(19.99) == 1999


# ---------------------------------------------------------------------------
# create_client
# ---------------------------------------------------------------------------


class TestCreateClient:
    """Tests for the create_client context manager."""

    def test_create_client_is_context_manager(self):
        """create_client yields an httpx.Client via context manager."""
        import inspect

        assert inspect.isgeneratorfunction(
            create_client.__wrapped__
            if hasattr(create_client, "__wrapped__")
            else create_client
        )

    def test_create_client_sets_auth_header(self):
        """create_client configures Bearer auth header on the yielded client."""
        with create_client("my_jwt_token") as client:
            assert client.headers["authorization"] == "Bearer my_jwt_token"


# ---------------------------------------------------------------------------
# fetch_categories
# ---------------------------------------------------------------------------


def _graphql_categories_response(categories: list[dict]) -> dict:
    """Build a Copilot-style GraphQL categories response body."""
    return {"data": {"categories": categories}}


def _make_raw_category(
    cat_id: str = "cat_1",
    name: str = "Groceries",
    color_name: str = "green",
    icon_unicode: str | None = "🛒",
    children: list | None = None,
) -> dict:
    """Build a raw Copilot category node."""
    icon = None
    if icon_unicode:
        icon = {"unicode": icon_unicode, "__typename": "EmojiUnicode"}
    return {
        "id": cat_id,
        "name": name,
        "colorName": color_name,
        "icon": icon,
        "childCategories": children or [],
        "__typename": "Category",
    }


class TestFetchCategories:
    """Tests for the fetch_categories function."""

    @respx.mock
    def test_happy_path_returns_parsed_categories(self, mock_client):
        """fetch_categories returns a flat list of categories."""
        categories = [
            _make_raw_category("cat_1", "Groceries", "green", "🛒"),
            _make_raw_category("cat_2", "Transport", "blue", "🚗"),
        ]
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200, json=_graphql_categories_response(categories)
            )
        )

        result = fetch_categories(mock_client)

        assert len(result) == 2
        assert result[0]["id"] == "cat_1"
        assert result[0]["name"] == "Groceries"
        assert result[0]["color"] == "green"
        assert result[0]["icon"] == "🛒"

    @respx.mock
    def test_flattens_child_categories(self, mock_client):
        """fetch_categories flattens parent and child categories."""
        child = _make_raw_category("cat_child", "Fast Food", "red", "🍔")
        parent = _make_raw_category("cat_parent", "Dining", "red", "🍽️", children=[child])
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200, json=_graphql_categories_response([parent])
            )
        )

        result = fetch_categories(mock_client)

        assert len(result) == 2
        assert result[0]["id"] == "cat_parent"
        assert result[1]["id"] == "cat_child"

    @respx.mock
    def test_empty_categories(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200, json=_graphql_categories_response([])
            )
        )

        result = fetch_categories(mock_client)

        assert result == []

    @respx.mock
    def test_category_without_icon(self, mock_client):
        cat = _make_raw_category("cat_no_icon", "Other", "gray", None)
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(
                200, json=_graphql_categories_response([cat])
            )
        )

        result = fetch_categories(mock_client)

        assert result[0]["icon"] is None

    @respx.mock
    def test_auth_error_raises(self, mock_client):
        error_body = {
            "errors": [{"message": "Not authenticated", "extensions": {"code": "UNAUTHENTICATED"}}]
        }
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json=error_body)
        )

        with pytest.raises(CopilotAuthError):
            fetch_categories(mock_client)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


class TestSetTransactionCategory:
    """Tests for set_transaction_category."""

    @respx.mock
    def test_happy_path(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={
                "data": {"editTransaction": {"transaction": {"id": "txn_1", "categoryId": "cat_1", "isReviewed": False, "userNotes": None, "__typename": "Transaction"}, "__typename": "EditTransactionPayload"}}
            })
        )

        set_transaction_category(mock_client, "txn_1", "acc_1", "item_1", "cat_1")

    @respx.mock
    def test_api_error_raises(self, mock_client):
        error_body = {
            "errors": [{"message": "Transaction not found", "extensions": {"code": "NOT_FOUND"}}]
        }
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json=error_body)
        )

        with pytest.raises(CopilotAPIError, match="Transaction not found"):
            set_transaction_category(mock_client, "txn_1", "acc_1", "item_1", "cat_1")


class TestSetTransactionNote:
    """Tests for set_transaction_note."""

    @respx.mock
    def test_happy_path(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={
                "data": {"editTransaction": {"transaction": {"id": "txn_1", "categoryId": None, "isReviewed": False, "userNotes": "test note", "__typename": "Transaction"}, "__typename": "EditTransactionPayload"}}
            })
        )

        set_transaction_note(mock_client, "txn_1", "acc_1", "item_1", "test note")

    @respx.mock
    def test_clear_note(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={
                "data": {"editTransaction": {"transaction": {"id": "txn_1", "categoryId": None, "isReviewed": False, "userNotes": "", "__typename": "Transaction"}, "__typename": "EditTransactionPayload"}}
            })
        )

        set_transaction_note(mock_client, "txn_1", "acc_1", "item_1", None)


class TestSetTransactionReviewed:
    """Tests for set_transaction_reviewed."""

    @respx.mock
    def test_mark_reviewed(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={
                "data": {"bulkEditTransactions": {"updated": [{"id": "txn_1", "isReviewed": True, "__typename": "Transaction"}], "failed": [], "__typename": "BulkEditTransactionsPayload"}}
            })
        )

        set_transaction_reviewed(mock_client, "txn_1", "acc_1", "item_1", True)

    @respx.mock
    def test_mark_unreviewed(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={
                "data": {"bulkEditTransactions": {"updated": [{"id": "txn_1", "isReviewed": False, "__typename": "Transaction"}], "failed": [], "__typename": "BulkEditTransactionsPayload"}}
            })
        )

        set_transaction_reviewed(mock_client, "txn_1", "acc_1", "item_1", False)

    @respx.mock
    def test_failed_update_raises(self, mock_client):
        respx.post(BASE_URL).mock(
            return_value=httpx.Response(200, json={
                "data": {"bulkEditTransactions": {"updated": [], "failed": [{"error": "Permission denied", "errorCode": "FORBIDDEN", "__typename": "BulkEditError"}], "__typename": "BulkEditTransactionsPayload"}}
            })
        )

        with pytest.raises(CopilotAPIError, match="Permission denied"):
            set_transaction_reviewed(mock_client, "txn_1", "acc_1", "item_1", True)
