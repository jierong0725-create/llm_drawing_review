from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

from .database import engine, Base
from .routers import parts, review

Base.metadata.create_all(bind=engine)

app = FastAPI(title="工程图纸审核系统")

os.makedirs(os.path.join(os.path.dirname(__file__), "static", "drawings"), exist_ok=True)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app.include_router(parts.router)
app.include_router(review.router)
app.include_router(review.api)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return RedirectResponse(url="/parts/")
