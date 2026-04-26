import re
import json
import time
from typing import List, Dict, Any

def format_tools_to_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """将 OpenAI tools 转换为系统提示词中的 XML 协议说明"""
    if not tools:
        return ""
    
    prompt = "\n\n## Tools\n\n"
    prompt += "You have access to a set of tools to help answer the user's question. You can invoke tools by writing a \"<tool_calls>\" block like the following:\n\n"
    prompt += "<tool_calls>\n"
    prompt += "<invoke name=\"$TOOL_NAME\">\n"
    prompt += "<parameter name=\"$PARAMETER_NAME\" string=\"true|false\">$PARAMETER_VALUE</parameter>\n"
    prompt += "...\n"
    prompt += "</invoke>\n"
    prompt += "</tool_calls>\n\n"
    
    prompt += "String parameters should be specified as is and set `string=\"true\"`. For all other types (numbers, booleans, arrays, objects), pass the value in JSON format and set `string=\"false\"`.\n\n"
    
    prompt += "Example:\n"
    prompt += "<tool_calls>\n"
    prompt += "<invoke name=\"read\">\n"
    prompt += "<parameter name=\"filePath\" string=\"true\">C:\\Users\\zhishang\\Desktop\\README.md</parameter>\n"
    prompt += "</invoke>\n"
    prompt += "<invoke name=\"write\">\n"
    prompt += "<parameter name=\"filePath\" string=\"true\">C:\\Users\\zhishang\\Desktop\\hello.py</parameter>\n"
    prompt += "<parameter name=\"content\" string=\"true\">\n"
    prompt += "def main():\n"
    prompt += "    print(\"Hello World\")\n"
    prompt += "</parameter>\n"
    prompt += "</invoke>\n"
    prompt += "<invoke name=\"question\">\n"
    prompt += "<parameter name=\"questions\" string=\"false\">\n"
    prompt += "[\n"
    prompt += "  {\n"
    prompt += "    \"question\": \"你希望按什么方向重写文件？\",\n"
    prompt += "    \"options\": [\"润色\", \"精简\", \"重构\"]\n"
    prompt += "  }\n"
    prompt += "]\n"
    prompt += "</parameter>\n"
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
    prompt += "[TOOLCALL_FORMAT_REMINDER]:\n<tool_calls>\n  <invoke name=\"tool_name\">\n    <parameter name=\"param_name\" string=\"true\">value</parameter>\n  </invoke>\n</tool_calls>\n"
    
    return prompt

def _content_to_str(content) -> str:
    """将 content 统一转换为字符串（兼容 OpenAI 多模态 list 格式）"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    parts.append(block.get("content", ""))
                else:
                    parts.append(str(block))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)

def process_messages_for_tools(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """处理带有 tool_calls 和 tool role 的消息（实现 History Alignment）"""
    new_messages = []
    for m in messages:
        msg = dict(m)
        
        # 1. 先统一 content 为字符串
        if "content" in msg:
            msg["content"] = _content_to_str(msg["content"])
        
        # 2. 如果是 assistant 消息且包含了 tool_calls，将其转回 XML 格式
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            content = msg.get("content") or ""
            for tc in msg.get("tool_calls"):
                func = tc.get("function", {})
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        pass
                
                # 序列化回 XML 格式
                xml_call = "\n<tool_calls>\n<invoke name=\"{}\">\n".format(func.get("name"))
                if isinstance(args, dict):
                    for k, v in args.items():
                        is_str = "true" if isinstance(v, str) else "false"
                        v_str = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                        xml_call += "  <parameter name=\"{0}\" string=\"{1}\">{2}</parameter>\n".format(k, is_str, v_str)
                xml_call += "</invoke>\n</tool_calls>\n"
                content += xml_call
            msg["content"] = content.strip()
            
        # 3. 如果是 tool 结果回复（OpenAI 标准），转成 user 角色
        if msg.get("role") == "tool":
            msg["role"] = "user"
            tool_content = _content_to_str(msg.get("content"))
            msg["content"] = f"Tool result for {msg.get('tool_call_id', 'unknown')}:\n{tool_content}"
            
        new_messages.append(msg)
    return new_messages

def parse_tool_calls_robust(text: str) -> List[Dict[str, Any]]:
    """
    鲁棒解析 XML 工具调用。
    断言容错：(?=</invoke>)|(?=</tool_calls>)|$ 允许模型漏写结束标签。
    """
    results = []
    # 1. 提取 invoke 块
    invoke_pattern = re.compile(r'<invoke name=["\']([^"\']+)["\']>(.*?)</invoke>', re.DOTALL)
    # 如果模型没写 </invoke>，也尝试提取内容直到下一个标签或结尾
    if not invoke_pattern.search(text):
        invoke_pattern = re.compile(r'<invoke name=["\']([^"\']+)["\']>(.*?)(?=<invoke|$)', re.DOTALL)
    
    # 2. 提取参数块
    param_pattern = re.compile(
        r'<parameter name=["\']([^"\']+)["\']\s+string=["\'](true|false)["\']>(.*?)(?:</parameter>|(?=<parameter)|(?=</invoke>)|(?=</tool_calls>)|$)', 
        re.DOTALL
    )

    for inv_match in invoke_pattern.finditer(text):
        tool_name = inv_match.group(1).strip()
        args = {}
        for pm in param_pattern.finditer(inv_match.group(2)):
            p_name, is_string, p_val = pm.group(1).strip(), pm.group(2).lower() == "true", pm.group(3).strip()
            if is_string:
                args[p_name] = p_val
            else:
                try: 
                    args[p_name] = json.loads(p_val)
                except: 
                    args[p_name] = p_val
        if tool_name: 
            results.append({"name": tool_name, "args": args})
    return results
