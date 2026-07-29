import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import engine, Base
from .config import settings
from .api import auth, moments, anniversaries, upload

app = FastAPI(
    title="恋心记录 LoveDiary",
    description="专为情侣设计的甜蜜记录 API",
    version="1.0.0"
)

# CORS — 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务 — 上传的图片
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(moments.router, prefix="/api/moments", tags=["瞬间"])
app.include_router(anniversaries.router, prefix="/api/anniversaries", tags=["纪念日"])
app.include_router(upload.router, prefix="/api/upload", tags=["上传"])


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}
