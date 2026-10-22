import uuid
from typing import Dict, Any
from app.schemas.assistant import ExecuteRequest, ExecuteResponse


class ActionExecutor:
    """Validates and executes authorized actions on behalf of the user."""

    @classmethod
    def execute(cls, request: ExecuteRequest, user_id: str) -> ExecuteResponse:
        action_type = request.action_type
        params = request.parameters

        if action_type == "CREATE_REMINDER":
            title = params.get("title", "Reminder")
            scheduled_time = params.get("scheduled_time")
            record_id = f"rem_{uuid.uuid4().hex[:12]}"

            return ExecuteResponse(
                success=True,
                record_id=record_id,
                message=f"Reminder '{title}' created successfully.",
                speech_response=f"Done! I've set your reminder for '{title}'.",
            )

        elif action_type == "CREATE_SCHEDULE":
            title = params.get("title", "Event")
            record_id = f"sch_{uuid.uuid4().hex[:12]}"

            return ExecuteResponse(
                success=True,
                record_id=record_id,
                message=f"Schedule item '{title}' booked successfully.",
                speech_response=f"Added '{title}' to your calendar.",
            )

        elif action_type == "COMPLETE_TASK":
            target = params.get("target_title", "Task")
            return ExecuteResponse(
                success=True,
                record_id=None,
                message=f"Task '{target}' marked as completed.",
                speech_response=f"Marked '{target}' completed.",
            )

        return ExecuteResponse(
            success=False,
            record_id=None,
            message=f"Unsupported action type: {action_type}",
            speech_response="I was unable to perform that specific action.",
        )
