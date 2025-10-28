"""CLI entrypoint for continuous verification."""

import json
import logging
import os
import sys
from pathlib import Path

import click
import yaml

from .models import VerificationConfig, VerificationResult, VerificationStatus
from .verifier import Verifier

# Exit codes
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2
EXIT_ERROR = 3


def setup_logging(verbose: bool = False):
    """Configure logging for the application.

    Args:
        verbose: Enable verbose (DEBUG) logging
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
    )


@click.group()
def cli():
    """Continuous Verification CLI for metrics monitoring."""
    pass


@cli.command()
@click.option(
    "--config-file",
    type=click.Path(exists=True),
    help="Path to YAML/JSON configuration file",
)
@click.option(
    "--config-stdin",
    is_flag=True,
    help="Read configuration from stdin",
)
@click.option(
    "--config-env",
    type=str,
    help="Environment variable name containing configuration",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    help="Directory to write output files (for CloudBees)",
)
@click.option(
    "--poll-interval",
    type=int,
    help="Override polling interval (seconds)",
)
@click.option(
    "--timeout",
    type=int,
    help="Override timeout (seconds)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def verify(
    config_file: str | None,
    config_stdin: bool,
    config_env: str | None,
    output_dir: str | None,
    poll_interval: int | None,
    timeout: int | None,
    verbose: bool,
):
    """Run continuous verification."""
    # Setup logging
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    try:
        # Load configuration
        config = load_config(config_file, config_stdin, config_env)

        # Apply CLI overrides
        if poll_interval:
            config.poll_interval = poll_interval
        if timeout:
            config.timeout = timeout

        # Run verification
        verifier = Verifier(config)
        try:
            result = verifier.run()
        finally:
            verifier.close()

        # Print summary
        logger.info("=" * 60)
        logger.info("Final Status: %s", result.status.value)
        logger.info("Checks Passed: %d", result.checks_passed)
        logger.info("Checks Failed: %d", result.checks_failed)
        logger.info("Total Polls: %d", result.total_polls)
        logger.info("Duration: %ds", result.duration)
        if result.failure_reason:
            logger.info("Reason: %s", result.failure_reason)
        logger.info("=" * 60)

        # Write outputs if directory specified
        if output_dir:
            write_outputs(result, output_dir)

        # Set exit code based on status
        match result.status:
            case VerificationStatus.PASSED:
                sys.exit(EXIT_SUCCESS)
            case VerificationStatus.FAILED:
                sys.exit(EXIT_FAILED)
            case VerificationStatus.TIMEOUT:
                sys.exit(EXIT_TIMEOUT)

    except Exception as e:
        logger.error("Verification failed: %s", str(e), exc_info=verbose)
        sys.exit(EXIT_ERROR)


def load_config(
    config_file: str | None,
    config_stdin: bool,
    config_env: str | None,
) -> VerificationConfig:
    """Load configuration from various sources.

    Args:
        config_file: Path to config file
        config_stdin: Read from stdin
        config_env: Environment variable name

    Returns:
        Parsed configuration

    Raises:
        ValueError: If no config source specified or parsing fails
    """
    config_data = None

    # Load from file
    if config_file:
        with open(config_file) as f:
            content = f.read()
            # Try YAML first (it's a superset of JSON)
            try:
                config_data = yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise ValueError(
                    f"Failed to parse configuration file '{config_file}': {e}"
                ) from e

    # Load from stdin
    elif config_stdin:
        content = sys.stdin.read()
        try:
            config_data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse configuration from stdin: {e}") from e

    # Load from environment variable
    elif config_env:
        content = os.environ.get(config_env)
        if not content:
            raise ValueError(f"Environment variable '{config_env}' not found or empty")
        try:
            config_data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(
                f"Failed to parse configuration from environment variable '{config_env}': {e}"
            ) from e

    else:
        raise ValueError(
            "Must specify one of: --config-file, --config-stdin, or --config-env"
        )

    # Parse and validate with Pydantic
    try:
        return VerificationConfig(**config_data)
    except Exception as e:
        raise ValueError(f"Configuration validation failed: {e}") from e


def write_outputs(result: VerificationResult, output_dir: str):
    """Write outputs to files for CloudBees.

    Args:
        result: Verification result
        output_dir: Directory to write output files
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Write each output as a separate file
    (output_path / "verification-status").write_text(result.status.value)
    (output_path / "checks-passed").write_text(str(result.checks_passed))
    (output_path / "checks-failed").write_text(str(result.checks_failed))
    (output_path / "duration").write_text(str(result.duration))
    (output_path / "poll-count").write_text(str(result.total_polls))

    # Write detailed results as JSON
    detailed = {
        "status": result.status.value,
        "checks_passed": result.checks_passed,
        "checks_failed": result.checks_failed,
        "total_polls": result.total_polls,
        "duration": result.duration,
        "failure_reason": result.failure_reason,
        "results": [
            {
                "check_name": r.check_name,
                "success": r.success,
                "value": r.value,
                "expected": r.expected,
                "message": r.message,
                "timestamp": r.timestamp.isoformat(),
                "poll_number": r.poll_number,
            }
            for r in result.detailed_results
        ],
    }
    (output_path / "detailed-results").write_text(json.dumps(detailed, indent=2))

    logging.getLogger(__name__).info("Outputs written to %s", output_dir)


if __name__ == "__main__":
    cli()
