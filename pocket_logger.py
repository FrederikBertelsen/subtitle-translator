import builtins
import os
import sys
from datetime import datetime
from typing import Optional

_ORIGINAL_PRINT = builtins.print
_ORIGINAL_STDERR = sys.stderr
_ORIGINAL_STDOUT = sys.stdout

_LOGGER_REGISTRY = []


def _global_print(*args, sep=' ', end='\n', file=None, flush=False, **kwargs):
    """Global print proxy: prints as normal and sends messages to registered loggers.

    This function preserves the usual `print` behavior while also delivering
    the rendered message to any registered `PocketLogger` instances.
    """
    message_body = sep.join(map(str, args))

    console_message = message_body
    if _LOGGER_REGISTRY and getattr(_LOGGER_REGISTRY[0], 'console_timestamp', False):
        try:
            ts = _LOGGER_REGISTRY[0]._current_timestamp()
            console_message = f'[{ts}] {message_body}'
        except Exception:
            console_message = message_body
    try:
        _ORIGINAL_PRINT(console_message, end=end, file=file, flush=flush, **kwargs)
    except TypeError:
        # In case unexpected kwargs make this fail, fall back to a safe call.
        _ORIGINAL_PRINT(console_message, end=end, file=file, flush=flush)
    if file is None or file in (sys.stdout, _ORIGINAL_STDOUT):
        for logger in list(_LOGGER_REGISTRY):
            try:
                logger._log_from_print(message_body)
            except Exception:
                # Swallow exceptions inside the global proxy to avoid breaking prints.
                pass


class _StdErrProxy:
    """Proxy for sys.stderr that forwards writes to registered loggers and original stderr."""

    def write(self, data):
        if data and data.strip():
            for logger in list(_LOGGER_REGISTRY):
                try:
                    logger.log_raw(data)
                except Exception:
                    pass
        _ORIGINAL_STDERR.write(data)

    def flush(self):
        try:
            return _ORIGINAL_STDERR.flush()
        except Exception:
            return None

    def __getattr__(self, name):
        return getattr(_ORIGINAL_STDERR, name)


class PocketLogger:
    """Lightweight logger that captures `print()` calls and `sys.stderr` writes to a file.

    Args:
        log_file_path: Path to the log file (string). If provided, ".log" is appended when missing.
        print_time: If True, prefix console output with a timestamp.
        print_message: If True, allow messages to be printed to the console.
        save_time: If True, include timestamps in saved file entries.
        save_message: If True, save the printed message into the log file.
        add_date_and_time_to_log_file_name: If True, append the current datetime to the filename.
        create_new_log_file: If True, find a unique filename when the target exists.

    Use `restore()` to unregister the logger and restore `print`/`sys.stderr` when finished.
    """

    def __init__(
        self,
        log_file_path: Optional[str] = None,
        print_time: bool = True,
        print_message: bool = True,
        save_time: bool = True,
        save_message: bool = True,
        add_date_and_time_to_log_file_name: bool = False,
        create_new_log_file: bool = True,
    ) -> None:
        # Public-facing parameter names preserved for backwards compatibility;
        # internal attribute names are clearer.
        self._log_path = log_file_path
        self.console_timestamp = print_time
        self.console_print = print_message
        self.file_timestamp = save_time
        self.file_message = save_message
        self.append_timestamp_to_filename = add_date_and_time_to_log_file_name
        self.ensure_unique_log_file = create_new_log_file

        self._is_registered = False

        if self._log_path:
            if not self._log_path.endswith('.log'):
                self._log_path += '.log'
            log_dir = os.path.dirname(self._log_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            if self.append_timestamp_to_filename:
                self._log_path = self._append_timestamp_to_filename(self._log_path)
            if self.ensure_unique_log_file:
                self._log_path = self._find_available_log_path(self._log_path)

            # Register this logger so the global proxies will forward messages to it.
            self.register()

    def register(self) -> None:
        """Register this instance with the global print/stderr proxies.

        Registering is automatic when a `log_file_path` is provided in `__init__`.
        Calling `register()` manually will re-register if previously restored.
        """
        if self._is_registered:
            return
        _LOGGER_REGISTRY.append(self)
        self._is_registered = True
        if len(_LOGGER_REGISTRY) == 1:
            builtins.print = _global_print
            sys.stderr = _StdErrProxy()

    def restore(self) -> None:
        """Unregister this logger and restore original `print` and `sys.stderr` when no loggers remain."""
        if not self._is_registered:
            return
        try:
            _LOGGER_REGISTRY.remove(self)
        except ValueError:
            pass
        self._is_registered = False
        if not _LOGGER_REGISTRY:
            builtins.print = _ORIGINAL_PRINT
            sys.stderr = _ORIGINAL_STDERR

    def log(self, message: str) -> None:
        """Write a formatted log entry to the logger's file according to settings."""
        if not self._log_path:
            return

        parts = []
        if self.file_timestamp:
            parts.append(f'[{self._current_timestamp()}]')
        if self.file_message:
            if '\n' in message:
                message = f'\n{message}\n'
            parts.append(message)

        save_message = '  '.join(parts)

        try:
            with open(self._log_path, 'a', encoding='utf-8') as fh:
                fh.write(save_message + '\n')
        except Exception:
            # Don't raise from the logger; write an indicator to original stderr.
            try:
                _ORIGINAL_STDERR.write(f"PocketLogger: failed writing to '{self._log_path}'\n")
            except Exception:
                pass

    def log_raw(self, message: str) -> None:
        """Append raw text to the log file (no formatting)."""
        if not self._log_path:
            return
        try:
            with open(self._log_path, 'a', encoding='utf-8') as fh:
                fh.write(message)
        except Exception:
            try:
                _ORIGINAL_STDERR.write(f"PocketLogger: failed writing raw to '{self._log_path}'\n")
            except Exception:
                pass

    # Internal helpers -----------------------------------------
    def _log_from_print(self, message: str) -> None:
        """Called from the global print proxy to log a print() message."""
        # Use the public `log()` behavior to keep formatting consistent.
        self.log(message)

    def _find_available_log_path(self, path: str) -> str:
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        counter = 1
        while True:
            candidate = f"{base} ({counter}){ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _append_timestamp_to_filename(self, path: str) -> str:
        base, ext = os.path.splitext(path)
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        return f"{base}_{stamp}{ext}"

    def _current_time(self) -> str:
        return datetime.now().strftime('%H:%M:%S')

    def _current_date(self) -> str:
        return datetime.now().strftime('%Y-%m-%d')

    def _current_timestamp(self) -> str:
        return f"{self._current_date()} {self._current_time()}"
