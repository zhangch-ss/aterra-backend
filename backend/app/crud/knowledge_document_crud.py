from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.knowledge_document import KnowledgeDocument
from app.crud.base_crud import CRUDBase
from app.crud.mixins import CRUDUserFilterMixin


class CRUDKnowledgeDocument(CRUDBase[KnowledgeDocument, KnowledgeDocument, KnowledgeDocument], CRUDUserFilterMixin):
    def __init__(self):
        super().__init__(KnowledgeDocument)

    async def list_by_knowledge(
        self,
        *,
        knowledge_id: str,
        user_id: str,
        db_session: AsyncSession | None = None,
    ) -> List[KnowledgeDocument]:
        db_session = db_session or self.db.session
        stmt = (
            select(self.model)
            .where(self.model.knowledge_id == knowledge_id)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc())
        )
        res = await db_session.execute(stmt)
        return res.scalars().all()

    async def get_by_knowledge_and_id(
        self,
        *,
        knowledge_id: str,
        doc_id: str,
        user_id: str,
        db_session: AsyncSession | None = None,
    ) -> Optional[KnowledgeDocument]:
        db_session = db_session or self.db.session
        stmt = (
            select(self.model)
            .where(self.model.id == doc_id)
            .where(self.model.knowledge_id == knowledge_id)
            .where(self.model.user_id == user_id)
        )
        res = await db_session.execute(stmt)
        return res.scalar_one_or_none()


crud_knowledge_document = CRUDKnowledgeDocument()
