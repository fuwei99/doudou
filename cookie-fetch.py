import asyncio
import os
import json
import uuid
import subprocess
import sys
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

    captured_url = [None]

    async def handle_response(response):
        if "chat/completion" in response.url and response.status == 200:
            captured_url[0] = response.url

    page.on("response", handle_response)

    wait_time = (settings.LOGIN_WAIT_TIME if settings else 15) * 1000

    try:
        logger.info("正在访问豆包首页获取初始 Session...")
        await page.goto("https://www.doubao.com/", wait_until="networkidle")

        # 等待输入框 — 兼容新旧版 UI 选择器
        input_selectors = [
            'textarea[data-testid="chat_input_input"]',
            'div[contenteditable="true"]',
            "textarea[placeholder]",
            "#chat-input",
            '[class*="chat-input"] textarea',
            '[class*="ChatInput"] textarea',
        ]
        input_el = None
        for sel in input_selectors:
            try:
                input_el = await page.wait_for_selector(sel, timeout=5000)
                if input_el:
                    logger.info(f"找到输入框: {sel}")
                    break
            except Exception:
                continue

        if not input_el:
            # 最后兜底：等久一点试第一个 textarea
            logger.warning("所有预设选择器均未匹配，尝试等待页面上任意 textarea...")
            input_el = await page.wait_for_selector("textarea", timeout=wait_time)

        if not input_el:
            raise Exception("无法找到输入框元素，豆包页面结构可能已更新。")

        await input_el.fill("你好")
        await input_el.press("Enter")

        # 核心等待：为了让豆包后端分配完整的账户/Session 资源
        logger.info("等待 10 秒以激活完整会话状态...")
        await asyncio.sleep(10)

        # 提取全量 Cookie
        cookies_list = await context.cookies()
        if not cookies_list:
            return None, None

        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])

        # 验证关键的 ttwid 或 s_v_web_id 是否存在
        if "ttwid" not in cookie_str and "s_v_web_id" not in cookie_str:
            logger.warning("捕获到的 Cookie 似乎不完整，可能触发了机器人验证")

        return cookie_str, captured_url[0]
    except Exception as e:
        logger.error(f"获取匿名 Cookie 过程出错: {e}")

        if settings and settings.DEBUG:
            logger.info("--- DEBUG 模式：执行诊断操作 ---")
            try:
                # 截图诊断
                screenshot_path = f"debug_timeout_{uuid.uuid4().hex[:6]}.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"已保存调试截图至: {screenshot_path}")

                # Curl 诊断
                logger.info("正在执行 curl -I https://www.doubao.com ...")
                result = subprocess.run(
                    ["curl", "-I", "https://www.doubao.com"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                logger.info(f"Curl 输出:\n{result.stdout}\n{result.stderr}")
            except Exception as debug_e:
                logger.error(f"执行调试诊断时出错: {debug_e}")

        return None, None
    finally:
        await context.close()


async def main():
    # 从环境或默认值读取配置
    default_num = settings.COOKIE_NUM if settings else 3
    default_times = settings.COOKIE_TIMES if settings else 10

    num_to_fetch = int(os.environ.get("COOKIE_NUM", default_num))

    # 代理配置
    proxy = None
    if settings and settings.HTTP_URL:
        proxy = {"server": settings.HTTP_URL.strip()}
        logger.info(f"使用代理抓取: {settings.HTTP_URL}")

    json_path = os.path.join(os.getcwd(), "cookies.json")

    logger.info(f"==== 匿名 Cookie 捕获任务启动 (目标数量: {num_to_fetch}) ====")

    total_added = 0

    def _append_to_json(cred: dict):
        """每抓到一个凭证就立刻追加写入 JSON 文件，让主服务随时能读到。"""
        data = []
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
            except Exception as e:
                logger.warning(f"读取 cookies.json 出错: {e}")
        if not isinstance(data, list):
            data = []
        data.append(cred)
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"写入 cookies.json 失败: {e}")

    async with async_playwright() as p:
        # 使用代理启动浏览器
        browser = await p.chromium.launch(headless=True, proxy=proxy)

        success_count = 0
        fail_count = 0
        while success_count < num_to_fetch and fail_count < 5:
            cookie, url = await fetch_one_cookie(browser)
            if cookie:
                cred = {
                    "cookie": cookie,
                    "request_url": url,
                    "current_usage": 0,
                    "is_anonymous": True,
                    "label": f"anonymous_{uuid.uuid4().hex[:6]}",
                }
                # 立刻写入文件，主服务可以实时读到
                _append_to_json(cred)
                success_count += 1
                total_added += 1
                logger.success(
                    f"成功捕获第 {success_count}/{num_to_fetch} 个匿名凭证 (已实时写入文件)"
                )
            else:
                fail_count += 1
                logger.warning(f"单次捕获失败，已失败 {fail_count} 次")

        await browser.close()

    if total_added == 0:
        logger.error("未能成功捕获到任何有效凭证。")
    else:
        logger.success(
            f"==== 捕获任务完成！共保存 {total_added} 个凭证到 {json_path} ===="
        )


if __name__ == "__main__":
    asyncio.run(main())
