from datetime import date, time

from timetable import generate_calendar, parse_periods, parse_weekday, parse_weeks, validate_records


SCHEDULE = {
    1: (time(8, 0), time(8, 45)),
    2: (time(8, 55), time(9, 40)),
    3: (time(10, 5), time(10, 50)),
}


def test_parse_common_values():
    assert parse_weekday("星期二") == 1
    assert parse_periods("第1-2节") == (1, 2)
    assert parse_weeks("1-3, 5周") == [1, 2, 3, 5]


def test_generate_stable_calendar_events():
    records = [{
        "course_name": "高等数学",
        "weekday": "周一",
        "start_period": "1",
        "end_period": "2",
        "teacher": "张老师",
        "classroom": "A101",
        "weeks": "1-2",
        "parity": "",
        "cancelled": "",
        "makeup": "",
        "note": "",
    }]
    ics_a, instances_a, errors_a = generate_calendar(records, first_week_date=date(2026, 9, 7), total_weeks=2, week_start=0, schedule=SCHEDULE)
    ics_b, instances_b, errors_b = generate_calendar(records, first_week_date=date(2026, 9, 7), total_weeks=2, week_start=0, schedule=SCHEDULE)
    assert not errors_a and not errors_b
    assert len(instances_a) == len(instances_b) == 2
    assert ics_a == ics_b
    assert b"SUMMARY:\xe9\xab\x98\xe7\xad\x89\xe6\x95\xb0\xe5\xad\xa6" in ics_a


def test_conflict_blocks_generation():
    records = [
        {"course_name": "A", "weekday": "周一", "start_period": "1", "end_period": "2", "weeks": "1"},
        {"course_name": "B", "weekday": "周一", "start_period": "2", "end_period": "3", "weeks": "1"},
    ]
    _, _, errors = generate_calendar(records, first_week_date=date(2026, 9, 7), total_weeks=1, week_start=0, schedule=SCHEDULE)
    assert any("时间冲突" in error for error in errors)


def test_missing_week_is_rejected():
    errors = validate_records([{"course_name": "A", "weekday": "周一", "start_period": "1", "end_period": "1", "weeks": ""}], 1, SCHEDULE)
    assert any("周次" in error for error in errors)
