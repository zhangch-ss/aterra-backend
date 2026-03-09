from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user
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
from app.utils.cache import AgentCache
from app.core.model.llm_factory import build_raw_client
from app.core.agent.registry import AgentRegistry
from app.core.agent.runner import AgentOrchestrator
# 确保类型适配器完成注册（导入即注册）
from app.core.agent.types import deep_agent as _deep_agent_module  # noqa: F401
from app.core.agent.types import plan_act as _plan_act_module  # noqa: F401
router = APIRouter()
from app.utils.logger import setup_logger
logger = setup_logger(__name__)


@router.get("/sessions", response_model=SessionsListResponse)
async def list_sessions(
    page: int = 1,
    page_size: int = 20,
    order_by: str = "updated_at",
    order_dir: str = "desc",
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    sessions = await crud_chat.get_sessions_by_user(
        user_id=current_user.id,
        db_session=db,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
    )
    total = await crud_chat.get_sessions_count_by_user(user_id=current_user.id, db_session=db)

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
async def create_chat_session(db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    payload = SessionCreate()
    chat_session_obj = await crud_chat.create_session(session_in=payload, user_id=str(current_user.id), db_session=db)

    return chat_session_obj


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_session_detail(session_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    s = await crud_chat.get_session(session_id=session_id, db_session=db)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(s.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限访问该会话")
    msgs = await crud_chat.get_messages(session_id=session_id, db_session=db)
    return SessionDetailOut.model_validate({
        **s.__dict__,
        "messages": msgs
    })


@router.put("/sessions/{session_id}")
async def rename_chat_session(session_id: str, payload: SessionRename, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    s0 = await crud_chat.get_session(session_id=session_id, db_session=db)
    if not s0:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(s0.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限修改该会话")
    s = await crud_chat.rename_session(session_id=session_id, new_title=payload.title, db_session=db)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_chat_session(session_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    s0 = await crud_chat.get_session(session_id=session_id, db_session=db)
    if not s0:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(s0.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限删除该会话")
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
async def stream_agent_chat(request: ChatCompletions, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):

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

    logger.info("用户输入: %s", user_input)

    # === 优化：尝试从缓存获取 Agent ===
    # 注意：由于 SQLModel 对象复杂，我们使用缓存来快速判断 Agent 是否存在
    # 如果缓存命中，说明 Agent 存在，可以直接查询；如果未命中，查询后缓存
    cached_agent_data = await AgentCache.get(agent_id)
    
    # 会话鉴权：仅允许操作自己的会话
    sess = await crud_chat.get_session(session_id=session_id, db_session=db)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if str(sess.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限操作该会话")

    # 从数据库查询 Agent（始终需要完整对象）
    agent_obj = await crud_agent.get_with_relations(
        id=agent_id, 
        db_session=db, 
        relations=["model", "tools"]
    )
    
    if not agent_obj:
        raise HTTPException(status_code=404, detail="Agent 未找到")
    if str(agent_obj.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权限使用该智能体")
    
    # 如果缓存未命中，查询后缓存 Agent 数据（用于快速判断 Agent 是否存在）
    if not cached_agent_data:
        await AgentCache.set(agent_id, agent_obj)

    # === 基于新框架：Registry + Orchestrator ===
    # 选择 agent 类型：优先请求配置的 mode，其次数据库 agent.type，默认 deepagent
    kind = None
    if cfg and getattr(cfg, "mode", None):
        kind = cfg.mode
    agent_impl = AgentRegistry.create(agent_obj, db, kind=kind)
    orchestrator = AgentOrchestrator(db=db)

    return await orchestrator.stream_response(
        agent_impl,
        user_id=str(current_user.id),
        session_id=session_id,
        user_input=user_input,
        persist_history=persist_history,
        ephemeral_ttl_seconds=ephemeral_ttl_seconds,
        ephemeral_cleanup=ephemeral_cleanup,
        extra_context={},
    )


# ========= 3️⃣ 自动生成标题接口 =========
@router.post("/sessions/summarize_title")
async def summarize_session_title(req: SummarizeRequest, db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    """
    自动生成会话标题。
    根据前两轮对话（用户+AI）生成一句简洁的中文标题。
    """
    try:
        # 统一从请求体读取 session_id 与 agent_id（路径参数仅为兼容保留）
        req_session_id = getattr(req, "session_id", None)
        agent_id = getattr(req, "agent_id", None)
        if not req_session_id:
            raise HTTPException(status_code=400, detail="缺少 session_id")
        if not agent_id:
            raise HTTPException(status_code=400, detail="缺少 agent_id")

        # 优先从数据库获取系统 Prompt（可配置覆盖）
        db_prompt = await crud_prompt.get_system_prompt_by_name(name="SUMMARIZE_TITLE", db_session=db)
        prompt_template = db_prompt.content if db_prompt else SUMMARIZE_TITLE
        prompt = prompt_template.format(context_text=req.query)

        # 查询会话与 Agent（预加载模型关系）
        sess = await crud_chat.get_session(session_id=req_session_id, db_session=db)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if str(sess.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="无权限访问该会话")

        agent_obj = await crud_agent.get_with_relations(
            id=agent_id,
            relations=["model"],
            db_session=db,
        )
        if not agent_obj:
            raise HTTPException(status_code=404, detail="Agent 未找到")
        if str(agent_obj.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="无权限使用该智能体")

        # 构造官方 SDK 客户端（优先使用 agent 绑定模型配置 + 凭证库）
        client = None
        model_name = "gpt-4o-mini"

        cfg = getattr(agent_obj.model, "invoke_config", None)
        provider = getattr(agent_obj.model, "provider", None)
        client, ctx = await build_raw_client(user_id=str(current_user.id), cfg=cfg, provider=provider)
        model_name = ctx.effective_model or model_name

        # 调用模型生成标题
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": ""},
                {"role": "user", "content": prompt},
            ],
        )

        title = response.choices[0].message.content.strip().replace("标题：", "").strip()
        if not title:
            title = "未命名会话"

        logger.info("[%s] 自动生成标题: %s", req_session_id, title)
        return {"title": title}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("生成标题出错: %s", e)
        raise HTTPException(status_code=500, detail=f"生成标题失败: {e}")
