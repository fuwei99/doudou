# /app/utils/tool_utils.py
import re
import json
import time
from typing import List, Dict, Any

def format_tools_to_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """
    将 OpenAI 格式的 tools 列表转换为嵌入系统提示词的 XML 属性化协议说明。
    参考 DSML 风格。
    """
    if not tools:
        return ""
    
    prompt = "\n\n### [CRITICAL] TOOL CALLING PROTOCOL\n\n"
    prompt += "You have access to a set of tools. To invoke tools, you MUST output a `<tool_calls>` block.\n"
    prompt += "Inside, use `<invoke name=\"tool_name\">` for each tool.\n"
    prompt += "Parameters MUST use: `<parameter name=\"p_name\" string=\"true|false\">value</parameter>`\n\n"
    
    prompt += "- Set `string=\"true\"` for raw text (NO escaping needed, perfect for code/scripts).\n"
    prompt += "- Set `string=\"false\"` for arrays, objects, numbers, or booleans (MUST be JSON).\n\n"
    
    prompt += "Example:\n"
    prompt += "<tool_calls>\n"
    prompt += "  <invoke name=\"read_file\">\n"
    prompt += "    <parameter name=\"path\" string=\"true\">C:\\Users\\Desktop\\README.md</parameter>\n"
    prompt += "  </invoke>\n"
    prompt += "  <invoke name=\"question\">\n"
    prompt += "    <parameter name=\"options\" string=\"false\">[\"重构\", \"优化\"]</parameter>\n"
    prompt += "  </invoke>\n"
    prompt += "</tool_calls>\n\n"

    prompt += "### Available Tool Schemas\n\n"
    
    for t in tools:
        if t.get("type") == "function":
            func = t.get("function", {})
            prompt += f"#### Tool: `{func.get('name')}`\n"
            prompt += f"Description: {func.get('description', '')}\n"
            prompt += f"Parameters: {json.dumps(func.get('parameters', {}), ensure_ascii=False)}\n\n"
    
    prompt += "Remember: You MUST strictly follow the above defined tool calling schema. All tags MUST be closed. DO NOT use markdown blocks for tool calls.\n"
    
    return prompt

def parse_tool_calls_robust(text: str) -> List[Dict[str, Any]]:
    """
    使用正则表达式鲁棒地从模型输出中提取工具调用。
    支持断言容错，处理模型漏写结束标签的情况。
    """
    results = []
    
    # 1. 提取 invoke 块
    # 匹配 <invoke name="...">
    invoke_pattern = re.compile(r'<invoke name=["\']([^"\']+)["\']>(.*?)(?:</invoke>|(?=<invoke)|(?=</tool_calls>)|$)', re.DOTALL)
    
    # 2. 提取参数块
    param_pattern = re.compile(
        r'<parameter name=["\']([^"\']+)["\']\s+string=["\'](true|false)["\']>(.*?)(?:</parameter>|(?=<parameter)|(?=</invoke>)|(?=</tool_calls>)|$)', 
        re.DOTALL
    )

    for inv_match in invoke_pattern.finditer(text):
        tool_name = inv_match.group(1).strip()
        args_str = inv_match.group(2)
        args = {}
        
        for pm in param_pattern.finditer(args_str):
            p_name = pm.group(1).strip()
            is_string = pm.group(2).lower() == "true"
            p_val = pm.group(3).strip()
            
            if is_string:
                args[p_name] = p_val
            else:
                try:
                    args[p_name] = json.loads(p_val)
                except:
                    # 容错：如果 JSON 解析失败，保留原样
                    args[p_name] = p_val
        
        if tool_name:
            results.append({
                "name": tool_name,
                "args": args
            })
            
    return results

def assemble_openai_tool_calls(parsed_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将解析出的工具调用转换为 OpenAI 标准格式。
    """
    tool_calls = []
    for i, call in enumerate(parsed_calls):
        tool_calls.append({
            "index": i,
            "id": f"call_{int(time.time())}_{i}",
            "type": "function",
            "function": {
                "name": call["name"],
                "arguments": json.dumps(call["args"], ensure_ascii=False)
            }
        })
    return tool_calls
