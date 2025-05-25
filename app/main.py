# main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from app.api import scripts

# Load environment variables
load_dotenv()

# Lifespan handler: autostart enabled scripts
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Autostarting enabled scripts...")
    await scripts.autostart_enabled_scripts()
    yield

# Create FastAPI app
app = FastAPI(
    title="PipeCrab",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Template setup
templates = Jinja2Templates(directory="app/templates")

# Include API routes
app.include_router(scripts.router, prefix="/scripts", tags=["Scripts"])

# Web dashboard routes
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    scripts_data = await scripts.load_scripts()
    return templates.TemplateResponse("dashboard.html", {"request": request, "scripts": scripts_data})

@app.post("/dashboard/start/{script_name}")
async def dashboard_start_script(script_name: str):
    await scripts.start_script(script_name)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/dashboard/stop/{script_name}")
async def dashboard_stop_script(script_name: str):
    await scripts.stop_script(script_name)
    return RedirectResponse(url="/dashboard", status_code=303)
