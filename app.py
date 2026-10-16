from __future__ import annotations

from datetime import date, datetime, timedelta
import os

import pandas as pd
import streamlit as st

from timetable import (
    COURSE_FIELDS,
    DEFAULT_SCHEDULE,
    FIELD_LABELS,
    WEEKDAY_NAMES,
    apply_mapping,
    generate_calendar,
    normalise_records,
    parse_schedule,
    read_spreadsheet,
    suggest_mapping,
    validate_records,
)


st.set_page_config(page_title="课表转苹果日历", page_icon="📅", layout="wide")


def init_state() -> None:
    defaults = {
        "step": "1. 上传课表",
        "records": [],
        "source_signature": None,
        "source_frame": None,
        "source_columns": [],
        "mapping": {},
        "ocr_warnings": [],
        "ics_bytes": None,
        "instances": [],
        "generation_errors": [],
        "first_week_date": None,
        "total_weeks": 18,
        "week_start": 0,
        "excluded_weeks": [],
        "schedule": DEFAULT_SCHEDULE.copy(),
        "reminder": 15,
        "afternoon_advance": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_result() -> None:
    st.session_state.ics_bytes = None
    st.session_state.instances = []
    st.session_state.generation_errors = []


def upload_step() -> None:
    st.subheader("1. 上传课表")
    st.caption("文件只在本机内存中处理，不会上传到 ChatGPT 或公开服务器。")
    mode = st.radio("输入方式", ["Excel / CSV", "课表截图 OCR"], horizontal=True)
    if mode == "Excel / CSV":
        uploaded = st.file_uploader("上传 .xlsx、.xls 或 .csv", type=["xlsx", "xls", "csv"])
        if not uploaded:
            st.info("请选择课表文件。")
            return
        signature = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.source_signature != signature:
            try:
                frame = read_spreadsheet(uploaded.getvalue(), uploaded.name)
            except Exception as exc:
                st.error(str(exc))
                return
            st.session_state.source_signature = signature
            st.session_state.source_frame = frame
            st.session_state.source_columns = list(frame.columns)
            st.session_state.mapping = suggest_mapping(frame.columns)
            reset_result()
        frame = st.session_state.source_frame
        st.write(f"已读取 {len(frame)} 行、{len(frame.columns)} 列。请确认字段映射：")
        options = ["（不导入）"] + [str(column) for column in st.session_state.source_columns]
        mapping: dict[str, str | None] = {}
        columns = st.columns(2)
        for index, field in enumerate(COURSE_FIELDS):
            suggestion = st.session_state.mapping.get(field)
            default_index = options.index(str(suggestion)) if suggestion is not None and str(suggestion) in options else 0
            with columns[index % 2]:
                selected = st.selectbox(FIELD_LABELS[field], options, index=default_index, key=f"mapping_{field}")
            mapping[field] = None if selected == "（不导入）" else selected
        if st.button("读取并进入设置", type="primary"):
            mapped = apply_mapping(frame, mapping)
            st.session_state.records = normalise_records(mapped)
            st.session_state.mapping = mapping
            reset_result()
            st.session_state.step = "2. 设置学期和作息"
            st.rerun()
    else:
        uploaded = st.file_uploader("上传 PNG、JPG 或 JPEG 截图", type=["png", "jpg", "jpeg"])
        if not uploaded:
            st.info("请选择课表截图。OCR 只会生成草稿，后续必须人工确认。")
            return
        st.image(uploaded, caption="原始截图", use_container_width=True)
        if st.button("运行本地 OCR", type="primary"):
            with st.spinner("正在本机处理截图…"):
                try:
                    from ocr_utils import recognize_timetable

                    records, warnings = recognize_timetable(uploaded.getvalue())
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.session_state.records = records
                    st.session_state.ocr_warnings = warnings
                    reset_result()
                    st.session_state.step = "2. 设置学期和作息"
                    st.rerun()


def schedule_step() -> None:
    st.subheader("2. 设置学期和作息")
    left, right = st.columns(2)
    with left:
        first_week = st.date_input("第一周开始日期", value=st.session_state.first_week_date or date.today())
        total_weeks = st.number_input("总周数", min_value=1, max_value=60, value=int(st.session_state.total_weeks), step=1)
        week_start_name = st.selectbox("每周从星期几开始", WEEKDAY_NAMES, index=int(st.session_state.week_start))
        st.checkbox("课表包含单双周", value=any(r.get("parity") for r in st.session_state.records))
    with right:
        reminder_options = {"不提醒": None, "提前10分钟": 10, "提前15分钟": 15, "提前30分钟": 30}
        reminder_label = st.selectbox("课前提醒", list(reminder_options), index=2)
        st.session_state.afternoon_advance = st.checkbox("下午课程整体提前 30 分钟", value=bool(st.session_state.afternoon_advance), help="勾选后自动将第 5 节及之后的时间提前 30 分钟，仍可在下方逐节修改。")
        st.checkbox("上午时间需要调整（请在下表修改）", value=False)
        st.checkbox("晚上时间需要调整（请在下表修改）", value=False)
    excluded = st.multiselect("排除节假日或停课周（可选）", list(range(1, int(total_weeks) + 1)), default=[w for w in st.session_state.excluded_weeks if w <= int(total_weeks)], format_func=lambda value: f"第 {value} 周")
    st.write("可直接编辑每节课的开始和结束时间：")
    schedule_frame = pd.DataFrame(st.session_state.schedule)
    edited = st.data_editor(schedule_frame, hide_index=True, num_rows="fixed", column_config={"period": st.column_config.NumberColumn("节次", min_value=1, step=1), "start": "开始 (HH:MM)", "end": "结束 (HH:MM)"}, key="schedule_editor")
    if st.button("保存设置并检查课程", type="primary"):
        schedule = edited.to_dict("records")
        if st.session_state.afternoon_advance:
            adjusted = []
            for row in schedule:
                row = dict(row)
                if int(row.get("period", 0)) >= 5:
                    for key in ("start", "end"):
                        parsed = datetime.strptime(str(row[key]), "%H:%M") - timedelta(minutes=30)
                        row[key] = parsed.strftime("%H:%M")
                adjusted.append(row)
            schedule = adjusted
        try:
            parsed_schedule = parse_schedule(schedule)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state.schedule = schedule
        st.session_state.first_week_date = first_week
        st.session_state.total_weeks = int(total_weeks)
        st.session_state.week_start = WEEKDAY_NAMES.index(week_start_name)
        st.session_state.excluded_weeks = excluded
        st.session_state.reminder = reminder_options[reminder_label]
        st.session_state.parsed_schedule = parsed_schedule
        reset_result()
        st.session_state.step = "3. 检查并修改识别结果"
        st.rerun()


def _display_records() -> pd.DataFrame:
    frame = pd.DataFrame(st.session_state.records)
    for field in COURSE_FIELDS:
        if field not in frame:
            frame[field] = ""
    rename = {field: FIELD_LABELS[field] for field in COURSE_FIELDS}
    frame = frame.rename(columns=rename)
    if st.session_state.records and "ocr_confidence" in st.session_state.records[0]:
        frame["识别置信度"] = [row.get("ocr_confidence", 1.0) for row in st.session_state.records]
    extra = ["识别置信度"] if "识别置信度" in frame else []
    return frame[[*rename.values(), *extra]]


def review_step() -> None:
    st.subheader("3. 检查并修改识别结果")
    records = st.session_state.records
    if not records:
        st.warning("还没有课程数据，请返回上传课表。")
        return
    if st.session_state.ocr_warnings:
        for warning in st.session_state.ocr_warnings:
            st.warning(warning)
    low = [row for row in records if row.get("ocr_confidence", 1.0) < 0.85]
    if low:
        st.error(f"有 {len(low)} 行 OCR 置信度低于 85%，请优先核对标红提示和所有空白字段。")
        confidence_preview = _display_records()
        if "识别置信度" in confidence_preview:
            def mark_low(row):
                return ["background-color: #ffd6d6" if row.get("识别置信度", 1.0) < 0.85 else "" for _ in row]

            st.dataframe(confidence_preview.style.apply(mark_low, axis=1), hide_index=True, use_container_width=True)
    st.caption("截图 OCR 结果只是草稿；课程名称、星期、节次、周次必须由你确认后才能生成日历。")
    edited = st.data_editor(_display_records(), hide_index=True, num_rows="dynamic", use_container_width=True, key="course_editor")
    reverse = {label: field for field, label in FIELD_LABELS.items()}
    canonical = edited.rename(columns=reverse)
    if "识别置信度" in canonical:
        canonical = canonical.rename(columns={"识别置信度": "ocr_confidence"})
    st.session_state.records = normalise_records(canonical)
    try:
        schedule = parse_schedule(st.session_state.schedule)
        errors = validate_records(st.session_state.records, st.session_state.total_weeks, schedule)
    except ValueError as exc:
        errors = [str(exc)]
    st.metric("识别到的课程数量", len(st.session_state.records))
    if errors:
        st.error("暂时不能生成日历：")
        for error in errors:
            st.write(f"- {error}")
    else:
        st.success("课程基础字段已通过检查，可以生成日历。")
    if st.button("确认并生成日历", type="primary", disabled=bool(errors)):
        ics, instances, generation_errors = generate_calendar(st.session_state.records, first_week_date=st.session_state.first_week_date, total_weeks=st.session_state.total_weeks, week_start=st.session_state.week_start, schedule=st.session_state.schedule, reminder_minutes=st.session_state.reminder, excluded_weeks=set(st.session_state.excluded_weeks))
        st.session_state.ics_bytes = ics
        st.session_state.instances = instances
        st.session_state.generation_errors = generation_errors
        st.session_state.step = "4. 下载 calendar.ics"
        st.rerun()


def download_step() -> None:
    st.subheader("4. 下载 calendar.ics")
    if st.session_state.generation_errors:
        st.error("生成失败，请返回检查：")
        for error in st.session_state.generation_errors:
            st.write(f"- {error}")
        return
    instances = st.session_state.instances
    st.metric("将生成的课程事件数量", len(instances))
    if not instances:
        st.warning("没有可生成的课程事件，请检查周次、单双周和停课设置。")
        return
    preview = pd.DataFrame([{"日期": item["date"].isoformat(), "周次": item["week"], "课程": item["row"].get("course_name", ""), "开始": item["start"].strftime("%H:%M"), "结束": item["end"].strftime("%H:%M"), "教室": item["row"].get("classroom", "")} for item in instances[:100]])
    st.dataframe(preview, hide_index=True, use_container_width=True)
    st.download_button("下载 calendar.ics", data=st.session_state.ics_bytes, file_name="calendar.ics", mime="text/calendar", type="primary")
    st.info("文件已在本机生成。下载后可按需删除原始截图；程序不会保存教务账号、密码或授权链接。")
    if st.button("清除本次上传数据"):
        for key, value in {
            "source_frame": None,
            "source_signature": None,
            "source_columns": [],
            "records": [],
            "ocr_warnings": [],
            "ics_bytes": None,
            "instances": [],
            "generation_errors": [],
        }.items():
            st.session_state[key] = value
        st.session_state.step = "1. 上传课表"
        st.rerun()


def access_allowed() -> bool:
    """Optional deployment password; local development stays passwordless."""
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        return True
    entered = st.text_input("访问密码", type="password")
    if not entered:
        st.info("请输入访问密码后继续。")
        return False
    if entered != expected:
        st.error("访问密码不正确。")
        return False
    return True


if not access_allowed():
    st.stop()

init_state()
st.title("📅 课表转苹果日历")
st.caption("本地运行 · Excel/CSV + 截图 OCR · 生成标准 .ics")
steps = ["1. 上传课表", "2. 设置学期和作息", "3. 检查并修改识别结果", "4. 下载 calendar.ics"]
st.session_state.step = st.radio("流程", steps, index=steps.index(st.session_state.step), horizontal=True, label_visibility="collapsed")
if st.session_state.step == steps[0]:
    upload_step()
elif st.session_state.step == steps[1]:
    schedule_step()
elif st.session_state.step == steps[2]:
    review_step()
else:
    download_step()
