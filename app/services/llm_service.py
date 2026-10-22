import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings
from app.schemas.assistant import (
    ActionProposal,
    IntentType,
    InterpretResponse,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are SARA, an intelligent, friendly personal assistant.
Your job is to understand user commands and extract actionable intent for reminders, calendar schedules, task completion, and queries.

Current local datetime: {current_time}
User timezone: {timezone}
{history_context}
You MUST return a JSON object with this exact structure:
{{
  "intent": "<INTENT_NAME>",
  "confidence": 0.95,
  "requires_clarification": false,
  "clarification_prompt": null,
  "action_proposal": {{
    "action_type": "<INTENT_NAME>",
    "parameters": {{ ... }}
  }},
  "speech_response": "<Natural conversational reply to speak or display to user>"
}}

Supported intents:
- CREATE_REMINDER: parameters {{ "title": string, "scheduled_time": ISO8601 string, "recurrence": "none"|"daily"|"weekdays"|"weekly"|"monthly", "priority": "LOW"|"MEDIUM"|"HIGH"|"URGENT", "category": string, "also_add_event": boolean, "event_start_time": Optional ISO8601 string, "event_end_time": Optional ISO8601 string }}
- CREATE_SCHEDULE: parameters {{ "title": string, "start_time": ISO8601 string, "end_time": ISO8601 string, "category": string, "also_remind_time": Optional ISO8601 string }}
- LIST_REMINDERS: parameters {{}}
- GET_TODAY_OVERVIEW: parameters {{}}
- GET_UPCOMING_EVENTS: parameters {{}}
- COMPLETE_TASK: parameters {{ "target_title": string }}
- DELETE_REMINDER: parameters {{ "target_title": string }}
- GET_PRODUCTIVITY_SUMMARY: parameters {{}}
- GET_TRACKER_BALANCE: parameters {{}}
- ADD_EXPENSE: parameters {{ "title": string, "amount": float, "type": "expense"|"income", "category": string }}
- GET_TRACKER_HABITS: parameters {{}}
- LOG_HABIT: parameters {{ "title": string }}
- GET_TRACKER_ACADEMICS: parameters {{}}
- GET_TRACKER_CAREER: parameters {{}}
- GET_TRACKER_WELLNESS: parameters {{}}
- LOG_WELLNESS: parameters {{ "mood": "ecstatic"|"happy"|"calm"|"tired"|"anxious"|"stressed", "water_glasses": Optional int, "sleep_hours": Optional float, "reflection": Optional string }}
- GET_TRACKERS_OVERVIEW: parameters {{}}
- CLARIFY_REQUEST: requires_clarification=true, clarification_prompt="..."
- UNSUPPORTED_REQUEST: speech_response="Friendly response to general conversation or greeting"

Guidelines:
1. Always interpret relative times ("in 5 minutes", "tomorrow at 3pm", "24th October afternoon session", "1 day before") relative to the Current local datetime provided.
   - For an "afternoon session" event on date X without explicit hours, use 14:00 to 17:00 on date X.
   - For "remind before 1 day" or "1 day before" an event, calculate 24 hours prior to the event (e.g. 23rd October 14:00).
2. For compound requests asking to both add an event and set a reminder (e.g., "add to event and remind me before 1 day"), use CREATE_SCHEDULE and include the "also_remind_time" parameter so both the calendar event and the reminder are saved.
3. If the user refers back to an earlier message or event from the recent conversation history (e.g. "ok also add to the event", "add this event too", "remind me then"), ALWAYS inherit the actual title, date, time, and session from the previous turn (for example, title: "NPTEL exam", date: 24th October afternoon 14:00) rather than misinterpreting words like "to the event" or "this" as the event title.
4. If tracker context (such as balance, habits, courses) is provided, incorporate the exact figures into speech_response naturally when responding to queries about balance, expenses, habits, or classes.
Return ONLY valid JSON. No markdown ticks, no preamble.
"""


class LLMAssistantService:
    """Interprets natural language using Gemini API with structured JSON output,

    falling back gracefully to deterministic parsing when offline or unconfigured.
    """

    @classmethod
    def is_available(cls) -> bool:
        return bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())

    @classmethod
    async def interpret_with_llm(
        cls,
        query: str,
        timezone: str = "UTC",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[InterpretResponse]:
        if not cls.is_available():
            return None

        api_key = settings.LLM_API_KEY.strip()
        raw_model = settings.LLM_MODEL or "gemini-2.5-flash"
        model = raw_model.replace("models/", "").strip()
        now_str = (context or {}).get("current_datetime") or datetime.now().isoformat()

        history_list = (context or {}).get("history") or []
        history_context = ""
        if history_list:
            history_lines = []
            for item in history_list:
                s = "User" if item.get("sender") == "user" or item.get("role") == "user" else "SARA"
                t = item.get("text", "").strip()
                if t:
                    history_lines.append(f"{s}: {t}")
            if history_lines:
                history_context = "\nRecent conversation history:\n" + "\n".join(history_lines) + "\n"

        trackers = (context or {}).get("trackers")
        if trackers and isinstance(trackers, dict):
            history_context += "\nUser's Current Personalized Life Trackers Data:\n"
            for k, v in trackers.items():
                history_context += f"- {k}: {v}\n"

        prompt = SYSTEM_PROMPT.format(
            current_time=now_str,
            timezone=timezone,
            history_context=history_context,
        )

        payload = {
            "system_instruction": {
                "parts": [{"text": prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": query}],
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        }

        candidate_models = [model]
        for m_name in [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
        ]:
            if m_name not in candidate_models:
                candidate_models.append(m_name)

        for current_model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            continue

                        content_parts = candidates[0].get("content", {}).get("parts", [])
                        if not content_parts:
                            continue

                        raw_json = content_parts[0].get("text", "").strip()
                        if raw_json.startswith("```"):
                            raw_json = raw_json.strip("`")
                            if raw_json.startswith("json"):
                                raw_json = raw_json[4:].strip()

                        parsed = json.loads(raw_json)
                        intent_str = parsed.get("intent", "UNSUPPORTED_REQUEST")
                        try:
                            intent_type = IntentType(intent_str)
                        except ValueError:
                            intent_type = IntentType.UNSUPPORTED_REQUEST

                        proposal = None
                        if parsed.get("action_proposal"):
                            proposal = ActionProposal(
                                action_type=parsed["action_proposal"].get("action_type", intent_str),
                                parameters=parsed["action_proposal"].get("parameters", {}),
                            )

                        return InterpretResponse(
                            intent=intent_type,
                            confidence=float(parsed.get("confidence", 0.95)),
                            requires_clarification=bool(parsed.get("requires_clarification", False)),
                            clarification_prompt=parsed.get("clarification_prompt"),
                            action_proposal=proposal,
                            speech_response=parsed.get(
                                "speech_response",
                                "I've processed your request.",
                            ),
                        )
                    else:
                        logger.warning(f"Model {current_model} returned {res.status_code}, trying next model...")
                        continue
            except Exception as e:
                logger.warning(f"Failed model {current_model} ({type(e).__name__}): {e}")
                continue

        return None

    @classmethod
    async def interpret_call_dialogue_with_llm(
        cls,
        user_speech: str,
        event_title: str,
        event_time: str,
        meeting_link: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Interprets in-call conversational turns using Gemini with action extraction and natural voice response."""
        if not cls.is_available():
            return None

        api_key = settings.LLM_API_KEY.strip()
        raw_model = settings.LLM_MODEL or "gemini-2.5-flash"
        model = raw_model.replace("models/", "").strip()

        history_context = ""
        if history:
            h_lines = []
            for item in history:
                role = "User" if item.get("role") == "user" or item.get("sender") == "user" else "SARA"
                t = item.get("text", "").strip()
                if t:
                    h_lines.append(f"{role}: {t}")
            if h_lines:
                history_context = "\nCall Dialogue History:\n" + "\n".join(h_lines) + "\n"

        prompt = f"""You are SARA, an intelligent, empathetic, and proactive AI voice assistant calling the user about their upcoming event.
Current Reminder Details:
- Event: "{event_title}"
- Scheduled Time: {event_time}
{f'- Meeting Link: {meeting_link}' if meeting_link else ''}
{history_context}

The user just spoke the following words on the phone call:
"{user_speech}"

Analyze the user's speech and return JSON with the exact action to perform:
1. "CONFIRM_ATTENDANCE": User will attend or is available (e.g. "yes", "i am free", "i will join", "ready").
   - STRICT: ONLY if they DO NOT say they are unavailable, busy, or asking to reschedule!
   - should_end_call: true (or false if asking to open meeting link)
   - should_listen: false
   - speech_response: Friendly confirmation under 20 words.
2. "RESCHEDULE_EVENT": User asks to reschedule AND gives a time or day (e.g. "reschedule to tomorrow morning 9am", "move it to tomorrow", "push it to 5:30", "reschedule to 4pm").
   - action_parameters: {{"new_time": "extracted time or date phrase, e.g. tomorrow morning 9am", "event_title": "{event_title}"}}
   - should_end_call: true
   - should_listen: false
   - speech_response: Confirming the reschedule and calendar update under 20 words (e.g. "All set! I have rescheduled {event_title} to tomorrow morning at 9am and updated your calendar.").
3. "OFFER_RESCHEDULE": User says they are NOT available, busy, cannot make it, or asks to reschedule WITHOUT giving a specific time (e.g. "i am not available right now and asked to reschedule it", "i'm busy", "can't attend right now").
   - action_parameters: {{"event_title": "{event_title}"}}
   - should_end_call: false
   - should_listen: true
   - speech_response: Empathetic response under 20 words asking when they would like to reschedule to.
4. "SNOOZE_REMINDER": User asks for another reminder or snooze (e.g. "remind me in 15 mins", "call me back later", "snooze").
   - action_parameters: {{"snooze_minutes": 15, "event_title": "{event_title}"}}
   - should_end_call: true
   - should_listen: false
   - speech_response: Confirming snooze under 20 words.
5. "OPEN_MEETING_LINK": User wants to open or join the meeting link.
   - action_parameters: {{"meeting_link": "{meeting_link}"}}
   - should_end_call: true
   - should_listen: false
   - speech_response: Confirming link open under 20 words.
6. "CLARIFY": Unclear speech.
   - action_parameters: {{"event_title": "{event_title}"}}
   - should_end_call: false
   - should_listen: true
   - speech_response: Politely ask for clarification under 20 words.

CRITICAL RULES:
- If user says "not available", "can't make it", "busy", or "reschedule", NEVER return CONFIRM_ATTENDANCE!
- speech_response must be spoken naturally: NO asterisks, NO markdown, NO quotes.
- Return ONLY valid JSON:
{{"action": "...", "action_parameters": {{...}}, "speech_response": "...", "should_end_call": boolean, "should_listen": boolean}}
"""

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1},
        }

        candidate_models = [model, "gemini-flash-lite-latest", "gemini-3.5-flash-lite"]
        for cur_model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{cur_model}:generateContent?key={api_key}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            continue
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if not parts:
                            continue
                        raw = parts[0].get("text", "").strip()
                        if raw.startswith("```"):
                            raw = raw.strip("`")
                            if raw.startswith("json"):
                                raw = raw[4:].strip()
                        return json.loads(raw)
            except Exception as e:
                logger.warning(f"Call dialogue LLM failed with {cur_model}: {e}")
                continue

        return None
