from __future__ import annotations

import datetime as dt
from sqlalchemy import String, Integer, Float, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

class Market(Base):
    __tablename__ = "markets"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="")
    close_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc))

class OrderbookSnapshot(Base):
    __tablename__ = "orderbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    yes_bids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # [[price, qty], ...]
    no_bids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

class NewsItem(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    url: Mapped[str] = mapped_column(String, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # yes|no
    action: Mapped[str] = mapped_column(String) # buy|sell (we mainly buy)
    price_cents: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)
    p_market: Mapped[float] = mapped_column(Float)
    p_model: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")

class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # yes|no
    action: Mapped[str] = mapped_column(String) # buy|sell
    price_cents: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String, default="paper")
    external_order_id: Mapped[str | None] = mapped_column(String, nullable=True)

class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # yes|no
    qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_price_cents: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
