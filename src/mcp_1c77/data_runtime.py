"""Isolated, serialized OLE session with a finite request deadline.

COM objects never cross the process boundary. Killing a stalled worker does not
terminate any user-owned 1C process. Credentials travel through a private pipe.
"""

from __future__ import annotations

import multiprocessing
import threading


class DataAccessError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _serve(connection) -> None:
    from .ole_data import OleReader

    reader = None
    try:
        while True:
            request = connection.recv()
            try:
                if request["operation"] == "connect":
                    reader = OleReader(**request["arguments"])
                    result = reader.info()
                elif request["operation"] == "close":
                    break
                elif reader is None:
                    raise DataAccessError("not_connected", "База не подключена.")
                else:
                    result = reader.call(request["operation"], request["arguments"])
                connection.send({"success": True, "data": result})
            except DataAccessError as exc:
                connection.send({"success": False, "code": exc.code, "error": str(exc)})
            except Exception:
                # COM exception text can contain the initialization command/password.
                connection.send({"success": False, "code": "ole_error", "error":
                                 "Ошибка OLE 1С 7.7. Проверьте доступность базы и параметры чтения."})
    except (EOFError, BrokenPipeError):
        pass
    finally:
        if reader is not None:
            reader.close()
        connection.close()


class DataRuntime:
    """One worker owns one OLE session; all requests have bounded execution time."""

    def __init__(self, timeout: float = 60):
        self.timeout = timeout
        self._process = None
        self._connection = None
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def connect(self, **arguments) -> dict:
        with self._lock:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            self._connection = parent
            self._process = context.Process(target=_serve, args=(child,), daemon=True)
            self._process.start()
            child.close()
            try:
                return self.call("connect", arguments)
            except Exception:
                self.close()
                raise

    def call(self, operation: str, arguments: dict) -> dict:
        with self._lock:
            if not self.connected:
                raise DataAccessError("not_connected", "Подключите файловую базу через веб-интерфейс.")
            try:
                self._connection.send({"operation": operation, "arguments": arguments})
                if not self._connection.poll(self.timeout):
                    self.close(force=True)
                    raise DataAccessError("timeout", "1С не ответила за отведённое время. Подключитесь заново.")
                response = self._connection.recv()
            except (EOFError, BrokenPipeError, OSError):
                self.close(force=True)
                raise DataAccessError("worker_failed", "Сеанс OLE завершился. Подключитесь заново.") from None
            if not response["success"]:
                raise DataAccessError(response["code"], response["error"])
            return response["data"]

    def close(self, force: bool = False) -> None:
        with self._lock:
            process = self._process
            connection = self._connection
            self._process = self._connection = None
            if process is not None:
                if process.is_alive() and not force:
                    try:
                        connection.send({"operation": "close"})
                        process.join(2)
                    except (BrokenPipeError, OSError):
                        pass
                if process.is_alive():
                    process.terminate()
                    process.join(2)
                process.close()
            if connection is not None:
                connection.close()
