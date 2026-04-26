# Web 逆向代理接入 Tool Call 鲁棒性优化技术指南

本文档旨在为开发大模型（LLM）Web 端逆向代理（如将网页版 ChatGPT、Claude、DeepSeek 转换为 OpenAI 标准 API 接口）的开发者，提供一套**极其鲁棒的 Tool Call（工具调用）实现方案**。

## 1. 前置知识：什么是 Tool Call（工具调用）？

**Tool Call**（工具调用，或称 Function Calling）是 OpenAI 率先提出并被业界广泛遵守的一种大模型能力。它允许大语言模型在对话过程中不再只输出纯文本，而是**格式化地向客户端输出它想要调用的第三方工具名称及所需参数**。

例如，当用户问“当前时间是几点？”时，模型本身缺乏实时感知，它会输出类似下面这样标准的 **OpenAI JSON 规范数据**：
```json
{
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "get_time_info",
        "arguments": "{}"  // 注意：此处必须是由有效 JSON 对象序列化而成的字符串
      }
    }
  ]
}
```
你的本地客户端（如 Kilo 或 Cursor）收到上述 JSON 后，在你的电脑上执行获取时间的操作，随后把结果传回给模型，模型再基于结果回答。这就是所谓的 Tool Call，它等于**赋予了大语言模型连接物理世界的手足**。

### 1.1 客户端是如何告诉大模型有哪些工具的？
在 OpenAI 规范中，客户端在发起对话请求时，会通过在 Body 中带上一个 `tools` 数组来把工具列表“注册”给大模型。它的规范强烈依赖于 **JSON Schema** 定义。典型的 `tools` 传入结构如下：

```json
{
  "model": "gpt-4",
  "messages": [ ... ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的当前天气情况",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "城市名称，例如：北京, 上海"
            }
          },
          "required": ["location"]
        }
      }
    }
  ]
}
```
**规范解析：**
* **type**: 目前固定为 `"function"`。
* **name & description**: 工具名称和描述，大模型完全靠阅读这个 `description` 来决定什么时候该调什么工具。
* **parameters**: 这是标准的 **JSON Schema** 语法。通过 `type`, `properties` 和 `required` 约束大模型返回工具参数时的名字和类型。

我们在逆向代理后端的 `format_tools_to_system_prompt` 函数中，做的第一件事就是把这个 JSON Schema 解析出来，拍扁成了纯文本，然后贴在我们的 XML 提示词里给底层大语言模型学习。

**转换后呈现给大模型的样子（示例）：**
```markdown
### AVAILABLE TOOLS

#### Tool: `get_weather`
Description: 获取指定城市的当前天气情况
Parameters: {"type": "object", "properties": {"location": {"type": "string", "description": "城市名称，例如：北京, 上海"}}, "required": ["location"]}
```

---


## 2. 核心痛点与解决思路

### 1.1 传统 JSON 协议的痛点
OpenAI 官方的标准 Tool Call 协议要求大模型直接输出 JSON 格式。在网页逆向代理场景中，如果依靠提示词强迫模型输出 JSON，很容易遭遇灾难性解析失败（`JSONDecodeError`）：
1. **长文本转义噩梦**：当工具被用来生成长段代码（如含有大量 `\` 的 LaTeX 源码、含有 `"` 的 Python 代码）时，模型极容易忘写转义符。
2. **标签吃漏幻觉**：长文本生成导致注意力衰减，模型常常在生成大型嵌套数组（如多项选择题选项）时，丢失末尾的闭合符号。

### 1.2 核心解法：混合协议 (XML 外壳 + JSON 内核)
我们摒弃了纯 JSON 协议的死板，转而采用一种更符合大模型预训练语料分布的混合协议：
* **外壳与普通字段选用 XML**：利用 XML 不需求对内部文本特殊字符进行转义的天然优势，原封不动地包裹长代码。
* **复杂对象降级为 JSON**：对于明确的数组（Array）或对象（Object）参数，在 XML 标签内部强制输出 JSON，便于反序列化。

---

## 3. 提示词工程 (Prompt Engineering) 全流程

### 第一步：构建强约束系统提示词 (System Prompt)
在提示词中定义一套模型必须遵守的“通用协议”：

```markdown
### [CRITICAL] TOOL CALLING PROTOCOL

To invoke tools, you MUST output a `<tool_calls>` block. 
Inside, use `<invoke name="tool_name">` for each tool.
Parameters MUST use: `<parameter name="p_name" string="true|false">value</parameter>`

- Set `string="true"` for raw text (NO escaping needed, perfect for code/scripts).
- Set `string="false"` for arrays, objects, numbers, or booleans (MUST be JSON).
```

### 第二步：增强型 Few-shot 示例
提供覆盖多种数据类型的示例，是保证模型稳定性的关键：

```xml
Example:
<tool_calls>
  <!-- 示例 1: 简单字符串参数 -->
  <invoke name="read_file">
    <parameter name="path" string="true">C:\Users\Desktop\README.md</parameter>
  </invoke>

  <!-- 示例 2: 包含换行和引号的长文本 (无需转义) -->
  <invoke name="write_file">
    <parameter name="path" string="true">C:\Users\Desktop\hello.py</parameter>
    <parameter name="content" string="true">
def main():
    print("Hello, \"World\"!") # 注意：直接写，无需转义
    </parameter>
  </invoke>

  <!-- 示例 3: 复杂的 JSON 数据 -->
  <invoke name="question">
    <parameter name="options" string="false">["重构", "优化"]</parameter>
  </invoke>
</tool_calls>
```

### 第三步：上下文对齐与末尾锚点 (Anchor Reminder)
1. **历史对齐**：确保将会话历史中的 JSON `tool_calls` 也转回上述 XML 格式，保持格式绝对一致。
2. **末尾锚点**：在最后一条 `User` 消息后追加 `[TOOLCALL_FORMAT_REMINDER]`，引导模型立即进入状态。

[TOOLCALL_FORMAT_REMINDER]:
<tool_calls>
  <invoke name="tool_name">
    <parameter name="param_name" string="true">value</parameter>
  </invoke>
</tool_calls>


---

## 4. 后端解析器 (Parser) 健壮性实现

### 4.1 极致容错解析器 (Python)
使用**断言正则**，完美处理模型忘记写闭合标签的情况：

```python
import re
import json

def parse_tool_calls_robust(text: str):
    """
    鲁棒解析属性化 XML 工具调用。
    断言容错：(?=</invoke>)|(?=</tool_calls>)|$ 允许模型漏写结束标签。
    """
    results = []
    # 1. 提取 invoke 块
    invoke_pattern = re.compile(r'<invoke name=["\']([^"\']+)["\']>(.*?)</invoke>', re.DOTALL)
    
    # 2. 提取参数块
    param_pattern = re.compile(
        r'<parameter name=["\']([^"\']+)["\']\s+string=["\'](true|false)["\']>(.*?)(?:</parameter>|(?=</invoke>)|(?=</tool_calls>)|$)', 
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
```

---

## 5. OpenAI 格式兼容装配

最后，将解析所得构造为标准的 OpenAI JSON。注意 `arguments` 必须是序列化后的字符串：

```python
t_args_str = json.dumps(t_args_dict, ensure_ascii=False)
openai_chunk = {
    "tool_calls": [{
        "index": 0,
        "id": f"call_{int(time.time())}",
        "type": "function",
        "function": {"name": t_name, "arguments": t_args_str}
    }]
}
```


## 6. 示例代码：
```python
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


``` 

```历史对齐
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

def process_messages_for_tools(messages: list) -> list:
    """处理带有 tool_calls 和 tool role 的消息（实现 History Alignment）"""
    new_messages = []
    for m in messages:
        msg = dict(m)
        
        # 1. 先统一 content 为字符串，避免多模态 List 格式干扰后续拼接
        if "content" in msg:
            msg["content"] = _content_to_str(msg["content"])
        
        # 2. 如果是 assistant 消息且包含了 tool_calls，将其转回 DSML 格式
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
                
                # 关键步骤：序列化回 DSML XML 格式以提供连贯的上下文
                dsml_call = "\n<|DSML|tool_calls>\n<|DSML|invoke name=\"{}\">\n".format(func.get("name"))
                if isinstance(args, dict):
                    for k, v in args.items():
                        is_str = "true" if isinstance(v, str) else "false"
                        # 处理复杂 JSON 参数或纯文本参数
                        v_str = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                        dsml_call += "  <|DSML|parameter name=\"{0}\" string=\"{1}\">{2}</|DSML|parameter>\n".format(k, is_str, v_str)
                dsml_call += "</|DSML|invoke>\n</|DSML|tool_calls>\n"
                content += dsml_call
            msg["content"] = content.strip()
            
        # 3. 如果是 tool 结果回复（OpenAI 标准），转成 user 角色
        if msg.get("role") == "tool":
            msg["role"] = "user" # 网页版不接受 tool 角色，转换为 user 绕过
            tool_content = _content_to_str(msg.get("content"))
            msg["content"] = f"Tool result for {msg.get('tool_call_id', 'unknown')}:\n{tool_content}"
            
        new_messages.append(msg)
    return new_messages
```