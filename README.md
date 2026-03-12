# 🎉 doubao-2api - 豆包转 OpenAI 接口工具

本项目是一个高性能代理服务端，可将豆包 (doubao.com) 的网页端接口转换为标准的 OpenAI API 格式。支持流式输出、深度思考模型、以及画图和识图功能。

## 🌟 核心特性

- **完全兼容 OpenAI**：支持 `/v1/chat/completions` 和 `/v1/models` 接口。
- **支持多账号轮询**：可配置多个 Cookie 自动循环使用，提高并发上限。
- **深度思考支持**：原生支持 `doubao-pro-reason` 和 `doubao-pro-expert`。
- **多模态功能**：
  - **画图**：模型识别到画图意图时，会自动返回 Markdown 图片。
  - **识图**：支持上传图片（OpenAI 格式），让模型分析图片内容。
- **内置签名服务**：集成 Playwright 自动处理 `a_bogus` 签名，稳定防爬。
- **一键部署**：支持 Docker 和 GitHub Actions 自动构建。

## 🔧 快速启动

### 1. 准备工作
- 安装 Python 3.10+。
- 准备豆包 Cookie（网页端抓包获取）。

### 2. 配置说明
本项目支持两种方式加载 Cookie：
- **推荐：** 在项目根目录创建 `cookies` 文件夹，将每个账号的 Cookie 分别存放在 `.txt` 文件中。
- **环境变量：** 在 `.env` 中配置 `COOKIES=cookie1|cookie2...`。

同时需要在 `.env` 中配置设备指纹（不填则使用内置默认值）：
```env
DOUBAO_DEVICE_ID=7600236600187471401
DOUBAO_FP=verify_...
DOUBAO_TEA_UUID=...
DOUBAO_WEB_ID=...
```

### 3. 运行
```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```
服务默认运行在 `7860` 端口。

## 🐳 Docker 部署
```bash
docker build -t doubao-2api .
docker run -d -p 7860:7860 --env-file .env doubao-2api
```

## ⚠️ 免责声明
本项目仅供学习和研究使用，请勿用于违反豆包服务协议的场景。
