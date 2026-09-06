import pytest
import test_hiring
from test_hiring import assert_ok, make_plan

hiring_client = test_hiring.hiring_client


@pytest.mark.parametrize("kind", ["vacancy", "resume", "context"])
def test_document_upload_over_old_ten_megabyte_limit(hiring_client, kind):
    client, service = hiring_client

    class Extractor:
        async def extract(self, document):
            assert document.size_bytes == 12 * 1024 * 1024
            return "Test candidate\nPython services and documented company requirements."

    service._extractor = Extractor()
    if kind == "vacancy":
        path, field = "/api/v1/vacancies/parse", "vacancy"
    elif kind == "resume":
        _, plan = make_plan(client)
        path = f"/api/v1/interview-plans/{plan['id']}/candidates/prepare"
        field = "resume"
    else:
        path, field = "/api/v1/company-context", "document"
    response = client.post(
        path,
        files={
            field: (
                "large.docx",
                b"x" * (12 * 1024 * 1024),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )
    assert assert_ok(response)


def test_oversized_upload_returns_validation_error_before_parsing(hiring_client):
    client, service = hiring_client
    service.max_document_bytes = 1024
    response = client.post(
        "/api/v1/vacancies/parse",
        files={
            "vacancy": ("oversized.txt", b"x" * 2048, "text/plain"),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["maxBytes"] == 1024
