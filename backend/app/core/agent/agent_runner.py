# app/core/agent/agent_runner.py
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from app.core.tool.tool_loader import ToolLoader
from app.core.config import settings
from app.core.tool.tools.gee.authz import RuntimeContext
from app.models.agent import Agent
from app.models.tool import Tool
from app.crud.chat_crud import crud_chat
from app.schemas.chat import MessageCreate
from app.utils import ephemeral_store as eph
from app.services.model_service import model_service
from langchain_openai import ChatOpenAI, AzureChatOpenAI


logger = logging.getLogger(__name__)


class AgentRunner:
    """🤖 Agent 执行器：创建并调用 DeepAgent，返回 JSON 流事件

    增强：加入全链路详细日志，覆盖配置解析、工具加载、上下文构建、流式输出、
    工具调用、持久化与异常等关键流程，所有日志均打上 trace/session/message 关联信息。
    """

    def __init__(self, agent_obj: Agent, db: AsyncSession):
        self.agent_obj = agent_obj
        self.db = db
        self.agent = None
        self.tool_funcs = []
        # 运行时模型/提供方标签（用于日志与 SSE）
        self.model_name: Optional[str] = None
        self.provider_label: Optional[str] = None

    # =============================
    # 日志辅助：统一结构与敏感信息屏蔽
    # =============================

    SENSITIVE_KEYS = {
        "api_key",
        "token",
        "access_token",
        "secret",
        "password",
        "key",
        "authorization",
        "auth",
    }

    def _mask_sensitive(self, obj: Any) -> Any:
        """递归屏蔽敏感字段值。"""
        try:
            if isinstance(obj, dict):
                masked = {}
                for k, v in obj.items():
                    if isinstance(k, str) and k.lower() in self.SENSITIVE_KEYS:
                        masked[k] = "***"
                    else:
                        masked[k] = self._mask_sensitive(v)
                return masked
            if isinstance(obj, list):
                return [self._mask_sensitive(i) for i in obj]
            return obj
        except Exception:
            return obj

    def _summarize_text(self, text: Any, max_len: int = 200) -> Dict[str, Any]:
        """摘要长文本，避免日志暴涨。"""
        try:
            s = str(text) if text is not None else ""
            total_len = len(s)
            if total_len <= max_len:
                return {"preview": s, "total_len": total_len}
            return {"preview": s[:max_len], "total_len": total_len}
        except Exception as e:
            return {"preview": f"<summary_error: {e}>", "total_len": None}

    def _log(self, level: str, event: str, **fields: Any) -> None:
        """统一事件式日志输出，自动屏蔽敏感字段。"""
        data = self._mask_sensitive(fields)
        msg = f"{event} | " + " ".join(
            [f"{k}={json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}" for k, v in data.items()]
        )
        if level == "debug":
            logger.debug(msg)
        elif level == "warning":
            logger.warning(msg)
        elif level == "error":
            logger.error(msg)
        else:
            logger.info(msg)

    async def init_agent(self):
        """初始化模型、工具与 DeepAgent 实例"""
        agent_obj = self.agent_obj

        self._log(
            "info",
            "AGENT_INIT_START",
            agent_id=str(getattr(agent_obj, "id", "")),
            user_id=str(getattr(agent_obj, "user_id", "")),
        )

        # === 模型配置 ===
        model_invoke_cfg = getattr(agent_obj.model, "invoke_config", {}) or {}
        if isinstance(model_invoke_cfg, dict):
            model_name = model_invoke_cfg.get("name", "gpt-4o")
        else:
            model_name = getattr(model_invoke_cfg, "name", "gpt-4o")
        # 记录模型名称用于 SSE 扩展字段
        self.model_name = model_name

        system_prompt = getattr(agent_obj, "system_prompt", None) or "You are a helpful assistant. 你可以使用工具来完成"

        # === 工具加载 ===
        tools = getattr(agent_obj, "tools", []) or []
        if tools and isinstance(tools[0], Tool):
            self.tool_funcs = ToolLoader.load_tools_from_records(tools)
        tool_names = [getattr(t, "name", "") for t in self.tool_funcs]
        self._log(
            "info",
            "TOOLS_LOADED",
            tool_count=len(self.tool_funcs),
            tool_names=tool_names,
        )

        # === 从数据库读取凭证并构建 Chat 模型（不使用环境变量） ===
        raw_cfg = getattr(agent_obj.model, "invoke_config", None)
        cfg = model_service.coerce_invoke_config(raw_cfg)

        prov = getattr(agent_obj.model, "provider", None)
        # 自动检测 Azure 风格（当 provider 未显式指定时）
        if not prov:
            base_url_candidate = None
            try:
                base_url_candidate = cfg.client.base_url if (cfg and getattr(cfg, "client", None)) else None
            except Exception:
                base_url_candidate = None
            if base_url_candidate:
                bu = base_url_candidate.lower()
                if "cognitiveservices.azure.com" in bu or "/openai/deployments/" in bu:
                    prov = "azure"
        if not prov:
            prov = "openai"
        p_lower = prov.lower()

        # 记录 provider 标签用于 SSE 扩展字段
        self.provider_label = (
            "AzureOpenAI" if p_lower in ("azure", "azure-openai") else (
                "OpenAI" if p_lower in ("openai", "oai", "openai-compatible") else prov
            )
        )

        # 从凭证库读取 Provider 凭据（按用户/提供方）
        creds = await model_service.get_provider_credentials(
            user_id=str(getattr(agent_obj, "user_id", "") or ""),
            provider=prov,
            reveal_secret=True,
        )
        cred_fields_present = sorted([k for k in creds.keys() if creds.get(k) is not None])

        # 基本采样参数
        temperature = 0.7
        max_completion_tokens=None
        try:
            if cfg and getattr(cfg, "parameters", None) and cfg.parameters.temperature is not None:
                temperature = float(cfg.parameters.temperature)
            if cfg and getattr(cfg, "parameters", None) and cfg.parameters.max_completion_tokens is not None:
                max_completion_tokens = int(cfg.parameters.max_completion_tokens)
        except Exception:
            pass

        self._log(
            "info",
            "MODEL_CONFIG_RESOLVED",
            provider_label=self.provider_label,
            model_name=self.model_name,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            base_url_present=bool(getattr(cfg, "client", None) and getattr(cfg.client, "base_url", None)),
        )
        self._log(
            "info",
            "CREDENTIALS_RESOLVED",
            provider=prov,
            fields_present=cred_fields_present,
        )

        # 构建 LangChain Chat 模型实例（直接传给 deepagents，不依赖环境变量）
        try:
            if p_lower in ("azure", "azure-openai"):
                api_key = creds.get("api_key")
                azure_endpoint = creds.get("azure_endpoint") or (cfg.client.azure_endpoint if getattr(cfg, "client", None) else None)
                if azure_endpoint:
                    azure_endpoint = model_service.derive_azure_endpoint(azure_endpoint)
                api_version = creds.get("api_version") or (cfg.client.api_version if getattr(cfg, "client", None) else None)
                deployment_name = creds.get("azure_deployment") or model_name

                if not api_key or not azure_endpoint or not api_version:
                    raise HTTPException(status_code=400, detail="Missing Azure credentials (api_key/endpoint/api_version)")
                try:
                    llm = AzureChatOpenAI(
                        api_key=api_key,
                        azure_endpoint=azure_endpoint,
                        api_version=api_version,
                        azure_deployment=deployment_name,
                        temperature=temperature,
                        max_completion_tokens=max_completion_tokens
                    )
                except TypeError:
                    # 兼容部分版本将部署名参数识别为 model
                    llm = AzureChatOpenAI(
                        api_key=api_key,
                        azure_endpoint=azure_endpoint,
                        api_version=api_version,
                        model=deployment_name,
                        temperature=temperature,
                        max_completion_tokens=max_completion_tokens
                    )
            elif p_lower in ("openai", "oai", "openai-compatible"):
                api_key = creds.get("api_key")
                base_url = creds.get("base_url") or (cfg.client.base_url if getattr(cfg, "client", None) else None)
                organization = creds.get("organization") or (cfg.client.organization if getattr(cfg, "client", None) else None)
                if not api_key:
                    raise HTTPException(status_code=400, detail="Missing provider API key")
                llm = ChatOpenAI(
                    model=model_name,
                    api_key=api_key,
                    base_url=base_url,
                    organization=organization,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported provider: {prov}")
            self._log("info", "LLM_INIT_SUCCESS", provider_label=self.provider_label, model_name=self.model_name)
        except Exception as e:
            self._log("error", "LLM_INIT_FAIL", provider_label=self.provider_label, model_name=self.model_name, error=str(e))
            raise

        # === 创建 DeepAgent（传入已配置的 Chat 模型实例） ===

        self.agent = create_deep_agent(
            model=llm,
            tools=self.tool_funcs,
            # system_prompt=system_prompt,
            backend=FilesystemBackend(
                root_dir=settings.WORK_DIR,
                virtual_mode=True,
            ),
            context_schema=RuntimeContext,
        )
        self._log(
            "info",
            "BACKEND_READY",
            work_dir=settings.WORK_DIR,
            virtual_mode=True,
        )

    async def build_conversation_context(
        self, 
        session_id: str, 
        include_user_input: bool = False,
        user_input: str = "",
        persist_history: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        从数据库构建完整的对话上下文，支持工具调用消息的转换
        
        Args:
            session_id: 会话ID
            include_user_input: 是否包含当前用户输入（用于流式响应前构建上下文）
            user_input: 当前用户输入内容
            
        Returns:
            List[Dict]: LangChain 格式的消息列表
        """
        self._log(
            "info",
            "CTX_BUILD_START",
            session_id=session_id,
            persist_history=persist_history,
            include_user_input=include_user_input,
        )
        # 从数据库获取历史消息
        history_msgs = await crud_chat.get_messages_by_session(
            session_id=session_id, 
            db_session=self.db
        )
        
        context = []
        
        # 如果不持久化，使用临时内存中的消息构建上下文
        if not persist_history:
            eph_msgs = await eph.get_messages(session_id)
            assistant_tool_calls_count = 0
            tool_msg_count = 0
            for msg in eph_msgs:
                role = msg.get("role")
                if role == "user":
                    context.append({"role": "user", "content": msg.get("content", "")})
                elif role == "assistant":
                    entry = {"role": "assistant", "content": msg.get("content") or ""}
                    tc_wrapper = msg.get("tool_calls") or {}
                    tool_calls_list = tc_wrapper.get("tool_calls", [])
                    if tool_calls_list:
                        assistant_tool_calls_count += 1
                        entry["tool_calls"] = []
                        for tc in tool_calls_list:
                            args_str = tc.get("arguments", "{}")
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                            except (json.JSONDecodeError, TypeError):
                                args = {}
                            masked_args = self._mask_sensitive(args)
                            entry["tool_calls"].append({
                                "id": tc.get("id", ""),
                                "name": tc.get("name", ""),
                                "args": masked_args,
                            })
                    context.append(entry)
                elif role == "tool":
                    tool_msg_count += 1
                    entry = {
                        "role": "tool",
                        "content": msg.get("content", ""),
                        "tool_call_id": msg.get("tool_call_id", ""),
                    }
                    if msg.get("tool_name"):
                        entry["name"] = msg.get("tool_name")
                    context.append(entry)
            if include_user_input and user_input:
                context.append({"role": "user", "content": user_input})
            self._log(
                "info",
                "CTX_BUILD_EPHEMERAL",
                session_id=session_id,
                total_messages=len(context),
                assistant_tool_calls_count=assistant_tool_calls_count,
                tool_msg_count=tool_msg_count,
            )
            logger.debug(f"📝(ephemeral) 构建上下文完成，共 {len(context)} 条消息")
            return context
        
        assistant_tool_calls_count = 0
        tool_msg_count = 0
        for msg in history_msgs:
            msg_dict: Dict[str, Any] = {}
            
            if msg.role == "user":
                # 用户消息：直接添加
                msg_dict = {
                    "role": "user",
                    "content": msg.content
                }
            
            elif msg.role == "assistant":
                # Assistant 消息：可能包含工具调用
                msg_dict = {
                    "role": "assistant",
                    "content": msg.content or ""  # 工具调用时可能为空
                }
                
                # 如果包含工具调用，转换为 LangChain 格式
                if msg.tool_calls:
                    tool_calls_list = msg.tool_calls.get("tool_calls", [])
                    if tool_calls_list:
                        assistant_tool_calls_count += 1
                        msg_dict["tool_calls"] = []
                        for tc in tool_calls_list:
                            tool_call_id = tc.get("id", "")
                            tool_name = tc.get("name", "")
                            arguments_str = tc.get("arguments", "{}")
                            
                            # 解析参数（可能是字符串或已经是字典）
                            try:
                                if isinstance(arguments_str, str):
                                    arguments = json.loads(arguments_str)
                                else:
                                    arguments = arguments_str
                            except (json.JSONDecodeError, TypeError):
                                arguments = {}
                            masked_args = self._mask_sensitive(arguments)
                            
                            msg_dict["tool_calls"].append({
                                "id": tool_call_id,
                                "name": tool_name,
                                "args": masked_args
                            })
            
            elif msg.role == "tool":
                # Tool 消息：包含工具执行结果
                tool_msg_count += 1
                msg_dict = {
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id or "",
                }
                
                # 如果 LangChain 需要 name 字段，也添加
                if msg.tool_name:
                    msg_dict["name"] = msg.tool_name
            
            if msg_dict:
                context.append(msg_dict)
        
        # 如果需要包含当前用户输入，添加到上下文末尾
        if include_user_input and user_input:
            context.append({
                "role": "user",
                "content": user_input
            })
        
        self._log(
            "info",
            "CTX_BUILD_PERSISTED",
            session_id=session_id,
            total_messages=len(context),
            assistant_tool_calls_count=assistant_tool_calls_count,
            tool_msg_count=tool_msg_count,
        )
        logger.debug(f"📝 构建上下文完成，共 {len(context)} 条消息")
        return context

    async def stream_response(self, user_input: str, session_id: str, persist_history: bool = True, ephemeral_ttl_seconds: Optional[int] = None, ephemeral_cleanup: bool = False):
        """返回模型 token + 工具调用事件流（SSE 格式）"""
        if not self.agent:
            raise HTTPException(status_code=500, detail="Agent 未初始化")

        # 事件扩展元信息
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        protocol_version = "v1"
        start_time = datetime.utcnow()

        self._log(
            "info",
            "STREAM_START",
            trace_id=trace_id,
            message_id=message_id,
            session_id=session_id,
            protocol_version=protocol_version,
            model_info={
                "model_id": getattr(self, 'model_name', None),
                "provider": getattr(self, 'provider_label', None),
            }
        )

        # === 构建历史上下文（包含工具调用信息） ===
        context = await self.build_conversation_context(
            session_id=session_id,
            include_user_input=True,
            user_input=user_input,
            persist_history=persist_history,
        )

        # === 优化：收集所有需要写入的消息，流式结束后批量写入 ===
        messages_to_save = []  # 在外部作用域定义，供 generate() 函数访问
        # 用户消息先保存（因为需要立即在数据库中可见）
        if persist_history:
            user_msg = await crud_chat.create_message(
                session_id=session_id,
                msg_in=MessageCreate(role="user", content=user_input),
                db_session=self.db
            )
            self._log("info", "USER_MSG_SAVED", session_id=session_id, message_id=user_msg.id)
        else:
            await eph.append_message(session_id, {"role": "user", "content": user_input}, ttl_seconds=ephemeral_ttl_seconds)
            self._log("info", "USER_MSG_EPHEMERAL", session_id=session_id, ttl_seconds=ephemeral_ttl_seconds)

        async def generate( ):
            nonlocal messages_to_save  # 声明使用外部作用域的变量
            ai_chunks = []
            assistant_tool_calls = None  # 存储assistant的工具调用
            gathered: AIMessageChunk = None  # 累积的 AIMessageChunk（参考官方示例）
            tool_calls_saved = False  # 标记 tool_calls 是否已保存
            last_assistant_msg_id = None  # 记录最后创建的 assistant 消息 ID，避免重复查询
            chunk_index = 0
            final_sent = False

            try:
                runtime_ctx = RuntimeContext(
                    user_id=str(getattr(self.agent_obj, "user_id", "") or ""),
                    db=self.db
                )

                print("runtime_ctx", runtime_ctx)
                async for item in self.agent.astream(
                    {"messages": context}, 
                    context=runtime_ctx, stream_mode=["messages"]):

                    # 🧠 兼容不同返回类型
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        mode, chunk = item
                    else:
                        # 新版本可能直接返回消息对象
                        mode, chunk = "messages", item

                    # === 模型 token 流和工具调用 ===
                    if mode == "messages":
                        msg, metadata = chunk
                        
                        if isinstance(msg, (AIMessageChunk, AIMessage)):
                            type = "token"
                            
                            # 累积 AIMessageChunk（参考 LangChain 官方示例）
                            if isinstance(msg, AIMessageChunk):
                                gathered = msg if gathered is None else gathered + msg
                                
                                # 使用累积后的消息
                                final_msg = gathered
                            else:
                                # AIMessage 不是 chunk，直接使用
                                final_msg = msg
                                gathered = None  # 重置累积器
                            
                            # 检查是否是最后一个 chunk
                            is_last_chunk = False
                            if isinstance(msg, AIMessageChunk):
                                chunk_position = getattr(msg, "chunk_position", None)
                                is_last_chunk = (chunk_position == "last")
                            elif isinstance(msg, AIMessage):
                                # AIMessage 本身就表示完整的消息
                                is_last_chunk = True
                            
                            # 收集文本内容（流式输出增量内容）
                            if hasattr(msg, "content") and msg.content:
                                # 使用累积后的消息获取完整内容
                                if gathered:
                                    content = gathered.content or ""
                                else:
                                    content = msg.content
                                
                                if content:
                                    # 提取新增的内容
                                    existing_content = "".join(ai_chunks)
                                    if content.startswith(existing_content):
                                        new_content = content[len(existing_content):]
                                        if new_content:
                                            ai_chunks.append(new_content)
                                            payload = {
                                                'type': 'token',
                                                'content': new_content,
                                                'final': False,
                                                'format': 'markdown',
                                                'index': chunk_index,
                                                'session_id': session_id,
                                                'message_id': message_id,
                                                'protocol_version': protocol_version,
                                                'created_at': datetime.utcnow().isoformat() + 'Z',
                                                'trace_id': trace_id,
                                            }
                                            self._log("debug", "TOKEN_CHUNK", index=chunk_index, new_len=len(new_content), total_len=len("".join(ai_chunks)))
                                            yield f"data: {json.dumps(payload)}\n\n"
                                            chunk_index += 1
                                    else:
                                        # 如果内容完全不同，可能是新的消息
                                        if len(ai_chunks) == 0:
                                            ai_chunks.append(content)
                                            payload = {
                                                'type': 'token',
                                                'content': content,
                                                'final': False,
                                                'format': 'markdown',
                                                'index': chunk_index,
                                                'session_id': session_id,
                                                'message_id': message_id,
                                                'protocol_version': protocol_version,
                                                'created_at': datetime.utcnow().isoformat() + 'Z',
                                                'trace_id': trace_id,
                                            }
                                            self._log("debug", "TOKEN_CHUNK", index=chunk_index, new_len=len(content), total_len=len("".join(ai_chunks)))
                                            yield f"data: {json.dumps(payload)}\n\n"
                                            chunk_index += 1
                            
                            # 检查是否有工具调用（使用累积后的消息）
                            if is_last_chunk and hasattr(final_msg, "tool_calls") and final_msg.tool_calls:
                                # 只在最后一个 chunk 时处理完整的 tool_calls
                                if not tool_calls_saved and not assistant_tool_calls:
                                    assistant_tool_calls = final_msg.tool_calls
                                    tool_calls_saved = True
                                    
                                    # 构建完整的 tool_calls_data
                                    tool_calls_data = []
                                    masked_args_for_log = []
                                    for tc in final_msg.tool_calls:
                                        tool_call_id = tc.get("id", "")
                                        tool_name = tc.get("name", "")
                                        args = tc.get("args", "")
                                        
                                        # 处理 arguments（可能是字符串或字典）
                                        if isinstance(args, str):
                                            try:
                                                args_dict = json.loads(args)
                                                arguments_str = json.dumps(args_dict, ensure_ascii=False)
                                                masked_args_for_log.append(self._mask_sensitive(args_dict))
                                            except (json.JSONDecodeError, TypeError):
                                                arguments_str = args if args else "{}"
                                                masked_args_for_log.append({})
                                        elif isinstance(args, dict):
                                            arguments_str = json.dumps(args, ensure_ascii=False)
                                            masked_args_for_log.append(self._mask_sensitive(args))
                                        else:
                                            arguments_str = "{}"
                                            masked_args_for_log.append({})
                                        
                                        tool_calls_data.append({
                                            "id": tool_call_id,
                                            "name": tool_name,
                                            "arguments": arguments_str
                                        })
                                    
                                    # 优化：收集消息，不立即写入（批量写入）
                                    messages_to_save.append({
                                        "role": "assistant",
                                        "content": final_msg.content or "",
                                        "tool_calls": {"tool_calls": tool_calls_data}
                                    })
                                    
                                    # 发送工具调用事件
                                    tool_names = [tc.get("name", "") for tc in final_msg.tool_calls]
                                    print(f"🔧 完整的工具调用 (累积后): {tool_names}, tool_calls_data: {tool_calls_data}")
                                    logger.info(f"🔧 完整的工具调用 (累积后): {tool_names}, tool_calls_data: {tool_calls_data}")
                                    self._log(
                                        "info",
                                        "TOOL_CALL_STARTED",
                                        tools=tool_names,
                                        args_masked=masked_args_for_log,
                                        session_id=session_id,
                                        trace_id=trace_id,
                                    )
                                    tool_payload = {
                                        'type': 'tool',
                                        'tools': tool_names,
                                        'status': 'started',
                                        'session_id': session_id,
                                        'message_id': message_id,
                                        'protocol_version': protocol_version,
                                        'created_at': datetime.utcnow().isoformat() + 'Z',
                                        'trace_id': trace_id,
                                    }
                                    yield f"data: {json.dumps(tool_payload)}\n\n"
                                    
                                    # 重置累积器（准备下一个消息）
                                    gathered = None
                        
                        elif isinstance(msg, ToolMessage):
                            type = "tool_msg"
                            # 捕获工具响应
                            tool_call_id = getattr(msg, "tool_call_id", "")
                            tool_name = getattr(msg, "name", "")
                            tool_content = msg.content if hasattr(msg, "content") else ""
                            
                            # 工具响应后，重置累积状态（准备下一个 AI 消息）
                            gathered = None
                            tool_calls_saved = False
                            assistant_tool_calls = None
                            
                            # 优化：收集工具响应消息，不立即写入（批量写入）
                            messages_to_save.append({
                                "role": "tool",
                                "content": tool_content,
                                "tool_call_id": tool_call_id,
                                "tool_name": tool_name
                            })
                            
                            # 发送工具响应事件（带扩展字段）
                            content_type = 'text'
                            parsed_json = None
                            summary = None
                            if isinstance(tool_content, str):
                                try:
                                    parsed_json = json.loads(tool_content)
                                    content_type = 'json'
                                except Exception:
                                    content_type = 'text'
                                finally:
                                    summary = self._summarize_text(tool_content)
                            else:
                                summary = self._summarize_text(tool_content)
                            self._log(
                                "info",
                                "TOOL_MSG_RECEIVED",
                                tool_call_id=tool_call_id,
                                tool_name=tool_name,
                                content_type=content_type,
                                summary=summary,
                                session_id=session_id,
                                trace_id=trace_id,
                            )
                            payload = {
                                'type': 'tool_msg',
                                'content': tool_content,
                                'tool_call_id': tool_call_id,
                                'tool_name': tool_name,
                                'content_type': content_type,
                                'json': parsed_json,
                                'status': 'success',
                                'session_id': session_id,
                                'message_id': message_id,
                                'protocol_version': protocol_version,
                                'created_at': datetime.utcnow().isoformat() + 'Z',
                                'trace_id': trace_id,
                            }
                            yield f"data: {json.dumps(payload)}\n\n"

                # === 完成后保存最终的assistant文本回复 ===
                ai_text = "".join(ai_chunks).strip()
                
                # 如果流结束但还有累积的消息（可能最后一个 chunk 没有设置 chunk_position）
                if gathered and hasattr(gathered, "tool_calls") and gathered.tool_calls and not tool_calls_saved:
                    # 保存最后的 tool_calls
                    assistant_tool_calls = gathered.tool_calls
                    tool_calls_saved = True
                    
                    tool_calls_data = []
                    masked_args_for_log = []
                    for tc in gathered.tool_calls:
                        tool_call_id = tc.get("id", "")
                        tool_name = tc.get("name", "")
                        args = tc.get("args", "")
                        
                        if isinstance(args, str):
                            try:
                                args_dict = json.loads(args)
                                arguments_str = json.dumps(args_dict, ensure_ascii=False)
                                masked_args_for_log.append(self._mask_sensitive(args_dict))
                            except (json.JSONDecodeError, TypeError):
                                arguments_str = args if args else "{}"
                                masked_args_for_log.append({})
                        elif isinstance(args, dict):
                            arguments_str = json.dumps(args, ensure_ascii=False)
                            masked_args_for_log.append(self._mask_sensitive(args))
                        else:
                            arguments_str = "{}"
                            masked_args_for_log.append({})
                        
                        tool_calls_data.append({
                            "id": tool_call_id,
                            "name": tool_name,
                            "arguments": arguments_str
                        })
                    
                    # 优化：收集消息，不立即写入（批量写入）
                    messages_to_save.append({
                        "role": "assistant",
                        "content": gathered.content or "",
                        "tool_calls": {"tool_calls": tool_calls_data}
                    })
                    
                    tool_names = [tc.get("name", "") for tc in gathered.tool_calls]
                    logger.info(f"🔧 工具调用（流结束）: {tool_names}, tool_calls_data: {tool_calls_data}")
                    self._log(
                        "info",
                        "TOOL_CALL_FINISHED",
                        tools=tool_names,
                        args_masked=masked_args_for_log,
                        session_id=session_id,
                        trace_id=trace_id,
                    )
                    tool_payload = {
                        'type': 'tool',
                        'tools': tool_names,
                        'status': 'finished',
                        'session_id': session_id,
                        'message_id': message_id,
                        'protocol_version': protocol_version,
                        'created_at': datetime.utcnow().isoformat() + 'Z',
                        'trace_id': trace_id,
                    }
                    yield f"data: {json.dumps(tool_payload)}\n\n"
                
                if ai_text and not assistant_tool_calls:
                    # 如果没有工具调用，收集普通文本回复
                    messages_to_save.append({
                        "role": "assistant",
                        "content": ai_text
                    })
                elif ai_text and assistant_tool_calls:
                    # 如果有工具调用且有文本回复，标记需要更新最后一条 assistant 消息
                    # 注意：这里我们会在批量写入后更新
                    pass
                
                # 优化：批量写入所有收集的消息
                if messages_to_save:
                    if persist_history:
                        try:
                            saved_messages = await crud_chat.bulk_create_messages(
                                session_id=session_id,
                                messages_data=messages_to_save,
                                db_session=self.db
                            )
                            logger.info(f"✅ 批量写入 {len(saved_messages)} 条消息")
                            self._log("info", "DB_BULK_WRITE_OK", count=len(saved_messages), session_id=session_id)
                            
                            # 如果有工具调用且有文本回复，更新最后一条 assistant 消息
                            if ai_text and assistant_tool_calls:
                                # 从批量保存的消息中找到最后一条带 tool_calls 的 assistant 消息
                                for msg in reversed(saved_messages):
                                    if msg.role == "assistant" and msg.tool_calls:
                                        last_assistant_msg_id = msg.id
                                        break
                                
                                if last_assistant_msg_id:
                                    from app.schemas.chat import MessageUpdate
                                    await crud_chat.update_message(
                                        message_id=last_assistant_msg_id,
                                        msg_in=MessageUpdate(content=ai_text),
                                        db_session=self.db
                                    )
                                    logger.info(f"✅ 已更新 assistant 消息内容: {last_assistant_msg_id}")
                                    self._log("info", "DB_ASSISTANT_UPDATE", message_id=last_assistant_msg_id, session_id=session_id)
                        except Exception as e:
                            logger.error(f"❌ 批量写入消息失败: {e}", exc_info=True)
                            self._log("error", "DB_BULK_WRITE_FAIL", error=str(e), session_id=session_id)
                    else:
                        # 如果有工具调用且有文本回复，更新待写入的 assistant 消息内容
                        if ai_text and assistant_tool_calls:
                            for i in range(len(messages_to_save) - 1, -1, -1):
                                m = messages_to_save[i]
                                if m.get("role") == "assistant" and m.get("tool_calls"):
                                    m["content"] = ai_text
                                    break
                        try:
                            await eph.bulk_append_messages(session_id, messages_to_save, ttl_seconds=ephemeral_ttl_seconds)
                            logger.info(f"🗒️(ephemeral) 缓存写入 {len(messages_to_save)} 条消息")
                            self._log("info", "EPHEMERAL_WRITE_OK", count=len(messages_to_save), session_id=session_id)
                        except Exception as e:
                            logger.error(f"❌ (ephemeral) 写入失败: {e}", exc_info=True)
                            self._log("error", "EPHEMERAL_WRITE_FAIL", error=str(e), session_id=session_id)
                        finally:
                            if ephemeral_cleanup:
                                try:
                                    await eph.clear_session(session_id)
                                    logger.info("🧹(ephemeral) 已清理会话临时数据")
                                    self._log("info", "EPHEMERAL_CLEANUP_OK", session_id=session_id)
                                except Exception as e:
                                    logger.error(f"❌ (ephemeral) 清理失败: {e}", exc_info=True)
                                    self._log("error", "EPHEMERAL_CLEANUP_FAIL", error=str(e), session_id=session_id)

                # 在 try 结束前发送最终结束事件（final token），用于前端聚合与统计
                if not final_sent:
                    elapsed_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    final_payload = {
                        'type': 'token',
                        'content': '',
                        'final': True,
                        'finish_reason': 'stop',
                        'format': 'markdown',
                        'index': chunk_index,
                        'session_id': session_id,
                        'message_id': message_id,
                        'protocol_version': protocol_version,
                        'created_at': datetime.utcnow().isoformat() + 'Z',
                        'trace_id': trace_id,
                            'model_info': {
                                'model_id': getattr(self, 'model_name', None),
                                'provider': getattr(self, 'provider_label', None),
                                'latency_ms': elapsed_ms,
                            },
                    }
                    self._log("info", "STREAM_FINAL", finish_reason='stop', latency_ms=elapsed_ms, token_count=len("".join(ai_chunks)))
                    yield f"data: {json.dumps(final_payload)}\n\n"
                    final_sent = True

            except Exception as e:
                logger.error(f"Agent stream error: {e}", exc_info=True)
                self._log("error", "STREAM_ERROR", error=str(e), session_id=session_id, trace_id=trace_id)
                err = f"[Agent Error]: {str(e)}"
                payload = {
                    'type': 'error',
                    'content': err,
                    'code': 500,
                    'session_id': session_id,
                    'message_id': message_id,
                    'protocol_version': protocol_version,
                    'created_at': datetime.utcnow().isoformat() + 'Z',
                    'trace_id': trace_id,
                }
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
