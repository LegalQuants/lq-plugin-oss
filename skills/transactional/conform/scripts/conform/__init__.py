"""Dependency-free core for the conform skill."""

from .models import (
    ConformRun,
    DestinationTerm,
    DocumentRef,
    Escalation,
    EvidenceItem,
    MappingRecord,
    SourceSpan,
)

__all__ = [
    "ConformRun",
    "DestinationTerm",
    "DocumentRef",
    "Escalation",
    "EvidenceItem",
    "MappingRecord",
    "SourceSpan",
]
