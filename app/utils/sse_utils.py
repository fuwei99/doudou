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
    reasoning_content: Optional[str] = None,
    tool_calls: Optional[list] = None
) -> Dict[str, Any]:
    delta = {}
    if content:
        delta["content"] = content
    if reasoning_content:
        delta["reasoning_content"] = reasoning_content
    if tool_calls:
        delta["tool_calls"] = tool_calls
        
    # 如果都为空（比如 finish 时且没有工具调用），至少保留 content 键
    if not delta and not finish_reason:
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
