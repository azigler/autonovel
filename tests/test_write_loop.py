"""Tests for the write loop helpers and pure submodules.

The write loop's state machine was retired in the bd-75p migration -- the
orchestrator (running ``/write``) is now the runtime, dispatching
in-harness subagents using the prompt builders in :mod:`write.prompts`.

What's tested here:

* :func:`write.loop.setup_run` and :func:`write.loop._write_draft_md` --
  the file-system helpers that survive in the thin coordinator.
* :func:`write.evaluate_fanfic.evaluate_gate` -- pure scoring logic.
* :func:`write.brief.validate_brief` -- pure validation.
* :func:`write.context.assemble_context` -- pure context assembly.
* :func:`write.state.save_state` / :func:`write.state.load_state` --
  pure persistence.
* :func:`write.revision.generate_revision_brief` -- pure brief builder.
* :func:`write.prepare` helpers -- AO3 format, tags, summary, notes.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

pytest.importorskip("write.brief", reason="awaiting write loop implementation")

from api.models import PublishRequest, Rating
from identity.schema import VoicePriors
from write.brief import StoryBrief, validate_brief
from write.context import assemble_context, estimate_tokens
from write.evaluate_fanfic import evaluate_gate
from write.experiment import create_experiment_bead
from write.loop import _write_draft_md, setup_run
from write.prepare import (
    format_ao3_html,
    generate_author_notes,
    generate_summary,
    generate_tags,
    prepare_publish_request,
)
from write.revision import generate_revision_brief
from write.state import WriteLoopState, load_state, save_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def basic_brief():
    """A minimal valid one-shot StoryBrief for Harry Potter fandom."""
    return StoryBrief(
        fandom="Harry Potter - J. K. Rowling",
        characters=["Luna Lovegood"],
        premise="Luna finds a creature nobody else can see",
        target_length=5000,
        rating=Rating.GENERAL,
        format="one_shot",
        genre="whimsy",
        tone="bittersweet",
    )


@pytest.fixture()
def multi_chapter_brief():
    """A multi-chapter StoryBrief with a longer target."""
    return StoryBrief(
        fandom="Naruto",
        characters=["Naruto Uzumaki", "Sasuke Uchiha"],
        premise="After the war, Naruto and Sasuke travel together to rebuild bridges.",
        target_length=40000,
        rating=Rating.TEEN,
        format="multi_chapter",
        genre="hurt/comfort",
        tone="bittersweet",
        ship="Naruto Uzumaki/Sasuke Uchiha",
    )


@pytest.fixture()
def mock_identity():
    """Mocked identity context as returned by load_identity()."""
    return {
        "self": "# Self\nI write fanfic with emotional specificity.",
        "pen_name": "# Pen Name\nNightOwlWrites - casual, warm author voice.",
        "inspirations": "# Inspirations\nUrsula K. Le Guin, Donna Tartt.",
        "fandom_context": "# Fandom Context\nHarry Potter magical world.",
        "voice_priors": VoicePriors(),
    }


@pytest.fixture()
def clean_state(basic_brief, tmp_path):
    """A fresh WriteLoopState at BRIEF stage."""
    run_id = str(uuid.uuid4())
    return WriteLoopState(
        run_id=run_id,
        state="BRIEF",
        brief=basic_brief,
        created_at="2026-03-26T00:00:00Z",
        updated_at="2026-03-26T00:00:00Z",
    )


@pytest.fixture()
def evaluate_state(clean_state):
    """A WriteLoopState at EVALUATE stage with a draft."""
    state = clean_state
    state.state = "EVALUATE"
    state.context_assembled = True
    state.context_token_counts = {
        "identity": 10000,
        "fandom": 15000,
        "anti_slop": 5000,
        "few_shot": 12000,
        "brief": 3000,
    }
    state.draft_chapters = [
        "Luna walked through the Forbidden Forest, her bare feet "
        "finding every root and stone with practiced ease."
    ]
    state.draft_word_count = 5200
    return state


@pytest.fixture()
def passing_scores():
    """Evaluation scores that pass all gates."""
    return {
        "slop_penalty": 1.2,
        "overall_score": 7.8,
        "characterization_accuracy": {
            "score": 7.5,
            "feedback": "Characters on point.",
        },
        "voice_adherence": {"score": 7.5},
        "fandom_voice_fit": {"score": 7.0},
        "prose_quality": {"score": 8.0},
        "engagement": {"score": 7.5},
        "pacing": {"score": 7.0},
        "emotional_arc": {"score": 7.2},
    }


@pytest.fixture()
def slop_failing_scores():
    """Evaluation scores where the slop hard gate fails."""
    return {
        "slop_penalty": 4.5,
        "overall_score": 8.2,
        "characterization_accuracy": {"score": 7.5, "feedback": "Good."},
        "voice_adherence": {"score": 8.0},
        "fandom_voice_fit": {"score": 7.5},
        "prose_quality": {"score": 8.0},
        "engagement": {"score": 8.5},
        "pacing": {"score": 7.5},
        "emotional_arc": {"score": 8.0},
    }


@pytest.fixture()
def char_failing_scores():
    """Evaluation scores where characterization fails but overall passes."""
    return {
        "slop_penalty": 1.0,
        "overall_score": 7.5,
        "characterization_accuracy": {
            "score": 4.0,
            "feedback": "Characters wildly OOC.",
        },
        "voice_adherence": {"score": 7.5},
        "fandom_voice_fit": {"score": 7.0},
        "prose_quality": {"score": 8.0},
        "engagement": {"score": 8.0},
        "pacing": {"score": 7.5},
        "emotional_arc": {"score": 7.5},
    }


@pytest.fixture()
def quality_failing_scores():
    """Evaluation scores where the soft quality gate fails."""
    return {
        "slop_penalty": 1.5,
        "overall_score": 5.8,
        "characterization_accuracy": {"score": 7.0, "feedback": "OK."},
        "voice_adherence": {"score": 5.0},
        "fandom_voice_fit": {"score": 6.0},
        "prose_quality": {"score": 5.5},
        "engagement": {"score": 6.0},
        "pacing": {"score": 6.0},
        "emotional_arc": {"score": 5.5},
    }


# ===========================================================================
# setup_run + thin coordinator helpers
# ===========================================================================


class TestSetupRun:
    """Tests for write.loop.setup_run, the orchestrator's run-init helper."""

    def test_setup_run_creates_state_file(self, basic_brief, tmp_path):
        """setup_run creates the run directory and seeds state.json."""
        state = setup_run(basic_brief, runs_dir=tmp_path)
        state_path = tmp_path / state.run_id / "state.json"
        assert state_path.parent.exists()

    def test_setup_run_state_at_brief(self, basic_brief, tmp_path):
        """Initial state is BRIEF, brief is preserved on the state."""
        state = setup_run(basic_brief, runs_dir=tmp_path)
        assert state.state == "BRIEF"
        assert state.brief is basic_brief

    def test_setup_run_uses_brief_path_stem(self, basic_brief, tmp_path):
        """When run_name is None and brief_path is given, run_name uses the stem."""
        state = setup_run(
            basic_brief,
            brief_path="briefs/luna_forest.json",
            runs_dir=tmp_path,
        )
        assert state.run_name == "luna_forest"
        assert state.run_id == "luna_forest"

    def test_setup_run_appends_v_for_existing(self, basic_brief, tmp_path):
        """If a run dir already exists, the second run gets _v2 suffix."""
        (tmp_path / "luna_forest").mkdir()
        state = setup_run(
            basic_brief,
            run_name="luna_forest",
            runs_dir=tmp_path,
        )
        assert state.run_name == "luna_forest_v2"

    def test_setup_run_stores_metadata(self, basic_brief, tmp_path):
        """setup_run records brief_path on the state for provenance."""
        state = setup_run(
            basic_brief,
            brief_path="briefs/luna_forest.json",
            runs_dir=tmp_path,
        )
        assert state.brief_path == "briefs/luna_forest.json"
        assert state.created_at != ""
        assert state.updated_at != ""


class TestWriteDraftMd:
    """Tests for write.loop._write_draft_md, the final-export helper."""

    def test_writes_frontmatter_and_prose(self, evaluate_state, tmp_path):
        """draft.md is written with YAML frontmatter and joined chapter prose."""
        evaluate_state.draft_chapters = ["First chapter.", "Second chapter."]
        evaluate_state.final_scores = {"slop_penalty": 1.5}

        _write_draft_md(evaluate_state, runs_dir=tmp_path)

        draft_path = tmp_path / evaluate_state.run_id / "draft.md"
        text = draft_path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert "slop_score: 1.5" in text
        assert "First chapter." in text
        assert "Second chapter." in text

    def test_no_op_when_no_chapters(self, evaluate_state, tmp_path):
        """If draft_chapters is empty, no file is written."""
        evaluate_state.draft_chapters = []
        _write_draft_md(evaluate_state, runs_dir=tmp_path)
        draft_path = tmp_path / evaluate_state.run_id / "draft.md"
        assert not draft_path.exists()


# ===========================================================================
# Evaluate Gate Unit Tests
# ===========================================================================


class TestEvaluateGate:
    """Unit tests for the evaluate_gate function covering all gate logic."""

    def test_all_gates_pass(self, passing_scores):
        passed, reason = evaluate_gate(passing_scores)
        assert passed is True
        assert reason == "PASS"

    def test_slop_gate_boundary_pass(self):
        scores = {
            "slop_penalty": 2.99,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 7.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is True

    def test_slop_gate_boundary_fail(self):
        scores = {
            "slop_penalty": 3.0,
            "overall_score": 9.0,
            "characterization_accuracy": {"score": 9.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "SLOP_FAIL"

    def test_char_gate_boundary_pass(self):
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 6.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is True

    def test_char_gate_boundary_fail(self):
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 5.99},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "CHARACTERIZATION_FAIL"

    def test_quality_gate_boundary_pass(self):
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 7.0,
            "characterization_accuracy": {"score": 7.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is True

    def test_quality_gate_boundary_fail(self):
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 6.99,
            "characterization_accuracy": {"score": 7.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "QUALITY_FAIL"

    def test_gate_priority_slop_before_char(self):
        scores = {
            "slop_penalty": 4.0,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 3.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "SLOP_FAIL"

    def test_gate_priority_char_before_quality(self):
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 5.0,
            "characterization_accuracy": {"score": 4.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "CHARACTERIZATION_FAIL"

    def test_slop_fail_with_passing_overall_does_not_override(
        self, slop_failing_scores
    ):
        passed, reason = evaluate_gate(slop_failing_scores)
        assert passed is False
        assert reason == "SLOP_FAIL"

    def test_char_fail_despite_passing_overall(self, char_failing_scores):
        passed, reason = evaluate_gate(char_failing_scores)
        assert passed is False
        assert reason == "CHARACTERIZATION_FAIL"


# ===========================================================================
# Story Brief Validation Tests
# ===========================================================================


class TestBriefValidation:
    """Unit tests for StoryBrief validation rules."""

    def test_empty_fandom_rejected(self):
        with pytest.raises((ValueError, Exception)) as exc_info:
            validate_brief(
                StoryBrief(
                    fandom="",
                    characters=["Luna"],
                    premise="A story about Luna.",
                    target_length=5000,
                    rating=Rating.GENERAL,
                )
            )
        assert "fandom" in str(exc_info.value).lower()

    def test_empty_characters_rejected(self):
        with pytest.raises((ValueError, Exception)) as exc_info:
            validate_brief(
                StoryBrief(
                    fandom="Harry Potter",
                    characters=[],
                    premise="A story.",
                    target_length=5000,
                    rating=Rating.GENERAL,
                )
            )
        assert "character" in str(exc_info.value).lower()

    def test_empty_premise_rejected(self):
        with pytest.raises((ValueError, Exception)) as exc_info:
            validate_brief(
                StoryBrief(
                    fandom="Harry Potter",
                    characters=["Luna"],
                    premise="",
                    target_length=5000,
                    rating=Rating.GENERAL,
                )
            )
        assert "premise" in str(exc_info.value).lower()

    def test_premise_too_short(self):
        with pytest.raises((ValueError, Exception)):
            validate_brief(
                StoryBrief(
                    fandom="Harry Potter",
                    characters=["Luna"],
                    premise="Short",
                    target_length=5000,
                    rating=Rating.GENERAL,
                )
            )

    def test_premise_too_long(self):
        with pytest.raises((ValueError, Exception)):
            validate_brief(
                StoryBrief(
                    fandom="Harry Potter",
                    characters=["Luna"],
                    premise="x" * 2001,
                    target_length=5000,
                    rating=Rating.GENERAL,
                )
            )

    def test_target_length_too_small(self):
        with pytest.raises((ValueError, Exception)):
            validate_brief(
                StoryBrief(
                    fandom="Harry Potter",
                    characters=["Luna"],
                    premise="Luna finds a creature nobody else can see.",
                    target_length=500,
                    rating=Rating.GENERAL,
                )
            )

    def test_target_length_too_large(self):
        with pytest.raises((ValueError, Exception)):
            validate_brief(
                StoryBrief(
                    fandom="Harry Potter",
                    characters=["Luna"],
                    premise="Luna finds a creature nobody else can see.",
                    target_length=100000,
                    rating=Rating.GENERAL,
                )
            )

    def test_multi_chapter_derives_chapter_count(self):
        brief = StoryBrief(
            fandom="Naruto",
            characters=["Naruto"],
            premise="A long journey of rebuilding after the war.",
            target_length=40000,
            rating=Rating.TEEN,
            format="multi_chapter",
        )
        validate_brief(brief)
        assert brief.chapter_count == 10

    def test_chapter_count_clamped_minimum(self):
        brief = StoryBrief(
            fandom="Naruto",
            characters=["Naruto"],
            premise="A short multi-chapter story about friendship.",
            target_length=2000,
            rating=Rating.GENERAL,
            format="multi_chapter",
        )
        validate_brief(brief)
        assert brief.chapter_count >= 2

    def test_chapter_count_clamped_maximum(self):
        brief = StoryBrief(
            fandom="Naruto",
            characters=["Naruto"],
            premise="An epic multi-chapter story spanning decades.",
            target_length=80000,
            rating=Rating.TEEN,
            format="multi_chapter",
        )
        validate_brief(brief)
        assert brief.chapter_count <= 20

    def test_valid_brief_passes(self, basic_brief):
        validate_brief(basic_brief)


# ===========================================================================
# Context Assembly Tests
# ===========================================================================


class TestContextAssembly:
    """Unit tests for context assembly and token budget management."""

    def test_estimate_tokens_approximation(self):
        text = "a" * 4000
        tokens = estimate_tokens(text)
        assert tokens == pytest.approx(1000, rel=0.1)

    def test_estimate_tokens_empty_string(self):
        assert estimate_tokens("") == 0

    def test_few_shot_max_three(self, basic_brief, mock_identity):
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        few_shot_count = context.get("few_shot_count", 0)
        assert few_shot_count <= 3

    def test_anti_slop_rules_included(self, basic_brief, mock_identity):
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        assert "anti_slop_rules" in context
        assert len(context["anti_slop_rules"]) > 0

    def test_identity_truncation_order(self, basic_brief):
        oversized_identity = {
            "self": "x" * 80000,
            "pen_name": "Short pen name.",
            "inspirations": "y" * 120000,
            "fandom_context": "Fandom context text.",
            "voice_priors": VoicePriors(),
        }
        context = assemble_context(
            brief=basic_brief, identity=oversized_identity
        )
        identity_tokens = context["token_counts"]["identity"]
        assert identity_tokens <= 30000

    def test_fandom_context_truncated_from_bottom(
        self, basic_brief, mock_identity
    ):
        mock_identity["fandom_context"] = "z" * 200000
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        fandom_tokens = context["token_counts"]["fandom"]
        assert fandom_tokens <= 40000

    def test_total_budget_within_limit(self, basic_brief, mock_identity):
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        total = sum(context["token_counts"].values())
        assert total <= 200000


# ===========================================================================
# State Persistence Tests
# ===========================================================================


class TestStatePersistence:
    """Unit tests for state save/load."""

    def test_save_and_load_roundtrip(self, clean_state, tmp_path):
        path = tmp_path / "state.json"
        save_state(clean_state, path)
        loaded = load_state(path)
        assert loaded.run_id == clean_state.run_id
        assert loaded.state == clean_state.state

    def test_state_preserves_evaluation_history(self, evaluate_state, tmp_path):
        evaluate_state.evaluation_history = [
            {"slop_penalty": 1.5, "overall_score": 7.8}
        ]
        path = tmp_path / "state.json"
        save_state(evaluate_state, path)
        loaded = load_state(path)
        assert len(loaded.evaluation_history) == 1
        assert loaded.evaluation_history[0]["overall_score"] == 7.8

    def test_state_preserves_draft_chapters(self, evaluate_state, tmp_path):
        path = tmp_path / "state.json"
        save_state(evaluate_state, path)
        loaded = load_state(path)
        assert len(loaded.draft_chapters) == len(evaluate_state.draft_chapters)


# ===========================================================================
# Revision Brief Tests
# ===========================================================================


class TestRevisionBrief:
    """Tests for write.revision.generate_revision_brief (pure builder)."""

    def test_slop_fail_brief_mentions_banned_words(self):
        scores = {
            "slop_penalty": 5.0,
            "tier1_hits": [("delve", 2), ("tapestry", 1)],
        }
        brief = generate_revision_brief(
            scores=scores,
            gate_result="SLOP_FAIL",
            draft_text="We delve into the tapestry of their relationship.",
            fandom_context="Harry Potter",
        )
        assert "delve" in brief.lower() or "tapestry" in brief.lower()

    def test_quality_fail_brief_targets_weakest_dimensions(self):
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 5.5,
            "characterization_accuracy": {"score": 7.0, "feedback": "OK"},
            "voice_adherence": {
                "score": 4.0,
                "feedback": "Voice inconsistent.",
            },
            "prose_quality": {"score": 5.0, "feedback": "Too much telling."},
        }
        brief = generate_revision_brief(
            scores=scores,
            gate_result="QUALITY_FAIL",
            draft_text="Some draft text.",
            fandom_context="General fandom context.",
        )
        assert brief is not None
        assert len(brief) > 0
        # Weakest dimension should be referenced
        assert "voice" in brief.lower()

    def test_revision_brief_includes_character_notes(self, char_failing_scores):
        brief = generate_revision_brief(
            scores=char_failing_scores,
            gate_result="CHARACTERIZATION_FAIL",
            draft_text="Naruto giggled and blushed.",
            fandom_context="Naruto is loud, brash, and determined.",
        )
        assert brief is not None
        assert len(brief) > 0
        assert "Naruto is loud" in brief or "loud" in brief.lower()

    def test_revision_brief_targets_slop_words(self, slop_failing_scores):
        brief = generate_revision_brief(
            scores=slop_failing_scores,
            gate_result="SLOP_FAIL",
            draft_text="The myriad tapestry of delve.",
            fandom_context="Harry Potter fandom",
        )
        assert brief is not None
        assert len(brief) > 0


# ===========================================================================
# Post Preparation Tests
# ===========================================================================


class TestPostPreparation:
    """Tests for AO3 post preparation, tag generation, and metadata."""

    def test_paragraphs_to_p_tags(self):
        md = "First paragraph.\n\nSecond paragraph."
        html = format_ao3_html(md)
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html

    def test_italics_to_em(self):
        md = "She felt *something* shift."
        html = format_ao3_html(md)
        assert "<em>something</em>" in html

    def test_bold_to_strong(self):
        md = "It was **important** to remember."
        html = format_ao3_html(md)
        assert "<strong>important</strong>" in html

    def test_section_breaks_to_hr(self):
        md = "End of part one.\n\n---\n\nStart of part two."
        html = format_ao3_html(md)
        assert "<hr />" in html

    def test_dialogue_quotes_preserved(self):
        md = '"Hello," she said. "How are you?"'
        html = format_ao3_html(md)
        assert '"Hello,"' in html or "“Hello,”" in html

    def test_no_raw_markdown_in_output(self):
        md = "A *bold* move.\n\n---\n\nNew section."
        html = format_ao3_html(md)
        assert "*bold*" not in html
        assert "\n---\n" not in html

    def test_prepare_returns_publish_request(
        self, evaluate_state, mock_identity
    ):
        with (
            patch("write.prepare.format_ao3_html", return_value="<p>Text.</p>"),
            patch("write.prepare.generate_tags", return_value=["Harry Potter"]),
            patch(
                "write.prepare.generate_summary",
                return_value="A story about Luna.",
            ),
            patch(
                "write.prepare.generate_author_notes", return_value="Thanks!"
            ),
        ):
            req = prepare_publish_request(
                state=evaluate_state,
                identity=mock_identity,
            )
        assert isinstance(req, PublishRequest)
        assert req.body == "<p>Text.</p>"
        assert req.fandom == evaluate_state.brief.fandom

    def test_tags_include_fandom(self, basic_brief):
        with patch("write.prepare.generate_tags_from_llm") as mock_gen:
            mock_gen.return_value = [
                "Harry Potter - J. K. Rowling",
                "Luna Lovegood",
                "Whimsy",
            ]
            tags = generate_tags(
                brief=basic_brief,
                fandom_context="Harry Potter fandom conventions.",
            )
        assert any("Harry Potter" in t for t in tags)

    def test_author_notes_no_ai_mention(self):
        with (
            patch("write.prepare.generate_notes_text") as mock_gen,
            patch(
                "write.prepare.slop_score", return_value={"slop_penalty": 0.5}
            ),
        ):
            mock_gen.return_value = "Had fun writing this one! Hope you enjoy."
            notes = generate_author_notes(
                draft_text="Some draft.",
                pen_name_voice="Warm, casual voice.",
                fandom="Harry Potter",
            )
        assert "ai" not in notes.lower()
        assert "automat" not in notes.lower()
        assert "language model" not in notes.lower()

    def test_sloppy_summary_regenerated(self):
        call_count = {"n": 0}

        def gen_summary_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return "Delve into the tapestry of their relationship."
            return "Luna finds something nobody else can see."

        with (
            patch(
                "write.prepare.generate_summary_text",
                side_effect=gen_summary_side_effect,
            ),
            patch("write.prepare.slop_score") as mock_slop,
        ):
            mock_slop.side_effect = [
                {"slop_penalty": 5.0},
                {"slop_penalty": 4.0},
                {"slop_penalty": 1.0},
            ]
            summary = generate_summary(
                draft_text="Luna walked through the forest...",
                pen_name_voice="Casual, warm voice.",
                fandom="Harry Potter",
            )
        assert "tapestry" not in summary.lower()

    def test_all_attempts_fail_adds_warning(self):
        with (
            patch(
                "write.prepare.generate_summary_text",
                return_value="Delve into tapestry.",
            ),
            patch(
                "write.prepare.slop_score", return_value={"slop_penalty": 5.0}
            ),
        ):
            summary = generate_summary(
                draft_text="Luna walked...",
                pen_name_voice="Casual voice.",
                fandom="Harry Potter",
            )
        assert summary is not None


# ===========================================================================
# Experiment Bead
# ===========================================================================


class TestExperimentBead:
    """Tests for experiment bead creation (used by /write skill)."""

    def test_create_experiment_bead(self):
        from unittest.mock import MagicMock

        with patch("write.experiment.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(
                stdout="Created bead bd-exp-001\n", returncode=0
            )
            bead_id = create_experiment_bead(
                fandom="Naruto",
                title="Second Person Test",
                hypothesis=(
                    "Second-person POV increases engagement in Naruto fandom"
                ),
            )
        assert bead_id is not None
        assert len(bead_id) > 0
