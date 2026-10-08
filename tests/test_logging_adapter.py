"""Tests for LoggingAdapter handler wiring (issue #27: duplicate log lines)."""

import logging
from collections.abc import Iterator

import pytest

from adapters.logging import LoggingAdapter

_NAMES = ("pixi_task", "pixi_task.security")


class _CountingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def counter() -> Iterator[_CountingHandler]:
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved = {
        n: (
            logging.getLogger(n).handlers[:],
            logging.getLogger(n).level,
            logging.getLogger(n).propagate,
        )
        for n in _NAMES
    }
    for n in _NAMES:
        logging.getLogger(n).handlers = []
    handler = _CountingHandler()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.handlers, root.level = saved_root[0], saved_root[1]
        for n, (handlers, level, propagate) in saved.items():
            lg = logging.getLogger(n)
            lg.handlers, lg.level, lg.propagate = handlers, level, propagate


def test_log_info_emitted_once_with_root_handler(counter: _CountingHandler) -> None:
    adapter = LoggingAdapter()
    adapter.log_info("x")
    assert adapter.logger.handlers == []
    assert len(counter.records) == 1


def test_security_event_emitted_once_with_root_handler(counter: _CountingHandler) -> None:
    adapter = LoggingAdapter()
    adapter.log_security_event("y")
    assert adapter.logger.handlers == []
    assert adapter.security_logger.handlers == []
    assert len(counter.records) == 1


def test_child_logger_emitted_once_with_root_handler(counter: _CountingHandler) -> None:
    adapter = LoggingAdapter()
    logging.getLogger("pixi_task.lean_mcp_interface").error("z")
    assert adapter.logger.handlers == []
    assert len(counter.records) == 1


def test_fallback_handler_attached_when_nothing_configured(counter: _CountingHandler) -> None:
    logging.getLogger().handlers = []
    adapter = LoggingAdapter()
    assert len(adapter.logger.handlers) == 1
    assert adapter.security_logger.handlers == []
    adapter.log_info("x")
