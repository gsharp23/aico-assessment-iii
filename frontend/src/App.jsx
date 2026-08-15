import { useState } from "react";

// No API URL is baked into the bundle. nginx (the web server in front of this
// app) proxies /api to the backend container, so the frontend just calls a
// relative path and works identically on a laptop and on EC2.
const API = "/api";

// One browser tab = one session (short-term memory). The user id is stable so
// Mem0 can build up long-term facts across sessions.
const SESSION_ID = `session-${Math.random().toString(36).slice(2, 10)}`;
const USER_ID = "demo-user";

export default function App() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState([]);
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);

  async function ask() {
    if (!question.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          session_id: SESSION_ID,
          user_id: USER_ID,
        }),
      });
      const data = await res.json();
      setTurns((prev) => [...prev, { question, ...data }]);
      setQuestion("");
    } catch (err) {
      setTurns((prev) => [...prev, { question, answer: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function refreshMemories() {
    const res = await fetch(`${API}/memories?user_id=${USER_ID}`);
    const data = await res.json();
    setMemories(data.memories || []);
  }

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: 20, fontFamily: "system-ui" }}>
      <h1>El Paso Ordinance Assistant</h1>
      <p style={{ color: "#555" }}>
        Ask a question about the municipal code. Answers come from a RAG pipeline
        over pgvector; the assistant remembers you between sessions via Mem0.
      </p>

      <div style={{ display: "flex", gap: 8, margin: "20px 0" }}>
        <input
          style={{ flex: 1, padding: 10, fontSize: 16 }}
          placeholder="e.g. How tall can a residential fence be?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
        />
        <button onClick={ask} disabled={loading} style={{ padding: "10px 20px" }}>
          {loading ? "Thinking..." : "Ask"}
        </button>
      </div>

      {turns.map((turn, i) => (
        <div key={i} style={{ borderTop: "1px solid #ddd", padding: "16px 0" }}>
          <p>
            <strong>You:</strong> {turn.question}
          </p>
          <p>
            <strong>Assistant:</strong> {turn.answer}
          </p>
          {turn.used_memories && (
            <p style={{ fontSize: 12, color: "#0a7" }}>✓ used long-term memory</p>
          )}
          {turn.sources?.length > 0 && (
            <details>
              <summary style={{ cursor: "pointer", fontSize: 14 }}>
                {turn.sources.length} retrieved sources
              </summary>
              {turn.sources.map((s, j) => (
                <p key={j} style={{ fontSize: 13, color: "#444", background: "#f6f6f6", padding: 8 }}>
                  <em>chunk {s.chunk}:</em> {s.preview}...
                </p>
              ))}
            </details>
          )}
        </div>
      ))}

      <hr style={{ marginTop: 30 }} />
      <h2>Long-term memory (Mem0)</h2>
      <button onClick={refreshMemories}>Show what the assistant remembers</button>
      <ul>
        {memories.map((m, i) => (
          <li key={i}>{m.memory}</li>
        ))}
      </ul>
    </div>
  );
}
