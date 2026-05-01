from pydantic import BaseModel


class AccountCreate(BaseModel):
    name: str
    bank: str
    type: str

class AccountResponse(BaseModel):
    id: int
    name: str
    bank: str
    type: str
    model_config = {"from_attributes": True}

class CategoryCreate(BaseModel):
    name: str

class CategoryResponse(BaseModel):
    id: int
    name: str
    is_default: bool
    model_config = {"from_attributes": True}

class KeywordMappingResponse(BaseModel):
    id: int
    keyword_pattern: str
    category_id: int
    category_name: str | None = None
    source: str
    model_config = {"from_attributes": True}

class BudgetCreate(BaseModel):
    month: str
    target_amount: float

class BudgetResponse(BaseModel):
    id: int
    month: str
    target_amount: float
    model_config = {"from_attributes": True}

class TransactionResponse(BaseModel):
    id: int
    date: str
    description: str
    amount: float
    type: str
    category_id: int | None
    category_name: str | None = None
    account_id: int
    account_name: str | None = None
    bank: str | None = None
    is_recurring: bool
    is_cash_withdrawal: bool
    is_internal_transfer: bool
    linked_transfer_id: int | None
    model_config = {"from_attributes": True}

class TransactionCategoryUpdate(BaseModel):
    category_id: int

class TransactionCreate(BaseModel):
    account_id: int
    date: str
    description: str
    amount: float
    type: str
    category_id: int | None = None

class UploadResult(BaseModel):
    filename: str
    bank: str
    transactions_imported: int
    duplicates_skipped: int
    status: str
    message: str | None = None

class DashboardSummary(BaseModel):
    month: str
    total_income: float
    total_spending: float
    savings: float
    savings_pct: float
    budget_target: float | None
    budget_used_pct: float | None
    cash_withdrawn: float
    cash_logged: float
    cash_untracked: float
    categories: list["CategorySpending"]
    internal_transfers: list["TransferSummary"]

class CategorySpending(BaseModel):
    category_id: int
    category_name: str
    amount: float

class TransferSummary(BaseModel):
    from_account: str
    to_account: str
    amount: float


class EmailAccountResponse(BaseModel):
    id: int
    email: str
    last_fetched_at: str | None
    model_config = {"from_attributes": True}

class FetchResult(BaseModel):
    email: str
    statements_found: int
    statements_processed: list[UploadResult]
    # ok: refresh + fetch succeeded.
    # auth_failed: refresh_token revoked/invalid — user needs to Reconnect Gmail.
    # fetch_failed: transient (network, Gmail API hiccup) — user can retry.
    status: str = "ok"
    error_message: str | None = None
