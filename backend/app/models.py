from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Naive UTC ISO strings keep the column shape (String(30)) and matching
# semantics with _token_near_expiry, which compares both sides as naive.
def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    bank: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    keyword_mappings: Mapped[list["KeywordMapping"]] = relationship(back_populates="category")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")


class KeywordMapping(Base):
    __tablename__ = "keyword_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[str] = mapped_column(String(30), default=_utcnow_iso)

    category: Mapped["Category"] = relationship(back_populates="keyword_mappings")


class Statement(Base):
    __tablename__ = "statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    bank: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    imported_at: Mapped[str] = mapped_column(String(30), default=_utcnow_iso)
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="statement")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("statements.id"), nullable=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cash_withdrawal: Mapped[bool] = mapped_column(Boolean, default=False)
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_transfer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=True)
    # Bank-provided per-transaction unique ID (e.g. TnG's "Trans No" or the
    # concatenated reference parts). None for parsers that don't expose one.
    # Used as a stricter dedup key than (date, amount, type, description) so
    # legitimately-identical transactions (e.g. two same-day same-amount toll
    # passes) are kept while overlapping-statement re-imports are blocked.
    external_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    statement: Mapped["Statement"] = relationship(back_populates="transactions")
    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category"] = relationship(back_populates="transactions")


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_fetched_at: Mapped[str | None] = mapped_column(String(30), nullable=True)


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False, unique=True)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)


class OAuthState(Base):
    """Pending OAuth state tokens. Persisted so a uvicorn --reload between
    /api/oauth/start and /api/oauth/callback doesn't invalidate the flow.
    expires_at is unix epoch seconds; rows are pruned on every cleanup pass."""
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
