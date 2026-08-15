"""
LangChain RAG pipeline.

Ported from the Week 14 municipal-ai project (main.py / embeddings.py). The chain
structure is the same multi-stage LCEL composition built there; two things changed:

  1. the vector store moved from a local Chroma folder to pgvector in Postgres,
     so the whole stack runs as three Docker services
  2. the chain now also carries session history and long-term memories, so the
     prompt sees the conversation as well as the retrieved context

Chain shape:

    {question, history, memories}
        |
        +-- RunnableParallel ---> source_documents = retriever(question)
        |                         question / history / memories passed through
        |
        +-- .assign(context) ---> documents formatted into prompt text
        |
        +-- .assign(answer) ---> prompt | ChatBedrock | StrOutputParser

The final output is a dict, so the API can return the answer *and* the source
documents that produced it.
"""

from operator import itemgetter

import boto3
from langchain_aws import BedrockEmbeddings, ChatBedrock
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_postgres import PGVector

from config import env, require

# --- Configuration: every value comes from the environment, nothing hardcoded ---
AWS_REGION = env("AWS_REGION", "us-east-1")
CHAT_MODEL_ID = env("CHAT_MODEL_ID", "us.amazon.nova-lite-v1:0")
EMBEDDING_MODEL_ID = env("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
COLLECTION_NAME = env("COLLECTION_NAME", "el_paso_ordinances")

# Retrieval-quality knobs. These were CLI flags in the Week 14 script; here they
# are environment variables so the deployed app can be tuned without a rebuild.
SEARCH_TYPE = env("RETRIEVER_SEARCH_TYPE", "similarity")  # similarity | mmr
RETRIEVER_K = int(env("RETRIEVER_K", "3"))
FETCH_K = int(env("RETRIEVER_FETCH_K", "0")) or None
LAMBDA_MULT = float(env("RETRIEVER_LAMBDA_MULT", "0.5"))


def get_db_url() -> str:
    """Build the Postgres connection string from individual env vars.

    Kept as separate vars (not one URL) so the password can come from a GitHub
    secret / AWS Secrets Manager without the rest of the connection details
    being secret too.
    """
    user = env("POSTGRES_USER", "raguser")
    password = require("POSTGRES_PASSWORD")
    host = env("POSTGRES_HOST", "db")
    port = env("POSTGRES_PORT", "5432")
    name = env("POSTGRES_DB", "ragdb")
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


def build_retriever(store: PGVector):
    """Baseline similarity search, or MMR to diversify the retrieved context.

    MMR (maximal marginal relevance) pulls a larger candidate pool (fetch_k) and
    then picks k chunks that are relevant but not near-duplicates of each other -
    it stops three copies of the same ordinance filling the whole prompt.
    """
    if SEARCH_TYPE == "similarity":
        return store.as_retriever(search_type="similarity", search_kwargs={"k": RETRIEVER_K})

    return store.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": RETRIEVER_K,
            "fetch_k": FETCH_K or max(20, RETRIEVER_K * 4),
            "lambda_mult": LAMBDA_MULT,
        },
    )


# --- Prompt template (Week 13 pattern: ChatPromptTemplate with placeholders) ---
# {context} = chunks retrieved from pgvector, {memories} = durable facts from Mem0,
# {history} = this session's conversation, {question} = what the user just asked.
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


def get_context(inputs) -> str:
    """Stage 2: read the raw documents out of the chain and format them."""
    return format_docs(inputs["source_documents"])


def get_answer_inputs(inputs) -> dict:
    """Stage 3: keep only the four fields the prompt template declares."""
    return {
        "context": inputs["context"],
        "question": inputs["question"],
        "history": inputs["history"],
        "memories": inputs["memories"],
    }


def build_chain(retriever=None):
    """Assemble the full multi-stage RAG chain.

    Built fresh per call rather than at import time, so the module can be
    imported (and unit tested) without a database or AWS credentials.
    """
    if retriever is None:
        retriever = build_retriever(get_vector_store())

    llm = ChatBedrock(
        client=get_bedrock_client(),
        model_id=CHAT_MODEL_ID,
        model_kwargs={"max_tokens": 1000, "temperature": 0.2},
    )

    # prompt -> model -> plain string
    answer_chain = PROMPT | llm | StrOutputParser()

    return (
        # Stage 1: retrieve, and carry the other inputs through untouched.
        RunnableParallel(
            source_documents=itemgetter("question") | retriever,
            question=itemgetter("question"),
            history=itemgetter("history"),
            memories=itemgetter("memories"),
        )
        # Stage 2: add the formatted context text.
        .assign(context=RunnableLambda(get_context))
        # Stage 3: add the generated answer.
        .assign(answer=RunnableLambda(get_answer_inputs) | answer_chain)
    )


def answer(question: str, history: str, memories: str) -> dict:
    """Run one full RAG turn.

    Returns the chain's output dict, which includes both `answer` and the
    `source_documents` it was grounded in.
    """
    return build_chain().invoke(
        {
            "question": question,
            "history": history or "(this is the first message)",
            "memories": memories or "(nothing remembered yet)",
        }
    )
