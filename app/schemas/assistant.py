from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IntentType(str, Enum):
    CREATE_REMINDER = "CREATE_REMINDER"
    CREATE_SCHEDULE = "CREATE_SCHEDULE"
    LIST_REMINDERS = "LIST_REMINDERS"
    LIST_SCHEDULES = "LIST_SCHEDULES"
    GET_TODAY_OVERVIEW = "GET_TODAY_OVERVIEW"
    GET_UPCOMING_EVENTS = "GET_UPCOMING_EVENTS"
    UPDATE_REMINDER = "UPDATE_REMINDER"
    UPDATE_SCHEDULE = "UPDATE_SCHEDULE"
    DELETE_REMINDER = "DELETE_REMINDER"
    DELETE_SCHEDULE = "DELETE_SCHEDULE"
    COMPLETE_TASK = "COMPLETE_TASK"
    SEARCH_EVENTS = "SEARCH_EVENTS"
    CREATE_RECURRING_REMINDER = "CREATE_RECURRING_REMINDER"
    GET_PRODUCTIVITY_SUMMARY = "GET_PRODUCTIVITY_SUMMARY"
    GET_TRACKER_BALANCE = "GET_TRACKER_BALANCE"
    ADD_EXPENSE = "ADD_EXPENSE"
    GET_TRACKER_HABITS = "GET_TRACKER_HABITS"
    GET_TRACKER_ACADEMICS = "GET_TRACKER_ACADEMICS"
    GET_TRACKER_CAREER = "GET_TRACKER_CAREER"
    GET_TRACKER_WELLNESS = "GET_TRACKER_WELLNESS"
    GET_TRACKERS_OVERVIEW = "GET_TRACKERS_OVERVIEW"
    CLARIFY_REQUEST = "CLARIFY_REQUEST"
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"


class InterpretRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User command or utterance")
    timezone: str = Field(default="UTC", description="User IANA timezone identifier")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Conversation context")


class ActionProposal(BaseModel):
    action_type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class InterpretResponse(BaseModel):
    intent: IntentType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None
    action_proposal: Optional[ActionProposal] = None
    speech_response: str


class ExecuteRequest(BaseModel):
    action_type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None


class ExecuteResponse(BaseModel):
    success: bool
    record_id: Optional[str] = None
    message: str
    speech_response: str
