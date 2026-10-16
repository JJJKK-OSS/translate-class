# 课表转苹果日历

这是一个完全在本机运行的 Streamlit 工具，可以将大学课表 Excel/CSV 或截图草稿转换为标准 `calendar.ics` 文件。程序不调用 ChatGPT API，也不会上传课表文件。

## 启动

建议使用 Python 3.10–3.12：

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py --server.address 0.0.0.0
```

在运行程序的电脑上打开 `http://localhost:8501`。如果要从 iPad 访问，请确保 iPad 与电脑连接同一 Wi‑Fi，在电脑上查找局域网 IPv4 地址，然后在 iPad 打开 `http://电脑局域网IP:8501`，例如 `http://192.168.1.23:8501`。首次访问时允许系统防火墙接收 Python/Streamlit 的局域网连接。

如果电脑是 macOS，可用 `ipconfig getifaddr en0` 查找 Wi‑Fi 地址；Windows 可运行 `ipconfig`；Linux 可运行 `hostname -I`。不要在 iPad 上访问 `localhost:8501`，那会指向 iPad 自己。云端开发环境的地址也不能直接当作家庭局域网地址使用；需要在你自己的电脑上运行此程序。

`requirements.txt` 已包含适合云端的 Tesseract OCR Python 接口，`packages.txt` 会为 Streamlit Cloud 安装中文语言模型；本地如果需要 PaddleOCR 中文模型，也可额外安装 `requirements-ocr.txt`。

## 使用流程

1. 上传 `.xlsx`、`.xls`、`.csv`，在字段映射页确认课程名称、星期、节次、教师、教室和周次；或者上传 PNG/JPG 截图并运行本地 PaddleOCR。
2. 填写第一周日期、周数、每周起始日，编辑每节课的作息时间，并按需排除停课周和设置提醒。
3. 在可编辑确认表中核对所有课程。OCR 只产生草稿，无法识别的星期、节次、周次和低置信度项目会阻止生成。
4. 通过检查后生成并下载 `calendar.ics`，导入或订阅到 Apple 日历。

程序会校验周次、节次、第一周日期和同日时间冲突；每个事件使用稳定 UID，重复生成同一份课表不会产生新的重复事件。原始上传文件只保留在当前进程内存中，关闭页面或进程后即可删除。

## 隐私

所有解析和 OCR 都在运行 Streamlit 的电脑上完成。日志和代码不会记录姓名、学号、教务系统密码、授权链接或上传文件内容。不要把包含个人信息的课表提交到公开仓库。

## 当前范围

第一阶段包含 Excel/CSV 和截图 OCR 到 `.ics`。批量导入、学校模板、订阅链接和自动更新可在后续迭代中增加。
