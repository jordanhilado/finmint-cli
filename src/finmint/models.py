"""TypedDict models for finmint database entities."""

from typing import TypedDict


class Account(TypedDict, total=False):
    id: str
    institution_name: str
    account_type: str
    last_four: str
    last_synced_at: str
    created_at: str


class Label(TypedDict, total=False):
    id: int
    name: str
    is_default: bool
    is_protected: bool
    created_at: str


class Transaction(TypedDict, total=False):
    id: str
    account_id: str
    amount: int  # cents (negative = debit)
    date: str
    description: str
    normalized_description: str
    label_id: int
    review_status: str
    categorized_by: str
    transfer_pair_id: str
    source_type: str
    created_at: str


class MerchantRule(TypedDict, total=False):
    id: int
    pattern: str
    label_id: int
    source: str
    created_at: str
