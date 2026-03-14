import threading
import os
import glob
import json
from typing import List, Dict, Any, Union
from urllib.parse import urlparse, parse_qs
from loguru import logger
from app.core.config import settings

class CredentialManager:
    def __init__(self, env_credentials: List[str]):
        # 加载所有可能的凭证，统一格式为 Dict
        self.credentials = self._load_all_credentials(env_credentials)
        
        self.index = 0
        self.failure_count = 0 
        self.lock = threading.Lock()
        self._initial_fetch_event = threading.Event()
        
        if not self.credentials:
            logger.warning("未找到任何预设凭证，系统将尝试进入 [零配置启动] 模式。")
            # 立即触发补货，并设置事件在完成后通知
            self._check_and_refill(is_initial=True)
        else:
            self._initial_fetch_event.set() # 已有凭证，无需等待
            logger.info(f"凭证管理器已初始化，共加载 {len(self.credentials)} 个设备套件。")

    def _load_all_credentials(self, env_credentials: List[str]) -> List[Dict[str, Any]]:
        """合并所有来源的凭证并标准化"""
        standard_creds = []
        
        # 1. 从环境变量加载并标准化
        for c in env_credentials:
            if c.strip():
                standard_creds.append({"cookie": c.strip()})
        
        # 2. 从 cookies 目录加载
        for c in self._load_from_directory():
            standard_creds.append({"cookie": c})

        # 3. 从环境变量 DOUBAO_COOKIES_JSON 加载
        env_json_creds = self._load_from_env_json()
        standard_creds.extend([self._augment_with_url_params(c) for c in env_json_creds])

        # 4. 从 cookies.json 加载 (全家桶模式)
        json_creds = self._load_from_json()
        standard_creds.extend([self._augment_with_url_params(c) for c in json_creds])
        
        # 高级去重逻辑
        dedup_map = {}
        
        for item in standard_creds:
            cookie_key = item["cookie"].strip()
            item["cookie"] = cookie_key # 顺便统一清洗
            
            if cookie_key not in dedup_map:
                dedup_map[cookie_key] = item
            else:
                # 优先级竞争逻辑 (得分制)
                existing = dedup_map[cookie_key]
                
                def get_score(cred):
                    score = 0
                    if cred.get("pinned_conversation_id"): score += 100  # 有固定 ID 最牛
                    if cred.get("fp"): score += 10                     # 有环境指纹次之
                    if cred.get("request_url"): score += 1             # 有原始 URL 再次之
                    return score

                if get_score(item) > get_score(existing):
                    dedup_map[cookie_key] = item
                    logger.debug(f"凭证去重：发现更完整的凭证版本，已替换。")
        
        return list(dedup_map.values())

    def _load_from_env_json(self) -> List[Dict[str, Any]]:
        """从环境变量 DOUBAO_COOKIES_JSON 加载"""
        if settings.DOUBAO_COOKIES_JSON:
            try:
                data = json.loads(settings.DOUBAO_COOKIES_JSON)
                if isinstance(data, list):
                    logger.info(f"从环境变量 DOUBAO_COOKIES_JSON 加载了 {len(data)} 个全家桶凭证。")
                    return data
            except Exception as e:
                logger.error(f"解析环境变量 DOUBAO_COOKIES_JSON 失败: {e}")
        return []

    def _load_from_json(self) -> List[Dict[str, Any]]:
        """从 cookies.json 加载"""
        json_path = os.path.join(os.getcwd(), "cookies.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logger.info(f"从 cookies.json 加载了 {len(data)} 个全家桶凭证。")
                        return data
            except Exception as e:
                logger.error(f"读取 cookies.json 失败: {e}")
        return []

    def _load_from_directory(self) -> List[str]:
        """从 cookies 目录加载凭证"""
        cookies_dir = os.path.join(os.getcwd(), "cookies")
        if not os.path.exists(cookies_dir):
            os.makedirs(cookies_dir, exist_ok=True)
            logger.info(f"创建了 cookies 目录: {cookies_dir}")
            return []

        creds = []
        txt_files = glob.glob(os.path.join(cookies_dir, "*.txt"))
        for file_path in txt_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        creds.append(content)
                        logger.info(f"从文件加载了 Cookie: {os.path.basename(file_path)}")
            except Exception as e:
                logger.error(f"读取 Cookie 文件失败 {file_path}: {e}")
        
        return creds

    def _augment_with_url_params(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """如果提供了 request_url，自动从中解析指纹参数"""
        url = item.get("request_url")
        if not url:
            return item
            
        try:
            parsed_url = urlparse(url)
            params = parse_qs(parsed_url.query)
            
            # 自动映射关键字段
            mappings = {
                "device_id": "device_id",
                "fp": "fp",
                "web_id": "web_id",
                "tea_uuid": "tea_uuid",
                "msToken": "msToken"
            }
            
            extracted_count = 0
            for param_key, obj_key in mappings.items():
                if param_key in params and params[param_key]:
                    # 如果原对象里没有，或者 URL 里的更新，则填充
                    val = params[param_key][0]
                    if val:
                        item[obj_key] = val
                        extracted_count += 1
            
            if extracted_count > 0:
                logger.success(f"自动从 request_url 中提取了 {extracted_count} 个指纹参数。")
                
        except Exception as e:
            logger.warning(f"从 request_url 解析参数失败: {e}")
            
        return item

    def get_credential(self) -> Dict[str, Any]:
        """获取当前正在使用的设备凭证 (锁定当前账号)"""
        with self.lock:
            if not self.credentials:
                # 尝试触发紧急补充
                self._check_and_refill()
                raise ValueError("当前没有可用的凭证，系统正在自动获取中，请稍后重试。")
                
            cred = self.credentials[self.index]
            logger.debug(f"当前使用凭据索引: [{self.index}/{len(self.credentials)-1}]")
            return cred

    def report_failure(self):
        """上报当前凭证失败。如果失败，立即切换到下一个，实现'故障切换'。"""
        with self.lock:
            old_index = self.index
            self.index = (self.index + 1) % len(self.credentials)
            logger.warning(f"凭证索引 {old_index} 确认失效，故障切换到索引: {self.index}")

    def report_success(self, cookie: str):
        """成功时重置失败计数，并增加使用次数计数"""
        with self.lock:
            if self.failure_count > 0:
                self.failure_count = 0
            
            # 找到对应的凭据并增加计数
            target_cred = None
            for cred in self.credentials:
                if cred.get("cookie") == cookie:
                    target_cred = cred
                    break
            
            if target_cred:
                # 只有匿名账号才执行自动淘汰逻辑
                current = target_cred.get("current_usage", 0) + 1
                target_cred["current_usage"] = current
                
                # 直接获取全局配置的使用寿命上限
                max_u = settings.COOKIE_TIMES
                
                if target_cred.get("is_anonymous") and current >= max_u:
                    logger.warning(f"匿名凭证使用次数已达上限 ({current}/{max_u})，正在准备淘汰并补充...")
                    self.credentials.remove(target_cred)
                    # 索引重置防止越界
                    if self.index >= len(self.credentials) and len(self.credentials) > 0:
                        self.index = 0
                    
                    # 触发异步补充
                    self._check_and_refill()

    def _check_and_refill(self, is_initial=False):
        """检查是否需要补充匿名 Cookie"""
        cookie_num = settings.COOKIE_NUM
        if len(self.credentials) < cookie_num:
            logger.info(f"当前剩余凭证 ({len(self.credentials)}) 低于设定阈值 ({cookie_num})，触发自动抓取...")
            import subprocess
            import sys
            try:
                needed = cookie_num - len(self.credentials)
                env = os.environ.copy()
                env["COOKIE_NUM"] = str(needed)
                env["COOKIE_TIMES"] = str(settings.COOKIE_TIMES)
                
                def run_fetch():
                    result = subprocess.run([sys.executable, "cookie-fetch.py"], env=env)
                    if result.returncode == 0:
                        new_json_creds = self._load_from_json()
                        with self.lock:
                            existing_cookies = {c["cookie"] for c in self.credentials}
                            added_count = 0
                            for item in new_json_creds:
                                if item["cookie"] not in existing_cookies:
                                    self.credentials.append(item)
                                    added_count += 1
                            logger.success(f"补货任务完成，成功导入 {added_count} 个新凭证。")
                    else:
                        logger.error("补货脚本运行失败。")
                    
                    if is_initial:
                        self._initial_fetch_event.set()
                
                threading.Thread(target=run_fetch, daemon=True).start()
            except Exception as e:
                logger.error(f"启动补货任务失败: {e}")
                if is_initial: self._initial_fetch_event.set()

    def wait_for_initial_fetch(self, timeout=60):
        """阻塞等待第一次抓取完成"""
        if not self._initial_fetch_event.is_set():
            logger.info(f"正在等待初始凭证捕获 (限时 {timeout}s)...")
            return self._initial_fetch_event.wait(timeout=timeout)
        return True

    def update_persistence(self, cookie: str, conversation_id: str, query_id: str):
        """将捕获到的固定对话 ID 和查询 ID 回写到本地持久化存储中"""
        with self.lock:
            # 1. 更新内存状态 (确保内存里是最新的，这样下次请求即便不重启也能用)
            target_cred = None
            for cred in self.credentials:
                if cred.get("cookie") == cookie:
                    cred["pinned_conversation_id"] = conversation_id
                    cred["pinned_query_id"] = query_id
                    target_cred = cred
                    break
            
            if not target_cred:
                logger.warning("内存凭据列表中未发现匹配的 Cookie，放弃持久化。")
                return

            # 2. 持久化到 JSON 文件
            json_path = os.path.join(os.getcwd(), "cookies.json")
            try:
                data = []
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if content:
                                data = json.loads(content)
                    except Exception as e:
                        logger.warning(f"读取旧的 cookies.json 出错，将尝试备份覆盖: {e}")
                
                if not isinstance(data, list):
                    data = []

                # 寻找匹配项并更新
                found_in_file = False
                for item in data:
                    # 匹配逻辑：优先用 cookie 字符串匹配，兼容性更好
                    orig_cookie = target_cred.get("cookie", "").strip()
                    if item.get("cookie") == orig_cookie:
                        item["pinned_conversation_id"] = conversation_id
                        item["pinned_query_id"] = query_id
                        # 顺便同步指纹，防止 .env 里的指纹没存进 json
                        for key in ["device_id", "fp", "web_id", "tea_uuid"]:
                            if target_cred.get(key):
                                item[key] = target_cred[key]
                        found_in_file = True
                        break
                
                if not found_in_file:
                    # 如果文件中没有（说明是来自 .env 的），则将内存中的完整对象（含指纹和固定ID）存入文件
                    new_item = target_cred.copy()
                    data.append(new_item)
                    logger.info("已将环境变量中的凭证正式固化到 cookies.json 文件中。")
                
                # 显式尝试新建文件并写入
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                logger.success(f"持久化成功! 永久 ID 已绑定 (Conv: {conversation_id[:8]})")
                
            except Exception as e:
                logger.error(f"回写持久化文件失败: {e}")
