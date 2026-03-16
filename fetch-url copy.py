# fetch-url.py
import asyncio
import json
import os
import random
import sys
from typing import List, Optional

# 尝试引入配置以支持代理和参数
try:
    # 调整路径以便能够找到 app 模块
    sys.path.append(os.getcwd())
    from app.core.config import settings
except ImportError:
    settings = None

# 如果 settings 导入失败，提供兜底
class FallbackSettings:
    HTTP_URL = None
    LOGIN_WAIT_TIME = 15

if settings is None:
    settings = FallbackSettings()

# 延迟导入，防止环境不全
try:
    from playwright.async_api import async_playwright, Response
    from loguru import logger
except ImportError:
    print("请先安装依赖: pip install playwright loguru && playwright install chromium")
    sys.exit(1)

async def fetch_new_url() -> Optional[str]:
    """使用现有 Cookie 登录并抓取新的 completion URL (Status 200 验证)"""
    logger.info("开始自动抓取 FETCH_URL (模范 cookie-fetch 逻辑)...")
    
    # 1. 加载现有 Cookie
    cookies_path = os.path.join(os.getcwd(), "cookies.json")
    if not os.path.exists(cookies_path):
        logger.error("未找到 cookies.json，无法进行抓取。")
        return None
        
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            creds = json.load(f)
    except Exception as e:
        logger.error(f"读取 cookies.json 失败: {e}")
        return None

    if not creds:
        logger.error("cookies.json 为空。")
        return None

    # 随机选一个号来抓 URL
    cred = random.choice(creds)
    cookie_str = cred["cookie"]
    logger.info(f"正在使用账号 [{cred.get('label', 'unknown')}] 尝试抓取...")

    async with async_playwright() as p:
        # 支持代理
        proxy = None
        if hasattr(settings, "HTTP_URL") and settings.HTTP_URL:
            proxy = {"server": settings.HTTP_URL.strip()}
            logger.info(f"使用代理抓取: {settings.HTTP_URL}")
            
        browser = await p.chromium.launch(headless=False, proxy=proxy) # 强制有头模式
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
        captured_data = {"url": None}
        
        # 响应拦截：必须状态码为 200 才是有效的非限流 URL
        async def handle_response(response: Response):
            if "completion" in response.url and response.status == 200:
                if not captured_data["url"]:
                    captured_data["url"] = response.url
                    logger.success(f"成功截获有效 URL (Status 200): {response.url[:120]}...")

        page.on("response", handle_response)
        
        wait_time_ms = int(getattr(settings, "LOGIN_WAIT_TIME", 15)) * 1000

        try:
            logger.info("正在打开浏览器，请如遇人机验证手动完成...")
            await page.goto("https://www.doubao.com/chat/", timeout=60000)
            
            # 定位输入框
            input_selector = 'textarea[data-testid="chat_input_input"]'
            
            try:
                # 给用户留出过验证码的时间
                await page.wait_for_selector(input_selector, timeout=wait_time_ms)
                
                logger.info("检测到输入框，发送测试指令以触发抓取...")
                await page.fill(input_selector, "你好，请回复。")
                await page.press(input_selector, "Enter")
                
                # 等待截获成功的 response
                logger.info("等待 10 秒以捕获稳定流...")
                await asyncio.sleep(10)
            except Exception as e:
                logger.warning(f"自动触发失败 (可能有人机验证)，请在浏览器中手动发送一条消息: {e}")
                # 如果自动发送失败，持续轮询直到截获成功或超时
                for _ in range(240): # 最多追加等待 120 秒
                    if captured_data["url"]: break
                    await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"抓取过程出错: {e}")
        finally:
            await browser.close()

        final_url = captured_data["url"]
        if final_url:
            save_url_to_pool(final_url)
            return final_url
        else:
            logger.error("抓取失败：未能截获到有效的 Status 200 请求。")
            return None

def save_url_to_pool(url: str):
    pool_path = os.path.join(os.getcwd(), "fetch_url.json")
    pool: List[str] = []
    if os.path.exists(pool_path):
        try:
            with open(pool_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        pool = data
        except: pass
    
    if url not in pool:
        pool.append(url)
        # 限制池大小，防止无限增长
        if len(pool) > 20: 
            pool = pool[len(pool) - 20:]
            
        with open(pool_path, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=4, ensure_ascii=False)
        logger.success(f"指纹已存入池中。当前池大小: {len(pool)}")

async def main():
    print("\n" + "="*50)
    print("      豆包 FETCH_URL (设备指纹) 自动化抓取工具")
    print("="*50)
    print("说明: 本工具将打开浏览器并登录您的账号，通过模拟对话抓取有效的 URL。")
    print("提示: 如果遇到人机验证，请手动在窗口中完成。")
    
    try:
        count_input = input("\n请输入想要抓取的指纹数量 (默认为 1，输入 0 取消): ").strip()
        if count_input == "0": return
        count = int(count_input) if count_input else 1
    except ValueError:
        logger.warning("输入无效，默认抓取 1 个。")
        count = 1

    success_total = 0
    for i in range(count):
        logger.info(f"\n>>> [任务 {i+1}/{count}] 启动中...")
        result = await fetch_new_url()
        if result:
            success_total += 1
            logger.success(f"任务 {i+1} 完成。")
        else:
            logger.error(f"任务 {i+1} 失败。")
        
        if i < count - 1:
            wait_gap = 3
            logger.info(f"等待 {wait_gap} 秒后开始下一个任务...")
            await asyncio.sleep(wait_gap)

    logger.info(f"\n全部任务结束。")
    logger.info(f"总计尝试: {count}")
    logger.success(f"成功保存: {success_total}")
    print("="*50 + "\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] 用户中断。")
    except Exception as e:
        print(f"\n[!] 运行时错误: {e}")
