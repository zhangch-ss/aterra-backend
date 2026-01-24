from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.knowledge import Knowledge
from app.crud.base_crud import CRUDBase
from app.schemas.knowledge import KnowledgeCreate, KnowledgeUpdate
from app.crud.mixins import CRUDUserFilterMixin

class CRUDKnowledge(CRUDBase[Knowledge, KnowledgeCreate, KnowledgeUpdate], CRUDUserFilterMixin):
    def __init__(self):
        super().__init__(Knowledge)

# ✅ 单例实例
crud_knowledge = CRUDKnowledge()
