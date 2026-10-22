import hashlib
import logging
import time
from typing import Any, Dict, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SarvamTTSService:
    """Manages natural neural text-to-speech generation via Sarvam AI API with caching and graceful fallback."""

    # In-memory LRU-like synthesis cache: hash -> base64 audio
    _cache: Dict[str, str] = {}
    _MAX_CACHE_ITEMS = 250

    @classmethod
    def _compute_cache_key(cls, text: str, speaker: str, lang: str) -> str:
        key_raw = f"{text.strip().lower()}:{speaker.lower()}:{lang.lower()}"
        return hashlib.md5(key_raw.encode("utf-8")).hexdigest()

    @classmethod
    async def synthesize(
        cls,
        text: str,
        language_code: Optional[str] = None,
        speaker: Optional[str] = None,
        pace: float = 1.0,
    ) -> Dict[str, Any]:
        """Synthesizes text using Sarvam AI Bulbul neural TTS.
        Returns base64 WAV audio if successful, or signals device_tts fallback if unconfigured/failed.
        """
        clean_text = text.strip()
        if not clean_text:
            return {"audio_base64": None, "provider": "device_tts", "latency_ms": 0}

        target_lang = language_code or settings.SARVAM_DEFAULT_LANGUAGE
        target_speaker = speaker or settings.SARVAM_DEFAULT_SPEAKER
        cache_key = cls._compute_cache_key(clean_text, target_speaker, target_lang)

        # Check Cache
        if cache_key in cls._cache:
            logger.info("Sarvam TTS: cache hit for key %s", cache_key[:8])
            return {
                "audio_base64": cls._cache[cache_key],
                "format": "wav",
                "provider": "sarvam_cached",
                "speaker": target_speaker,
                "latency_ms": 1.0,
            }

        # Primary Voice Provider: Microsoft Edge Neural TTS (en-IN-NeerjaNeural)
        # 100% free, natural, warm, human-like Indian English female voice (Neerja)
        start_edge = time.time()
        try:
            import base64
            import edge_tts

            edge_voice = "en-IN-NeerjaNeural"
            communicate = edge_tts.Communicate(clean_text, edge_voice)
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])

            audio_bytes = b"".join(chunks)
            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                if len(cls._cache) >= cls._MAX_CACHE_ITEMS:
                    cls._cache.pop(next(iter(cls._cache)))
                cls._cache[cache_key] = audio_b64

                latency = round((time.time() - start_edge) * 1000, 2)
                logger.info("Edge Neural TTS (Neerja) synthesized %d chars in %sms", len(clean_text), latency)
                return {
                    "audio_base64": audio_b64,
                    "format": "mp3",
                    "provider": "edge_tts_neerja",
                    "speaker": "Neerja (Neural)",
                    "fallback": False,
                    "latency_ms": latency,
                }
        except Exception as edge_err:
            logger.warning("Edge TTS Neerja synthesis failed: %s", edge_err)

        # Optional Sarvam AI Fallback if valid API key is present
        if settings.SARVAM_API_KEY and len(settings.SARVAM_API_KEY.strip()) > 10:
            start_time = time.time()
            url = "https://api.sarvam.ai/text-to-speech"
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": settings.SARVAM_API_KEY.strip(),
            }
            payload = {
                "inputs": [clean_text],
                "target_language_code": target_lang,
                "speaker": target_speaker,
                "pitch": 0.0,
                "pace": pace,
                "loudness": 1.0,
                "speech_sample_rate": 22050,
                "enable_preprocessing": True,
                "model": settings.SARVAM_TTS_MODEL,
            }

            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        audios = data.get("audios", [])
                        if audios and len(audios) > 0:
                            audio_b64 = audios[0]
                            if len(cls._cache) >= cls._MAX_CACHE_ITEMS:
                                cls._cache.pop(next(iter(cls._cache)))
                            cls._cache[cache_key] = audio_b64

                            latency = round((time.time() - start_time) * 1000, 2)
                            return {
                                "audio_base64": audio_b64,
                                "format": "wav",
                                "provider": "sarvam",
                                "speaker": target_speaker,
                                "fallback": False,
                                "latency_ms": latency,
                            }
            except Exception as e:
                logger.warning("Sarvam TTS request failed: %s", e)

        latency = round((time.time() - start_edge) * 1000, 2)
        return {
            "audio_base64": None,
            "format": "wav",
            "provider": "device_tts",
            "fallback": True,
            "latency_ms": latency,
        }
