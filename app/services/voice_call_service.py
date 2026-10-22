import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import httpx

from app.core.config import settings
from app.schemas.voice_call import (
    CallDialogueRequest,
    CallDialogueResponse,
    CallInitiateRequest,
    CallInitiateResponse,
    CallStatus,
    DialogueAction,
)
from app.services.llm_service import LLMAssistantService

logger = logging.getLogger(__name__)


class VoiceCallService:
    """Manages AI-driven proactive voice call reminders and conversational dialogues."""

    # In-memory session registry (session_id -> session state)
    _sessions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def generate_initial_speech(
        cls,
        event_title: str,
        event_time_str: str,
        lead_minutes: int = 5,
    ) -> str:
        lead_phrase = f"in {lead_minutes} minutes" if lead_minutes > 0 else "right now"
        return (
            f"Hi! This is Sara. I'm calling to remind you that you have {event_title} "
            f"scheduled for {event_time_str}, which is {lead_phrase}. "
            f"Are you available to attend the meeting?"
        )

    @classmethod
    async def initiate_call(cls, req: CallInitiateRequest) -> CallInitiateResponse:
        session_id = f"call_{uuid.uuid4().hex[:12]}"
        initial_speech = cls.generate_initial_speech(
            event_title=req.event_title,
            event_time_str=req.event_time,
            lead_minutes=req.lead_minutes,
        )

        session_record = {
            "session_id": session_id,
            "user_id": req.user_id,
            "event_id": req.event_id,
            "event_title": req.event_title,
            "event_time": req.event_time,
            "phone_number": req.phone_number,
            "meeting_link": req.meeting_link,
            "status": CallStatus.INITIATED,
            "created_at": datetime.now().isoformat(),
            "history": [{"role": "sara", "text": initial_speech}],
            "retries": 0,
        }
        cls._sessions[session_id] = session_record

        # Check if external telephony provider is configured (e.g. Twilio)
        provider = "in_app_device"
        if (
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and settings.TWILIO_FROM_NUMBER
            and req.phone_number
        ):
            provider = "twilio"
            try:
                await cls._dispatch_twilio_call(
                    session_id=session_id,
                    to_phone=req.phone_number,
                    initial_speech=initial_speech,
                )
                session_record["status"] = CallStatus.RINGING
            except Exception as e:
                logger.error(f"Failed to initiate Twilio call: {e}")
                # Gracefully fallback to in-app notification call
                provider = "in_app_device_fallback"
                session_record["status"] = CallStatus.INITIATED
        else:
            session_record["status"] = CallStatus.RINGING

        return CallInitiateResponse(
            session_id=session_id,
            status=session_record["status"],
            message=f"Voice call reminder initiated via {provider}.",
            provider=provider,
            initial_speech=initial_speech,
        )

    @classmethod
    async def _dispatch_twilio_call(
        cls,
        session_id: str,
        to_phone: str,
        initial_speech: str,
    ) -> None:
        """Dispatches an outbound call via Twilio REST API if credentials exist."""
        webhook_base = settings.VOICE_CALL_WEBHOOK_BASE_URL or f"http://{settings.HOST}:{settings.PORT}"
        twiml_url = f"{webhook_base}/api/voice-call/twiml?session_id={session_id}"
        status_url = f"{webhook_base}/api/voice-call/status?session_id={session_id}"

        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls.json"
        auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        data = {
            "To": to_phone,
            "From": settings.TWILIO_FROM_NUMBER,
            "Url": twiml_url,
            "StatusCallback": status_url,
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, data=data, auth=auth)
            resp.raise_for_status()
            res_json = resp.json()
            if session_id in cls._sessions:
                cls._sessions[session_id]["call_sid"] = res_json.get("sid")

    @classmethod
    def generate_twiml(cls, session_id: str) -> str:
        """Returns standard TwiML XML for carrier phone calls."""
        session = cls._sessions.get(session_id)
        speech = (
            session["history"][0]["text"]
            if session and session.get("history")
            else "Hi, this is Sara calling with your reminder. Are you available to attend?"
        )
        webhook_base = settings.VOICE_CALL_WEBHOOK_BASE_URL or f"http://{settings.HOST}:{settings.PORT}"
        action_url = f"{webhook_base}/api/voice-call/twiml-gather?session_id={session_id}"

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{action_url}" speechTimeout="auto" timeout="6">
        <Say voice="Polly.Joanna">{speech}</Say>
    </Gather>
    <Say voice="Polly.Joanna">I did not hear your response. I will follow up with a notification. Goodbye!</Say>
</Response>"""

    @classmethod
    async def process_dialogue(cls, req: CallDialogueRequest) -> CallDialogueResponse:
        """Processes conversational turns during the reminder call."""
        text = req.user_speech.strip()
        lower = text.lower()
        title = req.event_title or "your meeting"

        session = cls._sessions.get(req.session_id, {})
        meeting_link = req.meeting_link or session.get("meeting_link")

        # 1. Use Gemini LLM for conversational intelligence and understanding during the active voice call
        if LLMAssistantService.is_available():
            try:
                llm_res = await LLMAssistantService.interpret_call_dialogue_with_llm(
                    user_speech=text,
                    event_title=title,
                    event_time=req.event_time,
                    meeting_link=meeting_link,
                    history=req.history,
                )
                if llm_res and isinstance(llm_res, dict) and "action" in llm_res and "speech_response" in llm_res:
                    action_raw = llm_res.get("action", "CLARIFY")
                    try:
                        action_enum = DialogueAction(action_raw)
                    except ValueError:
                        action_enum = DialogueAction.CLARIFY

                    return CallDialogueResponse(
                        session_id=req.session_id,
                        speech_response=llm_res.get("speech_response", "").strip(),
                        action=action_enum,
                        action_parameters=llm_res.get("action_parameters", {}) or {},
                        should_end_call=bool(llm_res.get("should_end_call", False)),
                        should_listen=bool(llm_res.get("should_listen", True)),
                    )
            except Exception as e:
                logger.warning(f"VoiceCallService LLM call failed: {e}, falling back to deterministic rules")

        # 2. Deterministic Rule Fallback (Strict Negation & Reschedule Prioritization)
        has_negation = any(w in lower for w in ["not", "cannot", "can't", "don't", "no", "won't", "unavailable", "busy"])

        # Check Reschedule first
        if any(w in lower for w in ["reschedule", "move it", "postpone", "push it", "change time"]):
            time_match = re.search(r"\b([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm|a\.m\.|p\.m\.))\b", lower)
            day_match = re.search(r"\b(tomorrow|day after tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
            period_match = re.search(r"\b(morning|afternoon|evening|night)\b", lower)

            if time_match or day_match or period_match:
                parts = []
                if day_match:
                    parts.append(day_match.group(1))
                if period_match:
                    parts.append(period_match.group(1))
                if time_match:
                    parts.append(time_match.group(1))
                new_time_str = " ".join(parts).strip()
                speech = (
                    f"All set! I have rescheduled {title} to {new_time_str or 'the requested time'}. "
                    f"I've updated your schedule and calendar. Have a great day!"
                )
                return CallDialogueResponse(
                    session_id=req.session_id,
                    speech_response=speech,
                    action=DialogueAction.RESCHEDULE_EVENT,
                    action_parameters={"new_time": new_time_str, "event_title": title},
                    should_end_call=True,
                    should_listen=False,
                )
            speech = f"When would you prefer to reschedule {title} to?"
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.OFFER_RESCHEDULE,
                action_parameters={"event_title": title},
                should_end_call=False,
                should_listen=True,
            )

        # Check Unavailability next
        if has_negation or any(w in lower for w in ["running late", "stuck", "unavailable"]):
            speech = f"I understand you're not available right now. When would you prefer to reschedule {title} to?"
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.OFFER_RESCHEDULE,
                action_parameters={"event_title": title},
                should_end_call=False,
                should_listen=True,
            )

        # User confirms availability (STRICTLY ONLY IF NO NEGATION)
        affirmative_patterns = [
            r"\b(yes|yeah|yep|sure|i am|i will|attending|i'll attend|ready|joining|present)\b",
            r"\b(can make it|available|definitely|of course|gonna attend)\b",
        ]
        if not has_negation and any(re.search(pat, lower) for pat in affirmative_patterns):
            if meeting_link:
                speech = (
                    f"Great! I've noted that you're attending. Would you like me to open your "
                    f"meeting link for you now?"
                )
                return CallDialogueResponse(
                    session_id=req.session_id,
                    speech_response=speech,
                    action=DialogueAction.CONFIRM_ATTENDANCE,
                    action_parameters={"meeting_link": meeting_link},
                    should_end_call=False,
                    should_listen=True,
                )
            speech = f"Great! I've noted that you're attending. Best of luck with {title}! Have a wonderful day!"
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.CONFIRM_ATTENDANCE,
                action_parameters={},
                should_end_call=True,
                should_listen=False,
            )

        # 2. User answers to open link ("open it", "yes please", "open link")
        if any(w in lower for w in ["open", "join", "link", "meet link", "please do"]):
            speech = f"Opening {title} right now. Have a productive meeting!"
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.OPEN_MEETING_LINK,
                action_parameters={"meeting_link": meeting_link},
                should_end_call=True,
                should_listen=False,
            )

        # 3. User requests another reminder / snooze
        snooze_match = re.search(r"(\d+)\s*(mins?|minutes?|hours?)", lower)
        if any(w in lower for w in ["remind me in", "snooze", "remind me later", "another reminder", "remind again"]):
            mins = 10
            if snooze_match:
                val = int(snooze_match.group(1))
                unit = snooze_match.group(2)
                mins = val * 60 if "hour" in unit else val

            speech = (
                f"Got it! I will call and remind you again in {mins} minutes for {title}. "
                f"Talk to you soon!"
            )
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.SNOOZE_REMINDER,
                action_parameters={"snooze_minutes": mins, "event_title": title},
                should_end_call=True,
                should_listen=False,
            )

        # 4. User requests rescheduling with specific time ("reschedule to 4 pm", "move to tomorrow 3pm")
        if any(w in lower for w in ["reschedule", "move it", "postpone", "push it", "change time"]):
            time_match = re.search(r"(?:to|at|for)\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm|a\.m\.|p\.m\.))", lower)
            day_match = re.search(r"\b(tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)

            if time_match or day_match:
                new_time_str = " ".join(filter(None, [day_match.group(1) if day_match else "", time_match.group(1) if time_match else ""])).strip()
                speech = (
                    f"All set! I have rescheduled {title} to {new_time_str or 'the requested time'}. "
                    f"I've updated your schedule. Goodbye!"
                )
                return CallDialogueResponse(
                    session_id=req.session_id,
                    speech_response=speech,
                    action=DialogueAction.RESCHEDULE_EVENT,
                    action_parameters={"new_time": new_time_str, "event_title": title},
                    should_end_call=True,
                    should_listen=False,
                )
            speech = f"When would you prefer to reschedule {title} to?"
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.OFFER_RESCHEDULE,
                action_parameters={"event_title": title},
                should_end_call=False,
                should_listen=True,
            )

        # 5. User indicates unavailability without specifying next step ("no", "can't", "unavailable", "busy")
        unavail_patterns = [
            r"\b(no|nope|not available|can't make it|cannot attend|busy|won't make it|unavailable)\b",
            r"\b(stuck|running late|can't attend)\b",
        ]
        if any(re.search(pat, lower) for pat in unavail_patterns):
            speech = (
                f"I understand. Would you like me to reschedule {title} for you, or set another reminder?"
            )
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.OFFER_RESCHEDULE,
                action_parameters={"event_title": title},
                should_end_call=False,
                should_listen=True,
            )

        # 6. User answers with a raw time when asked about rescheduling ("tomorrow at 4pm", "at 5pm")
        raw_time_match = re.search(r"\b([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm))\b", lower)
        if raw_time_match or "tomorrow" in lower:
            target_str = lower
            speech = (
                f"All set! I have updated {title} to {target_str}. "
                f"Everything is confirmed. Have a great day!"
            )
            return CallDialogueResponse(
                session_id=req.session_id,
                speech_response=speech,
                action=DialogueAction.RESCHEDULE_EVENT,
                action_parameters={"new_time": target_str, "event_title": title},
                should_end_call=True,
                should_listen=False,
            )

        # 7. Fallback / Unclear utterance -> Clarify politely
        speech = (
            f"Could you please clarify if you're available to attend {title}, "
            f"or if you would like me to reschedule it or remind you later?"
        )
        return CallDialogueResponse(
            session_id=req.session_id,
            speech_response=speech,
            action=DialogueAction.CLARIFY,
            action_parameters={"event_title": title},
            should_end_call=False,
            should_listen=True,
        )

    @classmethod
    def record_call_status(
        cls,
        session_id: str,
        status: CallStatus,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Records final or intermediate call status, triggering retry if applicable."""
        session = cls._sessions.get(session_id)
        if not session:
            return {"session_id": session_id, "status": status, "retry_scheduled": False}

        session["status"] = status
        session["updated_at"] = datetime.now().isoformat()
        if reason:
            session["failure_reason"] = reason

        retry_scheduled = False
        # Retry policy on unanswered / busy calls if under max limit
        if status in [CallStatus.MISSED, CallStatus.BUSY, CallStatus.FAILED]:
            retries = session.get("retries", 0)
            if retries < settings.VOICE_CALL_MAX_RETRIES:
                session["retries"] = retries + 1
                retry_scheduled = True
                logger.info(
                    f"Call {session_id} ended with {status}. Retry #{session['retries']} scheduled."
                )

        return {
            "session_id": session_id,
            "status": status,
            "retry_scheduled": retry_scheduled,
            "retries": session.get("retries", 0),
        }
