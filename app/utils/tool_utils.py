# /app/utils/tool_utils.py
import re
import json
import time
from typing import List, Dict, Any

def format_tools_to_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """
    将 OpenAI JSON Schema 工具列表转换为增强版系统提示词 (XML 协议)。
    参考 toocall__instruction.md 实现。
    """
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
    
    return prompt

def parse_tool_calls_robust(text: str) -> List[Dict[str, Any]]:
    """
    鲁棒解析属性化 XML 工具调用。
    断言容错：(?=</invoke>)|(?=</tool_calls>)|$ 允许模型漏写结束标签。
    """
    results = []
    # 1. 提取 invoke 块
    invoke_pattern = re.compile(r'<invoke name=["\']([^"\']+)["\']>(.*?)(?:</invoke>|(?=</tool_calls>)|$)', re.DOTALL)
    
    # 2. 提取参数块
    param_pattern = re.compile(
        r'<parameter name=["\']([^"\']+)["\']\s+string=["\'](true|false)["\']>(.*?)(?:</parameter>|(?=</invoke>)|(?=</tool_calls>)|$)', 
        re.DOTALL
    )

    for inv_match in invoke_pattern.finditer(text):
        tool_name = inv_match.group(1).strip()
        raw_params_content = inv_match.group(2)
        args = {}
        for pm in param_pattern.finditer(raw_params_content):
            p_name = pm.group(1).strip()
            is_string = pm.group(2).lower() == "true"
            p_val = pm.group(3).strip()
            
            if is_string:
                args[p_name] = p_val
            else:
                try:
                    args[p_name] = json.loads(p_val)
                except:
                    args[p_name] = p_val
        
        if tool_name:
            # 转换为 OpenAI 格式需要的结构
            results.append({
                "id": f"call_{int(time.time() * 1000)}{len(results)}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args, ensure_ascii=False)
                }
            })
    return results

def convert_tool_calls_to_xml(tool_calls: List[Dict[str, Any]]) -> str:
    """
    将消息历史中的 OpenAI tool_calls 转回 XML 格式。
    用于保持上下文一致性。
    """
    if not tool_calls:
        return ""
    
    xml_parts = ["<tool_calls>"]
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name")
        args_str = func.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except:
            args = {}
        
        xml_parts.append(f"<invoke name=\"{name}\">")
        for p_name, p_val in args.items():
            if isinstance(p_val, str):
                xml_parts.append(f"<parameter name=\"{p_name}\" string=\"true\">{p_val}</parameter>")
            else:
                xml_parts.append(f"<parameter name=\"{p_name}\" string=\"false\">{json.dumps(p_val, ensure_ascii=False)}</parameter>")
        xml_parts.append("</invoke>")
    xml_parts.append("</tool_calls>")
    
    return "\n".join(xml_parts)
