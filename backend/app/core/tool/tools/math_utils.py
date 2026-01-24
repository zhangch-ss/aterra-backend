from pydantic import BaseModel, Field
from langchain.tools import tool
import ast
import operator


# ==============================
# 1. 参数 Schema（LLM 可见）
# ==============================

class CalculatorInput(BaseModel):
    """Input schema for calculator tool."""
    expression: str = Field(
        ...,
        description=(
            "一个算术表达式字符串，仅允许数字和 + - * / () 运算符，"
            "不允许变量、函数调用或其他 Python 语法。"
            "示例：'3*(15-4)'、'12/(2+4)'"
        ),
        examples=["3*(15-4)", "12/(2+4)"]
    )


# ==============================
# 2. 安全计算逻辑（AST）
# ==============================

_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
}


def safe_eval(expr: str) -> float:
    """Safely evaluate a simple arithmetic expression using AST."""

    def _eval(node):
        if isinstance(node, ast.Constant):  # py >= 3.8
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("仅支持数字常量")

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _ALLOWED_OPERATORS:
                raise ValueError(f"不支持的运算符: {op_type}")
            return _ALLOWED_OPERATORS[op_type](
                _eval(node.left),
                _eval(node.right)
            )

        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _ALLOWED_OPERATORS:
                raise ValueError(f"不支持的一元运算符: {op_type}")
            return _ALLOWED_OPERATORS[op_type](_eval(node.operand))

        raise ValueError("非法表达式结构")

    tree = ast.parse(expr, mode="eval")
    return _eval(tree.body)


# ==============================
# 3. Tool 定义（函数式）
# ==============================

@tool(
    args_schema=CalculatorInput,
    description=(
        "用于执行确定性的算术计算。"
        "当用户明确请求数值计算（尤其是包含括号或多步运算）时使用。"
        "不要用于符号推导、公式解释或自然语言回答。"
    )
)
def calculator(expression: str) -> str:
    """
    Execute a simple arithmetic expression safely.
    """
    try:
        result = safe_eval(expression)
        return str(result)
    except Exception as e:
        return f"ERROR: {e}"
