# Web 逆向代理接入 Tool Call 鲁棒性优化技术指南

本文档旨在为开发大模型（LLM）Web 端逆向代理（如将网页版 ChatGPT、Claude、DeepSeek 转换为 OpenAI 标准 API 接口）的开发者，提供一套**极其鲁棒的 Tool Call（工具调用）实现方案**。

## 1. 前置知识：什么是 Tool Call（工具调用）？

**Tool Call**（工具调用，或称 Function Calling）允许大语言模型在对话过程中不再只输出纯文本，而是**格式化地向客户端输出它想要调用的第三方工具名称及所需参数**。

我们在逆向代理后端的 `format_tools_to_system_prompt` 函数中，将客户端传入的 JSON Schema 解析出来，拍扁成纯文本，然后嵌入到系统提示词里。

---

## 2. 核心解法：结构化 XML 属性化设计 (Attribute-Based XML)

### 2.1 传统 JSON 协议的痛点
在网页逆向代理场景中，如果依靠提示词强迫模型直接输出 JSON，很容易遭遇灾难性解析失败：
1. **长文本转义噩梦**：模型极容易在生成代码（含大量 `\` 或 `"`）时忘写转义符。
2. **标签吃漏幻觉**：模型常常丢失 JSON 末尾的闭合符号。

### 2.2 核心解法：XML 属性化协议
我们推荐采用一种更符合模型预训练语料分布的协议，它不再依赖动态标签名，而是使用固定的属性化标签：
* **固定标签名**：使用 `<invoke name="xxx">` 而不是 `<get_weather>`。这避免了参数名与 XML 保留字冲突。
* **显式类型声明 (Type Hinting)**：通过 `string="true|false"` 属性，强制模型区分“纯文本”和“JSON 数据”。

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


## 6. 示例代码（以DeepSeek为例，|DSML|是该模型特性，不必模仿）：
```python
def format_tools_to_system_prompt(tools: list) -> str:
    if not tools:
        return ""
    
    prompt = "## Tools\n\n"
    prompt += "You have access to a set of tools to help answer the user's question. You can invoke tools by writing a \"<|DSML|tool_calls>\" block like the following:\n\n"
    prompt += "<|DSML|tool_calls>\n"
    prompt += "<|DSML|invoke name=\"$TOOL_NAME\">\n"
    prompt += "<|DSML|parameter name=\"$PARAMETER_NAME\" string=\"true|false\">$PARAMETER_VALUE</|DSML|parameter>\n"
    prompt += "...\n"
    prompt += "</|DSML|invoke>\n"
    prompt += "</|DSML|tool_calls>\n\n"
    
    prompt += "String parameters should be specified as is and set `string=\"true\"`. For all other types (numbers, booleans, arrays, objects), pass the value in JSON format and set `string=\"false\"`.\n\n"
    
    prompt += "If thinking_mode is enabled (triggered by <think>), you MUST output your complete reasoning inside <think>...</think> BEFORE any tool calls or final response.\n\n"
    
    prompt += "Example:\n"
    prompt += "<|DSML|tool_calls>\n"
    prompt += "<|DSML|invoke name=\"read\">\n"
    prompt += "<|DSML|parameter name=\"filePath\" string=\"true\">C:\\Users\\zhishang\\Desktop\\README.md</|DSML|parameter>\n"
    prompt += "</|DSML|invoke>\n"
    prompt += "<|DSML|invoke name=\"write\">\n"
    prompt += "<|DSML|parameter name=\"filePath\" string=\"true\">C:\\Users\\zhishang\\Desktop\\hello.py</|DSML|parameter>\n"
    prompt += "<|DSML|parameter name=\"content\" string=\"true\">\n"
    prompt += "def main():\n"
    prompt += "    print(\"Hello World\")\n"
    prompt += "</|DSML|parameter>\n"
    prompt += "</|DSML|invoke>\n"
    prompt += "<|DSML|invoke name=\"question\">\n"
    prompt += "<|DSML|parameter name=\"questions\" string=\"false\">\n"
    prompt += "[\n"
    prompt += "  {\n"
    prompt += "    \"question\": \"你希望按什么方向重写文件？\",\n"
    prompt += "    \"options\": [\"润色\", \"精简\", \"重构\"]\n"
    prompt += "  }\n"
    prompt += "]\n"
    prompt += "</|DSML|parameter>\n"
    prompt += "</|DSML|invoke>\n"
    prompt += "</|DSML|tool_calls>\n\n"
    prompt += "Note: The above examples are for format demonstration only. Please refer to the \"### Available Tool Schemas\" below for the actual tools and their parameter definitions.\n\n"

    prompt += "### Available Tool Schemas\n\n"
    
    for t in tools:
        if t.get("type") == "function":
            func = t.get("function", {})
            prompt += f"#### Tool: `{func.get('name')}`\n"
            prompt += f"Description: {func.get('description', '')}\n"
            prompt += f"Parameters: {json.dumps(func.get('parameters', {}), ensure_ascii=False)}\n\n"
    
    prompt += "[REPRISES]\n"
    prompt += "Remember: You MUST strictly follow the above defined DSML tool calling schema. All tags MUST be closed. DO NOT use markdown blocks for tool calls.\n"
    
    return prompt


``` 