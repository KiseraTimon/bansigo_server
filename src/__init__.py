# src/__init__.py

from fastapi import FastAPI, status, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.exception_handlers import request_validation_exception_handler, http_exception_handler
from fastapi.exceptions import RequestValidationError

from starlette.exceptions import HTTPException as StarletteHTTPException

from pathlib import Path


# path references
path = Path(__file__)
STATIC_DIR = f"{path.resolve().parent}/static"
MEDIA_DIR = f"{path.resolve().parent}/media"
TEMPLATES_DIR = f"{path.resolve().parent}/templates"


# app factory
def create_app() -> FastAPI:
    """
    creates an instance of FastAPI
    :return: FastAPI
    """

    # fastAPI object
    app = FastAPI()


    # mounting
    if Path(STATIC_DIR).is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    if Path(MEDIA_DIR).is_dir():
        app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

    # template object
    if Path(TEMPLATES_DIR).is_dir():
        app.state.templates = Jinja2Templates(directory=TEMPLATES_DIR)


    # routers


    # http exception handler
    @app.exception_handler(StarletteHTTPException)
    async def http_exceptions(request: Request, exception: StarletteHTTPException):
        # exceptions from apis
        if request.url.path.startswith("/api"):
            return await http_exception_handler(request, exception)

        message = (
            exception.detail
            if exception.detail else
            "An error occurred. Please check your request and try again"
        )

        # exceptions from views
        return app.state.templates.TemplateResponse(
            request,
            "errors.html",
            {
                "status_code": exception.status_code,
                "title": exception.status_code,
                "content": message
            },
            status_code=exception.status_code
        )

    # request validation exception handler
    @app.exception_handler(RequestValidationError)
    async def request_validation_exceptions(request: Request, exception: RequestValidationError):
        """
        handles request validation exceptions
        :param request: Request
        :param exception: RequestValidationError
        :return:
        """

        # exceptions from apis
        if request.url.path.startswith("/api"):
            return await request_validation_exception_handler(request, exception)

        # exceptions from views
        return app.state.templates.TemplateResponse(
            request,
            "errors.html",
            {
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "content": "an error occurred; kindly verify the information you sent in is correct"
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )


    # FastAPI instance
    return app
