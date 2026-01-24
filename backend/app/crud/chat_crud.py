# app/crud/chat_crud.py
from typing import List, Optional
from fastapi import HTTPException
from sqlalchemy import exc, select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.crud.base_crud import CRUDBase
from app.models.chat import ChatSession, ChatMessage
from app.schemas.chat import SessionCreate, SessionUpdate, MessageCreate, MessageUpdate
from datetime import datetime


class CRUDChat(CRUDBase[ChatSession, SessionCreate, SessionUpdate]):
    """💬 ChatSession + ChatMessage 的异步 CRUD 操作封装"""

    def __init__(self):
        super().__init__(ChatSession)

    # ====================== ChatSession 部分 ======================

    async def get_sessions_by_user(
        self,
        *,
        user_id: str,
        db_session: Optional[AsyncSession] = None,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "updated_at",
        order_dir: str = "desc",
    ) -> List[ChatSession]:
        """按用户ID获取会话，支持分页与排序"""
        db_session = db_session or self.db.session
        offset = max((page - 1), 0) * page_size
        order_col = ChatSession.updated_at if order_by == "updated_at" else ChatSession.created_at
        if order_by == "title":
            order_col = ChatSession.title
        if order_dir.lower() == "asc":
            order = order_col.asc()
        else:
            order = order_col.desc()
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(order)
            .offset(offset)
            .limit(page_size)
        )
        result = await db_session.exec(stmt)
        return result.scalars().all()

    async def get_sessions_count_by_user(
        self,
        *,
        user_id: str,
        db_session: Optional[AsyncSession] = None,
    ) -> int:
        db_session = db_session or self.db.session
        result = await db_session.exec(
            select(ChatSession).where(ChatSession.user_id == user_id)
        )
        return len(result.scalars().all())

    async def get_session_stats(
        self,
        *,
        session_id: str,
        db_session: Optional[AsyncSession] = None,
    ) -> dict:
        """计算会话的消息数与最近消息预览"""
        db_session = db_session or self.db.session
        # 消息总数
        msgs = await db_session.exec(
            select(ChatMessage).where(ChatMessage.session_id == session_id)
        )
        msgs_list = msgs.scalars().all()
        message_count = len(msgs_list)
        last_preview = None
        if message_count:
            last_preview = (msgs_list[-1].content or "")
            if last_preview and len(last_preview) > 120:
                last_preview = last_preview[:120]
        return {"message_count": message_count, "last_message_preview": last_preview}

    async def get_session(
        self,
        *,
        session_id: str,
        db_session: Optional[AsyncSession] = None,
    ) -> Optional[ChatSession]:
        """获取单个会话详情"""
        db_session = db_session or self.db.session
        stmt = select(ChatSession).where(ChatSession.id == session_id)
        result = await db_session.exec(stmt)
        return result.scalar_one_or_none()

    async def create_session(
        self,
        *,
        session_in: SessionCreate,
        db_session: Optional[AsyncSession] = None,
    ) -> ChatSession:
        """创建新的聊天会话"""
        db_session = db_session or self.db.session
        db_obj = ChatSession(**session_in.model_dump())

        try:
            db_session.add(db_obj)
            await db_session.commit()
            await db_session.refresh(db_obj)
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(status_code=409, detail=f"Session creation failed: {str(e)}")

        return db_obj

    async def rename_session(
        self,
        *,
        session_id: str,
        new_title: str,
        db_session: Optional[AsyncSession] = None,
    ) -> Optional[ChatSession]:
        """重命名聊天会话"""
        db_session = db_session or self.db.session
        stmt = select(ChatSession).where(ChatSession.id == session_id)
        result = await db_session.exec(stmt)
        s = result.scalar_one_or_none()

        if not s:
            return None

        s.title = new_title.strip() or s.title
        s.updated_at = datetime.utcnow()

        try:
            db_session.add(s)
            await db_session.commit()
            await db_session.refresh(s)
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=f"Rename failed: {str(e)}")

        return s

    async def delete_session(
        self,
        *,
        session_id: str,
        db_session: Optional[AsyncSession] = None,
    ) -> None:
        """删除聊天会话"""
        db_session = db_session or self.db.session
        stmt = select(ChatSession).where(ChatSession.id == session_id)
        result = await db_session.exec(stmt)
        s = result.scalar_one_or_none()

        if s:
            await db_session.delete(s)
            await db_session.commit()

    # ====================== ChatMessage 部分 ======================

    async def get_messages(
        self,
        *,
        session_id: str,
        db_session: Optional[AsyncSession] = None,
    ) -> List[ChatMessage]:
        """获取指定会话的全部消息"""
        db_session = db_session or self.db.session
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await db_session.exec(stmt)
        return result.scalars().all()

    async def create_message(
        self,
        *,
        session_id: str,
        msg_in: MessageCreate,
        db_session: Optional[AsyncSession] = None,
    ) -> ChatMessage:
        """创建新消息，并更新会话的 updated_at"""
        db_session = db_session or self.db.session
        db_obj = ChatMessage(session_id=session_id, **msg_in.model_dump())

        try:
            db_session.add(db_obj)
            await db_session.commit()
            await db_session.refresh(db_obj)
            # 更新会话的更新时间
            s_res = await db_session.exec(select(ChatSession).where(ChatSession.id == session_id))
            s = s_res.scalar_one_or_none()
            if s:
                s.updated_at = datetime.utcnow()
                db_session.add(s)
                await db_session.commit()
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(status_code=409, detail=f"Message creation failed: {str(e)}")
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=f"Message creation failed: {str(e)}")

        return db_obj

    async def bulk_create_messages(
        self,
        *,
        session_id: str,
        messages_data: list[dict],
        db_session: Optional[AsyncSession] = None,
    ) -> List[ChatMessage]:
        """批量插入消息记录"""
        db_session = db_session or self.db.session
        db_objs = [ChatMessage(session_id=session_id, **d) for d in messages_data]

        try:
            db_session.add_all(db_objs)
            await db_session.commit()
            for db_obj in db_objs:
                await db_session.refresh(db_obj)
        except exc.IntegrityError as e:
            await db_session.rollback()
            raise HTTPException(status_code=409, detail=f"Bulk insert failed: {str(e)}")

        return db_objs

    async def get_messages_by_session(self, *, session_id: str, db_session: AsyncSession):
        from app.models.chat import ChatMessage
        result = await db_session.exec(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return result.scalars().all()

    async def update_message(
        self,
        *,
        message_id: str,
        msg_in: MessageUpdate,
        db_session: Optional[AsyncSession] = None,
    ) -> Optional[ChatMessage]:
        """更新消息内容"""
        db_session = db_session or self.db.session
        stmt = select(ChatMessage).where(ChatMessage.id == message_id)
        result = await db_session.exec(stmt)
        msg = result.scalar_one_or_none()
        
        if not msg:
            return None
        
        if msg_in.content is not None:
            msg.content = msg_in.content
        
        try:
            db_session.add(msg)
            await db_session.commit()
            await db_session.refresh(msg)
        except Exception as e:
            await db_session.rollback()
            raise HTTPException(status_code=500, detail=f"Message update failed: {str(e)}")
        
        return msg
# 单例实例
crud_chat = CRUDChat()
