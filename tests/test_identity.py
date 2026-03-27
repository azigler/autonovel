"""Tests for the identity system (Spec: identity.md, Section 5).

Covers all spec test cases plus additional edge-case, error, and
integration tests for voice priors, self-reflection, and identity loading.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from identity.schema import (
    ChapterLengthTarget,
    FeedbackDigest,
    ParagraphLength,
    ReaderComment,
    SelfReflection,
    SentenceLength,
    VoicePriors,
    _load_voice_priors,
    _save_voice_priors,
    _utcnow_iso,
    load_identity,
    update_self,
    update_voice_priors,
)

# ---------------------------------------------------------------------------
# Paths to real identity template files (for copying into tmp_path)
# ---------------------------------------------------------------------------
_REAL_IDENTITY_DIR = Path(__file__).resolve().parent.parent / "identity"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def identity_dir(tmp_path, monkeypatch):
    """Copy identity templates into tmp_path and monkeypatch schema paths.

    This ensures all file operations happen in tmp_path, leaving the real
    identity/ directory untouched.
    """
    # Copy all identity files into tmp_path
    for src in _REAL_IDENTITY_DIR.iterdir():
        if src.is_file():
            shutil.copy2(src, tmp_path / src.name)

    # Monkeypatch the module-level path constants
    import identity.schema as schema_mod

    monkeypatch.setattr(schema_mod, "IDENTITY_DIR", tmp_path)
    monkeypatch.setattr(
        schema_mod, "_VOICE_PRIORS_PATH", tmp_path / "voice_priors.json"
    )
    monkeypatch.setattr(schema_mod, "_SELF_PATH", tmp_path / "self.md")

    return tmp_path


@pytest.fixture()
def default_priors():
    """Return a VoicePriors instance with all defaults."""
    return VoicePriors()


# ---------------------------------------------------------------------------
# Spec Test Cases (Section 5)
# ---------------------------------------------------------------------------


class TestLoadIdentity:
    """Tests for load_identity()."""

    def test_load_identity_returns_all_components(self, identity_dir):
        """TEST: load_identity returns all components (Spec identity, Test Case 01)
        Verifies the basic loading contract -- all identity components are read
        and returned in the expected format.
        """
        result = load_identity()

        assert "self" in result
        assert "pen_name" in result
        assert "inspirations" in result
        assert "fandom_context" in result
        assert "voice_priors" in result

        # Markdown keys are non-empty strings (template content)
        assert isinstance(result["self"], str)
        assert len(result["self"]) > 0
        assert isinstance(result["pen_name"], str)
        assert len(result["pen_name"]) > 0
        assert isinstance(result["inspirations"], str)
        assert len(result["inspirations"]) > 0
        assert isinstance(result["fandom_context"], str)
        assert len(result["fandom_context"]) > 0

        # voice_priors is a VoicePriors instance with version=1
        assert isinstance(result["voice_priors"], VoicePriors)
        assert result["voice_priors"].version == 1

    def test_load_identity_handles_missing_files(self, identity_dir):
        """TEST: load_identity handles missing files gracefully (Spec identity, Test Case 02)
        The agent may not have populated all identity files yet. Loading must
        not crash when a file is missing.
        """
        # Delete fandom_context.md
        (identity_dir / "fandom_context.md").unlink()

        result = load_identity()

        assert result["fandom_context"] == ""
        # Other keys still populated
        assert len(result["self"]) > 0
        assert len(result["pen_name"]) > 0
        assert len(result["inspirations"]) > 0
        assert isinstance(result["voice_priors"], VoicePriors)


class TestUpdateSelf:
    """Tests for update_self()."""

    def test_update_self_appends_history_entry(self, identity_dir):
        """TEST: update_self appends history entry (Spec identity, Test Case 03)
        Verifies the core self-reflection append mechanism and that existing
        content is not clobbered.
        """
        original_content = (identity_dir / "self.md").read_text(
            encoding="utf-8"
        )

        reflection = SelfReflection(
            publication_title="First Light",
            fandom="Our Flag Means Death",
            what_worked="Dialogue subtext",
            what_didnt_work="Pacing in act 2",
            lesson="Slow the middle; readers want to sit with the tension",
        )
        entry = update_self(reflection)

        updated_content = (identity_dir / "self.md").read_text(encoding="utf-8")

        # Original content preserved
        assert original_content.strip() in updated_content

        # New entry present
        assert "First Light" in updated_content
        assert "Our Flag Means Death" in updated_content
        assert "Dialogue subtext" in updated_content
        assert "Pacing in act 2" in updated_content
        assert "Slow the middle" in updated_content

        # Entry text returned matches what was written
        assert "First Light" in entry
        assert "Dialogue subtext" in entry

    def test_update_self_preserves_prior_entries(self, identity_dir):
        """TEST: update_self preserves prior entries (Spec identity, Test Case 03 extended)
        Multiple calls to update_self should accumulate entries without losing
        earlier ones.
        """
        r1 = SelfReflection(
            publication_title="Work One",
            fandom="Fandom A",
            what_worked="Pacing",
            what_didnt_work="Dialogue",
            lesson="Lesson one",
        )
        r2 = SelfReflection(
            publication_title="Work Two",
            fandom="Fandom B",
            what_worked="Character voice",
            what_didnt_work="Plot structure",
            lesson="Lesson two",
        )

        update_self(r1)
        update_self(r2)

        content = (identity_dir / "self.md").read_text(encoding="utf-8")
        assert "Work One" in content
        assert "Work Two" in content
        assert "Lesson one" in content
        assert "Lesson two" in content


class TestUpdateVoicePriors:
    """Tests for update_voice_priors()."""

    def test_update_voice_priors_applies_adjustments(self, identity_dir):
        """TEST: update_voice_priors applies adjustments correctly (Spec identity, Test Case 04)
        Verifies partial updates work -- only the specified key changes,
        version bumps, timestamp updates.
        """
        result = update_voice_priors({"dialogue_ratio": 0.40})

        assert result.dialogue_ratio == pytest.approx(0.40)
        assert result.version == 2
        assert result.updated_at == _utcnow_iso()

        # Other fields unchanged from defaults
        assert result.tense == "past"
        assert result.pov == "third_limited"
        assert result.sentence_length.mean == 14

    def test_update_voice_priors_nested_dict(self, identity_dir):
        """TEST: update_voice_priors with nested dict (Spec identity, Test Case 04 extended)
        Verifies that nested dict adjustments (e.g. sentence_length sub-fields)
        are merged correctly.
        """
        result = update_voice_priors({"sentence_length": {"mean": 16}})

        assert result.sentence_length.mean == 16
        # Other sentence_length fields preserved
        assert result.sentence_length.std == 8
        assert result.sentence_length.min == 3
        assert result.sentence_length.max == 45

    def test_update_voice_priors_unknown_key_ignored(self, identity_dir):
        """TEST: update_voice_priors ignores unknown keys
        Keys not in VoicePriors should be silently ignored.
        """
        result = update_voice_priors({"nonexistent_field": "value"})

        # Should succeed; version still bumps
        assert result.version == 2
        # Defaults preserved
        assert result.dialogue_ratio == pytest.approx(0.35)


class TestRoundTripSerialization:
    """Tests for VoicePriors serialization round-trip."""

    def test_round_trip_serialization(self):
        """TEST: round-trip serialization (Spec identity, Test Case 10)
        Identity state must survive persistence cycles without corruption.
        """
        priors = VoicePriors()
        d = priors.to_dict()
        restored = VoicePriors.from_dict(d)

        assert asdict(priors) == asdict(restored)

    def test_round_trip_with_custom_values(self):
        """TEST: round-trip serialization with custom values
        Verifies round-trip works for non-default configurations.
        """
        priors = VoicePriors(
            dialogue_ratio=0.50,
            pov="first",
            tense="present",
            strengths=["pacing", "dialogue"],
            weaknesses=["worldbuilding"],
            version=5,
            updated_at="2026-01-15",
        )
        d = priors.to_dict()
        restored = VoicePriors.from_dict(d)

        assert asdict(priors) == asdict(restored)

    def test_round_trip_via_json(self, identity_dir):
        """TEST: round-trip through JSON file (Spec identity, Test Case 10 extended)
        Verifies that writing to JSON and reading back preserves all fields.
        """
        priors = VoicePriors(
            dialogue_ratio=0.42,
            strengths=["tension", "subtext"],
            version=3,
            updated_at="2026-03-01",
        )
        _save_voice_priors(priors)
        loaded = _load_voice_priors()

        assert asdict(priors) == asdict(loaded)


class TestEmptyFeedback:
    """Tests for empty/no-op feedback scenarios."""

    def test_empty_feedback_no_changes(self, identity_dir):
        """TEST: empty feedback produces no changes (Spec identity, Test Case 12)
        The learning engine may produce no adjustments after a cycle where
        feedback is ambiguous. The system must handle this gracefully.
        """
        result = update_voice_priors({}, bump_version=False)

        # Version stays the same (bump_version=False)
        assert result.version == 1
        # updated_at is set to current date (timestamp always updates)
        assert result.updated_at == _utcnow_iso()
        # All other fields at defaults
        assert result.dialogue_ratio == pytest.approx(0.35)
        assert result.tense == "past"


class TestFirstTimeInit:
    """Tests for first-time initialization from missing files."""

    def test_first_time_init_missing_voice_priors(self, identity_dir):
        """TEST: first-time initialization from blank templates (Spec identity, Test Case 13)
        On first run, before any identity has been established, the system
        must bootstrap from hardcoded defaults rather than crashing.
        """
        # Delete voice_priors.json
        (identity_dir / "voice_priors.json").unlink()

        priors = _load_voice_priors()

        assert priors.version == 1
        assert priors.updated_at is None
        assert priors.dialogue_ratio == pytest.approx(0.35)
        assert priors.sentence_length.mean == 14
        assert priors.pov == "third_limited"
        assert priors.tense == "past"

    def test_first_time_init_all_files_missing(self, identity_dir):
        """TEST: first-time init with no files at all
        Even with all identity files deleted, load_identity should not crash.
        """
        for f in identity_dir.iterdir():
            if f.is_file():
                f.unlink()

        result = load_identity()

        assert result["self"] == ""
        assert result["pen_name"] == ""
        assert result["inspirations"] == ""
        assert result["fandom_context"] == ""
        assert isinstance(result["voice_priors"], VoicePriors)
        assert result["voice_priors"].version == 1


class TestVersionIncrement:
    """Tests for version tracking on update."""

    def test_version_increment_on_update(self, identity_dir):
        """TEST: version increment on update (Spec identity, Test Case 14)
        Version tracking ensures we can detect how many update cycles the
        identity has been through.
        """
        update_voice_priors({"tense": "present"})
        update_voice_priors({"tense": "past"})
        result = update_voice_priors({"tense": "present"})

        assert result.version == 4

    def test_version_no_bump_when_disabled(self, identity_dir):
        """TEST: version stays unchanged when bump_version=False
        Allows updates without version increment for internal adjustments.
        """
        result = update_voice_priors({"tense": "present"}, bump_version=False)

        assert result.version == 1


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge-case coverage beyond the spec."""

    def test_edge_voice_priors_default_values(self):
        """EDGE: default VoicePriors field values
        Verifies all defaults match what voice_priors.json ships with.
        """
        priors = VoicePriors()

        assert priors.sentence_length.mean == 14
        assert priors.sentence_length.std == 8
        assert priors.sentence_length.min == 3
        assert priors.sentence_length.max == 45
        assert priors.paragraph_length.mean == 4
        assert priors.paragraph_length.std == 2
        assert priors.dialogue_ratio == pytest.approx(0.35)
        assert priors.interiority_depth == "medium"
        assert priors.metaphor_density == "sparse"
        assert priors.pov == "third_limited"
        assert priors.tense == "past"
        assert priors.vocabulary_register == "literary_accessible"
        assert priors.humor_frequency == "occasional"
        assert priors.sensory_detail_density == "high"
        assert priors.emotional_directness == "indirect"
        assert priors.pacing_preference == "slow_burn"
        assert priors.chapter_length_target.min == 3000
        assert priors.chapter_length_target.max == 6000
        assert priors.strengths == []
        assert priors.weaknesses == []
        assert priors.updated_at is None
        assert priors.version == 1

    def test_edge_self_md_template_has_all_sections(self, identity_dir):
        """EDGE: self.md template contains all required sections
        The template must have all six sections for the update mechanism to work.
        """
        content = (identity_dir / "self.md").read_text(encoding="utf-8")

        assert "## Voice" in content
        assert "## Strengths" in content
        assert "## Growth Areas" in content
        assert "## Reader Relationship" in content
        assert "## Current Focus" in content
        assert "## History" in content

    def test_edge_from_dict_with_flat_sub_models(self):
        """EDGE: VoicePriors.from_dict handles already-constructed sub-models
        If sub-model fields are passed as dataclass instances rather than dicts,
        from_dict should still work (no double-wrapping).
        """
        data = VoicePriors().to_dict()
        # Replace nested dicts with dataclass instances
        data["sentence_length"] = SentenceLength(mean=20, std=5, min=4, max=50)
        priors = VoicePriors.from_dict(data)

        assert priors.sentence_length.mean == 20

    def test_edge_update_self_on_empty_file(self, identity_dir):
        """EDGE: update_self when self.md is empty
        Should not crash; should create the entry in an otherwise empty file.
        """
        (identity_dir / "self.md").write_text("", encoding="utf-8")

        reflection = SelfReflection(
            publication_title="Test",
            fandom="Test Fandom",
            what_worked="Everything",
            what_didnt_work="Nothing",
            lesson="Keep going",
        )
        entry = update_self(reflection)

        content = (identity_dir / "self.md").read_text(encoding="utf-8")
        assert "Test" in content
        assert "Keep going" in content
        assert len(entry) > 0

    def test_edge_load_identity_returns_voice_priors_from_json(
        self, identity_dir
    ):
        """EDGE: load_identity reads voice_priors.json, not just defaults
        If voice_priors.json has been modified, load_identity should reflect
        those changes.
        """
        # Modify the JSON file directly
        vp_path = identity_dir / "voice_priors.json"
        data = json.loads(vp_path.read_text(encoding="utf-8"))
        data["dialogue_ratio"] = 0.50
        data["version"] = 3
        vp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = load_identity()
        assert result["voice_priors"].dialogue_ratio == pytest.approx(0.50)
        assert result["voice_priors"].version == 3

    def test_edge_update_voice_priors_persists_to_disk(self, identity_dir):
        """EDGE: update_voice_priors writes changes to disk
        After calling update_voice_priors, re-reading the JSON file should
        reflect the new values.
        """
        update_voice_priors({"dialogue_ratio": 0.40})

        vp_path = identity_dir / "voice_priors.json"
        data = json.loads(vp_path.read_text(encoding="utf-8"))
        assert data["dialogue_ratio"] == pytest.approx(0.40)
        assert data["version"] == 2

    def test_edge_strengths_and_weaknesses_update(self, identity_dir):
        """EDGE: strengths and weaknesses lists can be set via update
        List fields should be replaceable through update_voice_priors.
        """
        result = update_voice_priors(
            {
                "strengths": ["pacing", "dialogue"],
                "weaknesses": ["worldbuilding"],
            }
        )

        assert result.strengths == ["pacing", "dialogue"]
        assert result.weaknesses == ["worldbuilding"]


# ---------------------------------------------------------------------------
# Error Path Tests
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Error path and boundary tests."""

    def test_error_from_dict_extra_keys_raises(self):
        """ERROR: VoicePriors.from_dict with unexpected keys raises TypeError
        Passing keys not in VoicePriors should raise an error during construction.
        """
        data = VoicePriors().to_dict()
        data["totally_fake_key"] = "bogus"

        with pytest.raises(TypeError):
            VoicePriors.from_dict(data)

    def test_error_self_reflection_requires_title_and_fandom(self):
        """ERROR: SelfReflection requires publication_title and fandom
        These are required positional args with no defaults.
        """
        with pytest.raises(TypeError):
            SelfReflection()  # type: ignore[call-arg]

    def test_error_reader_comment_requires_author_and_text(self):
        """ERROR: ReaderComment requires author and text
        These are required positional args with no defaults.
        """
        with pytest.raises(TypeError):
            ReaderComment()  # type: ignore[call-arg]

    def test_error_feedback_digest_requires_title_and_fandom(self):
        """ERROR: FeedbackDigest requires publication_title and fandom
        These are required positional args with no defaults.
        """
        with pytest.raises(TypeError):
            FeedbackDigest()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests spanning multiple operations."""

    def test_integration_full_update_cycle(self, identity_dir):
        """INTEGRATION: full identity update cycle
        Simulates a complete feedback cycle: load identity, update voice priors,
        record self-reflection, reload identity and verify consistency.
        """
        # 1. Load initial identity
        initial = load_identity()
        assert initial["voice_priors"].version == 1

        # 2. Update voice priors
        updated_priors = update_voice_priors({"dialogue_ratio": 0.40})
        assert updated_priors.version == 2

        # 3. Record self-reflection
        reflection = SelfReflection(
            publication_title="Tidal",
            fandom="Our Flag Means Death",
            what_worked="Emotional pacing",
            what_didnt_work="Too many POV shifts",
            lesson="Stick to one POV per chapter",
        )
        update_self(reflection)

        # 4. Reload and verify
        reloaded = load_identity()
        assert reloaded["voice_priors"].version == 2
        assert reloaded["voice_priors"].dialogue_ratio == pytest.approx(0.40)
        assert "Tidal" in reloaded["self"]
        assert "Stick to one POV" in reloaded["self"]

    def test_integration_multiple_update_cycles(self, identity_dir):
        """INTEGRATION: multiple sequential update cycles
        Verifies that state accumulates correctly across multiple cycles.
        """
        for i in range(3):
            ratio = 0.35 + (i * 0.01)
            update_voice_priors({"dialogue_ratio": ratio})
            update_self(
                SelfReflection(
                    publication_title=f"Work {i + 1}",
                    fandom="Test Fandom",
                    what_worked=f"Skill {i + 1}",
                    what_didnt_work=f"Gap {i + 1}",
                    lesson=f"Lesson {i + 1}",
                )
            )

        final = load_identity()
        assert (
            final["voice_priors"].version == 4
        )  # started at 1, bumped 3 times
        assert final["voice_priors"].dialogue_ratio == pytest.approx(0.37)

        # All three reflections present
        for i in range(3):
            assert f"Work {i + 1}" in final["self"]
            assert f"Lesson {i + 1}" in final["self"]

    def test_integration_save_load_round_trip(self, identity_dir):
        """INTEGRATION: save-load round-trip via persistence functions
        Update priors, save to disk, load back, and verify equality.
        """
        updated = update_voice_priors(
            {
                "dialogue_ratio": 0.40,
                "tense": "present",
                "strengths": ["subtext"],
            }
        )

        loaded = _load_voice_priors()
        assert asdict(updated) == asdict(loaded)


# ---------------------------------------------------------------------------
# Data model unit tests
# ---------------------------------------------------------------------------


class TestDataModels:
    """Unit tests for dataclass models."""

    def test_sentence_length_defaults(self):
        """TEST: SentenceLength default values"""
        sl = SentenceLength()
        assert sl.mean == 14
        assert sl.std == 8
        assert sl.min == 3
        assert sl.max == 45

    def test_paragraph_length_defaults(self):
        """TEST: ParagraphLength default values"""
        pl = ParagraphLength()
        assert pl.mean == 4
        assert pl.std == 2

    def test_chapter_length_target_defaults(self):
        """TEST: ChapterLengthTarget default values"""
        clt = ChapterLengthTarget()
        assert clt.min == 3000
        assert clt.max == 6000

    def test_reader_comment_defaults(self):
        """TEST: ReaderComment optional fields have sensible defaults"""
        rc = ReaderComment(author="user1", text="Great chapter!")
        assert rc.chapter is None
        assert rc.sentiment == "neutral"
        assert rc.themes == []

    def test_feedback_digest_defaults(self):
        """TEST: FeedbackDigest optional fields have sensible defaults"""
        fd = FeedbackDigest(publication_title="Test", fandom="Test Fandom")
        assert fd.hits == 0
        assert fd.kudos == 0
        assert fd.bookmarks == 0
        assert fd.comment_count == 0
        assert fd.subscriber_delta == 0
        assert fd.comments == []
        assert fd.top_praise == []
        assert fd.top_criticism == []
        assert fd.recurring_themes == []
        assert fd.engagement_trend == "stable"

    def test_utcnow_iso_format(self):
        """TEST: _utcnow_iso returns YYYY-MM-DD format"""
        result = _utcnow_iso()
        # Should match today's date
        expected = datetime.now(UTC).strftime("%Y-%m-%d")
        assert result == expected
        # Verify format: exactly 10 chars, two dashes
        assert len(result) == 10
        assert result.count("-") == 2
