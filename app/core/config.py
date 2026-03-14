# /app/core/config.py
import os
import uuid
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import Optional, List, Dict
from dotenv import load_dotenv
from loguru import logger

# 核心修复: 在 Pydantic 读取之前显式加载 .env 到环境变量
# 这样 os.getenv 才能在本地测试和运行中正确获取到值
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra="ignore"
    )

    APP_NAME: str = "doubao-2api"
    APP_VERSION: str = "1.0.0"
    DESCRIPTION: str = "一个将 doubao.com 转换为兼容 OpenAI 格式 API 的高性能代理，内置 a_bogus 签名解决方案。"

    # --- 核心安全与部署配置 ---
    API_MASTER_KEY: Optional[str] = "1"
    NGINX_PORT: int = 8088
    
    # --- Doubao 凭证 ---
    DOUBAO_COOKIES: List[str] = []
    DOUBAO_COOKIES_JSON: Optional[str] = None

    # --- 核心变更: 静态设备指纹配置 ---
    # 从您提供的有效请求中提取的静态设备指纹，这比动态嗅探稳定得多
    # 如果环境变量未配置，将默认使用下方的内置指纹
    DOUBAO_DEVICE_ID: str = "7600236600187471401"
    DOUBAO_FP: str = "verify_mkxf3p9i_hUn2VGVE_y5cH_4yp9_BjK6_iNSvN3wCyROz"
    DOUBAO_TEA_UUID: str = "7468737889876035084"
    DOUBAO_WEB_ID: str = "7468737889876035084"
    DOUBAO_MS_TOKEN: Optional[str] = None

    # --- 上游 API 配置 ---
    API_REQUEST_TIMEOUT: int = 180
    DOUBAO_PC_VERSION: str = "3.10.0"  # 关键：同步抓包版本
    
    # --- 匿名 Cookie 捕获配置 ---
    AUTO_FILL: bool = False   # 是否开启自动抓取补充
    COOKIE_NUM: int = 3       # 维持的最小匿名账号数量
    COOKIE_TIMES: int = 10    # 每个匿名账号的最大使用次数
    
    # --- 会话管理 ---
    SESSION_CACHE_TTL: int = 3600

    # --- 模型配置 ---
    DEFAULT_MODEL: str = "doubao-pro-chat"
    MODEL_MAPPING: Dict[str, str] = {
        "doubao-pro-chat": "7338286299411103781",   # 默认模型 Bot ID
        "doubao-pro-reason": "7338286299411103781",  # 深度思考模型，同 Bot ID，通过 need_deep_think=1 开启
        "doubao-pro-expert": "7338286299411103781",  # 专家模型，开启 deep_think=3
    }

    # 启用深度思考的模型列表
    DEEP_THINK_MODELS: Dict[str, int] = {
        "doubao-pro-reason": 1,
        "doubao-pro-expert": 3,
    }

    # --- 快捷配置 ---
    # 如果设置了此项，将自动从 URL 中解析 device_id, fp, tea_uuid, web_id 等参数
    FETCH_URL: Optional[str] = None

    # 如果为 True，则强制使用全局 FETCH_URL 解析出的指纹，忽略 Cookie 自带的 request_url
    FORCE_FETCH_URL: bool = False

    @model_validator(mode='after')
    def validate_settings(self) -> 'Settings':
        # 1. 解析 FETCH_URL (优先级高，自动提取指纹)
        if self.FETCH_URL:
            try:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(self.FETCH_URL)
                params = parse_qs(parsed.query)
                
                mappings = {
                    "device_id": "DOUBAO_DEVICE_ID",
                    "fp": "DOUBAO_FP",
                    "tea_uuid": "DOUBAO_TEA_UUID",
                    "web_id": "DOUBAO_WEB_ID",
                    "msToken": "DOUBAO_MS_TOKEN" # 备用载入
                }
                
                extracted = 0
                for param_key, attr_name in mappings.items():
                    val = params.get(param_key)
                    if val and val[0]:
                        setattr(self, attr_name, val[0])
                        extracted += 1
                
                if extracted > 0:
                    logger.success(f"已成功从 FETCH_URL 中提取并覆盖 {extracted} 个设备指纹参数。")
            except Exception as e:
                logger.warning(f"解析 FETCH_URL 失败: {e}")

        # 2. 从环境变量 COOKIES 加载，支持用 | 分隔多个
        cookies_env = os.getenv("COOKIES")
        if cookies_env:
            self.DOUBAO_COOKIES.extend([c.strip() for c in cookies_env.split("|") if c.strip()])
        
        # 3. 保留原有的 DOUBAO_COOKIE_X 加载方式以保证兼容性
        i = 1
        while True:
            cookie_str = os.getenv(f"DOUBAO_COOKIE_{i}")
            if cookie_str:
                self.DOUBAO_COOKIES.append(cookie_str)
                i += 1
            else:
                break
        
        if not self.DOUBAO_COOKIES:
            logger.info("未在 .env 中发现 DOUBAO_COOKIE_X，将尝试从 cookies 目录加载。")
        
        return self

settings = Settings()
