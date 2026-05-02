"""Tests for multi-fandom architecture (Spec bd-49j Section 3.8 + 4.7).

These tests pin the post-migration target state:

- ``identity/fandoms/`` directory exists with one ``{slug}.md`` per fandom
- ``identity/fandoms/bg3.md`` exists (renamed from ``identity/fandom_context.md``)
- ``identity/fandoms/CANDIDATES.md`` lists bg3 + at least two other fandoms
- ``identity/fandom_context.md`` no longer exists
- ``identity/self.md`` has ``currently_writing_in``, ``fandom_history``,
  ``fandoms_explored`` fields, and they are exposed by ``load_identity``
- ``write.context.assemble_context`` reads
  ``identity/fandoms/{currently_writing_in}.md`` by default, ``identity/fandoms/{brief.fandom}.md``
  when the brief sets it, and raises a clear error when ``brief.fandom`` is
  not a known fandom

The migration that satisfies these tests is impl bead bd-49j.8. Until that
lands, these tests are EXPECTED to fail -- that is the contract.

The filesystem-state tests look at the real repo's ``identity/`` directory
(the migration is a one-time mutation, not test-fixture state). The
code-path tests build a post-migration layout in ``tmp_path`` and
monkeypatch the relevant module paths so they remain self-contained
once impl lands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from identity.schema import VoicePriors, load_identity
from write.brief import StoryBrief

# Where the real (production) identity files live.
_REAL_IDENTITY_DIR = Path(__file__).resolve().parent.parent / "identity"
_REAL_FANDOMS_DIR = _REAL_IDENTITY_DIR / "fandoms"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_post_migration_self_md(
    path: Path, currently_writing_in: str = "bg3"
) -> None:
    """Write a minimal post-migration ``self.md`` into *path*.

    Only the fields this test cares about are populated; the rest of the
    file is a stripped-down stand-in that still has the section headers
    the schema parser looks for.
    """
    content = f"""# Self

## Voice
Close third, past tense. Concrete sensory anchors.

## Strengths
- Astarion interiority

## Growth Areas
- length control

## Reader Relationship
Tiny audience.

## Current Focus
Multi-fandom rotation in flight.

## Fandom State
- currently_writing_in: {currently_writing_in}
- fandom_history: [bg3]
- fandoms_explored:
  - bg3: {{ first_seen: 2026-03-27, works_published: 1 }}

## History
"""
    path.write_text(content, encoding="utf-8")


def _build_post_migration_identity_dir(tmp_path: Path) -> Path:
    """Build a minimal post-migration ``identity/`` directory in *tmp_path*.

    Layout:

    ::

        identity/
          self.md                         (with currently_writing_in: bg3)
          pen_name.md
          inspirations.md
          voice_priors.json
          fandoms/
            bg3.md
            CANDIDATES.md

    Returns the path to the synthetic identity directory.
    """
    ident = tmp_path / "identity"
    ident.mkdir()

    _write_post_migration_self_md(ident / "self.md", currently_writing_in="bg3")
    (ident / "pen_name.md").write_text(
        "# Pen Name\n\nMaren Solaire\n", encoding="utf-8"
    )
    (ident / "inspirations.md").write_text("# Inspirations\n", encoding="utf-8")
    (ident / "voice_priors.json").write_text(
        json.dumps(VoicePriors().to_dict(), indent=2), encoding="utf-8"
    )

    fandoms = ident / "fandoms"
    fandoms.mkdir()
    (fandoms / "bg3.md").write_text(
        "# Fandom Context\n\n## Fandom\nBaldur's Gate 3.\n",
        encoding="utf-8",
    )
    (fandoms / "CANDIDATES.md").write_text(
        "# Fandom Candidates\n\n- bg3\n- mass_effect\n- dragon_age\n",
        encoding="utf-8",
    )
    return ident


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def post_migration_identity(tmp_path, monkeypatch):
    """Build a post-migration identity layout in tmp_path and monkeypatch
    ``identity.schema`` paths so ``load_identity`` reads from it.
    """
    ident = _build_post_migration_identity_dir(tmp_path)

    import identity.schema as schema_mod

    monkeypatch.setattr(schema_mod, "IDENTITY_DIR", ident)
    monkeypatch.setattr(
        schema_mod, "_VOICE_PRIORS_PATH", ident / "voice_priors.json"
    )
    monkeypatch.setattr(schema_mod, "_SELF_PATH", ident / "self.md")
    return ident


@pytest.fixture()
def basic_brief():
    """A minimal valid one-shot StoryBrief, fandom field intentionally empty
    so individual tests can set ``brief.fandom`` per scenario.
    """
    return StoryBrief(
        characters=["Astarion"],
        premise="A quiet evening at camp after the brain.",
        target_length=3000,
    )


# ---------------------------------------------------------------------------
# Filesystem-state tests (real identity/ dir)
# ---------------------------------------------------------------------------


class TestFandomsDirectoryLayout:
    """Spec 3.8 / 4.7: ``identity/fandoms/`` directory and contents."""

    def test_fandoms_directory_exists(self):
        """``identity/fandoms/`` exists post-migration."""
        assert _REAL_FANDOMS_DIR.is_dir(), (
            f"Expected {_REAL_FANDOMS_DIR} to be a directory after the "
            "multi-fandom migration. Pre-migration this directory does not "
            "exist; this test will start passing once impl bd-49j.8 lands."
        )

    def test_bg3_md_exists_in_fandoms_dir(self):
        """``identity/fandoms/bg3.md`` exists (renamed from fandom_context.md)."""
        bg3 = _REAL_FANDOMS_DIR / "bg3.md"
        assert bg3.is_file(), (
            f"Expected {bg3} to exist (renamed from identity/fandom_context.md)."
        )

    def test_candidates_md_lists_bg3_and_at_least_two_others(self):
        """``identity/fandoms/CANDIDATES.md`` exists with bg3 and ≥2 more."""
        cand = _REAL_FANDOMS_DIR / "CANDIDATES.md"
        assert cand.is_file(), f"Expected {cand} to exist."

        text = cand.read_text(encoding="utf-8")
        assert "bg3" in text, "CANDIDATES.md must list bg3 as a known fandom."

        # Count non-empty content lines that look like candidate entries.
        # We do not pin the exact format, but require >=3 distinct fandom slug-
        # like tokens (bg3 + at least two others).
        candidate_lines = [
            line.strip().lstrip("-* ").strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        slugs = {tok.split()[0] for tok in candidate_lines if tok}
        assert len(slugs) >= 3, (
            "CANDIDATES.md should list bg3 plus at least two other fandoms; "
            f"found {sorted(slugs)}"
        )

    def test_legacy_fandom_context_md_removed(self):
        """``identity/fandom_context.md`` no longer exists post-migration."""
        legacy = _REAL_IDENTITY_DIR / "fandom_context.md"
        assert not legacy.exists(), (
            f"Legacy {legacy} should be removed after migration; its content "
            "moved to identity/fandoms/bg3.md."
        )


# ---------------------------------------------------------------------------
# self.md schema additions
# ---------------------------------------------------------------------------


class TestSelfMdFandomFields:
    """Spec 3.8: ``identity/self.md`` gains fandom-tracking fields."""

    def test_self_md_has_currently_writing_in_field(self):
        """``identity/self.md`` includes a ``currently_writing_in`` marker."""
        text = (_REAL_IDENTITY_DIR / "self.md").read_text(encoding="utf-8")
        assert "currently_writing_in" in text, (
            "self.md should declare currently_writing_in (e.g. "
            "'currently_writing_in: bg3') after migration."
        )

    def test_self_md_has_fandom_history_field(self):
        """``identity/self.md`` includes a ``fandom_history`` list."""
        text = (_REAL_IDENTITY_DIR / "self.md").read_text(encoding="utf-8")
        assert "fandom_history" in text, (
            "self.md should declare fandom_history (chronological list of "
            "explored fandoms) after migration."
        )

    def test_self_md_has_fandoms_explored_field(self):
        """``identity/self.md`` includes a ``fandoms_explored`` mapping."""
        text = (_REAL_IDENTITY_DIR / "self.md").read_text(encoding="utf-8")
        assert "fandoms_explored" in text, (
            "self.md should declare fandoms_explored (per-fandom metadata "
            "dict) after migration."
        )

    def test_load_identity_exposes_fandom_state_for_writers(
        self, post_migration_identity
    ):
        """``load_identity`` reflects post-migration ``self.md`` content.

        The schema may model these as separate keys or keep them inside the
        ``self`` markdown blob; either is acceptable. This test only asserts
        that the values are reachable (not lost) after ``load_identity``.
        """
        result = load_identity()

        # Either the schema parses these into a dedicated structure, or the
        # raw self.md text is returned and contains the field markers. Both
        # are valid contracts for impl; tests should not over-constrain.
        haystack_parts = [str(result.get("self", ""))]
        for key in (
            "currently_writing_in",
            "fandom_history",
            "fandoms_explored",
        ):
            if key in result:
                haystack_parts.append(str(result[key]))
        haystack = "\n".join(haystack_parts)

        assert "currently_writing_in" in haystack
        assert "bg3" in haystack
        assert "fandom_history" in haystack
        assert "fandoms_explored" in haystack


# ---------------------------------------------------------------------------
# assemble_context code-path behavior
# ---------------------------------------------------------------------------


class TestAssembleContextFandomSelection:
    """Spec 4.7: ``assemble_context`` selects the right fandom file.

    These tests build a post-migration ``identity/`` in ``tmp_path`` and
    drive ``assemble_context`` against it. The contract under test:

    - ``brief.fandom`` empty → use ``currently_writing_in`` from self.md
    - ``brief.fandom='bg3'`` → read ``identity/fandoms/bg3.md``
    - ``brief.fandom='unknown_fandom'`` → raise a clear error

    The implementation may take several shapes (a helper in ``identity.schema``
    that ``assemble_context`` uses, or assembly-time logic inside
    ``assemble_context`` itself). These tests assert the externally visible
    behavior, not the internal seam.
    """

    @pytest.fixture()
    def patched_context(self, post_migration_identity, monkeypatch):
        """Yield ``write.context`` with its identity-path constants pointed
        at the synthetic post-migration directory.

        ``write.context`` may import ``IDENTITY_DIR`` (or similar) from
        ``identity.schema`` post-migration; we patch both to keep the
        fixture robust to whichever route impl chooses.
        """
        import identity.schema as schema_mod
        import write.context as context_mod

        # Make sure schema-level constants point at the synthetic dir; this
        # was already done by post_migration_identity, but re-apply
        # defensively against future module-level caches.
        monkeypatch.setattr(schema_mod, "IDENTITY_DIR", post_migration_identity)

        # If write.context grew an IDENTITY_DIR / FANDOMS_DIR / similar
        # constant, repoint it at the synthetic dir as well.
        for attr in ("IDENTITY_DIR", "FANDOMS_DIR"):
            if hasattr(context_mod, attr):
                target = post_migration_identity
                if attr == "FANDOMS_DIR":
                    target = post_migration_identity / "fandoms"
                monkeypatch.setattr(context_mod, attr, target)

        return context_mod

    def test_assemble_context_uses_currently_writing_in_when_brief_fandom_empty(
        self, patched_context, post_migration_identity, basic_brief
    ):
        """No ``brief.fandom`` set → reads ``identity/fandoms/{currently_writing_in}.md``.

        Synthetic bg3.md has a UNIQUE_BG3_MARKER so we can confirm the
        right file was read.
        """
        marker = "UNIQUE_BG3_MARKER_FOR_DEFAULT_PATH_TEST"
        (post_migration_identity / "fandoms" / "bg3.md").write_text(
            f"# Fandom Context\n\n## Fandom\nBaldur's Gate 3. {marker}\n",
            encoding="utf-8",
        )

        identity = load_identity()
        basic_brief.fandom = (
            ""  # nothing set → fall through to currently_writing_in
        )

        ctx = patched_context.assemble_context(
            brief=basic_brief, identity=identity
        )

        assert marker in ctx["fandom_context"], (
            "assemble_context should fall back to identity/fandoms/"
            "{currently_writing_in}.md when brief.fandom is unset."
        )

    def test_assemble_context_reads_bg3_when_brief_fandom_is_bg3(
        self, patched_context, post_migration_identity, basic_brief
    ):
        """``brief.fandom='bg3'`` → reads ``identity/fandoms/bg3.md``."""
        marker = "UNIQUE_BG3_MARKER_FOR_BRIEF_OVERRIDE_TEST"
        (post_migration_identity / "fandoms" / "bg3.md").write_text(
            f"# Fandom Context\n\n## Fandom\nBaldur's Gate 3. {marker}\n",
            encoding="utf-8",
        )

        identity = load_identity()
        basic_brief.fandom = "bg3"

        ctx = patched_context.assemble_context(
            brief=basic_brief, identity=identity
        )

        assert marker in ctx["fandom_context"], (
            "assemble_context should read identity/fandoms/bg3.md when "
            "brief.fandom='bg3'."
        )

    def test_assemble_context_brief_fandom_overrides_currently_writing_in(
        self, patched_context, post_migration_identity, basic_brief
    ):
        """``brief.fandom`` overrides ``currently_writing_in`` from self.md.

        Set ``currently_writing_in: bg3`` in self.md but ``brief.fandom='mass_effect'``.
        Expectation: the mass_effect file is read, NOT bg3.md.
        """
        bg3_marker = "BG3_MARKER_SHOULD_NOT_APPEAR"
        me_marker = "MASS_EFFECT_MARKER_SHOULD_APPEAR"
        (post_migration_identity / "fandoms" / "bg3.md").write_text(
            f"# bg3\n\n{bg3_marker}\n", encoding="utf-8"
        )
        (post_migration_identity / "fandoms" / "mass_effect.md").write_text(
            f"# mass_effect\n\n{me_marker}\n", encoding="utf-8"
        )

        identity = load_identity()
        basic_brief.fandom = "mass_effect"

        ctx = patched_context.assemble_context(
            brief=basic_brief, identity=identity
        )

        assert me_marker in ctx["fandom_context"], (
            "brief.fandom must override currently_writing_in when set."
        )
        assert bg3_marker not in ctx["fandom_context"], (
            "currently_writing_in's fandom must NOT be loaded when brief.fandom "
            "is set to a different value."
        )

    def test_assemble_context_unknown_fandom_raises_clear_error(
        self, patched_context, post_migration_identity, basic_brief
    ):
        """``brief.fandom='unknown_fandom'`` → raises a clear error.

        Silent fall-back to a default fandom would be a footgun: a brief
        for an unwritten fandom would silently get bg3 context and the
        agent would write a BG3 piece labeled with the wrong fandom.
        """
        basic_brief.fandom = "unknown_fandom_that_does_not_exist"
        identity = load_identity()

        with pytest.raises(
            (FileNotFoundError, ValueError, KeyError)
        ) as exc_info:
            patched_context.assemble_context(
                brief=basic_brief, identity=identity
            )

        # The error message should mention the offending fandom slug so a
        # human reading the trace can fix the brief or add the fandom file.
        msg = str(exc_info.value)
        assert "unknown_fandom" in msg or "fandom" in msg.lower(), (
            "Error should reference the missing fandom slug. Got: " + msg
        )


# ---------------------------------------------------------------------------
# Identity-files-untouched-by-loop guard (Spec Section 5)
# ---------------------------------------------------------------------------


class TestIdentityFandomFilesNotMutatedByLoop:
    """Spec 3.4 / Section 5 ``identity-files-untouched-by-loop``.

    ``identity/fandoms/*.md`` mutates BY HAND only (deliberate drift).
    No code path in the write loop should write to these files.

    This test establishes that contract: it loads identity (which read-only
    consumes fandoms/bg3.md), runs assemble_context, and asserts the
    file's content + mtime are unchanged.
    """

    def test_assemble_context_does_not_mutate_fandoms_files(
        self, post_migration_identity, basic_brief, monkeypatch
    ):
        import write.context as context_mod

        for attr in ("IDENTITY_DIR", "FANDOMS_DIR"):
            if hasattr(context_mod, attr):
                target = post_migration_identity
                if attr == "FANDOMS_DIR":
                    target = post_migration_identity / "fandoms"
                monkeypatch.setattr(context_mod, attr, target)

        bg3_path = post_migration_identity / "fandoms" / "bg3.md"
        cand_path = post_migration_identity / "fandoms" / "CANDIDATES.md"

        before_bg3 = bg3_path.read_bytes()
        before_cand = cand_path.read_bytes()
        before_bg3_mtime = bg3_path.stat().st_mtime_ns
        before_cand_mtime = cand_path.stat().st_mtime_ns

        identity = load_identity()
        basic_brief.fandom = "bg3"
        context_mod.assemble_context(brief=basic_brief, identity=identity)

        assert bg3_path.read_bytes() == before_bg3
        assert cand_path.read_bytes() == before_cand
        assert bg3_path.stat().st_mtime_ns == before_bg3_mtime
        assert cand_path.stat().st_mtime_ns == before_cand_mtime


# ---------------------------------------------------------------------------
# Sanity: synthetic post-migration fixture is itself coherent
# ---------------------------------------------------------------------------


class TestPostMigrationFixtureSanity:
    """Tests for the synthetic post-migration fixture itself.

    These remain green even when the real ``identity/`` migration hasn't
    run yet, so they document the expected layout for impl.
    """

    def test_fixture_layout_matches_spec_4_7(self, post_migration_identity):
        """The fixture mirrors Spec 4.7's ``identity/`` tree."""
        ident = post_migration_identity
        assert (ident / "self.md").is_file()
        assert (ident / "pen_name.md").is_file()
        assert (ident / "voice_priors.json").is_file()
        assert (ident / "fandoms").is_dir()
        assert (ident / "fandoms" / "bg3.md").is_file()
        assert (ident / "fandoms" / "CANDIDATES.md").is_file()
        assert not (ident / "fandom_context.md").exists()

    def test_fixture_self_md_has_fandom_state_section(
        self, post_migration_identity
    ):
        """Synthetic self.md carries the new fandom-state markers impl must
        emit (``currently_writing_in``, ``fandom_history``, ``fandoms_explored``).
        """
        text = (post_migration_identity / "self.md").read_text(encoding="utf-8")
        assert "currently_writing_in: bg3" in text
        assert "fandom_history" in text
        assert "fandoms_explored" in text
