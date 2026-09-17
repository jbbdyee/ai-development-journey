# Docker Compose · EC2 수동 배포

## 학습 목적

- Docker Compose 기반 서비스를 EC2 Ubuntu에서 수동으로 배포한다.
- 로컬 확인용 Compose와 배포용 Compose의 차이를 확인한다.
- EC2에서 이미지를 받고 컨테이너를 기동·확인하는 명령을 직접 실행한다.

## 핵심 파일

| 파일 | 역할 |
| --- | --- |
| `compose.yml` | 로컬에서 `latest` 이미지로 서비스 구성과 healthcheck를 확인하는 예제 |
| `compose.release.yml` | EC2에서 버전이 고정된 Docker Hub 이미지를 `pull`해 실행하는 배포 예제 |
| `env/.env.release.example` | 실제 비밀값 없이 필요한 변수와 예시값만 보여 주는 템플릿 |
| `workflows/compose-validate.yml` | 두 Compose 파일의 변수 치환과 구성 문법을 검증하는 CI 예제 |

`compose.yml`은 학습용으로 변경을 빠르게 확인하는 `latest` 태그를, `compose.release.yml`은 재현 가능한 배포를 위해 `APP_VERSION`으로 고정한 태그를 사용한다. 원본 수업 프로젝트의 소스와 Dockerfile은 포함하지 않았다.

## EC2 수동 배포 흐름

```text
GitHub에서 배포 파일 확인
    ↓
EC2 Ubuntu에 접속해 저장소 clone/pull
    ↓
env/.env.release.example을 .env.release로 복사하고 실제 값 입력
    ↓
docker compose pull → up -d
    ↓
docker compose ps로 컨테이너 상태 확인
```

```bash
cp env/.env.release.example env/.env.release
# env/.env.release의 OPENAI_API_KEY와 POSTGRES_PASSWORD를 실제 값으로 변경
sudo docker compose --env-file env/.env.release -f compose.release.yml pull
sudo docker compose --env-file env/.env.release -f compose.release.yml up -d
sudo docker compose --env-file env/.env.release -f compose.release.yml ps
```

## 트러블슈팅 메모

### EC2 수동 배포 중 Docker Compose가 실행되지 않은 두 가지 원인

> TODO: Velog 글 발행 후 정확한 URL 연결

1. Windows PowerShell에서 쓰던 `.\compose.release.yml` 경로를 Ubuntu에서 그대로 사용해 `no such file or directory`가 발생했다.
2. Linux 경로로 고친 뒤에는 `/var/run/docker.sock permission denied` 오류가 나타났다.
3. 수업에서는 Docker socket 권한 문제를 피해 `sudo docker compose ...`로 배포를 진행했다.
4. 첫 오류를 해결한 뒤 다른 오류가 나타난 것은, 명령이 파일 탐색 단계를 통과해 Docker daemon 접속 단계까지 진행됐다는 단서였다.

비밀값이 든 `env/.env.release`는 커밋하지 않는다.
