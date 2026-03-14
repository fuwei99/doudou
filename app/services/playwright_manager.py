# /app/services/playwright_manager.py
import asyncio
import json
import uuid
import os
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode, urlparse

from playwright_stealth import stealth_async
from playwright.async_api import async_playwright, Browser, Page, ConsoleMessage, TimeoutError, Route, Request
from loguru import logger

from app.core.config import settings # 导入 settings

def handle_console_message(msg: ConsoleMessage):
    """将浏览器控制台日志转发到 Loguru，并过滤已知噪音"""
    log_level = msg.type.upper()
    text = msg.text
    # 过滤掉常见的、无害的浏览器噪音
    if "Failed to load resource" in text or "net::ERR_FAILED" in text:
        return
    if "WebSocket connection" in text:
        return
    if "Content Security Policy" in text:
        return
    if "Scripts may close only the windows that were opened by them" in text:
        return
    if "Ignoring too frequent calls to print()" in text:
        return

    log_message = f"[Browser Console] {text}"
    if log_level == "ERROR":
        logger.error(log_message)
    elif log_level == "WARNING":
        logger.warning(log_message)
    else:
        pass

class PlaywrightManager:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PlaywrightManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    async def initialize(self, credentials: List[Dict[str, Any]]):
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            logger.info("正在初始化 Playwright 管理器 (签名服务模式)...")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=os.getenv("HEADLESS", "true").lower() == "true",
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            self.page = await self.browser.new_page()

            await stealth_async(self.page)
            self.page.on("console", handle_console_message)
            await self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            self.static_device_fingerprint = {
                'device_id': settings.DOUBAO_DEVICE_ID,
                'fp': settings.DOUBAO_FP,
                'web_id': settings.DOUBAO_WEB_ID,
                'tea_uuid': settings.DOUBAO_TEA_UUID
            }
            logger.success(f"已从配置中加载静态设备指纹: {self.static_device_fingerprint}")
            
            self.ms_token = None

            async def _handle_response(response):
                try:
                    if 'x-ms-token' in response.headers:
                        token = response.headers['x-ms-token']
                        if token != self.ms_token:
                            self.ms_token = token
                            logger.success(f"通过响应头捕获到新的 msToken: {self.ms_token}")
                except Exception as e:
                    logger.warning(f"处理响应时出错: {e} (URL: {response.url})")

            self.page.on("response", _handle_response)

            if not credentials:
                logger.warning("初始化时未提供预设凭证，将进入匿名待命状态。")
                self.initialized = True
                return
            
            logger.info("正在为初始页面加载设置 Cookie...")
            # 从第一个凭证对象中提取 cookie 字符串
            initial_cred = credentials[0]
            initial_cookie_str = initial_cred.get("cookie", "")
            
            try:
                cookie_list = [
                    {"name": c.split('=')[0].strip(), "value": c.split('=', 1)[1].strip(), "domain": ".doubao.com", "path": "/"}
                    for c in initial_cookie_str.split(';') if '=' in c
                ]
                await self.page.context.add_cookies(cookie_list)
                logger.success("初始 Cookie 设置完成。")
            except Exception as e:
                logger.error(f"解析 Cookie 时出错: '{initial_cookie_str[:50]}...'. 错误: {e}")
                raise ValueError("Cookie 格式无效，无法进行初始化。") from e

            try:
                logger.info("正在导航到豆包官网以加载签名脚本 (超时时间: 60秒)...")
                await self.page.goto(
                    "https://www.doubao.com/chat/",
                    wait_until="load",
                    timeout=60000
                )
                logger.info("页面导航完成 (load 事件触发)。")
            except TimeoutError as e:
                logger.error(f"导航到豆包官网超时: {e}")
                # 尝试在此处截图帮助诊断
                await self.page.screenshot(path="debug_timeout_goto.png")
                logger.info("已保存导航超时截图到 debug_timeout_goto.png")
                raise RuntimeError("无法访问豆包官网，初始化失败。") from e

            try:
                logger.info("正在等待豆包页面完全加载并注入签名脚本 (超时时间: 30秒)...")
                
                # 增强探测：检测 window 对象的变化
                await self.page.wait_for_function("""
                    () => {
                        // 1. 检查 acrawler 是否由于某种原因被挂载到了其他地方或者还未加载
                        if (window.bdms && typeof window.bdms.frontierSign === 'function') return true;
                        
                        // 2. 尝试触发一些可能触发脚本加载的动作 (可选，但此处由于在聊天页，一般会自动加载)
                        return false;
                    }
                """, timeout=30000)
                logger.success("关键签名函数已成功捕获！")
                
                # 核心改进：如果没有配置静态指纹，尝试从当前页面动态提取，或者在找不到时回退
                current_fingerprint = await self.page.evaluate("""
                    () => {
                        try {
                            // 尝试从本地存储或全局变量中提取
                            return {
                                device_id: localStorage.getItem('device_id') || '',
                                fp: localStorage.getItem('verify_fp') || '',
                                web_id: localStorage.getItem('user_id') || ''
                            };
                        } catch(e) { return {}; }
                    }
                """)
                if current_fingerprint.get('fp') and not settings.DOUBAO_FP:
                    logger.info(f"动态提取到页面指纹: {current_fingerprint}")
            
            except TimeoutError:
                # 获取更详细的诊断信息
                diag = await self.page.evaluate("""
                    () => {
                        let res = { 
                            has_acrawler: !!window.bdms,
                            url: window.location.href,
                            is_login: !!document.querySelector('.login-container, .auth-form')
                        };
                        if (window.bdms) {
                            res.keys = Object.keys(window.bdms);
                        }
                        return res;
                    }
                """)
                logger.error(f"等待签名函数超时！诊断信息: {json.dumps(diag)}")
                await self.page.screenshot(path="debug_timeout_sign.png")
                
                # 如果是登录页，说明 Cookie 完全失效
                if diag.get('is_login'):
                    raise RuntimeError("检测到跳转到了登录页面，说明您的 Cookie 已彻底失效，请重新抓包并更新 DOUBAO_COOKIE_1。")
                
                raise RuntimeError("无法加载豆包签名函数。请观察弹出的浏览器窗口，确认是否正常进入了聊天页面。")
            
            if not self.ms_token:
                logger.info("等待 msToken 出现，最长等待 10 秒...")
                await asyncio.sleep(10)
                if not self.ms_token:
                    logger.warning("在额外等待后，依然未能捕获到初始 msToken。后续请求将依赖响应头更新。")

            logger.success("Playwright 管理器 (签名服务模式) 初始化完成。")
            self._initialized = True

    def update_ms_token(self, token: str):
        self.ms_token = token

    async def get_signed_url(self, base_url: str, cookie: str, base_params: Dict[str, str]) -> Optional[str]:
        async with self._lock:
            if not self._initialized:
                raise RuntimeError("PlaywrightManager 未初始化。")
            
            try:
                logger.info("正在使用 Playwright 生成 a_bogus 签名...")
                
                final_params = base_params.copy()
                
                # 指纹合并逻辑：优先使用传入的指纹，缺失才用默认的
                for k, v in self.static_device_fingerprint.items():
                    if k not in final_params or not final_params[k]:
                        final_params[k] = v
                
                if 'web_tab_id' not in final_params:
                    final_params['web_tab_id'] = str(uuid.uuid4())
                    
                if self.ms_token:
                    # 始终同步 Playwright 侧捕获的最新的 msToken，这对成功生成 a_bogus 至关重要
                    final_params['msToken'] = self.ms_token
                else:
                    logger.error("msToken 未被初始化，无法构建有效请求！")
                    return None

                # --- 核心修复: 对参数进行字母排序，以生成正确的签名 ---
                sorted_params = dict(sorted(final_params.items()))
                final_query_string = urlencode(sorted_params)
                url_with_params = f"{base_url}?{final_query_string}"

                logger.info(f"正在使用设备指纹和排序后的参数调用 window.bdms.frontierSign: \"{final_query_string}\"")
                signature_obj = await self.page.evaluate(f'window.bdms.frontierSign("{final_query_string}")')
                
                if isinstance(signature_obj, dict) and ('a_bogus' in signature_obj or 'X-Bogus' in signature_obj):
                    bogus_value = signature_obj.get('a_bogus') or signature_obj.get('X-Bogus')
                    logger.success(f"成功解析签名对象，获取到 a_bogus: {bogus_value}")
                    
                    signed_url = f"{url_with_params}&a_bogus={bogus_value}"
                    return signed_url
                else:
                    logger.error(f"调用签名函数失败，返回值不是预期的字典格式或缺少 a_bogus: {signature_obj}")
                    return None

            except Exception as e:
                logger.error(f"Playwright 签名时发生严重错误: {e}", exc_info=True)
                return None

    async def close(self):
        if self._initialized:
            async with self._lock:
                if self.browser:
                    await self.browser.close()
                if self.playwright:
                    await self.playwright.stop()
                self._initialized = False
                logger.info("Playwright 管理器已关闭。")
