import anyio
from app.services.llm_service import LLMAssistantService
from app.core.config import settings


def test_llm_service_returns_none_when_unconfigured():
    async def _test():
        original_key = settings.LLM_API_KEY
        try:
            settings.LLM_API_KEY = ""
            assert not LLMAssistantService.is_available()
            result = await LLMAssistantService.interpret_with_llm("Remind me to call Mom at 7pm")
            assert result is None
        finally:
            settings.LLM_API_KEY = original_key

    anyio.run(_test)
