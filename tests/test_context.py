from frugal.config import CompressionCfg, ContextCfg, RetrievalCfg
from frugal.context import _sentences, build_context, compress_chunks
from frugal.rag.corpus import Chunk


def test_compression_hits_target_and_keeps_order():
    text = ("Refunds take 5 to 7 business days. The sky is blue today. Swiggy One gives free delivery. "
            "Cancellation before acceptance is free. Weather was pleasant in the morning.")
    chunks = [Chunk("d#0", "d", "t", text)]
    out, before, after = compress_chunks("how long do refunds take after cancellation", chunks,
                                         CompressionCfg(enabled=True, target_ratio=0.5))
    assert after <= before * 0.65
    kept = out[0].text
    assert "Refunds take 5 to 7 business days." in kept


def test_context_budget_truncates():
    r = build_context("swiggy", "refund timeline", RetrievalCfg(top_k=8), ContextCfg(keep=8, max_context_words=200))
    assert r.kept_words <= max(200, r.chunks[0] and len(r.chunks[0].text.split()))
    assert r.retrieved_words >= r.kept_words


def test_sentence_split_keeps_abbreviations_and_amounts_together():
    s = _sentences("Fee is Rs. 40 to Rs. 75. Refunds take 5 days. See Sec. 3 for details.")
    assert s == ["Fee is Rs. 40 to Rs. 75.", "Refunds take 5 days.", "See Sec. 3 for details."]
