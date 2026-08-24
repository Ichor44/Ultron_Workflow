"""
DNA Lab v2 - Genomic Foundation Model Toolkit powered by Evo2.

A dedicated interface for Arc Institute's Evo2 genomic foundation model.
Evo2 is a 40B parameter DNA language model trained on 9.3 trillion nucleotides
from 100,000+ species across all domains of life.

Capabilities:
  - DNA sequence generation (autocomplete, de novo design)
  - Variant effect prediction (BRCA1-style zero-shot scoring)
  - Genomic embeddings for downstream ML tasks
  - Forward pass / logits computation
  - Multi-species genome analysis
  - Sequence utilities: reverse complement, complement, transcription
  - ORF finding (6-frame), codon optimization, GC content, validation
  - Batch operations via ThreadPoolExecutor (sub-agent orchestration)
  - Fetch-and-analyze via sub-bots / NCBI fallback (sub_bot, firecrawl)

Access:
  - NVIDIA NIM API (cloud-hosted, no local GPU needed)
  - Requires NVIDIA_API_KEY from https://build.nvidia.com/arc/evo2-40b

Usage:
  result = run(action="generate", sequence="ACTGACTGACTGACTG", num_tokens=200)
  result = run(action="score", reference_sequence="ATGCGTACGT", variant_sequence="ATGCGTACGA")
  result = run(action="embeddings", sequence="ATGCGTACGTAGCTAG")
  result = run(action="forward", sequence="ATGCGTACGTAGCTAG")
  result = run(action="analyze", sequence="ATGCGTACGTAGCTAG")
  result = run(action="reverse_complement", sequence="ATGCGTACGT")
  result = run(action="orf_find", sequence="ATGAAATAGATGCCCCCTAA")
  result = run(action="codon_optimize", sequence="ATGCGTACGT", organism="human")
  result = run(action="batch_analyze", sequences=["ATGC", "GGCC", "TTAA"])
  result = run(action="fetch_and_analyze", query="BRCA1", accession="NM_007294.3")

v2 improvements:
  - Added imports: concurrent.futures, re, base64, io, threading, time
  - Expanded TRIGGERS to include sub-bot / fetch terms and new actions
  - New helpers: _clean_dna, _reverse_complement, _complement, _transcribe,
    _reverse_transcribe, _gc_content, _kmer_counts, _codon_optimize,
    _orf_find, _validate_sequence, _fetch_via_subbots
  - New actions: reverse_complement, complement, transcribe, reverse_transcribe,
    orf_find, codon_optimize, validate, gc_content, batch_score, batch_generate,
    batch_embeddings, batch_analyze, fetch_and_analyze, fetch_and_score
  - Batch orchestration via ThreadPoolExecutor(max_workers=4)
  - Sub-bot integration with graceful fallback
"""

import os
import json
import re
import base64
import io
import threading
import time
import requests
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Any

try:
    import numpy as np
except ImportError:
    np = None

# Biotite integration (optional - falls back gracefully if not installed)
try:
    import biotite
    BIOTITE_AVAILABLE = True
except ImportError:
    BIOTITE_AVAILABLE = False

NAME = "dna_lab"
DESCRIPTION = "Genomic foundation model toolkit powered by Evo2 (Arc Institute): DNA generation, variant scoring, embeddings, forward pass, ORF finding, codon optimization, transcription, batch processing, and fetch-and-analyze via sub-bots."
TRIGGERS = [
    "evo2", "evo 2", "evo-2", "arc institute evo2",
    "dna generation", "dna sequence generation", "genome generation",
    "dna language model", "genomic foundation model",
    "brca1 scoring", "variant effect prediction", "zero-shot prediction",
    "dna embeddings", "genomic embeddings",
    "dna lab", "genomic analysis", "genome analysis",
    "dna design", "synthetic biology", "synthetic genome",
    "nucleotide", "dna sequence", "genome sequence",
    "gene essentiality", "exon classification",
    # v2: sub-bot / fetch terms
    "sub bot", "subbot", "sub-bot", "sub bots", "sub_bots", "ultron sub bots", "ultron_sub_bots", "SubBotManager",
    "firecrawl", "firecrawl search", "firecrawl scrape",
    "fetch", "fetch and analyze", "fetch_and_analyze", "fetch and score", "fetch_and_score",
    "ncbi", "genbank", "accession", "identifier", "pubmed fetch",
    # v2: new actions
    "reverse complement", "reverse_complement", "watson crick", "watson-crick",
    "complement", "dna complement",
    "transcribe", "transcription", "dna to rna", "dna->rna",
    "reverse transcribe", "reverse_transcribe", "rna to dna", "rna->dna",
    "orf", "orf find", "orf_find", "open reading frame", "6 frame", "six frame",
    "codon optimize", "codon_optimize", "codon optimization", "codon optimisation",
    "validate", "validate sequence", "sequence validation", "dna validation",
    "gc content", "gc_content", "gc-content", "gc%",
    "batch score", "batch_score", "batch generate", "batch_generate",
    "batch embeddings", "batch_embeddings", "batch analyze", "batch_analyze",
    "k-mer", "kmer", "codon usage",
    "rna", "dna complement",
    # v3: integrated advanced features
    "primer", "primer design", "primer_design", "primers",
    "crispr", "guide rna", "grna", "gRNA", "cas9", "pam",
    "melting temperature", "melting_temperature", "melting_temp", "tm", "Tm", "melting temp",
    "genome pipeline", "genome_pipeline", "snakemake", "pipeline",
    "dna to protein integrated", "dna_to_protein_integrated", "protein_lab integration",
]

# NVIDIA NIM API endpoints for Evo2
# Docs: https://docs.nvidia.com/nim/bionemo/evo2/latest/overview.html
_EVO2_GENERATE_URL = "https://health.api.nvidia.com/v1/biology/arc/evo2-40b/generate"
_EVO2_FORWARD_URL = "https://health.api.nvidia.com/v1/biology/arc/evo2-40b/forward"

# Alternative: use integrate.api.nvidia.com for chat-style access
_EVO2_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Thread safety for batch operations
_BATCH_LOCK = threading.Lock()
_BATCH_RESULTS = {}

# Standard codon table (DNA -> AA single letter, * = stop)
_CODON_TABLE = {
    'TTT': 'F', 'TTC': 'F', 'TTA': 'L', 'TTG': 'L',
    'TCT': 'S', 'TCC': 'S', 'TCA': 'S', 'TCG': 'S',
    'TAT': 'Y', 'TAC': 'Y', 'TAA': '*', 'TAG': '*',
    'TGT': 'C', 'TGC': 'C', 'TGA': '*', 'TGG': 'W',
    'CTT': 'L', 'CTC': 'L', 'CTA': 'L', 'CTG': 'L',
    'CCT': 'P', 'CCC': 'P', 'CCA': 'P', 'CCG': 'P',
    'CAT': 'H', 'CAC': 'H', 'CAA': 'Q', 'CAG': 'Q',
    'CGT': 'R', 'CGC': 'R', 'CGA': 'R', 'CGG': 'R',
    'ATT': 'I', 'ATC': 'I', 'ATA': 'I', 'ATG': 'M',
    'ACT': 'T', 'ACC': 'T', 'ACA': 'T', 'ACG': 'T',
    'AAT': 'N', 'AAC': 'N', 'AAA': 'K', 'AAG': 'K',
    'AGT': 'S', 'AGC': 'S', 'AGA': 'R', 'AGG': 'R',
    'GTT': 'V', 'GTC': 'V', 'GTA': 'V', 'GTG': 'V',
    'GCT': 'A', 'GCC': 'A', 'GCA': 'A', 'GCG': 'A',
    'GAT': 'D', 'GAC': 'D', 'GAA': 'E', 'GAG': 'E',
    'GGT': 'G', 'GGC': 'G', 'GGA': 'G', 'GGG': 'G',
}

# Codon optimization: most common codon per AA for each organism (simple optimize)
_HUMAN_OPTIMAL = {
    'A': 'GCC', 'R': 'CGC', 'N': 'AAC', 'D': 'GAC', 'C': 'TGC', 'E': 'GAG',
    'Q': 'CAG', 'G': 'GGC', 'H': 'CAC', 'I': 'ATC', 'L': 'CTG', 'K': 'AAG',
    'M': 'ATG', 'F': 'TTC', 'P': 'CCC', 'S': 'AGC', 'T': 'ACC', 'W': 'TGG',
    'Y': 'TAC', 'V': 'GTG', '*': 'TGA',
}
_ECOLI_OPTIMAL = {
    'A': 'GCT', 'R': 'CGT', 'N': 'AAC', 'D': 'GAT', 'C': 'TGC', 'E': 'GAA',
    'Q': 'CAG', 'G': 'GGT', 'H': 'CAT', 'I': 'ATT', 'L': 'CTG', 'K': 'AAA',
    'M': 'ATG', 'F': 'TTT', 'P': 'CCG', 'S': 'AGC', 'T': 'ACC', 'W': 'TGG',
    'Y': 'TAT', 'V': 'GTT', '*': 'TAA',
}
_YEAST_OPTIMAL = {
    'A': 'GCT', 'R': 'AGA', 'N': 'AAC', 'D': 'GAT', 'C': 'TGT', 'E': 'GAA',
    'Q': 'CAA', 'G': 'GGT', 'H': 'CAT', 'I': 'ATT', 'L': 'TTG', 'K': 'AAG',
    'M': 'ATG', 'F': 'TTC', 'P': 'CCA', 'S': 'TCT', 'T': 'ACT', 'W': 'TGG',
    'Y': 'TAC', 'V': 'GTT', '*': 'TAA',
}
_CODON_OPTIM_TABLES = {
    'human': _HUMAN_OPTIMAL,
    'homo_sapiens': _HUMAN_OPTIMAL,
    'hs': _HUMAN_OPTIMAL,
    'e_coli': _ECOLI_OPTIMAL,
    'ecoli': _ECOLI_OPTIMAL,
    'e.coli': _ECOLI_OPTIMAL,
    'yeast': _YEAST_OPTIMAL,
    's_cerevisiae': _YEAST_OPTIMAL,
}

# Complement maps
_COMPLEMENT_MAP = str.maketrans("ACGTacgt", "TGCAtgca")


# ---------------------------------------------------------------------------
# Config & key helpers (preserved + enhanced error handling)
# ---------------------------------------------------------------------------

def _get_config(api_key=None):
    """Get Evo2 API configuration with error handling."""
    try:
        key = api_key or os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVCF_RUN_KEY")
        return {
            "api_key": key,
            "generate_url": os.environ.get("EVO2_GENERATE_URL", _EVO2_GENERATE_URL),
            "forward_url": os.environ.get("EVO2_FORWARD_URL", _EVO2_FORWARD_URL),
            "chat_url": os.environ.get("EVO2_CHAT_URL", _EVO2_CHAT_URL),
            "model": os.environ.get("EVO2_MODEL", "evo2-40b"),
        }
    except Exception as e:
        # Fallback config if env read fails
        return {
            "api_key": api_key,
            "generate_url": _EVO2_GENERATE_URL,
            "forward_url": _EVO2_FORWARD_URL,
            "chat_url": _EVO2_CHAT_URL,
            "model": "evo2-40b",
            "error": str(e),
        }


def _check_key(config):
    """Check if API key is configured."""
    try:
        if not config or not config.get("api_key"):
            return (
                "ERROR: No NVIDIA API key found.\n"
                "Set NVIDIA_API_KEY environment variable or pass api_key=...\n"
                "Get a key at: https://build.nvidia.com/arc/evo2-40b\n"
                "Then restart Ultron or run: set-model to reload config."
            )
        return None
    except Exception as e:
        return "ERROR: Key check failed: %s" % str(e)


# ---------------------------------------------------------------------------
# v2 helper functions
# ---------------------------------------------------------------------------

def _clean_dna(seq: str) -> str:
    """Validate and clean DNA sequence: uppercases, removes whitespace/invalid, returns cleaned string."""
    try:
        if seq is None:
            return ""
        # Remove whitespace, numbers, and common fasta header artifacts
        s = str(seq).upper().strip()
        # Remove FASTA header line if present
        if s.startswith(">"):
            # drop first line
            s = "\n".join(s.split("\n")[1:])
        # Remove whitespace, newlines, numbers
        s = re.sub(r"[^ACGTU]", "", s)  # keep only ACGT and U (for RNA inputs, will convert)
        # If contains U, we treat as RNA and convert to T for DNA cleaning? But keep T conversion optional
        # For DNA cleaning, replace U with T
        s = s.replace("U", "T")
        return s
    except Exception:
        # Fallback simple clean
        try:
            return "".join(c for c in str(seq).upper() if c in "ACGT")
        except Exception:
            return ""


def _complement(seq: str) -> str:
    """Return Watson-Crick complement (non-reversed)."""
    try:
        cleaned = _clean_dna(seq)
        if not cleaned:
            # Try to preserve original if cleaning removed all (e.g., invalid)
            cleaned = str(seq).upper().strip()
        return cleaned.translate(_COMPLEMENT_MAP) if hasattr(str, "translate") else "".join({"A":"T","T":"A","G":"C","C":"G"}.get(b,b) for b in cleaned)
    except Exception as e:
        return "ERROR: _complement failed: %s" % str(e)


def _reverse_complement(seq: str) -> str:
    """Return Watson-Crick reverse complement."""
    try:
        comp = _complement(seq)
        if comp.startswith("ERROR"):
            return comp
        return comp[::-1]
    except Exception as e:
        return "ERROR: _reverse_complement failed: %s" % str(e)


def _transcribe(seq: str) -> str:
    """DNA -> RNA transcription (T -> U)."""
    try:
        cleaned = _clean_dna(seq)
        if not cleaned:
            return "ERROR: No valid DNA to transcribe."
        return cleaned.replace("T", "U")
    except Exception as e:
        return "ERROR: _transcribe failed: %s" % str(e)


def _reverse_transcribe(seq: str) -> str:
    """RNA -> DNA reverse transcription (U -> T)."""
    try:
        s = str(seq).upper().strip()
        s = re.sub(r"[^ACGU\s]", "", s)
        s = re.sub(r"\s+", "", s)
        return s.replace("U", "T")
    except Exception as e:
        return "ERROR: _reverse_transcribe failed: %s" % str(e)


def _gc_content(seq: str) -> float:
    """Return GC content as percentage (0-100). Reused logic from _analyze_sequence."""
    try:
        cleaned = _clean_dna(seq)
        if not cleaned:
            return 0.0
        gc = cleaned.count("G") + cleaned.count("C")
        return (gc / len(cleaned) * 100.0) if len(cleaned) > 0 else 0.0
    except Exception:
        return 0.0


def _kmer_counts(seq: str, k: int = 3) -> Dict[str, int]:
    """Return k-mer frequency dictionary. Reused from analyze."""
    try:
        cleaned = _clean_dna(seq)
        if not cleaned or k <= 0 or k > len(cleaned):
            return {}
        counts: Dict[str, int] = {}
        for i in range(len(cleaned) - k + 1):
            kmer = cleaned[i:i+k]
            counts[kmer] = counts.get(kmer, 0) + 1
        return counts
    except Exception:
        return {}


def _parse_list_input(raw) -> List[str]:
    """Deduplicated helper: normalize JSON string / comma-separated string / list -> List[str]."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out: List[str] = []
        for item in raw:
            s = str(item).strip()
            if not s:
                continue
            if "," in s:
                out.extend([x.strip() for x in s.split(",") if x.strip()])
            else:
                out.append(s)
        return out
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        if "," in raw:
            return [s.strip() for s in raw.split(",") if s.strip()]
        stripped = raw.strip()
        return [stripped] if stripped else []
    return [str(raw).strip()] if str(raw).strip() else []


def _cache_batch_result(key: str, value: Dict[str, Any]) -> None:
    """Store batch result in both in-memory dict and core.cache if available."""
    try:
        with _BATCH_LOCK:
            _BATCH_RESULTS[key] = value
    except Exception:
        try:
            _BATCH_RESULTS[key] = value
        except Exception:
            pass
    try:
        from core.cache import get_cache_manager
        get_cache_manager().set(f"dna_lab:{key}", value)
    except Exception:
        pass


def _validate_sequence(seq) -> Dict[str, Any]:
    """Return validation report for a DNA sequence."""
    try:
        original = str(seq) if seq is not None else ""
        cleaned = _clean_dna(original)
        length = len(cleaned)
        original_len = len(original.strip())
        # Single regex for invalid chars (allow ACGTU, whitespace, '>', digits as formatting)
        invalid_chars_found = re.findall(r"[^ACGTUacgtu\s>0-9]", original)
        invalid_unique = sorted(set(invalid_chars_found)) if invalid_chars_found else []

        gc = _gc_content(cleaned) if cleaned else 0.0
        counts = {base: cleaned.count(base) for base in "ACGT"} if cleaned else {b:0 for b in "ACGT"}
        is_valid = len(cleaned) > 0 and len(invalid_unique) == 0
        warnings = []
        if length == 0:
            warnings.append("No valid DNA characters found")
        if length > 0 and length < 10:
            warnings.append("Sequence very short (<10 bp) - analysis may be unreliable")
        if length > 100000:
            warnings.append("Sequence very long (>100k bp) - consider chunking for Evo2")
        if invalid_unique:
            warnings.append("Invalid characters found: %s" % ", ".join(invalid_unique[:10]))

        report = {
            "original_length": original_len,
            "cleaned_length": length,
            "cleaned_sequence_preview": cleaned[:60] + ("..." if len(cleaned) > 60 else ""),
            "is_valid": is_valid,
            "base_counts": counts,
            "gc_content": round(gc, 2),
            "invalid_characters": invalid_unique[:20],
            "warnings": warnings,
        }
        return report
    except Exception as e:
        return {"is_valid": False, "error": str(e), "cleaned_length": 0, "warnings": ["validation exception"]}


# ---------------------------------------------------------------------------
# v3 Advanced Integrated Features (offline, no API key)
# Tight integration with Ultron ecosystem: protein_lab, genome_pipeline,
# obsidian_memory, semantic_memory, core.memory_sqlite
# ---------------------------------------------------------------------------

def _store_result_memory_gracefully(text_to_store: str, key_prefix: str = "dna_lab", vault_note: str = "") -> None:
    """Gracefully store result in Ultron memory layers (sqlite, obsidian, semantic).
    All integrations are try/except so offline failure never breaks caller.
    """
    # core.memory_sqlite (SQLite FTS)
    try:
        from core.memory_sqlite import save_note as _sqlite_save  # type: ignore
        import time as _t
        key = "%s_%d" % (key_prefix, int(_t.time()))
        # truncate to 4000 chars to avoid huge DB bloat
        _sqlite_save(key, text_to_store[:4000])
    except Exception:
        pass
    # obsidian_memory vault
    try:
        from skills.obsidian_memory import run as _obs_run  # type: ignore
        # use vault note name under DNA_Lab/
        note_name = vault_note or ("DNA_Lab/%s_%s" % (key_prefix, __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")))
        _obs_run(action="write", name=note_name, content=text_to_store[:8000])
    except Exception:
        try:
            from core import skills as _skills_mod2  # type: ignore
            _skills_mod2.execute_skill("obsidian_memory", {"action": "write", "name": "DNA_Lab/%s_auto" % key_prefix, "content": text_to_store[:8000]})
        except Exception:
            pass
    # semantic_memory vector store
    try:
        from core.semantic_memory import SemanticMemory as _SemMem  # type: ignore
        _sm = _SemMem()
        _sm.add_text(text_to_store[:2000], metadata={"source": "dna_lab", "action": key_prefix})
    except Exception:
        pass


def _melting_temp(sequence: str, method: str = "wallace", **kwargs) -> Dict[str, Any]:
    """Calculate melting temperature (offline).

    Methods:
      wallace: Tm = 2*(A+T) + 4*(G+C)  (simple, good for 14-20 bp oligos)
      nn / nearest_neighbor / santa_lucia: simplified nearest-neighbor
         Tm = 64.9 + 41*(yG+zC-16.4)/(wA+xT+yG+zC)  (Wallace-like gc-adjusted, simplified)

    Integrates with _validate_sequence and _gc_content.
    Returns dict with tm, method, gc%, length, warnings.
    """
    try:
        method = str(method).lower().strip().replace("-", "_").replace(" ", "_")
        if method in ("tm", "melting_temp", "melting_temperature"):
            method = "wallace"
        cleaned = _clean_dna(sequence)
        if not cleaned:
            return {"error": "No valid DNA to calculate Tm. Provide ACGT sequence.", "method": method}
        # Integrate validation
        val = _validate_sequence(sequence)
        gc = _gc_content(cleaned)
        length = len(cleaned)
        a = cleaned.count("A")
        t = cleaned.count("T")
        g = cleaned.count("G")
        c = cleaned.count("C")
        tm_val = 0.0
        formula = ""
        if method in ("wallace", "wallace_rule"):
            tm_val = 2 * (a + t) + 4 * (g + c)
            formula = "Tm=2*(A+T)+4*(G+C)"
        elif method in ("nn", "nearest_neighbor", "nearest_neighbour", "santa_lucia", "santalucia", "gc_adjusted", "basic"):
            # Simplified: 64.9 + 41*(G+C-16.4)/N  (classic formula for >14bp)
            # For salt-adjusted: Tm = 81.5 + 16.6*log10([Na+]) + 0.41*GC% - 600/N  (assume 50mM Na+ => log10 0.05)
            # We'll use: 64.9+41*(gc_count-16.4)/N , clamped
            if length > 0:
                tm_val = 64.9 + 41 * (g + c - 16.4) / length
            else:
                tm_val = 0.0
            formula = "Tm=64.9+41*(G+C-16.4)/N (salt-adjusted simplified, 50mM Na+ assumed)"
            # If short (<14) fall back to wallace for plausibility and average
            if length < 14:
                wallace = 2*(a+t)+4*(g+c)
                tm_val = (tm_val + wallace)/2
                formula += " | averaged with Wallace for short oligo"
        else:
            # unknown method fallback to wallace
            tm_val = 2 * (a + t) + 4 * (g + c)
            formula = "Tm=2*(A+T)+4*(G+C) (fallback Wallace)"
            method = "wallace"
        tm_val = round(float(tm_val), 2)
        warnings = list(val.get("warnings", [])) if isinstance(val, dict) else []
        if length < 14:
            warnings.append("Sequence short (<14 bp): Wallace rule most accurate")
        elif length > 30:
            warnings.append("Sequence long (>30 bp): nearest-neighbor more accurate, consider method='nn'")
        if gc < 30:
            warnings.append("Low GC (%.1f%%): lower Tm, check primer specificity" % gc)
        elif gc > 70:
            warnings.append("High GC (%.1f%%): higher Tm, risk secondary structure" % gc)
        return {
            "sequence": cleaned,
            "cleaned_length": length,
            "method": method,
            "tm_c": tm_val,
            "gc_percent": round(gc, 2),
            "base_counts": {"A": a, "T": t, "G": g, "C": c},
            "formula": formula,
            "warnings": warnings,
            "is_valid": val.get("is_valid", True) if isinstance(val, dict) else True,
        }
    except Exception as e:
        return {"error": "melting_temp failed: %s" % str(e), "method": method if 'method' in locals() else "wallace"}


def _design_primers(sequence: str, target_region=None, primer_length: int = 20, tm_opt: float = 60, **kwargs) -> Dict[str, Any]:
    """Design forward/reverse primers (offline).

    Uses Wallace rule Tm=2*(A+T)+4*(G+C), GC clamp check, hairpin/dimer warnings.
    Integrates with _gc_content and _validate_sequence.

    Args:
        sequence: template DNA (ACGT)
        target_region: optional (start, end) tuple/list or "start:end" string to focus design; if None uses ends of template
        primer_length: desired primer length (default 20)
        tm_opt: optimal Tm target (default 60C)

    Returns dict with forward/reverse primer dicts: seq, tm, gc, clamp, warnings.
    """
    try:
        cleaned = _clean_dna(sequence)
        if not cleaned:
            return {"error": "No valid DNA template. Provide ACGT sequence.", "template_length": 0}
        val = _validate_sequence(sequence)
        # normalize primer_length, tm_opt
        try:
            primer_length = int(kwargs.get("primer_length", primer_length))
        except Exception:
            primer_length = 20
        try:
            tm_opt = float(kwargs.get("tm_opt", kwargs.get("tm", tm_opt)))
        except Exception:
            tm_opt = 60.0
        primer_length = max(14, min(30, primer_length))  # clamp sensible PCR range
        # target_region handling
        start = 0
        end = len(cleaned)
        tr = target_region if target_region is not None else kwargs.get("target") or kwargs.get("region")
        if tr is not None:
            try:
                if isinstance(tr, str) and ":" in tr:
                    a,b = tr.split(":")
                    start, end = int(a), int(b)
                elif isinstance(tr, (list, tuple)) and len(tr) >= 2:
                    start, end = int(tr[0]), int(tr[1])
                elif isinstance(tr, dict):
                    start = int(tr.get("start", 0))
                    end = int(tr.get("end", len(cleaned)))
                start = max(0, min(start, len(cleaned)-1))
                end = max(start+primer_length, min(end, len(cleaned)))
            except Exception:
                pass
        # Extract candidate primers: forward = 5' end of target, reverse = reverse complement of 3' end
        # Slide to find best Tm near tm_opt
        def _score_primer(pseq: str) -> float:
            mt = _melting_temp(pseq, method="wallace")
            tm = mt.get("tm_c", 0)
            # score = deviation from tm_opt + GC penalty if out of 40-60
            gc = mt.get("gc_percent", 50)
            score = abs(tm - tm_opt)
            if gc < 40 or gc > 60:
                score += 5
            return score

        # Forward primer candidates: slide window along start region
        best_fwd = None
        best_fwd_score = 1e9
        # For simple case: use first primer_length bases as primer; also check shifted windows
        max_shift_fwd = min(20, max(0, end - start - primer_length))
        for shift in range(max_shift_fwd+1):
            cand = cleaned[start+shift:start+shift+primer_length]
            if len(cand) < primer_length:
                continue
            sc = _score_primer(cand)
            if sc < best_fwd_score:
                best_fwd_score = sc
                best_fwd = cand
        if best_fwd is None:
            best_fwd = cleaned[start:start+primer_length]
        # Reverse primer: take from end region, reverse complement
        best_rev = None
        best_rev_score = 1e9
        max_shift_rev = min(20, max(0, end - start - primer_length))
        for shift in range(max_shift_rev+1):
            # shift from end backwards
            raw = cleaned[end - primer_length - shift:end - shift] if end - shift >= primer_length else ""
            if len(raw) < primer_length:
                continue
            rc = _reverse_complement(raw)
            if rc.startswith("ERROR"):
                continue
            sc = _score_primer(rc)
            if sc < best_rev_score:
                best_rev_score = sc
                best_rev = (rc, raw)
        if best_rev is None:
            raw = cleaned[end-primer_length:end] if len(cleaned) >= primer_length else cleaned
            rc = _reverse_complement(raw)
            best_rev = (rc if not rc.startswith("ERROR") else raw, raw)

        fwd_seq, rev_seq = best_fwd, best_rev[0] if isinstance(best_rev, tuple) else best_rev
        rev_raw = best_rev[1] if isinstance(best_rev, tuple) else cleaned[end-primer_length:end]

        # Per-primer analysis
        def _analyze_primer(pseq: str) -> Dict[str, Any]:
            mt = _melting_temp(pseq, method="wallace")
            gc = mt.get("gc_percent", _gc_content(pseq))
            tm = mt.get("tm_c", 0)
            # GC clamp: 3' end should be G or C for stable binding
            clamp = pseq[-1] in "GC" if pseq else False
            clamp_strong = pseq[-2:].count("G") + pseq[-2:].count("C") if len(pseq) >=2 else 0
            warnings = []
            if not clamp:
                warnings.append("Weak GC clamp at 3' end (%s): consider G/C ending for stability" % (pseq[-1] if pseq else "N/A"))
            if gc < 40:
                warnings.append("Low GC (%.1f%%): weak binding, risk low Tm" % gc)
            elif gc > 60:
                warnings.append("High GC (%.1f%%): risk secondary structure / high Tm" % gc)
            if abs(tm - tm_opt) > 5:
                warnings.append("Tm %.1fC deviates >5C from optimum %.1fC" % (tm, tm_opt))
            # Hairpin heuristic
            hairpin = False
            for i in range(len(pseq)-3):
                kmer = pseq[i:i+4]
                rkmer = _reverse_complement(kmer)
                if rkmer in pseq[i+4:]:
                    hairpin = True
                    break
            if hairpin:
                warnings.append("Potential hairpin/self-complementarity (4-mer repeat)")
            return {
                "sequence": pseq,
                "length": len(pseq),
                "tm_c": tm,
                "gc_percent": round(gc,2),
                "gc_clamp": clamp,
                "gc_clamp_strength_2bp": clamp_strong,
                "method": "wallace: 2*(A+T)+4*(G+C)",
                "warnings": warnings,
            }

        fwd_info = _analyze_primer(fwd_seq)
        rev_info = _analyze_primer(rev_seq)

        # Dimer / cross-complementarity warnings
        cross_warnings = []
        # check 3' end complementarity (last 4 bases)
        if len(fwd_seq) >=4 and len(rev_seq) >=4:
            f3 = fwd_seq[-4:]
            r3 = rev_seq[-4:]
            # dimer if f3 is complement to r3 revcomp
            if _reverse_complement(f3) == r3 or _reverse_complement(r3) == f3:
                cross_warnings.append("Strong 3'-3' complementarity (4-bp): risk primer-dimer")
            else:
                # check 3 base complementarity
                for k in [4,3]:
                    if _reverse_complement(fwd_seq[-k:]) in rev_seq or _reverse_complement(rev_seq[-k:]) in fwd_seq:
                        cross_warnings.append("Potential primer-dimer: %d bp 3' complementarity" % k)
                        break
        # Tm matching
        tm_diff = abs(fwd_info["tm_c"] - rev_info["tm_c"])
        if tm_diff > 5:
            cross_warnings.append("Tm mismatch %.1fC >5C: optimize for similar annealing" % tm_diff)

        # Overall product info
        product_len = (end - start) if (end-start) >0 else len(cleaned)

        result = {
            "template_length": len(cleaned),
            "template_preview": cleaned[:60] + ("..." if len(cleaned)>60 else ""),
            "target_region": [start, end],
            "primer_length_requested": primer_length,
            "tm_optimal": tm_opt,
            "forward": fwd_info,
            "reverse": rev_info,
            "reverse_template_raw": rev_raw,
            "product_length_estimate": product_len,
            "cross_warnings": cross_warnings,
            "validation": {"is_valid": val.get("is_valid"), "warnings": val.get("warnings", [])[:3]},
        }
        return result
    except Exception as e:
        return {"error": "primer design failed: %s" % str(e), "template_length": len(_clean_dna(sequence)) if sequence else 0}


def _crispr_guides(sequence: str, pam: str = "NGG", guide_length: int = 20, **kwargs) -> Dict[str, Any]:
    """Scan for CRISPR guides (SpCas9-style) on both strands.

    Scans for PAM on both strands, extracts guides, scores by GC%, off-target hint via k-mer uniqueness.
    Integrates with _reverse_complement and _gc_content.

    Args:
        sequence: template DNA
        pam: PAM pattern (default NGG; N = any, support NGG, NAG, TTTV, etc.; simple regex interpreted)
        guide_length: guide length (default 20)

    Returns dict with guides list, counts, warnings.
    """
    try:
        cleaned = _clean_dna(sequence)
        if not cleaned:
            return {"error": "No valid DNA for CRISPR scan. Provide ACGT.", "sequence_length": 0}
        try:
            guide_length = int(kwargs.get("guide_length", kwargs.get("guide_len", guide_length)))
        except Exception:
            guide_length = 20
        guide_length = max(15, min(25, guide_length))
        pam = str(kwargs.get("pam", pam)).upper().strip()
        if not pam:
            pam = "NGG"
        # Convert PAM to regex: N-> [ACGT], R-> [AG], Y->[CT], etc. (use IUPAC)
        iupac = {"N":"[ACGT]", "R":"[AG]", "Y":"[CT]", "S":"[GC]", "W":"[AT]", "K":"[GT]", "M":"[AC]", "B":"[CGT]", "D":"[AGT]", "H":"[ACT]", "V":"[ACG]"}
        pam_regex = ""
        for ch in pam:
            if ch in "ACGT":
                pam_regex += ch
            elif ch in iupac:
                pam_regex += iupac[ch]
            else:
                pam_regex += ch  # fallback literal
        rev_comp_seq = _reverse_complement(cleaned)
        if rev_comp_seq.startswith("ERROR"):
            rev_comp_seq = ""
        # k-mer uniqueness map for off-target hint
        kmer_counts = _kmer_counts(cleaned, k=guide_length) if len(cleaned) >= guide_length else {}
        guides = []
        seq_len = len(cleaned)
        import re as _re
        # Forward strand: guide is upstream of PAM (SpCas9: 5'-guide-PAM-3')
        for i in range(seq_len - len(pam) - guide_length + 1):
            pam_seq = cleaned[i+guide_length:i+guide_length+len(pam)]
            if _re.fullmatch(pam_regex, pam_seq):
                guide = cleaned[i:i+guide_length]
                if len(guide) != guide_length:
                    continue
                gc = _gc_content(guide)
                occ = kmer_counts.get(guide, 1)
                uniq = "unique" if occ == 1 else "repeated x%d" % occ
                score_notes = []
                if gc < 40:
                    score_notes.append("Low GC (%.1f%%): weaker binding" % gc)
                elif gc > 65:
                    score_notes.append("High GC (%.1f%%): risk secondary structure" % gc)
                else:
                    score_notes.append("GC optimal (%.1f%%)" % gc)
                if "TTTT" in guide:
                    score_notes.append("Poly-T tract: risk Pol III termination")
                if guide[0] == "G":
                    score_notes.append("5' G: favorable for U6 promoter")
                guides.append({
                    "strand": "+",
                    "pam": pam_seq,
                    "pam_pattern": pam,
                    "guide": guide,
                    "cut_position": i+guide_length,
                    "start": i,
                    "end": i+guide_length,
                    "pam_start": i+guide_length,
                    "gc_percent": round(gc,2),
                    "off_target_hint": uniq,
                    "occurrences": occ,
                    "notes": score_notes,
                })
        # Reverse strand: scan reverse complement same way, then map coordinates to original
        if rev_comp_seq and pam_regex:
            rc_len = len(rev_comp_seq)
            for j in range(rc_len - len(pam) - guide_length + 1):
                pam_seq_rc = rev_comp_seq[j+guide_length:j+guide_length+len(pam)]
                if _re.fullmatch(pam_regex, pam_seq_rc):
                    guide_rc = rev_comp_seq[j:j+guide_length]
                    gc = _gc_content(guide_rc)
                    occ = kmer_counts.get(_reverse_complement(guide_rc), 1) if guide_rc else 1
                    score_notes = []
                    if gc < 40:
                        score_notes.append("Low GC (%.1f%%)" % gc)
                    elif gc > 65:
                        score_notes.append("High GC (%.1f%%)" % gc)
                    else:
                        score_notes.append("GC optimal (%.1f%%)" % gc)
                    if "TTTT" in guide_rc:
                        score_notes.append("Poly-T tract")
                    orig_end = seq_len - j
                    orig_start = seq_len - (j+guide_length)
                    guides.append({
                        "strand": "-",
                        "pam": pam_seq_rc,
                        "pam_pattern": pam,
                        "guide": guide_rc,
                        "guide_rc_on_original": _reverse_complement(guide_rc),
                        "cut_position": orig_start,
                        "start": orig_start,
                        "end": orig_end,
                        "pam_start": seq_len - (j+guide_length+len(pam)),
                        "gc_percent": round(gc,2),
                        "off_target_hint": "unique" if occ==1 else "repeated x%d"%occ,
                        "occurrences": occ,
                        "notes": score_notes,
                    })
        def _guide_score(g):
            gc = g["gc_percent"]
            gc_dist = abs(gc-50)
            rep_penalty = 10 if g["occurrences"]>1 else 0
            return gc_dist + rep_penalty
        guides_sorted = sorted(guides, key=_guide_score)
        val = _validate_sequence(sequence)
        return {
            "sequence_length": seq_len,
            "pam": pam,
            "pam_regex": pam_regex,
            "guide_length": guide_length,
            "total_guides": len(guides),
            "guides": guides_sorted[:20],
            "all_guides_truncated": len(guides) > 20,
            "is_valid": val.get("is_valid"),
            "warnings": val.get("warnings", [])[:3] if isinstance(val, dict) else [],
        }
    except Exception as e:
        return {"error": "crispr guide scan failed: %s" % str(e), "pam": pam if 'pam' in locals() else "NGG"}


def _dna_to_protein_integrated(sequence: str, **kwargs) -> str:
    """Integrated DNA -> Protein translation using protein_lab cross-skill call.

    Tries: from skills.protein_lab import run as protein_run; protein_run(action="dna_to_protein", dna_sequence=...)
    Falls back to local 6-frame translation using _CODON_TABLE and _reverse_complement.
    Demonstrates cross-skill call.
    """
    cleaned = _clean_dna(sequence) if sequence else ""
    note_lines = []
    # Try protein_lab integration first
    try:
        from skills.protein_lab import run as protein_run  # type: ignore
        try:
            res = protein_run(action="dna_to_protein", dna_sequence=cleaned if cleaned else sequence, **kwargs)
            if res and isinstance(res, str) and "ERROR" not in res and len(res) > 10:
                note_lines.append("[Integrated via protein_lab]")
                note_lines.append(res)
                return "\n".join(note_lines)
            else:
                note_lines.append("[protein_lab returned empty/error, falling back to local]")
                note_lines.append(str(res)[:500] if res else "no response")
        except TypeError:
            res = protein_run(action="dna_to_protein", sequence=cleaned, **kwargs)
            if res and len(str(res))>10:
                return "[Integrated via protein_lab (alt param)]\n" + str(res)
            raise
    except ImportError as e:
        note_lines.append("[protein_lab not available: %s; using local translation]" % str(e))
    except Exception as e:
        note_lines.append("[protein_lab call failed: %s; using local translation]" % str(e))

    # Local fallback: translate forward frame 1 and reverse complement, report best
    try:
        if not cleaned:
            return "ERROR: No valid DNA to translate. Provide ACGT sequence.\n" + "\n".join(note_lines)
        orf_res = _orf_find(cleaned)
        best = orf_res.get("best_orf") if isinstance(orf_res, dict) else None
        if best and best.get("protein"):
            prot = best["protein"].replace("*","").strip()
            header = [
                "DNA TO PROTEIN (Integrated - Local Fallback)",
                "="*50,
                "Template length: %d bp" % len(cleaned),
                "Template preview: %s" % cleaned[:60],
                "-"*50,
                "Best ORF frame: %s | strand %s | coords %d-%d" % (best["frame"], best["strand"], best["start"], best["end"]),
                "Protein (%d aa): %s" % (len(prot), prot),
                "-"*50,
            ]
            orfs = orf_res.get("orfs", [])[:3]
            if orfs:
                header.append("Top ORFs:")
                for o in orfs:
                    header.append("  %s: %s (%d aa)" % (o["frame"], o["protein"][:40], len(o["protein"].replace("*",""))))
            if note_lines:
                header = note_lines + [""] + header
            return "\n".join(header)
        codons = [cleaned[i:i+3] for i in range(0, len(cleaned)-2, 3)]
        prot_simple = "".join(_CODON_TABLE.get(c, "X") for c in codons)
        prot_simple_nostop = prot_simple.split("*")[0]
        lines = [
            "DNA TO PROTEIN (Integrated - Local Simple Translate)",
            "="*50,
            "Template length: %d bp" % len(cleaned),
            "Protein (frame +1, %d aa): %s" % (len(prot_simple_nostop), prot_simple_nostop[:80]),
            "Full translate (with stops *): %s" % prot_simple[:80],
        ]
        if note_lines:
            lines = note_lines + [""] + lines
        return "\n".join(lines)
    except Exception as e:
        return "ERROR: dna_to_protein_integrated failed: %s\n" % str(e) + "\n".join(note_lines)


def _run_genome_pipeline(fastq_dir=None, reference=None, **kwargs) -> str:
    """Integration with genome_pipeline: check Snakefile exists and return instructions+config.

    Does NOT execute the pipeline (requires snakemake + data), but shows tight integration:
      - checks genome_pipeline/Snakefile exists
      - reads genome_pipeline/config.yaml if present
      - returns snakemake command template + input validation
    """
    try:
        import os as _os
        candidates = [
            _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "genome_pipeline", "Snakefile"),
            _os.path.join(_os.getcwd(), "genome_pipeline", "Snakefile"),
            _os.path.join("genome_pipeline", "Snakefile"),
            _os.path.join(_os.path.dirname(__file__), "..", "genome_pipeline", "Snakefile"),
        ]
        snake_path = None
        for c in candidates:
            try:
                if _os.path.exists(c):
                    snake_path = _os.path.abspath(c)
                    break
            except Exception:
                continue
        lines = [
            "GENOME PIPELINE INTEGRATION (Snakemake)",
            "="*60,
        ]
        if not snake_path:
            lines.append("STATUS: Snakefile NOT FOUND")
            lines.append("Searched candidates:")
            for c in candidates:
                lines.append("  - %s (%s)" % (c, "found" if _os.path.exists(c) else "missing"))
            lines.append("")
            lines.append("To use the pipeline, ensure genome_pipeline/Snakefile exists at project root.")
            lines.append("Then run: snakemake -s genome_pipeline/Snakefile --configfile genome_pipeline/config.yaml -j 8")
            return "\n".join(lines)
        lines.append("STATUS: Snakefile FOUND")
        lines.append("Path: %s" % snake_path)
        cfg_path = _os.path.join(_os.path.dirname(snake_path), "config.yaml")
        cfg_preview = ""
        if _os.path.exists(cfg_path):
            try:
                cfg_text = open(cfg_path, encoding="utf-8").read()
                cfg_preview = cfg_text[:800]
                lines.append("")
                lines.append("Config: %s" % cfg_path)
                lines.append("-"*60)
                lines.append(cfg_preview + ("..." if len(cfg_text)>800 else ""))
                lines.append("-"*60)
            except Exception as e:
                lines.append("Config read error: %s" % str(e))
        else:
            lines.append("Config: %s NOT FOUND (using defaults)" % cfg_path)
            lines.append("Expected defaults: reference=data/reference/hg38.fa  fastq_dir=data/fastq  bam_out=data/bam_intermediate")
        fastq = fastq_dir or kwargs.get("fastq") or kwargs.get("fastq_dir") or kwargs.get("fastqDir") or "data/fastq"
        ref = reference or kwargs.get("ref") or kwargs.get("reference") or kwargs.get("genome") or "data/reference/hg38.fa"
        try:
            abs_fastq = _os.path.abspath(fastq) if not _os.path.isabs(fastq) else fastq
            exists_fastq = _os.path.isdir(fastq) or _os.path.isdir(abs_fastq)
            lines.append("")
            lines.append("Input validation (informational):")
            lines.append("  fastq_dir: %s (%s)" % (fastq, "exists" if exists_fastq else "NOT FOUND - create or set fastq_dir=..."))
            if exists_fastq:
                try:
                    files = [f for f in _os.listdir(fastq) if f.endswith(".fastq.gz")][:5]
                    lines.append("    sample FASTQs: %s" % (", ".join(files) if files else "none found (*_R1.fastq.gz expected)"))
                except Exception:
                    pass
            ref_exists = _os.path.exists(ref) or _os.path.exists(_os.path.abspath(ref))
            lines.append("  reference: %s (%s)" % (ref, "exists" if ref_exists else "NOT FOUND - set reference=..."))
        except Exception:
            pass
        lines.append("")
        lines.append("HOW TO RUN (dry-run first):")
        lines.append("  snakemake -s %s --configfile %s -n  # dry-run" % (snake_path, cfg_path if _os.path.exists(cfg_path) else "config.yaml"))
        lines.append("  snakemake -s %s --configfile %s -j 8" % (snake_path, cfg_path if _os.path.exists(cfg_path) else "config.yaml"))
        lines.append("")
        lines.append("Override inputs via CLI:")
        lines.append("  snakemake -s %s --config fastq_dir=%s reference=%s -j 8" % (snake_path, fastq, ref))
        lines.append("")
        lines.append("Pipeline steps: split_fastq -> align_chr -> mask_N -> haplotypecaller_chr -> rg_reassign -> combine_gvcfs -> joint_genotype -> filter_final_variants")
        lines.append("")
        lines.append("Integration note: dna_lab can provide GC analysis / primer design for pipeline outputs;")
        lines.append("  use run(action='analyze', sequence=...) or run(action='primer_design', sequence=...) on VCF flanking regions.")
        try:
            _store_result_memory_gracefully("\n".join(lines), key_prefix="genome_pipeline_help")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as e:
        return "ERROR: genome_pipeline integration failed: %s" % str(e)


def _codon_optimize(seq: str, organism: str = "human") -> str:
    """Codon optimize a DNA sequence for a given organism using most-common-codon table.
    Preserves reading frame starting at 0. Input is cleaned to DNA. Translates codons to AA then back to optimal codon.
    If sequence length not divisible by 3, trailing bases are preserved as-is.
    """
    try:
        cleaned = _clean_dna(seq)
        if not cleaned:
            return "ERROR: No valid DNA to optimize. Provide ACGT sequence."
        org_key = str(organism).lower().strip()
        table = _CODON_OPTIM_TABLES.get(org_key)
        if not table:
            # Try fuzzy match
            for k, v in _CODON_OPTIM_TABLES.items():
                if k in org_key or org_key in k:
                    table = v
                    break
        if not table:
            table = _HUMAN_OPTIMAL
            # Note fallback
        # Split into codons
        codons = [cleaned[i:i+3] for i in range(0, len(cleaned), 3)]
        optimized = []
        trailing = ""
        for codon in codons:
            if len(codon) != 3:
                trailing = codon
                break
            aa = _CODON_TABLE.get(codon, None)
            if aa is None:
                # Unknown codon, keep as is
                optimized.append(codon)
            else:
                opt = table.get(aa, codon)
                optimized.append(opt)
        result = "".join(optimized) + trailing
        return result
    except Exception as e:
        return "ERROR: _codon_optimize failed: %s" % str(e)


def _orf_find(seq: str) -> Dict[str, Any]:
    """6-frame ORF scan returning all frames + best + ORF coords, using standard codon table.
    Returns dict with: frames (dict), orfs (list), best_orf (dict or None), orf_count, sequence_length
    Each ORF: {frame, strand, start, end, length, start_codon_pos, stop_codon_pos, dna, protein}
    Frames: +1, +2, +3, -1, -2, -3
    """
    try:
        cleaned = _clean_dna(seq)
        if not cleaned:
            return {"error": "No valid DNA sequence", "sequence_length": 0, "orfs": [], "frames": {}, "best_orf": None}
        rev_comp = _reverse_complement(cleaned)
        # Define frames
        frames: Dict[str, str] = {}
        # Forward
        for f in [1,2,3]:
            offset = f-1
            frames["+%d" % f] = cleaned[offset:]
        # Reverse
        for f in [1,2,3]:
            offset = f-1
            frames["-%d" % f] = rev_comp[offset:]

        start_codon = "ATG"
        stop_codons = {"TAA", "TAG", "TGA"}
        orfs = []
        # Scan each frame
        for frame_label, frame_seq in frames.items():
            # Iterate codons
            codons = [frame_seq[i:i+3] for i in range(0, len(frame_seq)-2, 3)]
            # Find ORFs: start at ATG, extend to next stop
            for idx, codon in enumerate(codons):
                if codon == start_codon:
                    # Look downstream for stop
                    for j in range(idx+1, len(codons)):
                        if codons[j] in stop_codons:
                            # Found ORF from idx to j inclusive
                            dna_orf = "".join(codons[idx:j+1])
                            # Translate
                            protein = "".join(_CODON_TABLE.get(c, "X") for c in codons[idx:j+1])
                            # Coordinates: need to map back to original sequence
                            # For forward strand, start = offset + idx*3, end = offset + (j+1)*3
                            # For reverse strand, coordinates are on reverse complement; we report as rev_comp coords but also orig
                            if frame_label.startswith("+"):
                                start_pos = (int(frame_label[1])-1) + idx*3  # 0-based
                                end_pos = (int(frame_label[1])-1) + (j+1)*3  # exclusive
                                strand = "+"
                            else:
                                # Reverse strand: coordinates on original are mirrored
                                # For simplicity, report positions on rev_comp and note strand -
                                strand = "-"
                                # Map: original length - (offset + j*3 +3) ??? approximate
                                # Use rev_comp positions for now, and add original_mapped
                                rev_start = (int(frame_label[1])-1) + idx*3
                                rev_end = (int(frame_label[1])-1) + (j+1)*3
                                # Map to original: original_len - rev_end  to original_len - rev_start
                                orig_len = len(cleaned)
                                start_pos = orig_len - rev_end
                                end_pos = orig_len - rev_start
                            orf_entry = {
                                "frame": frame_label,
                                "strand": strand,
                                "start": start_pos,
                                "end": end_pos,
                                "length": len(dna_orf),
                                "length_codons": j - idx + 1,
                                "dna": dna_orf,
                                "protein": protein,
                                "start_codon_pos": idx,
                                "stop_codon_pos": j,
                            }
                            orfs.append(orf_entry)
                            break  # stop at first stop for this start; continue scanning for next start

        # Sort by length descending
        orfs_sorted = sorted(orfs, key=lambda x: x["length"], reverse=True)
        best = orfs_sorted[0] if orfs_sorted else None

        return {
            "sequence_length": len(cleaned),
            "frames": frames,
            "orfs": orfs_sorted,
            "orf_count": len(orfs_sorted),
            "best_orf": best,
            "cleaned_sequence": cleaned,
        }
    except Exception as e:
        return {"error": str(e), "orfs": [], "frames": {}, "best_orf": None, "sequence_length": 0}


def _fetch_via_subbots(query=None, url=None, identifier=None, accession=None, **kwargs) -> Dict[str, Any]:
    """Single source of truth for fetch: delegates to web_crawler skill (Firecrawl) with NCBI efetch fallback."""
    target_url = url
    if not target_url and accession:
        target_url = "https://www.ncbi.nlm.nih.gov/nuccore/%s?report=fasta" % str(accession).strip()
    elif not target_url and identifier:
        target_url = "https://www.ncbi.nlm.nih.gov/nuccore/%s?report=fasta" % str(identifier).strip()
    elif not target_url and query and re.match(r"^[A-Z]{1,3}_?\d+(\.\d+)?$", str(query).strip()):
        target_url = "https://www.ncbi.nlm.nih.gov/nuccore/%s?report=fasta" % str(query).strip()

    # Try web_crawler skill (Firecrawl) first via core.skills
    try:
        from core import skills as _skills_mod
        result: Dict[str, Any] = {"via": "web_crawler"}
        if query:
            try:
                search_res = _skills_mod.execute_skill("web_crawler", {"action": "search", "query": str(query), "limit": 5})
                if search_res and "not found" not in search_res.lower() and "failed" not in search_res.lower():
                    result["search"] = str(search_res)[:4000]
                else:
                    result["search"] = str(search_res)[:4000]
                    result["search_error"] = "search returned no useful result"
            except Exception as e:
                result["search_error"] = str(e)
        if target_url:
            try:
                scrape_res = _skills_mod.execute_skill("web_crawler", {"action": "scrape", "url": target_url})
                if scrape_res and "failed" not in scrape_res.lower() and "not ready" not in scrape_res.lower():
                    result["scrape"] = str(scrape_res)[:4000]
                    result["scrape_url"] = target_url
                    # If we got usable scrape, return immediately (success path)
                    if result.get("scrape") and len(result["scrape"]) > 50:
                        return result
                else:
                    result["scrape_error"] = str(scrape_res)[:500]
                    result["scrape_url"] = target_url
            except Exception as e:
                result["scrape_error"] = str(e)
                result["scrape_url"] = target_url
        # If web_crawler gave us search or scrape, return it (caller will extract DNA)
        if "search" in result or "scrape" in result:
            # If scrape looks empty, fall through to NCBI
            if result.get("scrape") and len(result.get("scrape","")) > 100:
                return result
            if result.get("search") and len(result.get("search","")) > 100 and not result.get("scrape_error"):
                return result
            # otherwise keep result but also note fallback will be attempted by caller
            # but we also attempt NCBI here to make this single source of truth
        # Fallback to NCBI efetch inside same function (single source of truth)
        acc_candidate = accession or identifier or query or ""
        # Extract accession pattern from URL if needed
        if not acc_candidate and target_url:
            m = re.search(r"[A-Z]{1,3}_?\d+(\.\d+)?", target_url)
            if m:
                acc_candidate = m.group(0)
        if acc_candidate:
            fasta_text = _ncbi_efetch_fasta(str(acc_candidate))
            if fasta_text:
                result["scrape"] = fasta_text[:4000]
                result["scrape_url"] = "NCBI efetch:%s" % acc_candidate
                result["via"] = "ncbi_efetch"
                result.pop("scrape_error", None)
                return result
        # If still no usable result, return what we have with fallback flag
        if "search" not in result and "scrape" not in result:
            result["fallback"] = True
            result["error"] = result.get("search_error") or result.get("scrape_error") or "web_crawler returned no data and NCBI fallback failed"
            result["query"] = query
            result["url"] = url
        return result
    except Exception as e:
        # If core.skills import fails, try direct NCBI fallback
        try:
            acc_candidate = accession or identifier or query or ""
            if acc_candidate:
                fasta_text = _ncbi_efetch_fasta(str(acc_candidate))
                if fasta_text:
                    return {"scrape": fasta_text[:4000], "scrape_url": "NCBI efetch:%s" % acc_candidate, "via": "ncbi_efetch_fallback"}
        except Exception:
            pass
        return {"error": "web_crawler not available and NCBI fallback failed: %s" % str(e), "fallback": True, "query": query, "url": url}


# ---------------------------------------------------------------------------
# Main dispatcher - expanded
# ---------------------------------------------------------------------------

def run(action="help", **kwargs):
    """
    Main entry point for DNA Lab v2.

    Actions:
      generate    - Generate DNA sequences (autocomplete / de novo)
      score       - Score variants for pathogenicity (BRCA1-style)
      embeddings  - Get genomic embeddings for downstream tasks
      forward     - Run forward pass for logits/embeddings
      analyze     - Analyze a DNA sequence (composition, GC content, etc.)
      reverse_complement - Watson-Crick reverse complement
      complement  - Complement (non-reversed)
      transcribe  - DNA -> RNA (T->U)
      reverse_transcribe - RNA -> DNA (U->T)
      orf_find    - 6-frame ORF scan
      codon_optimize - Codon optimize for organism (human/e_coli/yeast)
      validate    - Validate DNA sequence
      gc_content  - Calculate GC content
      batch_score - Batch variant scoring (parallel)
      batch_generate - Batch generation (parallel)
      batch_embeddings - Batch embeddings (parallel)
      batch_analyze - Batch analysis (parallel)
      fetch_and_analyze - Fetch via sub-bots/NCBI then analyze
      fetch_and_score   - Fetch via sub-bots/NCBI then score
      primer_design - Design PCR primers (Wallace Tm, GC clamp)
      crispr        - CRISPR guide design (PAM scan both strands)
      melting_temp  - Melting temp (wallace/nn)
      dna_to_protein_integrated - Cross-skill DNA->protein via protein_lab
      genome_pipeline - Snakemake pipeline integration
      help        - Show help information

    Common args:
      api_key     - NVIDIA API key (or set NVIDIA_API_KEY env var)
      model       - Model name (default: evo2-40b)
    """
    action = action.lower().strip().replace("-", "_").replace(" ", "_")
    # Normalize some aliases
    alias_map = {
        "rev_comp": "reverse_complement",
        "revcomp": "reverse_complement",
        "rc": "reverse_complement",
        "transcription": "transcribe",
        "reverse_transcription": "reverse_transcribe",
        "orf": "orf_find",
        "orfs": "orf_find",
        "codon": "codon_optimize",
        "codon_opt": "codon_optimize",
        "validation": "validate",
        "gc": "gc_content",
        "fetch_analyze": "fetch_and_analyze",
        "fetch_score": "fetch_and_score",
        "fetchandanalyze": "fetch_and_analyze",
        "fetchandscore": "fetch_and_score",
        # v3 aliases
        "primer": "primer_design",
        "primers": "primer_design",
        "primerdesign": "primer_design",
        "tm": "melting_temp",
        "melting_temperature": "melting_temp",
        "melting": "melting_temp",
        "grna": "crispr",
        "guide_rna": "crispr",
        "guide": "crispr",
        "crispr_guide": "crispr",
        "dna_to_protein": "dna_to_protein_integrated",
        "dna2protein": "dna_to_protein_integrated",
        "genome": "genome_pipeline",
        "pipeline": "genome_pipeline",
        "snakemake": "genome_pipeline",
    }
    action = alias_map.get(action, action)

    handlers = {
        "generate": _generate,
        "score": _score_variants,
        "embeddings": _embeddings,
        "forward": _forward,
        "analyze": _analyze_sequence,
        "help": _show_help,
        # v2 new handlers
        "reverse_complement": _do_reverse_complement,
        "complement": _do_complement,
        "transcribe": _do_transcribe,
        "reverse_transcribe": _do_reverse_transcribe,
        "orf_find": _do_orf_find,
        "codon_optimize": _do_codon_optimize,
        "validate": _do_validate,
        "gc_content": _do_gc_content,
        "batch_score": _batch_score,
        "batch_generate": _batch_generate,
        "batch_embeddings": _batch_embeddings,
        "batch_analyze": _batch_analyze,
        "fetch_and_analyze": _fetch_and_analyze,
        "fetch_and_score": _fetch_and_score,
        # v3 integrated handlers
        "primer_design": _do_primer_design,
        "primers": _do_primer_design,
        "crispr": _do_crispr,
        "guide_rna": _do_crispr,
        "grna": _do_crispr,
        "melting_temp": _do_melting_temp,
        "tm": _do_melting_temp,
        "melting_temperature": _do_melting_temp,
        "dna_to_protein_integrated": _do_dna_to_protein_integrated,
        "dna_to_protein": _do_dna_to_protein_integrated,
        "genome_pipeline": _do_genome_pipeline,
        "pipeline": _do_genome_pipeline,
        "snakemake": _do_genome_pipeline,
    }

    handler = handlers.get(action)
    if not handler:
        return "Unknown action: '%s'. Use action='help' for available commands." % action

    try:
        return handler(**kwargs)
    except Exception as e:
        return "Error in %s: %s" % (action, str(e))


def _show_help(**kwargs):
    """Show help information - v2 expanded."""
    help_text = """
DNA LAB v2 - Genomic Foundation Model Toolkit
==============================================
Powered by Evo2 (Arc Institute) via NVIDIA NIM API
Version 3: primer, CRISPR, Tm, genome_pipeline, protein_lab integration + Version 2: batch, fetch, ORF, codon optimize, transcription & sub-bot support

Available Actions:

  CORE EVO2 (require NVIDIA_API_KEY):
    generate      Generate DNA sequences (autocomplete or de novo)
                  Args: sequence (str, DNA prompt), num_tokens (int, default=100),
                        temperature (float, default=1.0), top_k (int, default=4),
                        enable_sampled_probs (bool, default=True)

    score         Score DNA variants for impact (embedding-distance, zero-shot)
                  Args: reference_sequence (str), variant_sequence (str),
                        layer (str, default='blocks.28'), model (str, default='evo2-40b')

    embeddings    Get Evo2 embeddings for downstream ML tasks
                  Args: sequence (str), layer_name (str, default='blocks.28'),
                        model (str, default='evo2-40b')

    forward       Run forward pass to get layer activations for a DNA sequence
                  Args: sequence (str), layer_name (str, default='blocks.28'),
                        model (str, default='evo2-40b')

    analyze       Analyze DNA sequence composition (GC content, k-mers, etc.)
                  Args: sequence (str), k (int, default=3)

  SEQUENCE UTILITIES (offline, no API key needed):
    reverse_complement  Watson-Crick reverse complement
                  Args: sequence (str)
                  Example: run(action="reverse_complement", sequence="ATGCGT")

    complement    Complement (non-reversed)
                  Args: sequence (str)

    transcribe    DNA -> RNA (T->U)
                  Args: sequence (str)

    reverse_transcribe  RNA -> DNA (U->T)
                  Args: sequence (str)

    orf_find      6-frame ORF scan (all frames + best + coords)
                  Args: sequence (str)
                  Returns: frames +1/+2/+3/-1/-2/-3, ORFs sorted by length, best ORF

    codon_optimize  Codon optimize for organism
                  Args: sequence (str), organism (str: human/e_coli/yeast, default=human)
                  Uses most-common-codon table per organism

    validate      Validate DNA sequence
                  Args: sequence (str)
                  Returns: validation report (is_valid, gc%, counts, warnings)

    gc_content    Calculate GC content percentage
                  Args: sequence (str)
                  Returns: GC% string + value

  BATCH OPERATIONS (parallel via ThreadPoolExecutor max_workers=4):
    batch_score   Batch variant scoring
                  Args: reference_sequence (str), variant_sequences (list or comma-separated str),
                        layer (str, default='blocks.28')
                  Uses ThreadPoolExecutor to parallelize _score_variants calls

    batch_generate  Batch DNA generation
                  Args: sequences (list) or prompts (list) or sequence (str) comma-separated,
                        num_tokens (int, default=100), temperature, top_k, etc.

    batch_embeddings Batch embeddings
                  Args: sequences (list or comma-separated str), layer_name (str)

    batch_analyze Batch sequence analysis
                  Args: sequences (list or comma-separated str), k (int, default=3)
                  Returns: aggregated string report + JSON-like structured preview

   PRIMER & CRISPR & STABILITY (v3 integrated, offline):
     primer_design  Design PCR primers (Wallace Tm, GC clamp, dimer/hairpin)
                   Args: sequence (str), primer_length (int 14-30 default 20), tm_opt (float default 60),
                         target_region (str "start:end" or [start,end])
                   Example: run(action="primer_design", sequence="ATGCGT...ATGC", primer_length=20, tm_opt=60)

     crispr        CRISPR guide design (SpCas9 NGG scan both strands)
                   Args: sequence (str), pam (str default "NGG"), guide_length (int 15-25 default 20)
                   Example: run(action="crispr", sequence="ATGCGT...", pam="NGG", guide_length=20)

     melting_temp  Melting temperature (Wallace vs nearest-neighbor)
                   Args: sequence (str), method (str: "wallace" or "nn"/"nearest_neighbor")
                   Example: run(action="melting_temp", sequence="ATGCGT", method="wallace")
                   Alias: tm

     dna_to_protein_integrated  DNA -> Protein via protein_lab integration (cross-skill)
                   Args: sequence (str) or dna_sequence (str)
                   Tries skills.protein_lab.run(action="dna_to_protein", ...) else local translate
                   Example: run(action="dna_to_protein_integrated", sequence="ATGAAATAG")

     genome_pipeline  Snakemake genome pipeline integration (checks Snakefile, shows instructions)
                   Args: fastq_dir (str), reference (str) optional
                   Example: run(action="genome_pipeline", fastq_dir="data/fastq", reference="data/reference/hg38.fa")

  FETCH & ANALYZE (sub-bot / NCBI fallback):
    fetch_and_analyze  Fetch sequence via sub-bots then analyze
                  Args: query (str), url (str), identifier (str), accession (str), sequence (str), k (int)
                  Tries: web_crawler search + scrape (Firecrawl) via core.skills, fallback to NCBI efetch via requests.get
                  Then runs _analyze_sequence on fetched DNA

    fetch_and_score    Fetch sequence via sub-bots then score variants
                  Args: reference_sequence (str), variant_sequence (str), query/url/identifier/accession,
                        layer (str)
                  If query/accession provided, fetches reference then scores vs variant

  help          Show this help

Examples:
  run(action="generate", sequence="ACTGACTGACTGACTG", num_tokens=200)
  run(action="score", reference_sequence="ATGCGTACGT", variant_sequence="ATGCGTACGA")
  run(action="embeddings", sequence="ATGCGTACGTAGCTAG")
  run(action="forward", sequence="ATGCGTACGTAGCTAG", layer_name="blocks.49")
  run(action="analyze", sequence="ATGCGTACGTAGCTAG")
  run(action="reverse_complement", sequence="ATGCGTACGT")
  run(action="complement", sequence="ATGCGTACGT")
  run(action="transcribe", sequence="ATGCGTACGT")
  run(action="reverse_transcribe", sequence="AUGCGUACGU")
  run(action="orf_find", sequence="ATGAAATAGATGCCCCCTAA")
  run(action="codon_optimize", sequence="ATGCGTACGTAGCTAG", organism="human")
  run(action="validate", sequence="ATGCGTACGTXXX")
  run(action="gc_content", sequence="ATGCGTACGT")
  run(action="batch_analyze", sequences=["ATGCATGC", "GGCCGGCC", "TTAATTAA"], k=3)
  run(action="batch_score", reference_sequence="ATGCGTACGT", variant_sequences=["ATGCGTACGA", "ATGCGTACGG"])
  run(action="batch_generate", sequences=["ATGCATGC", "GGCCGGCC"], num_tokens=50)
  run(action="batch_embeddings", sequences=["ATGCATGC", "GGCCGGCC"])
  run(action="fetch_and_analyze", query="BRCA1", accession="NM_007294.3")
  run(action="fetch_and_analyze", url="https://www.ncbi.nlm.nih.gov/nuccore/NM_007294.3?report=fasta")
  run(action="fetch_and_score", reference_sequence="ATGCGTACGT", variant_sequence="ATGCGTACGA")
  run(action="fetch_and_score", query="NM_007294.3", variant_sequence="ATGCGTACGA")

Environment:
  NVIDIA_API_KEY - Your NVIDIA API key (get one at build.nvidia.com)
  EVO2_MODEL     - Model name (default: evo2-40b)
  EVO2_GENERATE_URL / EVO2_FORWARD_URL - Override endpoints if needed

Notes:
  - Batch operations use ThreadPoolExecutor(max_workers=4) to parallelize single-item calls (simulated sub-agent orchestration)
  - Fetch operations try web_crawler skill (Firecrawl via core.skills) first, then fallback to NCBI efetch (single source _fetch_via_subbots)
  - Offline utilities (reverse_complement etc.) work without API key
"""
    return help_text.strip()


# ---------------------------------------------------------------------------
# v2 action wrappers (human-readable string returns + JSON-like preview for batch)
# ---------------------------------------------------------------------------

def _do_reverse_complement(sequence=None, seq=None, dna=None, **kwargs):
    """Handler for reverse_complement action."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...'"
        cleaned = _clean_dna(s)
        # Use original if cleaning removes too much but we still want RC
        target = cleaned if cleaned else str(s)
        rc = _reverse_complement(target)
        if rc.startswith("ERROR"):
            return rc
        report = [
            "REVERSE COMPLEMENT (Watson-Crick)",
            "=" * 50,
            "Input length: %d bp" % len(target),
            "Input (first 60): %s" % target[:60],
            "-" * 50,
            "Reverse complement:",
            rc[:500] + ("..." if len(rc) > 500 else ""),
            "-" * 50,
            "Full length: %d bp" % len(rc),
        ]
        return "\n".join(report)
    except Exception as e:
        return "ERROR: reverse_complement failed: %s" % str(e)


def _do_complement(sequence=None, seq=None, dna=None, **kwargs):
    """Handler for complement action."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...'"
        cleaned = _clean_dna(s)
        target = cleaned if cleaned else str(s)
        comp = _complement(target)
        if comp.startswith("ERROR"):
            return comp
        report = [
            "COMPLEMENT (Watson-Crick, non-reversed)",
            "=" * 50,
            "Input length: %d bp" % len(target),
            "Input (first 60): %s" % target[:60],
            "-" * 50,
            "Complement:",
            comp[:500] + ("..." if len(comp) > 500 else ""),
            "-" * 50,
            "Full length: %d bp" % len(comp),
        ]
        return "\n".join(report)
    except Exception as e:
        return "ERROR: complement failed: %s" % str(e)


def _do_transcribe(sequence=None, seq=None, dna=None, **kwargs):
    """Handler for transcribe DNA->RNA."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...' (DNA)"
        rna = _transcribe(s)
        if rna.startswith("ERROR"):
            return rna
        cleaned = _clean_dna(s)
        report = [
            "TRANSCRIPTION DNA -> RNA (T->U)",
            "=" * 50,
            "DNA length: %d bp" % len(cleaned if cleaned else s),
            "DNA (first 60): %s" % (cleaned[:60] if cleaned else str(s)[:60]),
            "-" * 50,
            "RNA:",
            rna[:500] + ("..." if len(rna) > 500 else ""),
            "-" * 50,
            "RNA length: %d nt" % len(rna),
        ]
        return "\n".join(report)
    except Exception as e:
        return "ERROR: transcribe failed: %s" % str(e)


def _do_reverse_transcribe(sequence=None, seq=None, rna=None, **kwargs):
    """Handler for reverse_transcribe RNA->DNA."""
    try:
        s = sequence or seq or rna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='AUGC...' (RNA)"
        dna = _reverse_transcribe(s)
        if dna.startswith("ERROR"):
            return dna
        report = [
            "REVERSE TRANSCRIPTION RNA -> DNA (U->T)",
            "=" * 50,
            "RNA length: %d nt" % len(str(s).strip()),
            "RNA (first 60): %s" % str(s).strip()[:60],
            "-" * 50,
            "DNA:",
            dna[:500] + ("..." if len(dna) > 500 else ""),
            "-" * 50,
            "DNA length: %d bp" % len(dna),
        ]
        return "\n".join(report)
    except Exception as e:
        return "ERROR: reverse_transcribe failed: %s" % str(e)


def _do_orf_find(sequence=None, seq=None, dna=None, **kwargs):
    """Handler for orf_find 6-frame scan."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...'"
        result = _orf_find(s)
        if "error" in result and result.get("orf_count", 0) == 0 and "sequence_length" in result and result["sequence_length"] == 0:
            return "ERROR: %s" % result["error"]
        lines = [
            "ORF FINDER - 6 Frame Scan",
            "=" * 50,
            "Sequence length: %d bp" % result.get("sequence_length", 0),
            "Frames scanned: +1, +2, +3, -1, -2, -3",
            "Total ORFs found: %d" % result.get("orf_count", 0),
            "-" * 50,
        ]
        # Show frames preview
        frames = result.get("frames", {})
        for label in ["+1", "+2", "+3", "-1", "-2", "-3"]:
            seq_f = frames.get(label, "")
            lines.append("  Frame %s: %s%s" % (label, seq_f[:40], "..." if len(seq_f) > 40 else " (len %d)" % len(seq_f)))
        lines.append("-" * 50)
        orfs = result.get("orfs", [])
        if not orfs:
            lines.append("No ORFs found (no ATG ... stop in any frame)")
        else:
            lines.append("ORFs (sorted by length descending):")
            for idx, orf in enumerate(orfs[:10], 1):
                lines.append("  %d. Frame %s | %d bp | %d codons | pos %d-%d | strand %s" % (
                    idx, orf["frame"], orf["length"], orf["length_codons"], orf["start"], orf["end"], orf["strand"]))
                lines.append("     DNA: %s" % (orf["dna"][:60] + ("..." if len(orf["dna"]) > 60 else "")))
                lines.append("     Protein: %s" % (orf["protein"][:60] + ("..." if len(orf["protein"]) > 60 else "")))
            if len(orfs) > 10:
                lines.append("  ... and %d more ORFs (truncated)" % (len(orfs)-10))
        lines.append("-" * 50)
        best = result.get("best_orf")
        if best:
            lines.append("BEST ORF (longest):")
            lines.append("  Frame: %s | Strand: %s | Coords: %d-%d | Length: %d bp (%d codons)" % (
                best["frame"], best["strand"], best["start"], best["end"], best["length"], best["length_codons"]))
            lines.append("  DNA: %s" % best["dna"][:80])
            lines.append("  Protein: %s" % best["protein"][:80])
        else:
            lines.append("BEST ORF: None")
        # JSON-like structured preview
        lines.append("")
        lines.append("STRUCTURED PREVIEW (JSON-like):")
        try:
            preview = {
                "sequence_length": result.get("sequence_length"),
                "orf_count": result.get("orf_count"),
                "best_orf": {k: v for k, v in best.items() if k in ["frame","strand","start","end","length","protein"]} if best else None,
                "orfs_top3": [{"frame": o["frame"], "length": o["length"], "protein": o["protein"][:20]} for o in orfs[:3]],
            }
            lines.append(json.dumps(preview, indent=2))
        except Exception:
            lines.append(str({"orf_count": result.get("orf_count")})[:500])
        return "\n".join(lines)
    except Exception as e:
        return "ERROR: orf_find failed: %s" % str(e)


def _do_codon_optimize(sequence=None, seq=None, dna=None, organism="human", **kwargs):
    """Handler for codon_optimize."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...'"
        org = kwargs.get("organism") or kwargs.get("org") or organism or "human"
        # Normalize organism param
        if isinstance(org, str):
            org = org.lower().strip()
        else:
            org = "human"
        optimized = _codon_optimize(s, organism=org)
        if optimized.startswith("ERROR"):
            return optimized
        cleaned = _clean_dna(s)
        report = [
            "CODON OPTIMIZATION",
            "=" * 50,
            "Organism: %s" % org,
            "Input length: %d bp" % len(cleaned),
            "Input (first 60): %s" % cleaned[:60],
            "-" * 50,
            "Optimized sequence:",
            optimized[:500] + ("..." if len(optimized) > 500 else ""),
            "-" * 50,
            "Optimized length: %d bp" % len(optimized),
            "GC before: %.1f%% | GC after: %.1f%%" % (_gc_content(cleaned), _gc_content(optimized)),
        ]
        # Show translation check for first few codons
        try:
            orig_codons = [cleaned[i:i+3] for i in range(0, min(len(cleaned), 30), 3) if len(cleaned[i:i+3])==3]
            opt_codons = [optimized[i:i+3] for i in range(0, min(len(optimized), 30), 3) if len(optimized[i:i+3])==3]
            orig_aa = "".join(_CODON_TABLE.get(c, "X") for c in orig_codons[:5])
            opt_aa = "".join(_CODON_TABLE.get(c, "X") for c in opt_codons[:5])
            report.append("First 5 codons AA check: %s -> %s (should match)" % (orig_aa, opt_aa))
        except Exception:
            pass
        # JSON preview
        report.append("")
        report.append("STRUCTURED PREVIEW:")
        report.append(json.dumps({"organism": org, "input_gc": round(_gc_content(cleaned),2), "optimized_gc": round(_gc_content(optimized),2), "length": len(optimized), "optimized_preview": optimized[:60]}, indent=2))
        return "\n".join(report)
    except Exception as e:
        return "ERROR: codon_optimize failed: %s" % str(e)


def _do_validate(sequence=None, seq=None, dna=None, **kwargs):
    """Handler for validate."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s and kwargs:
            # Try any kwarg that looks like sequence
            for v in kwargs.values():
                if isinstance(v, str) and len(v) > 5:
                    s = v
                    break
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...'"
        rep = _validate_sequence(s)
        lines = [
            "SEQUENCE VALIDATION REPORT",
            "=" * 50,
            "Original length: %d" % rep.get("original_length", 0),
            "Cleaned length: %d bp" % rep.get("cleaned_length", 0),
            "Is valid: %s" % rep.get("is_valid"),
            "GC content: %.1f%%" % rep.get("gc_content", 0),
            "-" * 50,
            "Base counts: %s" % str(rep.get("base_counts")),
            "Preview: %s" % rep.get("cleaned_sequence_preview"),
        ]
        inv = rep.get("invalid_characters", [])
        if inv:
            lines.append("Invalid characters: %s" % ", ".join(inv[:10]))
        else:
            lines.append("Invalid characters: None")
        warns = rep.get("warnings", [])
        if warns:
            lines.append("-" * 50)
            lines.append("Warnings:")
            for w in warns:
                lines.append("  - %s" % w)
        if rep.get("error"):
            lines.append("Error: %s" % rep["error"])
        lines.append("")
        lines.append("STRUCTURED PREVIEW:")
        try:
            lines.append(json.dumps({k: rep[k] for k in ["is_valid","cleaned_length","gc_content","base_counts","invalid_characters"] if k in rep}, indent=2))
        except Exception:
            lines.append(str(rep)[:500])
        return "\n".join(lines)
    except Exception as e:
        return "ERROR: validate failed: %s" % str(e)


def _do_gc_content(sequence=None, seq=None, dna=None, **kwargs):
    """Handler for gc_content."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...'"
        cleaned = _clean_dna(s)
        gc = _gc_content(cleaned if cleaned else str(s))
        counts = {base: (cleaned if cleaned else str(s).upper()).count(base) for base in "ACGT"}
        length = len(cleaned) if cleaned else len(str(s).strip())
        lines = [
            "GC CONTENT",
            "=" * 50,
            "Sequence length: %d bp" % length,
            "G: %d | C: %d | A: %d | T: %d" % (counts.get("G",0), counts.get("C",0), counts.get("A",0), counts.get("T",0)),
            "-" * 50,
            "GC content: %.2f%%" % gc,
            "AT content: %.2f%%" % (100 - gc),
            "GC/(AT+GC) ratio: %.3f" % (gc/100 if length>0 else 0),
        ]
        # Add interpretation
        if gc > 60:
            lines.append("Interpretation: HIGH GC (thermostable, strong secondary structure)")
        elif gc > 40:
            lines.append("Interpretation: MODERATE GC (balanced)")
        else:
            lines.append("Interpretation: LOW GC (AT-rich)")
        lines.append("")
        lines.append("STRUCTURED PREVIEW:")
        lines.append(json.dumps({"length": length, "gc_percent": round(gc,2), "at_percent": round(100-gc,2), "counts": counts}, indent=2))
        return "\n".join(lines)
    except Exception as e:
        return "ERROR: gc_content failed: %s" % str(e)


# ---------------------------------------------------------------------------
# v3 Handler wrappers for advanced features (integrated)
# ---------------------------------------------------------------------------

def _do_primer_design(sequence=None, seq=None, dna=None, primer_length=20, tm_opt=60, target_region=None, **kwargs):
    """Handler for primer_design."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or kwargs.get("template") or ""
        if not s:
            # try any string kwarg that looks like DNA
            for v in kwargs.values():
                if isinstance(v, str) and len(_clean_dna(v)) >= 20:
                    s = v
                    break
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...' (template DNA)"
        # allow alt param names
        pl = kwargs.get("primer_length", kwargs.get("length", kwargs.get("primer_len", primer_length)))
        tm = kwargs.get("tm_opt", kwargs.get("tm", kwargs.get("tm_optimal", tm_opt)))
        tr = target_region or kwargs.get("target") or kwargs.get("region") or kwargs.get("target_region")
        res = _design_primers(s, target_region=tr, primer_length=pl, tm_opt=tm, **kwargs)
        if "error" in res:
            return "ERROR: %s" % res["error"]
        fwd = res["forward"]
        rev = res["reverse"]
        lines = [
            "PRIMER DESIGN (Wallace Tm, GC clamp, hairpin/dimer check)",
            "="*60,
            "Template length: %d bp | Primer len requested: %d | Tm opt: %.1fC" % (res["template_length"], res["primer_length_requested"], res["tm_optimal"]),
            "Template preview: %s" % res["template_preview"],
            "Target region: %s (product ~%d bp)" % (str(res["target_region"]), res["product_length_estimate"]),
            "-"*60,
            "FORWARD PRIMER (5' end):",
            "  Sequence: %s" % fwd["sequence"],
            "  Length: %d | Tm: %.1fC (%s) | GC: %.1f%% | GC clamp 3': %s (%d/2 G/C)" % (fwd["length"], fwd["tm_c"], fwd["method"], fwd["gc_percent"], "YES" if fwd["gc_clamp"] else "NO", fwd["gc_clamp_strength_2bp"]),
        ]
        if fwd["warnings"]:
            lines.append("  Warnings:")
            for w in fwd["warnings"]:
                lines.append("    - %s" % w)
        lines.extend([
            "-"*60,
            "REVERSE PRIMER (reverse complement of 3' end):",
            "  Sequence: %s" % rev["sequence"],
            "  Template raw (3' region): %s" % res.get("reverse_template_raw","")[:60],
            "  Length: %d | Tm: %.1fC (%s) | GC: %.1f%% | GC clamp 3': %s (%d/2 G/C)" % (rev["length"], rev["tm_c"], rev["method"], rev["gc_percent"], "YES" if rev["gc_clamp"] else "NO", rev["gc_clamp_strength_2bp"]),
        ])
        if rev["warnings"]:
            lines.append("  Warnings:")
            for w in rev["warnings"]:
                lines.append("    - %s" % w)
        lines.append("-"*60)
        if res["cross_warnings"]:
            lines.append("CROSS-PRIMER WARNINGS:")
            for w in res["cross_warnings"]:
                lines.append("  - %s" % w)
            lines.append("-"*60)
        else:
            lines.append("Cross-primer: OK (no strong dimer, Tm matched)")
            lines.append("-"*60)
        # Tm diff
        lines.append("Tm diff Fwd-Rev: %.1fC" % abs(fwd["tm_c"]-rev["tm_c"]))
        lines.append("")
        lines.append("STRUCTURED PREVIEW (JSON-like):")
        try:
            preview = {
                "template_length": res["template_length"],
                "forward": {"seq": fwd["sequence"], "tm": fwd["tm_c"], "gc": fwd["gc_percent"], "clamp": fwd["gc_clamp"]},
                "reverse": {"seq": rev["sequence"], "tm": rev["tm_c"], "gc": rev["gc_percent"], "clamp": rev["gc_clamp"]},
                "cross_warnings": res["cross_warnings"],
                "product_length_estimate": res["product_length_estimate"],
            }
            lines.append(json.dumps(preview, indent=2))
        except Exception:
            lines.append(str(preview)[:500])
        out = "\n".join(lines)
        # v3: graceful memory store
        try:
            _store_result_memory_gracefully(out[:4000], key_prefix="primer_design")
        except Exception:
            pass
        return out
    except Exception as e:
        return "ERROR: primer_design failed: %s" % str(e)


def _do_crispr(sequence=None, seq=None, dna=None, pam="NGG", guide_length=20, **kwargs):
    """Handler for CRISPR guide design."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or kwargs.get("template") or ""
        if not s:
            for v in kwargs.values():
                if isinstance(v, str) and len(_clean_dna(v)) >= 20:
                    s = v
                    break
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...' to scan for guides"
        pam_val = kwargs.get("pam", pam)
        gl = kwargs.get("guide_length", kwargs.get("guide_len", kwargs.get("length", guide_length)))
        res = _crispr_guides(s, pam=pam_val, guide_length=gl, **kwargs)
        if "error" in res and res.get("total_guides",0)==0 and "sequence_length" in res and res["sequence_length"]==0:
            return "ERROR: %s" % res["error"]
        guides = res.get("guides", [])
        lines = [
            "CRISPR GUIDE DESIGN (PAM scan both strands, GC & off-target hint)",
            "="*60,
            "Template length: %d bp | PAM: %s (regex %s) | Guide len: %d" % (res["sequence_length"], res["pam"], res["pam_regex"], res["guide_length"]),
            "Total guides found: %d (showing top %d sorted by GC~50%% + uniqueness)" % (res["total_guides"], len(guides)),
            "-"*60,
        ]
        if not guides:
            lines.append("No guides found for PAM %s. Try pam='NGG' (SpCas9) or pam='TTTV' (Cas12) or check template length." % res["pam"])
        else:
            for idx, g in enumerate(guides[:12], 1):
                lines.append("%d. [%s] %s | PAM %s at %d | GC %.1f%% | %s | cut~%d" % (idx, g["strand"], g["guide"], g["pam"], g["pam_start"], g["gc_percent"], g["off_target_hint"], g["cut_position"]))
                if g.get("notes"):
                    lines.append("    Notes: %s" % "; ".join(g["notes"][:3]))
                if g["strand"] == "-" and g.get("guide_rc_on_original"):
                    lines.append("    (on original + strand): %s" % g["guide_rc_on_original"][:30])
            if len(guides) > 12:
                lines.append("  ... and %d more (truncated, see JSON preview)" % (len(guides)-12))
        lines.append("-"*60)
        if res.get("warnings"):
            lines.append("Warnings: %s" % "; ".join(res["warnings"]))
        lines.append("Method: scan for PAM on both strands, extract upstream %d-bp guide, score GC%% (_gc_content) + k-mer uniqueness (_kmer_counts + _reverse_complement)" % res["guide_length"])
        lines.append("")
        lines.append("STRUCTURED PREVIEW:")
        try:
            preview = {
                "sequence_length": res["sequence_length"],
                "pam": res["pam"],
                "guide_length": res["guide_length"],
                "total_guides": res["total_guides"],
                "top_guides": [{"strand": g["strand"], "guide": g["guide"], "pam": g["pam"], "gc": g["gc_percent"], "off_target": g["off_target_hint"]} for g in guides[:5]],
            }
            lines.append(json.dumps(preview, indent=2))
        except Exception:
            lines.append(str(res)[:500])
        out = "\n".join(lines)
        try:
            _store_result_memory_gracefully(out[:4000], key_prefix="crispr")
        except Exception:
            pass
        return out
    except Exception as e:
        return "ERROR: crispr failed: %s" % str(e)


def _do_melting_temp(sequence=None, seq=None, dna=None, method="wallace", **kwargs):
    """Handler for melting_temp / tm."""
    try:
        s = sequence or seq or dna or kwargs.get("query") or ""
        if not s:
            for v in kwargs.values():
                if isinstance(v, str) and len(_clean_dna(v)) >= 5:
                    s = v
                    break
        if not s:
            return "ERROR: No sequence provided. Pass sequence='ATGC...' "
        meth = kwargs.get("method", kwargs.get("mode", method))
        # also allow action param confusion: if sequence contains method
        res = _melting_temp(s, method=meth, **kwargs)
        if "error" in res:
            return "ERROR: %s" % res["error"]
        lines = [
            "MELTING TEMPERATURE",
            "="*50,
            "Sequence: %s%s (len %d)" % (res["sequence"][:60], "..." if len(res["sequence"])>60 else "", res["cleaned_length"]),
            "Method: %s | Formula: %s" % (res["method"], res["formula"]),
            "-"*50,
            "Tm: %.2fC" % res["tm_c"],
            "GC: %.1f%%" % res["gc_percent"],
            "Counts: A=%d T=%d G=%d C=%d" % (res["base_counts"]["A"], res["base_counts"]["T"], res["base_counts"]["G"], res["base_counts"]["C"]),
        ]
        # Integration note
        lines.append("-"*50)
        lines.append("Integration: uses _validate_sequence + _gc_content + _clean_dna")
        if res.get("warnings"):
            lines.append("Warnings:")
            for w in res["warnings"]:
                lines.append("  - %s" % w)
        # Compare methods if requested
        if kwargs.get("compare") or kwargs.get("show_both"):
            other = "nn" if res["method"]=="wallace" else "wallace"
            other_res = _melting_temp(s, method=other)
            if "tm_c" in other_res:
                lines.append("-"*50)
                lines.append("Compare %s: %.2fC (GC %.1f%%)" % (other, other_res["tm_c"], other_res["gc_percent"]))
        lines.append("")
        lines.append("STRUCTURED PREVIEW:")
        lines.append(json.dumps({"sequence_preview": res["sequence"][:40], "tm_c": res["tm_c"], "method": res["method"], "gc_percent": res["gc_percent"], "formula": res["formula"]}, indent=2))
        out = "\n".join(lines)
        try:
            _store_result_memory_gracefully(out[:2000], key_prefix="melting_temp")
        except Exception:
            pass
        return out
    except Exception as e:
        return "ERROR: melting_temp failed: %s" % str(e)


def _do_dna_to_protein_integrated(sequence=None, seq=None, dna=None, dna_sequence=None, **kwargs):
    """Handler for dna_to_protein_integrated (cross-skill)."""
    try:
        s = sequence or seq or dna or dna_sequence or kwargs.get("query") or kwargs.get("template") or ""
        if not s:
            for v in kwargs.values():
                if isinstance(v, str) and len(_clean_dna(v)) >= 6:
                    s = v
                    break
        if not s:
            return "ERROR: No DNA provided. Pass sequence='ATGC...' or dna_sequence='ATGC...'"
        # allow any param naming; delegate to integrated function
        res_str = _dna_to_protein_integrated(s, **kwargs)
        # store gracefully
        try:
            _store_result_memory_gracefully(res_str[:4000], key_prefix="dna_to_protein")
        except Exception:
            pass
        return res_str
    except Exception as e:
        return "ERROR: dna_to_protein_integrated handler failed: %s" % str(e)


def _do_genome_pipeline(fastq_dir=None, reference=None, **kwargs):
    """Handler for genome_pipeline integration."""
    try:
        fd = fastq_dir or kwargs.get("fastq_dir") or kwargs.get("fastq") or kwargs.get("fastqDir") or kwargs.get("fastq_path")
        ref = reference or kwargs.get("reference") or kwargs.get("ref") or kwargs.get("genome")
        res = _run_genome_pipeline(fastq_dir=fd, reference=ref, **kwargs)
        return res
    except Exception as e:
        return "ERROR: genome_pipeline handler failed: %s" % str(e)


# ---------------------------------------------------------------------------
# Batch operations via ThreadPoolExecutor
# ---------------------------------------------------------------------------

def _batch_score(reference_sequence=None, variant_sequences=None, layer="blocks.28", model="evo2-40b", api_key=None, **kwargs):
    """Batch variant scoring via ThreadPoolExecutor (max_workers=4)."""
    try:
        ref = reference_sequence or kwargs.get("reference") or kwargs.get("ref_seq") or ""
        variants_raw = variant_sequences or kwargs.get("variants") or kwargs.get("variant_sequence") or []
        variants = _parse_list_input(variants_raw)
        if not ref:
            return "ERROR: batch_score requires reference_sequence (str). Pass reference_sequence='ATGC...' and variant_sequences=[...]"
        if not variants:
            return "ERROR: batch_score requires variant_sequences (list or comma-separated str). Got empty."

        # Allow alternative param names
        layer = kwargs.get("layer") or layer
        model = kwargs.get("model") or model
        api_key = kwargs.get("api_key") or api_key

        results = []
        errors = []
        start_t = time.time()

        def _score_one(var_seq):
            try:
                # Each task calls the single-item function (simulated sub-agent orchestration)
                res = _score_variants(reference_sequence=ref, variant_sequence=var_seq, layer=layer, model=model, api_key=api_key)
                return (var_seq, res, None)
            except Exception as e:
                return (var_seq, None, str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_var = {executor.submit(_score_one, v): v for v in variants}
            for future in as_completed(future_to_var):
                var_seq, res, err = future.result()
                if err:
                    errors.append({"variant": var_seq[:30], "error": err})
                    results.append({"variant": var_seq, "result": "ERROR: %s" % err})
                else:
                    # Keep truncated preview for aggregation
                    results.append({"variant": var_seq, "result": res})

        elapsed = time.time() - start_t
        # Build aggregated string report
        lines = [
            "BATCH VARIANT SCORING (ThreadPoolExecutor max_workers=4)",
            "=" * 60,
            "Reference: %s%s (len %d)" % (ref[:40], "..." if len(ref)>40 else "", len(ref)),
            "Variants: %d | Layer: %s | Model: %s" % (len(variants), layer, model),
            "Elapsed: %.2f s (avg %.2f s/var)" % (elapsed, elapsed/len(variants) if variants else 0),
            "-" * 60,
        ]
        for idx, entry in enumerate(results, 1):
            var_prev = entry["variant"][:40]
            res_preview = entry["result"][:300].replace("\n", " | ") if isinstance(entry["result"], str) else str(entry["result"])[:300]
            lines.append("%d. Variant %s... -> %s" % (idx, var_prev, res_preview[:120]))
        if errors:
            lines.append("-" * 60)
            lines.append("Errors: %d" % len(errors))
            for e in errors[:5]:
                lines.append("  - %s: %s" % (e["variant"], e["error"][:80]))
        lines.append("-" * 60)
        # JSON-like structured preview
        lines.append("STRUCTURED PREVIEW (JSON-like):")
        try:
            preview = {
                "reference_length": len(ref),
                "variant_count": len(variants),
                "layer": layer,
                "elapsed_sec": round(elapsed, 2),
                "results_preview": [{"variant_preview": r["variant"][:30], "has_error": "ERROR" in str(r["result"])} for r in results[:5]],
                "errors": errors[:3],
            }
            lines.append(json.dumps(preview, indent=2))
        except Exception:
            lines.append("Preview unavailable")

        # Thread-safe store
        _cache_batch_result("batch_score", {"count": len(variants), "elapsed": elapsed, "timestamp": time.time()})
        try:
            _store_result_memory_gracefully("\n".join(lines)[:4000], key_prefix="batch_score")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return "ERROR: batch_score failed: %s" % str(e)


def _batch_generate(sequences=None, prompts=None, sequence=None, num_tokens=100, temperature=1.0, top_k=4, enable_sampled_probs=True, model="evo2-40b", api_key=None, **kwargs):
    """Batch DNA generation via ThreadPoolExecutor."""
    try:
        seqs_raw = sequences or prompts or sequence or kwargs.get("seqs") or kwargs.get("prompt") or []
        seqs = _parse_list_input(seqs_raw)

        if not seqs:
            return "ERROR: batch_generate requires sequences (list or comma-separated str). Example: sequences=['ATGC','GGCC']"

        num_tokens = kwargs.get("num_tokens", num_tokens)
        temperature = kwargs.get("temperature", temperature)
        top_k = kwargs.get("top_k", top_k)
        enable_sampled_probs = kwargs.get("enable_sampled_probs", enable_sampled_probs)
        model = kwargs.get("model", model)
        api_key = kwargs.get("api_key", api_key)

        start_t = time.time()
        results = []
        errors = []

        def _gen_one(prompt_seq):
            try:
                res = _generate(sequence=prompt_seq, num_tokens=num_tokens, temperature=temperature, top_k=top_k, enable_sampled_probs=enable_sampled_probs, model=model, api_key=api_key)
                return (prompt_seq, res, None)
            except Exception as e:
                return (prompt_seq, None, str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_gen_one, s): s for s in seqs}
            for fut in as_completed(futures):
                prompt_seq, res, err = fut.result()
                if err:
                    errors.append({"prompt": prompt_seq[:30], "error": err})
                    results.append({"prompt": prompt_seq, "result": "ERROR: %s" % err})
                else:
                    results.append({"prompt": prompt_seq, "result": res})

        elapsed = time.time() - start_t
        lines = [
            "BATCH GENERATION (ThreadPoolExecutor max_workers=4)",
            "=" * 60,
            "Prompts: %d | num_tokens: %d | temp: %.2f | top_k: %d" % (len(seqs), int(num_tokens), float(temperature), int(top_k)),
            "Elapsed: %.2f s" % elapsed,
            "-" * 60,
        ]
        for idx, entry in enumerate(results, 1):
            preview = entry["result"][:200].replace("\n"," | ") if isinstance(entry["result"], str) else str(entry["result"])[:200]
            lines.append("%d. Prompt %s... -> %s" % (idx, entry["prompt"][:30], preview[:120]))
        if errors:
            lines.append("Errors: %d" % len(errors))
        lines.append("-" * 60)
        lines.append("STRUCTURED PREVIEW:")
        try:
            preview_data = {
                "prompt_count": len(seqs),
                "num_tokens": num_tokens,
                "elapsed_sec": round(elapsed,2),
                "results_count": len(results),
                "previews": [{"prompt_preview": r["prompt"][:30], "result_preview": str(r["result"])[:80]} for r in results[:3]],
            }
            lines.append(json.dumps(preview_data, indent=2))
        except Exception:
            lines.append("Preview error")

        _cache_batch_result("batch_generate", {"count": len(seqs), "elapsed": elapsed, "timestamp": time.time()})
        try:
            _store_result_memory_gracefully("\n".join(lines)[:4000], key_prefix="batch_generate")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return "ERROR: batch_generate failed: %s" % str(e)


def _batch_embeddings(sequences=None, sequence=None, layer_name="blocks.28", model="evo2-40b", api_key=None, **kwargs):
    """Batch embeddings via ThreadPoolExecutor."""
    try:
        seqs_raw = sequences or sequence or kwargs.get("seqs") or kwargs.get("seq") or []
        seqs = _parse_list_input(seqs_raw)
        if not seqs:
            return "ERROR: batch_embeddings requires sequences (list or comma-separated str)."

        layer_name = kwargs.get("layer_name") or kwargs.get("layer") or layer_name
        model = kwargs.get("model", model)
        api_key = kwargs.get("api_key", api_key)

        start_t = time.time()
        results = []
        errors = []

        def _emb_one(seq):
            try:
                res = _embeddings(sequence=seq, layer_name=layer_name, model=model, api_key=api_key)
                return (seq, res, None)
            except Exception as e:
                return (seq, None, str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_emb_one, s): s for s in seqs}
            for fut in as_completed(futures):
                seq, res, err = fut.result()
                if err:
                    errors.append({"seq_preview": seq[:30], "error": err})
                    results.append({"seq": seq, "result": "ERROR: %s" % err})
                else:
                    results.append({"seq": seq, "result": res})

        elapsed = time.time() - start_t
        lines = [
            "BATCH EMBEDDINGS (ThreadPoolExecutor max_workers=4)",
            "=" * 60,
            "Sequences: %d | Layer: %s | Model: %s" % (len(seqs), layer_name, model),
            "Elapsed: %.2f s" % elapsed,
            "-" * 60,
        ]
        for idx, entry in enumerate(results, 1):
            preview = entry["result"][:200].replace("\n"," | ") if isinstance(entry["result"], str) else str(entry["result"])[:200]
            lines.append("%d. Seq %s... -> %s" % (idx, entry["seq"][:30], preview[:120]))
        lines.append("-" * 60)
        lines.append("STRUCTURED PREVIEW:")
        try:
            preview_data = {
                "sequence_count": len(seqs),
                "layer": layer_name,
                "elapsed_sec": round(elapsed,2),
                "previews": [{"seq_preview": r["seq"][:30], "ok": "ERROR" not in str(r["result"])} for r in results[:3]],
                "errors": errors[:2],
            }
            lines.append(json.dumps(preview_data, indent=2))
        except Exception:
            lines.append("Preview error")

        _cache_batch_result("batch_embeddings", {"count": len(seqs), "elapsed": elapsed, "timestamp": time.time()})
        try:
            _store_result_memory_gracefully("\n".join(lines)[:4000], key_prefix="batch_embeddings")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return "ERROR: batch_embeddings failed: %s" % str(e)


def _batch_analyze(sequences=None, sequence=None, k=3, **kwargs):
    """Batch sequence analysis via ThreadPoolExecutor."""
    try:
        seqs_raw = sequences or sequence or kwargs.get("seqs") or []
        seqs = _parse_list_input(seqs_raw)
        if not seqs:
            return "ERROR: batch_analyze requires sequences (list or comma-separated str). Example: sequences=['ATGC','GGCC']"

        k = int(kwargs.get("k", k))

        start_t = time.time()
        results = []
        errors: List[Dict[str, Any]] = []

        def _analyze_one(seq):
            try:
                # Simulate sub-agent orchestration: each task calls single-item function
                res = _analyze_sequence(sequence=seq, k=k)
                gc = _gc_content(seq)
                kmers = _kmer_counts(seq, k=k)
                # Extract top kmer
                top_kmer = max(kmers.items(), key=lambda x: x[1]) if kmers else ("",0)
                return (seq, {"report": res, "gc": gc, "top_kmer": top_kmer, "length": len(_clean_dna(seq))}, None)
            except Exception as e:
                return (seq, None, str(e))

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_analyze_one, s): s for s in seqs}
            for fut in as_completed(futures):
                seq, data, err = fut.result()
                if err:
                    errors.append({"seq_preview": seq[:30], "error": err})
                    results.append({"seq": seq, "data": None, "error": err})
                else:
                    results.append({"seq": seq, "data": data, "error": None})

        elapsed = time.time() - start_t
        # Sort results to original order (by seq appearance)
        # Already have but keep as is
        lines = [
            "BATCH ANALYSIS (ThreadPoolExecutor max_workers=4)",
            "=" * 60,
            "Sequences: %d | k: %d | Elapsed: %.2f s" % (len(seqs), k, elapsed),
            "-" * 60,
        ]
        # Aggregate stats
        total_len = sum(r["data"]["length"] for r in results if r["data"])
        avg_gc = sum(r["data"]["gc"] for r in results if r["data"]) / len(results) if results else 0
        lines.append("Aggregated: total_bases=%d | avg_gc=%.1f%% | avg_len=%.0f" % (total_len, avg_gc, total_len/len(results) if results else 0))
        lines.append("-" * 60)
        for idx, entry in enumerate(results, 1):
            if entry["error"]:
                lines.append("%d. %s... -> ERROR: %s" % (idx, entry["seq"][:30], entry["error"][:60]))
            else:
                d = entry["data"]
                lines.append("%d. %s... | len=%d | GC=%.1f%% | top %d-mer=%s (%d)" % (
                    idx, entry["seq"][:30], d["length"], d["gc"], k, d["top_kmer"][0], d["top_kmer"][1]))
        if errors:
            lines.append("Errors: %d" % len(errors))
        lines.append("-" * 60)
        lines.append("Detailed reports (truncated to first 2):")
        for entry in results[:2]:
            if entry["data"]:
                # Show first 8 lines of each analyze report
                report_lines = entry["data"]["report"].split("\n")[:8]
                lines.append("--- %s ... ---" % entry["seq"][:20])
                lines.extend(report_lines)
        lines.append("-" * 60)
        lines.append("STRUCTURED PREVIEW (JSON-like):")
        try:
            preview = {
                "sequence_count": len(seqs),
                "k": k,
                "elapsed_sec": round(elapsed,2),
                "aggregated": {"total_bases": total_len, "avg_gc": round(avg_gc,2)},
                "per_sequence": [{"preview": r["seq"][:30], "gc": round(r["data"]["gc"],2) if r["data"] else None, "length": r["data"]["length"] if r["data"] else 0, "top_kmer": r["data"]["top_kmer"] if r["data"] else None} for r in results[:5]],
                "errors": errors[:2],
            }
            lines.append(json.dumps(preview, indent=2))
        except Exception as e:
            lines.append("Preview error: %s" % str(e))

        _cache_batch_result("batch_analyze", {"count": len(seqs), "elapsed": elapsed, "timestamp": time.time()})
        # v3: gracefully store in memory layers
        try:
            _store_result_memory_gracefully("\n".join(lines)[:4000], key_prefix="batch_analyze")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return "ERROR: batch_analyze failed: %s" % str(e)


# ---------------------------------------------------------------------------
# Fetch and analyze / score
# ---------------------------------------------------------------------------

def _extract_dna_from_text(text: str) -> Optional[str]:
    """Heuristic: extract longest DNA-like stretch from fetched text (FASTA or plain)."""
    try:
        if not text:
            return None
        # Try FASTA parsing first
        # Find lines that look like DNA (long ACGT stretches)
        # Remove header lines starting with >
        lines = [l.strip() for l in text.split("\n") if l.strip() and not l.strip().startswith(">")]
        # Join and clean
        joined = "".join(lines)
        # Find longest ACGT substring >= 20 bp
        # Use regex to find stretches
        candidates = re.findall(r"[ACGTacgt]{20,}", joined)
        if candidates:
            longest = max(candidates, key=len)
            # Clean and return
            cleaned = _clean_dna(longest)
            if len(cleaned) >= 20:
                return cleaned
        # Fallback: clean whole text and see if result is DNA-like
        cleaned_all = _clean_dna(text)
        if len(cleaned_all) >= 20 and len(cleaned_all) > len(text) * 0.5:
            # If cleaned is plausible (over half chars were DNA)
            return cleaned_all
        # Also try to find U-containing RNA and convert
        # Look for AUCGU stretches
        return None
    except Exception:
        return None


def _ncbi_efetch_fasta(accession: str) -> Optional[str]:
    """Fallback: direct requests.get to NCBI efetch for FASTA."""
    try:
        acc = str(accession).strip()
        # Basic accession validation: allow typical NCBI patterns
        if not re.match(r"^[A-Z]{1,3}_?\d+(\.\d+)?$", acc):
            # Try to extract accession from longer string
            m = re.search(r"[A-Z]{1,3}_?\d+(\.\d+)?", acc)
            if m:
                acc = m.group(0)
            else:
                return None
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=%s&rettype=fasta&retmode=text" % acc
        # Also try nucleotide
        resp = requests.get(url, timeout=20)
        if resp.status_code == 200 and resp.text and ">" in resp.text:
            return resp.text
        # Try with db=nucleotide
        url2 = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nucleotide&id=%s&rettype=fasta&retmode=text" % acc
        resp2 = requests.get(url2, timeout=20)
        if resp2.status_code == 200 and resp2.text and ">" in resp2.text:
            return resp2.text
        return None
    except Exception:
        return None


def _fetch_and_analyze(query=None, url=None, identifier=None, accession=None, sequence=None, k=3, **kwargs):
    """Fetch via sub-bots/NCBI then analyze. Args: query/url/identifier/accession or sequence param."""
    try:
        # If direct sequence provided without fetch intent, just analyze
        if sequence and not any([query, url, identifier, accession]):
            # Check if sequence looks like accession and user wants fetch - but if it's clearly DNA, analyze directly
            if len(_clean_dna(sequence)) >= 20 and len(_clean_dna(sequence)) / max(len(sequence),1) > 0.8:
                return _analyze_sequence(sequence=sequence, k=k)
            # Otherwise treat as query
            query = sequence
            sequence = None

        # If sequence is direct DNA and no fetch needed, handle
        if sequence and _clean_dna(sequence):
            # Could still fetch additional context, but prioritize sequence
            fetch_note = "Direct sequence provided; running _analyze_sequence immediately."
            analysis = _analyze_sequence(sequence=sequence, k=k)
            return fetch_note + "\n\n" + analysis

        # Normalize params: allow 'query' to be url/accession/sequence
        target_query = query or identifier or accession or url
        target_url = url
        target_accession = accession or identifier

        # Try sub-bots first
        fetch_result = _fetch_via_subbots(query=target_query, url=target_url, identifier=identifier, accession=target_accession, **kwargs)
        fetched_text: Optional[str] = None
        dna_seq: Optional[str] = None
        notes = []

        if fetch_result and not fetch_result.get("fallback"):
            # Sub-bot succeeded maybe; try to extract DNA from its scrape/search
            scrape_text = fetch_result.get("scrape") or fetch_result.get("search") or ""
            if scrape_text:
                dna_seq = _extract_dna_from_text(str(scrape_text))
                fetched_text = str(scrape_text)
                if dna_seq:
                    notes.append("Fetched via web_crawler (Firecrawl) scrape/search")
                else:
                    notes.append("web_crawler returned data but no DNA extracted; trying NCBI fallback")
            else:
                notes.append("web_crawler invoked but no scrape/search text; trying NCBI fallback")
        else:
            # Sub-bot not available or fallback
            err_msg = fetch_result.get("error", "unknown") if isinstance(fetch_result, dict) else "no result"
            notes.append("web_crawler fallback: %s" % err_msg[:120])
            notes.append("Trying direct NCBI efetch fallback...")

        # If no dna_seq yet, _fetch_via_subbots already tried web_crawler + NCBI efetch (single source).
        # Only remaining fallback: treat query directly as DNA if it looks like sequence
        if not dna_seq:
            if target_query and len(_clean_dna(str(target_query))) >= 20:
                dna_seq = _clean_dna(str(target_query))
                fetched_text = str(target_query)
                notes.append("No accession fetch; using query directly as DNA sequence (cleaned)")

        if not dna_seq:
            # Failure: return error + fetch notes
            lines = [
                "FETCH AND ANALYZE - FAILED TO OBTAIN DNA",
                "=" * 60,
                "Notes:",
            ]
            for n in notes:
                lines.append("  - %s" % n)
            lines.append("-" * 60)
            lines.append("Fetch result preview:")
            lines.append(json.dumps({k: str(v)[:300] for k, v in (fetch_result or {}).items()}, indent=2) if isinstance(fetch_result, dict) else str(fetch_result)[:500])
            if fetched_text:
                lines.append("Fetched text preview (first 400):")
                lines.append(fetched_text[:400])
            lines.append("")
            lines.append("Suggestion: Provide direct sequence via sequence='ATGC...' or a valid accession like NM_007294.3")
            lines.append("Example: run(action='fetch_and_analyze', accession='NM_007294.3')")
            return "\n".join(lines)

        # Success: run _analyze_sequence on fetched dna
        analysis = _analyze_sequence(sequence=dna_seq, k=int(k))
        header = [
            "FETCH AND ANALYZE - SUCCESS",
            "=" * 60,
            "Fetch notes:",
        ]
        for n in notes:
            header.append("  - %s" % n)
        header.append("Fetched DNA length: %d bp (preview: %s...)" % (len(dna_seq), dna_seq[:40]))
        header.append("Fetched text preview: %s" % (fetched_text[:120].replace("\n"," ") if fetched_text else "N/A"))
        header.append("-" * 60)
        # JSON preview
        header.append("STRUCTURED PREVIEW:")
        try:
            preview = {
                "fetched_length": len(dna_seq),
                "fetch_notes": notes[:3],
                "gc_percent": round(_gc_content(dna_seq),2),
                "accession_or_query": str(target_query or target_accession or target_url)[:40],
            }
            header.append(json.dumps(preview, indent=2))
        except Exception:
            pass
        header.append("-" * 60)
        header.append(analysis)
        full = "\n".join(header)
        try:
            _store_result_memory_gracefully(full[:4000], key_prefix="fetch_and_analyze")
        except Exception:
            pass
        return full

    except Exception as e:
        return "ERROR: fetch_and_analyze failed: %s" % str(e)


def _fetch_and_score(query=None, url=None, identifier=None, accession=None, reference_sequence=None, variant_sequence=None, variant_sequences=None, layer="blocks.28", model="evo2-40b", api_key=None, **kwargs):
    """Fetch via sub-bots/NCBI then score. Handles fetch for reference if needed, then calls _score_variants or batch."""
    try:
        # Normalize variant_sequences vs variant_sequence
        variants_raw = variant_sequences or variant_sequence or kwargs.get("variants") or []
        variants = _parse_list_input(variants_raw)

        ref = reference_sequence or kwargs.get("reference") or kwargs.get("ref_seq") or ""

        # If query/accession/url provided and no ref, try to fetch ref
        if not ref and any([query, url, identifier, accession]):
            fetch_res = _fetch_via_subbots(query=query, url=url, identifier=identifier, accession=accession, **kwargs)
            fetched_text = fetch_res.get("scrape") or fetch_res.get("search") if isinstance(fetch_res, dict) and not fetch_res.get("fallback") else None
            dna_candidate = _extract_dna_from_text(str(fetched_text)) if fetched_text else None
            # _fetch_via_subbots already attempted NCBI efetch internally; no duplicate fallback needed
            if dna_candidate:
                ref = dna_candidate
                notes = ["Fetched reference via web_crawler/NCBI: %d bp" % len(ref)]
            else:
                # Still no ref, error
                return (
                    "FETCH AND SCORE - FAILED\n"
                    "Could not fetch reference sequence.\n"
                    "Fetch result: %s\n"
                    "Provide reference_sequence directly or valid accession.\n"
                    "Example: run(action='fetch_and_score', accession='NM_007294.3', variant_sequence='ATGCGTACGA')" % str(fetch_res)[:600]
                )
        elif not ref and not variants:
            # Try to handle case where query is actually sequence and variant is in kwargs
            return "ERROR: fetch_and_score requires reference_sequence and variant_sequence (or variant_sequences), or query/accession to fetch reference."

        # If ref still missing but we have variants and query was meant as ref, use query cleaning
        if not ref and query and _clean_dna(str(query)):
            ref = _clean_dna(str(query))

        if not ref:
            return "ERROR: No reference sequence available after fetch. Provide reference_sequence='ATGC...'"

        # If only single variant in variants list, use score; if multiple, batch
        layer = kwargs.get("layer", layer)
        model = kwargs.get("model", model)
        api_key = kwargs.get("api_key", api_key)

        if len(variants) == 0:
            # Check if variant_sequence passed as kwarg singular but we missed
            vs = kwargs.get("variant_sequence") or kwargs.get("variant") or ""
            if vs:
                variants = [vs]
            else:
                return "ERROR: No variant_sequence provided. Pass variant_sequence='ATGC...' or variant_sequences=[...]"

        # If one variant, single score; else batch
        if len(variants) == 1:
            single_res = _score_variants(reference_sequence=ref, variant_sequence=variants[0], layer=layer, model=model, api_key=api_key)
            header = [
                "FETCH AND SCORE - SINGLE",
                "=" * 60,
                "Reference length: %d bp (preview %s...)" % (len(ref), ref[:30]),
                "Variant length: %d bp (preview %s...)" % (len(variants[0]), variants[0][:30]),
                "Layer: %s | Model: %s" % (layer, model),
                "-" * 60,
                single_res,
                "-" * 60,
                "STRUCTURED PREVIEW:",
                json.dumps({"reference_length": len(ref), "variant_length": len(variants[0]), "layer": layer, "fetched": bool(query or accession or url)}, indent=2),
            ]
            return "\n".join(header)
        else:
            # Batch scoring via ThreadPoolExecutor
            batch_res = _batch_score(reference_sequence=ref, variant_sequences=variants, layer=layer, model=model, api_key=api_key)
            header = [
                "FETCH AND SCORE - BATCH (via _batch_score)",
                "=" * 60,
                "Fetched reference: %d bp" % len(ref),
                "Variants: %d" % len(variants),
            ]
            full2 = "\n".join(header) + "\n" + batch_res
        try:
            _store_result_memory_gracefully(full2[:4000], key_prefix="fetch_and_score")
        except Exception:
            pass
        return full2

    except Exception as e:
        return "ERROR: fetch_and_score failed: %s" % str(e)


# ---------------------------------------------------------------------------
# Existing Evo2 functions (preserved with enhanced error handling)
# ---------------------------------------------------------------------------

def _generate(sequence, num_tokens=100, temperature=1.0, top_k=4,
              enable_sampled_probs=True, model="evo2-40b", api_key=None, **kwargs):
    """Generate DNA sequences using Evo2 via NVIDIA NIM API."""
    try:
        config = _get_config(api_key)
        err = _check_key(config)
        if err:
            return err

        if not sequence:
            return "ERROR: No sequence provided. Pass sequence='ACTG...' as DNA prompt."

        headers = {
            "Authorization": "Bearer %s" % config["api_key"],
            "Content-Type": "application/json",
        }

        payload = {
            "sequence": sequence,
            "num_tokens": num_tokens,
            "top_k": top_k,
            "enable_sampled_probs": enable_sampled_probs,
        }

        try:
            resp = requests.post(
                config["generate_url"],
                headers=headers,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")

            if "application/json" in content_type:
                data = resp.json()
                generated = data.get("sequence", data.get("generated_sequence", str(data)))

                lines = [
                    "EVO2 DNA SEQUENCE GENERATION",
                    "=" * 50,
                    "Model: %s" % model,
                    "Prompt: %s" % sequence[:60],
                    "Tokens requested: %d" % num_tokens,
                    "Temperature: %.2f" % temperature,
                    "Top-K: %d" % top_k,
                    "-" * 50,
                    "Generated sequence:",
                    generated[:500] if isinstance(generated, str) else str(generated)[:500],
                ]
                if isinstance(generated, str) and len(generated) > 500:
                    lines.append("... (truncated, total length: %d bp)" % len(generated))
                return "\n".join(lines)

            elif "application/zip" in content_type:
                # Large response saved as zip
                out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "dna_lab")
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "evo2_output.zip")
                with open(out_path, "wb") as f:
                    f.write(resp.content)
                return "Evo2 output saved to: %s (%d bytes)" % (out_path, len(resp.content))

            else:
                return "Evo2 response: %s" % resp.text[:500]

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return "ERROR: Invalid NVIDIA API key. Check NVIDIA_API_KEY."
            return "ERROR: Evo2 generate HTTP error: %s" % str(e)
        except Exception as e:
            return "ERROR: Evo2 generate failed: %s" % str(e)
    except Exception as e:
        return "ERROR: _generate wrapper failed: %s" % str(e)


_SCORE_LAYER = "blocks.28"  # raw residual-stream embedding; discriminative for variants
_EMBED_LAYER = "blocks.28"  # default embedding layer (raw residual stream carries signal)


def _npz_embeddings(raw_bytes, layer):
    """Decode a base64 NPZ forward response into a 2D [seq_len, dim] numpy array."""
    try:
        if np is None:
            raise RuntimeError("numpy is required for embedding decoding. Run: pip install numpy")

        npz = np.load(io.BytesIO(base64.b64decode(raw_bytes)), allow_pickle=True)
        key = layer + ".output"
        if key not in npz:
            key = list(npz.keys())[0]
        arr = npz[key]
        # NIM returns [batch, seq_len, dim]; squeeze batch.
        if arr.ndim == 3:
            arr = arr[0]
        return arr
    except Exception as e:
        raise RuntimeError("NPZ decode failed for layer %s: %s" % (layer, str(e)))


def _score_variants(reference_sequence, variant_sequence, layer=_SCORE_LAYER,
                    model="evo2-40b", api_key=None, **kwargs):
    """Score DNA variants using Evo2 embedding distance (zero-shot proxy).

    The hosted NIM forward endpoint exposes intermediate embeddings rather than
    raw logits. Variant impact is estimated as the embedding change between the
    reference and variant sequences at a mid-network residual-stream layer
    (blocks.28, the raw layer output before the final norm):

      - Low embedding distance  -> the model "sees" the variant as benign
      - High embedding distance -> the variant strongly rewrites the learned
                                   representation (candidate pathogenic / disruptive)

    This mirrors embedding-based variant-effect pipelines (e.g. Evo2/exon
    classifier embeddings). For a full log-likelihood-ratio BRCA1-style analysis,
    the standard Evo2 scoring notebook runs the model locally on a GPU.
    """
    try:
        config = _get_config(api_key)
        err = _check_key(config)
        if err:
            return err

        if not reference_sequence or not variant_sequence:
            return "ERROR: Both reference_sequence and variant_sequence are required."

        headers = {
            "Authorization": "Bearer %s" % config["api_key"],
            "Content-Type": "application/json",
        }

        def _embed(seq):
            payload = {"sequence": seq, "output_layers": [layer]}
            resp = requests.post(config["forward_url"], headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            if "data" not in data:
                raise RuntimeError("Unexpected forward response: %s" % str(data)[:200])
            return _npz_embeddings(data["data"], layer)

        try:
            ref_emb = _embed(reference_sequence)
            var_emb = _embed(variant_sequence)

            import numpy as np

            n = min(ref_emb.shape[0], var_emb.shape[0])
            if n == 0:
                return "ERROR: Empty embeddings returned."

            ref_emb, var_emb = ref_emb[:n], var_emb[:n]

            # Euclidean distance over aligned positions (raw embeddings).
            euclid = float(np.linalg.norm(ref_emb - var_emb, axis=1).mean())

            # Cosine similarity on unit-normalized rows (robust to layer-norm scale).
            def _unit_rows(x):
                norms = np.linalg.norm(x, axis=1, keepdims=True)
                return x / np.where(norms > 0, norms, 1.0)

            cos_sim = float((_unit_rows(ref_emb) * _unit_rows(var_emb)).sum(axis=1).mean())

            # Simple heuristic thresholds on mean cosine distance (1 - cos_sim).
            cos_dist = 1.0 - cos_sim

            lines = [
                "EVO2 VARIANT SCORING (Embedding-Based, Zero-Shot)",
                "=" * 50,
                "Model: %s" % model,
                "Embedding layer: %s" % layer,
                "Reference length: %d bp" % len(reference_sequence),
                "Variant length: %d bp" % len(variant_sequence),
                "Aligned positions: %d" % n,
                "-" * 50,
                "Mean Euclidean distance: %.4f" % euclid,
                "Mean cosine similarity: %.4f" % cos_sim,
                "Mean cosine distance:    %.4f" % cos_dist,
                "Interpretation (cosine distance):",
            ]

            if cos_dist > 0.15:
                lines.append("  -> HIGH impact (large representation change; candidate disruptive)")
            elif cos_dist > 0.05:
                lines.append("  -> MODERATE impact")
            else:
                lines.append("  -> LOW impact (near-identical representation; candidate benign)")

            lines.append("")
            lines.append("NOTE: embedding-distance score is a proxy; for log-likelihood")
            lines.append("ratios run the Evo2 BRCA1 scoring notebook on a GPU.")

            return "\n".join(lines)

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return "ERROR: Invalid NVIDIA API key. Check NVIDIA_API_KEY."
            return "ERROR: Evo2 score HTTP error: %s" % str(e)
        except Exception as e:
            return "ERROR: Evo2 score failed: %s" % str(e)
    except Exception as e:
        return "ERROR: _score_variants wrapper failed: %s" % str(e)


def _embeddings(sequence, layer_name=_EMBED_LAYER, model="evo2-40b", api_key=None, **kwargs):
    """Get Evo2 embeddings for a DNA sequence at a specific layer.

    Embeddings can be used for:
    - Exon/intron classification
    - Promoter region prediction
    - Gene essentiality prediction
    - Sequence similarity analysis
    - Custom downstream ML models
    """
    try:
        config = _get_config(api_key)
        err = _check_key(config)
        if err:
            return err

        if not sequence:
            return "ERROR: No sequence provided. Pass sequence='ATCG...'"

        headers = {
            "Authorization": "Bearer %s" % config["api_key"],
            "Content-Type": "application/json",
        }

        payload = {
            "sequence": sequence,
            "output_layers": [layer_name],
        }

        try:
            resp = requests.post(
                config["forward_url"],
                headers=headers,
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            lines = [
                "EVO2 EMBEDDINGS",
                "=" * 50,
                "Model: %s" % model,
                "Layer: %s" % layer_name,
                "Sequence length: %d bp" % len(sequence),
                "-" * 50,
            ]

            if "data" in data:
                emb = _npz_embeddings(data["data"], layer_name)
                if hasattr(emb, "shape"):
                    lines.append("Embeddings shape: [%d, %d]" % (emb.shape[0], emb.shape[1]))
                    lines.append("Position 0 (first 5): %s" % str([round(float(x), 4) for x in emb[0][:5]]))
                    lines.append("Norm (mean): %.4f" % float(np.linalg.norm(emb, axis=1).mean()))
            else:
                lines.append("Response keys: %s" % str(list(data.keys())))
                lines.append("Raw output preview: %s" % str(data)[:300])

            lines.append("")
            lines.append("Use these embeddings for:")
            lines.append("  - Exon/intron classification")
            lines.append("  - Promoter region prediction")
            lines.append("  - Gene essentiality prediction")
            lines.append("  - Sequence similarity analysis")
            lines.append("  - Custom downstream ML models")

            return "\n".join(lines)

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return "ERROR: Invalid NVIDIA API key. Check NVIDIA_API_KEY."
            return "ERROR: Evo2 embeddings HTTP error: %s" % str(e)
        except Exception as e:
            return "ERROR: Evo2 embeddings failed: %s" % str(e)
    except Exception as e:
        return "ERROR: _embeddings wrapper failed: %s" % str(e)


def _forward(sequence, model="evo2-40b", api_key=None, layer_name=_EMBED_LAYER, **kwargs):
    """Run Evo2 forward pass on a DNA sequence to get layer embeddings.

    The hosted NIM forward endpoint returns selected layer activations as a
    base64 NPZ payload. By default this returns the raw residual-stream
    embedding at blocks.28 (mid-network, carries strong sequence signal).
    """
    try:
        config = _get_config(api_key)
        err = _check_key(config)
        if err:
            return err

        if not sequence:
            return "ERROR: No sequence provided. Pass sequence='ATCG...'"

        headers = {
            "Authorization": "Bearer %s" % config["api_key"],
            "Content-Type": "application/json",
        }

        payload = {
            "sequence": sequence,
            "output_layers": [layer_name],
        }

        try:
            resp = requests.post(
                config["forward_url"],
                headers=headers,
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()

            lines = [
                "EVO2 FORWARD PASS",
                "=" * 50,
                "Model: %s" % model,
                "Sequence length: %d bp" % len(sequence),
                "Requested layer: %s" % layer_name,
                "-" * 50,
            ]

            if "data" in data:
                emb = _npz_embeddings(data["data"], layer_name)
                lines.append("Layer activations shape: [%d, %d]" % (emb.shape[0], emb.shape[1]))
                lines.append("Position 0 (first 5): %s" % str([round(float(x), 4) for x in emb[0][:5]]))
                lines.append("Elapsed (server): %d ms" % data.get("elapsed_ms", -1))
            else:
                lines.append("Response keys: %s" % str(list(data.keys())))
                lines.append("Raw output preview: %s" % str(data)[:300])

            return "\n".join(lines)

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                return "ERROR: Invalid NVIDIA API key. Check NVIDIA_API_KEY."
            return "ERROR: Evo2 forward HTTP error: %s" % str(e)
        except Exception as e:
            return "ERROR: Evo2 forward failed: %s" % str(e)
    except Exception as e:
        return "ERROR: _forward wrapper failed: %s" % str(e)


def _analyze_sequence(sequence, k=3, **kwargs):
    """Analyze DNA sequence composition (GC content, k-mer frequency, etc.)."""
    try:
        if not sequence:
            return "ERROR: No sequence provided. Pass sequence='ATCG...'"

        seq = _clean_dna(sequence)
        if not seq:
            return "ERROR: No valid DNA characters found. Use A, C, G, T only."
        length = len(seq)

        # Base counts
        counts = {base: seq.count(base) for base in "ACGT"}
        gc_content = (counts["G"] + counts["C"]) / length * 100 if length > 0 else 0

        # K-mer frequency via helper (single source; no manual fallback loop)
        kmer_counts = _kmer_counts(seq, k=k)

        # Sort by frequency
        sorted_kmers = sorted(kmer_counts.items(), key=lambda x: x[1], reverse=True)

        lines = [
            "DNA SEQUENCE ANALYSIS",
            "=" * 50,
            "Sequence length: %d bp" % length,
            "",
            "BASE COMPOSITION",
            "-" * 50,
            "  A: %d (%.1f%%)" % (counts["A"], counts["A"] / length * 100),
            "  C: %d (%.1f%%)" % (counts["C"], counts["C"] / length * 100),
            "  G: %d (%.1f%%)" % (counts["G"], counts["G"] / length * 100),
            "  T: %d (%.1f%%)" % (counts["T"], counts["T"] / length * 100),
            "",
            "GC Content: %.1f%%" % gc_content,
            "AT/GC Ratio: %.2f" % ((counts["A"] + counts["T"]) / (counts["G"] + counts["C"])) if (counts["G"] + counts["C"]) > 0 else "N/A",
            "",
            "TOP %d-MERS" % k,
            "-" * 50,
        ]

        for kmer, count in sorted_kmers[:10]:
            lines.append("  %s: %d (%.1f%%)" % (kmer, count, count / length * 100))

        # Codon analysis (if length >= 3)
        if length >= 3:
            codons = [seq[i:i+3] for i in range(0, len(seq) - 2, 3)]
            lines.append("")
            lines.append("CODON ANALYSIS")
            lines.append("-" * 50)
            lines.append("  Total codons: %d" % len(codons))
            lines.append("  First 5 codons: %s" % ", ".join(codons[:5]))

            # Start codon check
            if codons and codons[0] == "ATG":
                lines.append("  Start codon (ATG): YES")
            else:
                lines.append("  Start codon (ATG): NO")

            # Stop codon check
            stop_codons = {"TAA", "TAG", "TGA"}
            stop_positions = [i+1 for i, c in enumerate(codons) if c in stop_codons]
            if stop_positions:
                lines.append("  Stop codons at positions: %s" % str(stop_positions[:5]))
            else:
                lines.append("  Stop codons: None found")

        lines.append("")
        lines.append("Sequence preview (first 60 bp):")
        lines.append("  %s" % seq[:60])

        # Add validation hint from _validate_sequence
        try:
            val = _validate_sequence(seq)
            if val.get("warnings"):
                lines.append("")
                lines.append("Validation warnings: %s" % "; ".join(val["warnings"][:2]))
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return "ERROR: _analyze_sequence failed: %s" % str(e)

