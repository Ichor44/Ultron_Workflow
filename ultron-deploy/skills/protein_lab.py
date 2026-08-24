"""
Protein Lab - Comprehensive protein analysis and design toolkit.

A unified interface for protein sequence analysis, structure prediction,
visualization, and design. Combines multiple bioinformatics tools into
a single, easy-to-use skill for Ultron.

Capabilities:
  - Protein sequence analysis (composition, properties, motifs)
  - Structure prediction via Boltz-2 (folding, docking, affinity)
  - Sequence alignment and similarity search
  - FASTA file parsing and manipulation
  - Protein structure visualization (3Dmol, PyMOL)
  - Secondary structure prediction
  - Molecular weight and physicochemical calculations
  - Protein design and optimization suggestions
   - Natural language protein design ("Design a protein that binds ATP")
   - Mutation reporting, hydrophobicity profiles, batch FASTA analysis
   - PDB structure statistics and host-specific codon optimization
   - Automatic resource fetching via Firecrawl (structures, papers, databases)
   - Structure download and analysis from PDB, AlphaFold, RCSB

Usage:
  result = run(action="analyze", sequence="MKTLYF...")
  result = run(action="fold", sequence="MKTLYF...")
  result = run(action="visualize", pdb_file="output.pdb")
  result = run(action="natural_language", prompt="Design a protein that binds ATP")
  result = run(action="natural_language", prompt="Download and analyze the structure of insulin")
"""

import os
import sys
import json
import re
import requests
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass

# Biotite integration (optional - falls back gracefully if not installed)
try:
    import biotite
    import biotite.sequence
    import biotite.sequence.io as seq_io
    import biotite.sequence.fasta as fasta_io
    import biotite.sequence.io.pdb as pdb_io
    import biotite.structure as struct
    BIOTITE_AVAILABLE = True
except ImportError:
    BIOTITE_AVAILABLE = False

NAME = "protein_lab"
DESCRIPTION = "Comprehensive protein analysis and design toolkit: sequence analysis, structure prediction, visualization, alignment, design optimization, natural language design, structure download, and web research."
TRIGGERS = [
    "protein", "protein lab", "protein analysis", "protein design",
    "protein structure", "fold protein", "protein folding",
    "amino acid", "sequence analysis", "sequence alignment",
    "pdb file", "molecular weight", "protein properties",
    "protein motif", "binding site", "active site",
    "docking", "binding affinity", "protein-ligand",
    "fasta", "fasta file", "protein sequence",
    "design protein", "optimize protein", "mutate protein",
    "evo2", "evo 2", "evo-2", "arc institute evo2",
    "dna generation", "dna sequence generation", "genome generation",
    "design from text", "natural language design", "protein from description",
    "download structure", "download pdb", "fetch structure",
    "search structure", "find structure", "pdb search",
    "research protein", "protein literature", "protein paper",
    "design a protein", "create a protein", "make a protein",
    "optimize inducer", "inducer optimization", "improve ligand",
    "optimize ligand", "agonist design", "lead optimization",
    "download and analyze", "get structure", "find structures",
    "search for structures",
]

# Amino acid properties
AMINO_ACIDS = {
    'A': {'name': 'Alanine', 'mw': 89.09, 'category': 'nonpolar', 'hydrophobic': True},
    'R': {'name': 'Arginine', 'mw': 174.20, 'category': 'positive', 'hydrophobic': False},
    'N': {'name': 'Asparagine', 'mw': 132.12, 'category': 'polar', 'hydrophobic': False},
    'D': {'name': 'Aspartic Acid', 'mw': 133.10, 'category': 'negative', 'hydrophobic': False},
    'C': {'name': 'Cysteine', 'mw': 121.16, 'category': 'polar', 'hydrophobic': False},
    'E': {'name': 'Glutamic Acid', 'mw': 147.13, 'category': 'negative', 'hydrophobic': False},
    'Q': {'name': 'Glutamine', 'mw': 146.15, 'category': 'polar', 'hydrophobic': False},
    'G': {'name': 'Glycine', 'mw': 75.03, 'category': 'nonpolar', 'hydrophobic': True},
    'H': {'name': 'Histidine', 'mw': 155.16, 'category': 'positive', 'hydrophobic': False},
    'I': {'name': 'Isoleucine', 'mw': 131.17, 'category': 'nonpolar', 'hydrophobic': True},
    'L': {'name': 'Leucine', 'mw': 131.17, 'category': 'nonpolar', 'hydrophobic': True},
    'K': {'name': 'Lysine', 'mw': 146.19, 'category': 'positive', 'hydrophobic': False},
    'M': {'name': 'Methionine', 'mw': 149.21, 'category': 'nonpolar', 'hydrophobic': True},
    'F': {'name': 'Phenylalanine', 'mw': 165.19, 'category': 'nonpolar', 'hydrophobic': True},
    'P': {'name': 'Proline', 'mw': 115.13, 'category': 'nonpolar', 'hydrophobic': True},
    'S': {'name': 'Serine', 'mw': 105.09, 'category': 'polar', 'hydrophobic': False},
    'T': {'name': 'Threonine', 'mw': 119.12, 'category': 'polar', 'hydrophobic': False},
    'W': {'name': 'Tryptophan', 'mw': 204.23, 'category': 'nonpolar', 'hydrophobic': True},
    'Y': {'name': 'Tyrosine', 'mw': 181.19, 'category': 'polar', 'hydrophobic': False},
    'V': {'name': 'Valine', 'mw': 117.15, 'category': 'nonpolar', 'hydrophobic': True},
    'X': {'name': 'Unknown', 'mw': 0.0, 'category': 'unknown', 'hydrophobic': False},
    'U': {'name': 'Selenocysteine', 'mw': 168.06, 'category': 'polar', 'hydrophobic': False},
    'B': {'name': 'Asx', 'mw': 132.61, 'category': 'polar', 'hydrophobic': False},
    'Z': {'name': 'Glx', 'mw': 146.64, 'category': 'polar', 'hydrophobic': False},
    'J': {'name': 'Leucine/Isoleucine', 'mw': 131.17, 'category': 'nonpolar', 'hydrophobic': True},
}

# Kyte-Doolittle hydropathy scale (shared across analyses)
KD_HYDROPATHY = {
    'A': 1.8, 'R': -4.5, 'N': -3.5, 'D': -3.5, 'C': 2.5,
    'Q': -3.5, 'E': -3.5, 'G': -0.4, 'H': -3.2, 'I': 4.5,
    'L': 3.8, 'K': -3.9, 'M': 1.9, 'F': 2.8, 'P': -1.6,
    'S': -0.8, 'T': -0.7, 'W': -0.9, 'Y': -1.3, 'V': 4.2,
}

# Approximate codon usage tables (DNA letters, T not U).
# Each amino acid maps to an ordered list of (codon, relative weight %).
# Weights are approximate and intended for simple optimization only.
CODON_USAGE_TABLES = {
    "e_coli": {
        'A': [('GCT', 40), ('GCC', 28), ('GCG', 24), ('GCA', 8)],
        'R': [('CGT', 36), ('CGC', 32), ('CGA', 12), ('CGG', 8), ('AGG', 8), ('AGA', 4)],
        'N': [('AAC', 60), ('AAT', 40)],
        'D': [('GAT', 55), ('GAC', 45)],
        'C': [('TGC', 60), ('TGT', 40)],
        'Q': [('CAG', 65), ('CAA', 35)],
        'E': [('GAA', 62), ('GAG', 38)],
        'G': [('GGC', 50), ('GGT', 30), ('GGG', 12), ('GGA', 8)],
        'H': [('CAT', 58), ('CAC', 42)],
        'I': [('ATT', 50), ('ATC', 40), ('ATA', 10)],
        'L': [('CTG', 50), ('CTT', 12), ('TTG', 12), ('CTC', 10), ('TTA', 12), ('CTA', 4)],
        'K': [('AAA', 70), ('AAG', 30)],
        'M': [('ATG', 100)],
        'F': [('TTT', 58), ('TTC', 42)],
        'P': [('CCG', 55), ('CCA', 20), ('CCT', 15), ('CCC', 10)],
        'S': [('TCT', 25), ('AGC', 20), ('TCC', 18), ('TCG', 14), ('AGT', 13), ('TCA', 10)],
        'T': [('ACC', 40), ('ACT', 25), ('ACG', 20), ('ACA', 15)],
        'W': [('TGG', 100)],
        'Y': [('TAT', 55), ('TAC', 45)],
        'V': [('GTG', 30), ('GTT', 28), ('GTC', 20), ('GTA', 12)],
    },
    "human": {
        'A': [('GCC', 40), ('GCT', 27), ('GCA', 20), ('GCG', 13)],
        'R': [('AGA', 22), ('CGT', 21), ('AGG', 21), ('CGC', 19), ('CGG', 11), ('CGA', 6)],
        'N': [('AAC', 67), ('AAT', 33)],
        'D': [('GAC', 71), ('GAT', 29)],
        'C': [('TGC', 55), ('TGT', 45)],
        'Q': [('CAG', 73), ('CAA', 27)],
        'E': [('GAG', 58), ('GAA', 42)],
        'G': [('GGC', 34), ('GGT', 25), ('GGA', 25), ('GGG', 16)],
        'H': [('CAC', 66), ('CAT', 34)],
        'I': [('ATC', 62), ('ATT', 36), ('ATA', 2)],
        'L': [('CTG', 41), ('CTC', 20), ('TTG', 13), ('CTT', 13), ('TTA', 7), ('CTA', 6)],
        'K': [('AAG', 69), ('AAA', 31)],
        'M': [('ATG', 100)],
        'F': [('TTC', 56), ('TTT', 44)],
        'P': [('CCC', 33), ('CCT', 32), ('CCA', 27), ('CCG', 8)],
        'S': [('AGC', 24), ('TCC', 21), ('TCT', 20), ('AGT', 15), ('TCA', 10), ('TCG', 10)],
        'T': [('ACC', 43), ('ACT', 24), ('ACA', 24), ('ACG', 9)],
        'W': [('TGG', 100)],
        'Y': [('TAC', 54), ('TAT', 46)],
        'V': [('GTG', 47), ('GTC', 24), ('GTT', 18), ('GTA', 11)],
    },
}

# Common motifs and patterns
COMMON_MOTIFS = {
    'N-glycosylation': 'N[^P][ST]',
    'Phosphorylation (Ser)': '[ST]..[DE]',
    'Phosphorylation (Thr)': '[ST]..[DE]',
    'Phosphorylation (Tyr)': '[ST]..[DE]',
    'Myristoylation': 'G[^EDRQPKH]..[STAGM][STAGM][STAGM]',
    'Prenylation': 'C.{5}',
    'Palmitoylation': 'C...[STAGM]',
    'Signal peptide': '^M.{15,30}[GSA]',
}


@dataclass
class ParsedIntent:
    """Parsed natural language intent for protein tasks."""
    action: str  # design, download, analyze, search, research
    target: str  # what protein/structure/topic
    parameters: Dict[str, Any]  # additional parameters
    confidence: float  # 0-1 confidence score


def _parse_natural_language(prompt: str) -> ParsedIntent:
    """
    Parse natural language prompt into structured intent.
    
    Handles prompts like:
    - "Design a protein that binds ATP"
    - "Download and analyze the structure of insulin"
    - "Search for structures of kinase proteins"
    - "Research protein folding mechanisms"
    - "Get the PDB structure for 1CRN"
    """
    prompt_lower = prompt.lower().strip()
    
    # Design intent patterns
    design_patterns = [
        r'design\s+(?:a\s+)?protein\s+(?:that\s+)?(.+)',
        r'create\s+(?:a\s+)?protein\s+(?:that\s+)?(.+)',
        r'make\s+(?:a\s+)?protein\s+(?:that\s+)?(.+)',
        r'generate\s+(?:a\s+)?protein\s+(?:that\s+)?(.+)',
        r'protein\s+design\s+(?:for\s+)?(.+)',
    ]
    
    # Download/analyze intent patterns
    download_patterns = [
        r'download\s+(?:and\s+)?(?:analyze\s+)?(?:the\s+)?structure\s+(?:of\s+)?(.+)',
        r'fetch\s+(?:and\s+)?(?:analyze\s+)?(?:the\s+)?structure\s+(?:of\s+)?(.+)',
        r'get\s+(?:the\s+)?(?:pdb\s+)?structure\s+(?:of\s+|for\s+)?(.+)',
        r'analyze\s+(?:the\s+)?structure\s+(?:of\s+)?(.+)',
        r'pdb\s+(?:structure\s+)?(?:of\s+|for\s+)?(.+)',
        r'structure\s+(?:of\s+)?(.+)',
    ]
    
    # Search intent patterns
    search_patterns = [
        r'search\s+(?:for\s+)?(?:structures?\s+)?(?:of\s+)?(.+)',
        r'find\s+(?:structures?\s+)?(?:of\s+)?(.+)',
        r'look\s+up\s+(?:structures?\s+)?(?:of\s+)?(.+)',
    ]
    
    # Research intent patterns
    research_patterns = [
        r'research\s+(?:topic\s+)?(.+)',
        r'find\s+(?:papers?\s+)?(?:about\s+)?(.+)',
        r'literature\s+(?:on\s+)?(.+)',
        r'papers?\s+(?:on\s+)?(.+)',
    ]
    
    # Inducer optimization intent (before generic design)
    optimize_patterns = [
        r'optimize\s+(?:the\s+)?(?:inducer|ligand|agonist)\s*(.*)',
        r'improve\s+(?:the\s+)?(?:inducer|ligand|agonist)\s*(.*)',
        r'(?:inducer|ligand)\s+optimization\s*(.*)',
    ]
    for pattern in optimize_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            return ParsedIntent(
                action="optimize_inducer",
                target=match.group(1).strip() or prompt,
                parameters={"prompt": prompt},
                confidence=0.92
            )

    # Check design patterns
    for pattern in design_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            target = match.group(1).strip()
            return ParsedIntent(
                action="design",
                target=target,
                parameters={"prompt": prompt},
                confidence=0.9
            )
    
    # Check download/analyze patterns
    for pattern in download_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            target = match.group(1).strip()
            # Check if it looks like a PDB ID (4 chars, alphanumeric)
            if re.match(r'^[a-z0-9]{4}$', target, re.IGNORECASE):
                return ParsedIntent(
                    action="download_pdb",
                    target=target.upper(),
                    parameters={"source": "pdb"},
                    confidence=0.95
                )
            # Check if it looks like a UniProt ID
            elif re.match(r'^[A-Z0-9]{6,10}$', target):
                return ParsedIntent(
                    action="download_alphafold",
                    target=target,
                    parameters={"source": "alphafold"},
                    confidence=0.9
                )
            else:
                return ParsedIntent(
                    action="download_and_analyze",
                    target=target,
                    parameters={},
                    confidence=0.85
                )
    
    # Check research patterns (BEFORE search to avoid "research" matching "search")
    for pattern in research_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            target = match.group(1).strip()
            return ParsedIntent(
                action="research",
                target=target,
                parameters={},
                confidence=0.85
            )
    
    # Check search patterns
    for pattern in search_patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            target = match.group(1).strip()
            return ParsedIntent(
                action="search_structures",
                target=target,
                parameters={},
                confidence=0.85
            )
    
    # Default: treat as general protein query, try to analyze as sequence
    return ParsedIntent(
        action="analyze_sequence",
        target=prompt,
        parameters={},
        confidence=0.3
    )


def _execute_web_crawler(action: str, **kwargs) -> str:
    """Execute the web_crawler (firecrawl) skill with proper error handling."""
    try:
        from core import skills
        return skills.execute_skill("web_crawler", {"action": action, **kwargs})
    except Exception as e:
        return f"Web crawler error: {str(e)}"


def _natural_language(prompt: str = None, **kwargs) -> str:
    """
    Process natural language prompts for protein tasks.
    
    Examples:
      "Design a protein that binds ATP"
      "Download and analyze the structure of insulin"
      "Search for structures of kinase proteins"
      "Research protein folding mechanisms"
      "Get the PDB structure for 1CRN"
    """
    if not prompt:
        return "No prompt provided. Pass prompt='...'"
    
    # Parse the natural language intent
    intent = _parse_natural_language(prompt)
    
    lines = []
    lines.append("NATURAL LANGUAGE PROTEIN TASK")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Original prompt: {prompt}")
    lines.append(f"Parsed intent: {intent.action}")
    lines.append(f"Target: {intent.target}")
    lines.append(f"Confidence: {intent.confidence:.0%}")
    lines.append("")
    
    # Execute based on parsed intent
    if intent.action == "design":
        # Use evo2 for protein design from text
        lines.append("Initiating protein design from text...")
        lines.append("")
        result = _design_from_text(prompt=prompt, **kwargs)
        lines.append(result)
        return "\n".join(lines)
    
    elif intent.action == "download_pdb":
        # Download PDB structure
        lines.append(f"Downloading PDB structure: {intent.target}")
        lines.append("")
        result = _download_structure(identifier=intent.target, source="pdb", **kwargs)
        lines.append(result)
        
        # Also analyze the downloaded structure if it's a PDB file
        if "saved to" in result.lower() or ".pdb" in result.lower():
            lines.append("")
            lines.append("Analyzing downloaded structure...")
            # Try to extract sequence from PDB and analyze
            # This would require parsing the PDB file
        return "\n".join(lines)
    
    elif intent.action == "download_alphafold":
        # Download AlphaFold structure
        lines.append(f"Downloading AlphaFold structure for UniProt ID: {intent.target}")
        lines.append("")
        result = _download_structure(identifier=intent.target, source="alphafold", **kwargs)
        lines.append(result)
        return "\n".join(lines)
    
    elif intent.action == "download_and_analyze":
        # Search for structure first, then download and analyze
        lines.append(f"Searching for structure of: {intent.target}")
        lines.append("")
        
        # First search for the structure
        search_result = _search_structure(query=intent.target, **kwargs)
        lines.append("SEARCH RESULTS:")
        lines.append("-" * 50)
        lines.append(search_result)
        lines.append("")
        
        # If search returns a PDB ID, try to download it
        # Try to extract PDB IDs from search results
        pdb_ids = re.findall(r'\b([0-9][A-Za-z0-9]{3})\b', search_result)
        if pdb_ids:
            lines.append(f"Found potential PDB IDs: {', '.join(pdb_ids[:3])}")
            lines.append(f"Downloading first result: {pdb_ids[0]}")
            lines.append("")
            download_result = _download_structure(identifier=pdb_ids[0], source="pdb", **kwargs)
            lines.append("DOWNLOAD RESULT:")
            lines.append("-" * 50)
            lines.append(download_result)
        else:
            lines.append("No clear PDB ID found in search results. Try specifying a PDB ID or UniProt ID directly.")
        
        return "\n".join(lines)
    
    elif intent.action == "search_structures":
        # Search for structures
        lines.append(f"Searching for structures related to: {intent.target}")
        lines.append("")
        result = _search_structure(query=intent.target, **kwargs)
        lines.append(result)
        return "\n".join(lines)
    
    elif intent.action == "research":
        # Research topic using web search
        lines.append(f"Researching topic: {intent.target}")
        lines.append("")
        result = _research_topic(topic=intent.target, **kwargs)
        lines.append(result)
        return "\n".join(lines)
    
    elif intent.action == "optimize_inducer":
        # Forward to inducer optimizer (receptor/inducer may be in kwargs)
        lines.append("Routing to inducer optimizer...")
        lines.append("")
        result = _optimize_inducer(prompt=prompt, **kwargs)
        lines.append(result)
        return "\n".join(lines)

    elif intent.action == "analyze_sequence":
        # Try to clean and analyze as a protein sequence
        seq = _clean_sequence(intent.target)
        if seq and len(seq) > 5:
            lines.append("Attempting to analyze as protein sequence...")
            lines.append("")
            result = _analyze_sequence(sequence=seq, **kwargs)
            lines.append(result)
        else:
            lines.append("Could not parse as protein sequence. Try a more specific prompt.")
            lines.append("Examples:")
            lines.append("  - 'Design a protein that binds ATP'")
            lines.append("  - 'Download and analyze the structure of insulin'")
            lines.append("  - 'Search for structures of kinase proteins'")
            lines.append("  - 'Research protein folding mechanisms'")
            lines.append("  - 'Get the PDB structure for 1CRN'")
        return "\n".join(lines)
    
    else:
        return f"Unknown intent action: {intent.action}"


def run(action="analyze", **kwargs):
    """
    Main entry point for Protein Lab.
    
    Actions:
      analyze            - Analyze protein sequence composition and properties
      fold               - Predict 3D structure using Boltz-2
      dock               - Protein-ligand docking and binding prediction
      align              - Sequence alignment and similarity search
      visualize          - Generate 3D visualization of structure
      motifs             - Search for protein motifs and patterns
      properties         - Calculate physicochemical properties
      design             - Get design suggestions for protein optimization
      design_from_text   - Design protein from natural language prompt
      download_structure - Download structure from PDB, AlphaFold, RCSB
      search_structure   - Search for structures by query
      research_topic     - Research protein topics via web
      parse_fasta        - Parse FASTA format sequences
      convert            - Convert between sequence formats
      natural_language   - Process natural language prompts (NEW)
      mutate             - Apply point mutation(s), e.g. mutation='A42V,K7R'
      hydrophobicity_profile - Sliding-window KD hydropathy ASCII profile
      batch_analyze      - Summarize multiple FASTA entries in a table
      structure_stats    - Parse PDB chains/atoms/B-factors
      codon_optimize     - Codon-optimize a protein for a host (e_coli/human)
      optimize_inducer   - Optimize an inducer (peptide or SMILES) against a
                           receptor for affinity/solubility/stability.
                           Args: receptor=, inducer=, mode='quick'|'advanced',
                                 rounds=, variants_per_round=, boltz_budget=,
                                 goals={...}, dry_run=True
      
    Natural Language Examples:
      "Design a protein that binds ATP"
      "Download and analyze the structure of insulin"
      "Search for structures of kinase proteins"
      "Research protein folding mechanisms"
      "Get the PDB structure for 1CRN"
    
    Returns a human-readable summary string.
    """
    action = action.lower().strip()
    
    handlers = {
        'analyze': _analyze_sequence,
        'analyze_with_biotite': _analyze_with_biotite,
        'design': _design_suggestions,
        'protein_to_dna': _protein_to_dna,
        'dna_to_protein': _dna_to_protein,
        'design_from_proto_language': _design_from_proto_language,
        'proto_tools_bridge': _proto_tools_bridge,
        'dock': _dock_protein,
        'fold': _fold_protein,
        'align': _align_sequences,
        'visualize': _visualize_structure,
        'motifs': _search_motifs,
        'properties': _calculate_properties,
        'download_structure': _download_structure,
        'search_structure': _search_structure,
        'research_topic': _research_topic,
        'parse_fasta': _parse_fasta,
        'convert': _convert_format,
        'clean_sequence': _clean_sequence,
        'natural_language': _natural_language,
        'mutate': _mutate,
        'hydrophobicity_profile': _hydrophobicity_profile,
        'batch_analyze': _batch_analyze,
        'structure_stats': _structure_stats,
        'codon_optimize': _codon_optimize,
        'optimize_inducer': _optimize_inducer,
        'help': _show_help,
    }
    
    handler = handlers.get(action)
    if not handler:
        return "Unknown action: '%s'. Use action='help' for available commands." % action
    
    try:
        return handler(**kwargs)
    except Exception as e:
        return "Error in %s: %s" % (action, str(e))


def _clean_sequence(sequence):
    """Clean and validate a protein sequence."""
    if not sequence:
        return None
    # Remove whitespace and headers
    seq = re.sub(r'>.*\n', '', sequence)
    seq = re.sub(r'\s+', '', seq.upper())
    # Remove any non-amino acid characters
    valid_chars = set('ACDEFGHIKLMNPQRSTVWYXUBZJ')
    seq = ''.join(c for c in seq if c in valid_chars)
    return seq if seq else None


def _analyze_sequence(sequence=None, **kwargs):
    """Analyze protein sequence composition and properties."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    length = len(seq)
    
    # Count amino acids
    counts = {}
    for aa in seq:
        counts[aa] = counts.get(aa, 0) + 1
    
    # Calculate composition
    composition = {}
    for aa, count in counts.items():
        info = AMINO_ACIDS.get(aa, {'name': 'Unknown', 'category': 'unknown'})
        composition[aa] = {
            'count': count,
            'percent': round(100 * count / length, 2),
            'name': info['name'],
            'category': info['category'],
        }
    
    # Calculate categories
    categories = {'nonpolar': 0, 'polar': 0, 'positive': 0, 'negative': 0, 'unknown': 0}
    hydrophobic_count = 0
    for aa, count in counts.items():
        info = AMINO_ACIDS.get(aa, {'category': 'unknown', 'hydrophobic': False})
        cat = info['category']
        if cat in categories:
            categories[cat] += count
        if info.get('hydrophobic'):
            hydrophobic_count += count
    
    # Calculate molecular weight
    mw = sum(counts.get(aa, 0) * info['mw'] for aa, info in AMINO_ACIDS.items() if aa != 'X')
    
    # Calculate pI (approximate)
    positive = counts.get('K', 0) + counts.get('R', 0) + counts.get('H', 0)
    negative = counts.get('D', 0) + counts.get('E', 0)
    charge = positive - negative
    
    # Find motifs
    found_motifs = []
    for name, pattern in COMMON_MOTIFS.items():
        try:
            matches = re.findall(pattern, seq)
            if matches:
                found_motifs.append((name, len(matches)))
        except re.error:
            pass
    
    # Format output
    lines = []
    lines.append("PROTEIN SEQUENCE ANALYSIS")
    lines.append("=" * 50)
    lines.append("")
    lines.append("Sequence Length: %d amino acids" % length)
    lines.append("Molecular Weight: %.2f Da (%.2f kDa)" % (mw, mw / 1000))
    lines.append("Net Charge: %+.1f" % charge)
    lines.append("Isoelectric Point (approx): %.1f" % (6.5 + charge * 0.5))
    lines.append("")
    lines.append("AMINO ACID COMPOSITION")
    lines.append("-" * 50)
    
    # Sort by frequency
    sorted_aas = sorted(composition.items(), key=lambda x: x[1]['count'], reverse=True)
    for aa, info in sorted_aas[:10]:  # Top 10
        lines.append("  %s (%s): %3d (%5.1f%%)" % (aa, info['name'][:12], info['count'], info['percent']))
    
    lines.append("")
    lines.append("CATEGORY DISTRIBUTION")
    lines.append("-" * 50)
    for cat, count in sorted(categories.items()):
        if count > 0:
            lines.append("  %-12s: %3d (%5.1f%%)" % (cat.capitalize(), count, 100 * count / length))
    
    lines.append("")
    lines.append("HYDROPHOBICITY")
    lines.append("-" * 50)
    lines.append("  Hydrophobic residues: %d (%.1f%%)" % (hydrophobic_count, 100 * hydrophobic_count / length))
    lines.append("  Hydrophilic residues: %d (%.1f%%)" % (length - hydrophobic_count, 100 * (length - hydrophobic_count) / length))
    
    if found_motifs:
        lines.append("")
        lines.append("DETECTED MOTIFS")
        lines.append("-" * 50)
        for name, count in found_motifs:
            lines.append("  %s: %d occurrence(s)" % (name, count))
    
    lines.append("")
    lines.append("SEQUENCE (first 50 aa):")
    lines.append("  %s..." % seq[:50] if length > 50 else "  %s" % seq)
    
    return "\n".join(lines)


def _analyze_with_biotite(sequence=None, **kwargs):
    """Enhanced protein sequence analysis using biotite if available."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    if not BIOTITE_AVAILABLE:
        return (
            "Biotite is not installed. Install with: pip install biotite\n"
            "Running standard Protein Lab analysis instead.\n\n"
            "-" * 40 +
            _analyze_sequence(sequence=seq, **kwargs)
        )
    
    try:
        from biotite.sequence import ProteinSequence
        from biotite.sequence.io import fasta as fasta_io
        from biotite.sequence.analysis import dipeptide_frequencies
        
        # Create biotite protein sequence object
        bio_seq = ProteinSequence(seq)
        
        # Calculate dipeptide frequencies
        dipep_freq = dipeptide_frequencies(bio_seq)
        
        # Get basic properties via biotite
        mw = sum(
            {'A': 89.09, 'R': 174.20, 'N': 132.12, 'D': 133.10, 'C': 121.16,
             'Q': 146.15, 'E': 147.13, 'G': 75.07, 'H': 155.16, 'I': 131.17,
             'L': 131.17, 'K': 146.19, 'M': 149.21, 'F': 165.19, 'P': 115.13,
             'S': 105.09, 'T': 119.12, 'W': 204.23, 'Y': 181.19, 'V': 117.15}.get(aa, 0)
            for aa in seq
        )
        # Subtract water for peptide bonds
        mw -= 18.015 * (len(seq) - 1)
        
        # Calculate charge
        positive = seq.count('K') + seq.count('R') + seq.count('H')
        negative = seq.count('D') + seq.count('E')
        charge = positive - negative
        
        # Calculate GRAVY (grand average hydropathy - Kyte-Doolittle)
        gravi = sum(KD_HYDROPATHY.get(aa, 0) for aa in seq) / len(seq)
        
        # Format output
        lines = []
        lines.append("ENHANCED PROTEIN ANALYSIS (biotite)")
        lines.append("=" * 50)
        lines.append("")
        lines.append("Sequence Length: %d amino acids" % len(seq))
        lines.append("Molecular Weight: %.2f Da" % mw)
        lines.append("Net Charge: %+.1f" % charge)
        lines.append("GRAVY (hydropathy): %.3f" % gravi)
        lines.append("")
        lines.append("AMINO ACID COMPOSITION (top 10)")
        lines.append("-" * 50)
        
        from collections import Counter
        counts = Counter(seq.upper())
        sorted_aas = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        for aa, count in sorted_aas[:10]:
            lines.append("  %s: %d (%.1f%%)" % (aa, count, count / len(seq) * 100))
        
        lines.append("")
        lines.append("DIPEPTIDE FREQUENCIES (top 10)")
        lines.append("-" * 50)
        # Sort dipeptides by frequency
        dipep_list = list(dipep_freq.items())
        dipep_list.sort(key=lambda x: x[1], reverse=True)
        for dipep, freq in dipep_list[:10]:
            lines.append("  %s: %.1f%%" % (dipep, freq / len(seq) * 100))
        
        lines.append("")
        lines.append("SEQUENCE (first 50 aa):")
        lines.append("  %s..." % seq[:50] if len(seq) > 50 else "  %s" % seq)
        
        # Append standard analysis
        standard = _analyze_sequence(sequence=seq, **kwargs)
        lines.append("")
        lines.append("STANDARD ANALYSIS:")
        lines.append("-" * 50)
        lines.append(standard)
        
        return "\n".join(lines)
        
    except Exception as e:
        return "Biotite analysis failed: %s\n\nRunning standard analysis instead:\n%s" % (str(e), _analyze_sequence(sequence=seq, **kwargs))


def _fold_protein(sequence=None, output_dir=None, **kwargs):
    """Predict 3D structure using Boltz-2."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    # Check if boltz_2 skill is available
    try:
        from skills import boltz_2
        return boltz_2.run(task="fold", protein_sequence=seq, output_dir=output_dir)
    except ImportError:
        return (
            "Boltz-2 structure prediction requires the boltz2_client package. "
            "Make sure the Boltz-2 skill is properly installed.\n"
            "You can still use other Protein Lab features like 'analyze' and 'properties'."
        )
    except Exception as e:
        return "Structure prediction failed: %s" % str(e)


def _dock_protein(protein_sequence=None, ligand_smiles=None, ligand_ccd=None,
                  predict_affinity=True, **kwargs):
    """Protein-ligand docking and binding prediction."""
    seq = _clean_sequence(protein_sequence)
    if not seq:
        return "No valid protein sequence provided. Pass protein_sequence='...'"
    
    if not ligand_smiles and not ligand_ccd:
        return "No ligand provided. Pass ligand_smiles='...' or ligand_ccd='...'"
    
    try:
        from skills import boltz_2
        return boltz_2.run(
            task="ligand",
            protein_sequence=seq,
            ligand_smiles=ligand_smiles,
            ligand_ccd=ligand_ccd,
            predict_affinity=predict_affinity,
        )
    except ImportError:
        return (
            "Protein-ligand docking requires the boltz2_client package. "
            "Make sure the Boltz-2 skill is properly installed."
        )
    except Exception as e:
        return "Docking failed: %s" % str(e)


def _align_sequences(sequence1=None, sequence2=None, **kwargs):
    """Simple sequence alignment (Needleman-Wunsch)."""
    seq1 = _clean_sequence(sequence1)
    seq2 = _clean_sequence(sequence2)
    
    if not seq1 or not seq2:
        return "Two sequences required. Pass sequence1='...' and sequence2='...'"
    
    # Simple scoring
    match_score = 2
    mismatch_penalty = -1
    gap_penalty = -2
    
    # Build scoring matrix
    m, n = len(seq1), len(seq2)
    score = [[0] * (n + 1) for _ in range(m + 1)]
    
    for i in range(1, m + 1):
        score[i][0] = i * gap_penalty
    for j in range(1, n + 1):
        score[0][j] = j * gap_penalty
    
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if seq1[i-1] == seq2[j-1]:
                diag = score[i-1][j-1] + match_score
            else:
                diag = score[i-1][j-1] + mismatch_penalty
            
            score[i][j] = max(
                diag,
                score[i-1][j] + gap_penalty,
                score[i][j-1] + gap_penalty
            )
    
    # Traceback
    align1, align2 = [], []
    i, j = m, n
    while i > 0 and j > 0:
        if seq1[i-1] == seq2[j-1]:
            align1.append(seq1[i-1])
            align2.append(seq2[j-1])
            i -= 1
            j -= 1
        elif score[i-1][j] > score[i][j-1]:
            align1.append(seq1[i-1])
            align2.append('-')
            i -= 1
        else:
            align1.append('-')
            align2.append(seq2[j-1])
            j -= 1
    
    while i > 0:
        align1.append(seq1[i-1])
        align2.append('-')
        i -= 1
    while j > 0:
        align1.append('-')
        align2.append(seq2[j-1])
        j -= 1
    
    align1.reverse()
    align2.reverse()
    
    # Calculate identity
    matches = sum(1 for a, b in zip(align1, align2) if a == b and a != '-')
    identity = 100 * matches / max(m, n)
    
    # Format output
    lines = []
    lines.append("SEQUENCE ALIGNMENT")
    lines.append("=" * 50)
    lines.append("")
    lines.append("Sequence 1: %d aa" % m)
    lines.append("Sequence 2: %d aa" % n)
    lines.append("Alignment Score: %d" % score[m][n])
    lines.append("Sequence Identity: %.1f%%" % identity)
    lines.append("")
    lines.append("ALIGNMENT")
    lines.append("-" * 50)
    
    # Show alignment in chunks
    chunk_size = 60
    for start in range(0, len(align1), chunk_size):
        end = min(start + chunk_size, len(align1))
        lines.append("Seq1  %s" % ''.join(align1[start:end]))
        lines.append("      %s" % ''.join(
            '|' if a == b and a != '-' else ' ' for a, b in zip(align1[start:end], align2[start:end])
        ))
        lines.append("Seq2  %s" % ''.join(align2[start:end]))
        lines.append("")
    
    return "\n".join(lines)


def _visualize_structure(pdb_file=None, pdb_content=None, style="cartoon",
                         color="spectrum", **kwargs):
    """Generate 3D visualization HTML using 3Dmol.js."""
    if not pdb_file and not pdb_content:
        return "Provide pdb_file (path) or pdb_content (PDB string)"
    
    if pdb_file and not pdb_content:
        with open(pdb_file, 'r') as f:
            pdb_content = f.read()
    
    # Generate HTML visualization
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Protein Structure Viewer</title>
    <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #viewer { width: 100%%; height: 500px; position: relative; }
        .controls { margin: 10px 0; }
        button { margin: 5px; padding: 8px 16px; cursor: pointer; }
    </style>
</head>
<body>
    <h2>Protein Structure Viewer</h2>
    <div class="controls">
        <button onclick="setStyle('cartoon')">Cartoon</button>
        <button onclick="setStyle('surface')">Surface</button>
        <button onclick="setStyle('stick')">Stick</button>
        <button onclick="setStyle('sphere')">Sphere</button>
        <button onclick="colorBy('spectrum')">Spectrum</button>
        <button onclick="colorBy('ss')">Secondary Structure</button>
        <button onclick="colorBy('hydrophobicity')">Hydrophobicity</button>
    </div>
    <div id="viewer"></div>
    <script>
        var pdb = %s;
        var viewer = $3Dmol.createViewer(document.getElementById('viewer'));
        viewer.addModel(pdb, "pdb");
        viewer.setStyle({}, {cartoon: {color: 'spectrum'}});
        viewer.zoomTo();
        viewer.render();
        
        function setStyle(style) {
            viewer.setStyle({}, {});
            if (style === 'cartoon') viewer.setStyle({}, {cartoon: {color: 'spectrum'}});
            else if (style === 'surface') viewer.setStyle({}, {surface: {opacity: 0.9, color: 'white'}});
            else if (style === 'stick') viewer.setStyle({}, {stick: {colorscheme: 'Jmol'}});
            else if (style === 'sphere') viewer.setStyle({}, {sphere: {colorscheme: 'Jmol'}});
            viewer.render();
        }
        
        function colorBy(scheme) {
            viewer.setStyle({}, {});
            if (scheme === 'spectrum') viewer.setStyle({}, {cartoon: {color: 'spectrum'}});
            else if (scheme === 'ss') viewer.setStyle({}, {cartoon: {colorscheme: 'ssJmol'}});
            else if (scheme === 'hydrophobicity') viewer.setStyle({}, {cartoon: {colorscheme: 'hydrophobicity'}});
            viewer.render();
        }
    </script>
</body>
</html>""" % json.dumps(pdb_content)
    
    # Save HTML file (unique name per structure so results don't overwrite)
    import hashlib
    content_hash = hashlib.md5(pdb_content.encode("utf-8", errors="replace")).hexdigest()[:8]
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "protein_viewer")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "viewer_%s.html" % content_hash)
    
    with open(output_file, 'w') as f:
        f.write(html)
    
    return (
        "3D Structure Viewer generated!\n"
        "File: %s\n"
        "Open in browser to view the structure.\n\n"
        "Controls:\n"
        "  - Cartoon: Ribbon representation\n"
        "  - Surface: Molecular surface\n"
        "  - Stick: Ball-and-stick model\n"
        "  - Sphere: Space-filling model\n"
        "  - Color by: Spectrum, Secondary Structure, Hydrophobicity"
    ) % output_file


def _search_motifs(sequence=None, motif=None, **kwargs):
    """Search for protein motifs and patterns."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    lines = []
    lines.append("MOTIF SEARCH RESULTS")
    lines.append("=" * 50)
    lines.append("")
    
    if motif:
        # Search for custom motif (regex)
        try:
            matches = list(re.finditer(motif, seq))
            lines.append("Custom Pattern: %s" % motif)
            lines.append("Matches found: %d" % len(matches))
            lines.append("")
            for i, match in enumerate(matches[:10]):
                start = match.start() + 1  # 1-indexed
                end = match.end()
                context_start = max(0, match.start() - 5)
                context_end = min(len(seq), match.end() + 5)
                context = seq[context_start:context_end]
                lines.append("  Match %d: Position %d-%d" % (i + 1, start, end))
                lines.append("  Sequence: ...%s..." % context)
                lines.append("")
        except re.error as e:
            lines.append("Invalid regex pattern: %s" % str(e))
    else:
        # Search for common motifs
        lines.append("Searching for common protein motifs...")
        lines.append("")
        
        found_any = False
        for name, pattern in COMMON_MOTIFS.items():
            try:
                matches = list(re.finditer(pattern, seq))
                if matches:
                    found_any = True
                    lines.append("FOUND: %s" % name)
                    lines.append("  Pattern: %s" % pattern)
                    lines.append("  Occurrences: %d" % len(matches))
                    for match in matches[:3]:
                        start = match.start() + 1
                        end = match.end()
                        lines.append("  - Position %d-%d: %s" % (start, end, match.group()))
                    lines.append("")
            except re.error:
                pass
        
        if not found_any:
            lines.append("No common motifs found in the sequence.")
    
    return "\n".join(lines)


def _calculate_properties(sequence=None, **kwargs):
    """Calculate detailed physicochemical properties."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    length = len(seq)
    
    # Count amino acids
    counts = {}
    for aa in seq:
        counts[aa] = counts.get(aa, 0) + 1
    
    # Molecular weight
    mw = sum(counts.get(aa, 0) * info['mw'] for aa, info in AMINO_ACIDS.items() if aa != 'X')
    
    # Extinction coefficient (cysteine + tryptophan)
    cys_count = counts.get('C', 0)
    trp_count = counts.get('W', 0)
    tyr_count = counts.get('Y', 0)
    ext_coeff_280 = (trp_count * 5500 + tyr_count * 1490 + cys_count * 125)  # M-1 cm-1
    
    # Charge at pH 7
    # pKa values (approximate)
    pKa = {'D': 3.9, 'E': 4.1, 'H': 6.0, 'C': 8.3, 'Y': 10.1, 'K': 10.5, 'R': 12.5}
    charge_at_7 = 0
    for aa, pka_val in pKa.items():
        count = counts.get(aa, 0)
        if aa in ('D', 'E', 'C', 'Y'):
            # Negative charges
            charge_at_7 -= count * (1 / (1 + 10**(pka_val - 7)))
        else:
            # Positive charges
            charge_at_7 += count * (1 / (1 + 10**(7 - pka_val)))
    
    # Instability index (simplified)
    # Based on dipeptide instability values (simplified)
    instability = 0
    for i in range(length - 1):
        dipeptide = seq[i:i+2]
        # Simplified: some dipeptides are more unstable
        if dipeptide in ('DE', 'ED', 'DG', 'GD', 'NE', 'EN'):
            instability += 1
    instability_index = (10 * instability) / length
    
    # Aliphatic index (Ikai 1980): ((Ala + 2.9*Val + 3.9*(Ile+Leu)) / n) * 100
    aliphatic = (counts.get('A', 0) + counts.get('V', 0) * 2.9
                 + counts.get('I', 0) * 3.9 + counts.get('L', 0) * 3.9)
    aliphatic_index = 100.0 * aliphatic / length if length else 0.0
    
    # Hydrophobicity (Kyte-Doolittle)
    hydrophobicity = sum(KD_HYDROPATHY.get(aa, 0) for aa in seq) / length
    
    # Format output
    lines = []
    lines.append("PHYSICOCHEMICAL PROPERTIES")
    lines.append("=" * 50)
    lines.append("")
    lines.append("Basic Properties:")
    lines.append("  Sequence Length:     %d amino acids" % length)
    lines.append("  Molecular Weight:    %.2f Da (%.2f kDa)" % (mw, mw / 1000))
    lines.append("  Number of Residues: %d" % length)
    lines.append("")
    lines.append("Charge Properties:")
    lines.append("  Net Charge (pH 7):  %.2f" % charge_at_7)
    lines.append("  Positive Residues:  %d (K=%d, R=%d, H=%d)" % (
        counts.get('K', 0) + counts.get('R', 0) + counts.get('H', 0),
        counts.get('K', 0), counts.get('R', 0), counts.get('H', 0)))
    lines.append("  Negative Residues:  %d (D=%d, E=%d)" % (
        counts.get('D', 0) + counts.get('E', 0),
        counts.get('D', 0), counts.get('E', 0)))
    lines.append("")
    lines.append("Spectroscopic Properties:")
    lines.append("  Extinction Coeff (280nm): %d M-1 cm-1" % ext_coeff_280)
    lines.append("  Cysteines: %d" % cys_count)
    lines.append("  Tryptophans: %d" % trp_count)
    lines.append("  Tyrosines: %d" % tyr_count)
    lines.append("")
    lines.append("Stability Indicators:")
    lines.append("  Instability Index:   %.2f" % instability_index)
    lines.append("  Classification:      %s" % ("Stable" if instability_index < 40 else "Unstable"))
    lines.append("  Aliphatic Index:     %.2f" % aliphatic_index)
    lines.append("  Grand Average Hydropathy (GRAVY): %.3f" % hydrophobicity)
    lines.append("  Classification:      %s" % ("Hydrophobic" if hydrophobicity > 0 else "Hydrophilic"))
    
    return "\n".join(lines)


def _design_suggestions(sequence=None, goal="stability", **kwargs):
    """Get design suggestions for protein optimization."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    goal = goal.lower().strip()
    
    lines = []
    lines.append("PROTEIN DESIGN SUGGESTIONS")
    lines.append("=" * 50)
    lines.append("Goal: %s" % goal.capitalize())
    lines.append("")
    
    # Analyze current sequence
    counts = {}
    for aa in seq:
        counts[aa] = counts.get(aa, 0) + 1
    
    if goal in ("stability", "thermostability"):
        lines.append("STABILITY OPTIMIZATION")
        lines.append("-" * 50)
        
        # Proline at N-terminus
        if seq[0] != 'P':
            lines.append("  1. Add Proline at N-terminus: Improves thermal stability")
        
        # Disulfide bonds
        cys_count = counts.get('C', 0)
        if cys_count < 2:
            lines.append("  2. Consider adding Cysteine pairs for disulfide bonds")
        
        # Charge optimization
        positive = counts.get('K', 0) + counts.get('R', 0)
        negative = counts.get('D', 0) + counts.get('E', 0)
        if abs(positive - negative) > 3:
            lines.append("  3. Balance charge distribution (current: +%.0f/-%.0f)" % (positive, negative))
        
        # Hydrophobic core
        hydrophobic = sum(counts.get(aa, 0) for aa in 'AILVFW')
        if hydrophobic / len(seq) < 0.3:
            lines.append("  4. Increase hydrophobic core packing")
        
        lines.append("")
    
    elif goal in ("expression", "solubility"):
        lines.append("EXPRESSION/SOLUBILITY OPTIMIZATION")
        lines.append("-" * 50)
        
        # Codon usage (simplified)
        rare_aas = [aa for aa, count in counts.items() if aa in 'CMW' and count > 0]
        if rare_aas:
            lines.append("  1. Consider reducing rare codons: %s" % ', '.join(rare_aas))
        
        # Charge
        negative = counts.get('D', 0) + counts.get('E', 0)
        if negative < 5:
            lines.append("  2. Add negative charges (Asp/Glu) to improve solubility")
        
        # Reduce aggregation
        hydrophobic = sum(counts.get(aa, 0) for aa in 'AILVFW')
        if hydrophobic / len(seq) > 0.4:
            lines.append("  3. Reduce hydrophobic content to prevent aggregation")
        
        # Proline
        pro_count = counts.get('P', 0)
        if pro_count < 2:
            lines.append("  4. Add Proline residues to reduce aggregation")
        
        lines.append("")
    
    elif goal in ("binding", "affinity"):
        lines.append("BINDING AFFINITY OPTIMIZATION")
        lines.append("-" * 50)
        
        # Analyze binding site candidates
        lines.append("  1. Identify key residues at binding interface")
        
        # Aromatic residues for stacking
        aromatic = counts.get('F', 0) + counts.get('Y', 0) + counts.get('W', 0)
        if aromatic < 3:
            lines.append("  2. Add aromatic residues (F/Y/W) for pi-stacking interactions")
        
        # Charged residues for electrostatics
        positive = counts.get('K', 0) + counts.get('R', 0)
        if positive < 3:
            lines.append("  3. Add positive charges (K/R) for electrostatic interactions")
        
        # Hydrogen bonding
        polar = counts.get('S', 0) + counts.get('T', 0) + counts.get('N', 0) + counts.get('Q', 0)
        if polar < 5:
            lines.append("  4. Add polar residues (S/T/N/Q) for hydrogen bonding")
        
        lines.append("")
    
    else:
        lines.append("Available goals: stability, expression, binding")
        lines.append("")
    
    lines.append("GENERAL RECOMMENDATIONS")
    lines.append("-" * 50)
    lines.append("  - Validate mutations with structure prediction")
    lines.append("  - Consider evolutionary conservation at each position")
    lines.append("  - Test multiple variants experimentally")
    lines.append("  - Use computational tools for detailed analysis")
    
    return "\n".join(lines)


def _optimize_inducer(**kwargs):
    """Receptor-guided inducer optimization (delegates to inducer_optimizer)."""
    try:
        from skills import inducer_optimizer
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "inducer_optimizer",
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "inducer_optimizer.py"))
        inducer_optimizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inducer_optimizer)
    return inducer_optimizer.run(action="optimize_inducer", **kwargs)


def _design_from_text(prompt=None, **kwargs):
    """Design protein from natural language description."""
    if not prompt:
        return "No prompt provided. Pass prompt='...'"
    
    try:
        # Try to use evo2 for protein design from text
        from skills import evo2
        return evo2.run(
            task="design_protein_from_text",
            prompt=prompt,
            num_sequences=5,
            temperature=0.8,
        )
    except ImportError:
        return (
            "Protein design from text requires the evo2 skill for DNA/protein generation. "
            "Make sure the evo2 skill is properly installed."
        )
    except Exception as e:
        return "Protein design from text failed: %s" % str(e)


def _design_from_proto_language(prompt=None, **kwargs):
    """Design protein using proto-language generators.

    Tries Evo2 (a real, available skill) for generative protein design from
    text. If Evo2 is not installed, falls back to heuristic design suggestions
    on any protein sequence embedded in the prompt.
    """
    if not prompt:
        return "No prompt provided. Pass prompt='...'"

    # Try Evo2 (real skill)
    try:
        from skills import evo2
        result = evo2.run(
            task="design_protein_from_text",
            prompt=prompt,
            num_sequences=3,
            temperature=0.8,
        )
        return "Proto-language (Evo2):\n" + result
    except ImportError:
        pass

    # Fallback: heuristic design suggestions on a sequence found in the prompt
    seq_match = re.search(r'[ACDEFGHIKLMNPQRSTVWY]{15,}', prompt.upper())
    if seq_match:
        note = (
            "Note: Evo2 skill not installed; running heuristic design "
            "suggestions on the sequence found in the prompt instead.\n\n"
        )
        return note + _design_suggestions(sequence=seq_match.group(0), **kwargs)

    return (
        "Proto-language design requires the evo2 skill, which is not installed, "
        "and no usable protein sequence (>= 15 aa) was found in the prompt.\n"
        "Available alternatives: run(action='design_from_text') or run(action='design', sequence='...')"
    )


def _download_structure(identifier=None, source="pdb", output_dir=None, **kwargs):
    """Download structure from PDB, AlphaFold, or RCSB.

    Downloads the structure file directly from the source database and saves
    it under output/structures/, then returns a summary (path + sequence when
    parseable). Falls back to the web_crawler skill if the direct download
    fails.

    Args:
        identifier: PDB ID (e.g. "1CRN") or UniProt accession (e.g. "P69905").
        source: "pdb" (RCSB PDB) or "alphafold" (AlphaFold DB).
        output_dir: Optional directory to save the structure file.

    Returns:
        Human-readable summary string.
    """
    if not identifier:
        return "No identifier provided. Pass identifier='...'"

    identifier = identifier.strip().upper()
    source = (source or "pdb").lower().strip()

    # Map source to its download URL and expected file name.
    if source == "pdb":
        url = "https://files.rcsb.org/download/%s.pdb" % identifier
        filename = "%s.pdb" % identifier
    elif source in ("alphafold", "af"):
        # AlphaFold DB: query the API to discover the current model URL
        # (the version suffix changes over time, e.g. v4 -> v6).
        api_url = "https://alphafold.ebi.ac.uk/api/prediction/%s" % identifier
        try:
            api_resp = requests.get(api_url, timeout=30)
            api_resp.raise_for_status()
            entries = api_resp.json()
            if entries and isinstance(entries, list) and entries[0].get("pdbUrl"):
                url = entries[0]["pdbUrl"]
            else:
                url = "https://alphafold.ebi.ac.uk/files/AF-%s-F1-model_v4.pdb" % identifier
        except Exception:
            url = "https://alphafold.ebi.ac.uk/files/AF-%s-F1-model_v4.pdb" % identifier
        filename = url.rsplit("/", 1)[-1]
    else:
        return "Unsupported source: %s. Use: pdb, alphafold" % source

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
        if not text or text.strip().startswith("<!DOCTYPE") or "<html" in text[:500].lower():
            raise ValueError("Source returned no usable structure data (bad identifier?)")

        out_dir = output_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output", "structures")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

        lines = ["Structure downloaded: %s" % os.path.relpath(path, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
        lines.append("Source: %s  |  Identifier: %s" % (source, identifier))

        # Extract the sequence from ATOM/CAA records when available.
        seq = _extract_sequence_from_pdb(text)
        if seq:
            lines.append("Sequence (%d aa): %s" % (len(seq), seq))
            lines.append("")
            lines.append("Analyze it with: run(action='analyze', sequence='%s')" % seq)
        else:
            lines.append("Note: no sequence records found in this file.")
        return "\n".join(lines)
    except requests.RequestException as e:
        return "PDB structure download failed: %s" % str(e)
    except Exception as e:
        # Last resort: let the web_crawler skill fetch the raw file.
        try:
            return _execute_web_crawler("scrape", url=url, format="text")
        except Exception as e2:
            return "PDB structure download failed: %s (fallback also failed: %s)" % (e, e2)


def _extract_sequence_from_pdb(pdb_text: str) -> str:
    """Extract a one-letter protein sequence from PDB ATOM records (chain A)."""
    residues = {}
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and len(line) >= 27:
            resname = line[17:20].strip()
            chain = line[21]
            resseq = line[22:26].strip()
            if chain != "A":
                continue
            try:
                key = (int(resseq), resname)
            except ValueError:
                continue
            if key not in residues:
                residues[key] = resname
    if not residues:
        return ""
    aa_map = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    seq = "".join(aa_map.get(res, "X") for _idx, res in sorted(residues.items()))
    return seq


def _search_structure(query=None, limit=10, **kwargs):
    """Search for protein structures by query.

    Uses the RCSB PDB search API (full-text query) to return matching PDB
    entries. Falls back to the web_crawler skill if the API is unavailable.

    Args:
        query: Search text (e.g. "insulin receptor kinase").
        limit: Maximum number of results to return (default 10).

    Returns:
        Human-readable list of matching PDB entries.
    """
    if not query:
        return "No search query provided. Pass query='...'"

    limit = max(1, min(int(limit or 10), 50))
    payload = {
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query},
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": 0, "rows": limit},
        },
    }
    try:
        resp = requests.post(
            "https://search.rcsb.org/rcsbsearch/v2/query",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("result_set", [])
        if not hits:
            return "No structures found for query: '%s'. Try a different term or use action='download_structure' with a known PDB ID." % query

        lines = ["Structures matching '%s' (%d found):" % (query, len(hits))]
        lines.append("-" * 50)
        for i, hit in enumerate(hits[:limit], 1):
            pdb_id = hit.get("identifier", "")
            score = hit.get("score", 0)
            lines.append("%d. %s  (score %.3f)" % (i, pdb_id, score))
            lines.append("   Download: run(action='download_structure', identifier='%s', source='pdb')" % pdb_id)
        return "\n".join(lines)
    except requests.RequestException as e:
        return "Structure search failed: %s" % str(e)
    except Exception as e:
        # Fallback: web search for RCSB results.
        search_query = "RCSB PDB %s protein structure" % query
        try:
            return _execute_web_crawler("search", query=search_query, limit=limit, scrape_results=True)
        except Exception as e2:
            return "Structure search failed: %s (fallback also failed: %s)" % (e, e2)


def _research_topic(topic=None, **kwargs):
    """Research protein topics using web search via Firecrawl."""
    if not topic:
        return "No research topic provided. Pass topic='...'"
    
    # Use web_crawler (firecrawl) skill for literature search
    search_query = f"protein {topic} literature 2024"
    return _execute_web_crawler("search", query=search_query, limit=10, scrape_results=True)


# ============================================================
# Utility functions
# ============================================================

def _parse_fasta(content: str) -> List[Dict]:
    """Parse FASTA content into list of {header, sequence} dicts."""
    sequences = []
    current_header = None
    current_seq = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if line.startswith('>'):
            if current_header is not None:
                sequences.append({"header": current_header, "sequence": ''.join(current_seq)})
            current_header = line[1:]
            current_seq = []
        elif line:
            current_seq.append(line)
    if current_header is not None:
        sequences.append({"header": current_header, "sequence": ''.join(current_seq)})
    return sequences


def _convert_format(sequence=None, from_format="fasta", to_format="raw", **kwargs):
    """Convert between sequence formats."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    if from_format.lower() == "fasta" and to_format.lower() == "raw":
        return seq
    elif from_format.lower() == "raw" and to_format.lower() == "fasta":
        header = kwargs.get("header", "sequence")
        return f">{header}\n{seq}"
    else:
        return f"Conversion from {from_format} to {to_format} not supported. Use fasta <-> raw."


def _protein_to_dna(protein_sequence, dna_code="standard", **kwargs):
    """Convert a protein sequence to DNA nucleotide sequence.
    
    Uses the standard genetic code to translate protein amino acids
    into DNA base pairs. This is useful for codon optimization,
    synthetic biology applications, or preparing DNA templates
    for protein expression.
    
    Args:
        protein_sequence: Protein amino acid sequence (one-letter code)
        dna_code: Genetic code table to use (default: standard)
    
    Returns:
        DNA nucleotide sequence (A, C, G, T) corresponding to the protein.
        Each amino acid is randomly assigned a codon from the selected
        genetic code table.
    """
    from collections import Counter
    
    # Standard genetic code mapping amino acids to possible DNA codons
    GENETIC_CODE = {
        'A': ['GCA', 'GCC', 'GCG', 'GCT'],  # Alanine
        'R': ['CGA', 'CGC', 'CGG', 'CGT', 'AGA', 'AGG'],  # Arginine
        'N': ['AAC', 'AAT'],  # Asparagine
        'D': ['GAT', 'GAC'],  # Aspartic Acid
        'C': ['TGT', 'TGC'],  # Cysteine
        'E': ['GAA', 'GAG'],  # Glutamic Acid
        'Q': ['CAA', 'CAG'],  # Glutamine
        'G': ['GGA', 'GGC', 'GGG', 'GGT'],  # Glycine
        'H': ['CAT', 'CAC'],  # Histidine
        'I': ['ATT', 'ATC', 'ATA'],  # Isoleucine
        'L': ['CTA', 'CTC', 'CTG', 'CTT', 'TTA', 'TTG'],  # Leucine
        'K': ['AAA', 'AAG'],  # Lysine
        'M': ['ATG'],  # Methionine (start codon)
        'F': ['TTT', 'TTC'],  # Phenylalanine
        'P': ['CCA', 'CCC', 'CCG', 'CCT'],  # Proline
        'S': ['AGC', 'AGT', 'TCA', 'TCC', 'TCG', 'TCT'],  # Serine
        'T': ['ACA', 'ACC', 'ACG', 'ACT'],  # Threonine
        'W': ['TGG'],  # Tryptophan
        'Y': ['TAT', 'TAC'],  # Tyrosine
        'V': ['GTA', 'GTC', 'GTG', 'GTT'],  # Valine
        'Stop': ['TAA', 'TAG', 'TGA'],  # Stop codons
        '*': ['TAA', 'TAG', 'TGA'],
        'X': ['GCA', 'GCC', 'GCG', 'GCT'],  # Unknown -> Alanine codons
    }
    
    protein_sequence = protein_sequence.upper().strip()
    
    # Convert each amino acid to a codon
    dna_parts = []
    for aa in protein_sequence:
        if aa in GENETIC_CODE:
            codons = GENETIC_CODE[aa]
            # Choose a codon - for simplicity, use the first one
            # In a full implementation, you'd weight by codon usage bias
            selected_codon = codons[0]  # First codon
            dna_parts.append(selected_codon)
        elif aa == 'X':  # Unknown amino acid
            dna_parts.append('GCA')  # Default to Alanine codon
        else:
            # Skip unrecognized characters
            continue
    
    dna_sequence = ''.join(dna_parts)
    
    lines = []
    lines.append("PROTEIN TO DNA CONVERSION")
    lines.append("=" * 50)
    lines.append("")
    lines.append(" protein sequence: %d amino acids" % len(protein_sequence))
    lines.append(" DNA sequence: %d base pairs" % len(dna_sequence))
    lines.append("")
    lines.append("DNA sequence: %s" % dna_sequence)
    lines.append("")
    lines.append("Note: This conversion uses the first codon for each amino acid.")
    lines.append("For codon optimization with specific expression preferences,")
    lines.append("consider using dedicated tools or specify codon usage biases.")
    
    return "\n".join(lines)


def _dna_to_protein(dna_sequence, **kwargs):
    """Convert a DNA nucleotide sequence to protein amino acid sequence.
    
    Translates DNA base pairs into protein amino acids using the
    standard genetic code. This is useful for analyzing coding
    sequences, predicting protein products, or preparing
    annotations for genomic data.
    
    Args:
        dna_sequence: DNA nucleotide sequence (A, C, G, T)
    
    Returns:
        Protein amino acid sequence (one-letter code).
        Returns None if no valid protein sequence can be extracted.
    """
    import re
    
    # Clean the DNA sequence
    dna_sequence = dna_sequence.upper().strip()
    valid_bases = set("ACGT")
    dna_sequence = ''.join(c for c in dna_sequence if c in valid_bases)
    
    if not dna_sequence or len(dna_sequence) < 3:
        return "No valid DNA sequence provided. Use A, C, G, T only."
    
    # Standard genetic code (RNA codons, transcribed from DNA T->U)
    RNA_CODON_TABLE = {
        'UUU': 'F', 'UUC': 'F', 'UUA': 'L', 'UUG': 'L',
        'CUU': 'L', 'CUC': 'L', 'CUA': 'L', 'CUG': 'L',
        'GGU': 'G', 'GGC': 'G', 'GGA': 'G', 'GGG': 'G',
        'UCU': 'S', 'UCC': 'S', 'UCA': 'S', 'UCG': 'S',
        'UAU': 'Y', 'UAC': 'Y', 'UAA': '*', 'UAG': '*', 'UGA': '*',
        'CGU': 'R', 'CGC': 'R', 'CGA': 'R', 'CGG': 'R',
        'AGU': 'S', 'AGC': 'S', 'AGA': 'R', 'AGG': 'R',
        'GUU': 'V', 'GUC': 'V', 'GUA': 'V', 'GUG': 'V',
        'CCU': 'P', 'CCC': 'P', 'CCA': 'P', 'CCG': 'P',
        'ACU': 'T', 'ACC': 'T', 'ACA': 'T', 'ACG': 'T',
        'GCU': 'A', 'GCC': 'A', 'GCA': 'A', 'GCG': 'A',
        'CAU': 'H', 'CAC': 'H', 'CAA': 'Q', 'CAG': 'Q',
        'AAU': 'N', 'AAC': 'N', 'AAA': 'K', 'AAG': 'K',
        'GAU': 'D', 'GAC': 'D', 'GAA': 'E', 'GAG': 'E',
        'UGU': 'C', 'UGC': 'C', 'UGG': 'W',
        'AUU': 'I', 'AUC': 'I', 'AUA': 'I',
        'AUG': 'M',
    }
    
    # Reverse complement of the original DNA (computed once, on DNA letters)
    complement = {'A': 'T', 'T': 'A', 'G': 'C', 'C': 'G'}
    rc_dna = ''.join(complement.get(c, 'N') for c in reversed(dna_sequence))
    
    # Transcribe both strands to RNA (T -> U)
    rna = dna_sequence.replace('T', 'U')
    rna_rc = rc_dna.replace('T', 'U')
    
    # Translate in all 6 reading frames
    protein_sequences = []
    
    for frame_offset in range(3):
        # Forward frame
        protein = ""
        for i in range(frame_offset, len(rna) - 2, 3):
            codon = rna[i:i+3]
            amino_acid = RNA_CODON_TABLE.get(codon, 'X')
            if amino_acid == '*':
                break  # Stop codon
            protein += amino_acid
        
        if protein:
            protein_sequences.append(("Frame %d (forward)" % (frame_offset + 1), protein))
        
        # Reverse-complement frame
        protein2 = ""
        for i in range(frame_offset, len(rna_rc) - 2, 3):
            codon = rna_rc[i:i+3]
            amino_acid = RNA_CODON_TABLE.get(codon, 'X')
            if amino_acid == '*':
                break
            protein2 += amino_acid
        
        if protein2:
            protein_sequences.append(("Frame %d (reverse)" % (frame_offset + 1), protein2))
    
    # Return the longest valid protein sequence
    best_protein = None
    best_length = 0
    for frame_name, protein in protein_sequences:
        if len(protein) > best_length:
            best_length = len(protein)
            best_protein = protein
    
    if best_protein:
        lines = []
        lines.append("DNA TO PROTEIN CONVERSION")
        lines.append("=" * 50)
        lines.append("")
        lines.append("DNA sequence: %s" % dna_sequence[:60] + ("..." if len(dna_sequence) > 60 else ""))
        lines.append("")
        lines.append("Best protein sequence (longest ORF): %d amino acids" % len(best_protein))
        lines.append("Sequence: %s" % best_protein)
        lines.append("")
        lines.append("Reading frames analyzed: 6 (3 forward, 3 reverse)")
        lines.append("Start codon (ATG/GTG/TGG) presence: check above")
        lines.append("")
        lines.append("All predicted protein sequences:")
        for frame_name, protein in protein_sequences:
            lines.append("  %s: %s (%d aa)" % (frame_name, protein, len(protein)))
        
        return "\n".join(lines)
    else:
        return "No valid protein sequence found in the provided DNA. Check for start codons and reading frames."


def _proto_tools_bridge(sub_action=None, proto_action=None, action="predict", **kwargs):
    """Bridge to proto-tools structure prediction and scoring tools.
    
    Attempts Boltz-2 for structure prediction where available and falls back
    to built-in heuristics. Scoring/comparison require a full proto-tools
    installation, which is not present.
    
    Sub-actions (pass via sub_action= / proto_action= when dispatched through
    run(), since run() itself uses the `action` kwarg):
      predict      - Predict structure (Boltz-2, then heuristic fallback)
      score        - Structure quality scoring (requires proto-tools install)
      design       - Design mutations/modifications (heuristic suggestions)
      compare      - Compare predicted vs experimental structures (requires proto-tools install)
    """
    # Accept sub-action from any of: sub_action, proto_action, action
    chosen = sub_action or proto_action or action or "predict"
    chosen = str(chosen).lower().strip()
    if chosen == "predict":
        return _proto_tools_predict(**kwargs)
    elif chosen == "score":
        return _proto_tools_score(**kwargs)
    elif chosen == "design":
        return _proto_tools_design(**kwargs)
    elif chosen == "compare":
        return _proto_tools_compare(**kwargs)
    else:
        return "Unknown proto-tools sub-action: %s. Use sub_action='predict', 'score', 'design', or 'compare'." % chosen


def _proto_tools_predict(sequence=None, predictor="alphafold", output_dir=None, **kwargs):
    """Predict protein structure using available predictors."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    # Try boltz-2 predictor first
    try:
        from skills import boltz_2
        result = boltz_2.run(task="fold", protein_sequence=seq, output_dir=output_dir)
        return "Proto-tools (Boltz-2):\n" + result
    except ImportError:
        pass
    
    # Fallback to secondary-structure-level prediction if one exists
    fallback = globals().get("_predict_secondary_structure")
    if callable(fallback):
        return fallback(seq)
    
    return (
        "Structure prediction requires the boltz_2 skill (Boltz-2), which is not "
        "installed. No heuristic secondary-structure predictor is bundled with "
        "Protein Lab. You can still use 'analyze', 'properties', or 'motifs'."
    )


def _proto_tools_score(pdb_file=None, **kwargs):
    """Score protein structure quality.

    Requires a proto-tools installation (DSSP/PyRosetta-style scorers), which
    is not bundled with Protein Lab.
    """
    if not pdb_file:
        return "No PDB file provided. Pass pdb_file='...'"
    
    return (
        "Structure quality scoring requires a proto-tools installation "
        "(DSSP, PyRosetta, etc.), which is not present in this environment. "
        "You can still inspect basic structure statistics with "
        "run(action='structure_stats', pdb_file='%s')." % pdb_file
    )


def _proto_tools_design(sequence=None, goal="stability", **kwargs):
    """Design protein modifications using available heuristics."""
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    
    note = (
        "Note: proto-tools design generators are not installed; "
        "running heuristic design suggestions instead.\n\n"
    )
    return note + _design_suggestions(sequence=seq, goal=goal)


def _proto_tools_compare(pdb_file1=None, pdb_file2=None, **kwargs):
    """Compare two protein structures.

    Requires a proto-tools installation (structural superposition tools),
    which is not bundled with Protein Lab.
    """
    if not pdb_file1 or not pdb_file2:
        return "Two PDB files required. Pass pdb_file1='...' and pdb_file2='...'"
    
    return (
        "Structural comparison requires a proto-tools installation "
        "(superposition/RMSD tooling), which is not present in this environment."
    )


def _mutate(sequence=None, mutation=None, **kwargs):
    """Apply one or more point mutations/deletions to a protein sequence.

    Accepted mutation formats:
      "A42V"     - substitute residue 42 (Ala) with Val
      "p.A42V"   - HGVS-style prefix also accepted
      "K7del"    - delete residue 7
      comma-separated for multiple: "A42V,K7R"

    Positions are 1-indexed against the ORIGINAL sequence. The wildtype
    residue at each position must match, otherwise a clear error is reported.
    """
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"
    if not mutation:
        return "No mutation provided. Pass mutation='A42V' (also accepted: 'p.A42V', 'K7del', 'A42V,K7R')."

    mut_re = re.compile(r'^(?:p\.)?([A-Z])(\d+)(del|([A-Z]))$', re.IGNORECASE)

    edits = {}   # 0-indexed position -> new residue ('' means deletion)
    errors = []
    for raw in [m.strip() for m in str(mutation).split(',') if m.strip()]:
        m = mut_re.match(raw)
        if not m:
            errors.append("Could not parse mutation '%s'. Use formats like A42V, p.A42V, or K7del." % raw)
            continue
        wt, pos_str, _, new = m.groups()
        pos = int(pos_str) - 1
        if pos < 0 or pos >= len(seq):
            errors.append("Position %d is out of range for a sequence of length %d ('%s')." % (
                int(pos_str), len(seq), raw))
            continue
        actual = seq[pos]
        if actual != wt.upper():
            errors.append("Wildtype mismatch at position %d: expected '%s' but sequence has '%s'." % (
                int(pos_str), wt.upper(), actual))
            continue
        edits[pos] = new.upper() if new else ''

    lines = []
    lines.append("MUTATION REPORT")
    lines.append("=" * 50)
    lines.append("Original sequence: %d aa" % len(seq))
    lines.append("")

    for err in errors:
        lines.append("ERROR: %s" % err)
    if errors:
        lines.append("")
    if not edits:
        if errors:
            return "\n".join(lines)
        return "No mutations applied."

    def _charge_of(aa):
        if aa in ('K', 'R', 'H'):
            return 1
        if aa in ('D', 'E'):
            return -1
        return 0

    def _bucket(aa):
        info = AMINO_ACIDS.get(aa, {})
        if info.get('hydrophobic'):
            return 'hydrophobic'
        cat = info.get('category', 'unknown')
        if cat in ('positive', 'negative'):
            return cat
        return 'polar'

    for pos in sorted(edits):
        old_aa = seq[pos]
        new_aa = edits[pos]
        ctx_start = max(0, pos - 5)
        ctx_end = min(len(seq), pos + 6)
        context = seq[ctx_start:pos] + '[' + old_aa + ']' + seq[pos + 1:ctx_end]

        lines.append("Mutation %s%s%d%s:" % (
            old_aa, '', pos + 1,
            ('>' + new_aa) if new_aa else ' (deletion)'))
        lines.append("  Context (%d-%d): %s" % (ctx_start + 1, ctx_end, context))

        if new_aa:
            mw_delta = AMINO_ACIDS.get(new_aa, {}).get('mw', 0.0) - AMINO_ACIDS.get(old_aa, {}).get('mw', 0.0)
        else:
            # Deletion removes one residue: residue mass = free-aa mass - water
            mw_delta = -(AMINO_ACIDS.get(old_aa, {}).get('mw', 0.0) - 18.015)
        charge_delta = (_charge_of(new_aa) if new_aa else 0) - _charge_of(old_aa)
        hyd_delta = KD_HYDROPATHY.get(new_aa, 0.0) - KD_HYDROPATHY.get(old_aa, 0.0)

        if new_aa:
            cat_old = AMINO_ACIDS.get(old_aa, {}).get('category', 'unknown')
            cat_new = AMINO_ACIDS.get(new_aa, {}).get('category', 'unknown')
            if cat_old == cat_new:
                classification = "conservative (%s -> %s)" % (cat_old, cat_new)
            else:
                classification = "nonconservative (%s -> %s)" % (_bucket(old_aa), _bucket(new_aa))
        else:
            classification = "deletion"

        lines.append("  MW delta:         %+.2f Da" % mw_delta)
        lines.append("  Charge delta:     %+.0f" % charge_delta)
        lines.append("  Hydropathy delta: %+.2f KD" % hyd_delta)
        lines.append("  Classification:   %s" % classification)
        lines.append("")

    # Build the mutated sequence (positions refer to the original numbering)
    mutated_parts = []
    for i, aa in enumerate(seq):
        if i in edits:
            if edits[i]:
                mutated_parts.append(edits[i])
            # deletions simply skip the residue
        else:
            mutated_parts.append(aa)
    mutated_seq = ''.join(mutated_parts)

    lines.append("MUTATED SEQUENCE (%d aa):" % len(mutated_seq))
    lines.append("  %s" % (mutated_seq[:80] + "..." if len(mutated_seq) > 80 else mutated_seq))

    return "\n".join(lines)


def _hydrophobicity_profile(sequence=None, window=9, **kwargs):
    """Sliding-window Kyte-Doolittle hydrophobicity profile as ASCII bars.

    Prints one row per residue-window center (sampled evenly to <=120 rows for
    long sequences), flags the most hydrophobic windows as potential TM /
    hydrophobic-core candidates.
    """
    seq = _clean_sequence(sequence)
    if not seq:
        return "No valid sequence provided. Pass sequence='...'"

    try:
        window = int(window)
    except (TypeError, ValueError):
        window = 9
    window = max(3, min(window, len(seq)))
    if window % 2 == 0:
        window += 1
    half = window // 2

    # Compute average KD for every window centered on each residue possible
    values = []
    for center in range(half, len(seq) - half):
        seg = seq[center - half:center + half + 1]
        avg = sum(KD_HYDROPATHY.get(aa, 0.0) for aa in seg) / window
        values.append((center + 1, avg))  # 1-indexed center position

    lines = []
    lines.append("HYDROPHOBICITY PROFILE (Kyte-Doolittle, window=%d)" % window)
    lines.append("=" * 50)
    lines.append("Sequence length: %d aa | scale: +/-4.5 KD ('#' positive, '-' negative)" % len(seq))

    if not values:
        lines.append("Sequence too short for a sliding window.")
        return "\n".join(lines)

    # Cap displayed rows at <=120 by even sampling
    rows = values
    if len(rows) > 120:
        step = float(len(rows)) / 120.0
        rows = [rows[int(i * step)] for i in range(120)]

    BAR = 30
    zero = BAR  # zero axis sits at column BAR in a 2*BAR-wide field

    def _render(val):
        n = int(round(min(abs(val), 4.5) / 4.5 * BAR))
        field = [' '] * (2 * BAR)
        if val >= 0:
            for k in range(zero, zero + n):
                field[k] = '#'
        else:
            for k in range(zero - n, zero):
                field[k] = '-'
        return ''.join(field)

    lines.append("")
    axis_field = "-4.5".ljust(zero) + "0" + " " * (2 * BAR - zero - 5) + "+4.5"
    lines.append("%5s  %-6s |%s|" % ("pos", "KD", axis_field))
    for pos, val in rows:
        lines.append("%5d  %+5.2f |%s|" % (pos, val, _render(val)))

    # Flag the top 3 most-hydrophobic non-overlapping windows
    ranked = sorted(values, key=lambda v: v[1], reverse=True)
    flagged = []
    for pos, val in ranked:
        if all(abs(pos - p) >= window for p, _ in flagged):
            flagged.append((pos, val))
        if len(flagged) == 3:
            break

    lines.append("")
    lines.append("TOP HYDROPHOBIC WINDOWS (potential TM helices / hydrophobic core):")
    for rank, (pos, val) in enumerate(flagged, 1):
        start = max(1, pos - half)
        end = min(len(seq), pos + half)
        lines.append("  %d. Window centered at residue %d (aa %d-%d): avg KD %+.2f" % (
            rank, pos, start, end, val))
    if not any(v > 1.6 for _, v in flagged):
        lines.append("  Note: no strongly hydrophobic windows found (avg KD <= 1.6); "
                     "no obvious TM segment detected.")

    return "\n".join(lines)


def _batch_analyze(fasta=None, content=None, **kwargs):
    """Analyze multiple FASTA entries and print a summary table."""
    text = fasta if fasta is not None else content
    if not text:
        return "No FASTA content provided. Pass fasta='...' or content='...'"

    entries = _parse_fasta(text)
    if not entries:
        return "No FASTA entries could be parsed from the provided content."

    rows = []
    for entry in entries:
        seq = _clean_sequence(entry.get('sequence')) or ''
        n = len(seq)
        # Residue-mass based molecular weight (free-aa masses minus water per bond)
        mw = sum(AMINO_ACIDS.get(aa, {'mw': 0.0})['mw'] for aa in seq)
        if n > 1:
            mw -= 18.015 * (n - 1)
        gravy = (sum(KD_HYDROPATHY.get(aa, 0.0) for aa in seq) / n) if n else 0.0
        charge = (seq.count('K') + seq.count('R') + seq.count('H')
                  - seq.count('D') - seq.count('E'))
        header = (entry.get('header') or '').strip() or '(unnamed)'
        if len(header) > 30:
            header = header[:27] + '...'
        rows.append((header, n, mw, gravy, charge))

    rows.sort(key=lambda r: r[1], reverse=True)

    lines = []
    lines.append("BATCH ANALYSIS SUMMARY")
    lines.append("=" * 74)
    lines.append("%-32s %8s %12s %8s %8s" % ("Header", "Length", "MW (Da)", "GRAVY", "Charge"))
    lines.append("-" * 74)
    for header, n, mw, gravy, charge in rows:
        lines.append("%-32s %8d %12.2f %8.3f %+8d" % (header, n, mw, gravy, charge))
    lines.append("-" * 74)
    lines.append("Total sequences analyzed: %d" % len(rows))

    return "\n".join(lines)


def _structure_stats(pdb_file=None, pdb_content=None, **kwargs):
    """Parse PDB text and report chains, atom/residue counts, secondary
    structure records, and B-factor statistics."""
    if pdb_file and not pdb_content:
        try:
            with open(pdb_file, 'r', encoding='utf-8', errors='replace') as f:
                pdb_content = f.read()
        except OSError as e:
            return "Could not read PDB file '%s': %s" % (pdb_file, str(e))
    if not pdb_content:
        return "Provide pdb_file (path) or pdb_content (PDB string)."

    chains = {}       # chain id -> {'atoms': int, 'residues': set}
    helix_count = 0
    sheet_count = 0
    ss_residues = 0
    bfactors = []

    for line in pdb_content.splitlines():
        rec = line[:6].strip()
        if rec == 'ATOM':
            chain = line[21] if len(line) > 21 else '?'
            info = chains.setdefault(chain, {'atoms': 0, 'residues': set()})
            info['atoms'] += 1
            resname = line[17:20].strip()
            try:
                resnum = int(line[22:26])
            except ValueError:
                resnum = line[22:26].strip()
            info['residues'].add((resnum, resname))
            bfac_str = line[60:66].strip()
            if bfac_str:
                try:
                    bfactors.append(float(bfac_str))
                except ValueError:
                    pass
        elif rec == 'HELIX':
            helix_count += 1
            try:
                init_num = int(line[21:25])
                end_num = int(line[33:37])
                ss_residues += max(0, end_num - init_num + 1)
            except ValueError:
                pass
        elif rec == 'SHEET':
            sheet_count += 1
            try:
                init_num = int(line[22:26])
                end_num = int(line[33:37])
                ss_residues += max(0, end_num - init_num + 1)
            except ValueError:
                pass

    if not chains:
        return "No ATOM records found in the provided PDB data."

    total_atoms = sum(c['atoms'] for c in chains.values())
    total_residues = sum(len(c['residues']) for c in chains.values())

    lines = []
    lines.append("STRUCTURE STATISTICS")
    lines.append("=" * 50)
    lines.append("Chains: %d | Total ATOM records: %d | Total residues: %d" % (
        len(chains), total_atoms, total_residues))
    lines.append("")
    lines.append("%-8s %10s %10s" % ("Chain", "Atoms", "Residues"))
    lines.append("-" * 30)
    for chain in sorted(chains):
        lines.append("%-8s %10d %10d" % (chain, chains[chain]['atoms'], len(chains[chain]['residues'])))
    lines.append("-" * 30)

    lines.append("")
    lines.append("Secondary structure records:")
    lines.append("  HELIX records: %d" % helix_count)
    lines.append("  SHEET records: %d" % sheet_count)
    if helix_count or sheet_count:
        lines.append("  Residues in HELIX/SHEET spans (approx): %d" % ss_residues)
    else:
        lines.append("  (no HELIX/SHEET records present)")

    if bfactors:
        mean_b = sum(bfactors) / len(bfactors)
        lines.append("")
        lines.append("B-factors (%d atoms with values):" % len(bfactors))
        lines.append("  Min:  %.2f" % min(bfactors))
        lines.append("  Max:  %.2f" % max(bfactors))
        lines.append("  Mean: %.2f" % mean_b)
    else:
        lines.append("")
        lines.append("B-factors: none present in ATOM records.")

    return "\n".join(lines)


def _codon_optimize(protein_sequence=None, host="e_coli", **kwargs):
    """Codon-optimize a protein sequence using approximate host usage tables.

    Picks the highest-weight synonymous codon for every amino acid.
    Weights are approximate; verify with a dedicated tool before synthesis.
    """
    seq = _clean_sequence(protein_sequence)
    if not seq:
        return "No valid protein sequence provided. Pass protein_sequence='...'"

    host_key = (host or "e_coli").lower().strip()
    host_aliases = {
        'ecoli': 'e_coli', 'e.coli': 'e_coli', 'escherichia_coli': 'e_coli',
        'homo_sapiens': 'human', 'human': 'human', 'hsapiens': 'human',
    }
    host_key = host_aliases.get(host_key, host_key)
    table = CODON_USAGE_TABLES.get(host_key)
    if table is None:
        return ("Unknown host '%s'. Available hosts: %s"
                % (host, ', '.join(sorted(CODON_USAGE_TABLES))))

    codons = []
    unknown_aas = []
    for aa in seq:
        entry = table.get(aa)
        if not entry:
            unknown_aas.append(aa)
            continue
        best = max(entry, key=lambda cv: cv[1])[0]
        codons.append(best)
    cds = ''.join(codons)

    lines = []
    lines.append("CODON OPTIMIZATION")
    lines.append("=" * 50)
    lines.append("Host used: %s" % host_key)
    lines.append("Protein length: %d aa | CDS length: %d nt" % (len(seq), len(cds)))

    if unknown_aas:
        lines.append("Note: skipped unrecognized residues: %s" %
                     ', '.join(sorted(set(unknown_aas))))

    lines.append("")
    lines.append("OPTIMIZED CDS (5'->3'):")
    for i in range(0, len(cds), 60):
        lines.append("  %s" % cds[i:i + 60])

    if cds:
        gc = 100.0 * sum(cds.count(b) for b in 'GC') / len(cds)
        third_positions = cds[2::3]
        gc3 = 100.0 * sum(third_positions.count(b) for b in 'GC') / len(third_positions)
    else:
        gc = gc3 = 0.0
    lines.append("")
    lines.append("GC content:  %.1f%%" % gc)
    lines.append("GC3 (third-position GC): %.1f%%" % gc3)
    lines.append("")
    lines.append("Note: codon usage weights are approximate; the highest-weight "
                 "codon was chosen per amino acid. Verify with a dedicated "
                 "codon optimization tool before synthesis.")

    return "\n".join(lines)


def _show_help(**kwargs):
    """Show help for Protein Lab actions."""
    help_text = """
PROTEIN LAB - Available Actions
================================

ANALYSIS:
  analyze         - Analyze protein sequence (composition, properties, motifs)
  properties      - Calculate detailed physicochemical properties
  motifs          - Search for protein motifs and patterns
  align           - Sequence alignment (Needleman-Wunsch)
  mutate          - Apply point mutation(s) (e.g. mutation='A42V,K7R')
  hydrophobicity_profile - Sliding-window Kyte-Doolittle hydropathy profile
  batch_analyze   - Analyze multiple FASTA entries in a summary table
  structure_stats - Parse a PDB file/content: chains, atoms, B-factors

STRUCTURE:
  fold            - Predict 3D structure using Boltz-2 (boltz_2 skill)
  dock            - Protein-ligand docking and binding affinity (Boltz-2)
  visualize       - Generate 3D structure viewer (HTML)
  download_structure - Download PDB/AlphaFold structure
  search_structure - Search for protein structures

DESIGN:
  design          - Get design suggestions (stability, expression, binding)
  design_from_text - Design protein from natural language (uses Evo2 skill)
  design_from_proto_language - Design via Evo2, heuristic fallback
  codon_optimize  - Codon-optimize a protein sequence for a host
                    (host='e_coli' or 'human'; approximate weights)
  optimize_inducer - Optimize an inducer (peptide OR SMILES) against a
                    receptor: receptor=, inducer=, mode='quick'|'advanced',
                    rounds=, variants_per_round=, boltz_budget=,
                    goals={affinity,solubility,stability,bioavailability},
                    dry_run=True (offline property-only test)

NATURAL LANGUAGE:
  natural_language - Process natural language prompts
    Examples:
      "Design a protein that binds ATP"
      "Download and analyze the structure of insulin"
      "Search for structures of kinase proteins"
      "Research protein folding mechanisms"
      "Get the PDB structure for 1CRN"

INTEGRATIONS:
  Real skills used by this lab:
    boltz_2       - Structure prediction / docking / affinity
    evo2          - Generative DNA/protein design from text
    web_crawler   - Firecrawl-powered web search & structure downloads
  Proto-tools bridges (predict/score/design/compare) use Boltz-2 where
  possible; scoring/comparison require a separate proto-tools installation.

RESEARCH:
  research_topic  - Research protein topics via web search (Firecrawl/web_crawler)

UTILITIES:
  parse_fasta     - Parse FASTA format sequences
  convert         - Convert between sequence formats (fasta <-> raw)
  protein_to_dna  - Convert protein sequence to DNA nucleotides
  dna_to_protein  - Convert DNA sequence to protein amino acids
  clean_sequence  - Clean and validate protein sequence
  help            - Show this help

Usage: run(action="action_name", **kwargs)
"""
    return help_text.strip()














