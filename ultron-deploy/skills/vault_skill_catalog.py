NAME = "vault_skill_catalog"
DESCRIPTION = "Scan the Obsidian vault for existing skills organized by category, and find skills relevant to a user request."
TRIGGERS = ["find skill", "check skills", "search vault skills", "existing skills", "skill catalog", "what skills do i have"]

import os
import glob
import re
from typing import List, Dict, Any

VAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Ultron_brain")

# Category folders in the vault and their corresponding index files
SKILL_CATEGORIES = {
    "Thinking": {"folder": os.path.join("Skills", "Thinking"), "index": os.path.join("Skills", "Thinking Index")},
    "Scientific": {"folder": os.path.join("Skills", "Scientific"), "index": os.path.join("Skills", "Scientific Skills")},
    "Writing": {"folder": os.path.join("Skills", "Writing"), "index": os.path.join("Skills", "Writing Skills")},
    "Analysis": {"folder": os.path.join("Skills", "Analysis"), "index": os.path.join("Skills", "Analysis Skills")},
    "Code": {"folder": os.path.join("Skills", "Code"), "index": os.path.join("Skills", "Code Skills")},
    "Research": {"folder": os.path.join("Skills", "Research"), "index": os.path.join("Skills", "Research Skills")},
    "Productivity": {"folder": os.path.join("Skills", "Productivity"), "index": os.path.join("Skills", "Productivity Skills")},
    "Creative": {"folder": os.path.join("Skills", "Creative"), "index": os.path.join("Skills", "Creative Skills")},
    "Communication": {"folder": os.path.join("Skills", "Communication"), "index": os.path.join("Skills", "Communication Skills")},
    "Agent": {"folder": os.path.join("Skills", "Agent"), "index": os.path.join("Skills", "Agent Skills")},
    "CAD": {"folder": os.path.join("Skills", "CAD"), "index": os.path.join("Skills", "CAD Skills")},
    "Chemistry": {"folder": os.path.join("Skills", "Chemistry"), "index": os.path.join("Skills", "Chemistry Skills")},
    "ChemClaw": {"folder": os.path.join("Skills", "ChemClaw"), "index": os.path.join("Skills", "ChemClaw Skills")},
    "Medical": {"folder": os.path.join("Skills", "Medical"), "index": os.path.join("Skills", "Medical Skills")},
    "Biomedical": {"folder": os.path.join("Skills", "Biomedical"), "index": os.path.join("Skills", "Biomedical Skills")},
    "Circuit": {"folder": os.path.join("Skills", "Circuit"), "index": os.path.join("Skills", "Circuit Skills")},
    "Mechanical": {"folder": os.path.join("Skills", "Mechanical"), "index": os.path.join("Skills", "Mechanical Skills")},
    "Proto-Language": {"folder": os.path.join("Skills", "Proto-Language"), "index": os.path.join("Skills", "Proto-Language Skills")},
    "Proto-Tools": {"folder": os.path.join("Skills", "Proto-Tools"), "index": os.path.join("Skills", "Proto-Tools Skills")},
    "Media": {"folder": os.path.join("Skills", "Media"), "index": os.path.join("Skills", "Media Skills")},
}


def _vault_path():
    return os.environ.get("AGENT_VAULT_PATH", VAULT_PATH)


def _read_note(name: str) -> str:
    """Read a note from the vault."""
    vault = _vault_path()
    if not name.endswith(".md"):
        name += ".md"
    path = os.path.join(vault, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _list_category(category_info: dict) -> List[str]:
    """List all skill files in a category folder."""
    vault = _vault_path()
    cat_path = os.path.join(vault, category_info["folder"])
    if not os.path.isdir(cat_path):
        return []
    skills = []
    for f in glob.glob(os.path.join(cat_path, "*.md")):
        rel = os.path.relpath(f, vault)
        skills.append(rel)
    return skills


def _read_index(index_name: str) -> Dict[str, str]:
    """Read a category index file and parse skill descriptions."""
    content = _read_note(index_name)
    if not content:
        return {}
    
    skills = {}
    # Parse wiki-style links: [[skill-name]] — description
    for line in content.split("\n"):
        match = re.search(r"\[\[([^\]]+)\]\]\s*[—-]\s*(.+)", line)
        if match:
            skill_name = match.group(1).strip()
            description = match.group(2).strip()
            skills[skill_name] = description
        # Also handle bullet list format
        match2 = re.search(r"-\s*\[\[([^\]]+)\]\]", line)
        if match2:
            skill_name = match2.group(1).strip()
            # Try to get description from same line
            desc_match = re.search(r"-\s*\[\[[^\]]+\]\]\s*[—-]\s*(.+)", line)
            if desc_match:
                skills[skill_name] = desc_match.group(1).strip()
            elif skill_name not in skills:
                skills[skill_name] = ""
    return skills


def _get_all_vault_skills() -> Dict[str, Dict[str, Any]]:
    """Get all skills from the vault organized by category."""
    all_skills = {}
    
    for cat_name, cat_info in SKILL_CATEGORIES.items():
        index_file = cat_info["index"]
        skills = _read_index(index_file)
        
        # Also list files directly in case index is incomplete
        files = _list_category(cat_info)
        for f in files:
            skill_name = os.path.splitext(os.path.basename(f))[0]
            if skill_name not in skills or not skills[skill_name]:
                # Prefer the description from the SKILL.md frontmatter itself
                desc = ""
                try:
                    with open(f, "r", encoding="utf-8", errors="replace") as fh:
                        in_front = False
                        for line in fh:
                            line = line.rstrip("\n").rstrip("\r")
                            if line.strip() == "---":
                                if in_front:
                                    break
                                in_front = True
                                continue
                            if in_front and line.startswith("description:"):
                                desc = line[len("description:"):].strip()
                                break
                except OSError:
                    pass
                skills[skill_name] = desc
        
        for skill_name, description in skills.items():
            all_skills[skill_name] = {
                "category": cat_name,
                "path": f"{cat_info['folder']}/{skill_name}.md",
                "description": description,
                "vault_path": f"{cat_info['folder']}/{skill_name}"
            }
    
    return all_skills


def _has_word(text: str, word: str) -> bool:
    """True if `word` appears as a whole word in `text` (word-boundary match)."""
    return f" {word} " in f" {text} " or text.startswith(word + " ") or text.endswith(" " + word)


def _match_skills(query: str, skills: Dict[str, Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
    """Find skills matching the query using keyword matching with strict technical term requirements."""
    query_lower = query.lower()
    
    # Expanded stop words - exclude common action words that don't indicate specific intent
    stop_words = {
        "the", "and", "for", "with", "using", "when", "need", "want", "please", "help", "find", "make",
        "create", "build", "write", "read", "from", "into", "your", "this", "that", "will", "would",
        "could", "should", "have", "been", "their", "there", "what", "which", "does", "know", "get",
        "take", "put", "set", "run", "do", "does", "a", "an", "to", "of", "in", "on", "at", "by", "or", "is",
        "are", "was", "were", "be", "as", "if", "then", "than", "so", "but", "not", "you", "my", "i",
        "we", "our", "us", "me", "he", "she", "it", "they", "them", "his", "her", "its",
    }
    
    # Extract meaningful words (len > 3), excluding stop words
    query_words = set(w for w in query_lower.split() if len(w) > 3 and w not in stop_words)
    
    # Also extract bigrams for phrase matching
    query_bigrams = set()
    words = query_lower.split()
    for i in range(len(words) - 1):
        query_bigrams.add(words[i] + " " + words[i+1])
    
    # Define highly specific technical terms that should drive matching
    SPECIFIC_TECH_TERMS = {
        # Data formats
        "parquet", "json", "csv", "sql", "xml", "yaml", "yml", "toml", "avro", "orc", "protobuf", "proto",
        "arrow", "feather", "hdf5", "h5", "netcdf", "nc",
        # Web/API
        "api", "rest", "graphql", "grpc", "websocket", "http", "https", "endpoint", "url", "uri",
        # Databases
        "database", "postgres", "postgresql", "mysql", "sqlite", "mongodb", "redis", "elasticsearch", "dynamodb",
        # ML/Data Science
        "model", "training", "inference", "embedding", "vector", "tokenizer", "transformer", "bert", "gpt",
        "pytorch", "tensorflow", "sklearn", "scikit", "pandas", "numpy", "scipy",
        # File operations (specific)
        "schema", "migration", "etl", "pipeline", "workflow", "transform", "extract", "load", "normalize",
        "validate", "serialize", "deserialize", "compress", "decompress", "encrypt", "decrypt",
        # Scientific formats
        "fasta", "fastq", "genbank", "pdb", "sdf", "mol2", "mol", "xyz", "cif", "h5ad", "bed", "gtf",
        "gff", "vcf", "bam", "sam", "cram",
        # Code/Dev
        "docker", "kubernetes", "k8s", "helm", "terraform", "ansible", "ci", "cd", "github", "gitlab",
        "lint", "test", "pytest", "coverage", "benchmark", "profile",
        # Search/Retrieval
        "search", "query", "index", "retrieve", "rank", "rerank", "similarity", "cosine", "bm25",
        "opensearch", "solr", "milvus", "pinecone", "weaviate", "qdrant",
    }
    
    # Generic terms that should NOT drive matching alone
    GENERIC_TERMS = {"file", "convert", "change", "modify", "update", "process", "handle", "manage", "organize"}

    scored = []
    for skill_name, info in skills.items():
        score = 0
        desc = info.get("description", "").lower()
        cat = info.get("category", "").lower()
        name_lower = skill_name.lower()
        name_words = set(name_lower.replace("-", " ").split())
        
        matched_words = 0
        specific_term_matches = 0
        generic_term_matches = 0
        
        # Check skill name words (highest weight for specific terms)
        for word in name_words:
            if _has_word(query_lower, word):
                if word in SPECIFIC_TECH_TERMS:
                    score += 25
                    specific_term_matches += 1
                elif word in GENERIC_TERMS:
                    score += 3
                    generic_term_matches += 1
                else:
                    score += 10
                matched_words += 1
        
        # Check description words
        for word in query_words:
            if _has_word(desc, word):
                if word in SPECIFIC_TECH_TERMS:
                    score += 15
                    specific_term_matches += 1
                elif word in GENERIC_TERMS:
                    score += 2
                    generic_term_matches += 1
                else:
                    score += 5
                matched_words += 1
            if _has_word(name_lower, word):
                if word in SPECIFIC_TECH_TERMS:
                    score += 10
                    specific_term_matches += 1
                else:
                    score += 3
                matched_words += 1
            if _has_word(cat, word):
                score += 2
                matched_words += 1
        
        # Require at least 1 specific technical term match OR 2+ meaningful word matches
        # This prevents generic "convert file" from matching every file converter
        if specific_term_matches == 0 and matched_words < 2:
            continue
        
        # Bonus for phrase matches in description
        for bigram in query_bigrams:
            if bigram in desc:
                score += 15
            if bigram in name_lower:
                score += 20
        
        # Bonus: if query contains "web" and skill description mentions web
        if "web" in query_lower and "web" in desc:
            score += 10
        
        # Bonus: if query contains "search" and skill is a search skill
        if "search" in query_lower and "search" in name_lower:
            score += 5
            
        # Strong bonus for specific technical terms matching exactly
        for word in query_words:
            if word in SPECIFIC_TECH_TERMS:
                if _has_word(name_lower, word):
                    score += 30
                elif _has_word(desc, word):
                    score += 15
        
        # Heavy penalty for very generic skills when query has specific terms
        if generic_term_matches > 0 and specific_term_matches == 0 and len(query_words) > 1:
            # If skill name is generic (file, convert) but query has specific terms not matched
            if any(g in name_lower for g in GENERIC_TERMS):
                score = max(0, score - 25)
        
        # Minimum threshold - higher to filter noise
        if score >= 15:
            scored.append((score, skill_name, info))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"name": name, "category": info["category"], "description": info["description"], "vault_path": info["vault_path"], "score": score}
        for score, name, info in scored[:top_k]
    ]


def run(action: str = "search", query: str = "", category: str = "", top_k: int = 5, **kwargs) -> str:
    """
    Search the vault skill catalog.
    
    Actions:
    - search: Find skills matching a query
    - list: List all skills, optionally filtered by category
    - categories: List all available categories
    - read: Read a specific skill from the vault
    """
    action = action.lower()
    
    if action == "categories":
        return "Available skill categories:\n" + "\n".join(f"- {cat}" for cat in SKILL_CATEGORIES.keys())
    
    all_skills = _get_all_vault_skills()
    
    if action == "list":
        if category:
            cat_skills = {k: v for k, v in all_skills.items() if v["category"].lower() == category.lower()}
            if not cat_skills:
                return f"No skills found in category '{category}'. Available: {', '.join(SKILL_CATEGORIES.keys())}"
            out = f"Skills in {category}:\n"
            for name, info in sorted(cat_skills.items()):
                out += f"  - {name}: {info['description'][:100]}\n"
            return out
        else:
            out = f"All vault skills ({len(all_skills)} total):\n"
            for cat in sorted(set(s["category"] for s in all_skills.values())):
                cat_skills = [(n, s) for n, s in all_skills.items() if s["category"] == cat]
                out += f"\n{cat} ({len(cat_skills)} skills):\n"
                for name, s in sorted(cat_skills):
                    out += f"  - {name}: {s['description'][:80]}\n"
            return out
    
    if action == "read":
        if not query:
            return "Provide a skill name to read."
        # Find the skill
        skill_key = None
        for k in all_skills:
            if k.lower() == query.lower() or k.lower().endswith(query.lower()):
                skill_key = k
                break
        if not skill_key:
            return f"Skill '{query}' not found in vault."
        content = _read_note(all_skills[skill_key]["vault_path"])
        if content is None:
            return f"Could not read skill '{skill_key}'."
        return f"--- {skill_key} ({all_skills[skill_key]['category']}) ---\n{content}"
    
    if action == "search":
        if not query:
            return "Provide a query to search for."
        matches = _match_skills(query, all_skills, top_k)
        if not matches:
            return f"No skills matching '{query}'. Try 'list' to see all available skills."
        out = f"Top {len(matches)} skills matching '{query}':\n"
        for m in matches:
            out += f"  - {m['name']} ({m['category']}) [score: {m['score']}]\n    {m['description'][:150]}\n"
        return out
    
    return f"Unknown action: {action}. Use: search, list, categories, read"