"""Shared schemas and helpers for RPIM services."""

from rpim_shared.embedding import fake_embed
from rpim_shared.health import HealthStatus

__all__ = ["HealthStatus", "fake_embed"]
