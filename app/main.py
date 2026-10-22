from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router as assistant_router
from app.api.voice_call_routes import router as voice_call_router

app = FastAPI(
    title="SARA AI Personal Assistant API",
    description="Backend API for SARA - voice-enabled AI personal assistant",
    version="1.0.0",
)

# CORS Middleware
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if not origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assistant_router)
app.include_router(voice_call_router)


@app.get("/")
def root():
    return {
        "app": "SARA Assistant API",
        "status": "online",
        "docs": "/docs",
    }
