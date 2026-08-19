# FastAPI

FastAPI를 학습하며 이해한 개념과 직접 재구성한 최소 예제를 정리합니다.

## 학습 주제

- Request와 Response
- Pydantic Schema와 입력값 검증
- CRUD API
- Router·Service·Schema 구조
- 예외 처리
- Swagger UI
- 배포

## 정리 원칙

- 수업 코드를 그대로 보관하지 않습니다.
- 이해한 내용을 작은 예제로 다시 구현합니다.
- 관련 블로그와 실제 프로젝트 코드를 연결합니다.

## 관련 기록

### 🔐 Authentication & Authorization

프론트엔드에서 로그인 여부에 따라 메뉴를 숨기는 것만으로는
백엔드 API가 보호되지 않는다는 점을 실습을 통해 확인했습니다.

API 자체에서 사용자를 확인하기 위해
JWT, Bearer Token, FastAPI `Depends()`를 이용한 인증 흐름을 학습했습니다.

- 📖 [로그인해야 보이는 기능인데, API 주소로는 왜 접근될까?](https://velog.io/@jbbdyee/Auth-%EB%A1%9C%EA%B7%B8%EC%9D%B8%ED%95%B4%EC%95%BC-%EB%B3%B4%EC%9D%B4%EB%8A%94-%EA%B8%B0%EB%8A%A5%EC%9D%B8%EB%8D%B0-API-%EC%A3%BC%EC%86%8C%EB%A1%9C%EB%8A%94-%EC%99%9C-%EC%A0%91%EA%B7%BC%EB%90%A0%EA%B9%8C)
- 💻 [Supabase Auth · JWT · Bearer Token 실습 코드](https://github.com/jbbdyee/aidevs/tree/main/02_supabase-ai-backend/03_supabase-db-and-auth/04_supabase-auth-and-rls)