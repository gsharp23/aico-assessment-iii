"""
Two layers of memory (Week 12 pattern).

1. SESSION memory  - the current conversation, held in Postgres behind LangChain's
                     BaseChatMessageHistory interface. Short-term, scoped to one
                     session_id.
2. SEMANTIC memory - durable facts about the user, stored in Mem0. Mem0 decides
                     what is worth remembering and returns it by relevance.

Implementing BaseChatMessageHistory (rather than formatting rows by hand) means
this is a real LangChain conversation-memory backend: it can be swapped for any
other history implementation, or handed to RunnableWithMessageHistory, without
touching the chain.

Mem0 is optional at runtime: if MEM0_API_KEY is not set the app still works and
just reports that semantic memory is disabled. That keeps the demo from dying on
a missing key.
"""

import psycopg
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from config import env, require

MEM0_API_KEY = env("MEM0_API_KEY")


def _conn():
    """Plain psycopg connection - used for the session-memory table."""
    return psycopg.connect(
        host=env("POSTGRES_HOST", "db"),
        port=env("POSTGRES_PORT", "5432"),
        dbname=env("POSTGRES_DB", "ragdb"),
        user=env("POSTGRES_USER", "raguser"),
        password=require("POSTGRES_PASSWORD"),
    )


# ---------------------------------------------------------------- session memory


class PostgresChatHistory(BaseChatMessageHistory):
    """LangChain conversation memory backed by the `chat_messages` table.

    The interface is three members: read `messages`, `add_messages()`, `clear()`.
    Everything the chain needs to keep a session's context comes through here.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id

    @property
    def messages(self) -> list[BaseMessage]:
        """Replay this session's turns as LangChain message objects."""
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id = %s ORDER BY created_at",
                (self.session_id,),
            )
            rows = cur.fetchall()

        return [
            HumanMessage(content) if role == "human" else AIMessage(content)
            for role, content in rows
        ]

    def add_messages(self, messages: list[BaseMessage]) -> None:
        """Append messages to the session. Called once per completed turn."""
        rows = [
            (self.session_id, "human" if m.type == "human" else "ai", m.content)
            for m in messages
        ]
        with _conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
                rows,
            )
            conn.commit()

    def clear(self) -> None:
        """Drop this session's history. Required by the interface."""
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chat_messages WHERE session_id = %s", (self.session_id,))
            conn.commit()


def get_session_history(session_id: str) -> PostgresChatHistory:
    """Factory used by the API - the shape RunnableWithMessageHistory expects."""
    return PostgresChatHistory(session_id)


def format_history(messages: list[BaseMessage]) -> str:
    """Flatten messages into the plain text the prompt template expects."""
    label = {"human": "User", "ai": "Assistant"}
    return "\n".join(f"{label.get(m.type, m.type)}: {m.content}" for m in messages)


# --------------------------------------------------------------- semantic memory


def _mem0():
    """Build a Mem0 client, or None if no API key is configured."""
    if not MEM0_API_KEY:
        return None
    from mem0 import MemoryClient

    return MemoryClient(api_key=MEM0_API_KEY)


def recall(user_id: str, question: str) -> str:
    """Semantic search over what Mem0 has stored for this user."""
    client = _mem0()
    if client is None:
        return ""
    hits = client.search(query=question, user_id=user_id, limit=3)
    return "\n".join(f"- {h['memory']}" for h in hits)


def remember(user_id: str, question: str, answer: str) -> None:
    """Hand the turn to Mem0 and let it extract any durable facts."""
    client = _mem0()
    if client is None:
        return
    client.add(
        [{"role": "user", "content": question}, {"role": "assistant", "content": answer}],
        user_id=user_id,
    )


def list_memories(user_id: str):
    """Everything Mem0 currently holds for this user - powers the UI memory panel."""
    client = _mem0()
    if client is None:
        return []
    return client.get_all(user_id=user_id)
