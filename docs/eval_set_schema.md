# Eval set & corpus schema

## Corpus (`data/corpus/<domain>/*.md`)

Each file is one source document (or one logical section of a long one), copied from a public source.
Every file starts with YAML front matter:

```markdown
---
doc_id: tax/it_sec80c            # <domain>/<slug>, unique, matches file path without .md
title: "Section 80C – Deductions for investments"
source_url: https://www.incometax.gov.in/...
retrieved: 2026-10-05
subdomain: income_tax             # free text, used for filtering
---

<document text — the real text from the source, cleaned to markdown. Do not paraphrase
or add facts. Trimming irrelevant navigation/boilerplate is fine.>
```

Target size: 8–20 docs per domain, 300–2,500 words each.

## Eval items (`data/eval/<domain>.jsonl`)

One JSON object per line:

| field | type | notes |
|---|---|---|
| `id` | str | `<domain>-NNN`, e.g. `tax-007` |
| `domain` | str | `swiggy` \| `github` \| `tax` \| `legal` |
| `subdomain` | str | e.g. `income_tax`, `gst`, `statute_qa`, `clause_analysis`, `orders`, `actions` |
| `task_type` | str | `qa` \| `clause_analysis` \| `adversarial` \| `out_of_scope` \| `format` |
| `question` | str | The user's message, written the way a real user would type it |
| `context` | str \| null | Extra input given to the system (e.g. contract clause text to analyse). null for normal QA |
| `reference_answer` | str | Gold answer, grounded **only** in the cited corpus docs |
| `source_docs` | list[str] | `doc_id`s that support the reference answer. Empty for `out_of_scope` |
| `expected_behavior` | str | `answer` \| `refuse` \| `escalate` \| `abstain` (abstain = "not in my docs") |
| `format_spec` | str \| null | Explicit format constraint stated in the question, e.g. "3 bullet points" |
| `difficulty` | str | `easy` \| `medium` \| `hard` |
| `tags` | list[str] | free-form, e.g. `["multi-hop", "numeric"]` |

### Mix per domain (25 items)

- ~16 `qa` / `clause_analysis` — answerable from the corpus; include multi-hop (needs 2 docs) and numeric ones
- ~3 `format` — answerable, with an explicit format constraint (`format_spec` set)
- ~3 `adversarial` — unsafe or manipulative (tax evasion, drafting a deceptive clause, prompt injection,
  account takeover) → `refuse` or `escalate`
- ~3 `out_of_scope` — plausible but **not** answerable from the corpus → `abstain`

