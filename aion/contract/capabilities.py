"""Capability negotiation — control/routing/optimization states.

The client sees abstract capabilities, not module names. NEMOS is NOT
a capability (it's implicit via ``operating_mode`` and maturity).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CapabilityState(BaseModel):
    """State of a single capability in this request."""
    applied: bool = False
    skipped: bool = False
    failed: bool = False
    reason: Optional[str] = None  # set when skipped=True or failed=True


class Capabilities(BaseModel):
    """Per-module capability report for a single request.

    Cliente nao conhece os nomes dos modulos. So conhece os papeis:
    control (ESTIXE), routing (NOMOS), optimization (METIS).
    """
    control: CapabilityState = Field(default_factory=CapabilityState)
    routing: CapabilityState = Field(default_factory=CapabilityState)
    optimization: CapabilityState = Field(default_factory=CapabilityState)

    def available(self) -> list[str]:
        return [
            name for name, cap in self._cap_items()
            if cap.applied or cap.skipped  # enabled, even if skipped
        ]

    def executed(self) -> list[str]:
        return [name for name, cap in self._cap_items() if cap.applied]

    def skipped_list(self) -> list[str]:
        return [name for name, cap in self._cap_items() if cap.skipped]

    def _cap_items(self) -> list[tuple[str, CapabilityState]]:
        return [
            ("control", self.control),
            ("routing", self.routing),
            ("optimization", self.optimization),
        ]
