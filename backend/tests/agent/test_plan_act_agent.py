"""
Minimal Agent Demo: Plan → Act → Reflect → Verify → Memory

- Plan:   由 LLM 规划子任务列表
- Act:    顺序执行子任务（可以调用工具）
- Reflect:对执行结果做自我反思
- Verify: 使用“审稿人角色”验证任务是否完成
- Memory: 记录本次经验，为下次任务复用（这里简单存在内存里，也可改成写文件/DB）

运行方式：
    python agent_demo.py
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional

# ============================================================
# 配置：是否使用真实 OpenAI/Azure OpenAI API（通过环境变量控制）
# - 为避免泄露，默认不启用真实 API 调用。
# - 如需启用，请设置：
#     USE_OPENAI=true
#     AZURE_OPENAI_ENDPOINT=...
#     OPENAI_API_KEY=...
#     OPENAI_API_VERSION=2024-07-01-preview
# ============================================================
import os

use_openai = os.getenv("USE_OPENAI", "false").lower() in {"1", "true", "yes"}
azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://example.cognitiveservices.azure.com/")
api_key = os.getenv("OPENAI_API_KEY", "")
api_version = os.getenv("OPENAI_API_VERSION", "2024-07-01-preview")

if use_openai and api_key:
    from openai import AzureOpenAI
    client = AzureOpenAI(azure_endpoint=azure_endpoint, api_key=api_key, api_version=api_version)
else:
    client = None  # 用假的 LLM stub，方便直接跑示例


# ============================================================
# 一些简单的“工具函数”（可以理解为 Agent 的外部工具）
# ============================================================

def calculator(expression: str) -> str:
    """简单算式计算工具"""
    try:
        value = eval(expression)
        return str(value)
    except Exception as e:
        return f"CALC_ERROR: {e}"


def string_search(text: str, keyword: str) -> str:
    """模拟一个“文本搜索”工具，在给定文本中查关键字"""
    if keyword.lower() in text.lower():
        return f"Found keyword '{keyword}' in text."
    else:
        return f"Keyword '{keyword}' not found."


TOOLS: Dict[str, Callable[..., str]] = {
    "calculator": calculator,
    "string_search": string_search,
}


# ============================================================
# Memory 数据结构
# ============================================================

@dataclass
class EpisodeMemory:
    task: str
    plan: List[str] = field(default_factory=list)
    reflections: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    final_answer: Optional[str] = None
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "plan": self.plan,
            "reflections": self.reflections,
            "tool_calls": self.tool_calls,
            "final_answer": self.final_answer,
            "verified": self.verified,
        }


class LongTermMemory:
    """这里简单用列表存所有 episode，可以扩展为文件/数据库等"""
    def __init__(self):
        self.episodes: List[EpisodeMemory] = []

    def add_episode(self, episode: EpisodeMemory):
        self.episodes.append(episode)

    def summarize(self) -> str:
        """简单返回一个 JSON 字符串摘要"""
        return json.dumps([e.to_dict() for e in self.episodes], indent=2, ensure_ascii=False)


GLOBAL_MEMORY = LongTermMemory()


# ============================================================
# LLM 封装：支持 OpenAI & stub
# ============================================================

def call_llm(role_desc: str, content: str, system_hint: str = "") -> str:
    """
    小封装：
    - role_desc: 描述当前子模块角色（planner / executor / reflector / verifier）
    - content:   用户/上游内容
    - system_hint: 额外系统提示，可为空
    """
    if not use_openai:
        # ---- Stub 版本：方便本地直接跑，不依赖 LLM ----
        # 根据 role_desc 返回一些可预期的内容，方便理解流程
        if "planner" in role_desc.lower():
            # 直接返回一个 JSON 风格的简单计划
            return (
                "计划：\n"
                "1) 分析题目语义\n"
                "2) 用 calculator 计算表达式 (15-4)*3\n"
                "3) 整理结果并用自然语言回答用户\n"
            )
        elif "executor" in role_desc.lower():
            return "动作建议：调用 calculator 工具计算表达式 (15-4)*3"
        elif "reflector" in role_desc.lower():
            return "反思：这一轮工具调用成功，结果合理，可用于最终回答。"
        elif "verifier" in role_desc.lower():
            return "验证结果：答案数值正确，步骤合理，任务已完成。"
        else:
            return "Stub LLM: " + content[:100]

    # ---- 真 LLM 调用版本 ----
    system_msg = f"You are a {role_desc}.\n" + system_hint
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": content},
    ]
    resp = client.chat.completions.create(
        model="gpt-4.1",
        messages=messages,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


# ============================================================
# 1. Planner：生成 Plan
# ============================================================

def plan(task: str, memory: LongTermMemory) -> List[str]:
    """
    使用 LLM 生成任务计划（list of steps）
    这里简单用换行分割；实际可要求 LLM 输出 JSON。
    """
    prompt = f"用户任务：{task}\n请给出一个分步骤的解决计划，3-6 步，每步一句话。"
    out = call_llm("task planner", prompt)

    # 解析成步骤列表（这里简单按行拆分）
    lines = [line.strip(" 123456789).、.-") for line in out.splitlines() if line.strip()]
    # 简单过滤掉不含中文/英文的行（非常粗糙，只是示例）
    steps = [l for l in lines if any(ch.isalnum() for ch in l)]
    return steps


# ============================================================
# 2. Act：执行计划中的某一步
# ============================================================

def act(step: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行某一步计划：
    - 用 LLM 决定是否调用工具
    - 如果调用工具，则执行并返回结果
    返回：
    {
        "step": step,
        "tool_used": str or None,
        "tool_args": dict,
        "tool_result": str or None,
        "raw_llm_suggestion": str
    }
    """
    # 构建 prompt，让 LLM 告诉我们怎么做
    prompt = f"""
当前子任务：{step}

你可以选择：
1）直接思考并给出自然语言结论；
2）建议调用工具（calculator 或 string_search）。

请用类似下面的格式输出你的建议（注意这是给程序看的，不是给用户的最终答案）：

动作建议：
- 是否调用工具: 是/否
- 若调用工具，请给出: 工具名(tool_name)、参数(params)
- 若不调用工具，直接给出: 思考结论(reasoning_result)
"""
    out = call_llm("executor / tool selector", prompt)
    # 简单解析（真实工程里建议用严格 JSON）
    tool_name = None
    params = {}
    result = None

    lower = out.lower()
    if "calculator" in lower:
        tool_name = "calculator"
        # 简单从文本里抓表达式（这里是示例，实际应该让 LLM 输出 JSON）
        expr = "(15-4)*3"
        params = {"expression": expr}
    elif "string_search" in lower:
        tool_name = "string_search"
        params = {"text": context.get("text_corpus", ""), "keyword": "example"}
    else:
        # 认为不调用工具，直接把结果写在 result 里
        result = out

    if tool_name:
        tool_func = TOOLS.get(tool_name)
        if tool_func:
            try:
                result = tool_func(**params)
            except Exception as e:
                result = f"TOOL_RUNTIME_ERROR: {e}"
        else:
            result = f"UNKNOWN_TOOL: {tool_name}"

    return {
        "step": step,
        "tool_used": tool_name,
        "tool_args": params,
        "tool_result": result,
        "raw_llm_suggestion": out,
    }


# ============================================================
# 3. Reflect：对执行结果做反思
# ============================================================

def reflect(step_result: Dict[str, Any]) -> str:
    """
    让 LLM 对刚才的执行结果做自我反思：
    - 是否合理
    - 有无改进
    - 是否需要重试
    """
    prompt = f"""
刚才执行的子任务：{step_result['step']}
工具调用情况：{step_result['tool_used']}，参数：{step_result['tool_args']}
工具返回结果：{step_result['tool_result']}

请你作为一个反思模块，分析：
1）这一步是否执行正确、结果是否合理？
2）是否有明显问题或需要修正的地方？
3）给出简短的反思总结。
"""
    out = call_llm("reflector", prompt)
    return out


# ============================================================
# 4. Verify：整体验证任务是否完成
# ============================================================

def verify(task: str, episode: EpisodeMemory) -> bool:
    """
    让 LLM 扮演“审稿人/审查者”，根据 plan + 中间结果 + 候选答案，
    判断是否满足用户原始任务。
    """
    prompt = f"""
用户原始任务：{task}

执行计划：
{json.dumps(episode.plan, ensure_ascii=False, indent=2)}

中间工具调用与结果：
{json.dumps(episode.tool_calls, ensure_ascii=False, indent=2)}

候选最终答案：
{episode.final_answer}

请你作为一个严格的审查者，判断：
1）这个答案在逻辑上是否自洽、与中间结果是否一致？
2）是否真正回答了用户问题？

请只回答两个字：通过 或 不通过，并在后面用一句简短中文说明理由。
"""
    out = call_llm("verifier", prompt)
    return "通过" in out


# ============================================================
# 5. 主 Agent：Plan → Act → Reflect → Verify → Memory
# ============================================================

def run_agent(task: str, extra_context: Optional[Dict[str, Any]] = None) -> str:
    if extra_context is None:
        extra_context = {}

    episode = EpisodeMemory(task=task)

    # ---- Plan ----
    steps = plan(task, GLOBAL_MEMORY)
    episode.plan = steps
    print("=== 生成的计划 ===")
    for i, s in enumerate(steps, 1):
        print(f"{i}. {s}")

    # ---- Act + Reflect ----
    for step in steps:
        print(f"\n=== 执行子任务：{step} ===")
        step_result = act(step, extra_context)
        episode.tool_calls.append(step_result)
        print("工具结果:", step_result["tool_result"])

        reflection = reflect(step_result)
        episode.reflections.append(reflection)
        print("反思：", reflection)

    # 这里示例：直接取最后一次工具结果作为候选答案（真实工程可让 LLM 再做一个“总结”）
    if episode.tool_calls:
        episode.final_answer = episode.tool_calls[-1]["tool_result"]
    else:
        episode.final_answer = "No result."

    print("\n=== 候选最终答案 ===")
    print(episode.final_answer)

    # ---- Verify ----
    ok = verify(task, episode)
    episode.verified = ok
    print("\n=== 验证结果 ===")
    print("通过" if ok else "不通过")

    # ---- Memory ----
    GLOBAL_MEMORY.add_episode(episode)

    # 如果不通过，你可以在这里再触发：重新规划 / 再执行 / 人类介入
    return episode.final_answer


# ============================================================
# Demo
# ============================================================

if __name__ == "__main__":
    user_task = "如果我有 15 个苹果，吃掉 4 个，然后把剩下的数量乘以 3，最后有多少个？"
    final_answer = run_agent(user_task)

    print("\n=== Agent 给用户的最终回答（示例） ===")
    print(final_answer)

    print("\n=== 当前所有记忆的摘要（JSON） ===")
    print(GLOBAL_MEMORY.summarize())
