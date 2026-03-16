"""SQLAlchemy ORM models for persisting orders, fills, and backtest jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from backend.db.session import Base


def _uuid():
    return str(uuid.uuid4())


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=_uuid)
    intent_id = Column(String(36), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)  # buy / sell
    quantity = Column(Integer, nullable=False)
    order_type = Column(String(6), nullable=False)  # market / limit
    limit_price = Column(Float, nullable=True)
    status = Column(String(20), default="pending")
    # Option fields
    option_type = Column(String(2), nullable=True)    # CE / PE
    strike = Column(Float, nullable=True)
    expiry = Column(String(10), nullable=True)
    strategy = Column(String(30), nullable=True)      # single / vertical_spread / ...
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Fill(Base):
    __tablename__ = "fills"

    id = Column(String(36), primary_key=True, default=_uuid)
    order_id = Column(String(36), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    side = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    filled_price = Column(Float, nullable=False)
    slippage = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    # Option fields
    option_type = Column(String(2), nullable=True)
    strike = Column(Float, nullable=True)
    expiry = Column(String(10), nullable=True)
    strategy = Column(String(30), nullable=True)
    executed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BacktestJob(Base):
    __tablename__ = "backtest_jobs"

    id = Column(String(36), primary_key=True, default=_uuid)
    tickers = Column(Text, nullable=False)  # JSON list
    start_date = Column(String(10), nullable=False)
    end_date = Column(String(10), nullable=False)
    initial_capital = Column(Float, default=100_000.0)
    strategy = Column(String(50), default="momentum")
    status = Column(String(20), default="pending")
    result_json = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String(36), primary_key=True, default=_uuid)
    event = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(36), nullable=True)
    data = Column(Text, nullable=True)  # JSON blob
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
