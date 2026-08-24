"""
Boltz-2 biomolecular structure prediction & protein design.

Wraps NVIDIA Boltz-2 (the bundled `boltz2_client` package) so that Ultron can
fold proteins, build protein-ligand / covalent / DNA-protein complexes and
predict binding affinity — all through the agent skill API.

Endpoints supported (env config):
  * Local NIM         : BOLTZ2_BASE_URL=http://localhost:8000  (default)
  * NVIDIA GPU hosted : BOLTZ2_BASE_URL=https://health.api.nvidia.com
                        BOLTZ2_ENDPOINT_TYPE=nvidia_hosted  + NVIDIA_API_KEY
  * AWS SageMaker     : BOLTZ2_ENDPOINT_TYPE=sagemaker (+ AWS creds / SAGEMAKER_ENDPOINT_NAME)

Auth/endpoint can also be passed per-call via run() kwargs.
"""

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

NAME = "boltz_2"
DESCRIPTION = "Design and predict biomolecular structures with NVIDIA Boltz-2: protein folding, protein-ligand complexes, covalent complexes, DNA-protein complexes, multimer assembly, virtual screening and binding-affinity (pIC50) prediction."
TRIGGERS = [
    "boltz", "boltz-2", "boltz 2",
    "protein fold", "protein folding", "fold protein",
    "predict protein", "protein predict",
    "protein-ligand", "ligand complex", "binding affinity", "pic50", "potency",
    "covalent complex", "dna-protein", "dna protein complex", "multimer",
    "de novo protein", "biomolecular",
]

# Root of the AGENT project (two levels up: skills/ -> AGENT root).
# Guarded with try/except because skills._load_meta execs skill sources without
# defining __file__ (real imports via importlib provide it).
try:
    _AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    _AGENT_ROOT = os.getcwd()

# Directories that already contain the `boltz2_client` package (extracted repos).
_BOLTZ2_SOURCE_DIRS = [
    os.path.join(_AGENT_ROOT, "digital-biology-examples-main", "examples", "nims", "boltz-2"),
    os.path.join(_AGENT_ROOT, "proto-tools-main", "proto-tools-main", "proto_tools",
                 "tools", "structure_prediction", "boltz2"),
]

_DEFAULT_OUTPUT_DIR = os.path.join(_AGENT_ROOT, "output", "boltz2")

# Optional deps boltz2_client imports that may not be installed yet.
# Map: module import name -> pip package name. (httpx, pydantic, aiofiles,
# aiohttp were already present in this env.)
_EXTRA_DEPS = [
    ("rich", "rich"),
    ("yaml", "PyYAML"),
    ("pandas", "pandas"),
    ("aiofiles", "aiofiles"),
    ("aiohttp", "aiohttp"),
]


def _find_client_source():
    """Return the directory that contains the boltz2_client package, or None."""
    for d in _BOLTZ2_SOURCE_DIRS:
        if os.path.isdir(os.path.join(d, "boltz2_client")):
            return d
    return None


def _install_deps():
    """Auto-install missing optional deps; return list of (module,pip) still missing."""
    missing = [(m, p) for (m, p) in _EXTRA_DEPS if not _has_module(m)]
    if not missing:
        return []
    try:
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check"] + [p for (_m, p) in missing],
            check=False,
        )
    except Exception:
        pass
    return [(m, p) for (m, p) in missing if not _has_module(m)]


def _has_module(mod):
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


def _load_client():
    """Import the bundled boltz2_client sync client class."""
    _install_deps()
    src = _find_client_source()
    if not src:
        raise RuntimeError("Could not locate the bundled boltz2_client package.")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        from boltz2_client import Boltz2SyncClient, EndpointType
    except ImportError as e:
        raise RuntimeError(
            "Unable to import boltz2_client. Missing dependency: %s. "
            "Run: pip install rich aiofiles aiohttp httpx pydantic pyyaml py3Dmol" % e
        ) from e
    return Boltz2SyncClient, EndpointType


def _resolve_config(**kw):
    """Resolve endpoint + auth from kwargs or environment."""
    base_url = kw.get("base_url") or os.environ.get("BOLTZ2_BASE_URL") or "http://localhost:8000"
    api_key = kw.get("api_key") or os.environ.get("NVIDIA_API_KEY")
    ep = (kw.get("endpoint_type") or os.environ.get("BOLTZ2_ENDPOINT_TYPE") or "local").lower()
    if ep in ("nvidia_hosted", "nvidia", "hosted", "nvcf"):
        ep = "nvidia_hosted"
        if not api_key:
            raise ValueError(
                "NVIDIA hosted endpoint requires an API key. Set NVIDIA_API_KEY "
                "or pass api_key=...")
    elif ep in ("sagemaker", "aws"):
        ep = "sagemaker"
    else:
        ep = "local"
    return base_url, api_key, ep


def _make_outdir(output_dir):
    out = Path(output_dir) if output_dir else Path(_DEFAULT_OUTPUT_DIR)
    job = uuid.uuid4().hex[:8]
    d = out / ("%s_%s" % (datetime.now().strftime("%Y%m%d_%H%M%S"), job))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fmt_list(v):
    vals = [float(x) for x in v[:6]]
    return ", ".join("%.3f" % x for x in vals) + ("..." if len(v) > 6 else "")


def _fmt_scores(resp):
    lines = []
    if getattr(resp, "confidence_scores", None):
        lines.append("confidence: %s" % _fmt_list(resp.confidence_scores))
    for attr, label in (
        ("ptm_scores", "pTM"), ("iptm_scores", "ipTM"),
        ("complex_plddt_scores", "pLDDT"), ("complex_iplddt_scores", "interface-pLDDT"),
        ("complex_pde_scores", "PDE"), ("complex_ipde_scores", "interface-PDE"),
    ):
        v = getattr(resp, attr, None)
        if v:
            lines.append("%s: %s" % (label, _fmt_list(v)))
    return lines


def _fmt_affinities(resp):
    if not getattr(resp, "affinities", None):
        return []
    lines = []
    try:
        for lig_id, aff in resp.affinities.items():
            pic = getattr(aff, "affinity_pic50", None)
            if pic:
                lines.append("%s pIC50: %.3f" % (lig_id, float(pic[0])))
    except Exception:
        pass
    return lines


def _finalize(resp, outdir):
    parts = ["Boltz-2 prediction complete."]
    parts += _fmt_scores(resp)
    parts += _fmt_affinities(resp)
    parts.append("Outputs saved under: %s" % outdir)
    if os.path.isdir(outdir):
        filenames = sorted(os.listdir(outdir))
        if filenames:
            parts.append("Files: " + ", ".join(filenames))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Main entry point.
# --------------------------------------------------------------------------- #
def run(
    task="fold",
    sequence=None,
    sequences=None,
    protein_sequence=None,
    protein_sequences=None,
    dna_sequences=None,
    ligand_smiles=None,
    ligand_ccd=None,
    pocket_residues=None,
    predict_affinity=False,
    covalent_bonds=None,
    recycling_steps=3,
    sampling_steps=50,
    diffusion_samples=1,
    step_scale=1.638,
    output_dir=None,
    base_url=None,
    api_key=None,
    endpoint_type=None,
    timeout=600.0,
    poll_seconds=20,
    **kwargs,
):
    """
    Run a Boltz-2 structure-design job.

    task:
      fold          one protein sequence (sequence=...)
      multimer      several chains (sequences={"A": "...", "B": "..."})
      ligand        protein + ligand (ligand_smiles or ligand_ccd), optional affinity
      covalent      protein + CCD ligand with covalent_bonds constraints
      dna_protein   protein(s) + DNA sequence(s) complex

    Returns a human-readable summary string.
    """
    client_cls, EndpointType = _load_client()
    base_url, api_key, ep = _resolve_config(
        base_url=base_url, api_key=api_key, endpoint_type=endpoint_type)
    outdir = _make_outdir(output_dir)

    client = client_cls(
        base_url=base_url,
        api_key=api_key,
        endpoint_type=ep,
        timeout=timeout,
        poll_seconds=poll_seconds,
    )

    if task in ("ligand", "ligand_complex", "protein-ligand", "affinity"):
        if not ligand_smiles and not ligand_ccd:
            return "For task='ligand' provide ligand_smiles or ligand_ccd."
        resp = client.predict_protein_ligand_complex(
            protein_sequence=protein_sequence or sequence,
            ligand_smiles=ligand_smiles,
            ligand_ccd=ligand_ccd,
            pocket_residues=pocket_residues,
            predict_affinity=predict_affinity,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
            save_structures=True,
            output_dir=outdir,
        )
        return _finalize(resp, outdir)

    if task == "covalent":
        if not ligand_ccd or not covalent_bonds:
            return ("task='covalent' needs ligand_ccd and covalent_bonds "
                    "(list of (residue_idx, protein_atom, ligand_atom)).")
        resp = client.predict_covalent_complex(
            protein_sequence=protein_sequence or sequence,
            ligand_ccd=ligand_ccd,
            covalent_bonds=covalent_bonds,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
            output_dir=outdir,
        )
        return _finalize(resp, outdir)

    if task in ("dna", "dna_protein", "dna-protein"):
        if not protein_sequences:
            protein_sequences = [protein_sequence or sequence] if (protein_sequence or sequence) else None
        if not (protein_sequences and dna_sequences):
            return "task='dna_protein' needs protein_sequences and dna_sequences (lists)."
        resp = client.predict_dna_protein_complex(
            protein_sequences=protein_sequences,
            dna_sequences=dna_sequences,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
            output_dir=outdir,
        )
        return _finalize(resp, outdir)

    if task in ("multimer", "complex", "multimer_msa"):
        if not sequences:
            if protein_sequences:
                sequences = protein_sequences
            else:
                return "task='multimer' needs sequences (dict {chain_id: seq} or list of seqs)."
        from boltz2_client import Polymer
        items = sequences.items() if isinstance(sequences, dict) else enumerate(sequences)
        polymers = [
            Polymer(id=pid, molecule_type="protein", sequence=seq)
            for pid, seq in items
        ]
        resp = client.predict_with_advanced_parameters(
            polymers=polymers,
            recycling_steps=recycling_steps,
            sampling_steps=sampling_steps,
            output_dir=outdir,
        )
        return _finalize(resp, outdir)

    # default: fold
    seq = protein_sequence or sequence or (sequences if isinstance(sequences, str) else None)
    if not seq:
        return "No sequence provided. Pass sequence=... (task='fold')."
    resp = client.predict_protein_structure(
        sequence=seq,
        recycling_steps=recycling_steps,
        sampling_steps=sampling_steps,
        diffusion_samples=diffusion_samples,
        step_scale=step_scale,
        output_dir=outdir,
    )
    return _finalize(resp, outdir)
