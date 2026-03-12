# /app/utils/image_upload.py
import base64
import hashlib
import hmac
import uuid
import httpx
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from urllib.parse import quote
from loguru import logger

from app.core.config import settings


class FileUploader:
    def __init__(self, playwright_manager, client: httpx.AsyncClient, app_settings):
        self.playwright_manager = playwright_manager
        self.client = client
        self.settings = app_settings

    def _get_standard_base_params(self) -> Dict[str, str]:
        """返回豆包所有接口通用的标准 URL 参数，和 chat/completion 保持一致"""
        return {
            "version_code": "20800",
            "language": "zh",
            "device_platform": "web",
            "aid": "497858",
            "real_aid": "497858",
            "pkg_type": "release_version",
            "region": "",
            "sys_region": "",
            "samantha_web": "1",
            "use-olympus-account": "1",
            "pc_version": "3.9.0",
        }

    async def upload(self, input_source: str, cookie: str, resource_type: int = 2) -> Optional[Dict[str, Any]]:
        """
        完整的上传流程: Prepare -> Apply -> Put (POST) -> Commit
        input_source: 可以是 base64 (data:image/...) 也可以是 http URL
        resource_type: 1 为普通文件(txt), 2 为图片
        返回: {"uri": "tos-cn-xxx", "size": 1234}
        """
        try:
            # 0. 获取原始数据
            data, extension = await self._get_image_data(input_source)
            if not data:
                logger.error("无法获取上传数据数据，跳过上传。")
                return None
            data_size = len(data)
            logger.info(f"已获取数据, 大小: {data_size} 字节, 格式: {extension}")

            # 1. Prepare Upload - 获取上传凭证
            auth_info, service_id = await self._prepare_upload(cookie, resource_type)
            if not auth_info or not service_id:
                logger.error("Prepare Upload 失败，无法获取上传凭证。")
                return None
            logger.success(f"Prepare Upload 成功, service_id: {service_id}")

            # 2. Apply Upload - 申请存储位置
            store_uri, store_auth, upload_host, session_key, upload_id = await self._apply_upload(
                auth_info, service_id, extension, data_size, cookie
            )
            if not store_uri or not session_key:
                logger.error("Apply Upload 失败，无法获取存储路径。")
                return None
            logger.success(f"Apply Upload 成功, store_uri: {store_uri}, host: {upload_host}, upload_id: {upload_id}")

            # 3. Put - 实际上传二进制数据
            put_ok = await self._put_data(upload_host, store_uri, store_auth, data, upload_id, extension)
            if not put_ok:
                logger.error("Put 二进制数据上传失败。")
                return None
            logger.success("Put 二进制数据上传成功。")

            # 4. Commit Upload - 确认上传完成
            final_uri = await self._commit_upload(auth_info, service_id, session_key, cookie)
            if not final_uri:
                logger.error("Commit Upload 失败。")
                return None
            logger.success(f"Commit Upload 成功, 最终 URI: {final_uri}")
            return {"uri": final_uri, "size": data_size}

        except Exception as e:
            logger.error(f"上传流程异常: {e}", exc_info=True)
            return None

    async def upload_text(self, text: str, cookie: str, filename: str = "assistant.txt") -> Optional[Dict[str, Any]]:
        """
        将文本直接上传为附件
        """
        try:
            data = text.encode('utf-8')
            data_size = len(data)
            extension = ".txt"
            
            # 1. Prepare Upload (resource_type=1)
            auth_info, service_id = await self._prepare_upload(cookie, resource_type=1)
            if not auth_info or not service_id:
                return None

            # 2. Apply Upload
            store_uri, store_auth, upload_host, session_key, upload_id = await self._apply_upload(
                auth_info, service_id, extension, data_size, cookie
            )
            if not store_uri:
                return None

            # 3. Put (POST)
            put_ok = await self._put_data(upload_host, store_uri, store_auth, data, upload_id, extension)
            if not put_ok:
                return None

            # 4. Commit
            final_uri = await self._commit_upload(auth_info, service_id, session_key, cookie)
            if not final_uri:
                return None

            return {"uri": final_uri, "size": data_size}
        except Exception as e:
            logger.error(f"文本上传异常: {e}")
            return None

    # ==================== 内部方法 ====================

    async def _get_image_data(self, inp: str) -> Tuple[Optional[bytes], str]:
        """从 base64 或 URL 获取图片二进制数据"""
        try:
            if inp.startswith("data:image"):
                header, encoded = inp.split(",", 1)
                ext = header.split("/")[1].split(";")[0]
                return base64.b64decode(encoded), ext
            elif inp.startswith("http"):
                resp = await self.client.get(inp, follow_redirects=True)
                if resp.status_code != 200:
                    logger.error(f"下载图片失败, 状态码: {resp.status_code}, URL: {inp}")
                    return None, "png"
                # 从 URL 或 Content-Type 推断扩展名
                content_type = resp.headers.get("content-type", "")
                if "png" in content_type:
                    ext = "png"
                elif "jpeg" in content_type or "jpg" in content_type:
                    ext = "jpeg"
                elif "webp" in content_type:
                    ext = "webp"
                elif "gif" in content_type:
                    ext = "gif"
                else:
                    ext = inp.split(".")[-1].split("?")[0]
                    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                        ext = "png"
                return resp.content, ext
            else:
                logger.error(f"不支持的图片输入格式: {inp[:100]}...")
                return None, "png"
        except Exception as e:
            logger.error(f"获取图片数据时出错: {e}")
            return None, "png"

    async def _prepare_upload(self, cookie: str, resource_type: int = 2) -> Tuple[Optional[Dict], Optional[str]]:
        """
        第一步: 调用 alice/resource/prepare_upload
        resource_type: 2=图片, 1=文件
        """
        base_url = "https://www.doubao.com/alice/resource/prepare_upload"
        base_params = self._get_standard_base_params()
        payload = {"tenant_id": "5", "scene_id": "5", "resource_type": resource_type}
        headers = {
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Referer": "https://www.doubao.com/chat/",
            "agw-js-conv": "str",
        }

        signed_url = await self.playwright_manager.get_signed_url(base_url, cookie, base_params)
        if not signed_url:
            logger.error("Prepare Upload: 签名失败")
            return None, None

        logger.info(f"Prepare Upload: 请求 URL: {signed_url[:120]}...")
        resp = await self.client.post(signed_url, headers=headers, json=payload)
        resp_json = resp.json()
        logger.info(f"Prepare Upload: 响应 code={resp_json.get('code')}, msg={resp_json.get('msg')}")

        if resp_json.get("code") != 0:
            logger.error(f"Prepare Upload: 返回错误: {resp_json}")
            return None, None

        data = resp_json.get("data", {})
        auth_token = data.get("upload_auth_token")
        service_id = data.get("service_id")

        if not auth_token or not service_id:
            logger.error(f"Prepare Upload: 返回数据缺少关键字段: {data}")
            return None, None

        return auth_token, service_id

    async def _apply_upload(self, auth: Dict, service_id: str, ext: str, size: int, cookie: str):
        """
        第二步: 调用 Action=ApplyImageUpload
        获取 StoreUri, StoreAuth, UploadHost, SessionKey
        """
        # 确保扩展名以 . 开头
        if not ext.startswith("."):
            ext = f".{ext}"

        params = {
            "Action": "ApplyImageUpload",
            "Version": "2018-08-01",
            "ServiceId": service_id,
            "NeedFallback": "true",
            "FileSize": str(size),
            "FileExtension": ext,
            "s": uuid.uuid4().hex[:10],
        }

        now = datetime.utcnow()
        amz_date = now.strftime('%Y%m%dT%H%M%SZ')
        datestamp = now.strftime('%Y%m%d')

        headers = self._generate_aws4_headers(
            auth, "GET", "/top/v1", params, amz_date, datestamp, "imagex"
        )
        headers["Cookie"] = cookie
        headers["Referer"] = "https://www.doubao.com/chat/"

        logger.info(f"Apply Upload: 请求参数: {params}")
        resp = await self.client.get("https://www.doubao.com/top/v1", params=params, headers=headers)
        resp_json = resp.json()

        # 检查错误
        resp_meta = resp_json.get("ResponseMetadata", {})
        if resp_meta.get("Error"):
            logger.error(f"Apply Upload: 返回错误: {resp_meta['Error']}")
            return None, None, None, None

        result = resp_json.get("Result", {})
        addr = result.get("UploadAddress", {})
        store_infos = addr.get("StoreInfos", [])

        if not store_infos:
            logger.error(f"Apply Upload: StoreInfos 为空, 完整响应: {resp_json}")
            return None, None, None, None

        info = store_infos[0]
        store_uri = info.get("StoreUri")
        store_auth = info.get("Auth")  # 这个 Auth 用于 PUT/POST 上传
        upload_id = info.get("UploadID")
        upload_hosts = addr.get("UploadHosts", [])
        upload_host = upload_hosts[0] if upload_hosts else None
        session_key = addr.get("SessionKey")

        logger.info(f"Apply Upload: StoreUri={store_uri}, Host={upload_host}, upload_id={upload_id}")
        return store_uri, store_auth, upload_host, session_key, upload_id

    async def _put_data(self, host: str, store_uri: str, store_auth: str, data: bytes, upload_id: Optional[str] = None, ext: str = "png") -> bool:
        """
        第三步: POST 二进制数据到 TOS 存储 (根据抓包修正)
        路径需要包含 /upload/v1/，校验使用 CRC32
        """
        import zlib
        # 计算 CRC32 并转为 8 位 16 进制小写字符串
        crc32_val = zlib.crc32(data) & 0xffffffff
        crc32_hex = format(crc32_val, '08x')

        # 构造 URL: 路径中插入 /upload/v1/
        # store_uri 类似 tos-cn-i-a9rns2rl98/xxx.png
        url = f"https://{host}/upload/v1/{store_uri}"

        headers = {
            "Content-Type": "application/octet-stream",
            "Authorization": store_auth,
            "content-crc32": crc32_hex,
            "content-disposition": 'attachment; filename="undefined"',
            # 以下头可能是静态或与 PC 版相关的
            "x-storage-u": "2087334327887627",
            "Referer": "https://www.doubao.com/",
        }

        logger.info(f"Put Data: [POST] 上传到 {url}, CRC32: {crc32_hex}")
        # 注意：抓包显示是 POST
        resp = await self.client.post(url, content=data, headers=headers)
        logger.info(f"Put Data: 响应状态码: {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"Put Data: 上传失败, 状态码: {resp.status_code}, 响应: {resp.text[:500]}")
            return False
        return True

    async def _commit_upload(self, auth: Dict, service_id: str, session_key: str, cookie: str) -> Optional[str]:
        """
        第四步: 调用 Action=CommitImageUpload
        确认上传并获取最终 URI
        """
        params = {
            "Action": "CommitImageUpload",
            "Version": "2018-08-01",
            "ServiceId": service_id,
        }

        import json
        # 确保 JSON 序列化没有空格，并且键顺序一致（虽然这里只有一个键）
        body_str = json.dumps({"SessionKey": session_key}, separators=(',', ':'))
        body_bytes = body_str.encode('utf-8')

        now = datetime.utcnow()
        amz_date = now.strftime('%Y%m%dT%H%M%SZ')
        datestamp = now.strftime('%Y%m%d')

        headers = self._generate_aws4_headers(
            auth, "POST", "/top/v1", params, amz_date, datestamp, "imagex",
            payload_hash=hashlib.sha256(body_bytes).hexdigest()
        )
        headers["Cookie"] = cookie
        headers["Referer"] = "https://www.doubao.com/chat/"
        headers["Content-Type"] = "application/json"

        logger.info(f"Commit Upload: 请求参数: {params}")
        resp = await self.client.post(
            "https://www.doubao.com/top/v1",
            params=params,
            headers=headers,
            content=body_bytes
        )
        resp_json = resp.json()

        resp_meta = resp_json.get("ResponseMetadata", {})
        if resp_meta.get("Error"):
            logger.error(f"Commit Upload: 返回错误: {resp_meta['Error']}")
            return None

        result = resp_json.get("Result", {})
        results = result.get("Results", [])
        if not results:
            logger.error(f"Commit Upload: Results 为空, 完整响应: {resp_json}")
            return None

        uri = results[0].get("Uri")
        uri_status = results[0].get("UriStatus")
        logger.info(f"Commit Upload: Uri={uri}, UriStatus={uri_status}")

        if uri_status != 2000:
            logger.warning(f"Commit Upload: UriStatus 不为 2000, 可能上传未完全成功")

        return uri

    # ==================== AWS4 签名 ====================

    def _generate_aws4_headers(
        self, auth: Dict, method: str, path: str, params: Dict,
        amz_date: str, datestamp: str, service: str,
        payload_hash: str = None
    ) -> Dict[str, str]:
        """生成 AWS4-HMAC-SHA256 签名头"""
        ak = auth["access_key"]
        sk = auth["secret_key"]
        token = auth["session_token"]
        region = "cn-north-1"

        # Canonical Request
        canonical_uri = path
        sorted_params = sorted(params.items())
        canonical_querystring = "&".join([f"{k}={v}" for k, v in sorted_params])

        if payload_hash is None:
            payload_hash = hashlib.sha256(b"").hexdigest()

        # POST 请求需要额外签 x-amz-content-sha256
        if method == "POST":
            canonical_headers = (
                f"x-amz-content-sha256:{payload_hash}\n"
                f"x-amz-date:{amz_date}\n"
                f"x-amz-security-token:{token}\n"
            )
            signed_headers = "x-amz-content-sha256;x-amz-date;x-amz-security-token"
        else:
            canonical_headers = (
                f"x-amz-date:{amz_date}\n"
                f"x-amz-security-token:{token}\n"
            )
            signed_headers = "x-amz-date;x-amz-security-token"

        canonical_request = (
            f"{method}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        # String to Sign
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
        string_to_sign = (
            f"{algorithm}\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        # Signature
        signing_key = self._get_signature_key(sk, datestamp, region, service)
        signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

        authorization = f"{algorithm} Credential={ak}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

        result_headers = {
            "Authorization": authorization,
            "x-amz-date": amz_date,
            "x-amz-security-token": token,
        }
        if method == "POST":
            result_headers["x-amz-content-sha256"] = payload_hash

        return result_headers

    def _get_signature_key(self, key, date_stamp, region_name, service_name):
        k_date = self._sign(("AWS4" + key).encode('utf-8'), date_stamp)
        k_region = self._sign(k_date, region_name)
        k_service = self._sign(k_region, service_name)
        k_signing = self._sign(k_service, "aws4_request")
        return k_signing

    def _sign(self, key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
