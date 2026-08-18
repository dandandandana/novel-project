"""Compatibility shim: re-exports from the ``state`` package."""

from __future__ import annotations

from .state.types import StateReviewError, StatePromotionError, StateProposalReview, StatePromotionResult
from .state.review import (
    inspect_state_proposal,
    review_state_proposal,
    load_state_proposal,
    approve_state_proposal,
    promote_state_proposal,
    apply_state_proposal,
    reject_state_proposal,
)

__all__ = [
    "StateReviewError",
    "StatePromotionError",
    "StateProposalReview",
    "StatePromotionResult",
    "inspect_state_proposal",
    "review_state_proposal",
    "load_state_proposal",
    "approve_state_proposal",
    "promote_state_proposal",
    "apply_state_proposal",
    "reject_state_proposal",
]