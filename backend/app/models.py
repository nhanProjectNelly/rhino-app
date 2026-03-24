from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # "admin" | "user"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RhinoList(Base):
    """Rhino list (high_quality or images)."""
    __tablename__ = "rhino_lists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    list_type: Mapped[str] = mapped_column(String(32))  # "high_quality" | "images"
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    identities = relationship("RhinoIdentity", back_populates="list_ref", cascade="all, delete-orphan")


class RhinoIdentity(Base):
    """A rhino identity (ID)."""
    __tablename__ = "rhino_identities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("rhino_lists.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(256))  # e.g. "Donny ID1444"
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ATRW pid (number)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    list_ref = relationship("RhinoList", back_populates="identities")
    images = relationship("RhinoImage", back_populates="identity", cascade="all, delete-orphan")


class RhinoImage(Base):
    """Image in gallery. part crops link to parent_image_id (full/body source for re-crop)."""
    __tablename__ = "rhino_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_id: Mapped[int] = mapped_column(ForeignKey("rhino_identities.id"))
    file_path: Mapped[str] = mapped_column(String(512))
    part_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # left_ear, right_ear, head, body
    parent_image_id: Mapped[int | None] = mapped_column(ForeignKey("rhino_images.id"), nullable=True)
    source_stem: Mapped[str | None] = mapped_column(String(256), nullable=True)  # capture key e.g. 10_rhino
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description_parts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="draft")  # draft | pending_review | junk | confirmed
    review_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    identity = relationship("RhinoIdentity", back_populates="images")


class RhinoDescriptionVersion(Base):
    """Versioned four-part description for an anchor (body) image; trace via created_from_version_id."""
    __tablename__ = "rhino_description_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anchor_image_id: Mapped[int] = mapped_column(ForeignKey("rhino_images.id"), index=True)
    description_parts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_from_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("rhino_description_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PredictionRecord(Base):
    """Prediction result: query image → top1 + top5."""
    __tablename__ = "prediction_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_image_path: Mapped[str] = mapped_column(String(512))
    top1_identity_id: Mapped[int | None] = mapped_column(ForeignKey("rhino_identities.id"), nullable=True)
    top1_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    top5_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_image_id: Mapped[int | None] = mapped_column(ForeignKey("rhino_images.id"), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_identity_id: Mapped[int | None] = mapped_column(ForeignKey("rhino_identities.id"), nullable=True)
    reported: Mapped[bool] = mapped_column(Boolean, default=False)
    corrected_identity_id: Mapped[int | None] = mapped_column(ForeignKey("rhino_identities.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PredictionAuditLog(Base):
    __tablename__ = "prediction_audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("prediction_records.id"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
