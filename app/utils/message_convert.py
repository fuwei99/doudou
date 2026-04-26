# /app/utils/message_convert.py
from typing import List, Dict, Any

def convert_messages_to_prompt(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> str:
    """
    将 OpenAI 格式的消息体列表转换为单条拼接的字符串。
    如果提供了 tools，则将工具说明作为系统提示词注入。
    """
    prompt_parts = []
    
    # 注入工具说明
    if tools:
        from app.utils.tool_utils import format_tools_to_system_prompt
        tool_prompt = format_tools_to_system_prompt(tools)
        if tool_prompt:
            prompt_parts.append(f"System: {tool_prompt}")
    
    for msg in messages:
        role = msg.get("role", "user")
        content_raw = msg.get("content", "")
        
        # 处理 OpenAI 多模态格式 (content 是 list)
        if isinstance(content_raw, list):
            text_parts = [item.get("text", "") for item in content_raw if item.get("type") == "text"]
            content = " ".join(text_parts)
        else:
            content = content_raw
        
        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "assistant":
            prompt_parts.append(f"\n\nAssistant: {content}")
        elif role == "user":
            prompt_parts.append(f"\n\nHuman: {content}")
        else:
            # 兼容其他角色，视同 User
            prompt_parts.append(f"\n\nHuman: {content}")
            
    return "".join(prompt_parts).strip()
