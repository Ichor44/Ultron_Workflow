---
name: dna_lab_swarm
description: Evo2-powered DNA swarm — sub-agents batch score variants while sub-bots fetch live sequences from NCBI/ClinVar. Demonstrates Ultron DNA Lab v2 with parallel orchestration.
triggers: dna swarm, dna lab swarm, batch score brca1, evo2 batch, fetch and score, sub bot dna
---

# DNA Lab Swarm — Evo2 Batch + Sub-Bot Fetch

Orchestrates Ultron DNA Lab v2 with sub-agents (Apollo/Hephaestus) and sub-bots (Aphrodite/Hermes) for scalable genomic analysis.

## When to use
- Score dozens/hundreds of variants against a reference (BRCA1, CFTR panels)
- Generate many sequences in parallel (promoter library)
- Fetch live sequences from NCBI/Ensembl/ClinVar via Firecrawl sub-bots, then score/analyze
- Need offline seq-ops that degrade gracefully (reverse_complement, orf_find, codon_optimize) without NVIDIA key

## Skills + Nodes involved
- `skills/dna_lab.py` v2 — Evo2 NIM (generate/score/embeddings/forward/analyze) + seq-ops (reverse_complement, transcribe, orf_find, codon_optimize, validate, gc_content) + batch (ThreadPoolExecutor max_workers=4) + fetch via SubBotManager/NCBI fallback
- `ultron-workflow/src/nodes/DNALabNode.ts` v2 — workflow node routing to `/api/dna-lab/run` with snake_case + camelCase alias normalization, auto 180s timeout for batch/fetch, offline fallbacks
- `web.py` — fixed `/api/dna-lab/run` dispatch (Evo2 → dna_lab else protein_lab), new `/api/dna-lab/batch` and `/api/dna-lab/fetch`, merged `_DNALAB_ACTIONS` (25 actions)
- `ultron_sub_bots` — SubBotManager (SearchBot/ScrapeBot) via `fetch_and_analyze` / `fetch_and_score`; `ultron-workflow/src/nodes/SubBotNode.ts` for manual search→scrape→DNALab chaining

## Sub-Agent Pattern (Apollo → Hephaestus workers → Apollo Gather)
```
SubBotNode [search ClinVar "BRCA1 pathogenic"]  ──┐
     ↓ urls                                         │
SubBotNode [scrape NCBI Nucleotide FASTA]  ─────────┤
     ↓ variant_sequences[] + reference               │
SubAgentNode [apollo splitter, mode=broadcast] ─────┤
   shards 4 × 10 variants                            │
     ├─ DNALabNode v2 [hephaestus-1 batch_score shard 0-9]   ┐ parallel level
     ├─ DNALabNode v2 [hephaestus-2 shard 10-19]              │ (ultron-workflow computeTopologicalLevels)
     ├─ DNALabNode v2 [hephaestus-3 shard 20-29]              │
     └─ DNALabNode v2 [hephaestus-4 shard 30-39]   ───────────┘
                              ↓ results[]
SubAgentNode [apollo gather, waitForMessage=true, collaborationMode=broadcast]
     ↓ sorted scores
DNALabNode [analyze reference + reporter]
```

Each Hephaestus calls `POST /api/dna-lab/run action=batch_score` (server ThreadPoolExecutor fans out again if needed). Apollo gather merges via `broadcastAgentMessage`, sorts by `cos_dist` (HIGH >0.15, MOD >0.05, LOW).

## Sub-Bot Pattern (Aphrodite Search → Hermes Scrape)
- On canvas: `SubBotNode workflowId=brca1-search task=search query="ClinVar BRCA1 pathogenic missense NM_007294.3"`
- Then `SubBotNode workflowId=brca1-scrape waitForPrevious=true urls={{brca1-search.urls}} task=scrape`
- Then wire `{{brca1-scrape.variant_sequences}}` into `DNALabNode.batch_score.referenceSequence={{brca1-scrape.referenceSequence}}`
- Or one-step server composite: `DNALabNode action=fetch_and_analyze query=NM_007294.3` (calls SubBotManager internally) + fallback to `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nucleotide&id=NM_007294.3&rettype=fasta`

## Quick start (Python skill)
```python
from skills import dna_lab

# Offline seq-ops — no key needed
print(dna_lab.run(action="reverse_complement", sequence="ATGCGT"))
print(dna_lab.run(action="orf_find", sequence="ATGAAATAGATGCCCCCTAA"))
print(dna_lab.run(action="codon_optimize", sequence="ATGCGTACGTAGCTAG", organism="human"))
print(dna_lab.run(action="validate", sequence="ATGCGTXXX"))
print(dna_lab.run(action="gc_content", sequence="ATGCATGCATGC"))
print(dna_lab.run(action="batch_analyze", sequences=["ATGCATGC","GGCCGGCC","TTAATTAA"], k=3))

# Evo2 — requires NVIDIA_API_KEY
print(dna_lab.run(action="generate", sequence="ACTGACTGACTGACTG", num_tokens=50))
print(dna_lab.run(action="score", reference_sequence="ATGCGTACGT", variant_sequence="ATGCGTACGA"))

# Batch (sub-agent fan-out, 4 workers)
print(dna_lab.run(action="batch_score", reference_sequence="ATGCGTACGT",
                  variant_sequences=["ATGCGTACGA","ATGCGTACGG","ATGCGTACGC"]))

# Fetch via sub-bots / NCBI
print(dna_lab.run(action="fetch_and_analyze", accession="NM_007294.3"))
print(dna_lab.run(action="fetch_and_score", query="NM_007294.3", variant_sequence="ATGCGTACGA"))
```

## Quick start (HTTP via web.py)
```bash
curl -X POST http://localhost:5000/api/dna-lab/run -H Content-Type:application/json \
  -d '{"action":"reverse_complement","sequence":"ATGCGT"}'

curl -X POST http://localhost:5000/api/dna-lab/run -H Content-Type:application/json \
  -d '{"action":"orf_find","sequence":"ATGAAATAGATGCCCCCTAA"}'

curl -X POST http://localhost:5000/api/dna-lab/batch -H Content-Type:application/json \
  -d '{"action":"batch_analyze","sequences":["ATGCATGC","GGCCGGCC"]}'

curl -X POST http://localhost:5000/api/dna-lab/fetch -H Content-Type:application/json \
  -d '{"query":"NM_007294.3","auto_analyze":true}'

curl http://localhost:5000/api/dna-lab/actions | jq .actions[].id
curl http://localhost:5000/api/dna-lab/health
curl http://localhost:5000/api/biolab/health
```

## Quick start (Workflow JSON)
See `ultron-workflow/src/templates/dna-lab-swarm.json` — import in Ultron Workflow desktop (File → Import) to get a prewired 6-node swarm.

## References
- `skills/dna_lab.py` — 19 Evo2 actions (line 77-106 TRIGGERS, 1897 lines, helpers _clean_dna/_reverse_complement/_orf_find/_codon_optimize/_fetch_via_subbots, batch ThreadPoolExecutor)
- `ultron-workflow/src/nodes/DNALabNode.ts` — 308 lines, 24 inputs, 6 outputs, local fallbacks + 180s auto-timeout for batch/fetch
- `web.py` lines 808+ — DNA_EVO2_ACTIONS/LEGACY dispatch, _dna_normalize_kwargs, /api/dna-lab/run|batch|fetch, _DNALAB_ACTIONS 25, /api/dna-lab/actions, /api/dna-lab/health, /api/biolab/health (evo2_nim, sub_bots)
- `ultron_sub_bots/manager.py` — SubBotManager, core.run_parallel, bots Scrape/Crawl/Search/Map/Interact/Monitor/Download via Firecrawl CLI
- `ultron-workflow/src/nodes/SubAgentNode.ts` / `SubBotNode.ts` — collaborationMode broadcast/pairwise/roundRobin, waitForMessage, workflow nesting
