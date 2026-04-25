# /app/services/playwright_manager.py
"""
Chrome DevTools Protocol (CDP) 驱动的签名服务管理器。

相较于原先每次启动都用 Playwright 自己拉起无头 Chromium：
- 本版本通过 CDP 连接到本地真实的 Chrome 浏览器；
- 浏览器进程使用持久化的 `user-data-dir` 目录启动，保留 Cookie、缓存、登录态等；
- 如果本地 Chrome 还没开启调试端口，会自动帮你拉起一个，下次复用即可；
- 不需要 playwright-stealth，真实 Chrome 天然具备反检测特性。
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode

import httpx
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    ConsoleMessage,
    TimeoutError,
)
from loguru import logger

from app.core.config import settings


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def _find_chrome_executable() -> Optional[str]:
    """自动探测本机 Chrome 可执行文件路径。"""
    if settings.CHROME_PATH and os.path.exists(settings.CHROME_PATH):
        return settings.CHROME_PATH

    candidates: List[str] = []
    if sys.platform.startswith("win"):
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%ProgramFiles%\Google\Chrome Beta\Application\chrome.exe"
            ),
            # Edge 兜底（走 Chromium 内核，基本兼容）
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
            ),
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """检查指定端口是否已经在监听（即 Chrome 是否已打开调试端口）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def _verify_cdp_ready(port: int) -> bool:
    """验证 CDP 端口确实在响应 DevTools 协议。"""
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"CDP 版本信息: {data.get('Browser', 'unknown')}")
                return True
    except Exception:
        pass
    return False


def handle_console_message(msg: ConsoleMessage):
    """将浏览器控制台日志转发到 Loguru，并过滤已知噪音。"""
    text = msg.text
    if "Failed to load resource" in text or "net::ERR_FAILED" in text:
        return
    if "WebSocket connection" in text or "Content Security Policy" in text:
        return
    if "Scripts may close only the windows that were opened by them" in text:
        return
    if "Ignoring too frequent calls to print()" in text:
        return

    level = msg.type.upper()
    log_message = f"[Browser Console] {text}"
    if level == "ERROR":
        logger.error(log_message)
    elif level == "WARNING":
        logger.warning(log_message)


# ----------------------------------------------------------------------
# PlaywrightManager (CDP 版本)
# ----------------------------------------------------------------------
class PlaywrightManager:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PlaywrightManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    # ------------------------------------------------------------------
    # Chrome 实例管理
    # ------------------------------------------------------------------
    def _spawn_chrome_if_needed(self) -> None:
        """
        如果本机 CHROME_DEBUG_PORT 还没开启，则用持久化的 user-data-dir 启动一个 Chrome。
        已经打开的情况下直接复用，实现"浏览器实例文件储存在本地，不用每次打开新的浏览器"。
        """
        port = settings.CHROME_DEBUG_PORT
        if _is_port_open("127.0.0.1", port):
            logger.info(
                f"检测到本地 Chrome 调试端口 {port} 已就绪，将直接通过 CDP 复用现有实例。"
            )
            self._spawned_process = None
            return

        chrome_path = _find_chrome_executable()
        if not chrome_path:
            raise RuntimeError(
                "未找到本机 Chrome 可执行文件。请安装 Google Chrome，"
                "或在 .env 中设置 CHROME_PATH 指向 chrome.exe。"
            )

        # 持久化目录：相对路径统一解析到项目根
        user_data_dir = Path(settings.CHROME_USER_DATA_DIR)
        if not user_data_dir.is_absolute():
            user_data_dir = Path(os.getcwd()) / user_data_dir
        user_data_dir.mkdir(parents=True, exist_ok=True)

        headless = os.getenv("HEADLESS", "false").lower() == "true"

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-infobars",
            "--disable-features=TranslateUI,OptimizationHints",
            "--disable-blink-features=AutomationControlled",
        ]
        if headless:
            # 使用新版 headless，行为与有头模式最接近
            args.append("--headless=new")

        logger.info(f"本地调试端口 {port} 未开启，正在启动 Chrome...")
        logger.info(f"  - Chrome 路径: {chrome_path}")
        logger.info(f"  - 用户数据目录: {user_data_dir}")
        logger.info(f"  - Headless: {headless}")

        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform.startswith("win"):
            # Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            # 注意 Windows 上 close_fds=True 与 creationflags 不兼容，不传 close_fds
            popen_kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            popen_kwargs["close_fds"] = True

        try:
            self._spawned_process = subprocess.Popen(args, **popen_kwargs)
        except Exception as e:
            raise RuntimeError(f"启动 Chrome 失败: {e}") from e

        # 等端口就绪
        deadline = time.time() + 30
        while time.time() < deadline:
            if _is_port_open("127.0.0.1", port):
                logger.success(f"Chrome 启动成功，CDP 端口 {port} 已就绪。")
                return
            time.sleep(0.3)
        raise RuntimeError(f"启动 Chrome 后 30 秒内 CDP 端口 {port} 仍未就绪。")

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    async def initialize(self, credentials: List[Dict[str, Any]]):
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return

            logger.info("正在初始化 Playwright 管理器 (CDP 模式, 本地 Chrome)...")

            # 1) 确保 Chrome 在跑，用持久化 user-data-dir
            self._spawn_chrome_if_needed()

            # 2) 通过 CDP 连接
            self.playwright = await async_playwright().start()
            await _verify_cdp_ready(settings.CHROME_DEBUG_PORT)
            cdp_endpoint = f"http://127.0.0.1:{settings.CHROME_DEBUG_PORT}"

            try:
                self.browser: Browser = await self.playwright.chromium.connect_over_cdp(
                    cdp_endpoint
                )
            except Exception as e:
                raise RuntimeError(
                    f"通过 CDP 连接本地 Chrome 失败 ({cdp_endpoint}): {e}"
                ) from e

            logger.success(f"已通过 CDP 连接到本地 Chrome: {cdp_endpoint}")

            # 3) 复用或新建 Context + Page
            # connect_over_cdp 情况下 contexts[0] 对应真实用户的默认 context（持久化）
            if self.browser.contexts:
                self.context: BrowserContext = self.browser.contexts[0]
            else:
                self.context = await self.browser.new_context()

            # 尽量复用已打开的、指向豆包的 tab，没有则新开一个
            reuse_page: Optional[Page] = None
            for p in self.context.pages:
                try:
                    if "doubao.com" in (p.url or ""):
                        reuse_page = p
                        break
                except Exception:
                    continue
            if reuse_page is not None:
                self.page = reuse_page
                logger.info(f"复用已打开的豆包 Tab: {self.page.url}")
            else:
                self.page = await self.context.new_page()
                logger.info("已在持久化 Chrome 中新开一个 Tab。")

            self.page.on("console", handle_console_message)

            # 4) 静态指纹 & msToken 初始化
            self.static_device_fingerprint = {
                "device_id": settings.DOUBAO_DEVICE_ID,
                "fp": settings.DOUBAO_FP,
                "web_id": settings.DOUBAO_WEB_ID,
                "tea_uuid": settings.DOUBAO_TEA_UUID,
            }
            logger.success(
                f"已从配置中加载静态设备指纹: {self.static_device_fingerprint}"
            )

            self.ms_token = settings.DOUBAO_MS_TOKEN

            async def _handle_response(response):
                try:
                    if "x-ms-token" in response.headers:
                        token = response.headers["x-ms-token"]
                        if token and token != self.ms_token:
                            self.ms_token = token
                            logger.success(
                                f"通过响应头捕获到新的 msToken: {self.ms_token[:24]}..."
                            )
                except Exception as e:
                    logger.warning(f"处理响应时出错: {e} (URL: {response.url})")

            self.page.on("response", _handle_response)

            # 4.5) 拦截 Chrome 真实请求，从 URL 参数中提取设备指纹（最可靠的方式）
            self._captured_live_fingerprint: Dict[str, str] = {}

            def _handle_request(request):
                """从 Chrome 发出的真实 doubao 请求中提取 URL 参数里的指纹。"""
                try:
                    url = request.url or ""
                    if "doubao.com" in url and ("device_id=" in url or "fp=" in url):
                        from urllib.parse import urlparse, parse_qs

                        parsed = urlparse(url)
                        params = parse_qs(parsed.query)
                        changed = False
                        for k in ["device_id", "fp", "web_id", "tea_uuid"]:
                            if k in params and params[k] and params[k][0]:
                                old = self._captured_live_fingerprint.get(k)
                                if old != params[k][0]:
                                    self._captured_live_fingerprint[k] = params[k][0]
                                    changed = True
                        if changed:
                            logger.success(
                                f"从 Chrome 真实请求中捕获到设备指纹: {self._captured_live_fingerprint}"
                            )
                except Exception:
                    pass

            self.page.on("request", _handle_request)

            # 5) 注入 Cookie（如果调用方传了）
            if credentials:
                initial_cookie_str = credentials[0].get("cookie", "")
                if initial_cookie_str:
                    try:
                        cookie_list = [
                            {
                                "name": c.split("=")[0].strip(),
                                "value": c.split("=", 1)[1].strip(),
                                "domain": ".doubao.com",
                                "path": "/",
                            }
                            for c in initial_cookie_str.split(";")
                            if "=" in c
                        ]
                        await self.context.add_cookies(cookie_list)
                        logger.success("初始 Cookie 已注入到持久化 Context。")
                    except Exception as e:
                        logger.warning(
                            f"注入 Cookie 失败（忽略继续，持久化 Context 可能已登录）: {e}"
                        )
            else:
                logger.info(
                    "未提供预设凭证，直接使用持久化 Context 中已有的登录态（如果有）。"
                )

            # 6) 导航并等签名函数就绪
            try:
                need_nav = "doubao.com" not in (self.page.url or "")
                if need_nav:
                    logger.info("正在导航到豆包聊天页以加载签名脚本 (超时 60s)...")
                    await self.page.goto(
                        "https://www.doubao.com/chat/",
                        wait_until="load",
                        timeout=60000,
                    )
                else:
                    logger.info("当前 Tab 已在豆包域，跳过导航。")
            except TimeoutError:
                try:
                    await self.page.screenshot(path="debug_timeout_goto.png")
                except Exception:
                    pass
                raise RuntimeError("无法访问豆包官网，初始化失败。")

            try:
                logger.info("等待签名函数 window.bdms.frontierSign 就绪 (超时 30s)...")
                await self.page.wait_for_function(
                    """() => !!(window.bdms && typeof window.bdms.frontierSign === 'function')""",
                    timeout=30000,
                )
                logger.success("关键签名函数已就绪！")
            except TimeoutError:
                try:
                    diag = await self.page.evaluate(
                        """() => ({
                            has_bdms: !!window.bdms,
                            url: window.location.href,
                            is_login: !!document.querySelector('.login-container, .auth-form')
                        })"""
                    )
                    logger.error(f"等待签名函数超时！诊断: {json.dumps(diag)}")
                    await self.page.screenshot(path="debug_timeout_sign.png")
                    if diag.get("is_login"):
                        raise RuntimeError(
                            "检测到跳转到了登录页面，请在该 Chrome 窗口中手动登录豆包，"
                            "登录态会被保存到 CHROME_USER_DATA_DIR，下次自动复用。"
                        )
                except Exception:
                    pass
                raise RuntimeError(
                    "无法加载豆包签名函数，请在弹出的 Chrome 窗口中确认是否进入聊天页。"
                )

            # 7) 从 Chrome 页面中动态提取真实设备指纹
            #    核心策略：先等请求拦截器捕获，再用 JS 从 localStorage/Cookie 补漏

            # 7a) 等一下看看请求拦截器有没有抓到指纹（导航时可能已经触发了 API 请求）
            if not self._captured_live_fingerprint:
                logger.info("等待 Chrome 真实请求中的指纹参数 (最长 5 秒)...")
                for _ in range(10):
                    await asyncio.sleep(0.5)
                    if self._captured_live_fingerprint:
                        break

            # 7b) 如果拦截器没抓到完整指纹，用 JS 从页面全方位补充提取
            try:
                live_fp = await self.page.evaluate("""
                    () => {
                        const result = {};
                        try {
                            // 从 Cookie 提取
                            const cookies = document.cookie.split(';').reduce((acc, c) => {
                                const [k, ...v] = c.trim().split('=');
                                acc[k] = v.join('=');
                                return acc;
                            }, {});
                            
                            if (cookies['s_v_web_id']) result.fp = cookies['s_v_web_id'];
                            if (cookies['msToken']) result.msToken = cookies['msToken'];
                            
                            // 从 localStorage 暴力搜索所有 key
                            for (let i = 0; i < localStorage.length; i++) {
                                const key = localStorage.key(i);
                                const val = localStorage.getItem(key);
                                if (!val) continue;
                                
                                // 尝试 JSON 解析 (tea SDK 存储格式)
                                try {
                                    const obj = JSON.parse(val);
                                    if (obj && typeof obj === 'object') {
                                        if (obj.user_unique_id && !result.web_id) {
                                            result.web_id = String(obj.user_unique_id);
                                            result.tea_uuid = String(obj.user_unique_id);
                                        }
                                        if (obj.web_id && !result.web_id) {
                                            result.web_id = String(obj.web_id);
                                        }
                                        if (obj.device_id && !result.device_id) {
                                            result.device_id = String(obj.device_id);
                                        }
                                    }
                                } catch(e) {
                                    // 纯字符串值
                                    if (key === 'device_id' || key === '__device_id') result.device_id = val;
                                    if (key === 'verify_fp' || key === 's_v_web_id') result.fp = val;
                                    if (key === 'web_id' || key === 'user_id') result.web_id = val;
                                    if (key === 'tea_uuid') result.tea_uuid = val;
                                }
                            }
                        } catch(e) {
                            result.error = e.message;
                        }
                        return result;
                    }
                """)
                logger.info(
                    f"JS 提取到的指纹: {json.dumps(live_fp, ensure_ascii=False)}"
                )
            except Exception as e:
                logger.warning(f"JS 指纹提取失败: {e}")
                live_fp = {}

            # 7c) 合并：请求拦截 > JS 提取 > 静态配置（优先级递减）
            merged_fp = {}
            for k in ["device_id", "fp", "web_id", "tea_uuid"]:
                merged_fp[k] = (
                    self._captured_live_fingerprint.get(k)
                    or live_fp.get(k)
                    or self.static_device_fingerprint.get(k)
                    or ""
                )
            self.static_device_fingerprint = merged_fp

            if live_fp.get("msToken") and not self.ms_token:
                self.ms_token = live_fp["msToken"]
                logger.success(f"从 Cookie 提取到 msToken: {self.ms_token[:24]}...")

            # 标记是否成功提取到了 CDP 动态指纹（供外部判断优先级）
            self.has_live_fingerprint = bool(self._captured_live_fingerprint)

            logger.success(f"最终使用的设备指纹: {self.static_device_fingerprint}")
            if self.has_live_fingerprint:
                logger.success("指纹来源: Chrome 真实请求拦截 (最高可信度)")
            else:
                logger.warning("未能从真实请求中捕获指纹，使用 JS/静态兜底")

            if not self.ms_token:
                logger.info("等待 msToken 出现，最长 10 秒...")
                await asyncio.sleep(10)
                if not self.ms_token:
                    logger.warning("仍未捕获到初始 msToken，后续请求将依赖响应头更新。")

            logger.success("Playwright 管理器 (CDP 模式) 初始化完成。")
            self._initialized = True

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def update_ms_token(self, token: str):
        self.ms_token = token

    async def get_signed_url(
        self, base_url: str, cookie: str, base_params: Dict[str, str]
    ) -> Optional[str]:
        async with self._lock:
            if not self._initialized:
                raise RuntimeError("PlaywrightManager 未初始化。")

            try:
                logger.info("正在使用本地 Chrome 生成 a_bogus 签名...")
                final_params = base_params.copy()

                # 指纹合并：优先使用传入的，缺失的用静态兜底
                for k, v in self.static_device_fingerprint.items():
                    if k not in final_params or not final_params[k]:
                        final_params[k] = v

                if "web_tab_id" not in final_params:
                    final_params["web_tab_id"] = str(uuid.uuid4())

                if self.ms_token:
                    final_params["msToken"] = self.ms_token
                else:
                    logger.error("msToken 未初始化，无法构建有效请求！")
                    return None

                sorted_params = dict(sorted(final_params.items()))
                final_query_string = urlencode(sorted_params)
                url_with_params = f"{base_url}?{final_query_string}"

                # 用 arg 方式传字符串，避免 f-string 拼接时特殊字符转义问题
                signature_obj = await self.page.evaluate(
                    "(qs) => window.bdms.frontierSign(qs)",
                    final_query_string,
                )

                if isinstance(signature_obj, dict) and (
                    "a_bogus" in signature_obj or "X-Bogus" in signature_obj
                ):
                    bogus_value = signature_obj.get("a_bogus") or signature_obj.get(
                        "X-Bogus"
                    )
                    logger.success(f"签名成功，a_bogus: {bogus_value[:24]}...")
                    return f"{url_with_params}&a_bogus={bogus_value}"
                else:
                    logger.error(f"签名函数返回异常: {signature_obj}")
                    return None

            except Exception as e:
                logger.error(f"签名时发生错误: {e}", exc_info=True)
                return None

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------
    async def close(self):
        """
        关闭时只断开 CDP 连接、不要关闭用户的本地 Chrome。
        这样下次服务再启动可以秒级复用现有 Chrome 实例。
        如果是我们自己 spawn 出来的 Chrome，也保留（方便下次复用持久化目录），
        除非用户在 .env 中设置 CHROME_KILL_ON_EXIT=true（此处未暴露，默认不关）。
        """
        if not self._initialized:
            return
        async with self._lock:
            try:
                if getattr(self, "browser", None):
                    try:
                        await self.browser.close()
                    except Exception:
                        pass
                if getattr(self, "playwright", None):
                    await self.playwright.stop()
            finally:
                self._initialized = False
                logger.info(
                    "Playwright 管理器已断开 CDP 连接（本地 Chrome 保留运行）。"
                )
