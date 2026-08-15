"""
Unit tests for the API. Run in CI on every push - no AWS credentials, no database.

Both external dependencies (Bedrock and Postgres) are monkeypatched, so these
tests check our own logic: request validation, memory wiring, response shape.
"""

import pytest

import app as app_module
import memory


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_health_is_degraded_when_database_is_unreachable(client, monkeypatch):
    """No database -> 503, so the deploy workflow fails loudly instead of silently."""

    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(memory, "_conn", boom)

    response = client.get("/health")
    assert response.status_code == 503
    assert response.get_json()["database"] is False


def test_chat_rejects_an_empty_question(client):
    response = client.post("/chat", json={"question": "   "})
    assert response.status_code == 400
    assert "question is required" in response.get_json()["error"]


def test_chat_returns_the_answer_and_its_sources(client, monkeypatch):
    """The happy path: chain output and retrieved chunks come back to the frontend."""

    class FakeDoc:
        page_content = "Fences in residential districts may not exceed six feet."
        metadata = {"chunk": 7}

    monkeypatch.setattr(memory, "load_history", lambda session_id: [])
    monkeypatch.setattr(memory, "recall", lambda user_id, question: "- prefers short answers")
    monkeypatch.setattr(memory, "save_turn", lambda *args: None)
    monkeypatch.setattr(memory, "remember", lambda *args: None)
    monkeypatch.setattr(
        app_module.rag, "answer", lambda q, h, m: ("Six feet.", [FakeDoc()])
    )

    response = client.post("/chat", json={"question": "How tall can my fence be?"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer"] == "Six feet."
    assert body["sources"][0]["chunk"] == 7
    assert body["used_memories"] is True


def test_history_is_formatted_for_the_prompt():
    """Session memory has to reach the prompt as readable text, not objects."""
    from langchain_core.messages import AIMessage, HumanMessage

    formatted = memory.format_history(
        [HumanMessage("What about sheds?"), AIMessage("Under 120 sq ft, no permit.")]
    )

    assert formatted == "User: What about sheds?\nAssistant: Under 120 sq ft, no permit."
