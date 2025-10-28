#!/usr/bin/env python3
"""Mock Prometheus server for testing continuous verification."""

import time

from flask import Flask, jsonify, request

app = Flask(__name__)

# Track request count to simulate changing metrics
request_counts = {"error_rate": 0, "latency": 0}
start_time = time.time()


@app.route("/api/v1/query", methods=["POST", "GET"])
def query():
    """Mock Prometheus query endpoint."""
    # Get query from either GET params or POST body
    if request.method == "POST":
        query_str = request.form.get("query", "")
    else:
        query_str = request.args.get("query", "")

    print(f"Received query: {query_str}")

    # Simulate different metric scenarios based on query
    if "error_rate" in query_str.lower():
        return handle_error_rate()
    elif "latency" in query_str.lower() or "response_time" in query_str.lower():
        return handle_latency()
    elif "uptime" in query_str.lower() or "up{" in query_str.lower():
        return handle_uptime()
    elif "decreasing" in query_str.lower():
        return handle_decreasing_metric()
    elif "empty" in query_str.lower():
        return handle_empty_result()
    else:
        # Default: return a simple metric
        return jsonify(
            {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"__name__": "test_metric"},
                            "value": [int(time.time()), "5.0"],
                        }
                    ],
                },
            }
        )


def handle_error_rate():
    """Simulate error rate that starts high and decreases over time."""
    request_counts["error_rate"] += 1
    elapsed = time.time() - start_time

    # Start at 0.05 (5% errors), decrease to 0.005 (0.5%) over 30 seconds
    if elapsed < 10:
        value = "0.05"  # High error rate
    elif elapsed < 20:
        value = "0.02"  # Medium error rate
    else:
        value = "0.005"  # Low error rate (below threshold)

    print(f"  → Returning error_rate: {value} (elapsed: {elapsed:.1f}s)")

    return jsonify(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {
                            "__name__": "http_requests_errors_total",
                            "job": "web",
                        },
                        "value": [int(time.time()), value],
                    }
                ],
            },
        }
    )


def handle_latency():
    """Simulate latency metric."""
    request_counts["latency"] += 1

    # Return p99 latency: 450ms (below 500ms threshold)
    value = "0.450"

    print(f"  → Returning latency: {value}s")

    return jsonify(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "http_request_duration_seconds"},
                        "value": [int(time.time()), value],
                    }
                ],
            },
        }
    )


def handle_uptime():
    """Simulate uptime metric (always 1)."""
    print("  → Returning uptime: 1")

    return jsonify(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "up", "job": "my-service"},
                        "value": [int(time.time()), "1"],
                    }
                ],
            },
        }
    )


def handle_decreasing_metric():
    """Metric that starts high (50) and decreases to low (5) over time."""
    elapsed = time.time() - start_time

    if elapsed < 5:
        value = "50"
    elif elapsed < 10:
        value = "30"
    elif elapsed < 15:
        value = "15"
    else:
        value = "5"

    print(f"  → Returning decreasing metric: {value} (elapsed: {elapsed:.1f}s)")

    return jsonify(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "decreasing_metric"},
                        "value": [int(time.time()), value],
                    }
                ],
            },
        }
    )


def handle_empty_result():
    """Simulate empty result (no data)."""
    print("  → Returning empty result")

    return jsonify(
        {"status": "success", "data": {"resultType": "vector", "result": []}}
    )


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    print("=" * 60)
    print("Mock Prometheus Server")
    print("=" * 60)
    print("\nEndpoints:")
    print("  - POST/GET /api/v1/query - Prometheus query API")
    print("  - GET /health - Health check")
    print("\nQuery patterns:")
    print("  - 'error_rate' - Returns error rate that decreases over time")
    print("  - 'latency' - Returns 450ms latency")
    print("  - 'uptime' or 'up{' - Returns uptime=1")
    print("  - 'decreasing' - Returns metric that goes 50→30→15→5")
    print("  - 'empty' - Returns empty result")
    print("\nServer starting on http://localhost:9090")
    print("=" * 60)

    app.run(host="0.0.0.0", port=9090, debug=False)
