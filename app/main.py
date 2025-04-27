from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.api import scripts
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.api.scripts import load_scripts
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="PipeCrab",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(scripts.router, prefix="/scripts", tags=["Scripts"])

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    scripts_data = load_scripts()
    return templates.TemplateResponse("dashboard.html", {"request": request, "scripts": scripts_data})

@app.post("/dashboard/start/{script_name}")
async def dashboard_start_script(script_name: str):
    await scripts.start_script(script_name)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/dashboard/stop/{script_name}")
async def dashboard_stop_script(script_name: str):
    await scripts.stop_script(script_name)
    return RedirectResponse(url="/dashboard", status_code=303)
