import json
import re
import sys
import os

# 将项目根目录加入路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.tool_utils import parse_tool_calls_robust, process_messages_for_tools

def test_parsing():
    print("--- 测试解析逻辑 ---")
    bad_xml = """
    好的，我帮你写一个文件。
    <tool_calls>
      <invoke name="write_file">
        <parameter name="path" string="true">hello.py</parameter>
        <parameter name="content" string="true">
print("hello")
        </parameter>
      </invoke>
    </tool_calls>
    """
    results = parse_tool_calls_robust(bad_xml)
    print(f"解析结果: {json.dumps(results, indent=2, ensure_ascii=False)}")
    assert len(results) == 1
    assert results[0]["name"] == "write_file"
    assert "print(\"hello\")" in results[0]["args"]["content"]

    # 测试漏写结束标签的情况
    broken_xml = """
    <tool_calls>
      <invoke name="test_tool">
        <parameter name="p1" string="true">value1
    """
    results2 = parse_tool_calls_robust(broken_xml)
    print(f"容错解析结果: {json.dumps(results2, indent=2, ensure_ascii=False)}")
    assert len(results2) == 1
    assert results2[0]["args"]["p1"] == "value1"

def test_history_alignment():
    print("\n--- 测试历史记录对齐 ---")
    messages = [
        {"role": "user", "content": "帮我查天气"},
        {
            "role": "assistant", 
            "content": "好的", 
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"location": "北京"}'}
                }
            ]
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "晴天"}
    ]
    processed = process_messages_for_tools(messages)
    print(f"处理后消息: {json.dumps(processed, indent=2, ensure_ascii=False)}")
    
    # 验证 assistant 消息被转回 XML
    assert "<tool_calls>" in processed[1]["content"]
    assert "<invoke name=\"get_weather\">" in processed[1]["content"]
    
    # 验证 tool 消息被转为 user
    assert processed[2]["role"] == "user"
    assert "Tool result for call_1" in processed[2]["content"]

if __name__ == "__main__":
    try:
        test_parsing()
        test_history_alignment()
        print("\nAll logic tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
