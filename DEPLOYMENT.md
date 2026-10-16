# 公网部署说明

本项目可以部署到 Streamlit Community Cloud、Render、Railway 或其他支持 Python/Docker 的平台。部署后会获得 HTTPS 公网地址，iPad 和其他网络都可以访问。

公网部署会在云服务器上接收并处理用户上传的课表截图或 Excel。上传内容只在 Streamlit 进程内存中使用，应用没有保存上传文件的代码，但公网部署不能等同于“只在个人电脑本地处理”。如果课表包含敏感个人信息，应继续使用本地模式或先做脱敏。

## Streamlit Community Cloud

1. 将项目推送到 GitHub 后，在 Streamlit Community Cloud 创建应用。
2. 选择仓库、分支和入口文件 `app.py`。
3. 使用仓库内的 `requirements.txt`，它包含适合免费云构建的 RapidOCR 截图识别依赖；首次构建可能需要几分钟。
4. 在应用 Secrets/Environment variables 中设置可选的 `APP_PASSWORD`，启用访问密码保护。

## Docker 平台

仓库内的 `Dockerfile` 默认通过 `requirements-public.txt` 安装 RapidOCR 依赖并监听 `0.0.0.0:8501`：

```bash
docker build -t timetable-calendar .
docker run --rm -p 8501:8501 -e APP_PASSWORD='请在平台密钥中设置' timetable-calendar
```

生产环境应由平台提供 HTTPS，不要把密码写进镜像、仓库或命令历史。应用本身不调用 ChatGPT API，也不会记录密码、姓名、学号或授权链接。
