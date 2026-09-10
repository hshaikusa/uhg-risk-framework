# Emerging-events RAG for baseline risk revision

Design document (plan + illustrative sample code).  
**Not production code** — snippets show shape of a future implementation.

## Contents

1. [Problem and system framing](#1-problem-and-system-framing)
2. [End-to-end pipeline](#2-end-to-end-pipeline)
3. [Option A — Postgres schema and flush rules](#3-option-a--postgres-schema-and-flush-rules)
4. [Chunking deep dive](#4-chunking-deep-dive)
5. [Embedding, metadata, indexing](#5-embedding-metadata-indexing)
6. [Option B — Query → retrieve API contract](#6-option-b--query--retrieve-api-contract)
7. [Retrieval deep dive](#7-retrieval-deep-dive)
8. [Reranking (pointwise / pairwise / listwise)](#8-reranking-pointwise--pairwise--listwise)
9. [From chunks to revised baseline](#9-from-chunks-to-revised-baseline)
10. [Option C — Gold sets and metrics](#10-option-c--gold-sets-and-metrics)
11. [Verification workflow](#11-verification-workflow)
12. [Phased delivery](#12-phased-delivery)
13. [Illustrative sample modules](#13-illustrative-sample-modules)

---

## 1. Problem and system framing

| Layer | Cadence | Nature | Role |
|---|---|---|---|
| S&P Global country risk | ~quarterly | Structured numeric | Structural **baseline** |
| IMD digital / technology | ~every 2–3 years | Ordinal / survey | Slow-moving capability baseline |
| Factors / subfactors | Same as parent scores | Structured | Map to economic **drivers** |
| Emerging events | Continuous | Unstructured (news, research, blogs, podcasts, videos) | **Interim delta** until next official cycle |

**Drivers (examples):** supply, demand, capital, talent, technology, infrastructure, brand/reputation.

**Business rule:**  
Official scores produce baseline risk/opportunity per driver. Between publish dates, qualitative events (economist reports, S&P research, news) must be stored, retrieved, analyzed, and — only after confirmation — applied as overlays. When the next S&P/IMD cycle lands, events already reflected in that cycle are **absorbed** and flushed (or archived); only post-cycle events remain `active`.

Example sources:

- [S&P geopolitics / trade research hub](https://www.spglobal.com/en/research-insights/market-insights/global-trade/geopolitics)
- [S&P Energy: Hormuz tanker routing news](https://www.spglobal.com/energy/en/news-research/latest-news/crude-oil/090226-rerouting-after-hormuz-cuts-clean-tanker-cargoes-yet-fleet-expands)

Relation to this repo’s UHG demo: quant **baseline** + staged **overlay** is the same pattern; this document designs the **RAG memory** upstream of overlay extraction.

---

## 2. End-to-end pipeline

```text
┌──────────────┐   ┌─────────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐
│ Ingest URL / │ → │ Normalize   │ → │ Chunk    │ → │ Enrich  │ → │ Embed +  │
│ feed / PDF   │   │ + dedupe    │   │ (+parent)│   │ metadata│   │ Index    │
└──────────────┘   └─────────────┘   └──────────┘   └─────────┘   └────┬─────┘
                                                                       │
┌──────────────┐   ┌─────────────┐   ┌──────────┐   ┌─────────┐   ┌────▼─────┐
│ Apply delta  │ ← │ Human       │ ← │ Impact   │ ← │ Rerank  │ ← │ Retrieve │
│ to baseline  │   │ confirm     │   │ LLM      │   │         │   │ hybrid   │
└──────────────┘   └─────────────┘   └──────────┘   └─────────┘   └──────────┘
        │
        ▼
 Score-cycle job: mark absorbed / flush vectors older than new official as_of
```

---

## 3. Option A — Postgres schema and flush rules

### 3.1 Why Postgres (+ pgvector)

- Official score cycles are relational (dates, versions, countries, drivers).
- Lifecycle flush is a SQL job with clear predicates.
- pgvector keeps vectors next to metadata (one operational DB for POC/prod-lite).
- Optional later: OpenSearch for heavier BM25/faceting; keep Postgres as system of record.

### 3.2 Core tables (logical)

```sql
-- Official score calendar
CREATE TABLE score_cycle (
  cycle_id        TEXT PRIMARY KEY,           -- e.g. 'SP_2026Q2', 'IMD_2024'
  provider        TEXT NOT NULL,              -- 'SP_GLOBAL' | 'IMD'
  published_at    TIMESTAMPTZ NOT NULL,
  covers_from     TIMESTAMPTZ,                -- optional validity window
  covers_to       TIMESTAMPTZ,
  notes           TEXT
);

-- Baseline scores (normalized)
CREATE TABLE baseline_score (
  id              BIGSERIAL PRIMARY KEY,
  cycle_id        TEXT REFERENCES score_cycle(cycle_id),
  country_code    TEXT,
  industry        TEXT,
  driver          TEXT NOT NULL,              -- supply|demand|capital|...
  factor          TEXT,
  subfactor       TEXT,
  risk_0_100      DOUBLE PRECISION,
  opportunity_0_100 DOUBLE PRECISION,
  raw_payload     JSONB
);

-- Source documents
CREATE TABLE emerging_document (
  doc_id          UUID PRIMARY KEY,
  source_url      TEXT UNIQUE,
  publisher       TEXT,
  content_type    TEXT,                       -- news|research|blog|podcast|video
  title           TEXT,
  published_at    TIMESTAMPTZ,
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  language        TEXT DEFAULT 'en',
  checksum_sha256 TEXT,
  raw_uri         TEXT,                       -- blob store path
  full_text       TEXT,
  summary         TEXT,                       -- optional LLM abstract
  lifecycle       TEXT NOT NULL DEFAULT 'active',  -- active|absorbed|rejected
  score_cycle_anchor TEXT REFERENCES score_cycle(cycle_id), -- "active since"
  metadata        JSONB DEFAULT '{}'::jsonb
);

-- Chunks (parent-child)
CREATE TABLE emerging_chunk (
  chunk_id        UUID PRIMARY KEY,
  doc_id          UUID REFERENCES emerging_document(doc_id) ON DELETE CASCADE,
  parent_chunk_id UUID REFERENCES emerging_chunk(chunk_id),
  chunk_level     TEXT NOT NULL,              -- doc_summary|section|passage
  section_path    TEXT,                       -- 'Geopolitics > Shipping'
  ordinal         INT NOT NULL,
  text            TEXT NOT NULL,
  token_count     INT,
  -- denormalized filters for fast retrieve
  published_at    TIMESTAMPTZ,
  driver_tags     TEXT[] DEFAULT '{}',
  entity_tags     TEXT[] DEFAULT '{}',
  geo_tags        TEXT[] DEFAULT '{}',
  lifecycle       TEXT NOT NULL DEFAULT 'active',
  metadata        JSONB DEFAULT '{}'::jsonb
);

-- Embeddings (pgvector)
-- CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE emerging_embedding (
  chunk_id        UUID PRIMARY KEY REFERENCES emerging_chunk(chunk_id) ON DELETE CASCADE,
  embed_model     TEXT NOT NULL,              -- e.g. 'text-embedding-3-large'
  embed_version   TEXT NOT NULL,
  embedding       vector(3072),               -- dim depends on model
  embedded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX emerging_chunk_lifecycle_pub
  ON emerging_chunk (lifecycle, published_at DESC);
CREATE INDEX emerging_chunk_drivers_gin
  ON emerging_chunk USING GIN (driver_tags);
CREATE INDEX emerging_embedding_hnsw
  ON emerging_embedding USING hnsw (embedding vector_cosine_ops);

-- Confirmed overlays (downstream of RAG + LLM extract)
CREATE TABLE overlay_event (
  overlay_id      UUID PRIMARY KEY,
  doc_id          UUID REFERENCES emerging_document(doc_id),
  chunk_ids       UUID[],
  driver          TEXT NOT NULL,
  sign            TEXT NOT NULL,              -- risk|opportunity
  severity_0_to_3 INT,
  immediacy_0_to_3 INT,
  persistence_0_to_3 INT,
  novelty_0_to_1  DOUBLE PRECISION,
  status          TEXT NOT NULL,              -- staged|confirmed|rejected
  evidence_quote  TEXT,
  created_at      TIMESTAMPTZ DEFAULT now(),
  confirmed_at    TIMESTAMPTZ,
  absorbed_at     TIMESTAMPTZ
);
```

### 3.3 Flush / absorb rules

**Trigger:** insert of a new `score_cycle` for provider `SP_GLOBAL` or `IMD`.

**Policy (recommended):**

1. Compute `cutoff = new_cycle.published_at` (or provider-specific “as_of”).
2. Mark documents/chunks with `published_at <= cutoff` and `lifecycle = 'active'` → `absorbed`  
   (optional: only those overlapping themes covered by the new score release).
3. Soft-delete first; hard-delete vectors after retention window (e.g. 30 days) for audit.
4. Keep `overlay_event` rows with `absorbed_at` set for lineage; stop applying them to live baseline.

```sql
-- Illustrative absorb job
WITH new_cycle AS (
  SELECT cycle_id, published_at
  FROM score_cycle
  WHERE cycle_id = :new_cycle_id
)
UPDATE emerging_document d
SET lifecycle = 'absorbed'
FROM new_cycle c
WHERE d.lifecycle = 'active'
  AND d.published_at IS NOT NULL
  AND d.published_at <= c.published_at;

UPDATE emerging_chunk ch
SET lifecycle = 'absorbed'
WHERE ch.lifecycle = 'active'
  AND ch.doc_id IN (
    SELECT doc_id FROM emerging_document WHERE lifecycle = 'absorbed'
  );

UPDATE overlay_event o
SET absorbed_at = now()
WHERE o.absorbed_at IS NULL
  AND o.doc_id IN (
    SELECT doc_id FROM emerging_document WHERE lifecycle = 'absorbed'
  );
```

**Invariant for retrieval:** always filter `lifecycle = 'active'` AND `published_at > last_relevant_cycle.published_at`.

---

## 4. Chunking deep dive

### 4.1 Parameters to choose deliberately

| Parameter | Meaning | Typical starting point |
|---|---|---|
| `chunk_size_tokens` | Max tokens per passage chunk | News: 400–600; Research section: 600–900 |
| `chunk_overlap_tokens` | Shared tokens between adjacent passages | **10–15%** of size (e.g. 64–128) |
| `min_chunk_tokens` | Drop/merge tiny fragments | 50–80 |
| `separator_priority` | Split order | `\n## `, `\n### `, `\n\n`, sentence |
| `parent_max_tokens` | Parent section returned to LLM | 1500–2500 |
| `summary_max_tokens` | Doc-level summary chunk | 200–400 |
| `preserve_tables` | Don’t split mid-row | boolean true |
| `language` | Affects sentence splitter | `en` default |

**Overlap purpose:** keep entities/claims that sit on boundaries (e.g. “Hormuz” at end of chunk N, consequence at start of N+1).  
**Too much overlap:** duplicate hits, wasted context window.  
**Too little:** broken causality across chunks.

### 4.2 Strategy by content type

| Type | Strategy |
|---|---|
| News / blog | 1–3 passage chunks; light overlap; one doc summary |
| Long research | Hierarchy: doc summary → section parents → passage children |
| Transcript | Time-window chunks (e.g. 2–3 minutes) + optional speaker metadata |
| HTML hub pages | Extract article bodies only; don’t index nav/boilerplate |

### 4.3 Parent–child pattern

- **Embed** child passages (precision).  
- **Return** parent section text to the LLM (context completeness).  
- Store `parent_chunk_id` on children.

### 4.4 Illustrative chunker

```python
from dataclasses import dataclass
from typing import Iterator
import hashlib
import uuid

@dataclass
class ChunkParams:
    size_tokens: int = 512
    overlap_tokens: int = 64          # ~12.5%
    min_tokens: int = 60
    model_for_count: str = "cl100k_base"


def count_tokens(text: str) -> int:
    # production: tiktoken or provider tokenizer
    return max(1, len(text.split()))


def split_passages(text: str, params: ChunkParams) -> list[str]:
    """Greedy pack by paragraphs with overlap (illustrative)."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for p in paras:
        pt = count_tokens(p)
        if buf and buf_tokens + pt > params.size_tokens:
            chunks.append("\n\n".join(buf))
            # overlap: keep tail paragraphs approximating overlap_tokens
            keep: list[str] = []
            keep_tok = 0
            for q in reversed(buf):
                qt = count_tokens(q)
                if keep_tok + qt > params.overlap_tokens:
                    break
                keep.append(q)
                keep_tok += qt
            buf = list(reversed(keep))
            buf_tokens = keep_tok
        buf.append(p)
        buf_tokens += pt
    if buf:
        chunks.append("\n\n".join(buf))
    return [c for c in chunks if count_tokens(c) >= params.min_tokens]


def build_child_records(doc_id: str, section_path: str, text: str, params: ChunkParams):
    for i, passage in enumerate(split_passages(text, params)):
        yield {
            "chunk_id": str(uuid.uuid4()),
            "doc_id": doc_id,
            "chunk_level": "passage",
            "section_path": section_path,
            "ordinal": i,
            "text": passage,
            "token_count": count_tokens(passage),
        }
```

---

## 5. Embedding, metadata, indexing

### 5.1 What is embedded?

| Content | Embed? | Why |
|---|---|---|
| Passage text | **Yes (primary)** | Semantic match |
| `title + section_path + passage` | **Yes (recommended)** | Context header improves retrieval |
| Doc summary | Optional second vector | High-level recall |
| Raw metadata JSON | **No** | Dilutes semantics; use filters |
| Driver tags / dates / geo | **Filter columns** | Exact constraints |

**Do we embed metadata?**  
Generally **no**. Put metadata in columns / JSONB and filter at query time. Optionally embed a short “pseudo sentence” only if tags are free-form and must be semantic (rare if you normalize drivers to an enum).

### 5.2 Embedding model choices

| Model class | Example | Pros | Cons |
|---|---|---|---|
| OpenAI | `text-embedding-3-large` / `small` | Strong quality, simple API | Cost, dim size, vendor lock |
| Open dense SOTA | BGE-M3, E5, GTE | Strong multilingual / hybrid sparse+dense (M3) | Self-host ops |
| Local small | `bge-small`, `all-MiniLM` | Cheap POC | Weaker long-doc quality |

**Recommendation:** start `text-embedding-3-large` or `BGE-M3`; pin `embed_model` + `embed_version` on every row for safe re-embeds.

### 5.3 How to store metadata

- **Filterable fields** → first-class columns (`lifecycle`, `published_at`, `driver_tags[]`).  
- **Flexible extras** → `metadata JSONB` (paywall flag, author, campaign utm stripped, etc.).  
- **Never** put secrets or huge HTML in the vector row.

### 5.4 Indexing

| Index | Purpose |
|---|---|
| HNSW / IVFFlat on `embedding` | Dense ANN search |
| GIN on `driver_tags`, `entity_tags` | Tag filters |
| B-tree on `(lifecycle, published_at)` | Cycle window |
| Unique on `source_url` / checksum | Dedupe |
| Optional BM25 (OpenSearch / ParadeDB / `tsvector`) | Sparse lexical |

```sql
-- Postgres full-text (lightweight BM25-ish via ts_rank_cd)
ALTER TABLE emerging_chunk
  ADD COLUMN text_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED;
CREATE INDEX emerging_chunk_tsv ON emerging_chunk USING GIN (text_tsv);
```

---

## 6. Option B — Query → retrieve API contract

### 6.1 Purpose

Given a baseline context (country/industry/driver) and “as of” score cycle, return **active** evidence chunks to revise that driver’s risk/opportunity.

### 6.2 Request / response

```json
// POST /v1/rag/retrieve
{
  "query_text": "How does Hormuz disruption affect clean tanker supply and freight?",
  "driver": "supply",
  "country_codes": ["IR", "AE", "SA", "GLOBAL"],
  "industry": "energy_shipping",
  "after_cycle_id": "SP_2026Q2",
  "as_of": "2026-09-02T00:00:00Z",
  "top_k": 8,
  "methods": {
    "dense": true,
    "bm25": true,
    "metadata_filter": true,
    "mmr": true,
    "rerank": true
  }
}
```

```json
// 200 response
{
  "after_cycle_published_at": "2026-06-15T00:00:00Z",
  "retrieval": {
    "candidates_dense": 40,
    "candidates_bm25": 40,
    "fused": 50,
    "after_mmr": 20,
    "after_rerank": 8
  },
  "chunks": [
    {
      "chunk_id": "...",
      "doc_id": "...",
      "title": "Rerouting after Hormuz cuts clean tanker cargoes...",
      "source_url": "https://www.spglobal.com/energy/...",
      "published_at": "2026-09-02",
      "driver_tags": ["supply"],
      "score_dense": 0.81,
      "score_bm25": 12.4,
      "score_rrf": 0.032,
      "score_rerank": 0.74,
      "text": "...parent or child text...",
      "cite": "spglobal:hormuz-2026-09-02#chunk-3"
    }
  ]
}
```

### 6.3 Follow-on: impact extract (same session)

```json
// POST /v1/rag/impact
{
  "driver": "supply",
  "baseline_risk": 42.0,
  "chunk_ids": ["...", "..."],
  "require_citations": true
}
```

```json
{
  "overlay": {
    "sign": "risk",
    "severity_0_to_3": 2,
    "immediacy_0_to_3": 3,
    "persistence_0_to_3": 2,
    "novelty_0_to_1": 0.8,
    "rationale": "Cargo rerouting tightens clean tanker availability...",
    "evidence_chunk_ids": ["..."]
  },
  "status": "staged"
}
```

### 6.4 Illustrative service sketch

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

@dataclass
class RetrieveRequest:
    query_text: str
    driver: str
    after_cycle_id: str
    top_k: int = 8
    country_codes: Sequence[str] = ()


def resolve_cutoff(conn, cycle_id: str) -> datetime:
    row = conn.execute(
        "SELECT published_at FROM score_cycle WHERE cycle_id=%s", (cycle_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"unknown cycle {cycle_id}")
    return row[0]


def retrieve(conn, emb_client, reranker, req: RetrieveRequest) -> list[dict]:
    cutoff = resolve_cutoff(conn, req.after_cycle_id)
    qvec = emb_client.embed(
        f"Driver:{req.driver}\nQuestion:{req.query_text}"
    )

    dense = dense_search(
        conn, qvec,
        lifecycle="active",
        published_after=cutoff,
        driver=req.driver,
        limit=40,
    )
    sparse = bm25_search(
        conn, req.query_text,
        lifecycle="active",
        published_after=cutoff,
        driver=req.driver,
        limit=40,
    )
    fused = rrf_fuse(dense, sparse, k=60)
    diversified = mmr(fused, lambda c: c["embedding"], lam=0.7, top_n=20)
    reranked = reranker.rerank(req.query_text, diversified, top_k=req.top_k)
    return expand_to_parents(conn, reranked)
```

---

## 7. Retrieval deep dive

### 7.1 Method catalog

| Method | Type | What it searches | Strengths | Weaknesses |
|---|---|---|---|---|
| **Keyword / metadata filter** | Structured | SQL on tags, dates, lifecycle, geo | Exact “active Supply since Q2” | No paraphrase |
| **BM25** | Sparse lexical | Terms in title/body | Proper nouns (Hormuz, CMS), exact phrases | Misses synonyms |
| **Dense / semantic** | Vector ANN | Embedding similarity | Paraphrase, thematic match | Weak on rare IDs without hybrid |
| **BGE / E5 embeddings** | Dense (model family) | Same as dense | Strong open models; BGE-M3 also multi-vector/sparse | Hosting / dim management |
| **Hybrid (BM25 + dense)** | Fusion | Union of both | Best default for news+research | Needs tuning weights / RRF |
| **HyDE** | Query transform | Embed hypothetical answer | Helps vague questions | Extra LLM; can bias |
| **MMR** | Diversify | Reorder candidates | Reduces near-duplicate wires | May drop 2nd critical source |
| **Rerank (cross-encoder)** | Second stage | Query–doc pairs | Large quality jump | Cost/latency on large k |
| **Self-RAG / CRAG / Agentic** | Control loop | Multi-step retrieve/critique | Hard queries | Complexity; eval harder |

### 7.2 Recommended v1 stack

```text
metadata filters (lifecycle, date > cycle, driver)
        ↓
   ┌────┴────┐
 BM25      Dense (BGE / embedding-3)
   └────┬────┘
       RRF
        ↓
       MMR
        ↓
 cross-encoder rerank → top_k
```

### 7.3 Sparse detail

**Keyword search:** naive `ILIKE '%Hormuz%'` — use only for debugging.  

**Metadata search:** primary path for operational constraints:

```sql
WHERE lifecycle = 'active'
  AND published_at > :cutoff
  AND :driver = ANY(driver_tags)
  AND (geo_tags && :countries OR 'GLOBAL' = ANY(geo_tags))
```

**BM25:** OpenSearch `match`/`multi_match`, or Postgres `tsvector` + `ts_rank_cd`, or BGE-M3 learned sparse. Prefer real BM25 for news titles.

### 7.4 Dense / semantic detail

- Query embedding should include **driver context** (`"driver=supply; Hormuz tanker rerouting"`).  
- Retrieve `ef_search` / `top_n` >> final k (e.g. 40).  
- Always apply metadata filters **before or inside** ANN when the engine supports filtered search (pgvector + `WHERE`, Qdrant payload filter).

### 7.5 Fusion (RRF)

```python
def rrf_fuse(lists: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for result_list in lists:
        for rank, doc_id in enumerate(result_list, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return [d for d, _ in sorted(scores.items(), key=lambda x: -x[1])]
```

---

## 8. Reranking (pointwise / pairwise / listwise)

| Family | Idea | Examples | Use here |
|---|---|---|---|
| **Pointwise** | Score each (query, doc) independently | Cross-encoder relevance score; LLM “0–1 relevant” | **Default rerank** |
| **Pairwise** | Prefer doc A vs B for query | RankNet-style; LLM pairwise judge | Fine-tuning / hard negatives |
| **Listwise** | Optimize whole list | ListNet, LambdaMART; LLM list sort | Learning-to-rank if you have rich click/gold data |

**Cross-encoders** (e.g. `bge-reranker-v2-m3`, Cohere Rerank): jointly encode query+document → high-quality pointwise score. Run on fused top-20…50, emit top-5…8.

```python
def cross_encoder_rerank(query: str, docs: list[dict], model, top_k: int) -> list[dict]:
    pairs = [(query, d["text"]) for d in docs]
    scores = model.predict(pairs)  # higher = more relevant
    ranked = sorted(zip(docs, scores), key=lambda x: -float(x[1]))
    out = []
    for d, s in ranked[:top_k]:
        d = dict(d)
        d["score_rerank"] = float(s)
        out.append(d)
    return out
```

**LLM listwise (optional):** ask model to order citations — useful for demos, unstable for production metrics unless constrained to IDs only.

---

## 9. From chunks to revised baseline

Retrieval ≠ score update.

1. Pack top-k with citations.  
2. Structured LLM extract → overlay fields (sign, severity, immediacy, persistence, novelty, drivers).  
3. **Human confirm** (staged → confirmed).  
4. Deterministic combiner, e.g.:

\[
risk' = \mathrm{clip}_{0,100}\big(risk + w \cdot \Delta(\mathrm{severity}, \mathrm{sign})\big)
\]

with caps so overlays cannot erase the official S&P/IMD baseline.

Novelty high ⇒ larger interim weight; after absorb/flush ⇒ weight → 0.

---

## 10. Option C — Gold sets and metrics

### 10.1 Gold set design (tied to seven drivers)

Build **50–200** labeled items covering drivers: supply, demand, capital, talent, technology, infrastructure, brand.

**Retrieval gold row (`gold_retrieval.jsonl`):**

```json
{
  "id": "hormuz_supply_001",
  "query": "Impact of Hormuz disruption on clean tanker supply",
  "driver": "supply",
  "after_cycle_id": "SP_2026Q2",
  "relevant_chunk_ids": ["uuid-a", "uuid-b"],
  "relevant_doc_ids": ["doc-hormuz-2026-09-02"],
  "graded": {"uuid-a": 3, "uuid-b": 2, "uuid-c": 0}
}
```

**Impact / generation gold (`gold_impact.jsonl`):**

```json
{
  "id": "hormuz_supply_001_impact",
  "chunk_ids": ["uuid-a", "uuid-b"],
  "expected": {
    "sign": "risk",
    "drivers": ["supply"],
    "severity_0_to_3": [2, 3],
    "must_cite_urls": ["https://www.spglobal.com/energy/..."]
  },
  "forbidden_claims": ["pipeline explosion in Texas"]
}
```

Cover: synonym queries, metadata-only queries (“all active capital events since cycle”), distractors, multi-driver docs, near-duplicates.

### 10.2 Retrieval metrics

| Metric | Formula (intuition) | Target use |
|---|---|---|
| **Precision@k** | relevant_in_top_k / k | Noise control |
| **Recall@k** | relevant_in_top_k / all_relevant | Coverage |
| **F1@k** | harmonic mean of P & R | Single score |
| **Hit@k** | 1 if any relevant in k | Smoke |
| **MRR** | 1 / rank of first relevant | First-answer quality |
| **nDCG@k** | discounted graded gains / ideal | Rank quality with grades |
| **Filter compliance** | % results obeying date/lifecycle/driver | Lifecycle correctness |

```python
def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for x in top if x in relevant) / len(top)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(retrieved[:k])
    return len(top & relevant) / len(relevant)


def mrr(retrieved: list[str], relevant: set[str]) -> float:
    for i, x in enumerate(retrieved, start=1):
        if x in relevant:
            return 1.0 / i
    return 0.0


def dcg(scores: list[float]) -> float:
    import math
    return sum((2**s - 1) / math.log2(i + 2) for i, s in enumerate(scores))


def ndcg_at_k(retrieved: list[str], graded: dict[str, float], k: int) -> float:
    gains = [float(graded.get(x, 0)) for x in retrieved[:k]]
    ideal = sorted(graded.values(), reverse=True)[:k]
    idcg = dcg(ideal)
    return 0.0 if idcg == 0 else dcg(gains) / idcg
```

### 10.3 Generation / analysis metrics

| Metric | What it checks |
|---|---|
| **Faithfulness** | Claims supported by retrieved chunks (no invented events) |
| **Answer relevance** | Addresses driver/question |
| **Context relevance** | Chunks are about the query |
| **Citation accuracy** | URLs/chunk IDs back claims |
| **Driver attribution** | Correct driver tags vs gold |
| **Severity calibration** | Within human ±1 band (double-rate) |

These can be offline (human/gold) or LLM-as-judge (same idea as this repo’s `phoenix.evals` / narrative judges), but **humans remain source of truth** for release gates.

---

## 11. Verification workflow

```text
                    ┌─────────────────────────┐
   Ingest sample ─► │ Gold chunk/doc labels   │
                    └───────────┬─────────────┘
                                ▼
                    Run retrieve variants
                    (bm25 | dense | hybrid | +rerank)
                                ▼
                    Compute P@k R@k MRR nDCG
                    + filter compliance
                                ▼
                    Run impact LLM on retrieved set
                                ▼
                    Faithfulness / relevance / calibration
                                ▼
                    Gate: hybrid+rerank must beat bm25-only
                          on nDCG@8 and faithfulness
```

**Online:** log retrieved chunk IDs + overlay decisions; sample weekly for human review; track stale `active` docs older than latest cycle (should be ~0 after flush job).

**Chunk–answer verification checklist:**

1. Every severity claim cites ≥1 chunk_id.  
2. No claim outside chunk date window.  
3. Driver in overlay ⊆ drivers evidenced in chunks.  
4. If retrieval hit@8 fails gold, do **not** trust generated overlay.

---

## 12. Phased delivery

| Phase | Deliverable |
|---|---|
| 0 | Schema + score_cycle + ingest one S&P RSS/HTML source |
| 1 | Chunk + embed + hybrid retrieve API (read-only evidence) |
| 2 | Impact extract → staged overlay → confirmed baseline delta |
| 3 | Absorb/flush job on new cycle; retrieval + gen eval harness |
| 4 | Optional HyDE/CRAG; multi-source connectors; learning-to-rank |

---

## 13. Illustrative sample modules

### 13.1 Ingest + embed

```python
def ingest_url(conn, url: str, after_cycle_id: str, embedder, chunk_params: ChunkParams):
    html = fetch(url)
    title, published_at, text = normalize_article(html)
    doc_id = upsert_document(conn, url, title, published_at, text, after_cycle_id)
    for section_path, section_text in split_sections(text):
        parent = insert_parent_chunk(conn, doc_id, section_path, section_text)
        for child in build_child_records(doc_id, section_path, section_text, chunk_params):
            child["parent_chunk_id"] = parent["chunk_id"]
            child["driver_tags"] = tag_drivers(child["text"])  # rules or LLM
            insert_chunk(conn, child)
            vec = embedder.embed(f"{title}\n{section_path}\n{child['text']}")
            insert_embedding(conn, child["chunk_id"], vec, embedder.model_name)
```

### 13.2 Hybrid retrieve + metrics eval loop

```python
def evaluate_retrieval(gold_path: str, retrieve_fn) -> dict:
    import json
    rows = [json.loads(l) for l in open(gold_path, encoding="utf-8")]
    metrics = {"p@8": [], "r@8": [], "mrr": [], "ndcg@8": []}
    for row in rows:
        req = RetrieveRequest(
            query_text=row["query"],
            driver=row["driver"],
            after_cycle_id=row["after_cycle_id"],
            top_k=8,
        )
        hits = [h["chunk_id"] for h in retrieve_fn(req)]
        rel = set(row["relevant_chunk_ids"])
        graded = row.get("graded", {i: 1 for i in rel})
        metrics["p@8"].append(precision_at_k(hits, rel, 8))
        metrics["r@8"].append(recall_at_k(hits, rel, 8))
        metrics["mrr"].append(mrr(hits, rel))
        metrics["ndcg@8"].append(ndcg_at_k(hits, graded, 8))
    return {k: sum(v) / len(v) for k, v in metrics.items()}
```

### 13.3 Faithfulness check (sketch)

```python
def faithfulness_score(answer: str, chunk_texts: list[str], judge_llm) -> dict:
    context = "\n---\n".join(chunk_texts)
    # returns {faithful: bool, unsupported_claims: [...], score: float}
    return judge_llm.judge(answer=answer, context=context)
```

---

## Quick reference

| Topic | Choice |
|---|---|
| System of record | Postgres + score cycles + lifecycle |
| Vectors | pgvector (HNSW); optional OpenSearch BM25 |
| Chunking | Section-aware parent–child; size 512±, overlap ~64 (10–15%) |
| Embed | Title+section+passage; metadata as **filters** |
| Retrieve v1 | Filters + BM25 + dense → RRF → MMR → cross-encoder rerank |
| Advanced later | HyDE, CRAG, agentic, listwise LTR |
| Downstream | Staged overlay → human confirm → capped baseline delta |
| Flush | On new S&P/IMD cycle: absorb `published_at <= cycle.published_at` |
| Eval | Gold nDCG/MRR/P@k/R@k + faithfulness/relevance/calibration |

---

## Next decisions (product)

1. Single DB (Postgres+pgvector) vs Postgres + OpenSearch from day one.  
2. Embedding vendor (OpenAI vs self-hosted BGE-M3).  
3. Whether driver tagging at ingest is rules-based, LLM, or both.  
4. Hard-delete vs archive-only after absorb.

No implementation is included in the application codebase beyond this document.
