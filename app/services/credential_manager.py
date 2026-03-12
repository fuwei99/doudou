# /app/services/credential_manager.py
import threading
import os
import glob
from typing import List
from loguru import logger

class CredentialManager:
    def __init__(self, env_credentials: List[str]):
        # 加载所有可能的凭证
        self.credentials = self._load_all_credentials(env_credentials)
        
        if not self.credentials:
            raise ValueError("未找到任何有效凭证（环境变量或 cookies 目录）。")
            
        self.index = 0
        self.lock = threading.Lock()
        logger.info(f"凭证管理器已初始化，共加载 {len(self.credentials)} 个凭证。")

    def _load_all_credentials(self, env_credentials: List[str]) -> List[str]:
        """合并环境变量和目录中的凭证"""
        all_creds = list(env_credentials)
        
        # 加载 cookies 目录下的所有 .txt 文件
        dir_creds = self._load_from_directory()
        all_creds.extend(dir_creds)
        
        # 去重并过滤空值
        unique_creds = list(set([c.strip() for c in all_creds if c and c.strip()]))
        return unique_creds

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

    def get_credential(self) -> str:
        with self.lock:
            credential = self.credentials[self.index]
            self.index = (self.index + 1) % len(self.credentials)
            logger.debug(f"轮询到凭证索引: {self.index}")
            return credential
