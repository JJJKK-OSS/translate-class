"""Core timetable parsing, validation, and iCalendar generation.

The Streamlit UI deliberately stays thin so these functions can be tested without
starting a browser. No network access or remote API is used here.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from typing import Any, Iterable

import pandas as pd
from icalendar import Calendar, Event, Alarm


COURSE_FIELDS = [
    "course_name",
    "weekday",
    "start_period",
    "end_period",
    "teacher",
    "classroom",
    "weeks",
    "parity",
    "cancelled",
    "makeup",
    "note",
]

FIELD_LABELS = {
    "course_name": "课程名称",
    "weekday": "星期",
    "start_period": "开始节次",
    "end_period": "结束节次",
    "teacher": "教师",
    "classroom": "教室",
    "weeks": "周次",
    "parity": "单双周",
    "cancelled": "是否停课",
    "makeup": "是否补课",
    "note": "备注",
}

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DEFAULT_SCHEDULE = [
    {"period": i, "start": s, "end": e}
    for i, s, e in [
        (1, "08:00", "08:45"),
        (2, "08:55", "09:40"),
        (3, "10:05", "10:50"),
        (4, "10:55", "11:40"),
        (5, "14:30", "15:15"),
        (6, "15:25", "16:10"),
        (7, "16:40", "17:25"),
        (8, "17:35", "18:20"),
        (9, "19:00", "19:45"),
        (10, "19:55", "20:40"),
    ]
]


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalise_header(value: Any) -> str:
    return re.sub(r"[\s_()（）\[\]【】\-]+", "", _text(value).lower())


ALIASES = {
    "course_name": ["课程名称", "课程", "科目", "课程名", "名称", "subject", "course"],
    "weekday": ["星期", "周几", "上课日", "day", "weekday"],
    "start_period": ["开始节次", "起始节次", "节次", "上课节次", "startperiod", "period"],
    "end_period": ["结束节次", "终止节次", "endperiod"],
    "teacher": ["教师", "老师", "任课教师", "授课教师", "teacher"],
    "classroom": ["教室", "地点", "上课地点", "room", "classroom"],
    "weeks": ["周次", "上课周次", "教学周", "week", "weeks"],
    "parity": ["单双周", "单双", "周别", "parity"],
    "cancelled": ["停课", "是否停课", "取消", "cancelled"],
    "makeup": ["补课", "是否补课", "调课", "makeup"],
    "note": ["备注", "说明", "note"],
}


def suggest_mapping(columns: Iterable[Any]) -> dict[str, str | None]:
    """Suggest source columns for each canonical field using conservative aliases."""
    columns = list(columns)
    normalised = {_normalise_header(c): c for c in columns}
    result: dict[str, str | None] = {}
    for field, aliases in ALIASES.items():
        result[field] = next(
            (normalised[_normalise_header(alias)] for alias in aliases if _normalise_header(alias) in normalised),
            None,
        )
    return result


def read_spreadsheet(data: bytes, filename: str, sheet_name: str | int = 0) -> pd.DataFrame:
    """Read xlsx/xls/csv bytes into a dataframe without writing the upload to disk."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return pd.read_csv(BytesIO(data), encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("CSV 文件编码无法识别，请另存为 UTF-8 CSV。")
    if not lower.endswith((".xlsx", ".xls")):
        raise ValueError("仅支持 .xlsx、.xls 或 .csv 文件。")
    try:
        return pd.read_excel(BytesIO(data), sheet_name=sheet_name)
    except ImportError as exc:
        raise ValueError("读取 Excel 所需的引擎未安装，请安装 requirements.txt 中的依赖。") from exc


def apply_mapping(frame: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Convert arbitrary source columns to canonical course columns."""
    result = pd.DataFrame(index=frame.index)
    for field in COURSE_FIELDS:
        source = mapping.get(field)
        result[field] = frame[source] if source and source in frame.columns else ""
    return result.fillna("")


def parse_weekday(value: Any) -> int | None:
    text = _text(value).lower()
    if not text:
        return None
    for index, name in enumerate(WEEKDAY_NAMES):
        if name in text or str(index + 1) == text or f"星期{index + 1}" in text or f"礼拜{index + 1}" in text:
            return index
    aliases = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    for key, index in aliases.items():
        if text in {key, f"周{key}", f"星期{key}", f"礼拜{key}"}:
            return index
    return None


def parse_periods(value: Any) -> tuple[int | None, int | None]:
    numbers = [int(n) for n in re.findall(r"\d+", _text(value))]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def parse_weeks(value: Any, total_weeks: int | None = None) -> list[int]:
    """Parse values such as 1-16周, 1,3,5-7, or 1至16."""
    text = _text(value).replace("第", "").replace("周", "").replace("星期", "")
    text = text.replace("至", "-").replace("到", "-").replace("，", ",").replace("、", ",").replace(" ", "")
    if not text:
        return []
    if text in {"全", "全部", "每周", "每星期"}:
        return list(range(1, (total_weeks or 0) + 1))
    weeks: set[int] = set()
    try:
        for part in text.split(","):
            if not part:
                continue
            values = [int(n) for n in re.findall(r"\d+", part)]
            if len(values) == 1:
                weeks.add(values[0])
            elif len(values) >= 2:
                start, end = values[0], values[1]
                if end < start:
                    raise ValueError
                weeks.update(range(start, end + 1))
    except ValueError:
        return []
    return sorted(weeks)


def parse_bool(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "y", "是", "停课", "补课", "√", "✓"}


def normalise_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Make records serialisable and keep all user-editable fields present."""
    records = []
    for _, row in frame.iterrows():
        record = {field: _text(row.get(field, "")) for field in COURSE_FIELDS}
        if "ocr_confidence" in row.index:
            try:
                record["ocr_confidence"] = float(row.get("ocr_confidence"))
            except (TypeError, ValueError):
                record["ocr_confidence"] = 0.0
        if not record["course_name"] and not record["weekday"] and not record["weeks"]:
            continue
        records.append(record)
    return records


def parse_schedule(schedule: Iterable[dict[str, Any]]) -> dict[int, tuple[time, time]]:
    result: dict[int, tuple[time, time]] = {}
    for row in schedule:
        try:
            period = int(row["period"])
            start = datetime.strptime(_text(row["start"]), "%H:%M").time()
            end = datetime.strptime(_text(row["end"]), "%H:%M").time()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("作息时间表必须使用 24 小时制 HH:MM，并填写有效节次。") from exc
        if end <= start:
            raise ValueError(f"第 {period} 节的结束时间必须晚于开始时间。")
        result[period] = (start, end)
    return result


def validate_records(records: Iterable[dict[str, Any]], total_weeks: int, schedule: dict[int, tuple[time, time]]) -> list[str]:
    errors: list[str] = []
    for index, row in enumerate(records, 1):
        label = f"第 {index} 行"
        if not _text(row.get("course_name")):
            errors.append(f"{label}缺少课程名称。")
        if parse_weekday(row.get("weekday")) is None:
            errors.append(f"{label}无法识别星期。")
        start, start_range_end = parse_periods(row.get("start_period"))
        end2, end3 = parse_periods(row.get("end_period"))
        if start is None:
            errors.append(f"{label}无法识别开始节次。")
        else:
            end_period = end3 if end3 is not None else end2 or start_range_end
            if end_period is None:
                end_period = start
            if end_period < start:
                errors.append(f"{label}结束节次早于开始节次。")
            for period in range(start, end_period + 1):
                if period not in schedule:
                    errors.append(f"{label}第 {period} 节没有对应作息时间。")
        weeks = parse_weeks(row.get("weeks"), total_weeks)
        if not weeks:
            errors.append(f"{label}周次缺失或格式无法解析。")
        elif any(week < 1 or week > total_weeks for week in weeks):
            errors.append(f"{label}周次必须在 1 至 {total_weeks} 周之间。")
    return errors


def _event_instances(
    records: Iterable[dict[str, Any]],
    first_week_date: date,
    total_weeks: int,
    week_start: int,
    schedule: dict[int, tuple[time, time]],
    excluded_weeks: set[int] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    instances: list[dict[str, Any]] = []
    errors: list[str] = []
    for row_index, row in enumerate(records, 1):
        if parse_bool(row.get("cancelled")) and not parse_bool(row.get("makeup")):
            continue
        weekday = parse_weekday(row.get("weekday"))
        start, end_from_start = parse_periods(row.get("start_period"))
        end_from_end, end_period = parse_periods(row.get("end_period"))
        end_period = end_period or end_from_end or end_from_start or start
        weeks = parse_weeks(row.get("weeks"), total_weeks)
        parity = _text(row.get("parity")).lower()
        for week in weeks:
            if excluded_weeks and week in excluded_weeks:
                continue
            if "单" in parity and week % 2 == 0:
                continue
            if "双" in parity and week % 2 == 1:
                continue
            if weekday is None or start is None or end_period is None:
                continue
            if start not in schedule or end_period not in schedule:
                continue
            day_offset = (weekday - week_start) % 7
            course_date = first_week_date + timedelta(days=(week - 1) * 7 + day_offset)
            instances.append(
                {
                    "row_index": row_index,
                    "row": row,
                    "date": course_date,
                    "start": schedule[start][0],
                    "end": schedule[end_period][1],
                    "week": week,
                }
            )
    return instances, errors


def detect_conflicts(instances: Iterable[dict[str, Any]]) -> list[str]:
    grouped: dict[date, list[dict[str, Any]]] = {}
    for item in instances:
        grouped.setdefault(item["date"], []).append(item)
    conflicts: list[str] = []
    for day, items in grouped.items():
        items.sort(key=lambda x: x["start"])
        for left, right in zip(items, items[1:]):
            if right["start"] < left["end"]:
                conflicts.append(
                    f"{day.isoformat()} 第 {left['week']} 周存在时间冲突："
                    f"第 {left['row_index']} 行与第 {right['row_index']} 行。"
                )
    return conflicts


def generate_calendar(
    records: Iterable[dict[str, Any]],
    *,
    first_week_date: date,
    total_weeks: int,
    week_start: int,
    schedule: Iterable[dict[str, Any]] | dict[int, tuple[time, time]],
    reminder_minutes: int | None = 15,
    calendar_name: str = "大学课表",
    excluded_weeks: set[int] | None = None,
) -> tuple[bytes, list[dict[str, Any]], list[str]]:
    """Return (ics bytes, generated instances, errors)."""
    parsed_schedule = schedule if isinstance(schedule, dict) else parse_schedule(schedule)
    records = list(records)
    errors = validate_records(records, total_weeks, parsed_schedule)
    instances, _ = _event_instances(records, first_week_date, total_weeks, week_start, parsed_schedule, excluded_weeks)
    errors.extend(detect_conflicts(instances))
    if errors:
        return b"", instances, errors

    calendar = Calendar()
    calendar.add("prodid", "-//Local Timetable Calendar//CN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", calendar_name)
    calendar.add("x-wr-timezone", "Asia/Shanghai")
    for item in instances:
        row = item["row"]
        start_dt = datetime.combine(item["date"], item["start"])
        end_dt = datetime.combine(item["date"], item["end"])
        stable = "|".join(
            _text(row.get(key)) for key in ("course_name", "weekday", "start_period", "end_period", "teacher", "classroom", "weeks", "parity")
        )
        uid_source = f"{stable}|{item['date'].isoformat()}|{start_dt.isoformat()}"
        uid = hashlib.sha256(uid_source.encode("utf-8")).hexdigest()[:32] + "@local-timetable"
        event = Event()
        event.add("uid", uid)
        event.add("dtstamp", datetime.now(timezone.utc))
        event.add("dtstart", start_dt)
        event.add("dtend", end_dt)
        event.add("summary", _text(row.get("course_name")) or "未命名课程")
        description = "\n".join(
            part for part in [
                f"教师：{_text(row.get('teacher'))}" if _text(row.get("teacher")) else "",
                f"周次：第 {item['week']} 周",
                f"单双周：{_text(row.get('parity'))}" if _text(row.get("parity")) else "",
                _text(row.get("note")),
            ] if part
        )
        if description:
            event.add("description", description)
        if _text(row.get("classroom")):
            event.add("location", _text(row.get("classroom")))
        if reminder_minutes is not None:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", _text(row.get("course_name")) or "课程提醒")
            alarm.add("trigger", timedelta(minutes=-int(reminder_minutes)))
            event.add_component(alarm)
        calendar.add_component(event)
    return calendar.to_ical(), instances, []

