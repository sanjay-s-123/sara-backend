from fastapi import APIRouter, Depends, Query, Response
from app.core.security import get_current_user_id
from app.schemas.voice_call import (
    CallDialogueRequest,
    CallDialogueResponse,
    CallInitiateRequest,
    CallInitiateResponse,
    CallStatusUpdate,
)
from app.services.voice_call_service import VoiceCallService

router = APIRouter(prefix="/api/voice-call", tags=["voice-call"])


@router.get("/health")
def voice_call_health():
    return {
        "status": "healthy",
        "service": "SARA AI Voice Call Reminder Engine",
        "features": [
            "proactive_reminder_call",
            "interactive_speech_dialogue",
            "attendance_confirmation",
            "conversational_rescheduling",
            "conversational_snooze",
            "telephony_webhook_support",
        ],
    }


@router.post("/initiate", response_model=CallInitiateResponse)
async def initiate_voice_call(request: CallInitiateRequest):
    """Initiates an AI voice call reminder for an upcoming task or meeting."""
    return await VoiceCallService.initiate_call(request)


@router.post("/dialogue", response_model=CallDialogueResponse)
async def process_call_dialogue(request: CallDialogueRequest):
    """Processes multi-turn voice dialogue responses between SARA and the user."""
    return await VoiceCallService.process_dialogue(request)


@router.post("/status")
def update_call_status(update: CallStatusUpdate):
    """Records call status updates from telephony providers or mobile clients."""
    return VoiceCallService.record_call_status(
        session_id=update.session_id,
        status=update.status,
        reason=update.reason,
    )


@router.get("/twiml")
def get_twiml_response(session_id: str = Query(...)):
    """Serves TwiML XML instructions to telephone carrier providers."""
    xml_content = VoiceCallService.generate_twiml(session_id)
    return Response(content=xml_content, media_type="application/xml")


from pydantic import BaseModel
from typing import Optional
from app.services.sarvam_tts_service import SarvamTTSService


class SynthesizeSpeechRequest(BaseModel):
    text: str
    language_code: Optional[str] = "en-IN"
    speaker: Optional[str] = "meera"
    pace: float = 1.0


class SynthesizeSpeechResponse(BaseModel):
    audio_base64: Optional[str] = None
    format: str = "wav"
    provider: str = "sarvam"
    speaker: Optional[str] = None
    fallback: bool = False
    latency_ms: float = 0.0


@router.post("/synthesize", response_model=SynthesizeSpeechResponse)
async def synthesize_speech(req: SynthesizeSpeechRequest):
    """Generates natural human-like speech using Sarvam AI Bulbul neural TTS with on-device fallback."""
    return await SarvamTTSService.synthesize(
        text=req.text,
        language_code=req.language_code,
        speaker=req.speaker,
        pace=req.pace,
    )

