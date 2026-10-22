from datetime import datetime
import pytz
from app.services.date_time_parser import DateTimeParser


def test_relative_minutes():
    ref = datetime(2026, 10, 12, 10, 0, tzinfo=pytz.UTC)
    resolved, needs_clarify, _ = DateTimeParser.resolve_datetime(
        "Remind me in 30 minutes",
        user_tz="UTC",
        ref_time=ref,
    )
    assert not needs_clarify
    assert resolved is not None
    assert resolved.minute == 30
    assert resolved.hour == 10


def test_relative_hours():
    ref = datetime(2026, 10, 12, 10, 0, tzinfo=pytz.UTC)
    resolved, needs_clarify, _ = DateTimeParser.resolve_datetime(
        "Remind me in 2 hours",
        user_tz="UTC",
        ref_time=ref,
    )
    assert not needs_clarify
    assert resolved is not None
    assert resolved.hour == 12


def test_tomorrow_time():
    ref = datetime(2026, 10, 12, 10, 0, tzinfo=pytz.UTC)
    resolved, needs_clarify, _ = DateTimeParser.resolve_datetime(
        "Remind me tomorrow at 8 AM",
        user_tz="UTC",
        ref_time=ref,
    )
    assert not needs_clarify
    assert resolved is not None
    assert resolved.day == 13
    assert resolved.hour == 8


def test_ambiguous_evening_clarification():
    ref = datetime(2026, 10, 12, 10, 0, tzinfo=pytz.UTC)
    resolved, needs_clarify, prompt = DateTimeParser.resolve_datetime(
        "Move my meeting with Priya to Friday evening",
        user_tz="UTC",
        ref_time=ref,
    )
    assert needs_clarify
    assert resolved is None
    assert prompt is not None
    assert "evening" in prompt
