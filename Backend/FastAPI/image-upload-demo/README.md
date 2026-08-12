# Image Upload Demo

이미지 업로드 기능을 구현하면서 학습한 내용 중  
**이미지 파일 저장과 URL 접근 과정을 분리하여 확인하기 위한 최소 예제**입니다.

실제 프로젝트에서는 이미지 관련 정보를 데이터베이스에 저장하여 조회했지만,
이 예제에서는 핵심 동작을 확인하기 위해 데이터베이스 연결은 제외했습니다.

## 🔌 API

### 이미지 업로드

`POST /images`

이미지 파일을 업로드하면 `uploads` 폴더에 저장하고,
브라우저에서 접근할 수 있는 이미지 경로를 반환합니다.

예시 응답:

```json
{
  "filename": "sample.png",
  "image_url": "/uploads/sample.png"
}
```


## 실행 방법
```
python -m pip install -r requirements.txt  
python -m uvicorn backend:app --reload

Swagger http://127.0.0.1:8000/docs
```

## 실행 결과

- Swagger에서 이미지 업로드 성공
- uploads 폴더 자동 생성 확인
- 반환된 URL로 이미지 조회 성공

![이미지 조회 결과](./result.png)