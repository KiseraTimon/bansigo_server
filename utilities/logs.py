# utilities/logs.py

"""
Logging for this FastAPI project, built on Python's standard `logging` module.

Storage of logs:

    logs/
    ├── errors/                      ERROR and CRITICAL
    │   ├── services/auth_service.log        <- src/services/auth_service.py
    │   ├── dependencies.log                 <- src/dependencies.py
    │   ├── routers/server/auth.log          <- src/routers/server/auth.py
    │   ├── utilities/mail.log               <- utilities/mail.py
    │   ├── unhandled.log                    <- errors whose origin could not be traced to our code
    │   └── external/sqlalchemy.log          <- third-party libraries, one file each
    └── system/                      INFO and WARNING (same folder layout as errors/)
        └── services/auth_service.log

Usage:

    from utilities import get_logger
    log = get_logger(__name__)            # "src.services.auth_service"
    log.info("user %s registered", user.id)
    log.exception("could not hash password")      # inside `except`: ERROR + traceback

    and `src.services.auth_service` lands in `errors/services/auth_service.log` /
    `system/services/auth_service.log`. (`src.` is dropped; the last name is the file, the names before it are folders.)

Special Notes:

    UNEXPECTED exceptions need no try/except at all: the middleware catches whatever escapes a request, finds the
    innermost frame that belongs to OUR code (the module where it blew up) and logs the traceback under THAT module's
    logger. A crash inside `AuthService.register` therefore appears in errors/services/auth_service.log.
    Expected failures (wrong password -> 401, duplicate email -> 409) are normal answers, not errors, and are not logged as errors.

Every line carries the request id (also returned as the X-Request-ID response header).
"""

import logging
import logging.config
import logging.handlers
import re
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware


# per-request values (visible to every log)
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
request_url_var: ContextVar[str] = ContextVar("request_url", default="-")


"""
routing rules: logger name -> file
    top-level packages that belong to me get a file per module.
    Everything else such as sqlalchemy and uvicorn, is collapsed
    to one file per library under external/
"""
MY_PACKAGES = ("src", "app", "utilities", "config", "main")
PSEUDO_ROOTS = ("src", "app")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]") # safe handling of file names
_IGNORED_ORIGINS = {"utilities.logs"}   # secret origins


MAX_BYTES = 5_000_000
BACKUP_COUNT = 5
MAX_OPEN_FILES = 64


def _clean(part: str) -> str:
    """
    cleans file names before logging
    :param part: str
    :return: str
    """
    return _UNSAFE.sub("_", part).strip("_")


def log_path_for(logger_name: str, base_dir: Path) -> Path:
    """
    logs for a specific path i.e.
    'src.services.auth_service' -> <base>/services/auth_service.log
    'src.dependencies'          -> <base>/dependencies.log
    'utilities.mail'            -> <base>/utilities/mail.log
    'sqlalchemy.engine.Engine'  -> <base>/external/sqlalchemy.log

    :param logger_name: str
    :param base_dir: Path
    :return: Path
    """

    base_dir = Path(base_dir)
    parts = [p for p in logger_name.split(".") if p]

    if not parts or parts[0] not in MY_PACKAGES:
        library = _clean(parts[0]) if parts else ""
        return base_dir / "external" / f"{library or 'unknown'}.log"

    if parts[0] in PSEUDO_ROOTS:
        parts = parts[1:]
    cleaned = [c for c in (_clean(p) for p in parts) if c] or ["general"]
    return base_dir.joinpath(*cleaned[:-1], f"{cleaned[-1]}.log")


def origin_logger_name(exc: BaseException, default: str = "app.unhandled") -> str:
    """
    maps the module where the exception happened
    :param exc: BaseException
    :param default: str
    :return: str
    """

    name = default
    tb = exc.__traceback__
    while tb is not None:
        module = tb.tb_frame.f_globals.get("__name__", "")
        if module.split(".")[0] in MY_PACKAGES and module not in _IGNORED_ORIGINS:
            name = module
        tb = tb.tb_next
    return name


class ModuleFileHandler(logging.Handler):
    """
    a logical handler for module exceptions.
    Lazily creates files, folders and rotations until something is logged
    """

    def __init__(
        self,
        base_dir: str | Path,
        *,
        level: int | str = logging.NOTSET,
        max_bytes: int = MAX_BYTES,
        backup_count: int = BACKUP_COUNT,
        max_open: int = MAX_OPEN_FILES,
    ):
        """
        constructor
        :param base_dir: str | Path
        :param level: int | str
        :param max_bytes: int
        :param backup_count: int
        :param max_open: int
        """

        super().__init__(level)

        self.base_dir = Path(base_dir)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.max_open = max_open

        self._children: OrderedDict[Path, logging.handlers.RotatingFileHandler] = OrderedDict()


    def _child_for(self, path: Path) -> logging.handlers.RotatingFileHandler:
        """
        tracks the parent module
        :param path: Path
        :return: RotatingFileHandler
        """
        child = self._children.get(path)
        if child is not None:
            self._children.move_to_end(path)
            return child

        path.parent.mkdir(parents=True, exist_ok=True)
        child = logging.handlers.RotatingFileHandler(
            path, maxBytes=self.max_bytes, backupCount=self.backup_count, encoding="utf-8", delay=True
        )
        child.setFormatter(self.formatter)
        self._children[path] = child

        if len(self._children) > self.max_open:       # too many open files: close the least recently used
            _, oldest = self._children.popitem(last=False)
            oldest.close()
        return child


    def emit(self, record: logging.LogRecord) -> None:
        """
        :param record: LogRecord
        :return: None
        """
        try:
            self._child_for(log_path_for(record.name, self.base_dir)).handle(record)
        except Exception:
            self.handleError(record)

    def setFormatter(self, fmt) -> None:
        """
        determines the log formatting
        :param fmt: Formatter | None
        :return: None
        """

        super().setFormatter(fmt)
        for child in self._children.values():
            child.setFormatter(fmt)

    def close(self) -> None:
        """
        :return: None
        """

        self.acquire()
        try:
            for child in self._children.values():
                child.close()
            self._children.clear()
        finally:
            self.release()
        super().close()


class RequestContextFilter(logging.Filter):
    """
    Handles ContextVars for each log record
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        retrieves the ContextVars for copying onto each record
        :param record:
        :return: bool
        """
        record.request_id = request_id_var.get()
        record.url = request_url_var.get()
        return True


class BelowLevelFilter(logging.Filter):
    """
    Lets only records below 'below' through
    """

    def __init__(self, below: int = logging.ERROR):
        """
        constructor
        :param below: int
        """

        super().__init__()
        self.below = below

    def filter(self, record: logging.LogRecord) -> bool:
        """
        retrieves log level
        :param record: LogRecord
        :return: bool
        """

        return record.levelno < self.below


class UTCFormatter(logging.Formatter):
    """
    converts time to UTC
    """

    converter = time.gmtime  # timestamps in UTC, matching the database


def setup_logging(settings) -> None:
    """
    idempotent logging setup method
    :param settings:
    :return: None
    """

    console_fmt = "%(asctime)sZ %(levelname)-8s %(name)s [%(request_id)s] %(message)s"
    file_fmt = "%(asctime)sZ %(levelname)-8s %(name)s [%(request_id)s] [%(url)s]\n%(message)s\n"

    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
            "filters": ["context"],
        }
    }

    if settings.log_to_file:
        log_dir = Path(settings.log_dir)
        handlers["errors_by_module"] = {
            "()": ModuleFileHandler,
            "base_dir": str(log_dir / "errors"),
            "level": "ERROR",
            "formatter": "file",
            "filters": ["context"],
        }
        handlers["system_by_module"] = {
            "()": ModuleFileHandler,
            "base_dir": str(log_dir / "system"),
            "level": "INFO",
            "formatter": "file",
            "filters": ["context", "below_error"],
        }

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,  # preserving uvicorn's logging
        "filters": {
            "context": {"()": RequestContextFilter},
            "below_error": {"()": BelowLevelFilter, "below": logging.ERROR},
        },
        "formatters": {
            "console": {"()": UTCFormatter, "format": console_fmt, "datefmt": "%Y-%m-%d %H:%M:%S"},
            "file": {"()": UTCFormatter, "format": file_fmt, "datefmt": "%Y-%m-%d %H:%M:%S"},
        },
        "handlers": handlers,
        "root": {"level": settings.log_level, "handlers": list(handlers)},
    })


def get_logger(name: str) -> logging.Logger:
    """
    calls the logger
    :param name: str
    :return: Logger
    """

    return logging.getLogger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    assigns every request an id, put on every log line.
    Returns it as the X-Request-ID header for users to quote when
    reporting errors
    """

    async def dispatch(self, request, call_next):
        """
        :param request:
        :param call_next:
        :return:
        """

        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        id_token = request_id_var.set(request_id)
        url_token = request_url_var.set(f"{request.method} {request.url.path}")

        try:
            response = await call_next(request)
        except Exception as exc:
            logging.getLogger(origin_logger_name(exc)).error("Unhandled exception", exc_info=exc)
            raise
        finally:
            request_id_var.reset(id_token)
            request_url_var.reset(url_token)

        response.headers["X-Request-ID"] = request_id
        return response


# backward-compatible wrappers
def _name(log: str, path: str) -> str:
    folders = path.replace("\\", ".").replace("/", ".")
    return ".".join(part for part in ("app", folders, log) if part)


def log_critical_error(e: BaseException, log: str = "critical", path: str = "") -> None:
    """
    logs an exception
    :param e: BaseException
    :param log: str
    :param path: str
    :return: None
    """

    logging.getLogger(_name(log, path)).error("%s: %s", type(e).__name__, e, exc_info=e)


def log_system_info(msg: str, log: str = "general", path: str = "") -> None:
    """
    logs system messages
    :param msg: str
    :param log: str
    :param path: str
    :return: None
    """

    logging.getLogger(_name(log, path)).info(msg)
