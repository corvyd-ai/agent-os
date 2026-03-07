"""agent-os error classification — pluggable error categorization for SDK errors.

Extracts error classification logic from runner.py into a standalone module
with an abstract interface and default implementation for Claude Agent SDK errors.
"""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod


class ErrorClassifier(ABC):
    """Abstract interface for classifying runtime errors."""

    @abstractmethod
    def classify(self, error_text: str) -> tuple[str, bool]:
        """Classify error text as a category and retryability.

        Returns (category: str, retryable: bool).
        """

    @abstractmethod
    def is_benign_cleanup(self, exc: Exception) -> bool:
        """Return True if the exception is a benign transport cleanup artifact."""

    @abstractmethod
    def format_detail(self, exc: Exception) -> str:
        """Format an exception into a human-readable string with structured detail."""


class ClaudeErrorClassifier(ErrorClassifier):
    """Default error classifier for Claude Agent SDK errors.

    Categorizes errors as transient (retryable) or permanent based on
    pattern matching against known error signatures.
    """

    TRANSIENT_PATTERNS = [
        "rate_limit",
        "overloaded",
        "529",
        "500",
        "server_error",
        "connection reset",
        "connection refused",
        "timeout",
    ]

    PERMANENT_PATTERNS = [
        "authentication_failed",
        "billing",
        "credit",
        "unauthorized",
        "401",
        "403",
        "invalid_request",
        "cli not found",
    ]

    def classify(self, error_text: str) -> tuple[str, bool]:
        """Classify an error as transient (retryable) or permanent.

        Returns (category, retryable).
        """
        lower = error_text.lower()
        for p in self.PERMANENT_PATTERNS:
            if p in lower:
                return "permanent", False
        for p in self.TRANSIENT_PATTERNS:
            if p in lower:
                return "transient", True
        return "unknown", False

    def is_benign_cleanup(self, exc: Exception) -> bool:
        """Detect the SDK race condition where transport closes during cleanup.

        Returns True if the exception is an ExceptionGroup where ALL sub-exceptions
        are CLIConnectionError about "not ready for writing". This happens when
        the SDK's TaskGroup cancels before pending MCP control responses finish —
        the query already completed successfully, the cleanup is just noisy.
        """
        if not isinstance(exc, ExceptionGroup):
            return False

        # Import SDK error types — may not be available
        try:
            from claude_agent_sdk._errors import CLIConnectionError
        except ImportError:
            CLIConnectionError = None

        for sub in exc.exceptions:
            if CLIConnectionError is not None and isinstance(sub, CLIConnectionError):
                continue
            if "CLIConnectionError" in type(sub).__name__ and "not ready for writing" in str(sub):
                continue
            return False

        return len(exc.exceptions) > 0

    def format_detail(self, exc: Exception) -> str:
        """Extract useful detail from exceptions, especially ExceptionGroups.

        The SDK wraps transport errors in ExceptionGroup — str() on those just
        returns "unhandled errors in a TaskGroup (N sub-exception)" which is
        useless for debugging. This unpacks nested exceptions into readable text.
        """
        # Import SDK error types for structured extraction
        try:
            from claude_agent_sdk._errors import (
                CLIJSONDecodeError,
                ProcessError,
            )
        except ImportError:
            ProcessError = None
            CLIJSONDecodeError = None

        parts = [f"{type(exc).__name__}: {exc}"]

        if ProcessError and isinstance(exc, ProcessError):
            if hasattr(exc, "exit_code"):
                parts.append(f"  exit_code: {exc.exit_code}")
            if hasattr(exc, "stderr") and exc.stderr and exc.stderr != "Check stderr output for details":
                parts.append(f"  stderr: {exc.stderr}")

        elif CLIJSONDecodeError and isinstance(exc, CLIJSONDecodeError):
            if hasattr(exc, "line"):
                parts.append(f"  line: {exc.line}")

        elif isinstance(exc, ExceptionGroup):
            for i, sub in enumerate(exc.exceptions, 1):
                parts.append(f"  [{i}] {self.format_detail(sub)}")

        if exc.__cause__:
            parts.append(f"  caused by: {self.format_detail(exc.__cause__)}")

        return "\n".join(parts)

    def build_error_refs(self, exc: Exception, stderr_text: str = "", **extras) -> dict:
        """Build structured error data for JSONL log refs.

        Extracts error class, detail, category, retryability, exit code,
        stderr, and traceback. Merges with caller-provided extras.
        """
        error_text = self.format_detail(exc)
        combined = f"{error_text} {stderr_text}"
        category, retryable = self.classify(combined)

        refs = {
            "error_class": type(exc).__name__,
            "error_detail": str(exc)[:500],
            "error_category": category,
            "retryable": retryable,
            "traceback": traceback.format_exc()[-1000:],
        }

        if hasattr(exc, "exit_code"):
            refs["exit_code"] = exc.exit_code
        if hasattr(exc, "stderr") and exc.stderr:
            refs["stderr"] = str(exc.stderr)[:500]
        elif stderr_text:
            refs["stderr"] = stderr_text[:500]

        if isinstance(exc, ExceptionGroup):
            refs["sub_exceptions"] = [f"{type(sub).__name__}: {sub}" for sub in exc.exceptions]

        refs.update(extras)
        return refs
