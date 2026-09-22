"""Unit tests for the isolated OLE worker lifecycle."""

import pytest

from mcp_1c77.data_runtime import DataAccessError, DataRuntime


class FakeProcess:
    def __init__(self, alive=True, stop_on_join=True):
        self.alive = alive
        self.stop_on_join = stop_on_join
        self.terminated = False
        self.closed = False

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        if self.stop_on_join:
            self.alive = False

    def terminate(self):
        self.terminated = True
        self.alive = False

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, *, polled=True, response=None, send_error=None):
        self.polled = polled
        self.response = response
        self.send_error = send_error
        self.sent = []
        self.closed = False

    def send(self, value):
        if self.send_error:
            raise self.send_error
        self.sent.append(value)

    def poll(self, timeout):
        return self.polled

    def recv(self):
        return self.response

    def close(self):
        self.closed = True


def prepared_runtime(connection, process=None):
    runtime = DataRuntime(timeout=0.01)
    runtime._process = process or FakeProcess()
    runtime._connection = connection
    return runtime


def test_call_deadline_forces_worker_shutdown():
    process = FakeProcess(stop_on_join=False)
    connection = FakeConnection(polled=False)
    runtime = prepared_runtime(connection, process)

    with pytest.raises(DataAccessError) as error:
        runtime.call("read_catalog", {})

    assert error.value.code == "timeout"
    assert process.terminated
    assert process.closed
    assert connection.closed
    assert runtime._process is None


def test_worker_error_is_returned_as_typed_error():
    connection = FakeConnection(
        response={"success": False, "code": "bad_query", "error": "Неверный запрос"}
    )
    runtime = prepared_runtime(connection)

    with pytest.raises(DataAccessError) as error:
        runtime.call("read_documents", {"password": "must-not-leak"})

    assert error.value.code == "bad_query"
    assert str(error.value) == "Неверный запрос"


def test_broken_worker_is_closed_and_returns_safe_error():
    secret = "very-secret"
    connection = FakeConnection(send_error=BrokenPipeError(secret))
    runtime = prepared_runtime(connection)

    with pytest.raises(DataAccessError) as error:
        runtime.call("read_catalog", {"password": secret})

    assert error.value.code == "worker_failed"
    assert secret not in str(error.value)
    assert connection.closed


def test_close_requests_graceful_shutdown():
    process = FakeProcess(stop_on_join=True)
    connection = FakeConnection()
    runtime = prepared_runtime(connection, process)

    runtime.close()

    assert connection.sent == [{"operation": "close"}]
    assert not process.terminated
    assert process.closed
    assert connection.closed
    assert runtime._process is None
    assert runtime._connection is None

