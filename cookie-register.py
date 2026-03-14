# cookie-register.py
import asyncio
import json
import uuid
import os
import re
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from loguru import logger

# 配置
TARGET_FILE = "cookies-avi.json"
DOUBAO_URL = "https://www.doubao.com/"

async def register_one():
    async with async_playwright() as p:
        # 启动有头浏览器
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)

        captured_data = {
            "conversation_id": None,
            "query_id": None,
            "request_url": None
        }

        # 监听 SSE 响应
        async def handle_response(response):
            if "chat/completion" in response.url and response.status == 200:
                try:
                    # 记录完整的请求 URL，以便主程序自动解析指纹
                    if not captured_data["request_url"]:
                        captured_data["request_url"] = response.url

                    # 读取流式内容解析 ID
                    body = await response.text()
                    # 寻找 conversation_id
                    conv_match = re.search(r'"conversation_id":"(\d+)"', body)
                    if conv_match:
                        captured_data["conversation_id"] = conv_match.group(1)
                    
                    # 寻找第一个 question_id (这也是 pinned_query_id)
                    query_match = re.search(r'"question_id":"(\d+)"', body)
                    if query_match:
                        captured_data["query_id"] = query_match.group(1)
                        logger.success(f"成功捕获永久 ID: Conv={captured_data['conversation_id']}, Query={captured_data['query_id']}")
                except:
                    pass

        page.on("response", handle_response)

        logger.info("正在打开豆包官网，请稍候...")
        await page.goto(DOUBAO_URL)
        
        # 等待输入框出现
        try:
            input_selector = 'textarea[data-testid="chat_input_input"]'
            await page.wait_for_selector(input_selector, timeout=20000)
            
            logger.info("正在发送激活消息以捕获 SSE ID...")
            await page.fill(input_selector, "hello")
            await page.keyboard.press("Enter")
            
            # 额外等待一段时间，确保 SSE 完整返回
            for _ in range(15):
                if captured_data["conversation_id"] and captured_data["query_id"]:
                    break
                await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"操作超时或失败: {e}")

        # 提取最终 Cookie
        cookies = await context.cookies()
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        if captured_data["conversation_id"] and captured_data["query_id"]:
            new_item = {
                "cookie": cookie_str,
                "request_url": captured_data["request_url"],
                "pinned_conversation_id": captured_data["conversation_id"],
                "pinned_query_id": captured_data["query_id"],
                "is_anonymous": True,
                "current_usage": 0,
                "label": f"expert_{uuid.uuid4().hex[:6]}"
            }

            # 保存到文件
            data = []
            if os.path.exists(TARGET_FILE):
                with open(TARGET_FILE, "r", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except: data = []
            
            data.append(new_item)
            with open(TARGET_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            logger.success(f"注册成功！凭证已存入 {TARGET_FILE}")
        else:
            logger.error("未能在 SSE 中捕获到必要的 ID，注册失败。")

        await browser.close()

if __name__ == "__main__":
    print("\n" + "="*50)
    print("      豆包 [无限编辑模式] 批量注册工具")
    print("="*50 + "\n")
    
    try:
        count_str = input("请输入您想要注册的 Cookie 数量 (默认 1): ").strip()
        count = int(count_str) if count_str else 1
    except ValueError:
        count = 1
        
    logger.info(f"即将开始批量注册任务，目标数量: {count}\n")
    
    for i in range(count):
        logger.info(f"--- 正在执行第 {i+1}/{count} 个注册任务 ---")
        asyncio.run(register_one())
        if i < count - 1:
            logger.info("任务间歇，等待 3 秒后继续...")
            import time
            time.sleep(3)
            
    print("\n" + "="*50)
    print(f"恭喜！所有任务已完成。请查看 {TARGET_FILE}")
    print("="*50 + "\n")
