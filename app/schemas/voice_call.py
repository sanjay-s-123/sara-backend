from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CallStatus(str, Enum):
    INITIATED = "INITIATED"
    RINGING = "RINGING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    BUSY = "BUSY"
    DECLINED = "DECLINED"
    FAILED = "FAILED"


class DialogueAction(str, Enum):
    GREETING = "GREETING"
    CONFIRM_ATTENDANCE = "CONFIRM_ATTENDANCE"
    OFFER_RESCHEDULE = "OFFER_RESCHEDULE"
    RESCHEDULE_EVENT = "RESCHEDULE_EVENT"
    OFFER_SNOOZE = "OFFER_SNOOZE"
    SNOOZE_REMINDER = "SNOOZE_REMINDER"
    CLARIFY = "CLARIFY"
    END_CALL = "END_CALL"
    OPEN_MEETING_LINK = "OPEN_MEETING_LINK"


class CallInitiateRequest(BaseModel):
    user_id: str
    event_id: str
    event_title: str
    event_time: str
    phone_number: Optional[str] = None
    lead_minutes: int = Field(default=5, ge=0)
    meeting_link: Optional[str] = None
    timezone: str = "UTC"


class CallInitiateResponse(BaseModel):
    session_id: str
    status: CallStatus
    message: str
    provider: str
    initial_speech: str


class CallDialogueRequest(BaseModel):
    session_id: str
    user_speech: str
    event_title: str
    event_time: str
    meeting_link: Optional[str] = None
    turn_index: int = 0
    history: List[Dict[str, str]] = Field(default_factory=list)
    timezone: str = "UTC"


class CallDialogueResponse(BaseModel):
    session_id: str
    speech_response: str
    action: DialogueAction
    action_parameters: Dict[str, Any] = Field(default_factory=dict)
    should_end_call: bool = False
    should_listen: bool = True


class CallStatusUpdate(BaseModel):
    session_id: str
    status: CallStatus
    call_sid: Optional[str] = None
    reason: Optional[str] = None
