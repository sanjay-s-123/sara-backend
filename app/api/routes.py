from fastapi import APIRouter, Depends
from app.core.security import get_current_user_id
from app.schemas.assistant import (
    InterpretRequest,
    InterpretResponse,
    ExecuteRequest,
    ExecuteResponse,
)
from app.services.intent_parser import IntentParser
from app.services.action_executor import ActionExecutor
from app.services.llm_service import LLMAssistantService

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "SARA Assistant Core Backend",
        "version": "1.0.0",
        "ai_engine": "gemini-with-deterministic-fallback" if LLMAssistantService.is_available() else "hybrid-deterministic",
    }


@router.post("/interpret", response_model=InterpretResponse)
async def interpret_command(
    request: InterpretRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Interprets a natural-language query and returns an authorized action proposal."""
    if LLMAssistantService.is_available():
        llm_result = await LLMAssistantService.interpret_with_llm(
            query=request.query,
            timezone=request.timezone,
            context=request.context,
        )
        if llm_result is not None:
            return llm_result

    return IntentParser.parse_command(
        query=request.query,
        timezone=request.timezone,
        context=request.context,
    )


@router.post("/execute", response_model=ExecuteResponse)
def execute_action(
    request: ExecuteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Executes a validated action proposal for the authenticated user."""
    return ActionExecutor.execute(request, user_id=user_id)


@router.get("/history")
def get_user_history(user_id: str = Depends(get_current_user_id)):
    """Returns conversation activity log for the authenticated user."""
    return {
        "user_id": user_id,
        "logs": [],
    }
