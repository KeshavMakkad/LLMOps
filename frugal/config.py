"""YAML config loading: model registry, policies, prompts."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("FRUGAL_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"
_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------- models


class ModelSpec(BaseModel):
    key: str
    provider: str  # gemini | openrouter | fake
    model: str
    family: str = ""
    # What you ACTUALLY pay per 1M tokens (0 on free tiers): drives "actual spend".
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    # Published paid-tier price per 1M tokens: drives the clearly-labelled "$ at paid-tier prices"
    # estimate. Source + date recorded in configs/models.yaml.
    paid_input_per_mtok: float = 0.0
    paid_output_per_mtok: float = 0.0
    rpm: int = 60
    supports_system: bool = True
    supports_json_mode: bool = True
    disable_thinking: bool = False
    thinking_level: str | None = None  # e.g. "minimal" for Gemma 4 (it rejects thinking_budget)


@lru_cache
def load_models() -> dict[str, ModelSpec]:
    raw = _load_yaml(CONFIG_DIR / "models.yaml")
    return {k: ModelSpec(key=k, **v) for k, v in raw["models"].items()}


def get_model(key: str) -> ModelSpec:
    models = load_models()
    if key not in models:
        raise KeyError(f"unknown model '{key}'. Known: {sorted(models)}")
    return models[key]


@lru_cache
def load_domains() -> dict[str, dict]:
    return _load_yaml(CONFIG_DIR / "domains.yaml")["domains"]


# ---------------------------------------------------------------- policies


class CacheCfg(BaseModel):
    exact: bool = False
    semantic: bool = False
    threshold: float = 0.92  # cosine similarity needed to consider a cached answer
    # Guards against near-misses ("tax on 15L" vs "tax on 18L" embed almost identically):
    number_guard: bool = False  # the numbers in both questions must match (units normalised)
    verify_model: str | None = None  # cheap LLM confirms "the same answer is correct for both"
    max_candidates: int = 3  # how many above-threshold entries to try, best first


class RetrievalCfg(BaseModel):
    enabled: bool = True
    chunk_words: int = 150
    overlap_words: int = 30
    top_k: int = 8  # candidates fetched from the vector index


class ContextCfg(BaseModel):
    rerank: bool = False  # cross-encoder rerank of the retrieved candidates
    keep: int = 8  # chunks kept after (re)ranking
    max_context_words: int | None = None  # hard truncation budget for retrieved context


class CompressionCfg(BaseModel):
    enabled: bool = False
    target_ratio: float = 0.6  # keep ~this fraction of context words (query-aware extractive)
    min_sentence_words: int = 4


class DownshiftRule(BaseModel):
    """First matching rule wins. All conditions in a rule must hold."""

    name: str
    tier: str  # strong | cheap
    has_user_context: bool | None = None  # user pasted text (e.g. a contract clause)
    numeric_reasoning: bool | None = None  # asks to calculate / compare amounts
    max_question_words: int | None = None
    min_top_rerank_score: float | None = None  # retrieval confidence


class DownshiftCfg(BaseModel):
    enabled: bool = False
    rules: list[DownshiftRule] = Field(default_factory=list)


class Policy(BaseModel):
    name: str
    description: str = ""
    prompt_version: str = "v1"
    models: dict[str, str] = Field(default_factory=lambda: {"strong": "gemini-lite", "cheap": "gemma-26b"})
    default_tier: str = "strong"
    max_output_tokens: int = 700
    cache: CacheCfg = Field(default_factory=CacheCfg)
    retrieval: RetrievalCfg = Field(default_factory=RetrievalCfg)
    context: ContextCfg = Field(default_factory=ContextCfg)
    compression: CompressionCfg = Field(default_factory=CompressionCfg)
    downshift: DownshiftCfg = Field(default_factory=DownshiftCfg)


def load_policy(name_or_path: str, allow_path: bool = True) -> Policy:
    """By name from configs/policies/, or (CLI only) a YAML path. The API passes
    allow_path=False so callers can't make the service read arbitrary files."""
    if _NAME_RE.fullmatch(name_or_path):
        path = CONFIG_DIR / "policies" / f"{name_or_path}.yaml"
    elif allow_path and name_or_path.endswith((".yaml", ".yml")):
        path = Path(name_or_path)
    else:
        raise FileNotFoundError(name_or_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return Policy(**_load_yaml(path))


def list_policies() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "policies").glob("*.yaml"))


@lru_cache
def load_prompt(version: str) -> dict:
    if not _NAME_RE.fullmatch(version):
        raise FileNotFoundError(version)
    return _load_yaml(CONFIG_DIR / "prompts" / f"{version}.yaml")
