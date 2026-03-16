import threading
import os
import glob
import json
import subprocess
import sys
from typing import List, Dict, Any, Union, Optional
from urllib.parse import urlparse, parse_qs
from loguru import logger
from app.core.config import settings

class CredentialManager:
    def __init__(self, env_credentials: List[str]):
        self.index = 0
        self.lock = threading.RLock()  # 使用递归锁，防止 report_failure 嵌套调用 rotate_fingerprint 时死锁
        self._initial_fetch_event = threading.Event()
        
        # 指纹池管理
        self.fingerprint_pool: List[str] = []
        self.current_fp_url: Optional[str] = None
        self._load_fingerprints()
        
        # 启动同步：整合环境变量、活跃池和黑名单
        self._sync_all_on_startup(env_credentials)
        
        # 统计当前可用数量
        creds = self._load_from_json("cookies.json")
        if not creds:
            logger.warning("未找到任何可用凭证，请确保 cookies.json 存在或已配置环境变量。")
        
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

    def _load_fingerprints(self):
        """加载指纹池"""
        path = os.path.join(os.getcwd(), "fetch_url.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.fingerprint_pool = json.load(f)
                    if self.fingerprint_pool:
                        self.current_fp_url = self.fingerprint_pool[0]
                        logger.info(f"成功加载指纹池，共 {len(self.fingerprint_pool)} 个指纹。")
            except Exception as e:
                logger.error(f"加载指纹池失败: {e}")
        
        # 兜底：如果池为空但环境变量有设置，则使用环境变量的指纹
        if not self.current_fp_url and settings.DOUBAO_FETCH_URL:
            self.current_fp_url = settings.DOUBAO_FETCH_URL
            logger.info("指纹池为空，已应用环境变量中的 DOUBAO_FETCH_URL。")

    def rotate_fingerprint(self):
        """轮换指纹"""
        with self.lock:
            if not self.fingerprint_pool:
                logger.warning("指纹池为空，触发自动补货...")
                self._check_and_refill_fingerprints()
                return

            # 移除旧指纹 (如果是由于限流触发的)
            if self.current_fp_url in self.fingerprint_pool:
                self.fingerprint_pool.remove(self.current_fp_url)
                self._save_fingerprints()
            
            if self.fingerprint_pool:
                self.current_fp_url = self.fingerprint_pool[0]
                logger.success(f"已轮换到新指纹，剩余可用指纹: {len(self.fingerprint_pool)}")
            else:
                self.current_fp_url = settings.DOUBAO_FETCH_URL
                logger.warning("指纹池已耗尽，已回退至环境变量中的默认指纹。")

    def _save_fingerprints(self):
        path = os.path.join(os.getcwd(), "fetch_url.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.fingerprint_pool, f, indent=4, ensure_ascii=False)
        except: pass

    def _check_and_refill_fingerprints(self):
        """手动触发抓取 (不再由系统自动调用)"""
        logger.info("准备手动启动抓取新指纹工具...")
        def run():
            subprocess.run([sys.executable, "fetch-url.py"])
            self._load_fingerprints()
        threading.Thread(target=run, daemon=True).start()

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
                raise ValueError("未找到可用凭证，请检查 cookies.json 是否已配置到位。")
            self.index %= len(creds)
            cred = creds[self.index]
            logger.debug(f"正在获取凭证: 索引 [{self.index}/{len(creds)-1}], Cookie: {cred.get('cookie', '')[:10]}...")
            return cred

    def report_failure(self, err_msg: str = "", permanent: bool = False):
        """上报失败并同步文件"""
        with self.lock:
            creds = self._load_from_json("cookies.json")
            if not creds: return
            self.index %= len(creds)
            if permanent:
                self._move_to_invalid(creds.pop(self.index))
                self._save_list_to_json(creds, "cookies.json")
                if creds: self.index %= len(creds)
                logger.error(f"凭证已永久移除，当前索引重置为: {self.index}")
            else:
                old_index = self.index
                self.index = (self.index + 1) % len(creds)
                logger.warning(f"触发故障切号：索引 [{old_index}] -> [{self.index}]，活跃池总数: {len(creds)}")
                
                # --- 核心逻辑: 针对限流错误进行指纹轮换 ---
                if "710022004" in err_msg or "rate limited" in err_msg.lower():
                    logger.error("检测到指纹级限流 (710022004)，正在触发指纹轮换...")
                    self.rotate_fingerprint()

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
            self._save_list_to_json(creds, "cookies.json")

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

    def wait_for_initial_fetch(self, timeout=60):
        # 补货已禁用，直接返回 True
        return True

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
