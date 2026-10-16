"""Optional local OCR support for timetable screenshots.

PaddleOCR is imported lazily so Excel conversion remains usable when the OCR
model is not installed. OCR output is intentionally only a draft for review.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def preprocess_image(data: bytes, scale: int = 2) -> Image.Image:
    image = Image.open(BytesIO(data)).convert("RGB")
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.2)
    image = ImageEnhance.Sharpness(image).enhance(1.4)
    return image.filter(ImageFilter.MedianFilter(size=3))


def recognize_timetable(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    """Return draft rows and warnings; never claims the OCR is final."""
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "截图识别需要 PaddleOCR。请先执行 `pip install -r requirements-ocr.txt`，"
            "或改用 Excel/CSV 导入。"
        ) from exc

    image = preprocess_image(data)
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr.ocr(np.asarray(image), cls=True)
    except Exception as exc:  # PaddleOCR has version-specific runtime errors.
        raise RuntimeError(f"OCR 模型运行失败：{exc}") from exc

    rows: list[dict[str, Any]] = []
    for page in result or []:
        if not page:
            continue
        for item in page:
            try:
                text, confidence = item[1][0], float(item[1][1])
            except (IndexError, TypeError, ValueError):
                continue
            text = str(text).strip()
            if not text:
                continue
            rows.append(
                {
                    "course_name": text,
                    "weekday": "",
                    "start_period": "",
                    "end_period": "",
                    "teacher": "",
                    "classroom": "",
                    "weeks": "",
                    "parity": "",
                    "cancelled": "",
                    "makeup": "",
                    "note": "OCR 初步识别，请人工确认",
                    "ocr_confidence": confidence,
                }
            )
    warnings = []
    if not rows:
        warnings.append("没有识别到文字，请上传更清晰的截图或改用 Excel 导入。")
    low_count = sum(1 for row in rows if row["ocr_confidence"] < 0.85)
    if low_count:
        warnings.append(f"有 {low_count} 项 OCR 置信度低于 85%，已标记为待确认。")
    warnings.append("OCR 结果仅作初步识别，必须在确认页面补全并核对课程字段。")
    return rows, warnings

