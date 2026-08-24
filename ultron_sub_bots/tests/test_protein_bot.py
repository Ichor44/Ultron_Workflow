"""
Tests for ultron_sub_bots.bots.ProteinLabBot.

Covers:
- can_handle for protein / protein_lab task types
- validate_task with urls vs sequence-style params
- execute() with a fake monkeypatched skills.protein_lab.run
- Entry classification: PDB IDs -> download_structure, sequences -> default action

All tests inject a fake "skills.protein_lab" module into sys.modules,
so no real network calls or heavy imports ever happen. This bot does
not require the Firecrawl CLI.
"""

import sys
import types

import pytest

from ultron_sub_bots.core import ScrapingTask
from ultron_sub_bots.bots import ProteinLabBot, create_bot


# Sample real-ish protein sequences (ubiquitin fragment / small peptides)
SEQ = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
SHORT_SEQ = "ACDEFGHIKL"  # exactly 10 chars, all standard AA letters


# ---------------------------------------------------------------------------
# Fixture: fake skills.protein_lab module injected into sys.modules
# ---------------------------------------------------------------------------
@pytest.fixture()
def fake_protein_lab(monkeypatch):
    """Inject a fake skills.protein_lab package/module recording run() calls."""
    calls = []

    def fake_run(action="analyze", **kwargs):
        calls.append({"action": action, **kwargs})
        return f"OK:{action}"

    mod = types.ModuleType("skills.protein_lab")
    mod.run = fake_run

    pkg = types.ModuleType("skills")
    pkg.__path__ = []  # mark as package
    pkg.protein_lab = mod

    monkeypatch.setitem(sys.modules, "skills", pkg)
    monkeypatch.setitem(sys.modules, "skills.protein_lab", mod)
    return calls


# ===================================================================
# Factory function wiring
# ===================================================================
class TestProteinLabFactory:
    @pytest.mark.parametrize(
        "bot_type",
        ["protein", "protein_lab"],
    )
    def test_creates_protein_bot(self, bot_type):
        bot = create_bot(bot_type, bot_id=f"test_{bot_type}")
        assert isinstance(bot, ProteinLabBot)

    def test_default_id(self):
        bot = create_bot("protein")
        assert bot.bot_id == "protein_bot"

    def test_default_constructor_id(self):
        bot = ProteinLabBot()
        assert bot.bot_id == "protein_lab_bot"


# ===================================================================
# ProteinLabBot — can_handle / validate_task
# ===================================================================
class TestProteinLabCanHandle:
    def test_can_handle_protein(self):
        bot = ProteinLabBot()
        assert bot.can_handle("protein") is True
        assert bot.can_handle("protein_lab") is True

    def test_cannot_handle_other_types(self):
        bot = ProteinLabBot()
        assert bot.can_handle("scrape") is False
        assert bot.can_handle("crawl") is False
        assert bot.can_handle("search") is False


class TestProteinLabValidate:
    def test_validate_with_urls(self):
        bot = ProteinLabBot()
        assert bot.validate_task(ScrapingTask(urls=[SEQ])) is True

    def test_validate_with_sequence_param(self):
        bot = ProteinLabBot()
        assert bot.validate_task(ScrapingTask(params={"sequence": SEQ})) is True

    def test_validate_with_fasta_param(self):
        bot = ProteinLabBot()
        assert bot.validate_task(ScrapingTask(params={"fasta": f">{SEQ}"})) is True

    def test_validate_with_queries_param(self):
        bot = ProteinLabBot()
        assert bot.validate_task(ScrapingTask(params={"queries": ["1CRN"]})) is True

    def test_validate_fails_when_empty(self):
        bot = ProteinLabBot()
        assert bot.validate_task(ScrapingTask(urls=[], params={})) is False


# ===================================================================
# ProteinLabBot — classification helpers
# ===================================================================
class TestProteinLabClassification:
    def test_pdb_id_detected(self):
        assert ProteinLabBot._is_identifier("1CRN") is True

    def test_uniprot_accession_detected(self):
        assert ProteinLabBot._is_identifier("P01308") is True

    def test_lowercase_short_string_not_identifier(self):
        assert ProteinLabBot._is_identifier("abcd123456") is False

    def test_long_alnum_not_identifier(self):
        assert ProteinLabBot._is_identifier("A" * 11) is False

    def test_sequence_detected(self):
        assert ProteinLabBot._is_sequence(SEQ) is True

    def test_ten_char_aa_run_detected_as_sequence(self):
        assert ProteinLabBot._is_sequence(SHORT_SEQ) is True

    def test_short_string_not_sequence(self):
        assert ProteinLabBot._is_sequence("ACD") is False

    def test_sequence_with_many_invalid_letters_rejected(self):
        # Contains 4 invalid letters (X, X, X, Z) out of 20 -> 80% < 90% threshold
        assert ProteinLabBot._is_sequence("GGGGGNNGGNGGXGXGXGZQ") is False


# ===================================================================
# ProteinLabBot — execute()
# ===================================================================
class TestProteinLabExecute:
    def test_execute_sequence_success(self, fake_protein_lab):
        bot = ProteinLabBot()
        task = ScrapingTask(task_type="protein", urls=[SEQ])
        result = bot.execute(task)
        assert result.success is True
        assert result.data["count"] == 1
        assert result.urls_processed == 1
        assert result.data["results"][0][0] == SEQ
        assert result.data["results"][0][1] == "OK:analyze"
        # Default action used for sequence entries
        assert fake_protein_lab[0]["action"] == "analyze"
        assert fake_protein_lab[0]["sequence"] == SEQ

    def test_execute_pdb_id_uses_download_structure(self, fake_protein_lab):
        bot = ProteinLabBot()
        task = ScrapingTask(task_type="protein", urls=["1CRN"])
        result = bot.execute(task)
        assert result.success is True
        assert result.data["count"] == 1
        assert len(fake_protein_lab) == 1
        assert fake_protein_lab[0]["action"] == "download_structure"
        assert fake_protein_lab[0]["identifier"] == "1CRN"

    def test_execute_mixed_entries_classified_per_entry(self, fake_protein_lab):
        bot = ProteinLabBot()
        task = ScrapingTask(task_type="protein", urls=["1CRN", SEQ])
        result = bot.execute(task)
        assert result.success is True
        assert result.data["count"] == 2
        actions = [c["action"] for c in fake_protein_lab]
        assert actions == ["download_structure", "analyze"]

    def test_execute_action_override_from_params(self, fake_protein_lab):
        bot = ProteinLabBot(config={"default_action": "analyze"})
        task = ScrapingTask(
            task_type="protein",
            urls=[SEQ],
            params={"action": "properties"},
        )
        result = bot.execute(task)
        assert result.success is True
        # Reserved "action" param consumed as the action itself, never leaked
        # into kwargs; only the sequence payload is forwarded alongside it
        assert set(fake_protein_lab[0].keys()) == {"action", "sequence"}
        assert fake_protein_lab[0]["action"] == "properties"

    def test_execute_config_default_action(self, fake_protein_lab):
        bot = ProteinLabBot(config={"default_action": "fold"})
        task = ScrapingTask(task_type="protein", params={"sequence": SEQ})
        result = bot.execute(task)
        assert result.success is True
        assert fake_protein_lab[0]["action"] == "fold"

    def test_execute_reserved_core_key_not_forwarded(self, fake_protein_lab):
        bot = ProteinLabBot()
        task = ScrapingTask(
            task_type="protein",
            urls=[SEQ],
            params={"core": "should-not-leak", "temperature": 0.7},
        )
        result = bot.execute(task)
        assert result.success is True
        call = fake_protein_lab[0]
        assert "core" not in call
        assert call["temperature"] == 0.7

    def test_execute_import_failure_returns_error(self, monkeypatch):
        """If skills.protein_lab cannot be imported, execute returns a failed TaskResult."""

        class ImportBlocker:
            def find_module(self, name, path=None):
                if name.startswith("skills"):
                    return self

            def load_module(self, name):
                raise ImportError("blocked for test")

        # Ensure no real skills package resolves
        monkeypatch.setitem(sys.modules, "skills", None)
        monkeypatch.setitem(sys.modules, "skills.protein_lab", None)

        bot = ProteinLabBot()
        task = ScrapingTask(task_type="protein", urls=[SEQ])
        result = bot.execute(task)
        assert result.success is False
        assert "Failed to import protein_lab module" in result.error

    def test_execute_run_raises_returns_error(self, fake_protein_lab):
        bot = ProteinLabBot()

        def boom(action="analyze", **kwargs):
            raise RuntimeError("simulated crash")

        sys.modules["skills"].protein_lab.run = boom
        task = ScrapingTask(task_type="protein", urls=["1CRN"])
        result = bot.execute(task)
        assert result.success is False
        assert "simulated crash" in result.error

    def test_execute_no_entries_returns_error(self, fake_protein_lab):
        bot = ProteinLabBot()
        task = ScrapingTask(task_type="protein", urls=[], params={})
        result = bot.execute(task)
        assert result.success is False
        assert "No protein entries" in result.error

    def test_execute_output_dir_passed_through(self, fake_protein_lab):
        bot = ProteinLabBot(config={"output_dir": ".firecrawl/proteins"})
        task = ScrapingTask(task_type="protein", urls=["1CRN"])
        result = bot.execute(task)
        assert result.success is True
        assert fake_protein_lab[0]["output_dir"] == ".firecrawl/proteins"

    def test_works_without_firecrawl_cli(self, fake_protein_lab):
        """ProteinLabBot must not require Firecrawl: no core needed at all."""
        bot = ProteinLabBot()
        # No metadata / core reference whatsoever
        task = ScrapingTask(task_type="protein", urls=[SEQ])
        result = bot.execute(task)
        assert result.success is True
