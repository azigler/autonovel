"""Harness configuration for the write loop.

Defines WriteConfig dataclass with all tunable knobs, plus loading,
merging, and validation utilities.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Model short-name to full model ID mapping
MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# Validation ranges for each knob
_RANGES: dict[str, tuple[float, float]] = {
    "temperature": (0.5, 1.0),
    "revision_temperature": (0.5, 0.9),
    "muse_temperature": (0.7, 1.2),
    "revision_passes": (1, 4),
    "max_revision_cycles": (1, 5),
    "muse_seed_count": (1, 7),
    "slop_threshold": (1.0, 5.0),
    "quality_threshold": (5.0, 9.0),
    "target_length_tolerance": (0.05, 0.30),
}

_VALID_MODELS = {"haiku", "sonnet", "opus"}
_VALID_LENGTH_ENFORCEMENT = {"prompt", "retry", "none"}


@dataclass
class WriteConfig:
    """All tunable parameters for the write loop."""

    # Drafting
    temperature: float = 0.8
    writer_model: str = "sonnet"

    # Revision
    revision_temperature: float = 0.7
    revision_passes: int = 4
    max_revision_cycles: int = 3

    # Muse
    muse_enabled: bool = True
    muse_temperature: float = 1.0
    muse_model: str = "haiku"
    muse_seed_count: int = 4

    # Quality gates
    slop_threshold: float = 3.0
    quality_threshold: float = 7.0

    # Length
    target_length_tolerance: float = 0.15
    length_enforcement: str = "prompt"

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to a plain dict."""
        return asdict(self)

    def resolve_writer_model(self) -> str:
        """Resolve writer_model short name to full model ID."""
        return MODEL_MAP.get(self.writer_model, self.writer_model)

    def resolve_muse_model(self) -> str:
        """Resolve muse_model short name to full model ID."""
        return MODEL_MAP.get(self.muse_model, self.muse_model)


def load_config(
    config_path: str | Path = "write/config.json",
    overrides: dict[str, Any] | None = None,
) -> WriteConfig:
    """Load config from JSON file, apply overrides, and validate.

    If the config file does not exist, uses all defaults and logs a warning.
    Raises ValueError for out-of-range or invalid values after merging.

    Args:
        config_path: Path to the JSON config file.
        overrides: Optional per-brief overrides to merge on top of file values.

    Returns:
        A validated WriteConfig instance.
    """
    base_data: dict[str, Any] = {}
    path = Path(config_path)

    if path.exists():
        try:
            base_data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read config from %s: %s", path, exc)
    else:
        logger.warning("Config file %s not found, using defaults.", config_path)

    if overrides:
        base_data = merge_config(base_data, overrides)

    config = WriteConfig(
        **{
            k: v
            for k, v in base_data.items()
            if k in WriteConfig.__dataclass_fields__
        }
    )

    errors = validate_config(config)
    if errors:
        raise ValueError("Invalid config: " + "; ".join(errors))

    return config


def merge_config(
    base: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Merge per-brief overrides into a base config dict.

    Args:
        base: Base configuration values.
        overrides: Values that override the base.

    Returns:
        A new merged dict (does not mutate inputs).
    """
    merged = dict(base)
    merged.update(overrides)
    return merged


def validate_config(config: WriteConfig) -> list[str]:
    """Validate all knobs are within their allowed ranges.

    Returns a list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    for knob_name, (lo, hi) in _RANGES.items():
        value = getattr(config, knob_name, None)
        if value is not None and not (lo <= value <= hi):
            errors.append(f"{knob_name} must be {lo}-{hi}, got {value}")

    if config.writer_model not in _VALID_MODELS:
        errors.append(
            f"writer_model must be one of {sorted(_VALID_MODELS)}, "
            f"got '{config.writer_model}'"
        )

    if config.muse_model not in _VALID_MODELS:
        errors.append(
            f"muse_model must be one of {sorted(_VALID_MODELS)}, "
            f"got '{config.muse_model}'"
        )

    if config.length_enforcement not in _VALID_LENGTH_ENFORCEMENT:
        errors.append(
            f"length_enforcement must be one of "
            f"{sorted(_VALID_LENGTH_ENFORCEMENT)}, "
            f"got '{config.length_enforcement}'"
        )

    return errors
