"""Endpointy asystenta AI - rozmowy, historia, streaming SSE odpowiedzi (Etap 4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.ai.assistant import is_available, run_stream, strip_context
from app.db.base import AssistantSessionLocal, SessionLocal, get_db
from app.db.models.chat import Conversation, Message
from app.db.models.ops import User
from app.deps import get_current_user

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(get_current_user)])


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    updated_at: str


class MessageOut(BaseModel):
    role: str
    text: str


class SendIn(BaseModel):
    # Pytanie właściciela i opis widoku idą do modelu - limit chroni przed rachunkiem za tokeny.
    text: str = Field(min_length=1, max_length=4000)
    view_context: str | None = Field(default=None, max_length=2000)


@router.get("/status")
def status() -> dict:
    return {"available": is_available()}


def _own_conversation(db: DBSession, conv_id: uuid.UUID, user: User) -> Conversation:
    """Rozmowa zalogowanego konta. Cudza rozmowa daje to samo 404 co nieistniejąca."""
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Nie znaleziono rozmowy")
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user),
                       db: DBSession = Depends(get_db)) -> list[ConversationOut]:
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.archived_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    ).all()
    return [ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at.isoformat()) for c in rows]


@router.post("/conversations", response_model=ConversationOut)
def create_conversation(user: User = Depends(get_current_user),
                        db: DBSession = Depends(get_db)) -> ConversationOut:
    conv = Conversation(user_id=user.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return ConversationOut(id=conv.id, title=conv.title, updated_at=conv.updated_at.isoformat())


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def conversation_messages(conv_id: uuid.UUID, user: User = Depends(get_current_user),
                          db: DBSession = Depends(get_db)) -> list[MessageOut]:
    _own_conversation(db, conv_id, user)
    rows = db.scalars(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    ).all()
    out = []
    for m in rows:
        text = _extract_text(m.content)
        if text:
            out.append(MessageOut(role=m.role, text=text))
    return out


@router.post("/conversations/{conv_id}/messages")
def send_message(conv_id: uuid.UUID, data: SendIn = Body(...), user: User = Depends(get_current_user),
                 db: DBSession = Depends(get_db)) -> StreamingResponse:
    """Streaming SSE odpowiedzi asystenta. Używa własnej sesji DB (długożyjący strumień).

    Właściciel rozmowy jest sprawdzany przed startem strumienia: cudza rozmowa to zwykłe 404."""
    _own_conversation(db, conv_id, user)
    user_id = user.id

    def event_gen():
        db = SessionLocal()
        # Osobna sesja read-only (assistant_ro) dla zapytań narzędzi (decyzja #9). Tworzenie sesji
        # jest leniwe - ewentualny brak roli ujawni się dopiero przy zapytaniu, a wtedy run_stream
        # wyłącza narzędzia (fail closed). Historię czatu (chat.*) obsługuje zawsze `db`.
        try:
            tool_db = AssistantSessionLocal()
        except Exception:  # noqa: BLE001
            tool_db = None
        try:
            conv = db.get(Conversation, conv_id)
            if conv is None or conv.user_id != user_id:
                yield 'event: error\ndata: {"message_pl": "Nie znaleziono rozmowy"}\n\n'
                return
            yield from run_stream(db, conv, data.text, data.view_context, tool_db=tool_db)
        finally:
            if tool_db is not None:
                tool_db.close()
            db.close()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _extract_text(content) -> str:
    """Wyciąga tekst do wyświetlenia z bloków content (pomija tool_use/tool_result/kontekst)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            # Ukryj bloki kontekstu z wiadomości użytkownika.
            parts.append(strip_context(block.get("text", "")))
    return "\n".join(p for p in parts if p)
