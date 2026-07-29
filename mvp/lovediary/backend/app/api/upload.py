import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from ..auth import get_current_user
from ..models.user import User
from ..config import settings
from ..crud.moment import moment as crud_moment
from sqlalchemy.orm import Session
from ..database import get_db

router = APIRouter()

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("")
async def upload_image(
    file: UploadFile = File(...),
    moment_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

    # Generate unique filename
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

    # Save file
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10MB 限制")

    with open(filepath, "wb") as f:
        f.write(content)

    image_url = f"/uploads/{filename}"

    # If moment_id is provided, attach image to the moment
    if moment_id is not None:
        moment = crud_moment.get(db, id=moment_id)
        if not moment or moment.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="瞬间不存在或无权操作")
        crud_moment.update(db, db_obj=moment, obj_in={"image_url": image_url})

    return {"image_url": image_url, "filename": filename}
