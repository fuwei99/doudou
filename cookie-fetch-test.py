import asyncio
import time
import json
import os
from playwright.async_api import async_playwright

async def fetch_anonymous_cookie():
    async with async_playwright() as p:
        # 启动浏览器，使用无头模式
        browser = await p.chromium.launch(headless=True)
        # 创建新的上下文，确保是干净的匿名环境
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # 拦截 SSE 响应
        async def handle_response(response):
            if "/chat/completion" in response.url:
                try:
                    text = await response.text()
                    # 尝试从文本中寻找 conversation_id
                    if "conversation_id" in text:
                        print(f"成功拦截到接口响应，含有会话信息！")
                except:
                    pass

        page.on("response", handle_response)

        print("正在访问豆包首页...")
        await page.goto("https://www.doubao.com/", wait_until="networkidle")

        # 等待输入框出现
        input_selector = 'textarea[data-testid="chat_input_input"]'
        await page.wait_for_selector(input_selector)

        print("正在发送初始化消息 'hello'...")
        await page.fill(input_selector, "hello")
        await page.press(input_selector, "Enter")

        # 等待数据返回
        print("等待并拦截会话 ID...")
        await asyncio.sleep(10)

        # 提取所有 Cookies
        cookies_list = await context.cookies()
        # ... 保持之前的逻辑
        cookie_dict = {c['name']: c['value'] for c in cookies_list}
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])

        # 执行 JS 提取 localStorage 和 sessionStorage
        storage_data = await page.evaluate("""() => {
            return {
                local: { ...localStorage },
                session: { ...sessionStorage }
            };
        }""")

        # 尝试从中提取指纹字段
        device_id = cookie_dict.get('device_id')
        fp = cookie_dict.get('fp')
        
        # 扫描 localStorage 中的可能字段 (豆包经常把这些藏在特定 key 里)
        for key, value in storage_data['local'].items():
            if 'device_id' in key and not device_id: device_id = value
            if 'fp' in key and not fp: fp = value
            if 'web_id' in key: web_id = value

        # 构造“全家桶”格式
        credential = {
            "cookie": cookie_str,
            "request_url": page.url,
            "device_id": device_id or "",
            "fp": fp or "",
            "pinned_conversation_id": "",
            "pinned_query_id": ""
        }

        # 从 cookie 列表中提取特定的指纹字段
        for c in cookies_list:
            if c['name'] == 'device_id': credential['device_id'] = c['value']
            if c['name'] == 'fp': credential['fp'] = c['value']
            if c['name'] == 'web_id': credential['web_id'] = c['value']

        print("\n--- 捕获成功 ---")
        print(json.dumps(credential, indent=2, ensure_ascii=False))
        
        # 保存到临时文件供检查
        with open("anonymous_cookies_test.json", "w", encoding="utf-8") as f:
            json.dump([credential], f, indent=2, ensure_ascii=False)
        
        print(f"\n结果已保存至: anonymous_cookies_test.json")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(fetch_anonymous_cookie())
