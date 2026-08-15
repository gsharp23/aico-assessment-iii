"""
Unit tests. Run in CI on every push - no AWS credentials, no database.

Both external dependencies (Bedrock and Postgres) are substituted, so these tests
check our own logic: request validation, memory wiring, chain composition, and
response shape.
"""

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

import app as app_module
import memory
import rag
from config import env


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


class FakeHistory:
    """Stands in for PostgresChatHistory - same interface, no database."""

    def __init__(self, messages=None):
        self.messages = messages or []
        self.added = []

    def add_messages(self, messages):
        self.added.extend(messages)


# ----------------------------------------------------------------- the API


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
    """The happy path: chain output and retrieved chunks reach the frontend."""
    history = FakeHistory()

    monkeypatch.setattr(memory, "get_session_history", lambda session_id: history)
    monkeypatch.setattr(memory, "recall", lambda user_id, question: "- is a contractor")
    monkeypatch.setattr(memory, "remember", lambda *args: None)
    monkeypatch.setattr(
        app_module.rag,
        "answer",
        lambda q, h, m: {
            "answer": "Six feet.",
            "source_documents": [
                Document("Fences may not exceed six feet.", metadata={"chunk": 7})
            ],
        },
    )

    response = client.post("/chat", json={"question": "How tall can my fence be?"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["answer"] == "Six feet."
    assert body["sources"][0]["chunk"] == 7
    assert body["used_memories"] is True


def test_chat_writes_the_turn_to_session_memory(client, monkeypatch):
    """Both halves of the exchange must be persisted, or follow-ups lose context."""
    history = FakeHistory()

    monkeypatch.setattr(memory, "get_session_history", lambda session_id: history)
    monkeypatch.setattr(memory, "recall", lambda user_id, question: "")
    monkeypatch.setattr(memory, "remember", lambda *args: None)
    monkeypatch.setattr(
        app_module.rag,
        "answer",
        lambda q, h, m: {"answer": "Six feet.", "source_documents": []},
    )

    client.post("/chat", json={"question": "How tall?"})

    assert [(m.type, m.content) for m in history.added] == [
        ("human", "How tall?"),
        ("ai", "Six feet."),
    ]


# ----------------------------------------------------------------- memory


def test_history_is_formatted_for_the_prompt():
    """Session memory has to reach the prompt as readable text, not objects."""
    formatted = memory.format_history(
        [HumanMessage("What about sheds?"), AIMessage("Under 120 sq ft, no permit.")]
    )

    assert formatted == "User: What about sheds?\nAssistant: Under 120 sq ft, no permit."


# ----------------------------------------------------------------- config


def test_a_blank_environment_variable_falls_back_to_the_default(monkeypatch):
    """Compose sets unset variables to "" rather than leaving them absent.

    os.environ.get(name, default) would return "" and boto3 would then fail with
    "You must specify a region". env() has to treat blank and missing alike.
    """
    monkeypatch.setenv("AWS_REGION", "")
    assert env("AWS_REGION", "us-east-1") == "us-east-1"

    monkeypatch.delenv("AWS_REGION")
    assert env("AWS_REGION", "us-east-1") == "us-east-1"

    monkeypatch.setenv("AWS_REGION", "us-west-2")
    assert env("AWS_REGION", "us-east-1") == "us-west-2"


# ----------------------------------------------------------------- the chain


def test_the_rag_chain_runs_all_three_stages(monkeypatch):
    """Exercise the real LCEL chain with a fake retriever and a fake model.

    This proves the multi-stage composition is wired correctly: retrieval feeds
    context, context and both memory layers reach the prompt, and the output
    carries the answer together with its sources.
    """
    seen_prompt = {}

    def fake_model(prompt_value):
        seen_prompt["text"] = prompt_value.to_string()
        return AIMessage("Six feet.")

    monkeypatch.setattr(rag, "get_bedrock_client", lambda: None)
    monkeypatch.setattr(rag, "ChatBedrock", lambda **kwargs: RunnableLambda(fake_model))

    retriever = RunnableLambda(
        lambda question: [Document("Fences may not exceed six feet.", metadata={"chunk": 7})]
    )

    result = rag.build_chain(retriever=retriever).invoke(
        {
            "question": "How tall can my fence be?",
            "history": "User: I am a contractor.",
            "memories": "- works in Sunset Heights",
        }
    )

    # Stage 3 produced an answer...
    assert result["answer"] == "Six feet."
    # ...stage 1 kept the retrieved documents for citation...
    assert result["source_documents"][0].metadata["chunk"] == 7
    # ...and stage 2 put the retrieved text into the prompt.
    assert "Fences may not exceed six feet." in seen_prompt["text"]
    # Both memory layers reached the model too.
    assert "Sunset Heights" in seen_prompt["text"]
    assert "I am a contractor" in seen_prompt["text"]


def test_mmr_retrieval_can_be_enabled_by_configuration(monkeypatch):
    """The Week 14 retrieval-quality option is reachable without a code change."""

    class FakeStore:
        def as_retriever(self, **kwargs):
            return kwargs

    monkeypatch.setattr(rag, "SEARCH_TYPE", "mmr")
    monkeypatch.setattr(rag, "RETRIEVER_K", 3)

    kwargs = rag.build_retriever(FakeStore())

    assert kwargs["search_type"] == "mmr"
    assert kwargs["search_kwargs"]["fetch_k"] == 20  # max(20, k*4)
