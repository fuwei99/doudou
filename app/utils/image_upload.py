# /app/utils/image_upload.py
import base64
import hashlib
import hmac
import time
import uuid
import json
import httpx
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from loguru import logger

class ImageUploader:
    def __init__(self, playwright_manager, client: httpx.AsyncClient, settings):
        self.playwright_manager = playwright_manager
        self.client = client
        self.settings = settings

    async def upload(self, image_input: str, cookie: str) -> Optional[str]:
        """
        image_input: 可以是 base64 (data:image/...) 也可以是 http URL
        """
        try:
            image_data, extension = await self._get_image_data(image_input)
            if not image_data:
                return None

            # 1. Prepare
            auth_info, _, service_id = await self._prepare_upload(cookie)
            if not auth_info: return None

            # 2. Apply
            store_uri, upload_id, target_host, session_key = await self._apply_upload(
                auth_info, service_id, extension, len(image_data), cookie
            )
            if not store_uri: return None

            # 3. Put
            await self._put_data(target_host, store_uri, auth_info, image_data)

            # 4. Commit
            final_uri = await self._commit_upload(auth_info, service_id, session_key, cookie)
            return final_uri

        except Exception as e:
            logger.error(f"图片上传流程异常: {e}")
            return None

    async def _get_image_data(self, inp: str) -> Tuple[Optional[bytes], str]:
        if inp.startswith("data:image"):
            # base64
            header, encoded = inp.split(",", 1)
            ext = header.split("/")[1].split(";")[0]
            return base64.b64decode(encoded), ext
        elif inp.startswith("http"):
            # URL
            resp = await self.client.get(inp)
            ext = inp.split(".")[-1].split("?")[0] or "png"
            return resp.content, ext
        return None, "png"

    async def _prepare_upload(self, cookie: str) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        base_url = "https://www.doubao.com/alice/resource/prepare_upload"
        base_params = {"version_code": "20800", "language": "zh", "device_platform": "web", "aid": "497858"}
        payload = {"tenant_id": "5", "scene_id": "5", "resource_type": 2}
        headers = {"Content-Type": "application/json", "Cookie": cookie, "Referer": "https://www.doubao.com/chat/"}
        signed_url = await self.playwright_manager.get_signed_url(base_url, cookie, base_params)
        if not signed_url: return None, None, None
        resp = await self.client.post(signed_url, headers=headers, json=payload)
        res = resp.json().get("data", {})
        return res.get("upload_auth_token"), res.get("upload_host"), res.get("service_id")

    async def _apply_upload(self, auth: Dict, service_id: str, ext: str, size: int, cookie: str):
        params = {
            "Action": "ApplyImageUpload", "Version": "2018-08-01", "ServiceId": service_id,
            "FileSize": str(size), "FileExtension": f".{ext}", "s": uuid.uuid4().hex[:10]
        }
        now = datetime.utcnow()
        headers = self._generate_aws4_headers(auth, "GET", "/top/v1", params, now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d'), "imagex")
        headers["Cookie"] = cookie
        resp = await self.client.get("https://www.doubao.com/top/v1", params=params, headers=headers)
        res = resp.json().get("Result", {})
        addr = res.get("UploadAddress", {})
        info = addr.get("StoreInfos", [{}])[0]
        return info.get("StoreUri"), info.get("UploadID"), addr.get("UploadHosts", [""])[0], addr.get("SessionKey")

    async def _put_data(self, host: str, uri: str, auth: Dict, data: bytes):
        url = f"https://{host}/{uri}"
        headers = {"Content-Type": "application/octet-stream", "Authorization": auth.get("session_token", "")}
        await self.client.put(url, content=data, headers=headers)

    async def _commit_upload(self, auth: Dict, service_id: str, session_key: str, cookie: str):
        params = {"Action": "CommitImageUpload", "Version": "2018-08-01", "ServiceId": service_id}
        now = datetime.utcnow()
        headers = self._generate_aws4_headers(auth, "POST", "/top/v1", params, now.strftime('%Y%m%dT%H%M%SZ'), now.strftime('%Y%m%d'), "imagex")
        headers["Cookie"] = cookie
        headers["Content-Type"] = "application/json"
        
        body = {"SessionKey": session_key}
        resp = await self.client.post("https://www.doubao.com/top/v1", params=params, headers=headers, json=body)
        res = resp.json().get("Result", {})
        # 返回第一个成功上传的图片 URI
        items = res.get("Results", [])
        return items[0].get("Uri") if items else None

    def _generate_aws4_headers(self, auth: Dict, method: str, path: str, params: Dict, amz_date: str, datestamp: str, service: str):
        ak = auth["access_key"]
        sk = auth["secret_key"]
        token = auth["session_token"]
        region = "cn-north-1"
        
        canonical_uri = path
        sorted_params = sorted(params.items())
        canonical_querystring = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        canonical_headers = f"x-amz-date:{amz_date}\nx-amz-security-token:{token}\n"
        signed_headers = "x-amz-date;x-amz-security-token"
        
        payload_hash = hashlib.sha256(b"").hexdigest() # GET 请求无 body
        canonical_request = f"{method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
        string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        
        signing_key = self._get_signature_key(sk, datestamp, region, service)
        signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
        
        authorization_header = f"{algorithm} Credential={ak}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
        
        return {
            "Authorization": authorization_header,
            "x-amz-date": amz_date,
            "x-amz-security-token": token
        }

    def _get_signature_key(self, key, date_stamp, region_name, service_name):
        k_date = self._sign(("AWS4" + key).encode('utf-8'), date_stamp)
        k_region = self._sign(k_date, region_name)
        k_service = self._sign(k_region, service_name)
        k_signing = self._sign(k_service, "aws4_request")
        return k_signing

    def _sign(self, key, msg):
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
