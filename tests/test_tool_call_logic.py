# tests/test_tool_call_logic.py
import sys
import os
import json

# 将项目根目录加入路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.tool_utils import format_tools_to_system_prompt, parse_tool_calls_robust, convert_tool_calls_to_xml
from app.utils.message_convert import convert_messages_to_prompt

def test_format_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"}
                    }
                }
            }
        }
    ]
    prompt = format_tools_to_system_prompt(tools)
    print("--- Formatted Prompt ---")
    print(prompt)
    assert "<tool_calls>" in prompt
    assert "get_weather" in prompt

def test_parse_robust():
    # 测试 1: 完美 XML
    text1 = """
    好的，我来帮你查一下天气。
    <tool_calls>
    <invoke name="get_weather">
    <parameter name="location" string="true">北京</parameter>
    </invoke>
    </tool_calls>
    """
    res1 = parse_tool_calls_robust(text1)
    print("\n--- Parse Result 1 ---")
    print(json.dumps(res1, indent=2, ensure_ascii=False))
    assert len(res1) == 1
    assert res1[0]["function"]["name"] == "get_weather"
    assert json.loads(res1[0]["function"]["arguments"])["location"] == "北京"

    # 测试 2: 缺失闭合标签且含 JSON 参数
    text2 = """
    <tool_calls>
    <invoke name="calculate">
    <parameter name="nums" string="false">[1, 2, 3]
    """
    res2 = parse_tool_calls_robust(text2)
    print("\n--- Parse Result 2 (Robust) ---")
    print(json.dumps(res2, indent=2, ensure_ascii=False))
    assert len(res2) == 1
    assert res2[0]["function"]["name"] == "calculate"
    assert json.loads(res2[0]["function"]["arguments"])["nums"] == [1, 2, 3]

def test_message_convert():
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "思索中...", "tool_calls": [
            {"function": {"name": "web_search", "arguments": '{"query": "豆包 API"}'}}
        ]},
        {"role": "tool", "tool_call_id": "123", "content": "搜索结果：很好用"}
    ]
    prompt = convert_messages_to_prompt(messages)
    print("\n--- Convert Message Prompt ---")
    print(prompt)
    assert "<tool_calls>" in prompt
    assert "<tool_response" in prompt

if __name__ == "__main__":
    test_format_tools()
    test_parse_robust()
    test_message_convert()
    print("\n✅ All Logic Tests Passed!")
