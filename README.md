# k8s-product-image-pipeline

NHN Cloud 위에 직접 구축한 쿠버네티스 클러스터에서, 상품 이미지 등록 파이프라인을 통해 GitOps 배포와 장애 자동 복구를 검증하는 프로젝트

> 이 앱은 K8s 운영 포트폴리오의 "재료"입니다. 비즈니스 로직의 완성도보다 단순함, 명확한 상태 전이, 실제 부하를 유발할 수 있는 처리 과정을 우선했습니다. 애플리케이션 빌드 스펙 전문은 [`claude_code_build_instructions_260730.md`](./claude_code_build_instructions_260730.md) 참고. 서비스 구조와 다이어그램은 [ARCHITECTURE_v0.1.0.md](./ARCHITECTURE_v0.1.0.md), 테스트 절차와 재현 명령은 [TESTING.md](./TESTING.md) 참고.

## 리포지토리 구조

```
/product-service           # Product Service (FastAPI)
/image-processing-service  # Image Processing Service (RabbitMQ consumer + Pillow)
/web-ui                    # 발표용 Web UI (순수 HTML/CSS/JS)
/migrations                # DB 스키마 마이그레이션 + run_migration.py
/scripts                   # cleanup_temp_images.py (temp/ 정리)
/charts                    # (범위 밖) Helm 차트 - 이후 K8s 배포 단계
/argocd                    # (범위 밖) ArgoCD Application 매니페스트 - 이후 배포 단계
/docs                      # (범위 밖) 아키텍처 다이어그램, 로드맵 문서 보관용
/demo                      # (앱 스펙 범위 밖) 발표용 데모 이미지 생성 + 업로드 스크립트, demo/README.md 참고
```

## 로컬 실행 (docker-compose)

```
docker compose up --build
```

- Product Service: http://localhost:8000
- Web UI: http://localhost:8080
- RabbitMQ 관리 콘솔: http://localhost:15672 (app / app_password)
- MinIO 콘솔: http://localhost:9001 (minioadmin / minioadmin)

`migration` 컨테이너는 `run_migration.py`를 실행하고 종료되는 1회성 컨테이너입니다 (K8s Job을 로컬에서 흉내낸 것).

### ⚠️ 로컬 전용: Object Storage는 MinIO로 대체

실제 배포 환경에서는 `OBJECT_STORAGE_*` 환경변수가 NHN Cloud Object Storage를 가리키지만,
로컬 개발/테스트에서는 S3 호환 오픈소스인 **MinIO**로 대체했습니다 (스펙 8번 항목에는 명시되지
않았으나, 완료 기준 체크리스트의 업로드→처리→active 전환 흐름을 로컬에서 검증하려면 실제로
동작하는 Object Storage가 필요해 추가함 — 사용자 확인 후 반영).

Image Processing Service가 생성하는 이미지 공개 URL은 서비스 간 통신용 내부 호스트명
(`http://minio:9000`)이 아니라 `OBJECT_STORAGE_PUBLIC_URL`(`http://localhost:9000`)을 사용하도록
분리했습니다. 컨테이너 내부(업로드/다운로드)는 `OBJECT_STORAGE_ENDPOINT`로 `minio` 호스트명을
쓰고, 브라우저가 실제로 여는 URL만 호스트에 노출된 포트(`localhost:9000`)를 가리키게 하여
hosts 파일을 건드리지 않고도 구매자 화면에서 썸네일이 정상적으로 보입니다. 실제 NHN Cloud
배포 환경에서는 `OBJECT_STORAGE_ENDPOINT` 자체가 공개 URL이므로 `OBJECT_STORAGE_PUBLIC_URL`은
설정하지 않아도 됩니다 (미설정 시 `OBJECT_STORAGE_ENDPOINT`를 그대로 사용).

### 발표 전 데이터 초기화

개발/테스트하면서 등록한 상품들이 DB에 남아 있으면, 구매자 화면에 실제 발표용 데모 상품과
테스트 쓰레기 데이터가 섞여서 나옵니다 (`products.id`는 `SERIAL`이라 충돌은 나지 않지만,
지저분해 보입니다). 실제 발표 전에는 완전히 깨끗한 상태로 리셋하는 것을 권장합니다.

```
docker compose down -v   # Postgres/MinIO 볼륨까지 전부 삭제
docker compose up --build -d
```

재기동 후 `GET /products`가 빈 배열(`[]`)을 반환하면 초기화가 끝난 것입니다. 이 상태에서
`demo/run_demo.sh`([demo/README.md](./demo/README.md) 참고)를 실행하면 상품 id가 1번부터
새로 시작하고, 데모용 상품만 깨끗하게 보입니다.

컨테이너를 다시 만들 필요 없이 데이터만 비우고 싶다면(예: 발표 리허설을 여러 번 반복할 때)
더 가벼운 방법도 있습니다:

```
bash demo/reset_demo_data.sh
```

Postgres 테이블만 `TRUNCATE ... RESTART IDENTITY`하고 Redis 캐시·MinIO에 쌓인 이미지를 지우는
스크립트로, 스택 재기동 없이 몇 초 안에 끝납니다 (자세한 내용은 [demo/README.md](./demo/README.md)).

## Web UI 데모 강화 기능

스펙 14번 항목 최소 요구사항 위에, 발표 효과를 위해 아래 기능을 추가했습니다.

- **이미지 확대 모달**: 구매자 화면에서 카드를 클릭하면 모달이 뜨고, 상단 탭(썸네일/상세/확대)으로
  3가지 리사이징 사이즈를 전환해볼 수 있습니다. 사이즈를 바꿀 때마다 실제 픽셀 크기
  (`naturalWidth`/`naturalHeight`)와 실제 파일 용량(HTTP `Content-Length`)을 함께 보여줘서, Image
  Processing Service가 실제로 리사이징했다는 근거를 발표 중 바로 확인할 수 있습니다.
- **상품 설명 표시**: 구매자 카드에 등록 시 입력한 설명을 2줄까지 표시합니다 (넘치면 말줄임).
- **반려 사유 표시**: 판매자 목록에서 `rejected` 상품은 배지 아래에 반려 사유를 텍스트로 바로
  보여줍니다 (hover 툴팁이 아니라 항상 보이는 텍스트라 발표 중 놓치지 않습니다).
- **처리 중 배지 펄스 애니메이션**: `processing` 배지가 1.4초 주기로 은은하게 깜빡여, 지금 무엇이
  처리되고 있는지 목록에서 더 잘 드러납니다.
- **판매자 목록은 서버에서 직접 조회**: 브라우저 세션에 등록 이력을 들고 있지 않고,
  `GET /products?status=all`(아래 "API 추가 사항" 참고)을 2.5초마다 폴링해서 그립니다. 이
  브라우저의 폼으로 등록했든 `demo/run_demo.sh` 같은 외부 스크립트로 등록했든 전부 목록에
  나타납니다.

### API 추가 사항 (스펙 대비)

스펙 7번 항목에 정의된 API에 더해, 발표용 Web UI를 위해 아래를 추가했습니다. 기존 엔드포인트의
기본 동작은 전혀 바뀌지 않았습니다.

- `GET /products?status=all` — 상태(`draft`/`processing`/`active`/`rejected`) 무관하게 모든
  상품을 최신 등록순으로 반환합니다. 판매자 화면이 등록 경로와 무관하게 상태 전이를 실시간으로
  보여주려면 전체 상품 목록 조회가 필요해서 추가했습니다. 캐싱하지 않으며, 파라미터를 생략하면
  (`GET /products`) 기존과 동일하게 `active` 상품만 반환하고 Redis 캐시도 그대로 사용합니다
  (스펙 4번 항목 요구사항에 영향 없음).

## ⚠️ 빌드 시 주의사항 (Dockerfile)

- **빌드 컨텍스트는 리포지토리 루트여야 합니다.** `product-service/Dockerfile`은 `run_migration.py`
  실행을 위해 `/migrations`를, `image-processing-service/Dockerfile`은 `cleanup_temp_images.py`
  실행을 위해 `/scripts`를 함께 이미지에 담습니다. 예:
  ```
  docker build -f product-service/Dockerfile -t product-service:latest .
  docker build -f image-processing-service/Dockerfile -t image-processing-service:latest .
  docker build -f web-ui/Dockerfile -t web-ui:latest ./web-ui
  ```
- **타겟 아키텍처 주의**: NHN Cloud 인스턴스는 x86_64(amd64) 기준입니다. Apple Silicon(M1/M2/M3,
  arm64) 노트북 등에서 빌드할 경우 반드시 플랫폼을 명시해야 합니다. 그렇지 않으면 클러스터에서
  `exec format error`로 컨테이너 실행 자체가 되지 않습니다.
  ```
  docker build --platform linux/amd64 -f product-service/Dockerfile -t product-service:latest .
  ```

## 환경변수

| 변수명                      | 설명                                | 사용 서비스                              |
| --------------------------- | ----------------------------------- | ----------------------------------------- |
| `DATABASE_URL`              | PostgreSQL 연결 문자열              | Product Service, Image Processing Service |
| `REDIS_URL`                 | Redis 연결 문자열                   | Product Service                           |
| `RABBITMQ_URL`              | RabbitMQ 연결 문자열                | Product Service, Image Processing Service |
| `OBJECT_STORAGE_ENDPOINT`   | NHN Cloud Object Storage 엔드포인트 | Product Service, Image Processing Service |
| `OBJECT_STORAGE_ACCESS_KEY` | 접근 키                             | Product Service, Image Processing Service |
| `OBJECT_STORAGE_SECRET_KEY` | 시크릿 키                           | Product Service, Image Processing Service |
| `OBJECT_STORAGE_BUCKET`     | 버킷 이름                           | Product Service, Image Processing Service |

모든 값은 코드에 하드코딩되어 있지 않으며 환경변수로만 주입됩니다 (추후 K8s Secret/OpenBao 연동 예정).

## 알려진 기술 부채 및 향후 확장 방향

현재 Product Service와 Image Processing Service는 PostgreSQL을 공유하고 있어 완전한 서비스
독립성이 확보되지 않았습니다 (분산 모놀리스에 가까운 상태). 이는 1주일이라는 프로젝트 기간
제약 속에서 서비스 경계(코드/배포 단위) 분리를 우선하고, 데이터 분리는 다음 단계 과제로 남긴
의도적인 선택입니다. 향후 계획은 Image Processing Service 전용 DB를 분리하고, 처리 완료 시
이벤트(`{ event: "image_processed", product_id, result, reason }`)를 발행해 Product Service가
이를 구독하여 자신의 DB 상태를 갱신하는 Choreography 패턴으로 전환하는 것입니다.

이 마이그레이션을 쉽게 하기 위해 지금부터 지키고 있는 원칙:

- Image Processing Service가 `products` 상태를 변경하는 코드는 `db.py`의
  `update_product_status(product_id, status, reason=None)` 함수 하나로만 캡슐화되어 있습니다.
  나중에 이 함수 내부만 이벤트 발행으로 교체하면 됩니다.
- 각 서비스 `models.py` 상단에 테이블 소유권을 주석으로 명시했습니다 (`products`는 Product
  Service 소유, `product_images`는 Image Processing Service 소유).
- Product Service는 `product_images` 테이블에 쓰기 작업을 하지 않고, 상세/목록 조회 시
  읽기(JOIN)만 수행합니다.
- `image-processing-service/processor.py`의 룰 기반 검수 통과 직후 지점에, 향후 비전 LLM API를
  붙일 수 있는 위치를 TODO 주석으로 표시해뒀습니다 (스펙 13번 항목에 따라 실제 호출 구현은 하지
  않음 — 연동 지점만 표시).

## 완료 기준 검증 결과

`docker compose up --build`로 실제 스택을 띄우고 아래 항목을 직접 검증했습니다 (2026-07-31,
이후 기능 추가분에 대한 재검증 포함). 실행 명령과 재현 절차는 [TESTING.md](./TESTING.md)에
더 자세히 정리되어 있습니다.

| # | 항목 | 결과 |
|---|------|------|
| 1 | `docker-compose up`으로 전체(Product/Image Processing/DB/Redis/RabbitMQ/MinIO/Web UI) 기동 | ✅ PASS |
| 2 | 이미지 업로드 후 `GET /products/{id}`가 `active`로 전환 | ✅ PASS — 1200x1200, ~10.5MB 이미지 모두 정상 전환, 3종 리사이징 URL 생성 확인 |
| 3 | 저해상도 이미지 업로드 시 `rejected` | ✅ PASS — 100x100 이미지 → `rejection_reason`에 미달 사유 기록됨 |
| 4 | `GET /products`가 `active` 상품만 반환 | ✅ PASS — draft/processing/rejected 상품은 제외됨 |
| 5 | 20MB 초과 `413`, 15MB 이하 정상 처리 | ✅ PASS — 21MB → 413, ~10.5MB → 202 후 active |
| 6 | 처리 완료(active/rejected 무관) 후 `temp/` 원본 삭제 | ✅ PASS — MinIO `temp/` 접두사가 두 케이스 모두에서 비워짐 확인 |
| 7 | Image Processing Service 강제 종료 시 처리 중이던 메시지 재큐잉 | ✅ PASS — `SIGKILL` 후 RabbitMQ가 unacked 메시지를 자동으로 `ready` 상태로 되돌림, 재기동 후 정상 처리됨 |
| 8 | DB를 내렸다 올렸을 때 크래시 없이 재연결 | ✅ PASS — Postgres 중지 중에도 두 서비스 모두 크래시하지 않음, 재기동 후 대기 중이던 요청/메시지가 자동 처리됨 |
| 9 | `run_migration.py` 재실행 안전성 | ✅ PASS — 동일 스키마로 2회 연속 실행, 에러 없이 종료 |
| 10 | `cleanup_temp_images.py`가 24시간 이상 지난 파일만 삭제 | ✅ PASS — 기본 24시간 기준으로 최근 파일은 보존됨을 확인했고, cutoff 값을 임시로 낮춰 재실행한 별도 검증으로 "기준 초과 시 실제 삭제"까지 확인 (LastModified 비교 및 실제 delete_object 호출 검증) |
| 11 | Web UI 폴링으로 `draft → processing → active` 실시간 갱신 | ✅ PASS — 사용자가 실제 브라우저(`http://localhost:8080`)에서 확인. `demo/run_demo.sh`로 재현 시 판매자 목록 배지가 큐 처리 순서대로 실시간으로 바뀜 |
| 12 | 상태별 배지 색상 / 로딩 상태 / 성공 토스트 | ✅ PASS — 사용자가 실제 브라우저에서 확인. 추가로 반려 사유 텍스트 표시, `processing` 배지 펄스 애니메이션까지 반영 |
| 13 | 구매자 화면에서 `active` 상품만 카드로 표시 | ✅ PASS — 사용자가 실제 브라우저에서 확인 (진행 중 MinIO 내부 호스트명 문제로 썸네일이 깨졌던 것을 발견해 `OBJECT_STORAGE_PUBLIC_URL` 분리로 수정) |
| 14 | Product Service 코드 어디에도 `product_images` 쓰기 없음 | ✅ PASS — `grep`으로 `product-service/` 전체를 검사해 INSERT/UPDATE가 없음을 확인 (읽기 SELECT만 존재) |
| 15 | README에 "알려진 기술 부채" 섹션 포함 | ✅ PASS — 본 문서의 "알려진 기술 부채 및 향후 확장 방향" 섹션 |

### 검증 중 발견해 수정한 버그

- **`/health`가 DB 장애 시 최대 6분까지 응답을 블로킹하는 문제**: Postgres를 내린 뒤 `/health`를
  호출했더니 응답이 없어 조사한 결과, DB 접근 캡슐화 모듈(`db.py`)의 재연결 재시도(최대 10회,
  백오프 최대 60초)가 헬스체크 경로에도 그대로 적용되고 있었습니다. K8s Liveness/Readiness
  Probe는 빠른 실패가 필요하므로, `product-service/db.py`와 `product-service/cache.py`의
  `health_check()`를 재시도 로직과 분리해 짧은 타임아웃(2초)으로 1회만 확인하도록 수정했습니다.
  일반 요청 경로(상품 등록/조회)의 재연결 재시도 로직은 스펙 의도대로 그대로 유지했습니다.
- **동시 요청 중 하나가 블로킹되면 서버 전체가 멈추는 문제**: 위 수정 후에도, Web UI가
  폴링하는 `GET /products?status=all` 요청이 DB 재연결 재시도에 걸리는 동안 `/health`를
  포함한 다른 모든 요청까지 같이 멈추는 걸 재발견했습니다. 원인은 `main.py`의 `async def`
  라우트 핸들러 안에서 동기(blocking) DB/Redis/RabbitMQ 호출을 `await` 없이 직접 실행해,
  블로킹되는 동안 uvicorn의 단일 이벤트 루프 자체가 멈춰버린 것이었습니다.
  `create_product`는 내부 블로킹 호출을 `starlette.concurrency.run_in_threadpool`로 감싸고,
  `list_products`/`get_product`/`health`는 일반 `def`로 바꿔(FastAPI가 자동으로 스레드풀에서
  실행) 해결했습니다. 재현/검증 절차는 [TESTING.md](./TESTING.md#5-2-동시-요청이-하나라도-블로킹되면-전체-이벤트-루프가-멈추는-문제-2차-발견) 참고.
