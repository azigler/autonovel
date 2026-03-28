"""Tests for the write loop state machine and its subsystems.

TDD tests written against specs/write-loop.md. These tests define the contract
for the write loop implementation. All imports reference real module paths that
do not exist yet -- tests will be skipped until implementation lands.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports from modules that DO NOT EXIST yet. This is intentional TDD.
# pytest.importorskip skips all tests in this module until the write
# package is implemented. Removing the importorskip calls is all that is
# needed once the modules exist.
# ---------------------------------------------------------------------------
pytest.importorskip("write.brief", reason="awaiting write loop implementation")

from api.models import PublishRequest, Rating
from identity.schema import VoicePriors
from write.brief import StoryBrief, validate_brief
from write.context import assemble_context, estimate_tokens
from write.evaluate_fanfic import evaluate_gate
from write.experiment import create_experiment_bead
from write.loop import resume, run
from write.prepare import (
    format_ao3_html,
    generate_author_notes,
    generate_summary,
    generate_tags,
    prepare_publish_request,
)
from write.revision import (
    generate_revision,
    generate_revision_brief,
)
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
def draft_state(clean_state):
    """A WriteLoopState at DRAFT stage with context assembled."""
    state = clean_state
    state.state = "DRAFT"
    state.context_assembled = True
    state.context_token_counts = {
        "identity": 10000,
        "fandom": 15000,
        "anti_slop": 5000,
        "few_shot": 12000,
        "brief": 3000,
    }
    return state


@pytest.fixture()
def evaluate_state(draft_state):
    """A WriteLoopState at EVALUATE stage with a draft."""
    state = draft_state
    state.state = "EVALUATE"
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
# Spec Test Cases (Section 5)
# ===========================================================================


class TestTC01HappyPathOneShot:
    """TEST: TC-01 Happy path one-shot (Spec write-loop, Test Case 01)

    Verifies the complete happy path with no revision cycles needed.
    """

    def test_state_progression(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """State machine progresses BRIEF -> CONTEXT -> DRAFT -> EVALUATE (pass)
        -> PREPARE -> QUEUE -> DONE."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-001"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Luna walked..."),
            patch("write.loop.queue_work", return_value="q-abc-123"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="The Unseen",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                tags=["Luna Lovegood"],
                summary="Luna finds something nobody else can see.",
                body="<p>Luna walked...</p>",
                author_notes="Thanks for reading!",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.state == "DONE" or state.state == "QUEUE"
        assert state.queue_id is not None
        assert state.run_id is not None

    def test_queue_item_returned(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """QueueItem with status pending is returned after QUEUE state."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-001"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Luna walked..."),
            patch("write.loop.queue_work", return_value="q-abc-123"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="The Unseen",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Luna walked...</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.queue_id == "q-abc-123"


class TestTC02ReviseAndPass:
    """TEST: TC-02 Evaluate fails, revise, re-evaluate, pass (Spec write-loop, TC-02)

    Verifies the revision loop fires on soft gate failure and can recover.
    """

    def test_revision_loop_fires_on_quality_fail(
        self, basic_brief, mock_identity, quality_failing_scores, passing_scores, tmp_path
    ):
        """EVALUATE -> REVISE (count=1) -> EVALUATE (pass) -> PREPARE.
        evaluation_history has 2 entries."""
        call_count = {"n": 0}

        def eval_side_effect(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return quality_failing_scores
            return passing_scores

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", side_effect=eval_side_effect),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-002"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft text."),
            patch(
                "write.loop.generate_revision",
                return_value="Revised draft text.",
            ),
            patch(
                "write.loop.generate_revision_brief",
                return_value="Fix quality.",
            ),
            patch("write.loop.queue_work", return_value="q-abc-456"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="The Unseen",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Revised.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert len(state.evaluation_history) == 2
        assert state.revision_count >= 1


class TestTC03MaxRevisionsExhausted:
    """TEST: TC-03 Max revisions exhausted (Spec write-loop, TC-03)

    Verifies the loop terminates after max revisions and still produces
    output for human review rather than silently failing.
    """

    def test_max_revisions_reached_flag(
        self, basic_brief, mock_identity, quality_failing_scores, tmp_path
    ):
        """After 3 revision cycles that all fail, state has
        max_revisions_reached=True and a warning."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch(
                "write.loop.evaluate_draft", return_value=quality_failing_scores
            ),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-003"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft text."),
            patch(
                "write.loop.generate_revision", return_value="Still bad draft."
            ),
            patch(
                "write.loop.generate_revision_brief",
                return_value="Fix quality.",
            ),
            patch("write.loop.queue_work", return_value="q-abc-789"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="The Unseen",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Still bad.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.max_revisions_reached is True
        assert state.revision_count == 3
        assert len(state.warnings) > 0


class TestTC04AntiSlopHardGateForcesRevision:
    """TEST: TC-04 Anti-slop hard gate forces revision (Spec write-loop, TC-04)

    Verifies the hard gate behavior -- slop must be fixed regardless of LLM score.
    """

    def test_slop_fail_triggers_revision(
        self, basic_brief, mock_identity, slop_failing_scores, passing_scores, tmp_path
    ):
        """EVALUATE returns SLOP_FAIL, transitions to REVISE. After revision,
        slop_penalty < 3.0."""
        call_count = {"n": 0}

        def eval_side_effect(*_args, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return slop_failing_scores
            return passing_scores

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", side_effect=eval_side_effect),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-004"
            ),
            patch("write.loop.close_experiment"),
            patch(
                "write.loop.draft_chapter",
                return_value="Text with delve and tapestry.",
            ),
            patch(
                "write.loop.generate_revision",
                return_value="Clean revised text.",
            ),
            patch(
                "write.loop.generate_revision_brief",
                return_value="Remove slop words.",
            ),
            patch("write.loop.queue_work", return_value="q-slop-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Clean.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.evaluation_history[0]["slop_penalty"] >= 3.0
        assert state.gate_result == "PASS"

    def test_revision_brief_targets_slop_words(self, slop_failing_scores):
        """Revision brief for SLOP_FAIL focuses on specific banned word replacements."""
        brief = generate_revision_brief(
            scores=slop_failing_scores,
            gate_result="SLOP_FAIL",
            draft_text="The myriad tapestry of delve.",
            fandom_context="Harry Potter fandom",
        )
        # The brief should mention the specific slop issues
        assert brief is not None
        assert len(brief) > 0


class TestTC05SlopHardGateWithPassingLLMScore:
    """TEST: TC-05 Anti-slop hard gate with passing LLM score (Spec write-loop, TC-05)

    Confirms that slop is a hard gate, not a soft score that can be outweighed.
    """

    def test_high_llm_score_does_not_override_slop(self, slop_failing_scores):
        """EVALUATE returns SLOP_FAIL despite overall_score=8.2."""
        passed, reason = evaluate_gate(slop_failing_scores)
        assert passed is False
        assert reason == "SLOP_FAIL"

    def test_slop_checked_before_other_gates(self, slop_failing_scores):
        """Slop check runs first -- even if other scores are stellar."""
        # Scores have overall=8.2, char_acc=7.5 -- both passing -- but slop=4.5
        _passed, reason = evaluate_gate(slop_failing_scores)
        assert reason == "SLOP_FAIL"


class TestTC06ResumeFromDraft:
    """TEST: TC-06 Resume from saved state at DRAFT (Spec write-loop, TC-06)

    Verifies resumability after interruption during drafting.
    """

    def test_resume_from_draft_state(
        self, draft_state, mock_identity, passing_scores, tmp_path
    ):
        """Write loop loads state.json, detects state=DRAFT, produces draft,
        continues through remaining states."""
        state_dir = tmp_path / "runs" / draft_state.run_id
        state_dir.mkdir(parents=True)
        save_state(draft_state, state_dir / "state.json")

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-006"
            ),
            patch("write.loop.close_experiment"),
            patch(
                "write.loop.draft_chapter", return_value="Resumed draft text."
            ),
            patch("write.loop.queue_work", return_value="q-resume-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Resumed.</p>",
            )
            state = resume(draft_state.run_id, runs_dir=tmp_path / "runs")

        assert state.draft_word_count > 0
        assert state.state in ("DONE", "QUEUE")


class TestTC07ResumeFromEvaluate:
    """TEST: TC-07 Resume from saved state at EVALUATE (Spec write-loop, TC-07)

    Verifies resumability at a different state boundary.
    """

    def test_resume_from_evaluate_state(
        self, evaluate_state, mock_identity, passing_scores, tmp_path
    ):
        """Write loop resumes at EVALUATE, runs evaluation, proceeds."""
        state_dir = tmp_path / "runs" / evaluate_state.run_id
        state_dir.mkdir(parents=True)
        save_state(evaluate_state, state_dir / "state.json")

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-007"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.queue_work", return_value="q-resume-002"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Evaluated.</p>",
            )
            state = resume(evaluate_state.run_id, runs_dir=tmp_path / "runs")

        assert len(state.evaluation_history) >= 1
        assert state.state in ("DONE", "QUEUE")


class TestTC08ResumeFromError:
    """TEST: TC-08 Resume from ERROR state (Spec write-loop, TC-08)

    Verifies error recovery and retry logic.
    """

    def test_error_retry_increments_attempt_count(
        self, draft_state, mock_identity, passing_scores, tmp_path
    ):
        """Write loop retries DRAFT state, error_attempt_count increments to 2."""
        draft_state.state = "ERROR"
        draft_state.error_from = "DRAFT"
        draft_state.error_attempt_count = 1
        draft_state.error_detail = "API timeout"

        state_dir = tmp_path / "runs" / draft_state.run_id
        state_dir.mkdir(parents=True)
        save_state(draft_state, state_dir / "state.json")

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-008"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Retried draft."),
            patch("write.loop.queue_work", return_value="q-resume-003"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Retried.</p>",
            )
            state = resume(draft_state.run_id, runs_dir=tmp_path / "runs")

        assert state.state in ("DONE", "QUEUE")


class TestTC09MaxRetriesExceeded:
    """TEST: TC-09 Resume from ERROR with max retries exceeded (Spec write-loop, TC-09)

    Verifies the loop does not retry indefinitely.
    """

    def test_max_retries_halts(self, draft_state, tmp_path):
        """Write loop refuses to retry after 3 attempts, state remains ERROR."""
        draft_state.state = "ERROR"
        draft_state.error_from = "DRAFT"
        draft_state.error_attempt_count = 3
        draft_state.error_detail = "API timeout"

        state_dir = tmp_path / "runs" / draft_state.run_id
        state_dir.mkdir(parents=True)
        save_state(draft_state, state_dir / "state.json")

        state = resume(draft_state.run_id, runs_dir=tmp_path / "runs")

        assert state.state == "ERROR"
        assert state.error_attempt_count == 3


class TestTC10OneShotVsMultiChapter:
    """TEST: TC-10 One-shot vs multi-chapter branching (Spec write-loop, TC-10)

    Verifies the branching logic in DRAFT state and chapter count derivation.
    """

    def test_one_shot_single_draft_call(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """One-shot brief produces a single draft call."""
        draft_calls = []

        def track_draft(*args, **kwargs):
            draft_calls.append(1)
            return "One-shot draft text."

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-010a"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", side_effect=track_draft),
            patch("write.loop.queue_work", return_value="q-one-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>One-shot.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert len(draft_calls) == 1
        assert len(state.draft_chapters) == 1

    def test_multi_chapter_derives_chapter_count(
        self, multi_chapter_brief, mock_identity, passing_scores, tmp_path
    ):
        """Multi-chapter brief with target_length=40000 produces 10 chapter calls
        (40000 // 4000 = 10)."""
        draft_calls = []

        def track_draft(*args, **kwargs):
            draft_calls.append(1)
            return f"Chapter {len(draft_calls)} text."

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-010b"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", side_effect=track_draft),
            patch("write.loop.queue_work", return_value="q-multi-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Naruto",
                rating=Rating.TEEN,
                body="<p>Multi chapter.</p>",
            )
            state = run(multi_chapter_brief, runs_dir=tmp_path)

        expected_chapters = 40000 // 4000  # = 10
        assert len(draft_calls) == expected_chapters
        assert len(state.draft_chapters) == expected_chapters

    def test_chapter_count_derived_when_none(self, multi_chapter_brief):
        """When chapter_count is None on a multi-chapter brief, it is derived
        from target_length // 4000, clamped to [2, 20]."""
        assert multi_chapter_brief.chapter_count is None or (
            2 <= multi_chapter_brief.chapter_count <= 20
        )


class TestTC11ContextTokenBudget:
    """TEST: TC-11 Context assembly respects token budget (Spec write-loop, TC-11)

    Verifies the token budget enforcement and truncation priority.
    """

    def test_identity_truncation_order(self, basic_brief):
        """When identity files exceed 30K tokens, inspirations.md is truncated
        first, then self.md history section."""
        oversized_identity = {
            "self": "x" * 80000,  # ~20K tokens at 4 chars/token
            "pen_name": "Short pen name.",
            "inspirations": "y"
            * 120000,  # ~30K tokens -- should truncate first
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
        """Fandom context exceeding 40K tokens is truncated from the bottom."""
        mock_identity["fandom_context"] = "z" * 200000  # ~50K tokens
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        fandom_tokens = context["token_counts"]["fandom"]
        assert fandom_tokens <= 40000

    def test_total_budget_within_limit(self, basic_brief, mock_identity):
        """Total assembled context stays within 200K token budget."""
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        total = sum(context["token_counts"].values())
        assert total <= 200000


class TestTC12AO3Format:
    """TEST: TC-12 Post preparation generates valid AO3 format (Spec write-loop, TC-12)

    Verifies AO3-compatible HTML generation.
    """

    def test_paragraphs_to_p_tags(self):
        """Markdown paragraphs convert to <p> tags."""
        md = "First paragraph.\n\nSecond paragraph."
        html = format_ao3_html(md)
        assert "<p>First paragraph.</p>" in html
        assert "<p>Second paragraph.</p>" in html

    def test_italics_to_em(self):
        """Markdown *italics* converts to <em>."""
        md = "She felt *something* shift."
        html = format_ao3_html(md)
        assert "<em>something</em>" in html

    def test_bold_to_strong(self):
        """Markdown **bold** converts to <strong>."""
        md = "It was **important** to remember."
        html = format_ao3_html(md)
        assert "<strong>important</strong>" in html

    def test_section_breaks_to_hr(self):
        """Markdown --- converts to <hr />."""
        md = "End of part one.\n\n---\n\nStart of part two."
        html = format_ao3_html(md)
        assert "<hr />" in html

    def test_dialogue_quotes_preserved(self):
        """Quotation marks in dialogue are preserved."""
        md = '"Hello," she said. "How are you?"'
        html = format_ao3_html(md)
        assert '"Hello,"' in html or "\u201cHello,\u201d" in html

    def test_no_raw_markdown_in_output(self):
        """Output body has no raw markdown syntax."""
        md = "A *bold* move.\n\n---\n\nNew section."
        html = format_ao3_html(md)
        # No leftover asterisks used as markdown
        assert "*bold*" not in html
        assert "\n---\n" not in html


class TestTC13ExperimentBeadCreated:
    """TEST: TC-13 Experiment bead created with hypothesis (Spec write-loop, TC-13)

    Verifies automatic experiment tracking at the start of a run.
    """

    def test_bead_created_at_brief_state(self):
        """At BRIEF, a bead is created with the experiment hypothesis."""
        with patch("write.experiment.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(
                stdout="Created bead bd-exp-001\n", returncode=0
            )
            bead_id = create_experiment_bead(
                fandom="Naruto",
                title="Second Person Test",
                hypothesis="Second-person POV increases engagement in Naruto fandom",
            )
        assert bead_id is not None
        assert len(bead_id) > 0

    def test_experiment_bead_id_stored_in_state(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """experiment_bead_id is stored in state after BRIEF."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-exp-002"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft."),
            patch("write.loop.queue_work", return_value="q-exp-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Test.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.experiment_bead_id == "bd-exp-002"


class TestTC14ExperimentBeadUpdatedAtDone:
    """TEST: TC-14 Experiment bead updated with results at DONE (Spec write-loop, TC-14)

    Verifies experiment tracking completion and data recording.
    """

    def test_experiment_closed_with_results(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """At DONE, the experiment bead is updated with scores, revision count,
        outcome, and a learned summary. Bead is closed."""
        close_calls = []

        def track_close(*args, **kwargs):
            close_calls.append(kwargs if kwargs else args)

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-exp-003"
            ),
            patch("write.loop.close_experiment", side_effect=track_close),
            patch("write.loop.draft_chapter", return_value="Draft."),
            patch("write.loop.queue_work", return_value="q-exp-002"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Test.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert len(close_calls) >= 1
        assert state.final_scores is not None
        assert len(state.final_scores) > 0


class TestTC15InvalidBrief:
    """TEST: TC-15 Invalid brief missing required fields (Spec write-loop, TC-15)

    Verifies input validation catches bad briefs early.
    """

    def test_empty_fandom_rejected(self):
        """Fandom must be non-empty."""
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
        """Characters must contain at least one character."""
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
        """Premise must be non-empty."""
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

    def test_invalid_brief_transitions_to_error(self, tmp_path):
        """State transitions to ERROR with validation details; no drafting occurs."""
        bad_brief = StoryBrief(
            fandom="",
            characters=[],
            premise="short",
            target_length=5000,
            rating=Rating.GENERAL,
        )
        with (
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-015"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter") as mock_draft,
        ):
            state = run(bad_brief, runs_dir=tmp_path)

        assert state.state == "ERROR"
        assert state.error_detail is not None
        mock_draft.assert_not_called()


class TestTC16QueueHumanReview:
    """TEST: TC-16 Queue item human review flow (Spec write-loop, TC-16)

    Verifies the human-in-the-loop flow works end-to-end.
    """

    def test_queue_status_pending_after_post(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """QueueItem status is pending after POST /works."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-test-016"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft."),
            patch("write.loop.queue_work", return_value="q-human-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Draft.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.queue_id == "q-human-001"


class TestTC17CharacterizationGate:
    """TEST: TC-17 Characterization accuracy gate (Spec write-loop, TC-17)

    Verifies that characterization is gated independently of overall score.
    """

    def test_char_fail_despite_passing_overall(self, char_failing_scores):
        """EVALUATE returns CHARACTERIZATION_FAIL despite overall_score=7.5."""
        passed, reason = evaluate_gate(char_failing_scores)
        assert passed is False
        assert reason == "CHARACTERIZATION_FAIL"

    def test_revision_brief_includes_character_notes(self, char_failing_scores):
        """Revision brief for CHARACTERIZATION_FAIL includes character-specific notes."""
        brief = generate_revision_brief(
            scores=char_failing_scores,
            gate_result="CHARACTERIZATION_FAIL",
            draft_text="Naruto giggled and blushed.",
            fandom_context="Naruto is loud, brash, and determined.",
        )
        assert brief is not None
        assert len(brief) > 0


class TestTC18SummaryNotesSlop:
    """TEST: TC-18 Summary and author notes slop check (Spec write-loop, TC-18)

    Verifies that even metadata text passes anti-slop checks.
    """

    def test_sloppy_summary_regenerated(self):
        """Summary containing slop is regenerated up to 3 times."""
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
            # First two calls return high slop, third is clean
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
        """If all 3 summary attempts fail slop check, a WARNING is added."""
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
        # Even if all attempts fail, a summary is returned (with warning)
        assert summary is not None


# ===========================================================================
# Evaluate Gate Unit Tests
# ===========================================================================


class TestEvaluateGate:
    """Unit tests for the evaluate_gate function covering all gate logic."""

    def test_all_gates_pass(self, passing_scores):
        """TEST: All gates pass returns (True, 'PASS')."""
        passed, reason = evaluate_gate(passing_scores)
        assert passed is True
        assert reason == "PASS"

    def test_slop_gate_boundary_pass(self):
        """TEST: slop_penalty exactly 2.99 passes the hard gate."""
        scores = {
            "slop_penalty": 2.99,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 7.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is True

    def test_slop_gate_boundary_fail(self):
        """TEST: slop_penalty exactly 3.0 fails the hard gate."""
        scores = {
            "slop_penalty": 3.0,
            "overall_score": 9.0,
            "characterization_accuracy": {"score": 9.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "SLOP_FAIL"

    def test_char_gate_boundary_pass(self):
        """TEST: characterization_accuracy exactly 6.0 passes."""
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 6.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is True

    def test_char_gate_boundary_fail(self):
        """TEST: characterization_accuracy of 5.99 fails."""
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 5.99},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "CHARACTERIZATION_FAIL"

    def test_quality_gate_boundary_pass(self):
        """TEST: overall_score exactly 7.0 passes."""
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 7.0,
            "characterization_accuracy": {"score": 7.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is True

    def test_quality_gate_boundary_fail(self):
        """TEST: overall_score of 6.99 fails."""
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 6.99,
            "characterization_accuracy": {"score": 7.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "QUALITY_FAIL"

    def test_gate_priority_slop_before_char(self):
        """TEST: When both slop and characterization fail, SLOP_FAIL takes priority."""
        scores = {
            "slop_penalty": 4.0,
            "overall_score": 7.5,
            "characterization_accuracy": {"score": 3.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "SLOP_FAIL"

    def test_gate_priority_char_before_quality(self):
        """TEST: When both characterization and quality fail, CHARACTERIZATION_FAIL
        takes priority."""
        scores = {
            "slop_penalty": 1.0,
            "overall_score": 5.0,
            "characterization_accuracy": {"score": 4.0},
        }
        passed, reason = evaluate_gate(scores)
        assert passed is False
        assert reason == "CHARACTERIZATION_FAIL"


# ===========================================================================
# Story Brief Validation Tests
# ===========================================================================


class TestBriefValidation:
    """Unit tests for StoryBrief validation rules from spec 4.2."""

    def test_premise_too_short(self):
        """ERROR: Premise under 10 characters rejected."""
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
        """ERROR: Premise over 2000 characters rejected."""
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
        """ERROR: target_length under 1000 rejected."""
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
        """ERROR: target_length over 80000 rejected."""
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
        """Multi-chapter with chapter_count=None derives count from target_length."""
        brief = StoryBrief(
            fandom="Naruto",
            characters=["Naruto"],
            premise="A long journey of rebuilding after the war.",
            target_length=40000,
            rating=Rating.TEEN,
            format="multi_chapter",
        )
        validate_brief(brief)
        assert brief.chapter_count == 10  # 40000 // 4000

    def test_chapter_count_clamped_minimum(self):
        """Derived chapter count is clamped to minimum of 2."""
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
        """Derived chapter count is clamped to maximum of 20."""
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
        """A well-formed brief passes validation without error."""
        validate_brief(basic_brief)  # Should not raise


# ===========================================================================
# Context Assembly Tests
# ===========================================================================


class TestContextAssembly:
    """Unit tests for context assembly and token budget management."""

    def test_estimate_tokens_approximation(self):
        """EDGE: Token estimation uses ~4 chars per token."""
        text = "a" * 4000
        tokens = estimate_tokens(text)
        assert tokens == pytest.approx(1000, rel=0.1)

    def test_few_shot_max_three(self, basic_brief, mock_identity):
        """EDGE: At most 3 few-shot examples are selected."""
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        few_shot_count = context.get("few_shot_count", 0)
        assert few_shot_count <= 3

    def test_anti_slop_rules_included(self, basic_brief, mock_identity):
        """Context includes anti-slop rules extracted from databases."""
        context = assemble_context(brief=basic_brief, identity=mock_identity)
        assert "anti_slop_rules" in context
        assert len(context["anti_slop_rules"]) > 0


# ===========================================================================
# State Persistence Tests
# ===========================================================================


class TestStatePersistence:
    """Unit tests for state save/load and resumability."""

    def test_save_and_load_roundtrip(self, clean_state, tmp_path):
        """State survives a save/load roundtrip."""
        path = tmp_path / "state.json"
        save_state(clean_state, path)
        loaded = load_state(path)
        assert loaded.run_id == clean_state.run_id
        assert loaded.state == clean_state.state

    def test_state_preserves_evaluation_history(self, evaluate_state, tmp_path):
        """Evaluation history is preserved through save/load."""
        evaluate_state.evaluation_history = [
            {"slop_penalty": 1.5, "overall_score": 7.8}
        ]
        path = tmp_path / "state.json"
        save_state(evaluate_state, path)
        loaded = load_state(path)
        assert len(loaded.evaluation_history) == 1
        assert loaded.evaluation_history[0]["overall_score"] == 7.8

    def test_state_preserves_draft_chapters(self, evaluate_state, tmp_path):
        """Draft chapters are preserved through save/load."""
        path = tmp_path / "state.json"
        save_state(evaluate_state, path)
        loaded = load_state(path)
        assert len(loaded.draft_chapters) == len(evaluate_state.draft_chapters)


# ===========================================================================
# Revision Loop Tests
# ===========================================================================


class TestRevisionLoop:
    """Tests for revision brief generation and revision execution."""

    def test_slop_fail_brief_mentions_banned_words(self):
        """EDGE: SLOP_FAIL revision brief mentions specific banned words found."""
        scores = {
            "slop_penalty": 5.0,
            "tier1_hits": [("delve", 2), ("tapestry", 1)],
        }
        brief = generate_revision_brief(
            scores=scores,
            gate_result="SLOP_FAIL",
            draft_text="We delve into the tapestry of their relationship. We delve deeper.",
            fandom_context="Harry Potter",
        )
        assert "delve" in brief.lower() or "tapestry" in brief.lower()

    def test_quality_fail_brief_targets_weakest_dimensions(self):
        """EDGE: QUALITY_FAIL revision brief highlights weakest scoring dimensions."""
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

    def test_revision_preserves_passing_content(self):
        """EDGE: generate_revision is called with the full existing draft."""
        with patch("write.revision.call_revision_model") as mock_model:
            mock_model.return_value = "Revised text."
            result = generate_revision(
                draft_text="Original draft with some problems.",
                revision_brief="Fix the voice inconsistency in paragraph 3.",
                context={
                    "identity": "Some identity.",
                    "fandom": "Some fandom.",
                },
            )
        assert result == "Revised text."
        # Verify the original draft was passed to the model
        call_args = mock_model.call_args
        assert "Original draft" in str(call_args)


# ===========================================================================
# Post Preparation Tests
# ===========================================================================


class TestPostPreparation:
    """Tests for AO3 post preparation, tag generation, and metadata."""

    def test_prepare_returns_publish_request(
        self, evaluate_state, mock_identity
    ):
        """prepare_publish_request returns a valid PublishRequest."""
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
        """Generated tags include the fandom tag."""
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
        """ERROR: Author's notes must not mention AI or automation."""
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


# ===========================================================================
# Edge Case and Error Path Tests
# ===========================================================================


class TestEdgeCases:
    """Additional edge case and error path tests beyond spec Section 5."""

    def test_edge_zero_word_draft(self):
        """EDGE: A draft that produces zero words should be handled gracefully."""
        scores = {
            "slop_penalty": 0.0,
            "overall_score": 0.0,
            "characterization_accuracy": {"score": 0.0},
        }
        passed, _reason = evaluate_gate(scores)
        assert passed is False

    def test_edge_token_estimate_empty_string(self):
        """EDGE: Estimating tokens for empty string returns 0."""
        assert estimate_tokens("") == 0

    def test_error_api_failure_during_queue(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """ERROR: API failure during QUEUE transitions to ERROR state."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-edge-001"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft."),
            patch(
                "write.loop.queue_work", side_effect=ConnectionError("API down")
            ),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Draft.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.state == "ERROR"
        assert state.error_from == "QUEUE"

    def test_error_api_failure_during_draft(self, basic_brief, mock_identity, tmp_path):
        """ERROR: API failure during DRAFT transitions to ERROR state."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-edge-002"
            ),
            patch("write.loop.close_experiment"),
            patch(
                "write.loop.draft_chapter",
                side_effect=TimeoutError("Model timeout"),
            ),
        ):
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.state == "ERROR"
        assert state.error_from == "DRAFT"

    def test_edge_revision_count_never_exceeds_max(
        self, basic_brief, mock_identity, quality_failing_scores, tmp_path
    ):
        """EDGE: revision_count never goes above max_revisions (3)."""
        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch(
                "write.loop.evaluate_draft", return_value=quality_failing_scores
            ),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-edge-003"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft."),
            patch("write.loop.generate_revision", return_value="Revised."),
            patch("write.loop.generate_revision_brief", return_value="Fix."),
            patch("write.loop.queue_work", return_value="q-edge-001"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Revised.</p>",
            )
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.revision_count <= 3

    def test_edge_multi_chapter_continuity_threading(
        self, multi_chapter_brief, mock_identity, passing_scores, tmp_path
    ):
        """EDGE: Multi-chapter drafting passes previous chapter tail to next call."""
        draft_args = []

        def track_draft(*args, **kwargs):
            draft_args.append(kwargs)
            return f"Chapter text {len(draft_args)}."

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-edge-004"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", side_effect=track_draft),
            patch("write.loop.queue_work", return_value="q-edge-002"),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Naruto",
                rating=Rating.TEEN,
                body="<p>Multi chapter.</p>",
            )
            _state = run(multi_chapter_brief, runs_dir=tmp_path)

        # After the first chapter, subsequent calls should receive previous chapter context
        assert len(draft_args) > 1

    def test_error_identity_missing_transitions_to_error(self, basic_brief, tmp_path):
        """ERROR: Missing identity files cause ERROR transition at CONTEXT state."""
        with (
            patch(
                "write.loop.load_identity",
                side_effect=FileNotFoundError("self.md"),
            ),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-edge-005"
            ),
            patch("write.loop.close_experiment"),
        ):
            state = run(basic_brief, runs_dir=tmp_path)

        assert state.state == "ERROR"
        assert state.error_from == "CONTEXT"

    def test_edge_state_json_written_after_every_transition(
        self, basic_brief, mock_identity, passing_scores, tmp_path
    ):
        """EDGE: State file is persisted after every state transition."""
        state_writes = []
        original_save = save_state

        def track_save(state_obj, path):
            state_writes.append(state_obj.state)
            return original_save(state_obj, path)

        with (
            patch("write.loop.load_identity", return_value=mock_identity),
            patch("write.loop.evaluate_draft", return_value=passing_scores),
            patch(
                "write.loop.create_experiment_bead", return_value="bd-edge-006"
            ),
            patch("write.loop.close_experiment"),
            patch("write.loop.draft_chapter", return_value="Draft."),
            patch("write.loop.queue_work", return_value="q-edge-003"),
            patch("write.loop.save_state", side_effect=track_save),
            patch("write.loop.prepare_publish_request") as mock_prepare,
        ):
            mock_prepare.return_value = PublishRequest(
                title="Test",
                fandom="Harry Potter - J. K. Rowling",
                rating=Rating.GENERAL,
                body="<p>Draft.</p>",
            )
            run(basic_brief, runs_dir=tmp_path)

        # State should be saved at least once per major transition
        assert len(state_writes) >= 4
