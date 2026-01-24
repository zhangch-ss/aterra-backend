from fastapi import APIRouter
from app.api.v1.endpoints import lake
from app.api.v1.endpoints import chat
from app.api.v1.endpoints import agent
from app.api.v1.endpoints import tool
from app.api.v1.endpoints import auth
from app.api.v1.endpoints import model
from app.api.v1.endpoints import prompt
from app.api.v1.endpoints import knowledge
from app.api.v1.endpoints import text_splitter
from app.api.v1.endpoints import market
from app.api.v1.endpoints import plan_act

api_router = APIRouter()

api_router.include_router(lake.router, prefix="/lake", tags=["lake"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(agent.router, prefix="/agents", tags=["Agents"])
api_router.include_router(plan_act.router, prefix="/agents", tags=["Agents"])
api_router.include_router(tool.router, prefix="/tools", tags=["Tools"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(model.router, prefix="/models", tags=["Models"])
api_router.include_router(prompt.router, prefix="/prompts", tags=["Prompts"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge"])
api_router.include_router(market.router, prefix="/market", tags=["Market"])
api_router.include_router(text_splitter.router, prefix="/text-splitters", tags=["TextSplitters"])
