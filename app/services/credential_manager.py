import threading
import os
import glob
import json
from typing import List, Dict, Any, Union
from urllib.parse import urlparse, parse_qs
from loguru import logger

class CredentialManager:
    def __init__(self, env_credentials: List[str]):
        # 加载所有可能的凭证，统一格式为 Dict
        self.credentials = self._load_all_credentials(env_credentials)
        
        if not self.credentials:
            raise ValueError("未找到任何有效凭证（环境变量、cookies 目录或 cookies.json）。")
            
        self.index = 0
        self.failure_count = 0 
        self.lock = threading.Lock()
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
        unique_list = []
        # 使用字典缓存，cookie 字符串作为 key，value 是最完整的那个凭证对象
        dedup_map = {}
        
        for item in standard_creds:
            cookie_key = item["cookie"].strip()
            item["cookie"] = cookie_key # 顺便统一清洗
            
            if cookie_key not in dedup_map:
                dedup_map[cookie_key] = item
            else:
                # 优先级竞争：如果新条目比旧条目多了设备信息，则替换它
                existing = dedup_map[cookie_key]
                # 简单判断：如果现有条目没 fp 但新条目有，就换新的
                if not existing.get("fp") and item.get("fp"):
                    dedup_map[cookie_key] = item
        
        return list(dedup_map.values())

    def _load_from_env_json(self) -> List[Dict[str, Any]]:
        """从环境变量 DOUBAO_COOKIES_JSON 加载"""
        from app.core.config import settings
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
            cred = self.credentials[self.index]
            logger.debug(f"当前使用凭据索引: [{self.index}/{len(self.credentials)-1}]")
            return cred

    def report_failure(self):
        """上报当前凭证失败。如果失败，立即切换到下一个，实现'故障切换'。"""
        with self.lock:
            old_index = self.index
            self.index = (self.index + 1) % len(self.credentials)
            logger.warning(f"凭证索引 {old_index} 确认失效，故障切换到索引: {self.index}")

    def report_success(self):
        """成功时重置失败计数"""
        with self.lock:
            if self.failure_count > 0:
                self.failure_count = 0
                logger.debug(f"凭证索引 {self.index} 请求成功，重置失败计数。")

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
