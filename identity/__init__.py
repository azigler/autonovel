"""Identity system for the agentic fanfiction author.

Provides the creative identity, voice parameters, and self-reflection
models that make the agent's writing distinctive and allow it to evolve.
"""

from identity.schema import (
    ChapterLengthTarget,
    FeedbackDigest,
    ParagraphLength,
    ReaderComment,
    SelfReflection,
    SentenceLength,
    VoicePriors,
    load_identity,
    update_self,
    update_voice_priors,
)

__all__ = [
    "ChapterLengthTarget",
    "FeedbackDigest",
    "ParagraphLength",
    "ReaderComment",
    "SelfReflection",
    "SentenceLength",
    "VoicePriors",
    "load_identity",
    "update_self",
    "update_voice_priors",
]
