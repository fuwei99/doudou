import sys
import os

# 将项目根目录添加到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.utils.tool_utils import format_tools_to_system_prompt, parse_tool_calls_robust, assemble_openai_tool_calls
from app.utils.message_convert import convert_messages_to_prompt

def test_prompt_generation():
    print("--- 测试提示词生成 ---")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "城市名"}
                    },
                    "required": ["location"]
                }
            }
        }
    ]
    messages = [{"role": "user", "content": "今天北京天气怎么样？"}]
    prompt = convert_messages_to_prompt(messages, tools=tools)
    print(prompt)
    assert "TOOL CALLING PROTOCOL" in prompt
    assert "get_weather" in prompt
    print("Success: Prompt generation test passed")

def test_parsing():
    print("\n--- Testing Parser ---")
    text = """
Ok, let me check.
<tool_calls>
  <invoke name="get_weather">
    <parameter name="location" string="true">Beijing</parameter>
  </invoke>
</tool_calls>
"""
    results = parse_tool_calls_robust(text)
    print(f"Results: {results}")
    assert len(results) == 1
    assert results[0]["name"] == "get_weather"
    assert results[0]["args"]["location"] == "Beijing"
    
    # 测试漏写结束标签的情况 (断言容错)
    text_fault = """
<tool_calls>
  <invoke name="test">
    <parameter name="p1" string="true">hello
  </invoke>
</tool_calls>
"""
    results_fault = parse_tool_calls_robust(text_fault)
    print(f"Fault-tolerant results: {results_fault}")
    assert len(results_fault) == 1
    assert results_fault[0]["args"]["p1"] == "hello"

    print("Success: Parser test passed")

if __name__ == "__main__":
    try:
        test_prompt_generation()
        test_parsing()
        print("\nAll tests passed!")
    except Exception as e:
        print(f"\nFailed: {e}")
        import traceback
        traceback.print_exc()
