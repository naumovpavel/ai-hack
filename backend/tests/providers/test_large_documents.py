import pytest

from interview_api.workflow.hiring_ai import HiringAI
from interview_api.workflow.openrouter import OpenRouterWorkflowAI


@pytest.mark.asyncio
async def test_large_vacancy_pdf_reuses_extracted_text_instead_of_resending_binary(monkeypatch):
    gateway = OpenRouterWorkflowAI(
        api_key="test", chat_model="test", stt_model="test", tts_model="test"
    )
    ai = HiringAI(gateway)
    requests = []

    async def capture(name, schema, system, user, **kwargs):
        requests.append((user, kwargs))
        return {
            "title": "Python developer",
            "role": "Backend",
            "level": "Middle",
            "description": "Build and maintain Python services.",
            "requirements": ["Python"],
        }

    monkeypatch.setattr(ai, "_json", capture)
    try:
        await ai.parse_vacancy(
            "Extracted requirements",
            "Company context",
            pdf=b"x" * (4 * 1024 * 1024 + 1),
            filename="large.pdf",
        )
        user, options = requests[0]
        assert user["document"] == "Extracted requirements"
        assert user["companyContext"] == "Company context"
        assert options["pdf"] is None
    finally:
        gateway.close()
