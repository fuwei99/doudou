# /app/utils/message_convert.py
from typing import List, Dict, Any
from app.utils.tool_utils import convert_tool_calls_to_xml

def convert_messages_to_prompt(messages: List[Dict[str, Any]], add_tool_reminder: bool = False) -> str:
    """
    将 OpenAI 格式的消息体列表转换为单条拼接的字符串。
    add_tool_reminder: 是否在末尾添加工具调用格式提醒（锚点）
    """
    prompt_parts = []
    
    for i, msg in enumerate(messages):
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
            tool_id = msg.get("tool_call_id", "unknown")
            content = f"<tool_response id=\"{tool_id}\">\n{content}\n</tool_response>"

        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "assistant":
            prompt_parts.append(f"\n\nAssistant: {content}")
        elif role == "user":
            # 如果是最后一条 User 消息且需要提醒
            if i == len(messages) - 1 and add_tool_reminder:
                reminder = (
                    "\n\n[TOOLCALL_FORMAT_REMINDER]:\n"
                    "<tool_calls>\n"
                    "  <invoke name=\"tool_name\">\n"
                    "    <parameter name=\"param_name\" string=\"true\">value</parameter>\n"
                    "  </invoke>\n"
                    "</tool_calls>"
                )
                prompt_parts.append(f"\n\nHuman: {content}{reminder}")
            else:
                prompt_parts.append(f"\n\nHuman: {content}")
        elif role == "tool":
            prompt_parts.append(f"\n\nSystem (Tool Result): {content}")
        else:
            prompt_parts.append(f"\n\nHuman: {content}")
            
    return "".join(prompt_parts).strip()
