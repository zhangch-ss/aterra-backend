
import re

def strip_json_block(text: str) -> str:
    text = text.strip()
    # 去掉 ```json 或 ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text

if __name__ == "__main__":
    
    text = """
    ```json
    {
    "is_complete": false,
    "need_replan": false,
    "need_react": false,
    "summary": "当前步骤成功完成，需继续执行下一步生成空间分析结论。"
    }

    ```"""

    print(strip_json_block(text))