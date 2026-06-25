from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ParserType(str, Enum):
    pymupdf4llm = "pymupdf4llm"
    docling = "docling"


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PARSE_PENDING = "PARSE_PENDING"
    PARSE_RUNNING = "PARSE_RUNNING"
    PARSE_FAILED = "PARSE_FAILED"
    PARSE_COMPLETE = "PARSE_COMPLETE"
    NORMALIZE_PENDING = "NORMALIZE_PENDING"
    NORMALIZE_RUNNING = "NORMALIZE_RUNNING"
    NORMALIZE_FAILED = "NORMALIZE_FAILED"
    NORMALIZE_COMPLETE = "NORMALIZE_COMPLETE"
    REVIEW_PENDING = "REVIEW_PENDING"
    REVIEW_IN_PROGRESS = "REVIEW_IN_PROGRESS"
    REVIEW_APPROVED = "REVIEW_APPROVED"
    CHUNK_PENDING = "CHUNK_PENDING"
    CHUNK_RUNNING = "CHUNK_RUNNING"
    CHUNK_FAILED = "CHUNK_FAILED"
    INDEXED = "INDEXED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PARSING = "PARSING"
    NORMALIZING = "NORMALIZING"
    REVIEW_PENDING = "REVIEW_PENDING"
    REVIEWING = "REVIEWING"
    CHUNKING = "CHUNKING"
    PARTIALLY_COMPLETE = "PARTIALLY_COMPLETE"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class VariantStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class PipelineStage(str, Enum):
    UPLOAD = "UPLOAD"
    PARSE = "PARSE"
    NORMALIZE = "NORMALIZE"
    REVIEW = "REVIEW"
    CHUNK = "CHUNK"
    INDEX = "INDEX"
    CLEANUP = "CLEANUP"
    SYSTEM = "SYSTEM"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ApiResponse(BaseModel):
    data: Any = None
    error: Optional[str] = None
    detail: Optional[str] = None


class NormModelConfig(BaseModel):
    model_id: str
    endpoint: str
    display_name: str


class PerDocConfig(BaseModel):
    parsers: list[ParserType] = Field(default_factory=lambda: [ParserType.docling])
    normalization_enabled: bool = False
    normalization_models: list[NormModelConfig] = Field(default_factory=list)


class BatchConfig(BaseModel):
    default_parsers: list[ParserType] = Field(default_factory=lambda: [ParserType.docling])
    default_normalization_enabled: bool = False
    default_normalization_models: list[NormModelConfig] = Field(default_factory=list)
    per_document_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BatchConfigPatch(BaseModel):
    default_parsers: list[ParserType]
    default_normalization_enabled: bool
    default_normalization_models: list[NormModelConfig] = Field(default_factory=list)
    per_document_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SelectVariantRequest(BaseModel):
    parse_variant_id: str
    norm_variant_id: Optional[str] = None


class SaveReviewRequest(BaseModel):
    content: str


class ApproveReviewRequest(BaseModel):
    selected_parse_variant_id: str
    selected_norm_variant_id: Optional[str] = None
    notes: Optional[str] = None


class TriggerNormalizeRequest(BaseModel):
    models: list[NormModelConfig]


class RetryParseRequest(BaseModel):
    parse_variant_id: str


class RetryNormalizeRequest(BaseModel):
    norm_variant_id: str


class LlmEndpointRequest(BaseModel):
    model_id: str
    endpoint: str
    display_name: str
    enabled: bool = True

