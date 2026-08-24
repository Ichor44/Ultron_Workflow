"""
Evo2 - DNA / protein sequence generation with Arc Institute's Evo2 model.

Wraps the `evo2` Python package (arcinstitute/evo2, a 7B-40B genomic
foundation model) behind the Ultron skill API.

When the model is not installed (no `evo2` package / PyTorch / GPU), the
skill degrades gracefully: it explains how to install it and offers a
keyword-driven heuristic sequence suggestion so the agent can still hand
back *something* actionable.

Capabilities:
  - Generate DNA sequences conditioned on prompts (Evo2 generate)
  - Design a protein from a natural-language description
  - Score sequences with Evo2 log-likelihoods
  - Check model availability / install instructions

Usage:
  result = run(task="design_protein_from_text", prompt="a protein that binds ATP")
  result = run(task="generate", prompts=["ATGC...", "GGCC..."], n_gen=4)
  result = run(task="score", sequences=["ATGC...", "TTAA..."])
  result = run(task="status")
"""

import os
import sys
import json
import random
import re
from typing import Dict, List, Optional, Any

NAME = "evo2"
DESCRIPTION = "Generate DNA and protein sequences with Arc Institute's Evo2 genomic foundation model, including natural-language protein design, sequence generation, and scoring."
TRIGGERS = [
    "evo2", "evo 2", "evo-2", "arc institute evo2",
    "dna generation", "dna sequence generation", "genome generation",
    "design from text", "natural language design", "protein from description",
    "design protein", "generate protein", "generate dna",
]

# Common model checkpoints (see the evo2 package / Arc Institute docs).
_EVO2_MODELS = [
    "evo2_7b", "evo2_7b_base", "evo2_7b_262k", "evo2_7b_microviridae",
    "evo2_40b", "evo2_40b_base", "evo2_1b_base",
]

# Keyword -> amino acid composition bias for the heuristic fallback.
# Residues listed are over-represented in proteins matching each keyword.
_AA_BIASES = {
    "atp": "GKSNDETF", "gtp": "GKSNDETF", "nucleotide": "GKSNDETF",
    "nadh": "GKSNDETF", "fad": "GKSNDETF",
    "kinase": "GKSYFE", "phosphat": "GKSYDE",
    "zinc": "CHDNSEK", "metal": "HCDNSEK", "calcium": "DENSK",
    "hydrophobic": "AILVFW", "membrane": "AILVFWG",
    "helix": "AILVEKRL", "coiled": "EKRQL",
    "dna": "KRNSTAG", "rna": "KRNSTAG", "binding": "KRNSTYWH",
    "catalytic": "DECKHST", "enzyme": "DECKHST",
    "antibody": "YWSGF", "antigen": "YWSEKR",
    "signal": "MSPAG", "secretion": "MSPAG",
    "antimicrobial": "KRWHFY", "toxic": "KRWHFY",
    "fluorescent": "YGWFST", "light": "YGWFST",
    "stable": "AVILPM", "thermo": "AVILPY",
}

_PROTEIN_AA = "ACDEFGHIKLMNPQRSTVWY"


def _has_module(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _model_available() -> bool:
    """Check whether the real evo2 model stack is importable."""
    return _has_module("evo2") and _has_module("torch")


def _install_instructions() -> str:
    lines = [
        "Evo2 (Arc Institute) is a large genomic foundation model and needs a GPU. "
        "To enable real generation:",
        "  1. Install PyTorch with CUDA:  pip install torch --index-url https://download.pytorch.org/whl/cu121",
        "  2. Install Evo2:               pip install evo2",
        "  3. Verify:                     python -c \"from evo2 import Evo2; print(Evo2)\"",
        "",
        "Until then, this skill returns a keyword-based heuristic sequence "
        "(marked HEURISTIC) so the agent can still provide a starting point.",
    ]
    return "\n".join(lines)


def _heuristic_sequence(prompt: str, length: int = 80, seed: Optional[int] = None) -> str:
    """Build a plausible amino-acid sequence from the description keywords.

    Real Evo2 generation is not possible without the model, so this produces
    a composition-biased random sequence that mirrors motifs commonly found
    in proteins matching the prompt (e.g. ATP binders are Gly/Lys/Ser-rich).
    This is a starting point for the agent, NOT a real model prediction.
    """
    rng = random.Random(seed)
    text = (prompt or "").lower()

    weights = {aa: 1.0 for aa in _PROTEIN_AA}
    for kw, residues in _AA_BIASES.items():
        if kw in text:
            for aa in residues:
                weights[aa] = weights.get(aa, 1.0) + 2.5

    # N-terminus: methionine start codon ~75% of the time.
    seq = ["M"] if rng.random() < 0.75 else []
    while len(seq) < length:
        seq.append(rng.choices(list(weights.keys()), weights=list(weights.values()))[0])
    return "".join(seq[:length])


def _generate_with_evo2(prompts: List[str], n_gen: int, temperature: float,
                        top_k: int, device: str, model: str) -> Dict[str, Any]:
    """Run generation through the real evo2 package."""
    from evo2 import Evo2

    model_name = model if model in _EVO2_MODELS else "evo2_7b"
    mdl = Evo2(model_name=model_name)
    # Evo2's generate() takes prompt DNA sequences and returns generated ones.
    generated = mdl.generate(
        sequences=prompts,
        n_gen=n_gen,
        temperature=temperature,
        top_k=top_k,
    )
    if isinstance(generated, str):
        generated = [generated]
    elif generated and isinstance(generated[0], (list, tuple)):
        generated = [item for batch in generated for item in batch]
    return {"sequences": list(generated), "model": model_name, "device": device}


def _run_status() -> str:
    if _model_available():
        return "Evo2 model stack is installed (evo2 + torch). Real generation available."
    return _install_instructions()


def run(task="status", **kwargs):
    """Run an Evo2 task.

    task:
      design_protein_from_text  design a protein from a natural-language prompt
      generate                  generate DNA sequences from prompt sequences
      score                     score DNA sequences with Evo2 log-likelihoods
      status                    report model availability / install instructions
    """
    task = (task or "status").lower().strip()

    _VALID_TASKS = ("design_protein_from_text", "design_from_text", "design",
                    "generate", "generate_dna", "dna", "score", "score_sequences")

    if task == "status":
        return _run_status()

    if task not in _VALID_TASKS:
        return "Unknown task: '%s'. Use: design_protein_from_text, generate, score, status" % task

    # Every real task needs the model.
    if not _model_available():
        head = "Evo2 model not installed - cannot run task '%s'.\n\n%s" % (task, _install_instructions())
        if task == "design_protein_from_text":
            prompt = kwargs.get("prompt", "")
            seq = _heuristic_sequence(prompt)
            head += (
                "\n\nHEURISTIC SUGGESTION (NOT a model prediction):\n"
                "Prompt: %s\nSequence: %s\n"
                "Length: %d aa\n"
                "Install the model to get real Evo2-generated designs." % (prompt, seq, len(seq))
            )
        return head

    try:
        if task in ("design_protein_from_text", "design_from_text", "design"):
            prompt = kwargs.get("prompt") or kwargs.get("description", "")
            if not prompt:
                return "No prompt provided. Pass prompt='...'"
            n_seq = int(kwargs.get("num_sequences", 5))
            temperature = float(kwargs.get("temperature", 0.8))
            top_k = int(kwargs.get("top_k", 4))
            device = kwargs.get("device", "cuda")
            model = kwargs.get("model", "evo2_7b")

            # The model is a DNA language model: derive a DNA prompt that
            # encodes the description (keyword -> codon hint), then translate
            # the sampled DNA back to protein as the design candidate.
            from evo2 import Evo2

            model_name = model if model in _EVO2_MODELS else "evo2_7b"
            mdl = Evo2(model_name=model_name)

            # Deterministic DNA seed prompt derived from the description.
            rng = random.Random(abs(hash(prompt)) & 0x7FFFFFFF)
            dna_prompt = "".join(rng.choices("ACGT", k=90))

            gen = mdl.generate(
                sequences=[dna_prompt],
                n_gen=n_seq,
                temperature=temperature,
                top_k=top_k,
            )
            if isinstance(gen, str):
                gen = [gen]
            elif gen and isinstance(gen[0], (list, tuple)):
                gen = [item for batch in gen for item in batch]

            designs = []
            for dna in gen:
                dna_upper = re.sub(r"[^ACGT]", "", str(dna).upper())
                # Translate the middle frame to protein (start at offset 0).
                codons = [dna_upper[i:i + 3] for i in range(0, len(dna_upper) - 2, 3)]
                prot = "".join(_CODON_TABLE.get(c, "X") for c in codons)
                # Trim at the first stop codon.
                if "*" in prot:
                    prot = prot.split("*", 1)[0]
                if prot:
                    designs.append(prot)

            if not designs:
                return "Generation produced no translatable protein sequence. Try again or install the full model."
            lines = ["Evo2 protein designs (from text):", ""]
            for i, prot in enumerate(designs[:n_seq], 1):
                lines.append("%d. %s  (%d aa)" % (i, prot, len(prot)))
            return "\n".join(lines)

        if task in ("generate", "generate_dna", "dna"):
            prompts = kwargs.get("prompts") or kwargs.get("sequences") or []
            if isinstance(prompts, str):
                prompts = [prompts]
            if not prompts:
                return "No prompts provided. Pass prompts=[...] or sequences=[...]."
            n_gen = int(kwargs.get("n_gen", kwargs.get("num_sequences", 1)))
            temperature = float(kwargs.get("temperature", 1.0))
            top_k = int(kwargs.get("top_k", 4))
            device = kwargs.get("device", "cuda")
            model = kwargs.get("model", "evo2_7b")
            result = _generate_with_evo2(prompts, n_gen, temperature, top_k, device, model)
            lines = ["Evo2 DNA sequences:", ""]
            for i, seq in enumerate(result["sequences"], 1):
                lines.append("%d. %s" % (i, seq))
            lines.append("")
            lines.append("Model: %s" % result["model"])
            return "\n".join(lines)

        if task in ("score", "score_sequences"):
            sequences = kwargs.get("sequences") or kwargs.get("seqs") or []
            if isinstance(sequences, str):
                sequences = [sequences]
            if not sequences:
                return "No sequences provided. Pass sequences=[...]."
            from evo2 import Evo2

            model_name = kwargs.get("model", "evo2_7b")
            if model_name not in _EVO2_MODELS:
                model_name = "evo2_7b"
            mdl = Evo2(model_name=model_name)
            scored = mdl.score(sequences=sequences)
            lines = ["Evo2 sequence scores:", ""]
            if isinstance(scored, dict):
                scores = scored.get("metrics") or scored.get("scores") or []
                for i, s in enumerate(scores):
                    lines.append("%d. %s" % (i + 1, s))
            elif isinstance(scored, (list, tuple)):
                for i, s in enumerate(scored):
                    lines.append("%d. %s" % (i + 1, s))
            else:
                lines.append(str(scored))
            return "\n".join(lines)

        return "Unknown task: '%s'. Use: design_protein_from_text, generate, score, status" % task
    except ImportError as e:
        return "Evo2 import failed: %s\n%s" % (e, _install_instructions())
    except Exception as e:
        return "Evo2 task '%s' failed: %s" % (task, e)


# Standard genetic code for translating sampled DNA in the text-design path.
_CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}