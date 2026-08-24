import json
import os

from core import recipes

RECIPES_DIR = recipes.RECIPES_DIR
SKILLS_SH_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".skills-sh")


def ensure_dirs():
    recipes.ensure_dirs()
    os.makedirs(SKILLS_SH_DIR, exist_ok=True)


def _skills_sh_path():
    return os.path.join(SKILLS_SH_DIR, "installed.json")


def _skills_sh_log_path():
    return os.path.join(SKILLS_SH_DIR, "log.txt")


def log_skills_sh_message(msg):
    os.makedirs(SKILLS_SH_DIR, exist_ok=True)
    with open(_skills_sh_log_path(), "a", encoding="utf-8") as f:
        f.write("%s\n" % msg)


def fetch_skills_sh_skills():
    log_skills_sh_message("=== fetch_skills_sh_skills called ===")
    return "Skills.sh integration requires manual configuration. Please set SKILLS_SH_API_KEY in .env and restart.", False


def install_skills_sh_recipe(recipe_url_or_name):
    log_skills_sh_message("=== install_skills_sh_recipe: %s ===" % recipe_url_or_name)
    return "Skills.sh integration requires manual configuration. Please set SKILLS_SH_API_KEY in .env and restart."


def list_skills_sh_installed():
    log_skills_sh_message("=== list_skills_sh_installed called ===")
    ensure_dirs()
    path = _skills_sh_path()
    if not os.path.exists(path):
        log_skills_sh_message("No installed.json found, creating empty list")
        data = []
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def save_skills_sh_installation(recipes_data):
    log_skills_sh_message("=== save_skills_sh_installation called ===")
    path = _skills_sh_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recipes_data, f, indent=2)
    return True
