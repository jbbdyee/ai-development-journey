from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles


# ======================================
# 1. FastAPI 애플리케이션 생성
# ======================================

app = FastAPI()


# ======================================
# 2. 이미지를 저장할 폴더 준비
# ======================================
# uploads 폴더가 없으면 자동으로 생성합니다.

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


# ======================================
# 3. Static Files 연결
# ======================================
# 브라우저가 /uploads/파일이름 주소로 접근하면 uploads 폴더 안의 파일을 보여줄 수 있도록 연결합니다.

app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads"
)


# ======================================
# 4. 이미지 업로드 API
# ======================================
# 이미지를 업로드하면 uploads 폴더에 저장하고 이미지 URL을 반환합니다.

@app.post("/images")
async def upload_image(
    image: UploadFile = File(...)
):

    # 저장될 파일 위치
    file_path = UPLOAD_DIR / image.filename

    # 바이너리(Binary) 형태로 저장
    with open(file_path, "wb") as file:
        file.write(await image.read())

    # 저장된 이미지 주소 반환
    return {
        "filename": image.filename,
        "image_url": f"/uploads/{image.filename}",
    }