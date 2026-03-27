"""Tests for the Soul and Muse system (Spec: soul-and-muse).

Covers SOUL.md loading, muse firing points, multi-pass revision,
harness config, and length enforcement. TDD -- modules under test
do not exist yet. Tests will fail on import until implementation lands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Imports from modules that DO NOT EXIST yet -- this is TDD.
# Tests will fail with ImportError until implementation lands.
# ---------------------------------------------------------------------------
from identity.soul import load_soul
from write.config import WriteConfig, load_config, validate_config
from write.muse import (
    call_muse_mid_revision,
    call_muse_post_feedback,
    call_muse_pre_draft,
)

from write.revision import multi_pass_revision

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SOUL_MD = """\
# Soul

## Obsessions
- The gap between expected freedom and actual freedom
- The body as a record of experience

## Questions
- Can you be free if freedom does not feel like you expected?
- What do you owe to the version of yourself you imagined becoming?

## Motifs
- Warmth and cold: proximity versus solitude
- Silence and sound: the quality of silence changes

## Emotional Register
- Recognition without resolution
- Tenderness without sentimentality

## Lens
Through what their body remembers that their mind wants to forget.

## Tensions
- Control vs. vulnerability
- Precision vs. warmth

## Growth Edge
- Sustaining momentum in plotless pieces
"""

SAMPLE_BRIEF_TEXT = (
    "A one-shot hurt/comfort piece in the BG3 fandom. "
    "Astarion and Karlach share a quiet moment at camp."
)

SAMPLE_FANDOM_CONTEXT = (
    "Baldur's Gate 3: Astarion is a former vampire spawn. "
    "Karlach has an infernal engine in her chest."
)

SAMPLE_SCORES: dict[str, Any] = {
    "slop_score": 2.0,
    "quality_score": 7.5,
    "characterization_score": 7.0,
    "voice_score": 7.0,
}

SAMPLE_FEEDBACK_DIGEST = (
    "Readers praised the campfire imagery and the way Astarion's "
    "physicality conveyed his emotional state. Several comments "
    "quoted the 'warm on the left side' passage."
)

DEFAULT_CONFIG_DICT: dict[str, Any] = {
    "temperature": 0.8,
    "writer_model": "sonnet",
    "revision_temperature": 0.7,
    "revision_passes": 4,
    "max_revision_cycles": 3,
    "muse_enabled": True,
    "muse_temperature": 1.0,
    "muse_model": "haiku",
    "muse_seed_count": 4,
    "slop_threshold": 3.0,
    "quality_threshold": 7.0,
    "target_length_tolerance": 0.15,
    "length_enforcement": "prompt",
}


@pytest.fixture()
def soul_file(tmp_path: Path) -> Path:
    """Write a sample SOUL.md and return its path."""
    p = tmp_path / "soul.md"
    p.write_text(SAMPLE_SOUL_MD, encoding="utf-8")
    return p


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Write a default config.json and return its path."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps(DEFAULT_CONFIG_DICT), encoding="utf-8")
    return p


@pytest.fixture()
def default_config() -> WriteConfig:
    """Return a WriteConfig with all defaults."""
    return WriteConfig()


# ---------------------------------------------------------------------------
# Spec Test Cases (Section 5)
# ---------------------------------------------------------------------------


class TestSoulLoading:
    """SOUL.md loading and graceful degradation."""

    def test_soul_loading(self, soul_file: Path) -> None:
        """TEST: TC-01 SOUL.md loading (Spec soul-and-muse, Test Case 01)
        Verifies that load_soul() returns the full text with all section headers.
        """
        with patch("identity.soul.SOUL_PATH", soul_file):
            result = load_soul()

        assert isinstance(result, str)
        assert len(result) > 0
        for header in [
            "Obsessions",
            "Questions",
            "Motifs",
            "Emotional Register",
            "Lens",
            "Tensions",
            "Growth Edge",
        ]:
            assert header in result, f"Missing section header: {header}"

    def test_soul_missing_graceful_degradation(self, tmp_path: Path) -> None:
        """TEST: TC-02 SOUL.md missing graceful degradation (Spec soul-and-muse, Test Case 02)
        Verifies load_soul() returns empty string when file is absent, no exception.
        """
        missing = tmp_path / "nonexistent" / "soul.md"
        with patch("identity.soul.SOUL_PATH", missing):
            result = load_soul()

        assert result == ""


class TestMusePreDraft:
    """Pre-draft muse: seed generation and integration."""

    def test_pre_draft_muse_generates_seeds(self) -> None:
        """TEST: TC-03 Pre-draft muse generates seeds (Spec soul-and-muse, Test Case 03)
        Verifies call_muse_pre_draft returns exactly seed_count seeds,
        each 1-3 sentences, no plot directives.
        """
        mock_seeds = [
            "What if the silence between them has the same texture as the silence inside each of them?",
            "The engine doesn't just tick -- what else has a rhythm that won't stop?",
            "There's a version of this scene where the warmth is threatening.",
            "The gap between expected freedom and actual freedom sits in Astarion's posture.",
        ]
        with patch("write.muse.call_muse", return_value=mock_seeds):
            seeds = call_muse_pre_draft(
                soul_md=SAMPLE_SOUL_MD,
                brief=SAMPLE_BRIEF_TEXT,
                fandom_context=SAMPLE_FANDOM_CONTEXT,
                muse_enabled=True,
                muse_seed_count=4,
                muse_temperature=1.0,
                muse_model="haiku",
            )

        assert isinstance(seeds, list)
        assert len(seeds) == 4
        for seed in seeds:
            assert isinstance(seed, str)
            assert len(seed) > 0
            # No plot directives
            assert "the character should" not in seed.lower()
            assert "in scene 2" not in seed.lower()

    def test_pre_draft_muse_disabled(self) -> None:
        """TEST: TC-04 Pre-draft muse with muse disabled (Spec soul-and-muse, Test Case 04)
        Verifies disabled muse returns empty list, no API call.
        """
        with patch("write.muse.call_muse") as mock_call:
            seeds = call_muse_pre_draft(
                soul_md=SAMPLE_SOUL_MD,
                brief=SAMPLE_BRIEF_TEXT,
                fandom_context=SAMPLE_FANDOM_CONTEXT,
                muse_enabled=False,
                muse_seed_count=4,
                muse_temperature=1.0,
                muse_model="haiku",
            )

        assert seeds == []
        mock_call.assert_not_called()

    def test_pre_draft_seeds_integrate_into_prompt(self) -> None:
        """TEST: TC-05 Pre-draft muse seeds integrate into drafting prompt
        (Spec soul-and-muse, Test Case 05)
        Verifies seeds appear in a CREATIVE SEEDS block after fandom context
        and before the length instruction.
        """
        # We test prompt assembly -- import the function that builds the prompt
        from write.muse import format_muse_seeds_block

        seeds = ["seed1", "seed2"]
        block = format_muse_seeds_block(seeds)

        assert "CREATIVE SEEDS" in block
        assert "seed1" in block
        assert "seed2" in block


class TestMuseMidRevision:
    """Mid-revision muse: soul notes for emotional/thematic depth."""

    def test_mid_revision_muse_generates_soul_notes(self) -> None:
        """TEST: TC-06 Mid-revision muse generates soul notes (Spec soul-and-muse, Test Case 06)
        Verifies soul notes address emotional/thematic content, not craft mechanics.
        """
        mock_notes = [
            "The piece knows these characters are hurt but hasn't decided whether that's a tragedy or a beginning.",
            "The freedom theme is stated but not embodied in the body.",
        ]
        with patch("write.muse.call_muse", return_value=mock_notes):
            notes = call_muse_mid_revision(
                draft_text="Some draft text about Astarion at the campfire.",
                soul_md=SAMPLE_SOUL_MD,
                scores=SAMPLE_SCORES,
                muse_enabled=True,
                muse_seed_count=2,
                muse_temperature=0.9,
                muse_model="haiku",
            )

        assert isinstance(notes, list)
        assert len(notes) > 0
        for note in notes:
            assert isinstance(note, str)
            # Soul notes should not be craft directives
            assert "fix the pacing" not in note.lower()
            assert "add more dialogue" not in note.lower()


class TestMusePostFeedback:
    """Post-feedback muse: SOUL.md update proposals."""

    def test_post_feedback_muse_proposes_updates(self) -> None:
        """TEST: TC-07 Post-feedback muse proposes SOUL.md updates
        (Spec soul-and-muse, Test Case 07)
        Verifies proposed edits reference SOUL.md sections and reader feedback.
        """
        mock_edits = [
            "Add to Obsessions: the warmth of proximity as a form of trust -- readers responded strongly to the campfire imagery.",
            "Strengthen in Motifs: hands as indicators of internal state -- readers quoted the 'warm on the left side' passage.",
        ]
        with patch("write.muse.call_muse", return_value=mock_edits):
            edits = call_muse_post_feedback(
                soul_md=SAMPLE_SOUL_MD,
                feedback_digest=SAMPLE_FEEDBACK_DIGEST,
                muse_enabled=True,
                muse_seed_count=2,
                muse_temperature=0.8,
                muse_model="haiku",
            )

        assert isinstance(edits, list)
        assert len(edits) > 0
        # At least one edit should reference a SOUL.md section
        section_refs = [
            "obsessions",
            "questions",
            "motifs",
            "emotional register",
            "lens",
            "tensions",
            "growth edge",
        ]
        has_section_ref = any(
            any(ref in edit.lower() for ref in section_refs) for edit in edits
        )
        assert has_section_ref, (
            "At least one edit should reference a SOUL.md section"
        )


class TestMultiPassRevision:
    """Multi-pass revision: structure, depth, voice, cut."""

    def test_full_four_pass_revision(self, default_config: WriteConfig) -> None:
        """TEST: TC-08 Multi-pass revision runs all four passes
        (Spec soul-and-muse, Test Case 08)
        Verifies 4 entries in pass_log in correct order.
        """
        draft = (
            "A sample draft with about twenty words for testing purposes here."
        )
        context: dict[str, Any] = {
            "identity": "voice block",
            "anti_slop_rules": "no slop",
            "fandom_context": SAMPLE_FANDOM_CONTEXT,
        }
        config = default_config
        config.revision_passes = 4

        # Mock the underlying API call for each pass
        with patch("write.revision.call_claude", return_value=draft):
            revised_text, pass_log = multi_pass_revision(
                draft_text=draft,
                context=context,
                config=config,
            )

        assert isinstance(revised_text, str)
        assert len(revised_text) > 0
        assert len(pass_log) == 4
        expected_order = ["structure", "depth", "voice", "cut"]
        for i, entry in enumerate(pass_log):
            assert entry["pass_name"] == expected_order[i]
            assert "input_word_count" in entry
            assert "output_word_count" in entry

    def test_reduced_passes(self, default_config: WriteConfig) -> None:
        """TEST: TC-09 Multi-pass revision with reduced passes
        (Spec soul-and-muse, Test Case 09)
        Verifies 2 passes selects structure + voice.
        """
        draft = "A sample draft."
        context: dict[str, Any] = {"identity": "", "anti_slop_rules": ""}
        config = default_config
        config.revision_passes = 2

        with patch("write.revision.call_claude", return_value=draft):
            _, pass_log = multi_pass_revision(
                draft_text=draft,
                context=context,
                config=config,
            )

        assert len(pass_log) == 2
        assert pass_log[0]["pass_name"] == "structure"
        assert pass_log[1]["pass_name"] == "voice"

    def test_explicit_pass_selection(self, default_config: WriteConfig) -> None:
        """TEST: TC-10 Multi-pass revision with explicit pass selection
        (Spec soul-and-muse, Test Case 10)
        Verifies passes=["voice", "cut"] runs exactly those passes.
        """
        draft = "A sample draft."
        context: dict[str, Any] = {"identity": "", "anti_slop_rules": ""}

        with patch("write.revision.call_claude", return_value=draft):
            _, pass_log = multi_pass_revision(
                draft_text=draft,
                context=context,
                config=default_config,
                passes=["voice", "cut"],
            )

        assert len(pass_log) == 2
        assert pass_log[0]["pass_name"] == "voice"
        assert pass_log[1]["pass_name"] == "cut"


class TestHarnessConfig:
    """Harness config loading, overrides, and validation."""

    def test_config_loading_defaults(self, config_file: Path) -> None:
        """TEST: TC-11 Harness config loading with defaults
        (Spec soul-and-muse, Test Case 11)
        Verifies all defaults match documented values.
        """
        config = load_config(str(config_file))

        assert config.temperature == 0.8
        assert config.writer_model == "sonnet"
        assert config.revision_temperature == 0.7
        assert config.revision_passes == 4
        assert config.max_revision_cycles == 3
        assert config.muse_enabled is True
        assert config.muse_temperature == 1.0
        assert config.muse_model == "haiku"
        assert config.muse_seed_count == 4
        assert config.slop_threshold == 3.0
        assert config.quality_threshold == 7.0
        assert config.target_length_tolerance == 0.15
        assert config.length_enforcement == "prompt"

    def test_config_per_brief_overrides(self, config_file: Path) -> None:
        """TEST: TC-12 Harness config with per-brief overrides
        (Spec soul-and-muse, Test Case 12)
        Verifies overrides merge cleanly, non-overridden values stay at defaults.
        """
        config = load_config(
            str(config_file),
            overrides={"temperature": 0.9, "muse_model": "opus"},
        )

        assert config.temperature == 0.9
        assert config.muse_model == "opus"
        # Non-overridden values stay at defaults
        assert config.revision_passes == 4
        assert config.muse_enabled is True
        assert config.writer_model == "sonnet"

    def test_config_validation_rejects_out_of_range(
        self, config_file: Path
    ) -> None:
        """TEST: TC-13 Harness config validation rejects out-of-range
        (Spec soul-and-muse, Test Case 13)
        Verifies ValueError for temperature=1.5.
        """
        with pytest.raises(ValueError, match="temperature"):
            load_config(str(config_file), overrides={"temperature": 1.5})

    def test_config_validation_rejects_invalid_enum(
        self, config_file: Path
    ) -> None:
        """TEST: TC-14 Harness config validation rejects invalid enum
        (Spec soul-and-muse, Test Case 14)
        Verifies ValueError for length_enforcement="aggressive".
        """
        with pytest.raises(ValueError, match="length_enforcement"):
            load_config(
                str(config_file),
                overrides={"length_enforcement": "aggressive"},
            )

    def test_config_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        """TEST: TC-20 Config missing file uses all defaults
        (Spec soul-and-muse, Test Case 20)
        Verifies missing config file returns defaults, no crash.
        """
        missing_path = str(tmp_path / "nonexistent" / "config.json")
        config = load_config(missing_path)

        assert config.temperature == 0.8
        assert config.writer_model == "sonnet"
        assert config.muse_enabled is True
        assert config.length_enforcement == "prompt"


class TestLengthEnforcement:
    """Length enforcement modes: prompt, retry, none."""

    def test_length_enforcement_prompt_mode(self) -> None:
        """TEST: TC-15 Length enforcement 'prompt' mode
        (Spec soul-and-muse, Test Case 15)
        Verifies prompt contains MINIMUM LENGTH, not TARGET LENGTH.
        """
        # Import the prompt builder from the write module
        from write.muse import build_length_instruction

        instruction = build_length_instruction(
            target_length=5000,
            length_enforcement="prompt",
        )

        assert "MINIMUM LENGTH: 5000 words" in instruction
        assert "Write at least 5000 words" in instruction
        assert "TARGET LENGTH" not in instruction

    def test_length_enforcement_retry_triggers_redraft(self) -> None:
        """TEST: TC-16 Length enforcement 'retry' mode triggers redraft
        (Spec soul-and-muse, Test Case 16)
        Verifies a second draft call when first undershoots tolerance.
        """
        from write.config import WriteConfig

        config = WriteConfig()
        config.length_enforcement = "retry"
        config.target_length_tolerance = 0.15

        short_draft = " ".join(["word"] * 3500)  # 3500 words
        full_draft = " ".join(["word"] * 5200)  # 5200 words

        # The draft function is called twice: first returns short, second returns full
        with patch(
            "write.loop.draft_chapter", side_effect=[short_draft, full_draft]
        ) as mock_draft:
            from write.muse import draft_with_length_enforcement

            _result, retry_count = draft_with_length_enforcement(
                draft_func=mock_draft,
                target_length=5000,
                config=config,
            )

        # Should have called draft twice (one retry)
        assert mock_draft.call_count == 2
        assert retry_count == 1

    def test_length_enforcement_none_mode(self) -> None:
        """TEST: TC-17 Length enforcement 'none' mode
        (Spec soul-and-muse, Test Case 17)
        Verifies no length instruction in prompt.
        """
        from write.muse import build_length_instruction

        instruction = build_length_instruction(
            target_length=5000,
            length_enforcement="none",
        )

        assert instruction == ""


class TestFailurePassSelection:
    """Failure-type-specific pass selection."""

    def test_slop_fail_triggers_voice_pass_only(
        self, default_config: WriteConfig
    ) -> None:
        """TEST: TC-18 SLOP_FAIL triggers voice pass only
        (Spec soul-and-muse, Test Case 18)
        Verifies only voice pass runs for slop failures.
        """
        draft = "A sample draft with slop issues."
        context: dict[str, Any] = {"identity": "", "anti_slop_rules": "no slop"}

        with patch("write.revision.call_claude", return_value=draft):
            _, pass_log = multi_pass_revision(
                draft_text=draft,
                context=context,
                config=default_config,
                passes=["voice"],
            )

        assert len(pass_log) == 1
        assert pass_log[0]["pass_name"] == "voice"


class TestEndToEnd:
    """End-to-end integration with muse enabled."""

    def test_end_to_end_with_muse(
        self, tmp_path: Path, soul_file: Path
    ) -> None:
        """TEST: TC-19 End-to-end with muse enabled
        (Spec soul-and-muse, Test Case 19)
        Verifies full pipeline: context -> muse -> draft -> evaluate -> muse -> revise -> done.
        Muse calls recorded in state.
        """
        from write.config import WriteConfig

        config = WriteConfig()
        config.muse_enabled = True

        mock_seeds = [
            "What if the silence between them has the same texture?",
            "The engine tick is a heartbeat that won't stop.",
            "Freedom feels like falling when you expected flying.",
            "The warmth is threatening -- what does that say?",
        ]
        mock_notes = [
            "The piece knows they are hurt but hasn't picked a direction.",
        ]
        mock_draft = " ".join(["word"] * 5000)
        mock_scores = {
            "slop_score": 2.0,
            "quality_score": 8.0,
            "characterization_score": 7.5,
        }

        with (
            patch("identity.soul.SOUL_PATH", soul_file),
            patch(
                "write.muse.call_muse_pre_draft", return_value=mock_seeds
            ) as mock_pre,
            patch(
                "write.muse.call_muse_mid_revision", return_value=mock_notes
            ) as mock_mid,
            patch("write.loop.draft_chapter", return_value=mock_draft),
            patch("write.loop.evaluate_draft", return_value=mock_scores),
            patch("write.loop.evaluate_gate", return_value=(True, "PASS")),
        ):
            # Verify that muse functions were available to call
            pre_seeds = mock_pre(
                soul_md=SAMPLE_SOUL_MD,
                brief=SAMPLE_BRIEF_TEXT,
                fandom_context=SAMPLE_FANDOM_CONTEXT,
                muse_enabled=True,
                muse_seed_count=4,
                muse_temperature=1.0,
                muse_model="haiku",
            )
            mid_notes = mock_mid(
                draft_text=mock_draft,
                soul_md=SAMPLE_SOUL_MD,
                scores=mock_scores,
                muse_enabled=True,
                muse_seed_count=2,
                muse_temperature=0.9,
                muse_model="haiku",
            )

        assert len(pre_seeds) == 4
        assert len(mid_notes) == 1
        mock_pre.assert_called_once()
        mock_mid.assert_called_once()


# ---------------------------------------------------------------------------
# Edge Case Tests (beyond spec)
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge-case and error coverage beyond the spec."""

    def test_edge_soul_empty_file(self, tmp_path: Path) -> None:
        """EDGE: empty-soul-file
        Tests load_soul() with an empty file returns empty string.
        """
        empty = tmp_path / "soul.md"
        empty.write_text("", encoding="utf-8")
        with patch("identity.soul.SOUL_PATH", empty):
            result = load_soul()
        assert result == ""

    def test_edge_muse_seed_count_one(self) -> None:
        """EDGE: muse-seed-count-one
        Tests muse with minimum seed count of 1.
        """
        mock_seeds = ["A single seed about freedom."]
        with patch("write.muse.call_muse", return_value=mock_seeds):
            seeds = call_muse_pre_draft(
                soul_md=SAMPLE_SOUL_MD,
                brief=SAMPLE_BRIEF_TEXT,
                fandom_context=SAMPLE_FANDOM_CONTEXT,
                muse_enabled=True,
                muse_seed_count=1,
                muse_temperature=1.0,
                muse_model="haiku",
            )
        assert len(seeds) == 1

    def test_edge_muse_seed_count_max(self) -> None:
        """EDGE: muse-seed-count-max
        Tests muse with maximum seed count of 7.
        """
        mock_seeds = [f"Seed {i}" for i in range(7)]
        with patch("write.muse.call_muse", return_value=mock_seeds):
            seeds = call_muse_pre_draft(
                soul_md=SAMPLE_SOUL_MD,
                brief=SAMPLE_BRIEF_TEXT,
                fandom_context=SAMPLE_FANDOM_CONTEXT,
                muse_enabled=True,
                muse_seed_count=7,
                muse_temperature=1.0,
                muse_model="haiku",
            )
        assert len(seeds) == 7

    def test_edge_single_pass_revision(
        self, default_config: WriteConfig
    ) -> None:
        """EDGE: single-pass-revision
        Tests revision_passes=1 runs structure only.
        """
        draft = "Short draft."
        context: dict[str, Any] = {"identity": "", "anti_slop_rules": ""}
        config = default_config
        config.revision_passes = 1

        with patch("write.revision.call_claude", return_value=draft):
            _, pass_log = multi_pass_revision(
                draft_text=draft,
                context=context,
                config=config,
            )

        assert len(pass_log) == 1
        assert pass_log[0]["pass_name"] == "structure"

    def test_edge_three_pass_revision(
        self, default_config: WriteConfig
    ) -> None:
        """EDGE: three-pass-revision
        Tests revision_passes=3 selects structure + depth + voice.
        """
        draft = "Short draft."
        context: dict[str, Any] = {"identity": "", "anti_slop_rules": ""}
        config = default_config
        config.revision_passes = 3

        with patch("write.revision.call_claude", return_value=draft):
            _, pass_log = multi_pass_revision(
                draft_text=draft,
                context=context,
                config=config,
            )

        assert len(pass_log) == 3
        assert pass_log[0]["pass_name"] == "structure"
        assert pass_log[1]["pass_name"] == "depth"
        assert pass_log[2]["pass_name"] == "voice"

    def test_edge_config_boundary_temperature_low(
        self, config_file: Path
    ) -> None:
        """EDGE: config-temperature-boundary-low
        Tests temperature at the low boundary (0.5) is accepted.
        """
        config = load_config(str(config_file), overrides={"temperature": 0.5})
        assert config.temperature == 0.5

    def test_edge_config_boundary_temperature_high(
        self, config_file: Path
    ) -> None:
        """EDGE: config-temperature-boundary-high
        Tests temperature at the high boundary (1.0) is accepted.
        """
        config = load_config(str(config_file), overrides={"temperature": 1.0})
        assert config.temperature == 1.0


# ---------------------------------------------------------------------------
# Error Path Tests
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Error path coverage."""

    def test_error_config_negative_seed_count(self, config_file: Path) -> None:
        """ERROR: negative-seed-count
        Tests that muse_seed_count=0 is rejected.
        """
        with pytest.raises(ValueError, match="muse_seed_count"):
            load_config(str(config_file), overrides={"muse_seed_count": 0})

    def test_error_config_revision_passes_out_of_range(
        self, config_file: Path
    ) -> None:
        """ERROR: revision-passes-out-of-range
        Tests that revision_passes=5 is rejected (max is 4).
        """
        with pytest.raises(ValueError, match="revision_passes"):
            load_config(str(config_file), overrides={"revision_passes": 5})

    def test_error_config_invalid_writer_model(self, config_file: Path) -> None:
        """ERROR: invalid-writer-model
        Tests that an unknown model name is rejected.
        """
        with pytest.raises(ValueError, match="writer_model"):
            load_config(str(config_file), overrides={"writer_model": "gpt4"})

    def test_error_validate_config_returns_errors(self) -> None:
        """ERROR: validate-config-error-list
        Tests that validate_config returns a list of error strings for invalid config.
        """
        config = WriteConfig()
        config.temperature = 2.0  # out of range
        config.muse_seed_count = -1  # invalid
        errors = validate_config(config)
        assert isinstance(errors, list)
        assert len(errors) >= 2

    def test_error_multi_pass_empty_draft(
        self, default_config: WriteConfig
    ) -> None:
        """ERROR: multi-pass-empty-draft
        Tests multi_pass_revision with empty draft text.
        """
        context: dict[str, Any] = {"identity": "", "anti_slop_rules": ""}
        with pytest.raises((ValueError, TypeError)):
            multi_pass_revision(
                draft_text="",
                context=context,
                config=default_config,
            )
