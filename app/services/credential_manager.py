import threading
import os
import glob
import json
import subprocess
import sys
from typing import List, Dict, Any, Union
from urllib.parse import urlparse, parse_qs
from loguru import logger
from app.core.config import settings

class CredentialManager:
    def __init__(self, env_credentials: List[str]):
        self.index = 0
        self.lock = threading.Lock()
        self._initial_fetch_event = threading.Event()
        
        # 启动同步：整合环境变量、活跃池和黑名单
        self._sync_all_on_startup(env_credentials)
        
        # 统计当前可用数量
        creds = self._load_from_json("cookies.json")
        if not creds:
            logger.warning("未找到任何预设凭证，系统将尝试进入 [零配置启动] 模式。")
            self._check_and_refill(is_initial=True)
        else:
            self._initial_fetch_event.set()
            logger.info(f"凭证管理器已初始化，活跃池共计 {len(creds)} 个凭证。")

    def _load_from_json(self, filename: str) -> List[Dict[str, Any]]:
        """从指定 JSON 文件加载凭证"""
        path = os.path.join(os.getcwd(), filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception as e:
                logger.error(f"读取 {filename} 失败: {e}")
        return []

    def _sync_all_on_startup(self, env_credentials: List[str]):
        """启动时的全量同步与去重逻辑"""
        with self.lock:
            # 1. 收集候选号
            candidates = []
            for c in env_credentials:
                if c.strip(): candidates.append({"cookie": c.strip()})
            for c in self._load_from_directory():
                candidates.append({"cookie": c})
            candidates.extend(self._load_from_env_json())
            
            # 2. 预处理
            processed = [self._augment_with_url_params(c) for c in candidates]
            
            # 3. 加载已有数据实现去重
            invalid_list = self._load_from_json("invaild-cookies.json")
            active_list = self._load_from_json("cookies.json")
            
            invalid_keys = {c["cookie"].strip() for c in invalid_list}
            active_keys = {c["cookie"].strip() for c in active_list}
            
            # 4. 合并新号
            new_added = 0
            for item in processed:
                key = item["cookie"].strip()
                if key not in invalid_keys and key not in active_keys:
                    active_list.append(item)
                    active_keys.add(key)
                    new_added += 1
            
            if new_added > 0:
                self._save_list_to_json(active_list, "cookies.json")
                logger.success(f"启动同步：已从外部导入 {new_added} 个新凭证。")
            else:
                logger.info("启动同步完成：活跃池已是最新的。")

    def _load_from_env_json(self) -> List[Dict[str, Any]]:
        """从环境变量 DOUBAO_COOKIES_JSON 加载"""
        if settings.DOUBAO_COOKIES_JSON:
            try:
                data = json.loads(settings.DOUBAO_COOKIES_JSON)
                if isinstance(data, list): return data
            except Exception as e:
                logger.error(f"解析 DOUBAO_COOKIES_JSON 错误: {e}")
        return []

    def _load_from_directory(self) -> List[str]:
        """从 cookies 目录加载凭证"""
        cookies_dir = os.path.join(os.getcwd(), "cookies")
        if not os.path.exists(cookies_dir):
            os.makedirs(cookies_dir, exist_ok=True)
            return []
        creds = []
        for file_path in glob.glob(os.path.join(cookies_dir, "*.txt")):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content: creds.append(content)
            except Exception: pass
        return creds

    def _augment_with_url_params(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """从 URL 提取指纹"""
        if settings.FORCE_FETCH_URL: return item
        url = item.get("request_url")
        if not url: return item
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            for k, obj_k in {"device_id":"device_id", "fp":"fp", "web_id":"web_id", "tea_uuid":"tea_uuid"}.items():
                if k in params and params[k]: item[obj_k] = params[k][0]
        except Exception: pass
        return item

    def get_credential(self) -> Dict[str, Any]:
        """实时重载物理文件"""
        with self.lock:
            creds = self._load_from_json("cookies.json")
            if not creds:
                self._check_and_refill()
                raise ValueError("未找到可用凭证，系统正在抓取中...")
            self.index %= len(creds)
            return creds[self.index]

    def report_failure(self, permanent: bool = False):
        """上报失败并同步文件"""
        with self.lock:
            creds = self._load_from_json("cookies.json")
            if not creds: return
            self.index %= len(creds)
            if permanent:
                self._move_to_invalid(creds.pop(self.index))
                self._save_list_to_json(creds, "cookies.json")
                if creds: self.index %= len(creds)
            else:
                self.index = (self.index + 1) % len(creds)
            self._check_and_refill()

    def report_success(self, cookie: str):
        """更新使用计数"""
        with self.lock:
            creds = self._load_from_json("cookies.json")
            for cred in creds:
                if cred.get("cookie") == cookie:
                    cred["current_usage"] = cred.get("current_usage", 0) + 1
                    if cred.get("is_anonymous") and cred["current_usage"] >= settings.COOKIE_TIMES:
                        creds.remove(cred)
                    break
            self._save_list_to_json(creds, "cookies.json")
            self._check_and_refill()

    def _move_to_invalid(self, cred: Dict[str, Any]):
        """移至冷宫"""
        data = self._load_from_json("invaild-cookies.json")
        from datetime import datetime
        cred["invalid_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data.append(cred)
        self._save_list_to_json(data, "invaild-cookies.json")
        logger.warning(f"凭证已移至 invaild-cookies.json")

    def _save_list_to_json(self, data: List[Dict[str, Any]], filename: str):
        path = os.path.join(os.getcwd(), filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception: pass

    def _save_to_json(self): pass

    def _check_and_refill(self, is_initial=False):
        """异步补货"""
        if not settings.AUTO_FILL and not is_initial: return
        creds = self._load_from_json("cookies.json")
        if len(creds) < settings.COOKIE_NUM:
            if not settings.AUTO_FILL and is_initial:
                self._initial_fetch_event.set()
                return
            logger.info("触发自动补货抓取...")
            def run():
                env = os.environ.copy()
                env["COOKIE_NUM"] = str(settings.COOKIE_NUM - len(creds))
                subprocess.run([sys.executable, "cookie-fetch.py"], env=env)
                if is_initial: self._initial_fetch_event.set()
            threading.Thread(target=run, daemon=True).start()

    def wait_for_initial_fetch(self, timeout=60):
        return self._initial_fetch_event.wait(timeout=timeout) if not self._initial_fetch_event.is_set() else True

    def update_persistence(self, cookie: str, conversation_id: str, query_id: str):
        with self.lock:
            creds = self._load_from_json("cookies.json")
            for cred in creds:
                if cred.get("cookie") == cookie:
                    cred["pinned_conversation_id"] = conversation_id
                    cred["pinned_query_id"] = query_id
                    self._save_list_to_json(creds, "cookies.json")
                    logger.success(f"持久化绑定完成 ({conversation_id[:8]})")
                    break
