"""Core verification engine."""

import logging
import time
from datetime import datetime
from typing import Any

from jsonpath_ng import parse as jsonpath_parse

from .http_client import HTTPClient
from .models import (
    Check,
    CheckResult,
    EvaluationMode,
    ThresholdEvaluator,
    VerificationConfig,
    VerificationResult,
    VerificationStatus,
)

logger = logging.getLogger(__name__)


class Verifier:
    """Core verification engine with polling logic."""

    def __init__(self, config: VerificationConfig):
        """Initialize verifier.

        Args:
            config: Verification configuration
        """
        self.config = config
        self.http_client = HTTPClient(
            config.api_endpoint,
            config.auth,
            verify_ssl=config.verify_ssl,
            ca_bundle=config.ca_bundle,
        )

    def run(self) -> VerificationResult:
        """Run the verification process with polling.

        Returns:
            Final verification result
        """
        start_time = time.time()
        end_time = start_time + self.config.timeout
        poll_count = 0
        all_results: list[CheckResult] = []

        logger.info("Starting verification with %d check(s)", len(self.config.checks))
        logger.info(
            "Polling every %ds, timeout after %ds",
            self.config.poll_interval,
            self.config.timeout,
        )

        while time.time() < end_time:
            poll_count += 1
            elapsed = int(time.time() - start_time)
            logger.info("Poll #%d (elapsed: %ds)", poll_count, elapsed)

            # Execute all checks for this poll
            poll_results = self._execute_poll(poll_count)
            all_results.extend(poll_results)

            # Evaluate overall status
            status, reason = self._evaluate_overall(poll_results)

            if status == VerificationStatus.PASSED:
                logger.info("Verification PASSED after %d poll(s)", poll_count)
                duration = int(time.time() - start_time)
                return self._build_result(status, all_results, poll_count, duration)

            # If failed, continue polling until timeout
            logger.debug("Status: %s, continuing to poll...", reason)

            # Continue polling
            if time.time() + self.config.poll_interval < end_time:
                logger.debug(
                    "Waiting %ds before next poll...", self.config.poll_interval
                )
                time.sleep(self.config.poll_interval)
            else:
                logger.debug("Not enough time for another poll before timeout")
                break

        # Timeout reached - determine final status from last poll
        duration = int(time.time() - start_time)
        if all_results:
            latest_poll_results = self._get_latest_results(all_results, poll_count)
            final_status, reason = self._evaluate_overall(latest_poll_results)

            if final_status == VerificationStatus.PASSED:
                logger.info("Verification PASSED on final poll")
                return self._build_result(
                    final_status, all_results, poll_count, duration
                )
            else:
                logger.warning(
                    "Verification FAILED: Checks did not pass within %ds", duration
                )
                return self._build_result(
                    VerificationStatus.FAILED,
                    all_results,
                    poll_count,
                    duration,
                    f"Checks did not pass within timeout ({duration}s)",
                )
        else:
            logger.error("Verification TIMEOUT: No polls completed")
            return self._build_result(
                VerificationStatus.TIMEOUT,
                all_results,
                poll_count,
                duration,
                "Timeout before any polls completed",
            )

    def _execute_poll(self, poll_number: int) -> list[CheckResult]:
        """Execute all checks for a single poll iteration.

        Args:
            poll_number: Current poll number

        Returns:
            List of check results
        """
        results = []
        for check in self.config.checks:
            try:
                result = self._execute_check(check, poll_number)
                results.append(result)
                status_icon = "✓" if result.success else "✗"
                logger.info("  %s %s: %s", status_icon, check.name, result.message)
            except Exception as e:
                # All errors become failed checks
                result = CheckResult(
                    check_name=check.name,
                    success=False,
                    value=None,
                    expected=None,
                    message=f"Error: {str(e)}",
                    timestamp=datetime.now(),
                    poll_number=poll_number,
                )
                results.append(result)
                logger.error("  ✗ %s: Error - %s", check.name, str(e))

        return results

    def _execute_check(self, check: Check, poll_number: int) -> CheckResult:
        """Execute a single check.

        Args:
            check: Check configuration
            poll_number: Current poll number

        Returns:
            Check result

        Raises:
            ValueError: If extraction or type conversion fails
        """
        # Make API call
        response = self.http_client.request(check.query)

        # Extract value
        value = self._extract_value(response, check.extract.path)

        # Convert type
        value = self._convert_type(value, check.extract.type, check.extract.default)

        # Evaluate
        success, message = self._evaluate_check(check.evaluate, value)

        return CheckResult(
            check_name=check.name,
            success=success,
            value=value,
            expected=f"{check.evaluate.operator} {check.evaluate.value}",
            message=message,
            timestamp=datetime.now(),
            poll_number=poll_number,
        )

    def _extract_value(self, data: dict, path: str) -> Any:
        """Extract value from JSON using JSONPath.

        Args:
            data: JSON data
            path: JSONPath expression

        Returns:
            Extracted value

        Raises:
            ValueError: If JSONPath finds no matches
        """
        try:
            jsonpath_expr = jsonpath_parse(path)
            matches = jsonpath_expr.find(data)

            if not matches:
                raise ValueError(
                    f"JSONPath '{path}' found no matches in response: {data}"
                )

            return matches[0].value
        except Exception as e:
            # Provide better error context
            raise ValueError(
                f"Failed to extract value using JSONPath '{path}': {str(e)}"
            ) from e

    def _convert_type(self, value: Any, expected_type: str, default: Any | None) -> Any:
        """Convert extracted value to expected type.

        Args:
            value: Extracted value
            expected_type: Expected type (number, string, boolean, json)
            default: Default value if conversion fails

        Returns:
            Converted value

        Raises:
            ValueError: If conversion fails and no default provided
        """
        try:
            match expected_type:
                case "number":
                    return float(value)
                case "string":
                    return str(value)
                case "boolean":
                    # Handle common boolean representations
                    if isinstance(value, bool):
                        return value
                    if isinstance(value, str):
                        return value.lower() not in ("false", "0", "")
                    return bool(value)
                case "json":
                    # Keep as-is
                    return value
                case _:
                    raise ValueError(f"Unknown type: {expected_type}")
        except (ValueError, TypeError) as e:
            if default is not None:
                logger.warning(
                    "Type conversion failed for value '%s', using default: %s",
                    value,
                    default,
                )
                return default
            else:
                raise ValueError(
                    f"Cannot convert '{value}' to {expected_type} and no default provided"
                ) from e

    def _evaluate_check(
        self, evaluator: ThresholdEvaluator, value: Any
    ) -> tuple[bool, str]:
        """Evaluate a threshold check.

        Args:
            evaluator: Threshold evaluator config
            value: Extracted value

        Returns:
            Tuple of (success, message)
        """
        expected = evaluator.value
        op = evaluator.operator

        # Perform comparison
        if op == "<":
            success = value < expected
        elif op == ">":
            success = value > expected
        elif op == "<=":
            success = value <= expected
        elif op == ">=":
            success = value >= expected
        elif op == "==":
            success = value == expected
        elif op == "!=":
            success = value != expected
        else:
            raise ValueError(f"Unknown operator: {op}")

        if success:
            message = f"value {value} {op} {expected}"
        else:
            message = f"value {value} not {op} {expected}"

        return success, message

    def _evaluate_overall(
        self, poll_results: list[CheckResult]
    ) -> tuple[VerificationStatus, str]:
        """Evaluate overall verification status for this poll.

        Args:
            poll_results: Results from current poll

        Returns:
            Tuple of (status, reason)
        """
        passed_count = sum(1 for r in poll_results if r.success)
        failed_count = len(poll_results) - passed_count

        # Get evaluation mode
        mode = self.config.evaluation.mode

        if mode == EvaluationMode.ALL_PASS:
            if passed_count == len(poll_results):
                return VerificationStatus.PASSED, "All checks passed"
            else:
                return VerificationStatus.FAILED, f"{failed_count} check(s) failed"

        elif mode == EvaluationMode.ANY_PASS:
            if passed_count > 0:
                return VerificationStatus.PASSED, "At least one check passed"
            else:
                return VerificationStatus.FAILED, "All checks failed"

        elif mode == EvaluationMode.THRESHOLD:
            min_passed = self.config.evaluation.min_passed or 1
            if passed_count >= min_passed:
                return (
                    VerificationStatus.PASSED,
                    f"{passed_count} checks passed (>= {min_passed})",
                )
            else:
                return (
                    VerificationStatus.FAILED,
                    f"Only {passed_count} checks passed (need >= {min_passed})",
                )

        # Default: continue polling
        return VerificationStatus.FAILED, "Checks not yet passing"

    def _get_latest_results(
        self, all_results: list[CheckResult], poll_count: int
    ) -> list[CheckResult]:
        """Get results from the latest poll.

        Args:
            all_results: All check results
            poll_count: Latest poll number

        Returns:
            Results from latest poll only
        """
        return [r for r in all_results if r.poll_number == poll_count]

    def _build_result(
        self,
        status: VerificationStatus,
        all_results: list[CheckResult],
        poll_count: int,
        duration: int,
        failure_reason: str | None = None,
    ) -> VerificationResult:
        """Build final verification result.

        Args:
            status: Final status
            all_results: All check results across all polls
            poll_count: Total number of polls
            duration: Total duration in seconds
            failure_reason: Optional failure reason

        Returns:
            Verification result
        """
        # Count passed/failed from latest poll only
        latest_poll_results = self._get_latest_results(all_results, poll_count)
        checks_passed = sum(1 for r in latest_poll_results if r.success)
        checks_failed = len(latest_poll_results) - checks_passed

        return VerificationResult(
            status=status,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            total_polls=poll_count,
            duration=duration,
            detailed_results=all_results if self.config.output.include_details else [],
            failure_reason=failure_reason,
        )

    def close(self):
        """Clean up resources."""
        self.http_client.close()
