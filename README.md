# Assessment III — CI/CD Pipeline with GitHub Actions & Docker Compose

A three-tier RAG application, delivered end to end by a GitHub Actions pipeline.

Ask a question about the El Paso municipal code; the app retrieves the relevant
passages from a vector store, answers with AWS Bedrock, shows its sources, and
remembers you between sessions.

**📐 [Architecture, pipeline, and database diagrams →](docs/architecture.md)**

---

## The stack

| Tier | Service | Technology |
|---|---|---|
| Frontend + web server | `web` | React (Vite) built into nginx, which also proxies `/api` |
| Backend API | `api` | Flask + LangChain + Mem0, served by gunicorn |
| Database | `db` | Postgres 16 with pgvector — application data *and* the vector store |

All three run as Docker Compose services, identically on a laptop and on EC2.

---

## Quick start — run it locally

```bash
git clone <this-repo> && cd aico-assessment-iii

cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, your AWS credentials, and (optionally) MEM0_API_KEY

./scripts/local-up.sh
```

That builds the images, starts all three containers, waits for the API to report
healthy, and loads the corpus into pgvector. Then open **http://localhost**.

Verify by hand:

```bash
curl http://localhost/api/health

curl -X POST http://localhost/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"What does the code say about fence height?"}'

# The app really is writing to the database:
docker compose exec db psql -U raguser -d ragdb -c 'SELECT role, left(content,60) FROM chat_messages;'
```

Tear down: `docker compose down -v`

---

## Deploy it to AWS

### Prerequisites

- AWS CLI configured, with **Bedrock model access enabled in us-east-1** for
  `amazon.nova-lite-v1:0` and `amazon.titan-embed-text-v2:0`
- An EC2 key pair (this project assumes `aico-echo`)
- GitHub CLI, authenticated (`gh auth login`)

### Step 1 — Create the Terraform state backend (once)

```bash
./scripts/bootstrap-state.sh
```

Creates the versioned, encrypted S3 bucket and the DynamoDB lock table that
`terraform/main.tf` points at. This has to exist before Terraform can store
state remotely.

### Step 2 — Push your secrets to GitHub (once)

```bash
./scripts/set-secrets.sh
```

Reads your local `.env` and `~/.aws/credentials` and registers everything the
workflows need:

| Name | Type | Used by |
|---|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | secret | Terraform, ECR push |
| `POSTGRES_PASSWORD` | secret | `TF_VAR_postgres_password` → Secrets Manager |
| `MEM0_API_KEY` | secret | `TF_VAR_mem0_api_key` → Secrets Manager |
| `EC2_SSH_KEY` | secret | the deploy job's SSH and SCP steps |
| `EC2_KEY_NAME` | variable | which EC2 key pair to attach |

### Step 3 — Release

GitHub → **Actions** → **Deploy** → **Run workflow**.

One click provisions the infrastructure, builds and pushes both images, deploys
the stack, loads the knowledge base, and smoke-tests the result. The run summary
prints the public URL.

### Step 4 — Tear down

GitHub → **Actions** → **Destroy** → type `assessment-iii` to confirm.

Or locally: `terraform -chdir=terraform destroy`

---

## The pipeline

**`ci.yml`** — every push and pull request. No AWS credentials, no cost.

- Ruff lint + pytest on the backend
- Both compose files validated with `docker compose config`
- Both images built (matrix job, gated behind the tests)
- `terraform fmt -check` and `terraform validate`

**`deploy.yml`** — manual trigger, four sequential jobs.

1. **provision** — `terraform apply`, exports the instance IP and ECR URLs as job outputs
2. **build** — matrix over `api` and `web`; tags each image `:${{ github.sha }}` and `:latest`
3. **deploy** — waits for SSH, copies the compose file, pulls from ECR, `up -d`, runs ingest
4. **smoke test** — asserts `/api/health` is `ok`, the frontend serves, and a real
   question round-trips through the RAG chain; dumps container logs on failure

**`destroy.yml`** — manual, requires typing the project name.

Nothing downstream hardcodes an address: the deploy job learns the instance IP and
the registry URLs from Terraform outputs at runtime.

---

## How the AI layer works

`backend/rag.py` builds a LangChain chain in the LCEL style:

```
question → pgvector retriever (k=3) → ChatPromptTemplate → ChatBedrock → StrOutputParser
```

The prompt receives four inputs: retrieved `{context}`, the `{question}`, the
`{history}` of this session, and `{memories}` — durable facts Mem0 has learned
about the user.

`backend/memory.py` implements the two layers separately:

- **Session memory** — every turn written to the `chat_messages` table in Postgres,
  read back as LangChain `HumanMessage` / `AIMessage` objects.
- **Semantic memory** — turns handed to Mem0, which extracts what is worth keeping
  and returns it by relevance on later questions. Optional: with no `MEM0_API_KEY`
  the app runs fine and reports `semantic_memory: false` on `/health`.

`backend/ingest.py` is the loading half: `TextLoader` → `RecursiveCharacterTextSplitter`
(1000 chars, 150 overlap) → Titan embeddings → pgvector. It skips itself if the
collection is already populated, so re-running a deploy is safe.

---

## Built on earlier coursework

| Piece | Came from |
|---|---|
| Terraform VPC / SG / IAM / EC2 layout | Assessment II |
| RAG pipeline, corpus, chunking strategy | Week 14 — municipal-ai |
| `ChatBedrock` + `ChatPromptTemplate` + LCEL | Week 13 — langchain-chatbot |
| Two-layer memory design, Mem0 client | Week 12 |
| Workflow structure, matrix jobs, pytest suite | Week 11 — ollama-actions-week |
| Ruff CI job | Week 14 — municipal-ai `ci.yml` |

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `/health` shows `"database": false` | `docker compose logs db` — usually `POSTGRES_PASSWORD` is unset in `.env` |
| `AccessDeniedException` from Bedrock | Model access not enabled in this region: Bedrock console → Model access |
| Chat answers "not available in the provided documents" | Ingest never ran: `docker compose exec api python ingest.py` |
| Retrieval returns irrelevant chunks | `EMBEDDING_MODEL_ID` changed after ingest — re-run with `FORCE_INGEST=1` |
| Deploy job hangs on SSH | First boot takes ~2 min to install Docker; check `/var/log/user-data.log` on the instance |
| `terraform init` fails on the backend | Run `./scripts/bootstrap-state.sh` first |
| State is locked | A previous run died: `terraform force-unlock <id>` |
