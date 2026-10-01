# utilities/logs.py

"""
logging for the fastAPI project

usage:
    from utilities import get_logger
    log = get_logger(__name__)
    log.info("order %s created", order.id)  # note: %s args are not f-strings
    log.exception("payment failed")         # use inside except blocks to capture the traceback
"""

import logging
import logging.config
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware


# per-request values; visible to every log line emitted while handling the request
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
request_url_var: ContextVar[str] = ContextVar("request_url", default="-")


class RequestContextFilter(logging.Filter):
    """
    copies ContextVars onto each record for the format string to use
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        captures ContextVars
        :param record: LogRecord
        :return: bool
        """

        record.request_id = request_id_var.get()
        record.url = request_url_var.get()

        return True


class UTCFormatter(logging.Formatter):
    """
    calls for a  UTC timestamp
    """
    converter = time.gmtime


def setup_logging(settings) -> None:
    """
    idempotent call to set up logging
    :param settings:
    :return: None
    """

    console_fmt = "%(asctime)sZ %(levelname)-8s %(name)s [%(request_id)s] %(message)s"
    file_fmt = "%(asctime)sZ %(levelname)-8s %(name)s [%(request_id)s] [%(url)s]\n%(message)s\n"

    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
            "filters": ["context"]
        }
    }

    if settings.log_to_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        rotating = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "file",
            "filters": ["context"],
            "maxBytes": 5_000_000,
            "backupCount": 5,
            "encoding": "utf-8"
        }

        handlers["app_file"] = {**rotating, "filename": str(settings.log_dir / "app_log"), "level": "INFO"}
        handlers["error_file"] = {**rotating, "filename": str(settings.log_dir / "error_log"), "level": "ERROR"}

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,   # false to prevent switching off uvicorn loggers
        "filters": {"context": {"()": RequestContextFilter}},
        "formatters": {
            "console": {"()": UTCFormatter, "format": console_fmt, "datefmt": "%Y-%m-%d %H:%M:%S"},
            "file": {"()": UTCFormatter, "format": file_fmt, "datefmt": "%Y-%m-%d %H:%M:%S"}
        },
        "handlers": handlers,
        "root": {"level": settings.log_level, "handlers": list(handlers)}
    })


def get_logger(name: str) -> logging.Logger:
    """
    retrieves the logger
    :param name: ste
    :return: Logger
    """

    return logging.getLogger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    gives every request an id, which is put on every log line
    """

    async def dispatch(self, request, call_next):
        """
        returns the X-Request-ID header; quotable when reporting a problem
        :param request: Request[state]
        :param call_next:
        :return: Response
        """

        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        id_token = request_id_var.set(request_id)
        url_token = request_url_var.set(f"{request.method} {request.url.path}")

        try:
            response = await call_next(request)

        except Exception as exc:
            logging.getLogger("app.unhandled").error("Unhandled exception", exc_info=exc)
            raise

        finally:
            request_id_var.reset(id_token)
            request_url_var.reset(url_token)

        response.headers["X-Request-ID"] = request_id
        return response


# backward-compatible wrappers
def _name(log: str, path: str) -> str:
    """
    resolves the name of the log file
    :param log: str
    :param path: str
    :return: str
    """
    return ".".join(part for part in (path, log) if part)


def log_critical_error(e: BaseException, log: str = "critical", path: str = "") -> None:
    """
    deprecated method to log exceptions
    :param e: BaseException
    :param log: str
    :param path: str
    :return: None
    """
    logging.getLogger(_name(log, path)).error("%s: %s", type(e).__name__, e, exc_info=e)


def log_system_info(msg: str, log: str = "general", path: str = "") -> None:
    """
    deprecated method to log console messages
    :param msg: str
    :param log: str
    :param path: str
    :return: None
    """
    logging.getLogger(_name(log, path)).info(msg)
