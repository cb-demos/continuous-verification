"""Integration tests using mock Prometheus server."""

import threading
import time
from pathlib import Path

import httpx
import pytest
import yaml

from cv.verifier import Verifier


@pytest.fixture(scope="module")
def mock_prometheus():
    """Start mock Prometheus server for tests."""
    # Import Flask app
    from tests import mock_prometheus as mock_server

    # Run server in background thread
    def run_server():
        mock_server.app.run(
            host="127.0.0.1", port=9090, debug=False, use_reloader=False
        )

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    max_retries = 20
    for i in range(max_retries):
        try:
            response = httpx.get("http://127.0.0.1:9090/health", timeout=1.0)
            if response.status_code == 200:
                print("\nMock Prometheus server is ready")
                break
        except Exception as e:
            if i == max_retries - 1:
                raise RuntimeError("Mock Prometheus server failed to start") from e
            time.sleep(0.2)

    yield "http://127.0.0.1:9090"


def test_immediate_pass(mock_prometheus):
    """Test verification that passes immediately."""
    config_path = Path(__file__).parent / "test-immediate-pass.yaml"

    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    from cv.models import VerificationConfig, VerificationStatus

    config = VerificationConfig(**config_data)
    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.PASSED
    assert result.checks_passed == 1
    assert result.checks_failed == 0
    assert result.total_polls == 1


def test_multi_check_all_pass(mock_prometheus):
    """Test multiple checks that all pass."""
    config_path = Path(__file__).parent / "test-multi-check.yaml"

    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    from cv.models import VerificationConfig, VerificationStatus

    config = VerificationConfig(**config_data)
    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.PASSED
    assert result.checks_passed == 2
    assert result.checks_failed == 0
    assert result.total_polls == 1


def test_error_rate_decreasing(mock_prometheus):
    """Test error rate that decreases over time (polls until it passes)."""
    config_path = Path(__file__).parent / "test-error-rate.yaml"

    with open(config_path) as f:
        config_data = yaml.safe_load(f)

    from cv.models import VerificationConfig, VerificationStatus

    config = VerificationConfig(**config_data)
    verifier = Verifier(config)
    result = verifier.run()
    verifier.close()

    assert result.status == VerificationStatus.PASSED
    assert result.checks_passed == 1
    assert result.checks_failed == 0
    # Should take multiple polls (error rate decreases over time)
    assert result.total_polls > 1
    # Should take around 20-25 seconds
    assert 15 <= result.duration <= 30
