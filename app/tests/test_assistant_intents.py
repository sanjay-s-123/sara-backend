from datetime import datetime
import pytz
from app.services.intent_parser import IntentParser
from app.services.date_time_parser import DateTimeParser
from app.schemas.assistant import IntentType


def test_list_reminders_is_not_create():
    for q in ["List my reminders", "Show my reminders", "what are my reminders?", "my reminders"]:
        res = IntentParser.parse_command(q)
        assert res.intent == IntentType.LIST_REMINDERS, q


def test_today_overview_variants():
    for q in ["What's my schedule today?", "today's plan", "what do I have today"]:
        res = IntentParser.parse_command(q)
        assert res.intent == IntentType.GET_TODAY_OVERVIEW, q


def test_upcoming_events():
    res = IntentParser.parse_command("Show my upcoming events")
    assert res.intent == IntentType.GET_UPCOMING_EVENTS


def test_create_birthday_event_with_calendar_date():
    res = IntentParser.parse_command("Add birthday party on 22 December at 6 PM", timezone="Asia/Kolkata")
    assert res.intent == IntentType.CREATE_SCHEDULE
    params = res.action_proposal.parameters
    assert params["category"] == "Birthday"
    assert "-12-22T18:00" in params["start_time"]
    assert "Birthday party" in params["title"]


def test_schedule_meeting_tomorrow():
    res = IntentParser.parse_command("Schedule a team meeting tomorrow at 3 PM")
    assert res.intent == IntentType.CREATE_SCHEDULE
    assert res.action_proposal.parameters["title"] == "Team meeting"
    assert "T15:00" in res.action_proposal.parameters["start_time"]


def test_complete_named_task():
    res = IntentParser.parse_command("Mark gym as done")
    assert res.intent == IntentType.COMPLETE_TASK
    assert res.action_proposal.parameters["target_title"] == "gym"


def test_complete_resolves_target_from_sentence():
    res = IntentParser.parse_command("I finished my assignment. Mark it as completed.")
    assert res.action_proposal.parameters["target_title"] == "assignment"


def test_delete_reminder():
    res = IntentParser.parse_command("Delete the reminder for groceries")
    assert res.intent == IntentType.DELETE_REMINDER
    assert res.action_proposal.parameters["target_title"] == "groceries"


def test_remind_to_cancel_is_still_create():
    res = IntentParser.parse_command("Remind me to cancel Netflix tomorrow at 9 AM")
    assert res.intent == IntentType.CREATE_REMINDER
    assert "cancel netflix" in res.action_proposal.parameters["title"].lower()


def test_greeting_is_friendly_not_clarification():
    res = IntentParser.parse_command("Hello")
    assert not res.requires_clarification
    assert "reminder" in res.speech_response.lower()


def test_priority_and_category_detection():
    res = IntentParser.parse_command("Remind me to take medicine at 9 PM, it's important")
    params = res.action_proposal.parameters
    assert params["priority"] == "HIGH"
    assert params["category"] == "Health"


def test_calendar_date_rolls_to_next_year_when_past():
    tz = pytz.timezone("Asia/Kolkata")
    ref = tz.localize(datetime(2026, 10, 17, 9, 0))
    resolved, _, _ = DateTimeParser.resolve_datetime("on 5 January at 10 AM", "Asia/Kolkata", ref)
    assert resolved.year == 2027 and resolved.month == 1 and resolved.day == 5
