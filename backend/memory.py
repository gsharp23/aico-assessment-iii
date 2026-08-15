"""
Two layers of memory (Week 12 pattern).

1. SESSION memory  - the current conversation, stored in Postgres as LangChain
                     message objects. Short-term, scoped to one session_id.
2. SEMANTIC memory - durable facts about the user, stored in Mem0. Mem0 decides
                     what is worth remembering and returns it by relevance.

Mem0 is optional at runtime: if MEM0_API_KEY is not set the app still works and
just reports that semantic memory is disabled. That keeps the demo from dying
on a missing key.
"""

import os

import psycopg
from langchain_core.messages import AIMessage, HumanMessage

MEM0_API_KEY = os.environ.get("MEM0_API_KEY", "")


def _conn():
    """Plain psycopg connection - used for the session-memory table."""
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "ragdb"),
        user=os.environ.get("POSTGRES_USER", "raguser"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


# ---------------------------------------------------------------- session memory


def load_history(session_id: str):
    """Read this session's turns back out of Postgres as LangChain messages."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT role, content FROM chat_messages "
            "WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        )
        rows = cur.fetchall()

    messages = []
    for role, content in rows:
        messages.append(HumanMessage(content) if role == "human" else AIMessage(content))
    return messages


def save_turn(session_id: str, question: str, answer: str) -> None:
    """Write one question/answer pair into the database."""
    with _conn() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
            [(session_id, "human", question), (session_id, "ai", answer)],
        )
        conn.commit()


def format_history(messages) -> str:
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
