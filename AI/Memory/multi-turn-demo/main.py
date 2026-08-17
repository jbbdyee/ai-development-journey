import os

from dotenv import load_dotenv
from google import genai


# ==========================================
# 1. 환경변수와 Gemini 클라이언트 설정
# ==========================================

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# ==========================================
# 2. 이전 대화 없이 질문
# ==========================================

question = "내가 좋아하는 과일이 뭐라고 했지?"

without_history = client.models.generate_content(
    model="gemini-3.1-flash-lite",
    contents=question,
)

print("=== History 없음 ===")
print(without_history.text)


# ==========================================
# 3. 이전 대화를 포함해서 질문
# ==========================================

conversation = """
이전 대화:
사용자: 내가 좋아하는 과일은 복숭아야.
AI: 알겠습니다.

현재 질문:
사용자: 내가 좋아하는 과일이 뭐라고 했지?
"""

with_history = client.models.generate_content(
    model="gemini-3.1-flash-lite",
    contents=conversation,
)

print("\n=== History 있음 ===")
print(with_history.text)