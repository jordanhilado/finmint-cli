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
    fetch_transactions,
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
) -> dict:
    """Build a raw Copilot transaction node as returned by the GraphQL API."""
    return {
        "id": txn_id,
        "name": name,
        "amount": amount,
        "date": date,
        "type": txn_type,
        "accountId": account_id,
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
            _make_raw_txn("txn_1", "Spotify", -30.0, "2026-03-15"),
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
        assert result[0]["amount"] == -3000
        assert result[0]["date"] == "2026-03-15"
        assert result[0]["description"] == "Spotify"
        assert result[0]["source_type"] == "REGULAR"
        assert result[1]["amount"] == 184017
        assert result[1]["source_type"] == "INCOME"

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
