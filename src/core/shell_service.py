"""
Core business logic for ClaudeCode Shell MCP Server.

This module implements the secure execution service for claudecode functions,
providing thread-safe operations with comprehensive security validation.
"""

import time
from typing import Any

from core.models import (
    BulkExecutionRequest,
    FunctionExecutionRequest,
    SecurityAuditLog,
)
from core.ports import (
    CachePort,
    EnvironmentPort,
    FunctionDiscoveryPort,
    FunctionExecutorPort,
    LoggingPort,
    MetricsPort,
    SecurityAuditPort,
    TimeoutPort,
    ValidationPort,
)


class ClaudeCodeShellService:
    """
    Core service for secure claudecode function execution.

    Provides thread-safe operations with comprehensive security validation,
    audit logging, and performance monitoring.
    """

    def __init__(
        self,
        function_executor: FunctionExecutorPort,
        function_discovery: FunctionDiscoveryPort,
        security_audit: SecurityAuditPort,
        logging: LoggingPort,
        environment: EnvironmentPort,
        validation: ValidationPort,
        timeout: TimeoutPort,
        cache: CachePort,
        metrics: MetricsPort,
    ):
        self.function_executor = function_executor
        self.function_discovery = function_discovery
        self.security_audit = security_audit
        self.logging = logging
        self.environment = environment
        self.validation = validation
        self.timeout = timeout
        self.cache = cache
        self.metrics = metrics

    def execute_function(
        self,
        function_name: str,
        args: list[str] | None = None,
        working_dir: str | None = None,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """
        Execute a claudecode function with comprehensive security validation.

        Returns: {"success": bool, "stdout": str, "stderr": str, "exit_code": int, "execution_time": float}
        """
        start_time = time.time()

        # Create execution request with validation
        try:
            request = FunctionExecutionRequest(
                function_name=function_name,
                args=args or [],
                working_dir=working_dir,
                timeout_seconds=timeout_seconds,
            )
        except Exception as e:
            self.logging.log_error(f"Invalid execution request: {e}")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Invalid request: {str(e)}",
                "exit_code": 1,
                "execution_time": time.time() - start_time,
            }

        # Security validation
        security_issues = self.security_audit.check_security_violations(request)
        if security_issues:
            error_msg = f"Security violations detected: {', '.join(security_issues)}"
            self.logging.log_security_event(
                error_msg,
                {
                    "function_name": function_name,
                    "args": args,
                    "violations": security_issues,
                },
            )
            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": 1,
                "execution_time": time.time() - start_time,
            }

        # Execute function
        try:
            result = self.function_executor.execute_function(request)

            # Log execution for audit
            audit_log = SecurityAuditLog.create(request, result, security_issues)
            self.security_audit.log_execution(audit_log)

            # Record metrics
            self.metrics.record_execution_time(function_name, result.execution_time)
            if result.success:
                self.metrics.record_execution_success(function_name)
            else:
                self.metrics.record_execution_failure(function_name, "execution_failed")

            self.logging.log_info(
                f"Function executed: {function_name}",
                {
                    "success": result.success,
                    "exit_code": result.exit_code,
                    "execution_time": result.execution_time,
                },
            )

            return {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "execution_time": result.execution_time,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Function execution failed: {str(e)}"

            self.logging.log_error(
                error_msg,
                {"function_name": function_name, "args": args, "error": str(e)},
            )

            self.metrics.record_execution_failure(function_name, "exception")

            return {
                "success": False,
                "stdout": "",
                "stderr": error_msg,
                "exit_code": 1,
                "execution_time": execution_time,
            }

    def list_available_functions(self, category: str | None = None) -> dict[str, Any]:
        """
        List available claudecode functions with caching.

        Returns: {"functions": [...], "total_count": int, "categories": {...}}
        """
        start_time = time.time()

        try:
            # Check cache first
            cache_key = f"discovery_{category or 'all'}"
            cached_result = self.cache.get_cached_discovery(cache_key)

            if cached_result:
                self.logging.log_info(f"Function discovery cache hit: {cache_key}")
                return {
                    "functions": [func.dict() for func in cached_result.functions],
                    "total_count": cached_result.total_count,
                    "categories": cached_result.categories,
                    "discovery_time": cached_result.discovery_time,
                    "cached": True,
                }

            # Discover functions
            discovery_result = self.function_discovery.discover_functions(category)

            # Cache the result
            self.cache.cache_discovery(cache_key, discovery_result, ttl_seconds=600)

            self.logging.log_info(
                "Function discovery completed",
                {
                    "category": category,
                    "total_functions": discovery_result.total_count,
                    "discovery_time": discovery_result.discovery_time,
                },
            )

            return {
                "functions": [func.dict() for func in discovery_result.functions],
                "total_count": discovery_result.total_count,
                "categories": discovery_result.categories,
                "discovery_time": discovery_result.discovery_time,
                "cached": False,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Function discovery failed: {str(e)}"

            self.logging.log_error(error_msg, {"category": category, "error": str(e)})

            return {
                "functions": [],
                "total_count": 0,
                "categories": {},
                "discovery_time": execution_time,
                "error": error_msg,
            }

    def validate_function_exists(self, function_name: str) -> dict[str, Any]:
        """
        Validate that a claudecode function exists and is executable.

        Returns: {"exists": bool, "executable": bool, "description": str}
        """
        try:
            # Check cache first
            cached_result = self.cache.get_cached_function_info(function_name)
            if cached_result:
                self.logging.log_info(f"Function validation cache hit: {function_name}")
                return {
                    "exists": cached_result.exists,
                    "executable": cached_result.executable,
                    "description": cached_result.description,
                    "path": cached_result.path,
                    "cached": True,
                }

            # Validate function
            validation_result = self.function_executor.validate_function(function_name)

            # Cache the result
            self.cache.cache_function_info(
                function_name, validation_result, ttl_seconds=300
            )

            self.logging.log_info(
                f"Function validated: {function_name}",
                {
                    "exists": validation_result.exists,
                    "executable": validation_result.executable,
                },
            )

            return {
                "exists": validation_result.exists,
                "executable": validation_result.executable,
                "description": validation_result.description,
                "path": validation_result.path,
                "cached": False,
            }

        except Exception as e:
            error_msg = f"Function validation failed: {str(e)}"
            self.logging.log_error(
                error_msg, {"function_name": function_name, "error": str(e)}
            )

            return {
                "exists": False,
                "executable": False,
                "description": error_msg,
                "path": None,
                "error": str(e),
            }

    def execute_bulk_functions(
        self, operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Execute multiple claudecode functions with atomic semantics.

        Returns: {"success": bool, "results": [...], "errors": [...]}
        """
        start_time = time.time()

        try:
            # Convert operations to execution requests
            requests = []
            for op in operations:
                try:
                    request = FunctionExecutionRequest(
                        function_name=op["function_name"],
                        args=op.get("args", []),
                        working_dir=op.get("working_dir"),
                        timeout_seconds=op.get("timeout_seconds", 30),
                    )
                    requests.append(request)
                except Exception as e:
                    return {
                        "success": False,
                        "results": [],
                        "errors": [f"Invalid operation: {str(e)}"],
                        "partial_success": False,
                        "completed_operations": 0,
                        "total_operations": len(operations),
                    }

            # Create bulk request
            bulk_request = BulkExecutionRequest(
                operations=requests, atomic=True, timeout_seconds=120
            )

            # Execute bulk operations
            bulk_result = self.function_executor.execute_bulk(bulk_request)

            # Log bulk execution
            self.logging.log_info(
                "Bulk execution completed",
                {
                    "total_operations": bulk_result.total_operations,
                    "completed_operations": bulk_result.completed_operations,
                    "success": bulk_result.success,
                    "execution_time": bulk_result.total_execution_time,
                },
            )

            return {
                "success": bulk_result.success,
                "results": [result.dict() for result in bulk_result.results],
                "errors": bulk_result.errors,
                "partial_success": bulk_result.partial_success,
                "completed_operations": bulk_result.completed_operations,
                "total_operations": bulk_result.total_operations,
                "execution_time": bulk_result.total_execution_time,
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Bulk execution failed: {str(e)}"

            self.logging.log_error(
                error_msg, {"operations_count": len(operations), "error": str(e)}
            )

            return {
                "success": False,
                "results": [],
                "errors": [error_msg],
                "partial_success": False,
                "completed_operations": 0,
                "total_operations": len(operations),
                "execution_time": execution_time,
            }

    def get_execution_stats(self, hours: int = 24) -> dict[str, Any]:
        """
        Get execution statistics for monitoring and debugging.

        Returns: Comprehensive execution statistics
        """
        try:
            stats = self.security_audit.get_execution_stats(hours)
            metrics = self.metrics.get_metrics_summary(hours)

            return {
                "total_executions": stats.total_executions,
                "successful_executions": stats.successful_executions,
                "failed_executions": stats.failed_executions,
                "success_rate": (
                    stats.successful_executions / max(stats.total_executions, 1)
                )
                * 100,
                "average_execution_time": stats.average_execution_time,
                "most_used_functions": stats.most_used_functions,
                "stats_period_hours": hours,
                "metrics_summary": metrics,
            }

        except Exception as e:
            self.logging.log_error(f"Failed to get execution stats: {str(e)}")
            return {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "success_rate": 0.0,
                "average_execution_time": 0.0,
                "most_used_functions": {},
                "error": str(e),
            }

    def get_system_health(self) -> dict[str, Any]:
        """
        Get system health information for monitoring.

        Returns: System health status and metrics
        """
        try:
            health = self.environment.get_system_health()
            security_alerts = self.security_audit.get_security_alerts()

            return {
                "healthy": health.healthy,
                "available_functions": health.available_functions,
                "recent_executions": health.recent_executions,
                "error_rate": health.error_rate,
                "average_response_time": health.average_response_time,
                "security_alerts": security_alerts,
                "resource_usage": health.resource_usage,
                "last_health_check": health.last_health_check,
            }

        except Exception as e:
            self.logging.log_error(f"Health check failed: {str(e)}")
            return {
                "healthy": False,
                "available_functions": 0,
                "recent_executions": 0,
                "error_rate": 100.0,
                "average_response_time": 0.0,
                "security_alerts": [f"Health check failed: {str(e)}"],
                "resource_usage": {},
                "last_health_check": f"{time.time():.6f}",
                "error": str(e),
            }

    def cleanup_cache(self, max_age_minutes: int = 60) -> dict[str, Any]:
        """
        Clean up cached data for maintenance.

        Returns: Cleanup summary
        """
        try:
            cleaned_entries = self.cache.invalidate_cache()

            self.logging.log_info(
                "Cache cleanup completed",
                {
                    "cleaned_entries": cleaned_entries,
                    "max_age_minutes": max_age_minutes,
                },
            )

            return {
                "success": True,
                "cleaned_entries": cleaned_entries,
                "max_age_minutes": max_age_minutes,
            }

        except Exception as e:
            self.logging.log_error(f"Cache cleanup failed: {str(e)}")
            return {"success": False, "cleaned_entries": 0, "error": str(e)}
