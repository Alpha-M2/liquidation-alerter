"""SQLAlchemy database models and session management.

This module defines the database schema for the DeFi Liquidation Alerter,
including User, Wallet, and PositionSnapshot models. It uses SQLAlchemy
with async support for non-blocking database operations.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, BigInteger, Boolean, UniqueConstraint, Index, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # User settings
    alert_threshold = Column(Float, default=1.5)  # Health factor threshold for warnings
    critical_threshold = Column(Float, default=1.1)  # Critical threshold
    alerts_paused = Column(Boolean, default=False)

    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("user_id", "address", name="uq_wallet_user_address"),
        Index("ix_wallet_user_address", "user_id", "address"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    address = Column(String(42), nullable=False, index=True)
    label = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="wallets")
    snapshots = relationship(
        "PositionSnapshot", back_populates="wallet", cascade="all, delete-orphan"
    )


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False, index=True)
    protocol = Column(String(50), nullable=False)
    health_factor = Column(Float, nullable=False)
    total_collateral_usd = Column(Float, nullable=False)
    total_debt_usd = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    wallet = relationship("Wallet", back_populates="snapshots")


def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key enforcement for SQLite connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or get_settings().database_url

        engine_kwargs = {"echo": False}
        if "sqlite" in self.database_url:
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 0
            engine_kwargs["pool_pre_ping"] = True

        self.engine = create_async_engine(self.database_url, **engine_kwargs)

        # Enable SQLite foreign key enforcement
        if "sqlite" in self.database_url:
            event.listen(self.engine.sync_engine, "connect", _set_sqlite_pragma)

        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self):
        """Dispose the engine and release all connection pool resources."""
        await self.engine.dispose()


db = Database()
