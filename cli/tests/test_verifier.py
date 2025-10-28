"""Tests for the verification engine."""

import httpx
from pytest_httpx import HTTPXMock

from cv.models import (
    AuthConfig,
    Check,
    ExtractConfig,
    QueryConfig,
    ThresholdEvaluator,
    VerificationConfig,
    VerificationStatus,
)
from cv.verifier import Verifier


def test_simple_threshold_pass(httpx_mock: HTTPXMock):
    """Test a simple threshold check that passes."""
    # Mock Prometheus-like response
    httpx_mock.add_response(
        url="http://prometheus:9090/api/v1/query",
        json={
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "error_count"},
                        "value": [1234567890, "5"],  # 5 errors
                    }
                ],
            },
        },
    )

    # Create config
    config = VerificationConfig(
        api_endpoint="http://prometheus:9090",
        checks=[
            Check(
                name="error_count_check",
                query=QueryConfig(
                    endpoint="/api/v1/query",
                    method="POST",
                    body="query=error_count",
                ),
                extract=ExtractConfig(
                    path="$.data.result[0].value[1]",
                    type="number",
                ),
                evaluate=ThresholdEvaluator(
                    type="threshold",
                    operator="<",
                    value=10,  # Pass if < 10
                ),
            )
        ],
        poll_interval=1,
        timeout=5,
    )

    # Run verification
    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    # Assert
    assert result.status == VerificationStatus.PASSED
    assert result.checks_passed == 1
    assert result.checks_failed == 0
    assert result.total_polls == 1


def test_simple_threshold_fail(httpx_mock: HTTPXMock):
    """Test a simple threshold check that fails."""
    # Mock response with high error count - add enough for 5 polls
    for _ in range(5):
        httpx_mock.add_response(
            url="http://prometheus:9090/api/v1/query",
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"__name__": "error_count"},
                            "value": [1234567890, "50"],  # 50 errors (bad!)
                        }
                    ],
                },
            },
        )

    config = VerificationConfig(
        api_endpoint="http://prometheus:9090",
        checks=[
            Check(
                name="error_count_check",
                query=QueryConfig(
                    endpoint="/api/v1/query",
                    method="POST",
                    body="query=error_count",
                ),
                extract=ExtractConfig(
                    path="$.data.result[0].value[1]",
                    type="number",
                ),
                evaluate=ThresholdEvaluator(
                    type="threshold",
                    operator="<",
                    value=10,
                ),
            )
        ],
        poll_interval=1,
        timeout=5,
    )

    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.FAILED
    assert result.checks_passed == 0
    assert result.checks_failed == 1


def test_polling_until_pass(httpx_mock: HTTPXMock):
    """Test that verification polls until check passes."""
    # First two polls fail, third passes
    responses = [
        {"data": {"result": [{"value": [0, "50"]}]}},  # Poll 1: 50 errors (fail)
        {"data": {"result": [{"value": [0, "20"]}]}},  # Poll 2: 20 errors (fail)
        {"data": {"result": [{"value": [0, "5"]}]}},  # Poll 3: 5 errors (pass!)
    ]

    for response in responses:
        httpx_mock.add_response(
            url="http://prometheus:9090/api/v1/query",
            json=response,
        )

    config = VerificationConfig(
        api_endpoint="http://prometheus:9090",
        checks=[
            Check(
                name="error_count_check",
                query=QueryConfig(
                    endpoint="/api/v1/query",
                    method="POST",
                ),
                extract=ExtractConfig(
                    path="$.data.result[0].value[1]",
                    type="number",
                ),
                evaluate=ThresholdEvaluator(
                    type="threshold",
                    operator="<",
                    value=10,
                ),
            )
        ],
        poll_interval=1,
        timeout=10,
    )

    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.PASSED
    assert result.total_polls == 3  # Took 3 polls to pass


def test_multiple_checks_all_pass(httpx_mock: HTTPXMock):
    """Test multiple checks with all-pass mode."""
    # Mock responses for two checks (need 2 responses since we make 2 requests)
    httpx_mock.add_response(
        url="http://prometheus:9090/api/v1/query",
        json={"data": {"result": [{"value": [0, "5"]}]}},
    )
    httpx_mock.add_response(
        url="http://prometheus:9090/api/v1/query",
        json={"data": {"result": [{"value": [0, "5"]}]}},
    )

    config = VerificationConfig(
        api_endpoint="http://prometheus:9090",
        checks=[
            Check(
                name="error_count",
                query=QueryConfig(endpoint="/api/v1/query", method="POST"),
                extract=ExtractConfig(path="$.data.result[0].value[1]", type="number"),
                evaluate=ThresholdEvaluator(type="threshold", operator="<", value=10),
            ),
            Check(
                name="error_count_duplicate",  # Same check twice for testing
                query=QueryConfig(endpoint="/api/v1/query", method="POST"),
                extract=ExtractConfig(path="$.data.result[0].value[1]", type="number"),
                evaluate=ThresholdEvaluator(type="threshold", operator="<", value=10),
            ),
        ],
        poll_interval=1,
        timeout=5,
    )

    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.PASSED
    assert result.checks_passed == 2
    assert result.checks_failed == 0


def test_bearer_auth(httpx_mock: HTTPXMock):
    """Test Bearer token authentication."""

    def check_auth(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            status_code=200,
            json={"data": {"result": [{"value": [0, "5"]}]}},
        )

    httpx_mock.add_callback(check_auth, url="http://api:8080/metrics")

    config = VerificationConfig(
        api_endpoint="http://api:8080",
        auth=AuthConfig(method="bearer", token="test-token"),
        checks=[
            Check(
                name="test",
                query=QueryConfig(endpoint="/metrics", method="GET"),
                extract=ExtractConfig(path="$.data.result[0].value[1]", type="number"),
                evaluate=ThresholdEvaluator(type="threshold", operator="<", value=10),
            )
        ],
        poll_interval=1,
        timeout=5,
    )

    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.PASSED
