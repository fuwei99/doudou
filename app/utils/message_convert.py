# /app/utils/message_convert.py
import json
from typing import List, Dict, Any

def format_tools_to_system_prompt(tools: list) -> str:
    if not tools:
        return ""
    
    prompt = "## Tools\n\n"
    prompt += "You have access to a set of tools to help answer the user's question. You can invoke tools by writing a \"<tool_calls>\" block like the following:\n\n"
    prompt += "<tool_calls>\n"
    prompt += "<invoke name=\"$TOOL_NAME\">\n"
    prompt += "<parameter name=\"$PARAMETER_NAME\" string=\"true|false\">$PARAMETER_VALUE</parameter>\n"
    prompt += "...\n"
    prompt += "</invoke>\n"
    prompt += "</tool_calls>\n\n"
    
    prompt += "String parameters should be specified as is and set `string=\"true\"`. For all other types (numbers, booleans, arrays, objects), pass the value in JSON format and set `string=\"false\"`.\n\n"
    
    prompt += "If thinking_mode is enabled (triggered by <think>), you MUST output your complete reasoning inside <think>...</think> BEFORE any tool calls or final response.\n\n"
    
    prompt += "Example:\n"
    prompt += "<tool_calls>\n"
    prompt += "<invoke name=\"read\">\n"
    prompt += "<parameter name=\"filePath\" string=\"true\">C:\\Users\\Desktop\\README.md</parameter>\n"
    prompt += "</invoke>\n"
    prompt += "<invoke name=\"write\">\n"
    prompt += "<parameter name=\"filePath\" string=\"true\">C:\\Users\\Desktop\\hello.py</parameter>\n"
    prompt += "<parameter name=\"content\" string=\"true\">\n"
    prompt += "def main():\n"
    prompt += "    print(\"Hello World\")\n"
    prompt += "</parameter>\n"
    prompt += "</invoke>\n"
    prompt += "<invoke name=\"question\">\n"
    prompt += "<parameter name=\"options\" string=\"false\">[\"重构\", \"优化\"]</parameter>\n"
    prompt += "</invoke>\n"
    prompt += "</tool_calls>\n\n"
    
    prompt += "Note: The above examples are for format demonstration only. Please refer to the \"### Available Tool Schemas\" below for the actual tools and their parameter definitions.\n\n"

    prompt += "### Available Tool Schemas\n\n"
    
    for t in tools:
        if t.get("type") == "function":
            func = t.get("function", {})
            prompt += f"#### Tool: `{func.get('name')}`\n"
            prompt += f"Description: {func.get('description', '')}\n"
            prompt += f"Parameters: {json.dumps(func.get('parameters', {}), ensure_ascii=False)}\n\n"
    
    prompt += "[REPRISES]\n"
    prompt += "Remember: You MUST strictly follow the above defined tool calling schema. All tags MUST be closed. DO NOT use markdown blocks for tool calls.\n"
    
    return prompt

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
        
        # 处理 OpenAI 多模态格式 (content 是 list)
        if isinstance(content_raw, list):
            text_parts = [item.get("text", "") for item in content_raw if item.get("type") == "text"]
            content = " ".join(text_parts)
        else:
            content = content_raw or ""
        
        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "assistant":
            # 将历史的 tool_calls 重新格式化为 XML
            if "tool_calls" in msg and msg["tool_calls"]:
                tool_calls_str = "<tool_calls>\n"
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    name = func.get("name")
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str)
                    except:
                        args = {}
                    
                    tool_calls_str += f'<invoke name="{name}">\n'
                    for k, v in args.items():
                        if isinstance(v, str):
                            tool_calls_str += f'<parameter name="{k}" string="true">{v}</parameter>\n'
                        else:
                            tool_calls_str += f'<parameter name="{k}" string="false">{json.dumps(v, ensure_ascii=False)}</parameter>\n'
                    tool_calls_str += "</invoke>\n"
                tool_calls_str += "</tool_calls>"
                
                content = content + "\n" + tool_calls_str if content else tool_calls_str
                
            prompt_parts.append(f"\n\nAssistant: {content}")
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            prompt_parts.append(f"\n\nSystem: [Tool Result for {tool_call_id}]\n{content}")
        elif role == "user":
            prompt_parts.append(f"\n\nHuman: {content}")
        else:
            # 兼容其他角色，视同 User
            prompt_parts.append(f"\n\nHuman: {content}")
            
    return "".join(prompt_parts).strip()
