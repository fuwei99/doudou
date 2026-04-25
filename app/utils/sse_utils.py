# /app/utils/sse_utils.py
import json
import time
from typing import Dict, Any, Optional

DONE_CHUNK = b"data: [DONE]\n\n"

def create_sse_data(data: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode('utf-8')

def create_chat_completion_chunk(
    request_id: str,
    model: str,
    content: str = "",
    finish_reason: Optional[str] = None,
    reasoning_content: Optional[str] = None
) -> Dict[str, Any]:
    delta = {}
    if content:
        delta["content"] = content
    if reasoning_content:
        delta["reasoning_content"] = reasoning_content
    # 如果都为空（比如 finish 时），至少保留 content 键
    if not delta:
        delta["content"] = content
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason
            }
        ]
    }

import re

def parse_tool_calls_robust(text: str):
    """
    鲁棒解析属性化 XML 工具调用。
    断言容错：(?=</invoke>)|(?=</tool_calls>)|$ 允许模型漏写结束标签。
    """
    results = []
    # 支持 <invoke> 和 <|DSML|invoke> 等前缀
    invoke_pattern = re.compile(r'<(?:\|.*?\|)?invoke name=["\']([^"\']+)["\']>(.*?)</(?:\|.*?\|)?invoke>', re.DOTALL)
    
    param_pattern = re.compile(
        r'<(?:\|.*?\|)?parameter name=["\']([^"\']+)["\']\s+string=["\'](true|false)["\']>(.*?)(?:</(?:\|.*?\|)?parameter>|(?=</(?:\|.*?\|)?invoke>)|(?=</(?:\|.*?\|)?tool_calls>)|$)', 
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
                try: args[p_name] = json.loads(p_val)
                except: args[p_name] = p_val
        if tool_name: results.append({"name": tool_name, "args": args})
    return results

def create_tool_call_chunk(
    request_id: str,
    model: str,
    tool_calls: list,
    finish_reason: Optional[str] = None
) -> Dict[str, Any]:
    
    formatted_tool_calls = []
    for i, tc in enumerate(tool_calls):
        formatted_tool_calls.append({
            "index": i,
            "id": f"call_{int(time.time())}_{i}",
            "type": "function",
            "function": {
                "name": tc["name"],
                "arguments": json.dumps(tc["args"], ensure_ascii=False)
            }
        })

    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": formatted_tool_calls
                },
                "finish_reason": finish_reason
            }
        ]
    }

class ToolCallStreamBuffer:
    def __init__(self, tools_enabled: bool):
        self.tools_enabled = tools_enabled
        self.buffer = ""
        self.is_flushed = False

    def process_delta(self, delta: str) -> tuple[str, bool]:
        """
        Returns (content_to_yield, is_buffering)
        """
        if not self.tools_enabled or self.is_flushed:
            return delta, False
        
        self.buffer += delta
        
        target1 = "<tool_calls>"
        target2 = "<|DSML|tool_calls>"
        
        if target1 in self.buffer or target2 in self.buffer:
            return "", True
            
        if len(self.buffer) < 20:
            stripped = self.buffer.strip()
            if not stripped:
                return "", True
            if target1.startswith(stripped) or target2.startswith(stripped) or stripped.startswith("<|DSML"):
                return "", True
        
        self.is_flushed = True
        flushed_content = self.buffer
        self.buffer = ""
        return flushed_content, False

