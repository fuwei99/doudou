# /app/utils/message_convert.py
from typing import List, Dict, Any
from app.utils.tool_utils import convert_tool_calls_to_xml

def convert_messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    将 OpenAI 格式的消息体列表转换为单条拼接的字符串。
    格式:
    System: xxxx
    Assistant: xxx
    Human: xxx
    """
    prompt_parts = []
    
    for msg in messages:
        role = msg.get("role", "user")
        content_raw = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        
        # 处理 OpenAI 多模态格式 (content 是 list)
        if isinstance(content_raw, list):
            text_parts = [item.get("text", "") for item in content_raw if item.get("type") == "text"]
            content = " ".join(text_parts)
        else:
            content = content_raw
        
        # 处理 Assistant 的 Tool Calls
        if role == "assistant" and tool_calls:
            xml_tool_calls = convert_tool_calls_to_xml(tool_calls)
            if content:
                content = f"{content}\n\n{xml_tool_calls}"
            else:
                content = xml_tool_calls

        # 处理 Tool 响应
        if role == "tool":
            # 将工具响应包裹在 XML 中，方便模型识别
            tool_id = msg.get("tool_call_id", "unknown")
            content = f"<tool_response id=\"{tool_id}\">\n{content}\n</tool_response>"

        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "assistant":
            prompt_parts.append(f"\n\nAssistant: {content}")
        elif role == "user":
            prompt_parts.append(f"\n\nHuman: {content}")
        elif role == "tool":
            # 工具响应通常紧跟在 Assistant 之后，作为上下文的一部分送入
            prompt_parts.append(f"\n\nSystem (Tool Result): {content}")
        else:
            # 兼容其他角色，视同 User
            prompt_parts.append(f"\n\nHuman: {content}")
            
    return "".join(prompt_parts).strip()
