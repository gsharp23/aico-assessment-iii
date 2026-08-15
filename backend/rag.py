"""
LangChain RAG pipeline.

Ported from the Week 14 municipal-ai project (main.py / embeddings.py), with the
vector store moved from a local Chroma folder to pgvector inside our Postgres
container, so the whole stack runs as three Docker services.

Chain shape (LCEL):   question -> retriever -> prompt -> Bedrock LLM -> string
"""

import os

import boto3
from langchain_aws import BedrockEmbeddings, ChatBedrock
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_postgres import PGVector

# --- Configuration: every value comes from the environment, nothing hardcoded ---
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
CHAT_MODEL_ID = os.environ.get("CHAT_MODEL_ID", "us.amazon.nova-lite-v1:0")
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "el_paso_ordinances")
RETRIEVER_K = int(os.environ.get("RETRIEVER_K", "3"))


def get_db_url() -> str:
    """Build the Postgres connection string from individual env vars.

    Kept as separate vars (not one URL) so the password can come from a GitHub
    secret / AWS Secrets Manager without the rest of the connection details
    being secret too.
    """
    user = os.environ.get("POSTGRES_USER", "raguser")
    password = os.environ["POSTGRES_PASSWORD"]  # required - fail loudly if missing
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    name = os.environ.get("POSTGRES_DB", "ragdb")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def get_bedrock_client():
    """One Bedrock runtime client, shared by the embeddings model and the chat model."""
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def get_embeddings() -> BedrockEmbeddings:
    """Titan embeddings. The same model MUST be used for ingest and for query,
    otherwise the vectors live in different spaces and retrieval returns garbage."""
    return BedrockEmbeddings(client=get_bedrock_client(), model_id=EMBEDDING_MODEL_ID)


def get_vector_store() -> PGVector:
    """Connect to the pgvector table inside our Postgres service."""
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=COLLECTION_NAME,
        connection=get_db_url(),
        use_jsonb=True,
    )


# --- Prompt template (Week 13 pattern: ChatPromptTemplate with placeholders) ---
# {history} = this session's conversation, {memories} = long-term facts from Mem0,
# {context} = chunks retrieved from pgvector, {question} = what the user just asked.
PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an assistant on the El Paso municipal code. Answer using ONLY "
            "the CONTEXT below. If the context does not contain the answer, say the "
            "information is not available in the provided documents. Do not use "
            "outside knowledge.\n\n"
            "WHAT YOU REMEMBER ABOUT THIS USER:\n{memories}\n\n"
            "CONTEXT:\n{context}",
        ),
        ("human", "Conversation so far:\n{history}\n\nQUESTION: {question}"),
    ]
)


def format_docs(docs) -> str:
    """Turn retrieved Document objects into the plain text the prompt expects."""
    return "\n\n".join(doc.page_content for doc in docs)


def build_chain():
    """Assemble prompt -> model -> string parser.

    Returned separately from the retriever so app.py can show the user which
    source chunks were used (the retriever output is needed for citations).
    """
    llm = ChatBedrock(
        client=get_bedrock_client(),
        model_id=CHAT_MODEL_ID,
        model_kwargs={"max_tokens": 1000, "temperature": 0.2},
    )
    return PROMPT | llm | StrOutputParser()


def answer(question: str, history: str, memories: str):
    """Run one full RAG turn. Returns (answer_text, source_documents)."""
    retriever = get_vector_store().as_retriever(search_kwargs={"k": RETRIEVER_K})
    docs = retriever.invoke(question)

    text = build_chain().invoke(
        {
            "context": format_docs(docs),
            "question": question,
            "history": history or "(this is the first message)",
            "memories": memories or "(nothing remembered yet)",
        }
    )
    return text, docs
