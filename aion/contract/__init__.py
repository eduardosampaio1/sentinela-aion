"""aion.contract — standardized decision contract.

AION padroniza a decisao, nao a execucao.
"""

from aion.contract.builder import build_contract
from aion.contract.capabilities import Capabilities, CapabilityState
from aion.contract.decision import (
    Action,
    ConfidenceLevel,
    ContractMeta,
    ContractMetrics,
    DecisionConfidence,
    DecisionContract,
    ExtensionEntry,
    FinalOutput,
    RetryPolicy,
    SideEffectLevel,
    default_retry_policy,
    side_effect_for,
    target_type_for,
)
from aion.contract.errors import ContractError, ErrorType
from aion.contract.idempotency import CachedResult, IdempotencyCache, get_idempotency_cache

__all__ = [
    "build_contract",
    "Action",
    "Capabilities",
    "CapabilityState",
    "CachedResult",
    "ConfidenceLevel",
    "ContractError",
    "ContractMeta",
    "ContractMetrics",
    "DecisionConfidence",
    "DecisionContract",
    "ErrorType",
    "ExtensionEntry",
    "FinalOutput",
    "IdempotencyCache",
    "RetryPolicy",
    "SideEffectLevel",
    "default_retry_policy",
    "get_idempotency_cache",
    "side_effect_for",
    "target_type_for",
]
