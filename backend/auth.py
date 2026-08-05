"""Database-backed users and JWT authentication."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from config import settings

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserDailyUsage(Base):
    __tablename__ = "user_daily_usage"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_user_daily_usage"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    usage_date: Mapped[date] = mapped_column(Date)
    llm_request_count: Mapped[int] = mapped_column(Integer, default=0)


class InterviewHistory(Base):
    __tablename__ = "interview_histories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    target_position: Mapped[str] = mapped_column(String(200))
    difficulty: Mapped[str] = mapped_column(String(50))
    answered_questions: Mapped[int] = mapped_column(Integer, default=0)
    overall_score: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
bearer = HTTPBearer(auto_error=False)

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"

def _verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt_hex, digest_hex = encoded.split("$", 2)
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False

def create_user(username: str, password: str) -> User:
    with SessionLocal() as db:
        if db.query(User).filter(User.username == username).first():
            raise ValueError("username already exists")
        user = User(username=username, password_hash=_hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

def authenticate(username: str, password: str) -> User | None:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
        if user and _verify_password(password, user.password_hash):
            return user
    return None


def create_knowledge_document(user_id: int, filename: str) -> KnowledgeDocument:
    with SessionLocal() as db:
        document = KnowledgeDocument(id=str(uuid4()), user_id=user_id, filename=filename)
        db.add(document)
        db.commit()
        db.refresh(document)
        return document


def update_knowledge_document_chunk_count(document_id: str, user_id: int, chunk_count: int) -> None:
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if not document or document.user_id != user_id:
            raise ValueError("knowledge document not found")
        document.chunk_count = chunk_count
        db.commit()


def delete_knowledge_document(document_id: str, user_id: int) -> None:
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document and document.user_id == user_id:
            db.delete(document)
            db.commit()


def consume_daily_llm_quota(user_id: int, quota: int) -> bool:
    usage_date = datetime.now(timezone.utc).date()
    for _ in range(2):
        with SessionLocal() as db:
            update_result = db.execute(
                update(UserDailyUsage)
                .where(
                    UserDailyUsage.user_id == user_id,
                    UserDailyUsage.usage_date == usage_date,
                    UserDailyUsage.llm_request_count < quota,
                )
                .values(llm_request_count=UserDailyUsage.llm_request_count + 1)
            )
            if update_result.rowcount:
                db.commit()
                return True
            try:
                db.add(UserDailyUsage(user_id=user_id, usage_date=usage_date, llm_request_count=1))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
    return False


def get_daily_llm_request_count(user_id: int) -> int:
    usage_date = datetime.now(timezone.utc).date()
    with SessionLocal() as db:
        usage = db.query(UserDailyUsage).filter(
            UserDailyUsage.user_id == user_id,
            UserDailyUsage.usage_date == usage_date,
        ).first()
        return usage.llm_request_count if usage else 0


def cleanup_expired_daily_usage(retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=retention_days)
    with SessionLocal() as db:
        deleted = db.query(UserDailyUsage).filter(UserDailyUsage.usage_date < cutoff).delete()
        db.commit()
        return deleted


def get_expired_knowledge_document_ids(retention_days: int) -> list[str]:
    if retention_days <= 0:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with SessionLocal() as db:
        return [document_id for document_id, in db.query(KnowledgeDocument.id).filter(KnowledgeDocument.created_at < cutoff)]


def delete_knowledge_documents(document_ids: list[str]) -> int:
    if not document_ids:
        return 0
    with SessionLocal() as db:
        deleted = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(document_ids)).delete(synchronize_session=False)
        db.commit()
        return deleted


def save_interview_history(user_id: int, session_id: str, session, report: dict) -> InterviewHistory:
    import json

    with SessionLocal() as db:
        history = db.query(InterviewHistory).filter(
            InterviewHistory.user_id == user_id,
            InterviewHistory.session_id == session_id,
        ).first()
        if history is None:
            history = InterviewHistory(
                id=str(uuid4()),
                user_id=user_id,
                session_id=session_id,
                target_position=session.target_position,
                difficulty=session.difficulty,
                created_at=datetime.now(timezone.utc),
            )
            db.add(history)
        history.answered_questions = int(report.get("answered_questions", 0))
        history.overall_score = int(report.get("overall_score", 0))
        history.report_json = json.dumps(report, ensure_ascii=False)
        db.commit()
        db.refresh(history)
        return history


def list_interview_histories(user_id: int) -> list[InterviewHistory]:
    with SessionLocal() as db:
        return db.query(InterviewHistory).filter(
            InterviewHistory.user_id == user_id,
        ).order_by(InterviewHistory.created_at.desc()).all()


def get_interview_history(history_id: str, user_id: int) -> InterviewHistory | None:
    with SessionLocal() as db:
        return db.query(InterviewHistory).filter(
            InterviewHistory.id == history_id,
            InterviewHistory.user_id == user_id,
        ).first()


def delete_interview_history(history_id: str, user_id: int) -> str | None:
    with SessionLocal() as db:
        history = db.query(InterviewHistory).filter(
            InterviewHistory.id == history_id,
            InterviewHistory.user_id == user_id,
        ).first()
        if history is None:
            return None
        session_id = history.session_id
        db.delete(history)
        db.commit()
        return session_id


def delete_all_interview_histories(user_id: int) -> list[str]:
    with SessionLocal() as db:
        histories = db.query(InterviewHistory).filter(
            InterviewHistory.user_id == user_id,
        ).all()
        session_ids = [history.session_id for history in histories]
        db.query(InterviewHistory).filter(
            InterviewHistory.user_id == user_id,
        ).delete(synchronize_session=False)
        db.commit()
        return session_ids

def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "username": user.username, "iat": now, "exp": now + timedelta(hours=8)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user is inactive")
        return user
