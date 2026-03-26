from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owned_cages: Mapped[list["Cage"]] = relationship(back_populates="owner")
    usage_records: Mapped[list["UsageRecord"]] = relationship(back_populates="user")
    announcements: Mapped[list["Announcement"]] = relationship(back_populates="user")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    racks: Mapped[list["Rack"]] = relationship(back_populates="room")
    cages: Mapped[list["Cage"]] = relationship(back_populates="room")


class Rack(Base):
    __tablename__ = "racks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)

    room: Mapped["Room"] = relationship(back_populates="racks")
    cages: Mapped[list["Cage"]] = relationship(back_populates="rack")


class Cage(Base):
    __tablename__ = "cages"

    id: Mapped[int] = mapped_column(primary_key=True)
    cage_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    rack_id: Mapped[int] = mapped_column(ForeignKey("racks.id"), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    strain: Mapped[str] = mapped_column(String(100), nullable=False)
    male_genotype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    female_genotype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    male_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    female_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    setup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    wean_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pup_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="使用中")
    cage_tag_image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    room: Mapped["Room"] = relationship(back_populates="cages")
    rack: Mapped["Rack"] = relationship(back_populates="cages")
    owner: Mapped["User"] = relationship(back_populates="owned_cages")
    usage_records: Mapped[list["UsageRecord"]] = relationship(
        back_populates="cage", order_by="desc(UsageRecord.created_at)"
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    cage_id: Mapped[int] = mapped_column(ForeignKey("cages.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cage: Mapped["Cage"] = relationship(back_populates="usage_records")
    user: Mapped["User"] = relationship(back_populates="usage_records")


class SyncOperation(Base):
    __tablename__ = "sync_operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    op_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    cage_code: Mapped[str] = mapped_column(String(50), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    client_created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sync_result: Mapped[str] = mapped_column(String(20), default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="announcements")


class LoginMemory(Base):
    __tablename__ = "login_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip_address: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship()
