"""Tests for the prompt builders in write.prompts.

After bd-75p, the write loop's muse / draft / revision prompt content
lives in :mod:`write.prompts` as pure builder functions. The previous
test suite mocked ``write.muse.call_muse`` and ``write.revision.call_claude``
to verify behavior; with the API callers gone, the equivalent
verification is to assert the produced prompt strings contain the
expected blocks (voice, anti-slop rules, soul, etc.).

This file also keeps a smoke test for :func:`write.loop.load_soul`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from write import prompts
from write.loop import load_soul

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

SAMPLE_CONTEXT = {
    "identity": "Voice: Lyrical, observational, restrained sentiment.",
    "anti_slop_rules": "Banned: delve, tapestry, myriad.",
    "fandom_context": SAMPLE_FANDOM_CONTEXT,
    "brief_text": SAMPLE_BRIEF_TEXT,
}

SAMPLE_SCORES = {
    "slop_penalty": 2.0,
    "overall_score": 7.5,
    "voice_adherence": {"score": 7.0, "feedback": "Mostly good"},
}


# ---------------------------------------------------------------------------
# Mock brief
# ---------------------------------------------------------------------------


class MockBrief:
    """Minimal stand-in for StoryBrief used in prompt-builder tests."""

    def __init__(self, target_length: int = 5000):
        self.target_length = target_length


# ---------------------------------------------------------------------------
# load_soul tests
# ---------------------------------------------------------------------------


class TestLoadSoul:
    """SOUL.md loading and graceful degradation."""

    def test_soul_loading(self, tmp_path: Path) -> None:
        """load_soul returns the full text with all section headers."""
        soul_file = tmp_path / "soul.md"
        soul_file.write_text(SAMPLE_SOUL_MD, encoding="utf-8")
        result = load_soul(soul_file)

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
        """load_soul returns empty string when file is absent, no exception."""
        missing = tmp_path / "nonexistent" / "soul.md"
        result = load_soul(missing)
        assert result == ""

    def test_soul_empty_file(self, tmp_path: Path) -> None:
        """An empty soul.md returns empty string."""
        empty = tmp_path / "soul.md"
        empty.write_text("", encoding="utf-8")
        result = load_soul(empty)
        assert result == ""


# ---------------------------------------------------------------------------
# Persona-suppression frame
# ---------------------------------------------------------------------------


class TestPersonaSuppressionFrame:
    """The wrap_for_subagent frame is load-bearing -- assert it verbatim."""

    def test_wrap_for_subagent_contains_output_rules(self) -> None:
        wrapped = prompts.wrap_for_subagent(
            system="VOICE GOES HERE", user="TASK GOES HERE"
        )
        assert "OUTPUT RULES (non-negotiable):" in wrapped
        assert "Output ONLY the story prose" in wrapped
        assert "Do not break character" in wrapped

    def test_wrap_for_subagent_substitutes_system_and_user(self) -> None:
        wrapped = prompts.wrap_for_subagent(
            system="VOICE_SENTINEL_ABC", user="TASK_SENTINEL_XYZ"
        )
        assert "VOICE_SENTINEL_ABC" in wrapped
        assert "TASK_SENTINEL_XYZ" in wrapped

    def test_wrap_for_subagent_ends_with_begin_now(self) -> None:
        wrapped = prompts.wrap_for_subagent(system="s", user="u")
        assert wrapped.rstrip().endswith("Output the story only.")

    def test_wrap_for_subagent_voice_section_marked(self) -> None:
        wrapped = prompts.wrap_for_subagent(system="THE VOICE", user="task")
        assert "VOICE AND CONSTRAINTS:" in wrapped
        assert "WRITING TASK:" in wrapped

    def test_wrap_for_subagent_structured_swaps_output_rules(self) -> None:
        wrapped = prompts.wrap_for_subagent_structured(
            system="VOICE_SENTINEL",
            user="TASK_SENTINEL",
            output_kind=(
                "a numbered list of 4 seeds, one per line, no preamble"
            ),
        )
        assert "VOICE_SENTINEL" in wrapped
        assert "TASK_SENTINEL" in wrapped
        assert "numbered list of 4 seeds" in wrapped
        assert "OUTPUT RULES (non-negotiable):" in wrapped
        # Structured frame still suppresses persona
        assert "Do not break character" in wrapped


# ---------------------------------------------------------------------------
# Draft prompt builders
# ---------------------------------------------------------------------------


class TestDraftPrompts:
    """Tests for build_draft_system / build_draft_user."""

    def test_draft_system_includes_voice(self) -> None:
        system = prompts.build_draft_system(
            context=SAMPLE_CONTEXT, soul=SAMPLE_SOUL_MD
        )
        assert "VOICE:" in system
        assert SAMPLE_CONTEXT["identity"] in system

    def test_draft_system_includes_anti_slop_rules(self) -> None:
        system = prompts.build_draft_system(
            context=SAMPLE_CONTEXT, soul=SAMPLE_SOUL_MD
        )
        assert "ANTI-SLOP RULES" in system
        assert SAMPLE_CONTEXT["anti_slop_rules"] in system

    def test_draft_system_includes_soul_when_present(self) -> None:
        system = prompts.build_draft_system(
            context=SAMPLE_CONTEXT, soul=SAMPLE_SOUL_MD
        )
        assert "THEMATIC DNA" in system
        assert "Obsessions" in system

    def test_draft_system_omits_soul_when_empty(self) -> None:
        system = prompts.build_draft_system(context=SAMPLE_CONTEXT, soul="")
        assert "THEMATIC DNA" not in system

    def test_draft_system_includes_anti_patterns(self) -> None:
        system = prompts.build_draft_system(
            context=SAMPLE_CONTEXT, soul=SAMPLE_SOUL_MD
        )
        assert "STRUCTURAL ANTI-PATTERNS" in system
        # Em-dash density rule is in the anti-patterns
        assert "em-dash" in system.lower()

    def test_draft_user_includes_brief_and_fandom(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(target_length=5000),
            context=SAMPLE_CONTEXT,
        )
        assert SAMPLE_CONTEXT["brief_text"] in user
        assert SAMPLE_CONTEXT["fandom_context"] in user

    def test_draft_user_minimum_length_default(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(target_length=5000),
            context=SAMPLE_CONTEXT,
        )
        assert "MINIMUM LENGTH: 5000 words" in user

    def test_draft_user_no_length_when_enforcement_none(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(target_length=5000),
            context=SAMPLE_CONTEXT,
            length_enforcement="none",
        )
        assert "MINIMUM LENGTH" not in user

    def test_draft_user_length_retry_includes_critical(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(target_length=5000),
            context=SAMPLE_CONTEXT,
            length_retry=True,
            previous_word_count=3500,
        )
        assert "CRITICAL" in user
        assert "3500" in user
        assert "5000" in user

    def test_draft_user_seeds_block_when_present(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(),
            context=SAMPLE_CONTEXT,
            seeds=["seed one", "seed two"],
        )
        assert "CREATIVE SEEDS" in user
        assert "seed one" in user
        assert "seed two" in user

    def test_draft_user_no_seeds_block_when_empty(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(),
            context=SAMPLE_CONTEXT,
            seeds=None,
        )
        assert "CREATIVE SEEDS" not in user

    def test_draft_user_chapter_position_for_multi(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(),
            context=SAMPLE_CONTEXT,
            chapter_num=3,
            total_chapters=10,
            previous_chapter_tail="Tail of chapter 2 here.",
        )
        assert "chapter 3 of 10" in user
        assert "Tail of chapter 2 here." in user

    def test_draft_user_no_chapter_position_for_one_shot(self) -> None:
        user = prompts.build_draft_user(
            brief=MockBrief(),
            context=SAMPLE_CONTEXT,
            chapter_num=1,
            total_chapters=1,
        )
        assert "chapter 1 of" not in user


# ---------------------------------------------------------------------------
# Revision pass prompt builders
# ---------------------------------------------------------------------------


class TestRevisionPassPrompts:
    """Tests for the four-pass revision system prompts."""

    def test_structure_pass_focused_on_shape(self) -> None:
        system = prompts.build_revision_pass_system(
            pass_name="structure", context=SAMPLE_CONTEXT
        )
        assert "structural editor" in system.lower()
        assert "shape" in system.lower()

    def test_depth_pass_includes_muse_notes(self) -> None:
        system = prompts.build_revision_pass_system(
            pass_name="depth",
            context=SAMPLE_CONTEXT,
            muse_notes=["The piece skates over grief.", "Body is missing."],
        )
        assert "depth editor" in system.lower()
        assert "SOUL NOTES" in system
        assert "skates over grief" in system

    def test_depth_pass_no_notes_block_when_empty(self) -> None:
        system = prompts.build_revision_pass_system(
            pass_name="depth", context=SAMPLE_CONTEXT, muse_notes=None
        )
        assert "SOUL NOTES" not in system

    def test_voice_pass_includes_identity_and_anti_slop(self) -> None:
        system = prompts.build_revision_pass_system(
            pass_name="voice", context=SAMPLE_CONTEXT
        )
        assert "voice editor" in system.lower()
        assert SAMPLE_CONTEXT["identity"] in system
        assert SAMPLE_CONTEXT["anti_slop_rules"] in system

    def test_cut_pass_includes_soul(self) -> None:
        system = prompts.build_revision_pass_system(
            pass_name="cut",
            context=SAMPLE_CONTEXT,
            soul=SAMPLE_SOUL_MD,
        )
        assert "cutting editor" in system.lower()
        assert "Obsessions" in system

    def test_revision_pass_user_includes_draft(self) -> None:
        user = prompts.build_revision_pass_user("Draft text here.")
        assert "Draft text here." in user
        assert "CURRENT DRAFT" in user


# ---------------------------------------------------------------------------
# Simple revision prompt builders
# ---------------------------------------------------------------------------


class TestSimpleRevisionPrompts:
    """Tests for build_simple_revision_system / build_simple_revision_user."""

    def test_simple_revision_system_directs_full_text(self) -> None:
        system = prompts.build_simple_revision_system()
        assert "revising" in system.lower()
        assert "complete revised text" in system.lower()

    def test_simple_revision_user_includes_brief_and_draft(self) -> None:
        user = prompts.build_simple_revision_user(
            draft="Draft body.",
            brief=MockBrief(),
            context=SAMPLE_CONTEXT,
            revision_brief="Fix the voice in paragraph 3.",
        )
        assert "Draft body." in user
        assert "Fix the voice in paragraph 3." in user

    def test_simple_revision_user_includes_voice_context(self) -> None:
        user = prompts.build_simple_revision_user(
            draft="Draft body.",
            brief=MockBrief(),
            context=SAMPLE_CONTEXT,
            revision_brief="Brief.",
        )
        assert SAMPLE_CONTEXT["identity"] in user
        assert "VOICE REFERENCE" in user

    def test_simple_revision_user_handles_none_context(self) -> None:
        user = prompts.build_simple_revision_user(
            draft="Draft.",
            brief=MockBrief(),
            context=None,
            revision_brief="Brief.",
        )
        assert "Draft." in user
        assert "Brief." in user
        # No context-block headers leak through
        assert "VOICE REFERENCE" not in user


# ---------------------------------------------------------------------------
# Muse prompt builders
# ---------------------------------------------------------------------------


class TestMusePrompts:
    """Tests for the three muse builders + parse_seeds."""

    def test_muse_seeds_system_names_seed_count(self) -> None:
        system = prompts.build_muse_seeds_system(seed_count=4)
        assert "exactly 4 creative seeds" in system

    def test_muse_seeds_system_creative_subconscious_framing(self) -> None:
        system = prompts.build_muse_seeds_system(seed_count=4)
        assert "creative subconscious" in system

    def test_muse_seeds_user_includes_soul_brief_fandom(self) -> None:
        user = prompts.build_muse_seeds_user(
            soul=SAMPLE_SOUL_MD,
            brief=SAMPLE_BRIEF_TEXT,
            fandom_context=SAMPLE_FANDOM_CONTEXT,
            seed_count=3,
        )
        assert SAMPLE_BRIEF_TEXT in user
        assert SAMPLE_FANDOM_CONTEXT in user
        assert "Obsessions" in user
        assert "Generate 3 creative seeds" in user

    def test_muse_depth_system_seed_count(self) -> None:
        system = prompts.build_muse_depth_system(seed_count=2)
        assert "exactly 2 soul notes" in system

    def test_muse_depth_user_includes_scores_and_draft(self) -> None:
        user = prompts.build_muse_depth_user(
            soul=SAMPLE_SOUL_MD,
            scores=SAMPLE_SCORES,
            draft="Some draft text.",
        )
        assert "Some draft text." in user
        assert "voice_adherence" in user
        assert "EVALUATION SCORES" in user

    def test_muse_evolution_prompts_propose_edits(self) -> None:
        system = prompts.build_muse_evolution_system(seed_count=3)
        assert "feedback" in system.lower()
        user = prompts.build_muse_evolution_user(
            soul=SAMPLE_SOUL_MD,
            digest="Readers loved the campfire imagery.",
        )
        assert "Readers loved the campfire imagery." in user
        assert "Obsessions" in user


class TestParseSeeds:
    """Tests for parse_seeds output parser."""

    def test_parse_numbered_seeds_dot(self) -> None:
        raw = "1. First seed\n2. Second seed\n3. Third seed"
        seeds = prompts.parse_seeds(raw, expected=3)
        assert len(seeds) == 3
        assert seeds[0] == "First seed"
        assert seeds[2] == "Third seed"

    def test_parse_numbered_seeds_paren(self) -> None:
        raw = "1) Alpha\n2) Beta\n3) Gamma"
        seeds = prompts.parse_seeds(raw, expected=3)
        assert len(seeds) == 3
        assert seeds[0] == "Alpha"

    def test_parse_seeds_caps_at_expected(self) -> None:
        raw = "1. a\n2. b\n3. c\n4. d\n5. e"
        seeds = prompts.parse_seeds(raw, expected=3)
        assert len(seeds) == 3

    def test_parse_seeds_blank_line_fallback(self) -> None:
        # Without numbered prefixes the parser keeps text as a single seed --
        # the blank-line fallback only fires when the numbered split returns
        # nothing, which here it does not (it matches the whole input).
        raw = "First idea here.\n\nSecond idea here."
        seeds = prompts.parse_seeds(raw, expected=2)
        assert len(seeds) == 1
        assert "First idea here." in seeds[0]

    def test_parse_seeds_empty_input(self) -> None:
        assert prompts.parse_seeds("", expected=4) == []

    def test_parse_seeds_single_block(self) -> None:
        raw = "Just one chunk of text without numbering."
        seeds = prompts.parse_seeds(raw, expected=4)
        assert len(seeds) == 1


# ---------------------------------------------------------------------------
# Integration: persona frame around builder output
# ---------------------------------------------------------------------------


class TestPromptIntegration:
    """End-to-end: builder + frame produces a single dispatchable string."""

    def test_draft_prompt_round_trip(self) -> None:
        system = prompts.build_draft_system(
            context=SAMPLE_CONTEXT, soul=SAMPLE_SOUL_MD
        )
        user = prompts.build_draft_user(
            brief=MockBrief(target_length=5000),
            context=SAMPLE_CONTEXT,
            seeds=["A seed about silence."],
        )
        wrapped = prompts.wrap_for_subagent(system=system, user=user)

        # The frame is intact
        assert "OUTPUT RULES (non-negotiable):" in wrapped
        # Voice and task survive substitution
        assert SAMPLE_CONTEXT["identity"] in wrapped
        assert "MINIMUM LENGTH: 5000 words" in wrapped
        assert "A seed about silence." in wrapped

    def test_muse_seeds_prompt_structured_round_trip(self) -> None:
        system = prompts.build_muse_seeds_system(seed_count=4)
        user = prompts.build_muse_seeds_user(
            soul=SAMPLE_SOUL_MD,
            brief=SAMPLE_BRIEF_TEXT,
            fandom_context=SAMPLE_FANDOM_CONTEXT,
            seed_count=4,
        )
        wrapped = prompts.wrap_for_subagent_structured(
            system=system,
            user=user,
            output_kind=(
                "a numbered list of 4 seeds, one per line, no preamble"
            ),
        )
        assert "exactly 4 creative seeds" in wrapped
        assert "numbered list of 4 seeds" in wrapped


# ---------------------------------------------------------------------------
# write.muse re-export shim
# ---------------------------------------------------------------------------


class TestMuseShim:
    """write.muse should still re-export parse_seeds for legacy callers."""

    def test_parse_seeds_importable_from_write_muse(self) -> None:
        from write.muse import parse_seeds as muse_parse_seeds

        assert muse_parse_seeds is prompts.parse_seeds


# ---------------------------------------------------------------------------
# Smoke test: ensure no module under write/ imports anthropic
# ---------------------------------------------------------------------------


class TestNoAnthropicImports:
    """Verify the bd-75p migration eliminated direct-API consumers."""

    def test_no_anthropic_under_write(self) -> None:
        write_dir = Path(__file__).resolve().parent.parent / "write"
        offenders = []
        for py_file in write_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            if "import anthropic" in text or "from anthropic" in text:
                offenders.append(str(py_file.relative_to(write_dir)))
        assert offenders == [], (
            f"Files under write/ still import anthropic: {offenders}"
        )

    def test_no_write_api_module(self) -> None:
        """write.api was deleted in bd-75p."""
        with pytest.raises(ImportError):
            import write.api  # noqa: F401
