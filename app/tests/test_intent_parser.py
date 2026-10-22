from app.services.intent_parser import IntentParser
from app.schemas.assistant import IntentType


def test_create_reminder_intent():
    res = IntentParser.parse_command("Remind me to study physics tomorrow at 8 AM")
    assert res.intent == IntentType.CREATE_REMINDER
    assert not res.requires_clarification
    assert res.action_proposal is not None
    assert res.action_proposal.action_type == "CREATE_REMINDER"
    assert "Study physics" in res.action_proposal.parameters["title"]


def test_create_recurring_reminder_intent():
    res = IntentParser.parse_command("Remind me every day at 6 AM to exercise")
    assert res.intent == IntentType.CREATE_RECURRING_REMINDER
    assert res.action_proposal is not None
    assert res.action_proposal.parameters["recurrence"] == "daily"


def test_today_schedule_intent():
    res = IntentParser.parse_command("What do I have scheduled for today?")
    assert res.intent == IntentType.GET_TODAY_OVERVIEW
    assert not res.requires_clarification


def test_complete_task_intent():
    res = IntentParser.parse_command("I finished my assignment. Mark it as completed.")
    assert res.intent == IntentType.COMPLETE_TASK
    assert res.action_proposal is not None


def test_ambiguous_request_clarification():
    res = IntentParser.parse_command("Move my meeting with Priya to Friday evening")
    assert res.requires_clarification
    assert res.clarification_prompt is not None


def test_user_internal_reminder_query():
    res = IntentParser.parse_command("I have my internal at 11:45 remaind 5 mins before the time")
    assert res.intent == IntentType.CREATE_REMINDER
    assert not res.requires_clarification
    assert res.action_proposal is not None
    assert res.action_proposal.parameters["title"] == "Internal"
    assert "11:40" in res.action_proposal.parameters["scheduled_time"] or "11:45" in res.speech_response
