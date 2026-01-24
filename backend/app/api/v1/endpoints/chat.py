from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.schemas.chat import (
    SessionCreate,
    SessionRename,
    SessionOut,
    SessionDetailOut,
    ChatSessionListItem,
    SessionsListResponse,
    MessageCreate,
    SummarizeRequest,
)
from app.crud.chat_crud import crud_chat
from app.crud.tool_crud import crud_tool
from app.crud.agent_crud import crud_agent
from app.crud.prompt_crud import crud_prompt
from app.core.prompts.prompts import SUMMARIZE_TITLE
from uuid import UUID
from openai import AzureOpenAI
import os
from deepagents import create_deep_agent
from app.core.tool.tool_loader import ToolLoader
from app.core.agent.agent_runner import AgentRunner
from app.utils.cache import AgentCache
from app.core.config import settings
router = APIRouter()


@router.get("/sessions", response_model=SessionsListResponse)
async def list_sessions(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "updated_at",
    order_dir: str = "desc",
    db: AsyncSession = Depends(get_db),
):
    sessions = await crud_chat.get_sessions_by_user(
        user_id=user_id,
        db_session=db,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
    )
    total = await crud_chat.get_sessions_count_by_user(user_id=user_id, db_session=db)

    items: list[ChatSessionListItem] = []
    for s in sessions:
        stats = await crud_chat.get_session_stats(session_id=str(s.id), db_session=db)
        items.append(
            ChatSessionListItem(
                id=s.id,
                title=s.title,
                created_at=s.created_at,
                updated_at=getattr(s, "updated_at", None),
                user_id=s.user_id,
                last_message_preview=stats.get("last_message_preview"),
                message_count=stats.get("message_count"),
            )
        )

    return SessionsListResponse(sessions=items, total=total, page=page, page_size=page_size)


@router.post("/sessions", response_model=SessionOut)
async def create_chat_session(payload: SessionCreate, db: AsyncSession = Depends(get_db)):
    chat_session_obj = await crud_chat.create_session(session_in=payload, db_session=db)

    return chat_session_obj


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_session_detail(session_id: str, db: AsyncSession = Depends(get_db)):
    s = await crud_chat.get_session(session_id=session_id, db_session=db)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = await crud_chat.get_messages(session_id=session_id, db_session=db)
    return SessionDetailOut.model_validate({
        **s.__dict__,
        "messages": msgs
    })


@router.put("/sessions/{session_id}")
async def rename_chat_session(session_id: str, payload: SessionRename, db: AsyncSession = Depends(get_db)):
    s = await crud_chat.rename_session(session_id=session_id, new_title=payload.title, db_session=db)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_chat_session(session_id: str, db: AsyncSession = Depends(get_db)):
    await crud_chat.delete_session(session_id=session_id, db_session=db)
    return {"ok": True}

from pydantic import BaseModel




class ChatConfig(BaseModel):
    persist_history: bool | None = True
    mode: str | None = None
    ephemeral: bool | None = None
    ttl_seconds: int | None = None
    cleanup_on_finish: bool | None = None

class ChatCompletions(BaseModel):
    query: str
    agent_id: str
    session_id: str
    config: ChatConfig | None = None


@router.post("/completions/stream")
async def stream_agent_chat(request: ChatCompletions, db: AsyncSession = Depends(get_db)):

    user_input = request.query
    session_id = request.session_id
    agent_id = request.agent_id
    cfg = getattr(request, "config", None)
    persist_history = True
    ephemeral_ttl_seconds = None
    ephemeral_cleanup = False
    if cfg:
        if getattr(cfg, "ephemeral", None) is True:
            persist_history = False
        elif getattr(cfg, "persist_history", None) is not None:
            persist_history = bool(cfg.persist_history)
        ttl = getattr(cfg, "ttl_seconds", None)
        if ttl is not None:
            try:
                ephemeral_ttl_seconds = int(ttl)
            except Exception:
                ephemeral_ttl_seconds = None
        cleanup_flag = getattr(cfg, "cleanup_on_finish", None)
        if cleanup_flag is True:
            ephemeral_cleanup = True

    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")

    print(f"💬 用户输入: {user_input}")

    # === 优化：尝试从缓存获取 Agent ===
    # 注意：由于 SQLModel 对象复杂，我们使用缓存来快速判断 Agent 是否存在
    # 如果缓存命中，说明 Agent 存在，可以直接查询；如果未命中，查询后缓存
    cached_agent_data = await AgentCache.get(agent_id)
    
    # 从数据库查询 Agent（始终需要完整对象）
    agent_obj = await crud_agent.get_with_relations(
        id=agent_id, 
        db_session=db, 
        relations=["model", "tools"]
    )
    
    if not agent_obj:
        raise HTTPException(status_code=404, detail="Agent 未找到")
    
    # 如果缓存未命中，查询后缓存 Agent 数据（用于快速判断 Agent 是否存在）
    if not cached_agent_data:
        await AgentCache.set(agent_id, agent_obj)

    # === 初始化执行器 ===
    runner = AgentRunner(agent_obj, db)
    await runner.init_agent()

    # === 返回流式响应 ===
    return await runner.stream_response(
        user_input,
        session_id,
        persist_history=persist_history,
        ephemeral_ttl_seconds=ephemeral_ttl_seconds,
        ephemeral_cleanup=ephemeral_cleanup,
    )


# ========= 3️⃣ 自动生成标题接口 =========
@router.post("/sessions/{session_id}/summarize_title")
async def summarize_session_title(session_id: str, req: SummarizeRequest, db: AsyncSession = Depends(get_db)):
    """
    自动生成会话标题。
    根据前两轮对话（用户+AI）生成一句简洁的中文标题。
    """
    try:
        # 优先从数据库获取系统 Prompt（可配置覆盖）
        db_prompt = await crud_prompt.get_system_prompt_by_name(name="SUMMARIZE_TITLE", db_session=db)
        prompt_template = db_prompt.content if db_prompt else SUMMARIZE_TITLE
        prompt = prompt_template.format(context_text=req.query)

        # TODO 改为根据请求参数初始化client
        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.OPENAI_API_KEY,
            api_version=settings.OPENAI_API_VERSION,
        )

        # 调用 Azure OpenAI 模型
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ""},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=50,
        )

        title = response.choices[0].message.content.strip().replace("标题：", "").strip()

        if not title:
            title = "未命名会话"

        print(f"✅ [{session_id}] 自动生成标题: {title}")
        return {"title": title}

    except Exception as e:
        print(f"❌ 生成标题出错: {e}")
        raise HTTPException(status_code=500, detail=f"生成标题失败: {e}")
