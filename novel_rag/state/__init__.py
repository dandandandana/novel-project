"""Human review and promotion of confirmed state-writeback proposals.

The generation/writeback pipeline deliberately stops at a ``needs_review``
proposal.  This package is the small, explicit second step: a human can inspect
the proposal, reject it, or approve a bounded set of state fields.  Only a
confirmed History document is used as evidence.  Runtime state is never made
canonical by itself.

The implementation keeps the command layer deliberately thin.  The public
functions return plain dataclasses/dictionaries so they can be used by either
the CLI or the TUI without duplicating persistence logic.
"""

from __future__ import annotations

from .types import StateReviewError, StatePromotionError, StateProposalReview, StatePromotionResult
from .review import (
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