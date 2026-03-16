# fetch-url.py
import asyncio
import json
import os
import random
import uuid
from playwright.async_api import async_playwright
from loguru import logger

# 引入配置以支持代理
try:
    from app.core.config import settings
except ImportError:
    settings = None

async def fetch_new_url():
    """使用现有 Cookie 登录并抓取新的 completion URL (Status 200 验证)"""
    logger.info("开始自动抓取 FETCH_URL (模范 cookie-fetch 逻辑)...")
    
    # 1. 加载现有 Cookie
    cookies_path = os.path.join(os.getcwd(), "cookies.json")
    if not os.path.exists(cookies_path):
        logger.error("未找到 cookies.json，无法进行抓取。")
        return
        
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            creds = json.load(f)
    except Exception as e:
        logger.error(f"读取 cookies.json 失败: {e}")
        return

    if not creds:
        logger.error("cookies.json 为空。")
        return

    # 随机选一个号来抓 URL
    cred = random.choice(creds)
    cookie_str = cred["cookie"]
    logger.info(f"正在使用账号 [{cred.get('label', 'unknown')}] 尝试抓取...")

    async with async_playwright() as p:
        # 允许通过 HTTP_URL 走代理
        proxy = None
        if settings and settings.HTTP_URL:
            proxy = {"server": settings.HTTP_URL.strip()}
            logger.info(f"使用代理抓取: {settings.HTTP_URL}")
            
        browser = await p.chromium.launch(headless=False, proxy=proxy) # 有头模式
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # 注入 Cookie
        cookie_list = []
        for item in cookie_str.split(";"):
            if "=" in item:
                parts = item.strip().split("=", 1)
                if len(parts) == 2:
                    k, v = parts
                    cookie_list.append({"name": k, "value": v, "domain": ".doubao.com", "path": "/"})
        await context.add_cookies(cookie_list)
        
        page = await context.new_page()
        captured_url = [None]
        
        # 响应拦截：必须状态码为 200 才是有效的非限流 URL
        async def handle_response(response):
            if "completion" in response.url and response.status == 200:
                if not captured_url[0]:
                    captured_url[0] = response.url
                    logger.success(f"成功截获有效 URL (Status 200): {response.url[:120]}...")

        page.on("response", handle_response)
        
        wait_time = (settings.LOGIN_WAIT_TIME if settings else 15) * 1000

        try:
            logger.info("正在打开浏览器，请如遇人机验证手动完成...")
            await page.goto("https://www.doubao.com/chat/", timeout=60000)
            
            # 定位输入框
            input_selector = 'textarea[data-testid="chat_input_input"]'
            
            try:
                # 等待输入框出现，给用户留出过验证码的时间
                await page.wait_for_selector(input_selector, timeout=wait_time)
                
                logger.info("检测到输入框，发送指令...")
                await page.fill(input_selector, "你好")
                await page.press(input_selector, "Enter")
                
                # 核心等待：留出时间让消息发出并截获成功的 response
                logger.info("等待 10 秒以捕获稳定会话...")
                await asyncio.sleep(10)
            except Exception as e:
                logger.warning(f"自动发送流程未完全成功 (可能是验证码拦截)，请手动发送一条消息: {e}")
                # 如果自动发送失败，多等一段时间留给用户手动发
                for _ in range(120): # 最多等 60 秒
                    if captured_url[0]: break
                    await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"抓取过程出错: {e}")
        finally:
            await browser.close()

        if captured_url[0]:
            save_url_to_pool(captured_url[0])
            return captured_url[0]
        else:
            logger.error("抓取失败：未能截获到有效的 Status 200 请求。")

def save_url_to_pool(url):
    pool_path = os.path.join(os.getcwd(), "fetch_url.json")
    pool = []
    if os.path.exists(pool_path):
        try:
            with open(pool_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    pool = json.loads(content)
        except: pass
    
    if not isinstance(pool, list): pool = []

    if url not in pool:
        pool.append(url)
        if len(pool) > 20: pool = pool[-20:]
            
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=4, ensure_ascii=False)
        logger.success(f"有效指纹已存入池中。当前池大小: {len(pool)}")

async def main():
    print("\n" + "="*40)
    print("      豆包 FETCH_URL 交互抓取工具")
    print("="*40)
    
    try:
        count_input = input("\n请输入想要抓取的指纹数量 (默认为 1): ").strip()
        count = int(count_input) if count_input else 1
    except ValueError:
        logger.warning("输入无效，将默认抓取 1 个。")
        count = 1

    success_total = 0
    for i in range(count):
        logger.info(f"\n>>> 正在进行第 {i+1}/{count} 次抓取任务...")
        result = await fetch_new_url()
        if result:
            success_total += 1
            logger.success(f"第 {i+1} 次抓取成功。")
        else:
            logger.error(f"第 {i+1} 次抓取失败。")
        
        if i < count - 1:
            logger.info("准备进入下一次抓取，建议您等待页面完全关闭后再继续...")
            await asyncio.sleep(2)

    logger.info(f"\n任务结束。总计尝试: {count}, 成功: {success_total}")
    print("="*40 + "\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户取消任务。")
