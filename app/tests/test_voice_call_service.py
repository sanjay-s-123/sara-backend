import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.voice_call import (
    CallDialogueRequest,
    CallInitiateRequest,
    CallStatus,
    DialogueAction,
)
from app.services.voice_call_service import VoiceCallService

client = TestClient(app)


def test_voice_call_health():
    response = client.get("/api/voice-call/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "proactive_reminder_call" in data["features"]


def test_initiate_call_generates_correct_greeting():
    req = CallInitiateRequest(
        user_id="user_test_1",
        event_id="evt_123",
        event_title="Google Meet meeting",
        event_time="11:00 AM",
        lead_minutes=5,
        phone_number="+1234567890",
        meeting_link="https://meet.google.com/abc-defg-hij",
    )
    res = asyncio.run(VoiceCallService.initiate_call(req))
    assert res.session_id.startswith("call_")
    assert "Google Meet meeting" in res.initial_speech
    assert "11:00 AM" in res.initial_speech
    assert "in 5 minutes" in res.initial_speech
    assert "Are you available to attend the meeting?" in res.initial_speech


def test_dialogue_user_confirms_attendance():
    req = CallDialogueRequest(
        session_id="session_test_1",
        user_speech="Yes I am available to attend",
        event_title="Google Meet meeting",
        event_time="11:00 AM",
        meeting_link="https://meet.google.com/abc-defg-hij",
    )
    res = asyncio.run(VoiceCallService.process_dialogue(req))
    assert res.action == DialogueAction.CONFIRM_ATTENDANCE
    assert any(w in res.speech_response.lower() for w in ["attend", "attendance", "joining", "meeting"])


def test_dialogue_user_unavailable_offers_reschedule():
    req = CallDialogueRequest(
        session_id="session_test_2",
        user_speech="No, I can't attend, I am stuck in traffic",
        event_title="Google Meet meeting",
        event_time="11:00 AM",
    )
    res = asyncio.run(VoiceCallService.process_dialogue(req))
    assert res.action == DialogueAction.OFFER_RESCHEDULE
    assert "reschedule" in res.speech_response.lower()
    assert res.should_end_call is False
    assert res.should_listen is True


def test_dialogue_user_reschedules_to_tomorrow():
    req = CallDialogueRequest(
        session_id="session_test_3",
        user_speech="Please reschedule to tomorrow at 4 pm",
        event_title="Google Meet meeting",
        event_time="11:00 AM",
    )
    res = asyncio.run(VoiceCallService.process_dialogue(req))
    assert res.action == DialogueAction.RESCHEDULE_EVENT
    assert "tomorrow" in res.action_parameters.get("new_time", "")
    assert res.should_end_call is True


def test_dialogue_user_requests_snooze():
    req = CallDialogueRequest(
        session_id="session_test_4",
        user_speech="Remind me in 15 minutes",
        event_title="Google Meet meeting",
        event_time="11:00 AM",
    )
    res = asyncio.run(VoiceCallService.process_dialogue(req))
    assert res.action == DialogueAction.SNOOZE_REMINDER
    assert res.action_parameters.get("snooze_minutes") == 15
    assert "15" in res.speech_response or "fifteen" in res.speech_response.lower()
    assert res.should_end_call is True


def test_dialogue_unclear_response_asks_clarification():
    req = CallDialogueRequest(
        session_id="session_test_5",
        user_speech="hmm wait what is this",
        event_title="Google Meet meeting",
        event_time="11:00 AM",
    )
    res = asyncio.run(VoiceCallService.process_dialogue(req))
    assert res.action == DialogueAction.CLARIFY
    assert any(w in res.speech_response.lower() for w in ["clarify", "remind", "join", "would you like", "meeting"])
    assert res.should_end_call is False
    assert res.should_listen is True


def test_missed_call_triggers_retry_policy():
    status_res = VoiceCallService.record_call_status(
        session_id="session_test_retry",
        status=CallStatus.MISSED,
        reason="No answer after 30 seconds",
    )
    assert status_res["status"] == CallStatus.MISSED


def test_twiml_generation():
    twiml = VoiceCallService.generate_twiml("test_sess")
    assert "<Response>" in twiml
    assert "<Gather" in twiml
    assert "Sara" in twiml


def test_sarvam_tts_synthesize_fallback():
    response = client.post(
        "/api/voice-call/synthesize",
        json={
            "text": "Hello, this is Sara with your reminder.",
            "language_code": "en-IN",
            "speaker": "meera",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "provider" in data
    assert data["format"] in ["wav", "mp3"]
    assert "latency_ms" in data

