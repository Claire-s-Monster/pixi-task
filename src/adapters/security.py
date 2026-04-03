"""
Security audit adapter for ClaudeCode Shell MCP Server.

Provides security auditing, execution tracking, and metrics collection.
"""

import time
from collections import defaultdict
from typing import Any

from core.models import ExecutionStats, FunctionExecutionRequest, SecurityAuditLog
from core.ports import LoggingPort, MetricsPort, SecurityAuditPort


class SecurityAuditAdapter(SecurityAuditPort, MetricsPort):
    """Adapter for security auditing and metrics collection."""

    def __init__(self, logging: LoggingPort):
        self.logging = logging
        self.execution_logs: list[SecurityAuditLog] = []
        self.metrics: dict[str, Any] = defaultdict(lambda: defaultdict(int))
        self.execution_times: dict[str, list[float]] = defaultdict(list)
        self.security_alerts: list[str] = []

        # Keep metrics for the last 7 days
        self.max_logs = 10000

    def log_execution(self, audit_log: SecurityAuditLog) -> None:
        """Log a function execution for security audit."""
        self.execution_logs.append(audit_log)

        # Trim old logs to maintain memory usage
        if len(self.execution_logs) > self.max_logs:
            self.execution_logs = self.execution_logs[-self.max_logs // 2 :]

        # Log security events if there are flags
        if audit_log.security_flags:
            self.logging.log_security_event(
                f"Security flags in execution: {audit_log.function_name}",
                {
                    "execution_id": audit_log.execution_id,
                    "flags": audit_log.security_flags,
                    "args": audit_log.args,
                },
            )

    def get_execution_stats(self, hours: int = 24) -> ExecutionStats:
        """Get execution statistics for the specified period."""
        cutoff_time = time.time() - (hours * 3600)

        # Filter logs by time period
        recent_logs = [
            log for log in self.execution_logs if float(log.timestamp) > cutoff_time
        ]

        total_executions = len(recent_logs)
        successful_executions = sum(1 for log in recent_logs if log.success)
        failed_executions = total_executions - successful_executions

        # Calculate average execution time
        execution_times = [log.execution_time for log in recent_logs]
        average_execution_time = (
            sum(execution_times) / len(execution_times) if execution_times else 0.0
        )

        # Count function usage
        function_counts = defaultdict(int)
        for log in recent_logs:
            function_counts[log.function_name] += 1

        # Sort by usage count
        most_used_functions = dict(
            sorted(function_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        )

        return ExecutionStats(
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            average_execution_time=average_execution_time,
            most_used_functions=most_used_functions,
            execution_history=recent_logs[-50:],  # Last 50 executions
            stats_period_start=f"{time.time() - (hours * 3600):.6f}",
            stats_period_end=f"{time.time():.6f}",
        )

    def check_security_violations(self, request: FunctionExecutionRequest) -> list[str]:
        """Check for potential security violations in a request."""
        violations = []

        # Check for suspicious function names
        if not request.function_name.startswith("claudecode_"):
            violations.append("Function name does not start with claudecode_")

        # Check for dangerous arguments
        dangerous_patterns = [";", "&", "|", "`", "$", "$(", "rm -rf", "sudo"]
        for arg in request.args:
            for pattern in dangerous_patterns:
                if pattern in arg.lower():
                    violations.append(f"Dangerous pattern '{pattern}' in argument")
                    break

        # Check for excessive argument count
        if len(request.args) > 50:
            violations.append(f"Excessive argument count: {len(request.args)}")

        # Check for very long arguments
        for arg in request.args:
            if len(arg) > 1000:
                violations.append(f"Argument too long: {len(arg)} characters")

        # Check timeout
        if request.timeout_seconds > 300:
            violations.append(f"Excessive timeout: {request.timeout_seconds}")

        return violations

    def get_security_alerts(self) -> list[str]:
        """Get current security alerts."""
        # Return recent security alerts (could be enhanced with real monitoring)
        recent_violations = []

        # Check for recent failed executions with security flags
        cutoff_time = time.time() - 3600  # Last hour
        for log in self.execution_logs:
            if float(log.timestamp) > cutoff_time and log.security_flags:
                recent_violations.extend(log.security_flags)

        # Add any persistent alerts
        alerts = list(set(recent_violations + self.security_alerts))

        return alerts[:10]  # Limit to 10 most recent

    # MetricsPort implementation
    def record_execution_time(self, function_name: str, execution_time: float) -> None:
        """Record execution time for a function."""
        self.execution_times[function_name].append(execution_time)

        # Keep only recent times (last 1000 per function)
        if len(self.execution_times[function_name]) > 1000:
            self.execution_times[function_name] = self.execution_times[function_name][
                -500:
            ]

    def record_execution_success(self, function_name: str) -> None:
        """Record a successful function execution."""
        self.metrics[function_name]["success_count"] += 1
        self.metrics[function_name]["total_count"] += 1

    def record_execution_failure(self, function_name: str, error_type: str) -> None:
        """Record a failed function execution."""
        self.metrics[function_name]["failure_count"] += 1
        self.metrics[function_name]["total_count"] += 1
        self.metrics[function_name][f"error_{error_type}"] += 1

    def get_metrics_summary(self, hours: int = 24) -> dict[str, Any]:
        """Get metrics summary for the specified period."""
        # For simplicity, return current metrics (could be enhanced with time-based filtering)
        summary = {}

        for function_name, metrics in self.metrics.items():
            if metrics["total_count"] > 0:
                success_rate = (metrics["success_count"] / metrics["total_count"]) * 100
                avg_time = (
                    sum(self.execution_times[function_name])
                    / len(self.execution_times[function_name])
                    if self.execution_times[function_name]
                    else 0.0
                )

                summary[function_name] = {
                    "total_count": metrics["total_count"],
                    "success_count": metrics["success_count"],
                    "failure_count": metrics["failure_count"],
                    "success_rate": success_rate,
                    "average_execution_time": avg_time,
                }

        return summary

    def export_metrics(self) -> dict[str, Any]:
        """Export all metrics for external monitoring."""
        return {
            "function_metrics": dict(self.metrics),
            "execution_times": dict(self.execution_times),
            "total_executions": len(self.execution_logs),
            "security_alerts": self.security_alerts,
            "export_timestamp": f"{time.time():.6f}",
        }
