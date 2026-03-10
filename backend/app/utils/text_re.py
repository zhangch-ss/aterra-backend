
import re

def strip_json_block(text: str) -> str:
    text = text.strip()
    # 去掉 ```json 或 ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text

if __name__ == "__main__":
    # Example usage for local testing
    sample = """
    ```json
    {
      "ok": true
    }
    ```
    """
    # Avoid stdout noise in production code paths
    cleaned = strip_json_block(sample)
    # Intentionally no print here