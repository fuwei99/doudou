import asyncio
import os
import json
import uuid
from playwright.async_api import async_playwright
from loguru import logger
try:
    from app.core.config import settings
except ImportError:
    settings = None

async def fetch_one_cookie(browser):
    """
    启动一个干净的情境获取一个匿名 Cookie
    """
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    page = await context.new_page()
    try:
        logger.info("正在访问豆包首页获取初始 Session...")
        await page.goto("https://www.doubao.com/", wait_until="networkidle")
        
        # 等待并输入指令
        input_selector = 'textarea[data-testid="chat_input_input"]'
        await page.wait_for_selector(input_selector, timeout=15000)
        
        await page.fill(input_selector, "你好")
        await page.press(input_selector, "Enter")
        
        # 核心等待：为了让豆包后端分配完整的账户/Session 资源
        logger.info("等待 10 秒以激活完整会话状态...")
        await asyncio.sleep(10)
        
        # 提取全量 Cookie
        cookies_list = await context.cookies()
        if not cookies_list:
            return None
            
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
        
        # 验证关键的 ttwid 或 s_v_web_id 是否存在
        if "ttwid" not in cookie_str and "s_v_web_id" not in cookie_str:
            logger.warning("捕获到的 Cookie 似乎不完整，可能触发了机器人验证")
            
        return cookie_str
    except Exception as e:
        logger.error(f"获取匿名 Cookie 过程出错: {e}")
        return None
    finally:
        await context.close()

async def main():
    # 从环境或默认值读取配置
    default_num = settings.COOKIE_NUM if settings else 3
    default_times = settings.COOKIE_TIMES if settings else 10
    
    num_to_fetch = int(os.environ.get("COOKIE_NUM", default_num))
    cookie_times = int(os.environ.get("COOKIE_TIMES", default_times))
    
    json_path = os.path.join(os.getcwd(), "cookies.json")
    
    logger.info(f"==== 匿名 Cookie 捕获任务启动 (目标数量: {num_to_fetch}) ====")
    
    new_creds = []
    
    async with async_playwright() as p:
        # 建议使用 headless=True 提高效率，除非需要调试
        browser = await p.chromium.launch(headless=True)
        
        success_count = 0
        fail_count = 0
        while success_count < num_to_fetch and fail_count < 5:
            cookie = await fetch_one_cookie(browser)
            if cookie:
                new_creds.append({
                    "cookie": cookie,
                    "current_usage": 0,
                    "is_anonymous": True,
                    "label": f"anonymous_{uuid.uuid4().hex[:6]}"
                })
                success_count += 1
                logger.success(f"成功捕获第 {success_count}/{num_to_fetch} 个匿名凭证")
            else:
                fail_count += 1
                logger.warning(f"单次捕获失败，已失败 {fail_count} 次")
        
        await browser.close()

    if not new_creds:
        logger.error("未能成功捕获到任何有效凭证。")
        return

    # 持久化逻辑：追加或创建
    data = []
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
        except Exception as e:
            logger.warning(f"读取旧 cookies.json 出错: {e}")

    if not isinstance(data, list):
        data = []
        
    data.extend(new_creds)
    
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.success(f"==== 捕获任务完成！已保存 {len(new_creds)} 个凭证到 {json_path} ====")
    except Exception as e:
        logger.error(f"持久化到 JSON 失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
