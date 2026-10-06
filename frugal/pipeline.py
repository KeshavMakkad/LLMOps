"""Single request path: cache -> context -> compression -> routing -> model."""

from __future__ import annotations

import time

from pydantic import BaseModel

from frugal.cache import SemanticCache, cache_scope, embed_question
from frugal.config import Policy, load_domains, load_prompt
from frugal.context import build_context, compress_chunks
from frugal.llm import LLMError, complete
from frugal.router import route
from frugal.trace import Request


class Record(BaseModel):
    req_id: str
    group_id: str
    kind: str
    policy: str
    answer: str = ""
    served_from: str = "llm"  # llm | exact_cache | semantic_cache | error
    cache_similarity: float | None = None
    cache_source_req: str | None = None
    cache_source_group: str | None = None
    tier: str | None = None
    route_rule: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0  # actual spend ($0 on free tiers)
    est_cost_usd: float = 0.0  # the same tokens at paid-tier prices (labelled estimate)
    llm_ms: float = 0.0  # provider latency
    overhead_ms: float = 0.0  # our own work: embeddings, cache lookup, rerank, compression
    retrieved_words: int = 0
    context_words: int = 0  # retrieved context actually sent, after rerank/truncation/compression
    retrieved_docs: list[str] = []
    llm_cached: bool = False  # answered from the dev response cache (replay), not a live call
    fallback: bool = False  # cheap tier failed or returned nothing, retried on strong
    error: str | None = None

    @property
    def latency_ms(self) -> float:
        return self.overhead_ms + self.llm_ms

    @property
    def false_hit(self) -> bool:
        return self.served_from.endswith("cache") and self.cache_source_group != self.group_id


def _render(template: str, **vals: str) -> str:
    for k, v in vals.items():
        template = template.replace("{" + k + "}", v)
    return template


def answer_with_llm(req: Request, policy: Policy, rec: Record, run_id: str = "") -> Record:
    """Everything after a cache miss. Mutates and returns rec."""
    t0 = time.perf_counter()
    query = req.question if not req.context else f"{req.question}\n{req.context[:400]}"
    ctx = build_context(req.domain, query, policy.retrieval, policy.context)
    chunks = ctx.chunks
    if policy.compression.enabled and chunks:
        chunks, _, _ = compress_chunks(req.question, chunks, policy.compression)
    tier, rule = route(req.question, req.context, ctx.top_rerank_score, policy.downshift, policy.default_tier)

    prompt = load_prompt(policy.prompt_version)
    dom = load_domains().get(req.domain, {"name": req.domain, "description": ""})
    docs = ""
    if chunks:
        docs = "<documents>\n" + "\n".join(
            f'<doc id="{c.doc_id}">\n{c.text}\n</doc>' for c in chunks) + "\n</documents>"
    ctx_block = f"<user_provided_text>\n{req.context}\n</user_provided_text>" if req.context else ""
    system = _render(prompt["system"], domain_name=dom["name"], domain_description=dom["description"])
    user = _render(prompt["user"], documents=docs, context=ctx_block, question=req.question)
    rec.overhead_ms += (time.perf_counter() - t0) * 1000

    rec.route_rule = rule
    rec.retrieved_words = ctx.retrieved_words
    rec.context_words = sum(len(c.text.split()) for c in chunks)
    rec.retrieved_docs = list(dict.fromkeys(c.doc_id for c in chunks))
    tiers = [tier] if tier == "strong" else [tier, "strong"]
    for t in tiers:
        rec.tier, rec.model = t, policy.models[t]
        try:
            resp = complete(rec.model, system, user, max_tokens=policy.max_output_tokens, purpose="answer",
                            trace_meta={"run_id": run_id, "policy": policy.name, "req": req.req_id, "tier": t})
        except LLMError as exc:
            rec.error = str(exc)
            rec.fallback = t != "strong"
            continue
        # tokens of a failed cheap attempt still count
        rec.prompt_tokens += resp.input_tokens
        rec.output_tokens += resp.output_tokens
        rec.cost_usd += resp.cost_usd
        rec.est_cost_usd += resp.est_cost_usd
        rec.llm_ms += resp.latency_ms
        rec.llm_cached = resp.cached
        if resp.text.strip():
            rec.answer, rec.error = resp.text.strip(), None
            return rec
        rec.fallback = t != "strong"
    rec.served_from = "error"
    rec.error = rec.error or "empty answer"
    return rec


def handle(req: Request, policy: Policy, cache: SemanticCache, run_id: str = "") -> Record:
    """Live path (API): look up, answer on miss, store."""
    rec = Record(req_id=req.req_id, group_id=req.group_id, kind=req.kind, policy=policy.name)
    t0 = time.perf_counter()
    scope = cache_scope(req.domain, req.context)
    vec = embed_question(req.question) if policy.cache.semantic else None
    hit = cache.lookup(scope, req.question, vec, domain=req.domain)
    rec.overhead_ms = (time.perf_counter() - t0) * 1000
    if hit:
        rec.answer, rec.served_from = hit.entry.answer, f"{hit.kind}_cache"
        rec.cache_similarity, rec.cache_source_req = hit.similarity, hit.entry.req_id
        rec.cache_source_group = hit.entry.group_id
        return rec
    rec = answer_with_llm(req, policy, rec, run_id)
    if rec.served_from == "llm" and rec.answer:  # never cache an empty or failed answer
        cache.store(scope, req.question, rec.answer, req.req_id, req.group_id, vec)
    return rec
