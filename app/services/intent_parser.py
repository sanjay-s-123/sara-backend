import re
from datetime import timedelta
from typing import Dict, Any, Optional
from app.schemas.assistant import IntentType, InterpretResponse, ActionProposal
from app.services.date_time_parser import DateTimeParser


class IntentParser:
    """Hybrid intent processor with deterministic zero-latency patterns and AI semantic fallback.

    Order matters: read / complete / delete intents are evaluated before the
    create-reminder intent, because phrases like "list my reminders" or
    "delete the reminder" also contain the word "reminder".
    """

    GREETINGS = ("hi", "hello", "hey", "good morning", "good afternoon", "good evening", "hii", "yo")
    THANKS = ("thank", "thanks", "thx")

    @classmethod
    def parse_command(
        cls,
        query: str,
        timezone: str = "UTC",
        context: Optional[Dict[str, Any]] = None,
    ) -> InterpretResponse:
        clean = query.strip()
        lower = clean.lower().rstrip("?!. ")

        # 0. Small talk & help -------------------------------------------------
        if lower in cls.GREETINGS or re.fullmatch(r"(?:hi|hello|hey)(?:\s+\w+)?", lower):
            return cls._chat(
                "Hi! I can set reminders, add events to your calendar, show today's plan, "
                "list your reminders, or mark tasks done. What would you like?"
            )
        if any(lower.startswith(t) for t in cls.THANKS):
            return cls._chat("You're welcome! Anything else I can help with?")
        if re.search(r"\b(?:help|what can you do|how do i use)\b", lower):
            return cls._chat(
                "Try things like:\n"
                "• \"Remind me to call Mom at 7 PM\"\n"
                "• \"Schedule a team meeting tomorrow at 3 PM\"\n"
                "• \"Add birthday party on 22 December at 6 PM\"\n"
                "• \"What's my schedule today?\"\n"
                "• \"List my reminders\"\n"
                "• \"Mark gym as done\""
            )

        # Commands that start by asking to create something must never be read
        # as delete/complete (e.g. "Remind me to cancel Netflix").
        is_create_cmd = bool(re.match(
            r"^(?:please\s+)?(?:can you\s+)?(?:remind|remaind|set|create|add|schedule|book|plan|arrange)\b", lower
        ))

        # 1. DELETE_REMINDER ---------------------------------------------------
        delete_match = None if is_create_cmd else re.search(
            r"\b(?:delete|remove|cancel)\s+(?:the\s+|my\s+)?(?:reminder\s+(?:for\s+|about\s+|to\s+)?)?(.+?)(?:\s+reminder)?$",
            lower,
        )
        if delete_match and ("reminder" in lower or not re.search(r"\b(?:meeting|event)\b", lower)):
            target = cls._clean_target(delete_match.group(1))
            return InterpretResponse(
                intent=IntentType.DELETE_REMINDER,
                confidence=0.9,
                requires_clarification=False,
                action_proposal=ActionProposal(
                    action_type="DELETE_REMINDER",
                    parameters={"target_title": target},
                ),
                speech_response=f"Deleting '{target or 'that reminder'}'.",
            )

        # 2. COMPLETE_TASK -----------------------------------------------------
        complete_patterns = [
            r"\b(?:i\s+)?(?:finished|completed|done with)\s+(?:my\s+|the\s+)?(.+?)(?:\.|$)",
            r"\bmark\s+(?:the\s+|my\s+)?(.+?)\s+as\s+(?:done|complete|completed|finished)\b",
            r"^(?:the\s+|my\s+)?(.+?)\s+is\s+(?:done|completed|finished)$",
        ]
        if not is_create_cmd and (
            any(p in lower for p in ["mark as completed", "mark it as completed", "mark as done", "mark it done"])
            or any(re.search(p, lower) for p in complete_patterns)
        ):
            target = None
            for pattern in complete_patterns:
                m = re.search(pattern, lower)
                if m:
                    target = cls._clean_target(m.group(1).split(".")[0])
                    if target:
                        break
            return InterpretResponse(
                intent=IntentType.COMPLETE_TASK,
                confidence=0.92,
                requires_clarification=False,
                action_proposal=ActionProposal(
                    action_type="COMPLETE_TASK",
                    parameters={"target_title": target},
                ),
                speech_response=f"Well done! I've marked '{target or 'task'}' as completed.",
            )

        # 3. LIST_REMINDERS ----------------------------------------------------
        if re.search(r"\b(?:list|show|see|view|what are|what're|any|check)\b.*\breminders?\b", lower) \
                or re.fullmatch(r"(?:my\s+)?(?:active\s+|pending\s+)?reminders", lower):
            return InterpretResponse(
                intent=IntentType.LIST_REMINDERS,
                confidence=0.98,
                requires_clarification=False,
                speech_response="Here are your active reminders.",
            )

        # 4. GET_TODAY_OVERVIEW -----------------------------------------------
        today_phrases = [
            "today's schedule", "schedule today", "schedule for today", "what do i have",
            "plans today", "plan today", "today's plan", "agenda today", "today's agenda",
            "my day", "what's on today", "what is on today", "anything today",
        ]
        if any(p in lower for p in today_phrases) or re.search(r"\bwhat'?s?\s+(?:is\s+)?my\s+schedule\b", lower):
            return InterpretResponse(
                intent=IntentType.GET_TODAY_OVERVIEW,
                confidence=0.98,
                requires_clarification=False,
                speech_response="Here is your overview for today.",
            )

        # 5. GET_UPCOMING_EVENTS ----------------------------------------------
        if re.search(r"\b(?:upcoming|next|future)\s+(?:events?|meetings?|schedule)\b", lower) \
                or re.search(r"\b(?:list|show|see|view)\b.*\b(?:events?|meetings?|calendar|schedules?)\b", lower) \
                or re.search(r"\bwhat'?s\s+(?:coming\s+up|next)\b", lower):
            return InterpretResponse(
                intent=IntentType.GET_UPCOMING_EVENTS,
                confidence=0.95,
                requires_clarification=False,
                speech_response="Here are your upcoming events.",
            )

        # 6. GET_PRODUCTIVITY_SUMMARY -----------------------------------------
        if any(p in lower for p in ["what have i completed", "productivity", "how productive", "my progress", "how am i doing"]):
            return InterpretResponse(
                intent=IntentType.GET_PRODUCTIVITY_SUMMARY,
                confidence=0.95,
                requires_clarification=False,
                speech_response="Here's your productivity summary.",
            )

        # 7. CREATE_REMINDER ---------------------------------------------------
        # Matches: "remind me...", "set a reminder...", "remaind 5 mins before...", "I have my internal at 11:45 remind 5 mins before"
        is_reminder_intent = bool(
            re.search(r"\b(?:remind|remaind|reminder)\b", lower)
            or re.search(r"^(?:set|create|add) (?:a )?reminder\b", lower)
        )

        if is_reminder_intent:
            recurrence = cls._detect_recurrence(lower)
            intent = IntentType.CREATE_RECURRING_REMINDER if recurrence != "none" else IntentType.CREATE_REMINDER

            resolved_time, needs_clarify, clarify_prompt = DateTimeParser.resolve_datetime(
                clean, user_tz=timezone
            )

            if needs_clarify:
                return InterpretResponse(
                    intent=IntentType.CLARIFY_REQUEST,
                    confidence=0.9,
                    requires_clarification=True,
                    clarification_prompt=clarify_prompt,
                    speech_response=clarify_prompt or "Could you clarify the timing?",
                )

            # Extract title:
            # Case A: "I have my internal at 11:45 remaind 5 mins before" -> title: "Internal"
            event_match = re.search(r"(?:i have|got)\s+(?:my\s+)?([a-zA-Z0-9\s]+?)\s+(?:at|on|tomorrow|in)\b", lower)
            title = None
            if event_match:
                title = event_match.group(1).strip()
            else:
                title_match = re.search(
                    r"(?:remind|remaind)(?:\s+me)?\s+(?:every\s+\w+\s+(?:at\s+[\d:]+\s*(?:am|pm)?\s+)?)?(?:to\s+|about\s+|of\s+)?(.+?)(?:\s+(?:in|tomorrow|today|tonight|at|every|on|daily|\d+\s*min)\b|$)",
                    lower,
                )
                if title_match:
                    title = title_match.group(1).strip()
                if not title or title in ("me", "every"):
                    set_match = re.search(r"reminder\s+(?:for|to|about)\s+(.+?)(?:\s+(?:in|tomorrow|today|at|on)\b|$)", lower)
                    if set_match:
                        title = set_match.group(1).strip()
                # "Remind me every day at 6 AM to exercise"
                trailing = re.search(r"\bto\s+(.+)$", lower)
                if (not title or title in ("me", "every") or title.startswith("every")) and trailing:
                    title = trailing.group(1).strip()

            if not title or title in ["me", ""]:
                title = "Reminder"

            title = re.sub(r"\s+(?:tomorrow|today|tonight|at \d.*|in \d.*|\d+\s*mins?.*|every .*|daily)$", "", title).strip()
            if not title:
                title = "Reminder"
            title = title[0].upper() + title[1:]

            iso_time = resolved_time.isoformat() if resolved_time else None
            time_display = resolved_time.strftime("%I:%M %p") if resolved_time else "the requested time"

            return InterpretResponse(
                intent=intent,
                confidence=0.98,
                requires_clarification=False,
                action_proposal=ActionProposal(
                    action_type="CREATE_REMINDER",
                    parameters={
                        "title": title,
                        "scheduled_time": iso_time,
                        "priority": cls._detect_priority(lower),
                        "category": cls._detect_category(lower),
                        "recurrence": recurrence,
                    },
                ),
                speech_response=f"Of course! I've scheduled a reminder for '{title}' at {time_display}.",
            )

        # 8. CREATE_SCHEDULE / MEETING / EVENT --------------------------------
        schedule_trigger = (
            re.search(r"\b(?:schedule|book|set up|plan|arrange)\s+(?:a\s+|an\s+|my\s+)?", lower)
            or re.search(r"\badd\b.+\b(?:to\s+(?:my\s+)?calendar|event|meeting|appointment|birthday|party)\b", lower)
            or re.search(r"\b(?:i have|there is|there's)\s+(?:a\s+|an\s+|my\s+)?.+\b(?:on|at|tomorrow)\b", lower)
            or re.search(r"\b(?:meeting|appointment|birthday|party|interview|exam|call)\b.+\b(?:on|at|tomorrow|today)\b", lower)
        )
        if schedule_trigger:
            # Ambiguous rescheduling ("move my meeting to Friday evening") needs a precise time.
            resolved_time, needs_clarify, clarify_prompt = DateTimeParser.resolve_datetime(
                clean, user_tz=timezone
            )
            if needs_clarify:
                return InterpretResponse(
                    intent=IntentType.CLARIFY_REQUEST,
                    confidence=0.9,
                    requires_clarification=True,
                    clarification_prompt=clarify_prompt,
                    speech_response=clarify_prompt or "Could you please clarify the meeting time?",
                )

            title = cls._extract_event_title(lower)
            end_time = (resolved_time + timedelta(hours=1)) if resolved_time else None

            return InterpretResponse(
                intent=IntentType.CREATE_SCHEDULE,
                confidence=0.96,
                requires_clarification=False,
                action_proposal=ActionProposal(
                    action_type="CREATE_SCHEDULE",
                    parameters={
                        "title": title,
                        "start_time": resolved_time.isoformat() if resolved_time else None,
                        "end_time": end_time.isoformat() if end_time else None,
                        "category": cls._detect_event_category(lower),
                    },
                ),
                speech_response=f"I've added '{title}' to your schedule.",
            )

        # 9. Personalized Life Trackers ---------------------------------------
        if any(w in lower for w in ["account balance", "net balance", "my balance", "expense balance", "how much money", "how much spent", "how much did i spend", "expense tracker", "my expenses"]):
            return InterpretResponse(
                intent=IntentType.GET_TRACKER_BALANCE,
                confidence=0.95,
                requires_clarification=False,
                action_proposal=ActionProposal(action_type="GET_TRACKER_BALANCE", parameters={}),
                speech_response="Checking your expense tracker balance...",
            )

        if any(w in lower for w in ["my habit", "my habits", "habit streak", "daily discipline", "habits today", "habit progress"]):
            return InterpretResponse(
                intent=IntentType.GET_TRACKER_HABITS,
                confidence=0.95,
                requires_clarification=False,
                action_proposal=ActionProposal(action_type="GET_TRACKER_HABITS", parameters={}),
                speech_response="Checking your daily habits...",
            )

        if any(w in lower for w in ["my attendance", "course attendance", "academic attendance", "upcoming assignments", "assignments due", "my homework", "my courses"]):
            return InterpretResponse(
                intent=IntentType.GET_TRACKER_ACADEMICS,
                confidence=0.95,
                requires_clarification=False,
                action_proposal=ActionProposal(action_type="GET_TRACKER_ACADEMICS", parameters={}),
                speech_response="Checking your academics and attendance...",
            )

        if any(w in lower for w in ["my projects", "active projects", "career tracker", "job application", "job applications", "internship application"]):
            return InterpretResponse(
                intent=IntentType.GET_TRACKER_CAREER,
                confidence=0.95,
                requires_clarification=False,
                action_proposal=ActionProposal(action_type="GET_TRACKER_CAREER", parameters={}),
                speech_response="Checking your career projects and applications...",
            )

        if any(w in lower for w in ["wellness", "my mood", "sleep hours", "water glasses", "hydration tracker", "water intake"]):
            return InterpretResponse(
                intent=IntentType.GET_TRACKER_WELLNESS,
                confidence=0.95,
                requires_clarification=False,
                action_proposal=ActionProposal(action_type="GET_TRACKER_WELLNESS", parameters={}),
                speech_response="Checking your daily wellness and reflection...",
            )

        if any(w in lower for w in ["life os", "trackers overview", "tracker summary", "all trackers", "all my trackers"]):
            return InterpretResponse(
                intent=IntentType.GET_TRACKERS_OVERVIEW,
                confidence=0.95,
                requires_clarification=False,
                action_proposal=ActionProposal(action_type="GET_TRACKERS_OVERVIEW", parameters={}),
                speech_response="Gathering your Life OS tracker summary...",
            )

        # 10. Rescheduling requests we can't safely automate yet ---------------
        if re.search(r"\b(?:move|reschedule|postpone|shift)\b", lower):
            resolved_time, needs_clarify, clarify_prompt = DateTimeParser.resolve_datetime(clean, user_tz=timezone)
            prompt = clarify_prompt if needs_clarify else (
                "Rescheduling by voice isn't supported yet — open the event in your calendar to change its time."
            )
            return InterpretResponse(
                intent=IntentType.CLARIFY_REQUEST,
                confidence=0.7,
                requires_clarification=True,
                clarification_prompt=prompt,
                speech_response=prompt,
            )

        # 11. Fallback clarification ------------------------------------------
        return InterpretResponse(
            intent=IntentType.UNSUPPORTED_REQUEST,
            confidence=0.4,
            requires_clarification=True,
            clarification_prompt="I didn't quite understand that. Would you like to create a reminder, schedule an event, or see today's plan?",
            speech_response="I didn't quite catch that. Would you like me to create a reminder or schedule an event?",
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _chat(text: str) -> InterpretResponse:
        return InterpretResponse(
            intent=IntentType.UNSUPPORTED_REQUEST,
            confidence=1.0,
            requires_clarification=False,
            speech_response=text,
        )

    @staticmethod
    def _clean_target(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        target = re.sub(r"\b(?:task|reminder|it|please|now)\b", "", raw).strip(" .,'\"")
        target = re.sub(r"\s+", " ", target)
        return target or None

    @staticmethod
    def _detect_recurrence(lower: str) -> str:
        if re.search(r"\b(?:every\s+weekday|weekdays)\b", lower):
            return "weekdays"
        if re.search(r"\b(?:every\s+week|weekly|every\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", lower):
            return "weekly"
        if re.search(r"\b(?:every\s+month|monthly)\b", lower):
            return "monthly"
        if re.search(r"\b(?:every\s+day|everyday|daily|every\s+morning|every\s+night|every\s+evening)\b", lower) \
                or "every" in lower:
            return "daily"
        return "none"

    @staticmethod
    def _detect_priority(lower: str) -> str:
        if re.search(r"\b(?:urgent|asap|critical)\b", lower):
            return "URGENT"
        if re.search(r"\b(?:important|high priority)\b", lower):
            return "HIGH"
        if re.search(r"\blow priority\b", lower):
            return "LOW"
        return "MEDIUM"

    @staticmethod
    def _detect_category(lower: str) -> str:
        if re.search(r"\b(?:meeting|work|office|client|project|deadline|report)\b", lower):
            return "Work"
        if re.search(r"\b(?:study|exam|internal|assignment|homework|class|lecture|revise|notes)\b", lower):
            return "Study"
        if re.search(r"\b(?:medicine|pill|tablet|doctor|gym|workout|exercise|water|walk)\b", lower):
            return "Health"
        if re.search(r"\b(?:mom|dad|family|friend|birthday|call|groceries|shopping)\b", lower):
            return "Personal"
        return "General"

    @staticmethod
    def _detect_event_category(lower: str) -> str:
        if "birthday" in lower:
            return "Birthday"
        if re.search(r"\b(?:meeting|call|sync|standup|interview)\b", lower):
            return "Meeting"
        if re.search(r"\b(?:doctor|dentist|gym|hospital|checkup)\b", lower):
            return "Health"
        if re.search(r"\b(?:work|office|client|project)\b", lower):
            return "Work"
        return "General"

    @staticmethod
    def _extract_event_title(lower: str) -> str:
        patterns = [
            r"(?:schedule|book|set up|plan|arrange)\s+(?:a\s+|an\s+|my\s+)?(.+?)(?:\s+(?:for|on|at|next|from|tomorrow|today|tonight|this|with\s+\w+\s+(?:on|at))\b|$)",
            r"add\s+(?:a\s+|an\s+|my\s+)?(.+?)(?:\s+(?:to\s+(?:my\s+)?calendar|for|on|at|next|tomorrow|today|tonight)\b|$)",
            r"(?:i have|there is|there's)\s+(?:a\s+|an\s+|my\s+)?(.+?)(?:\s+(?:on|at|tomorrow|today|tonight|next)\b|$)",
            r"^(?:my\s+)?(.+?)\s+(?:on|at|tomorrow|today|tonight)\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, lower)
            if m:
                title = m.group(1).strip(" .,")
                title = re.sub(r"\s+(?:event|to my calendar|to calendar)$", "", title).strip()
                if title and title not in ("a", "an", "my", "event"):
                    return title[0].upper() + title[1:]
        return "Event"
