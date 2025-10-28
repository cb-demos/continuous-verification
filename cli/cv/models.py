"""Data models for continuous verification."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AuthMethod(str, Enum):
    """Authentication methods supported."""

    BEARER = "bearer"
    BASIC = "basic"
    API_KEY = "api-key"
    HEADER = "header"
    NONE = "none"


class AuthConfig(BaseModel):
    """Authentication configuration."""

    method: AuthMethod = AuthMethod.NONE
    token: str | None = None
    username: str | None = None
    password: str | None = None
    header_name: str | None = None

    @model_validator(mode="after")
    def validate_auth_method(self):
        """Validate that required fields are present for each auth method."""
        if self.method == AuthMethod.BASIC:
            if not self.username or not self.password:
                raise ValueError("Basic auth requires both username and password")
        elif self.method in (AuthMethod.BEARER, AuthMethod.API_KEY, AuthMethod.HEADER):
            if not self.token:
                raise ValueError(f"{self.method.value} auth requires token")
            if (
                self.method in (AuthMethod.API_KEY, AuthMethod.HEADER)
                and not self.header_name
            ):
                raise ValueError(f"{self.method.value} auth requires header_name")
        return self

    def model_dump(self, **kwargs):
        """Override to redact sensitive fields in output."""
        data = super().model_dump(**kwargs)
        if data.get("token"):
            data["token"] = "***REDACTED***"
        if data.get("password"):
            data["password"] = "***REDACTED***"
        return data


class QueryConfig(BaseModel):
    """HTTP query configuration."""

    endpoint: str
    method: Literal["GET", "POST", "PUT", "PATCH"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | dict | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    timeout: int = 30


class ExtractConfig(BaseModel):
    """Value extraction configuration."""

    path: str  # JSONPath expression
    type: Literal["number", "string", "boolean", "json"] = "number"
    default: Any | None = None


class ThresholdEvaluator(BaseModel):
    """Threshold-based evaluation."""

    type: Literal["threshold"] = "threshold"
    operator: Literal["<", ">", "<=", ">=", "==", "!="]
    value: int | float | str


# For now, we'll only support threshold evaluation
# Can add Range, Change, Custom later
EvaluatorConfig = ThresholdEvaluator


class Check(BaseModel):
    """A single verification check."""

    name: str
    description: str | None = None
    query: QueryConfig
    extract: ExtractConfig
    evaluate: EvaluatorConfig


class EvaluationMode(str, Enum):
    """Overall evaluation modes."""

    ALL_PASS = "all-pass"
    ANY_PASS = "any-pass"
    THRESHOLD = "threshold"


class EvaluationConfig(BaseModel):
    """Overall evaluation configuration."""

    mode: EvaluationMode = EvaluationMode.ALL_PASS
    min_passed: int | None = None  # For threshold mode

    @model_validator(mode="after")
    def validate_threshold_mode(self):
        """Validate threshold mode configuration."""
        if self.mode == EvaluationMode.THRESHOLD:
            if self.min_passed is None:
                raise ValueError("min_passed is required when mode is THRESHOLD")
            if self.min_passed < 1:
                raise ValueError("min_passed must be at least 1")
        return self


class OutputConfig(BaseModel):
    """Output configuration."""

    include_details: bool = True
    format: Literal["json", "markdown"] = "json"


class VerificationConfig(BaseModel):
    """Complete verification configuration."""

    api_endpoint: str
    auth: AuthConfig = Field(default_factory=AuthConfig)
    checks: list[Check] = Field(..., min_length=1)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    poll_interval: int = 60
    timeout: int = 3600
    verify_ssl: bool = Field(
        default=True, description="Verify SSL certificates (disable for dev/test only)"
    )
    ca_bundle: str | None = Field(
        default=None, description="Path to custom CA bundle file"
    )

    @model_validator(mode="after")
    def validate_threshold_against_checks(self):
        """Validate that threshold mode min_passed doesn't exceed number of checks."""
        if (
            self.evaluation.mode == EvaluationMode.THRESHOLD
            and self.evaluation.min_passed
        ):
            if self.evaluation.min_passed > len(self.checks):
                raise ValueError(
                    f"min_passed ({self.evaluation.min_passed}) cannot exceed "
                    f"number of checks ({len(self.checks)})"
                )
        return self


class CheckResult(BaseModel):
    """Result of a single check."""

    check_name: str
    success: bool
    value: Any
    expected: Any
    message: str
    timestamp: datetime
    poll_number: int


class VerificationStatus(str, Enum):
    """Final verification status."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class VerificationResult(BaseModel):
    """Final verification result."""

    status: VerificationStatus
    checks_passed: int
    checks_failed: int
    total_polls: int
    duration: int  # seconds
    detailed_results: list[CheckResult]
    failure_reason: str | None = None
