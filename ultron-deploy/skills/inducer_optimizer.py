"""
Inducer Optimizer - Receptor-guided inducer improvement for Protein Lab.

Given a RECEPTOR (protein sequence) and an INDUCER (a peptide/protein
sequence OR a small-molecule SMILES), iteratively proposes improved variants
of the inducer with the goal of triggering the receptor more efficiently:

  * higher binding affinity / complex confidence   (Boltz-2)
  * better aqueous solubility                      (property model)
  * better structural / formulation stability      (property model)
  * better bioavailability                         (Lipinski-style rules)

How it works:
  1. Auto-detect inducer type: peptide (amino-acid sequence) or SMILES.
  2. Score the baseline inducer against the receptor:
       - peptide inducers  -> Boltz-2 two-chain complex, signal = ipTM /
         interface-pLDDT
       - SMILES inducers   -> Boltz-2 protein-ligand complex, signal = pIC50
  3. Generate goal-weighted variants:
       - peptides: solubility-driven surface substitutions, stability proline
         scan, charge balancing, terminal truncation
       - SMILES: aromatic methyl/halogen/hydroxyl scans (RDKit)
  4. Cheap property pre-filter -> only the top `boltz_budget` candidates per
     round get an expensive Boltz-2 affinity call.
  5. Rank by a weighted composite score; in advanced mode, seed the next
     round's variants from the current best.

Modes:
  quick     - 1 round, ~8 variants, ~5 Boltz calls   (default)
  advanced  - configurable rounds/variants via `rounds` and
              `variants_per_round`

Usage:
  result = run(action="optimize_inducer",
               receptor="MKT...",            # receptor protein sequence
               inducer="PEPTIDESEQ",          # peptide or SMILES (auto-detected)
               mode="quick")                  # or "advanced"
  # advanced knobs: rounds=3, variants_per_round=16, boltz_budget=6,
  #                 goals={"affinity":1.0,"solubility":0.7,...},
  #                 pocket_residues="12,45-50", dry_run=True, seed=7

dry_run=True skips all Boltz-2 calls and ranks on properties only (useful
offline / for testing the loop).
dry_run=False (default) now auto-starts Boltz-2 NIM if not reachable:
  - probes http://localhost:8000/v1/health/ready
  - if down and endpoint=local, tries `docker run --gpus all nvcr.io/nim/mit-boltz2:1.6.0`
  - if Docker missing or NIM not ready, falls back to property-only with clear
    instructions (install Docker Desktop or set NVIDIA_API_KEY for hosted API).
"""

import os
import re
import random
from typing import Dict, List, Optional, Any

NAME = "inducer_optimizer"
DESCRIPTION = ("Optimize an inducer molecule (peptide or small molecule) "
               "against a receptor for stronger, more drug-like activation: "
               "affinity, solubility, stability, bioavailability.")
TRIGGERS = [
    "optimize inducer", "inducer optimization", "improve ligand",
    "optimize ligand", "improve inducer", "ligand optimization",
    "receptor inducer", "agonist design", "optimize agonist",
    "improve peptide binding", "lead optimization",
]

try:
    _AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    _AGENT_ROOT = os.getcwd()

def _load_env():
    """Load .env into os.environ if not already present (like config.py does)."""
    env_path = os.path.join(_AGENT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("\"'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

_load_env()

AA20 = set("ACDEFGHIKLMNPQRSTVWY")

# Kyte-Doolittle hydropathy
_KD = {'A': 1.8, 'R': -4.5, 'N': -3.5, 'D': -3.5, 'C': 2.5, 'Q': -3.5,
       'E': -3.5, 'G': -0.4, 'H': -3.2, 'I': 4.5, 'L': 3.8, 'K': -3.9,
       'M': 1.9, 'F': 2.8, 'P': -1.6, 'S': -0.8, 'T': -0.7, 'W': -0.9,
       'Y': -1.3, 'V': 4.2}
_AA_MW = {'A': 89.09, 'R': 174.20, 'N': 132.12, 'D': 133.10, 'C': 121.16,
          'Q': 146.15, 'E': 147.13, 'G': 75.03, 'H': 155.16, 'I': 131.17,
          'L': 131.17, 'K': 146.19, 'M': 149.21, 'F': 165.19, 'P': 115.13,
          'S': 105.09, 'T': 119.12, 'W': 204.23, 'Y': 181.19, 'V': 117.15}

# Surface-hydrophobic residues are solubility liabilities when exposed;
# these are the conservative polar swaps we try first.
_HYDRO_SURFACE = set("LVIAFMW")
_POLAR_SWAPS = "STNQ"

_DEFAULT_GOALS = {
    "affinity": 1.0,
    "solubility": 0.7,
    "stability": 0.5,
    "bioavailability": 0.5,
}


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# Input handling / auto-detection
# --------------------------------------------------------------------------- #
def _clean_peptide(sequence):
    if not sequence:
        return None
    seq = re.sub(r'>.*\n', '', str(sequence))
    seq = re.sub(r'\s+', '', seq.upper())
    seq = ''.join(c for c in seq if c in AA20)
    return seq or None


def detect_inducer_type(inducer):
    """Return 'peptide' or 'smiles' for an inducer string."""
    s = str(inducer).strip()
    cleaned = _clean_peptide(s)
    if cleaned and len(cleaned) >= 8:
        raw = re.sub(r'\s+', '', s.upper())
        if len(cleaned) >= 0.8 * len(raw):
            return "peptide"
    return "smiles"


def validate_receptor(receptor):
    """The receptor must be a protein sequence (that is what Boltz folds)."""
    seq = _clean_peptide(receptor)
    if not seq or len(seq) < 10:
        raise ValueError(
            "Receptor must be a protein sequence of at least 10 amino acids.")
    return seq


# --------------------------------------------------------------------------- #
# Property models
# --------------------------------------------------------------------------- #
def peptide_props(seq):
    n = len(seq)
    mw = sum(_AA_MW.get(a, 110.0) for a in seq) - 18.02 * (n - 1)
    gravy = sum(_KD.get(a, 0.0) for a in seq) / n
    pos = sum(seq.count(a) for a in "KRH")
    neg = sum(seq.count(a) for a in "DE")
    charge = pos - neg
    hydro_frac = sum(1 for a in seq if a in "AILVFWMPGC") / n
    # simplified instability proxy: unstable dipeptides + low Pro/Gly content
    unstable_dp = sum(1 for i in range(n - 1)
                      if seq[i:i + 2] in ("DE", "ED", "DG", "GD", "NE", "EN"))
    instability = 10.0 * unstable_dp / max(1, n - 1)
    return {"mw": round(mw, 1), "gravy": round(gravy, 3),
            "net_charge": charge, "hydrophobic_frac": round(hydro_frac, 3),
            "instability_index": round(instability, 2), "length": n}


def peptide_subscores(props):
    gravy = props["gravy"]
    charge = props["net_charge"]
    hf = props["hydrophobic_frac"]
    instab = props["instability_index"]
    mw = props["mw"]

    solubility = _clip(0.5 - 0.15 * gravy + min(abs(charge), 6) * 0.04
                       - max(0.0, hf - 0.45) * 1.5)
    stability = _clip(1.0 - instab / 60.0 - max(0.0, hf - 0.55) * 0.8)
    bioavail = _clip(1.0 - max(0.0, mw - 5000.0) / 10000.0
                     - max(0.0, hf - 0.6) * 0.8)
    return {"solubility": round(solubility, 3),
            "stability": round(stability, 3),
            "bioavailability": round(bioavail, 3)}


def smiles_props(smiles):
    """RDKit-based drug-like properties. Returns dict; values may be None if
    RDKit is missing or the molecule cannot be parsed."""
    out = {"mw": None, "logp": None, "tpsa": None, "hbd": None, "hba": None,
           "rotatable_bonds": None, "lipinski_violations": None,
           "valid": False}
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors, Lipinski
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return out
        mw = Descriptors.MolWt(mol)
        logp = Crippen.MolLogP(mol)
        tpsa = rdMolDescriptors.CalcTPSA(mol)
        hbd = Lipinski.NumHDonors(mol)
        hba = Lipinski.NumHAcceptors(mol)
        rotb = rdMolDescriptors.CalcNumRotatableBonds(mol)
        viol = int(mw > 500) + int(logp > 5) + int(hbd > 5) + int(hba > 10)
        out.update({"mw": round(mw, 1), "logp": round(logp, 2),
                    "tpsa": round(tpsa, 1), "hbd": hbd, "hba": hba,
                    "rotatable_bonds": rotb, "lipinski_violations": viol,
                    "valid": True})
    except ImportError:
        pass
    except Exception:
        pass
    return out


def smiles_subscores(props):
    if not props.get("valid"):
        return {"solubility": 0.5, "stability": 0.5, "bioavailability": 0.5}
    logp = props["logp"]
    tpsa = props["tpsa"] or 0.0
    rotb = props["rotatable_bonds"] or 0
    viol = props["lipinski_violations"] or 0
    mw = props["mw"] or 500.0

    solubility = _clip(1.0 - abs(logp - 1.5) / 3.5 - max(0.0, tpsa - 140) / 200.0)
    stability = _clip(1.0 - max(0.0, rotb - 5) / 10.0 - max(0.0, mw - 600) / 1500.0)
    bioavail = _clip(1.0 - 0.25 * viol)
    return {"solubility": round(solubility, 3),
            "stability": round(stability, 3),
            "bioavailability": round(bioavail, 3)}


# --------------------------------------------------------------------------- #
# Variant generation
# --------------------------------------------------------------------------- #
def peptide_variants(seq, n, goals, rng):
    """Goal-weighted single-mutant / truncation variants of a peptide."""
    cands = []
    seen = {seq}

    def add(v):
        if v and v not in seen and len(v) >= 8 and set(v) <= AA20:
            seen.add(v)
            cands.append(v)

    positions = list(range(len(seq)))
    # Interleave mutation strategies so any budget samples all of them.
    strategies = []

    if goals.get("solubility", 0) > 0.15:
        strategies.append("sol")
    if goals.get("stability", 0) > 0.15:
        strategies.append("stab")
    if goals.get("affinity", 0) > 0.15:
        strategies.append("aff")

    if not strategies:
        strategies = ["sol", "stab", "aff"]

    made = 0
    guard = 0
    while made < n and guard < n * 30:
        guard += 1
        strat = strategies[made % len(strategies)]
        i = rng.choice(positions)
        aa = seq[i]
        if strat == "sol" and aa in _HYDRO_SURFACE:
            swap = _POLAR_SWAPS[rng.randrange(len(_POLAR_SWAPS))]
            add(seq[:i] + swap + seq[i + 1:])
            made += 1
        elif strat == "stab":
            # proline scan away from termini + charge balancing at termini
            if 1 < i < len(seq) - 1 and aa != "P":
                add(seq[:i] + "P" + seq[i + 1:])
                made += 1
            elif i == 0 and aa not in "DE":
                add("E" + seq[1:])   # N-terminal acidic cap-like residue
                made += 1
            elif i == len(seq) - 1 and aa not in "KR":
                add(seq[:-1] + "K")  # C-terminal basic cap-like residue
                made += 1
        elif strat == "aff":
            # conservative affinity tweaks: aromatic anchoring, H-bond donors
            if aa in "ASTG":
                add(seq[:i] + rng.choice("YW") + seq[i + 1:])
                made += 1
            elif aa in "DENQ":
                add(seq[:i] + rng.choice("KHR") + seq[i + 1:])
                made += 1

    # terminal truncation (peptide drugs often benefit from trimming)
    if len(seq) >= 14:
        add(seq[:-1])
    return cands[:n]


def smiles_variants(smiles, n):
    """Aromatic-substitution analogs: methyl / halogen / hydroxyl scans."""
    variants = []
    try:
        from rdkit import Chem
    except ImportError:
        return [], "rdkit not installed - cannot generate small-molecule analogs."

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return [], "Invalid base SMILES."

    try:
        # Use the original mol (without explicit Hs) to find aromatic C-H
        # sites: aromatic carbon with exactly 1 implicit H.
        targets = [a.GetIdx() for a in mol.GetAtoms()
                   if a.GetAtomicNum() == 6 and a.GetIsAromatic()
                   and a.GetTotalNumHs() == 1]
        if not targets:
            return [], "No aromatic C-H positions found for substitution."

        ref_smi = Chem.MolToSmiles(mol)
        subs = [("methyl", 6, False), ("fluoro", 9, False),
                ("chloro", 17, False), ("hydroxy", 8, True)]
        for idx in targets:
            for _name, atomic_num, _needs_o in subs:
                if len(variants) >= n * 2:  # headroom for dedupe/filtering
                    break
                em = Chem.EditableMol(mol)
                new_atom = em.AddAtom(Chem.Atom(atomic_num))
                em.AddBond(idx, new_atom, Chem.BondType.SINGLE)
                try:
                    cand = em.GetMol()
                    Chem.SanitizeMol(cand)
                    smi = Chem.MolToSmiles(cand)
                    if smi and smi != ref_smi and smi not in variants:
                        variants.append(smi)
                except Exception:
                    continue
        return variants[:n], None
    except Exception as e:
        return [], "Analog generation failed: %s" % e


# --------------------------------------------------------------------------- #
# Boltz-2 NIM auto-start helpers
# --------------------------------------------------------------------------- #
def _is_nim_ready(base_url, timeout=3, endpoint_type=None, api_key=None):
    """Probe NIM health endpoint. For nvidia_hosted, api_key presence = ready."""
    # Hosted NIM is always ready if we have an API key - don't probe without auth
    if (endpoint_type or "").lower() in ("nvidia_hosted", "nvidia", "hosted", "nvcf"):
        return bool(api_key)
    try:
        import requests
        for path in ("/v1/health/ready", "/v1/metadata", "/health"):
            try:
                r = requests.get(base_url.rstrip("/") + path, timeout=timeout)
                if r.status_code == 200:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def _try_start_nim(base_url, api_key, endpoint_type, log_lines=None):
    """
    Best-effort auto-start for Boltz-2 NIM when dry_run=False and NIM is down.
    Tries (in order):
      1. If endpoint_type is nvidia_hosted and api_key present -> already ready, just check.
      2. If docker is available -> `docker run --gpus all -p 8000:8000 nvcr.io/nim/mit-boltz2:1.6.0`
         (detached, with --rm). Waits up to 90s for /v1/health/ready.
      3. Otherwise -> instructions.

    Returns (started: bool, message: str). Never raises.
    """
    import shutil, subprocess, time

    def _log(msg):
        if log_lines is not None:
            log_lines.append(msg)

    # Hosted endpoint - nothing to start locally, just report status
    if (endpoint_type or "").lower() in ("nvidia_hosted", "nvidia", "hosted", "nvcf"):
        if not api_key:
            _log("  -> NVIDIA hosted endpoint selected but NVIDIA_API_KEY is not set.")
            _log("     Set NVIDIA_API_KEY in .env or pass api_key='...' to use hosted NIM.")
            return False, "missing_api_key"
        _log(f"  -> Using NVIDIA hosted Boltz-2 at {base_url} (api_key ****{api_key[-4:] if len(api_key)>4 else ''})")
        return False, "hosted_ready"

    # Check docker
    docker = shutil.which("docker")
    if not docker:
        _log("  -> Docker not found in PATH, cannot auto-start local NIM.")
        _log("     Install Docker Desktop or set BOLTZ2_BASE_URL to a running NIM,")
        _log("     or set NVIDIA_API_KEY + BOLTZ2_ENDPOINT_TYPE=nvidia_hosted for hosted API.")
        _log("     Falling back to property-only scoring for this run.")
        return False, "no_docker"

    # Check if container already running
    try:
        ps = subprocess.run([docker, "ps", "--format", "{{.Names}} {{.Image}}"],
                            capture_output=True, text=True, timeout=10)
        if "boltz2" in ps.stdout.lower() or "mit-boltz2" in ps.stdout.lower():
            _log("  -> Found existing boltz2 container, waiting for health...")
            for _ in range(30):
                if _is_nim_ready(base_url, timeout=2):
                    _log("  -> NIM became ready.")
                    return True, "already_running"
                time.sleep(3)
    except Exception:
        pass

    # Try to start NIM container
    # Use the official NIM image; requires `docker login nvcr.io` once and GPU.
    image = os.environ.get("BOLTZ2_IMAGE", "nvcr.io/nim/mit-boltz2:1.6.0")
    port = "8000"
    # Try to infer port from base_url (e.g. http://localhost:8001 -> 8001)
    try:
        import urllib.parse
        parsed = urllib.parse.urlparse(base_url)
        if parsed.port:
            port = str(parsed.port)
    except Exception:
        pass

    cmd = [docker, "run", "-d", "--rm", "--gpus", "all",
           "-p", f"{port}:8000",
           "--name", "boltz2-nim-autostart",
           image]
    _log(f"  -> Attempting: {' '.join(cmd)}")
    _log("     (first pull can be ~10GB and take several minutes)")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            _log(f"  -> Docker run failed: {result.stderr.strip()[:400]}")
            # Try without --gpus as fallback (CPU-only hosts)
            cmd2 = [docker, "run", "-d", "--rm",
                    "-p", f"{port}:8000",
                    "--name", "boltz2-nim-autostart",
                    image]
            _log(f"  -> Retrying without --gpus: {' '.join(cmd2)}")
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
            if result2.returncode != 0:
                _log(f"  -> Still failed: {result2.stderr.strip()[:400]}")
                return False, result2.stderr.strip()[:200]
            _log(f"  -> Container started: {result2.stdout.strip()[:80]}")
        else:
            _log(f"  -> Container started: {result.stdout.strip()[:80]}")
    except Exception as e:
        _log(f"  -> Could not start container: {e}")
        return False, str(e)

    # Wait for health
    _log("  -> Waiting for NIM to become ready (up to 90s)...")
    for i in range(30):
        if _is_nim_ready(base_url, timeout=3):
            _log("  -> Boltz-2 NIM is ready!")
            return True, "started"
        time.sleep(3)
    _log("  -> NIM did not become ready in time. Check `docker logs boltz2-nim-autostart`.")
    _log("     Continuing with property-only fallback for now.")
    return False, "timeout"


def _ensure_nim_if_needed(cfg, log_lines=None):
    """If NIM is down and cfg says local, try to auto-start. Returns True if ready."""
    try:
        # reuse boltz_2._resolve_config to get canonical base_url/endpoint
        try:
            from skills import boltz_2 as _b2
        except ImportError:
            try:
                import boltz_2 as _b2
            except ImportError:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "boltz_2", os.path.join(_AGENT_ROOT, "skills", "boltz_2.py"))
                _b2 = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(_b2)
        base_url, api_key, endpoint_type = _b2._resolve_config(**cfg)
    except Exception:
        base_url = cfg.get("base_url") or os.environ.get("BOLTZ2_BASE_URL") or "http://localhost:8000"
        api_key = cfg.get("api_key") or os.environ.get("NVIDIA_API_KEY")
        endpoint_type = (cfg.get("endpoint_type") or os.environ.get("BOLTZ2_ENDPOINT_TYPE") or "local").lower()

    _load_env()
    # Re-resolve after ensuring env is loaded (in case .env had hosted config)
    try:
        base_url2, api_key2, endpoint_type2 = _b2._resolve_config(**cfg)
        base_url, api_key, endpoint_type = base_url2, api_key2, endpoint_type2
    except Exception:
        pass

    if _is_nim_ready(base_url, endpoint_type=endpoint_type, api_key=api_key):
        if log_lines is not None and endpoint_type in ("nvidia_hosted", "nvidia", "hosted", "nvcf"):
            log_lines.append(f"  Boltz-2 NIM ready at {base_url} (endpoint={endpoint_type})")
        return True

    # Not ready -> try auto-start
    if log_lines is not None:
        log_lines.append(f"  Boltz-2 NIM not reachable at {base_url} (endpoint={endpoint_type}), attempting auto-start...")
    _try_start_nim(base_url, api_key, endpoint_type, log_lines=log_lines)
    # Re-check after attempt
    return _is_nim_ready(base_url, endpoint_type=endpoint_type, api_key=api_key)


# --------------------------------------------------------------------------- #
# Boltz-2 scoring
# --------------------------------------------------------------------------- #
def _get_boltz_client(cfg):
    _load_env()
    try:
        from skills import boltz_2
    except ImportError:
        try:
            import boltz_2
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "boltz_2", os.path.join(_AGENT_ROOT, "skills", "boltz_2.py"))
            boltz_2 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(boltz_2)

    client_cls, _ep = boltz_2._load_client()
    base_url, api_key, endpoint_type = boltz_2._resolve_config(**cfg)
    return client_cls(
        base_url=base_url, api_key=api_key, endpoint_type=endpoint_type,
        timeout=cfg.get("timeout", 600.0),
        poll_seconds=cfg.get("poll_seconds", 20))


def _score_peptide_binding(client, receptor, candidate, cfg, outdir):
    """Two-chain complex prediction; returns dict with ipTM/interface-pLDDT."""
    from boltz2_client import Polymer
    polymers = [
        Polymer(id="R", molecule_type="protein", sequence=receptor),
        Polymer(id="I", molecule_type="protein", sequence=candidate),
    ]
    resp = client.predict_with_advanced_parameters(
        polymers=polymers,
        recycling_steps=cfg.get("recycling_steps", 3),
        sampling_steps=cfg.get("sampling_steps", 50),
        output_dir=outdir,
    )
    iptm = None
    iplddt = None
    for attr, store in (("iptm_scores", "iptm"),
                        ("complex_iplddt_scores", "iplddt")):
        v = getattr(resp, attr, None)
        if v:
            val = float(list(v)[0]) if hasattr(v, "__iter__") else float(v)
            if store == "iptm":
                iptm = val
            else:
                iplddt = val
    primary = iptm if iptm is not None else iplddt
    metric = "ipTM" if iptm is not None else "interface-pLDDT"
    return {"metric": metric, "value": primary,
            "iptm": iptm, "interface_plddt": iplddt}


def _score_ligand_affinity(client, receptor, smiles, cfg, outdir):
    """Protein-ligand complex with affinity head; returns pIC50."""
    resp = client.predict_protein_ligand_complex(
        protein_sequence=receptor,
        ligand_smiles=smiles,
        pocket_residues=cfg.get("pocket_residues"),
        predict_affinity=True,
        recycling_steps=cfg.get("recycling_steps", 3),
        sampling_steps=cfg.get("sampling_steps", 50),
        save_structures=True,
        output_dir=outdir,
    )
    pic50 = None
    affs = getattr(resp, "affinities", None)
    if affs:
        try:
            for _lig_id, aff in affs.items():
                pic = getattr(aff, "affinity_pic50", None)
                if pic:
                    pic50 = float(pic[0]) if hasattr(pic, "__iter__") else float(pic)
                    break
        except Exception:
            pass
    return {"metric": "pIC50", "value": pic50}


def score_affinity(receptor, structure, itype, cfg, dry_run=False):
    """Boltz-2 binding score for one candidate. Returns (result_dict, outdir)."""
    try:
        from skills.boltz_2 import _make_outdir  # reuse output-dir convention
    except ImportError:
        from boltz_2 import _make_outdir
    try:
        client = _get_boltz_client(cfg)
        outdir = _make_outdir(None)
        if itype == "peptide":
            r = _score_peptide_binding(client, receptor, structure, cfg, outdir)
        else:
            r = _score_ligand_affinity(client, receptor, structure, cfg, outdir)
        return r, str(outdir)
    except Exception as e:
        return {"metric": None, "value": None, "error": str(e)}, None


# --------------------------------------------------------------------------- #
# Composite scoring
# --------------------------------------------------------------------------- #
def composite_score(subscores, affinity_norm, goals):
    w_aff = goals.get("affinity", 1.0)
    w_sol = goals.get("solubility", 0.7)
    w_stab = goals.get("stability", 0.5)
    w_bio = goals.get("bioavailability", 0.5)
    total_w = (w_aff if affinity_norm is not None else 0.0) + w_sol + w_stab + w_bio
    if total_w <= 0:
        return 0.0
    s = 0.0
    if affinity_norm is not None:
        s += w_aff * affinity_norm
    s += w_sol * subscores.get("solubility", 0.5)
    s += w_stab * subscores.get("stability", 0.5)
    s += w_bio * subscores.get("bioavailability", 0.5)
    return s / total_w


def _norm_affinity(itype, value):
    if value is None:
        return None
    if itype == "peptide":
        return _clip((value - 0.2) / (0.85 - 0.2))   # ipTM window
    return _clip((value - 4.0) / (10.0 - 4.0))       # pIC50 window


def property_only_score(structure, itype):
    """Cheap pre-filter score (no Boltz). Used to rank candidates before
    spending expensive affinity calls."""
    if itype == "peptide":
        props = peptide_props(structure)
        subs = peptide_subscores(props)
    else:
        props = smiles_props(structure)
        subs = smiles_subscores(props)
    return composite_score(subs, None, _DEFAULT_GOALS)


# --------------------------------------------------------------------------- #
# Main optimization loop
# --------------------------------------------------------------------------- #
def optimize_inducer(receptor=None, inducer=None, mode="quick", rounds=None,
                     variants_per_round=None, boltz_budget=None, goals=None,
                     pocket_residues=None, dry_run=False, seed=7,
                     **boltz_cfg):
    if not receptor:
        return "No receptor provided. Pass receptor='<protein sequence>'."
    if not inducer:
        return ("No inducer provided. Pass inducer='<peptide sequence or "
                "SMILES>'.")

    rec = validate_receptor(receptor)
    itype = detect_inducer_type(inducer)
    goals = {**_DEFAULT_GOALS, **(goals or {})}
    rng = random.Random(seed)

    quick = (str(mode).lower().strip() != "advanced")
    rounds = int(rounds) if rounds else (1 if quick else 3)
    variants_per_round = int(variants_per_round) if variants_per_round else (
        8 if quick else 16)
    boltz_budget = int(boltz_budget) if boltz_budget else (5 if quick else 6)

    lines = []
    lines.append("INDUCER OPTIMIZATION RUN")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Mode:             %s" % ("QUICK" if quick else "ADVANCED"))
    lines.append("Inducer type:     %s%s" % (
        itype, " (auto-detected)" if True else ""))
    lines.append("Rounds:           %d" % rounds)
    lines.append("Variants/round:   %d" % variants_per_round)
    lines.append("Boltz calls/round: %d" % (0 if dry_run else boltz_budget))
    lines.append("Goals (weights):  " + ", ".join(
        "%s=%.2f" % (k, v) for k, v in sorted(goals.items()) if v > 0))
    lines.append("Receptor:         %d aa (%s...)" % (len(rec), rec[:20]))
    lines.append("Baseline inducer: %s" % (inducer if itype == "smiles"
                                               else "%s (%d aa)" % (inducer[:40], len(inducer))))
    if dry_run:
        lines.append("DRY RUN: Boltz-2 skipped - property-only ranking.")
    lines.append("")

    # ---- Round 0: baseline ----
    base_structure = inducer if itype == "smiles" else _clean_peptide(inducer)
    if itype == "peptide" and (not base_structure or len(base_structure) < 8):
        return "Inducer peptide too short (min 8 aa after cleaning)."

    baseline_aff = {"metric": None, "value": None}
    if not dry_run:
        # --- Auto-start Boltz-2 NIM if needed (dry_run=False contract) ---
        _nim_logs = []
        _nim_ready = _ensure_nim_if_needed({**boltz_cfg, "pocket_residues": pocket_residues}, log_lines=_nim_logs)
        for _l in _nim_logs:
            lines.append(_l)
        if not _nim_ready:
            lines.append("  Proceeding anyway - Boltz calls will be attempted and fall back if NIM is still unavailable.")
        lines.append("Scoring baseline vs receptor with Boltz-2 ...")
        baseline_aff, _outdir = score_affinity(rec, base_structure, itype,
                                               {**boltz_cfg, "pocket_residues": pocket_residues})
        if baseline_aff.get("error"):
            lines.append("  WARNING: baseline Boltz call failed: %s"
                         % baseline_aff["error"])
            lines.append("  Continuing with property-only ranking.")
        elif baseline_aff.get("value") is not None:
            lines.append("  Baseline %s: %.3f" % (baseline_aff["metric"],
                                                  baseline_aff["value"]))
    else:
        baseline_aff = {"metric": "ipTM" if itype == "peptide" else "pIC50",
                        "value": None}

    leaderboard = [{
        "name": "WT (baseline)",
        "structure": base_structure,
        "type": itype,
        "affinity": baseline_aff,
        "affinity_norm": _norm_affinity(itype, baseline_aff.get("value")),
        "generation": 0,
        "boltz_scored": not dry_run and baseline_aff.get("value") is not None,
    }]

    current_best = base_structure

    for rnd in range(1, rounds + 1):
        lines.append("-" * 60)
        lines.append("ROUND %d / %d" % (rnd, rounds))
        lines.append("-" * 60)

        # ---- generate variants seeded from current best ----
        if itype == "peptide":
            cands = peptide_variants(current_best, variants_per_round, goals, rng)
            gen_note = None
        else:
            cands, gen_note = smiles_variants(current_best, variants_per_round)
            if gen_note:
                lines.append("Variant generation note: %s" % gen_note)

        already = {e["structure"] for e in leaderboard}
        cands = [c for c in cands if c not in already]
        if not cands:
            lines.append("  No new unique variants generated - stopping early.")
            break
        lines.append("  Generated %d unique variants." % len(cands))

        # ---- cheap property prefilter ----
        scored_cheap = [(c, property_only_score(c, itype)) for c in cands]
        scored_cheap.sort(key=lambda x: x[1], reverse=True)
        shortlist = [c for c, _s in scored_cheap[:boltz_budget]]

        # ---- evaluate candidates ----
        for cand in shortlist:
            entry_name = ("V%d.%d" % (rnd, len(leaderboard)))
            if dry_run:
                aff = {"metric": ("ipTM" if itype == "peptide" else "pIC50"),
                       "value": None}
                aff_norm = None
                outdir = None
            else:
                aff, outdir = score_affinity(
                    rec, cand, itype, {**boltz_cfg, "pocket_residues": pocket_residues})
                aff_norm = _norm_affinity(itype, aff.get("value"))
            entry = {
                "name": entry_name,
                "structure": cand,
                "type": itype,
                "affinity": aff,
                "affinity_norm": aff_norm,
                "generation": rnd,
                "boltz_scored": aff_norm is not None,
                "outdir": outdir,
            }
            leaderboard.append(entry)

        # ---- rank & pick round winner ----
        for e in leaderboard:
            if e["type"] == "peptide":
                subs = peptide_subscores(peptide_props(e["structure"]))
            else:
                subs = smiles_subscores(smiles_props(e["structure"]))
            e["_subs"] = subs
            e["_total_score"] = composite_score(subs, e["affinity_norm"], goals)
        ranked = sorted(leaderboard, key=lambda e: e["_total_score"], reverse=True)

        best = ranked[0]
        if best["structure"] != current_best:
            current_best = best["structure"]
            lines.append("  New best: %s (%s)"
                         % (best["name"], _short_struct(best)))
        else:
            lines.append("  Best unchanged (%s); converging."
                         % best["name"])
        lines.append("")

    # ---- final report ----
    for e in leaderboard:
        if e["type"] == "peptide":
            e["_props"] = peptide_props(e["structure"])
            e["_subs"] = peptide_subscores(e["_props"])
        else:
            e["_props"] = smiles_props(e["structure"])
            e["_subs"] = smiles_subscores(e["_props"])
        e["_total_score"] = composite_score(e["_subs"], e["affinity_norm"], goals)

    ranked = sorted(leaderboard, key=lambda e: e["_total_score"], reverse=True)
    best = ranked[0]
    base_entry = next((e for e in leaderboard if e["generation"] == 0), None)

    lines.append("")
    lines.append("=" * 60)
    lines.append("FINAL LEADERBOARD (top 10)")
    lines.append("=" * 60)
    header = "  %-10s %-8s %-8s %-8s %-8s %-8s %s"
    lines.append(header % ("Rank", "Affinity", "Solub", "Stab", "BioAvail",
                           "TOTAL", "Candidate"))

    def fmt_aff(e):
        v = e["affinity"].get("value")
        if v is None:
            return "-"
        return "%.3f" % v

    for rank, e in enumerate(ranked[:10], 1):
        s = e["_subs"]
        lines.append(header % (
            rank, fmt_aff(e),
            "%.2f" % s.get("solubility", 0),
            "%.2f" % s.get("stability", 0),
            "%.2f" % s.get("bioavailability", 0),
            "%.3f" % e["_total_score"],
            "%s %s" % (e["name"], _short_struct(e))))

    # ---- improvement summary ----
    lines.append("")
    lines.append("BEST INDUCER")
    lines.append("-" * 60)
    lines.append("  Structure: %s" % best["structure"])
    if base_entry is not None and best is not base_entry:
        b_aff = best["affinity"].get("value")
        w_aff = base_entry["affinity"].get("value")
        if b_aff is not None and w_aff is not None:
            delta = b_aff - w_aff
            lines.append("  Affinity delta vs baseline: %+.3f %s (%.3f -> %.3f)"
                         % (delta, best["affinity"]["metric"], w_aff, b_aff))
        bp, wp = best["_props"], base_entry["_props"]
        if best["type"] == "peptide":
            lines.append("  Solubility proxy (GRAVY):   %.3f -> %.3f (lower is better)"
                         % (wp["gravy"], bp["gravy"]))
            lines.append("  Instability index:          %.2f -> %.2f (lower is better)"
                         % (wp["instability_index"], bp["instability_index"]))
            lines.append("  Net charge:                 %+d -> %+d"
                         % (wp["net_charge"], bp["net_charge"]))
        else:
            for k in ("logp", "tpsa", "mw"):
                if wp.get(k) is not None and bp.get(k) is not None:
                    lines.append("  %-26s %s -> %s" % (k + ":", wp[k], bp[k]))
            if (wp.get("lipinski_violations") is not None
                    and bp.get("lipinski_violations") is not None):
                lines.append("  lipinski_violations:        %d -> %d"
                             % (wp["lipinski_violations"], bp["lipinski_violations"]))
    elif best is base_entry:
        lines.append("  No variant beat the wild-type inducer under the current")
        lines.append("  goal weights. Consider raising 'variants_per_round',")
        lines.append("  using mode='advanced', or adjusting goal weights.")

    lines.append("")
    lines.append("Composite scores combine goal-weighted affinity (Boltz-2 %s)"
                 % ("ipTM" if itype == "peptide" else "pIC50"))
    lines.append("with solubility / stability / bioavailability proxies.")
    if dry_run:
        lines.append("(Dry run: '-'* means candidate was NOT affinity-scored.)")
    lines.append("")
    lines.append("NOTE: computational predictions only - validate experimentally.")

    return "\n".join(lines)


def _short_struct(entry):
    s = entry["structure"]
    if entry["type"] == "peptide":
        return "%s...(%d aa)" % (s[:18], len(s))
    return s[:44] + ("..." if len(s) > 44 else "")


# --------------------------------------------------------------------------- #
# Skill API entry point
# --------------------------------------------------------------------------- #
def run(action="optimize_inducer", **kwargs):
    """
    Entry point. Currently supports a single action: optimize_inducer.
    All parameters forwarded to optimize_inducer().
    """
    if action in ("optimize_inducer", "help"):
        if action == "help":
            return __doc__ or DESCRIPTION
        return optimize_inducer(**kwargs)
    return ("Unknown action '%s' for inducer_optimizer. "
            "Use action='optimize_inducer'." % action)


if __name__ == "__main__":
    print(run(action="optimize_inducer",
              receptor="MKTAYIAKQRQISFVKSHFSRQLEERLRLIEVLLRIG",
              inducer="FLPIGAETTMPGYSV",
              dry_run=True))
