"""
Flask API - the middle tier.

Endpoints:
  GET  /health     - liveness + dependency check (used by CI and by the deploy workflow)
  POST /chat       - one RAG turn: retrieve -> remember -> answer
  GET  /memories   - what Mem0 has stored for a user (drives the UI panel)

Same shape as the Assessment II backend, with the AWS AI calls replaced by the
LangChain RAG chain and the two memory layers.
"""

import logging
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

import memory
import rag

# Structured-ish logging so the deploy workflow's `docker compose logs` is readable
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("api")

app = Flask(__name__)
CORS(app)


@app.get("/health")
def health():
    """Reports whether the API can reach Postgres. The deploy workflow polls this."""
    try:
        with memory._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        db_ok = True
    except Exception as exc:  # noqa: BLE001 - we want the reason in the payload
        log.warning("health: database unreachable: %s", exc)
        db_ok = False

    status = 200 if db_ok else 503
    return (
        jsonify(
            {
                "status": "ok" if db_ok else "degraded",
                "database": db_ok,
                "semantic_memory": bool(memory.MEM0_API_KEY),
                "chat_model": rag.CHAT_MODEL_ID,
            }
        ),
        status,
    )


@app.post("/chat")
def chat():
    """One conversational turn against the municipal code."""
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    session_id = body.get("session_id") or "demo-session"
    user_id = body.get("user_id") or "demo-user"

    if not question:
        return jsonify({"error": "question is required"}), 400

    log.info("chat: user=%s session=%s q=%r", user_id, session_id, question[:80])

    # 1. Pull both memory layers
    history = memory.format_history(memory.load_history(session_id))
    memories = memory.recall(user_id, question)

    # 2. Run the RAG chain
    answer, docs = rag.answer(question, history, memories)

    # 3. Persist the turn to both layers
    memory.save_turn(session_id, question, answer)
    memory.remember(user_id, question, answer)

    return jsonify(
        {
            "answer": answer,
            "sources": [
                {
                    "preview": d.page_content[:300],
                    "chunk": d.metadata.get("chunk"),
                }
                for d in docs
            ],
            "used_memories": bool(memories),
        }
    )


@app.get("/memories")
def memories():
    """List the durable facts Mem0 holds for a user."""
    user_id = request.args.get("user_id", "demo-user")
    return jsonify({"user_id": user_id, "memories": memory.list_memories(user_id)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
