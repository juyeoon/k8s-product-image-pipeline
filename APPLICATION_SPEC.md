# 애플리케이션 스펙 (As-Built)

> 이 문서는 현재 코드 기준으로 이 애플리케이션이 실제로 무엇을 하고, 어떤 계약(API/상태/재시도
> 규칙)을 지키는지를 정리한 스펙입니다. 최초 빌드 지침서(`claude_code_build_instructions_260730.md`,
> 리포지토리 범위 밖)는 구현 *전* 요구사항이었고, 이후 구현 과정에서 추가/보강된 부분(런타임
> RabbitMQ 재연결, heartbeat 파일, `status=all` 조회, Web UI 강화 등)이 있어 지금은 이 문서가
> 최신 기준입니다. 실행 방법/환경변수/검증 결과는 [README.md](./README.md), 서비스 토폴로지와
> 다이어그램은 [ARCHITECTURE.md](./ARCHITECTURE.md), 재현 절차는 [TESTING.md](./TESTING.md)를
> 참고하세요.

---

## 1. 개요

이커머스 판매자가 상품 정보와 이미지를 등록하면, 시스템이 이미지를 비동기로 검수(룰 기반)하고
3가지 사이즈로 가공한 뒤, 검수를 통과한 상품만 구매자에게 노출합니다.

- **아키텍처 스타일**: MSA-lite. Product Service와 Image Processing Service 2개로 코드/배포
  단위(Docker 이미지)는 분리하되, PostgreSQL은 당분간 공유합니다 (§10 알려진 기술 부채).
- **판매자 관점**: 상품 등록 → 즉시 `202 Accepted` 응답 → 백그라운드 처리 → 폴링으로 상태 확인
- **구매자 관점**: `active` 상태 상품만 조회 가능 (Redis 캐싱)
- **설계 의도**: 이미지 검수 + 3종 리사이징은 실제 CPU/메모리 부하를 유발하는 무거운 작업이므로,
  요청-응답 경로에서 분리해 비동기(RabbitMQ 큐)로 처리한다.

이 앱은 K8s 운영 실습(장애 주입, HPA, GitOps)을 위한 "재료"입니다. 비즈니스 로직의 완성도보다
단순함, 명확한 상태 전이, 실제 부하를 유발하는 처리 과정을 우선합니다.

---

## 2. 서비스 구성

| 서비스 | 책임 | 비고 |
|---|---|---|
| **Product Service** | 상품 등록(`draft` 생성), 원본 이미지 업로드, 큐 발행, 목록/상세 조회, `active` 목록 캐싱 | FastAPI. `product_images` 테이블은 읽기(JOIN)만 수행, 쓰기 금지 |
| **Image Processing Service** | 큐 소비(manual ack), 룰 기반 검수, Pillow 리사이징 3종, Object Storage 업로드, `products` 상태 갱신 | HTTP 서버 없음 — RabbitMQ 컨슈머 루프 단일 프로세스 |
| **Web UI** | 판매자/구매자 화면, 등록 폼, 상태 폴링 | 순수 HTML/CSS/JS, nginx로 정적 서빙, 빌드 도구 없음 |

기술 스택 버전, 인프라 이미지(Postgres/Redis/RabbitMQ/MinIO) 목록은 [ARCHITECTURE.md](./ARCHITECTURE.md#기술-스택)에 정리되어 있습니다.

두 서비스는 **별도 Docker 이미지**로 빌드합니다. K8s에서 독립적으로 배포/스케일링/장애
실험(Pod Kill, OOMKilled, HPA 등) 대상이 되어야 하기 때문입니다.

---

## 3. 상태(Status) 정의

| 상태 | 의미 |
|---|---|
| `draft` | 등록 직후, 큐 처리 대기 중 |
| `processing` | Image Processing Service가 검수/리사이징 처리 중 |
| `active` | 검수 통과, 구매자에게 노출 |
| `rejected` | 검수 실패, 구매자에게 비노출 (`rejection_reason`에 사유 기록) |

상태 전이는 **`draft → processing → (active | rejected)`** 순으로만 발생하며 역행하지
않습니다. 상태를 바꾸는 코드 경로는 오직 `image-processing-service/db.py`의
`update_product_status(product_id, status, reason=None)` 하나뿐입니다.

---

## 4. DB 스키마 및 테이블 소유권

```sql
-- Product Service 소유
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price INTEGER NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft/processing/active/rejected
    rejection_reason TEXT,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

-- Image Processing Service 소유
CREATE TABLE IF NOT EXISTS product_images (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    size_type VARCHAR(20) NOT NULL, -- thumbnail / detail / zoom
    url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);
```

| 테이블 | 소유 서비스 | 쓰기 권한 |
|---|---|---|
| `products` | Product Service | Product Service: INSERT O. Image Processing Service: `update_product_status()` 통해서만 UPDATE O, 그 외 직접 UPDATE 금지 |
| `product_images` | Image Processing Service | Image Processing Service: INSERT O. Product Service: 읽기(JOIN)만, 쓰기 금지 |

이 캡슐화는 향후 서비스별 DB 분리 + 이벤트 기반(Choreography) 전환을 대비한 의도적 설계입니다
(§10).

---

## 5. API 스펙 (Product Service)

Base path는 실제 배포 시 Ingress가 라우팅하며, 로컬에서는 `http://localhost:8000`으로 직접
호출합니다.

### `POST /products`

- **요청**: `multipart/form-data` — `name`(str), `price`(int), `description`(str, 선택),
  `image`(file)
- **검증**:
  - `image.content_type`이 `image/jpeg` 또는 `image/png`가 아니면 `400`
  - 업로드 바이트 수가 **20MB 초과** 시 `413 Payload Too Large`
- **처리 순서**:
  1. `products`에 `status=draft`로 INSERT
  2. 원본 이미지를 Object Storage `temp/{uuid}_original.{ext}`에 업로드 (로컬 디스크에 저장하지
     않음 — 두 서비스가 서로 다른 Pod이므로 파일시스템 공유 불가)
  3. RabbitMQ `image_processing` 큐에 `{ "product_id": <id>, "temp_image_key": "temp/..." }` 발행
- **응답**: `202 Accepted`, `{ "product_id": <id>, "status": "draft" }`

### `GET /products`

- **기본 동작(파라미터 없음)**: `status=active`인 상품만 반환. Redis에 30초 TTL로 캐싱
  (`products:active` 키). 응답 필드: `id`, `name`, `price`, `description`, `thumbnail_url`
- **`?status=all`** *(발표용 Web UI를 위한 확장, 캐싱하지 않음)*: 상태 무관하게 모든 상품을
  최신 등록순으로 반환. 응답 필드: `id`, `name`, `price`, `status`, `rejection_reason`. 등록
  경로(브라우저 폼 / 외부 스크립트)와 무관하게 판매자 화면이 상태 전이를 실시간으로 보여주기
  위해 추가되었으며, 파라미터 생략 시 기존 동작·캐시에는 영향을 주지 않습니다.

### `GET /products/{id}`

- **응답**: 상품 상세 (`id`, `name`, `price`, `description`, `status`, `rejection_reason`,
  `created_at`, `updated_at`) + `images`(size_type/url 배열, `product_images` JOIN 결과)
- 존재하지 않는 `id`는 `404`

### `GET /health`

- DB, Redis 연결 상태를 각각 **짧은 타임아웃(2초) 1회 확인**으로 체크 (재시도/백오프 없음 —
  일반 요청 경로의 재연결 로직을 그대로 쓰면 장애 시 최대 수 분간 Probe 응답이 막히기 때문에
  분리했습니다)
- 둘 다 정상이면 `200 { "status": "ok" }`, 하나라도 실패하면
  `503 { "status": "unhealthy", "db": bool, "redis": bool }`

> Image Processing Service는 HTTP 서버가 없어 `/health`가 없습니다. 대신 파일 기반
> heartbeat(`/tmp/healthy`, §7)로 연결 상태를 노출합니다.

---

## 6. Image Processing Service 처리 로직

```
1. RabbitMQ에서 메시지 수신 (manual ack, prefetch_count=1)
2. update_product_status(product_id, "processing")
3. temp_image_key로 Object Storage에서 원본 다운로드
4. 룰 기반 검수 (processor.inspect_image):
   - Pillow로 열 수 없으면 반려
   - format이 JPEG/PNG가 아니면 반려
   - 가로/세로 중 하나라도 500px 미만이면 반려
5. 검수 통과 시:
   - RGB 변환 후 thumbnail(200px) / detail(800px) / zoom(1600px)로 리사이징
     (Image.LANCZOS, 긴 변 기준 thumbnail 방식, JPEG quality=85)
   - 파일명은 UUID로 생성: products/{product_id}/{uuid}_{size_type}.jpg
   - 각각 Object Storage에 ACL=public-read로 업로드 (Presigned URL 아님 — 상품 이미지는
     구매자 전체 공개가 목적이므로 서명 불필요)
   - product_images에 3행 INSERT (공개 URL 그대로 저장)
   - update_product_status(product_id, "active")
6. 검수 실패 시: update_product_status(product_id, "rejected", reason=<실패 사유>)
7. 5/6 어느 경로든 처리 완료 후 temp/ 원본 삭제 (삭제 실패는 처리 결과를 막지 않고 로그만 남김
   — scripts/cleanup_temp_images.py가 뒤늦게 정리)
8. ack (실패 시 §8 재시도/DLQ 로직으로 이동, 원본은 삭제하지 않음)
```

### 검수 기준 / 리사이징 스펙 상수 (`image-processing-service/models.py`)

| 항목 | 값 |
|---|---|
| 지원 포맷 | JPEG, PNG |
| 최소 해상도 | 가로/세로 각 500px |
| thumbnail | 200px |
| detail | 800px |
| zoom | 1600px |

> **범위 제외 (명시)**: 비전 LLM 기반 콘텐츠 검수는 이번 스펙 범위에 포함하지 않습니다. 룰 기반
> 검수 통과 직후 지점(`processor.inspect_image` 내부)에 연동 지점만 TODO 주석으로 표시되어
> 있으며, 실제 호출은 구현하지 않습니다.

---

## 7. 메시지 재시도 / DLQ / 장애 복구

### 7-1. 처리 실패 재시도 (Image Processing Service)

- manual ack 모드. RabbitMQ 자체 재전송이 아니라 **메시지 헤더 `x-retry-count`를 직접 증가시켜
  같은 큐(`image_processing`)에 재발행**하는 방식으로 최대 **3회**까지 재시도합니다.
- 3회 초과 시 `image_processing.dlq`로 발행합니다.
- 재시도/DLQ 이동 모두 원본 메시지는 즉시 `ack` 처리합니다(재발행이 새 메시지 역할을 함).
- 프로세스가 `SIGKILL` 등으로 강제 종료되어 ack 전에 죽으면, 위 로직과 무관하게 RabbitMQ가
  연결 끊김을 감지해 unacked 메시지를 자동으로 재큐잉합니다.

### 7-2. 정상 종료(SIGTERM/SIGINT)

- 현재 처리 중인 메시지를 마무리한 뒤 `channel.stop_consuming()`으로 새 메시지 소비를 멈추고
  종료합니다. 재연결 루프(7-4)로 돌아가지 않고 그대로 프로세스가 끝납니다.

### 7-3. DB / Redis / RabbitMQ 연결 재시도

두 서비스 모두 아래 원칙을 기동 시점과 **실행 중** 모두에 적용합니다 (Init Container로
"대기"만 시키는 방식은 채택하지 않음 — 실행 중 재연결 상황에 대응할 수 없기 때문).

| 대상 | 최초 연결(기동) | 쿼리/발행 중 끊김 |
|---|---|---|
| PostgreSQL (`db.py`, 양쪽 서비스) | 지수 백오프 2s→4s→...→최대 60s, 최대 10회 재시도 후 실패 시 raise | 쿼리 실패(`OperationalError`/`InterfaceError`) 시 재연결 후 1회 재시도 |
| Redis (`cache.py`, Product Service) | 동일 백오프/횟수 | get/set 실패 시 클라이언트를 버리고 다음 호출에서 재연결, 실패해도 요청은 캐시 미스로 처리(장애를 사용자에게 전파하지 않음) |
| RabbitMQ 발행 (`queue_publisher.py`, Product Service) | 동일 백오프/횟수 | 발행 실패 시 재연결 후 1회 재시도, 재실패 시 예외 발생 |
| RabbitMQ 소비 (`queue_consumer.py`, Image Processing Service) | 동일 백오프/횟수 | 컨슘 중 연결이 끊기면(`AMQPConnectionError`/`OSError`) 프로세스를 죽이지 않고 `main()`의 `while not shutdown_requested:` 루프가 `connect_with_retry()`를 재호출해 재연결 후 컨슘 재개 |

`GET /health`는 위 재시도 로직을 타지 않고 짧은 타임아웃(2초) 1회 확인만 수행합니다(§5) —
Probe 응답이 장애 상황에서 수 분간 블로킹되는 것을 방지하기 위함입니다.

### 7-4. Image Processing Service 헬스 노출 (파일 기반 heartbeat)

Image Processing Service는 HTTP 서버가 없어 K8s Liveness/Readiness Probe용 HTTP 엔드포인트가
없습니다. 대신:

- `RABBITMQ_HEALTH_FILE`(기본 `/tmp/healthy`)을 RabbitMQ 연결 성공 직후, 그리고 컨슘 루프가
  살아있는 동안(메시지 처리마다 + 유휴 시 30초 주기로) touch합니다.
- 재연결 재시도가 반복되는 동안은 touch되지 않으므로, `exec` probe에서
  `find /tmp/healthy -mmin -1` 같은 명령으로 mtime 신선도를 확인하면 연결 상태를 판단할 수
  있습니다. (Probe 매니페스트 자체는 K8s 배포 단계 범위)

### 7-5. 실제 부하 특성

- 이미지 처리는 실제 Pillow 리사이징 연산을 사용 — 인위적인 CPU burn 코드 없이 실제 CPU 부하
  발생 (HPA 시나리오에서 사용)
- 메모리 사용량은 이미지 크기에 자연스럽게 비례 (OOMKilled 시나리오에서 큰 이미지 업로드로
  재현 가능, 인위적인 memory-leak 코드 없음)

---

## 8. 운영 스크립트 (K8s Job/CronJob 대상)

두 스크립트는 각각 기존 서비스 이미지를 재사용하고 실행 커맨드만 다르게 지정합니다 (별도
Dockerfile 불필요).

### 8-1. `migrations/run_migration.py`

- `DATABASE_URL`로 접속해 `001_init_schema.sql`(`CREATE TABLE IF NOT EXISTS`) 실행
- 재실행해도 안전 (K8s Job으로 배포마다 실행 가능)

### 8-2. `scripts/cleanup_temp_images.py`

- Object Storage `temp/` 경로를 스캔해 `LastModified`가 24시간 이상 지난 객체만 `delete_object`
- 1회 스캔 후 종료하는 일회성 실행 (지속 프로세스 아님 — CronJob에 적합)
- DLQ로 이동한 메시지는 `temp/` 원본이 정리되지 않으므로(§7-1), 이 스크립트가 그 잔여 파일까지
  함께 정리하는 안전망 역할을 합니다.

---

## 9. 환경변수

| 변수명 | 설명 | 사용 서비스 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | Product, Image Processing |
| `REDIS_URL` | Redis 연결 문자열 | Product |
| `RABBITMQ_URL` | RabbitMQ 연결 문자열 | Product, Image Processing |
| `OBJECT_STORAGE_ENDPOINT` | Object Storage 엔드포인트 | Product, Image Processing |
| `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` | 접근 자격증명 | Product, Image Processing |
| `OBJECT_STORAGE_BUCKET` | 버킷 이름 | Product, Image Processing |
| `OBJECT_STORAGE_PUBLIC_URL` | 브라우저가 접근하는 공개 이미지 URL (로컬 전용, 미설정 시 `OBJECT_STORAGE_ENDPOINT` 사용) | Image Processing |
| `OBJECT_STORAGE_ACCOUNT_ID` | 설정 시 공개 URL이 `/v1/AUTH_<값>/<버킷>/<key>` 형식 (선택) | Image Processing |
| `RABBITMQ_HEALTH_FILE` | heartbeat 파일 경로 (선택, 기본 `/tmp/healthy`) | Image Processing |

모든 값은 하드코딩하지 않고 환경변수로만 주입합니다 (추후 K8s Secret/OpenBao 연동 예정). 값의
실제 출처와 로컬 개발용 대체 값(MinIO 등)은 [README.md](./README.md#환경변수) 참고.

---

## 10. 알려진 기술 부채 및 향후 확장 방향

Product Service와 Image Processing Service는 PostgreSQL을 공유하고 있어 완전한 서비스
독립성이 확보되지 않았습니다 (분산 모놀리스에 가까운 상태). 서비스 경계(코드/배포 단위) 분리를
우선하고 데이터 분리는 다음 단계 과제로 남긴 의도적인 선택입니다.

향후 계획: Image Processing Service 전용 DB로 분리하고, 처리 완료 시 이벤트
(`{ event: "image_processed", product_id, result, reason }`)를 발행해 Product Service가 이를
구독해 자신의 DB 상태를 갱신하는 Choreography 패턴으로 전환. 이 전환을 쉽게 하기 위해 지금부터
지키는 원칙은 §4, §6 말미의 캡슐화 규칙입니다.

---

## 11. 범위 제외 (하지 않는 것)

- 판매자/구매자 인증 (로그인, JWT 등)
- 결제, 주문, 배송 등 다른 이커머스 도메인
- 비전 LLM 기반 이미지 콘텐츠 검수 (연동 지점만 TODO로 표시, §6)
- API Gateway 자체의 인증/레이트리밋 (Ingress 라우팅만 K8s 배포 단계에서 구성)
- 실제 서비스별 DB 분리, 이벤트 기반 통신 구현 (§10 향후 과제)
- Web UI 반응형 디자인, 라우팅/상태관리 프레임워크, 정교한 에러 처리 UX

---

## 12. Web UI 스펙

순수 HTML/CSS/JS(빌드 도구 없음), `nginx:alpine`으로 정적 파일만 서빙합니다.

### 판매자 화면

- 등록 폼(이름/가격/설명/이미지) → `POST /products`. 제출 시 로딩 상태(버튼 비활성화 + 텍스트
  변경) → 완료 시 짧은 성공 토스트(2초 후 자동 소멸)
- 상품 목록은 `GET /products?status=all`을 **2.5초 간격으로 폴링**해 서버에서 직접 그립니다
  (브라우저 세션에 등록 이력을 들고 있지 않음 — 폼으로 등록했든 외부 스크립트로 등록했든 전부
  표시됨)
- 상태 배지: `draft`=회색, `processing`=노란색(1.4초 주기 펄스 애니메이션), `active`=초록색,
  `rejected`=빨간색(배지 아래 반려 사유 텍스트 항상 노출)

### 구매자 화면

- `GET /products`(기본 호출, `active`만) 결과를 카드(썸네일 + 상품명 + 가격 + 설명 2줄)로 나열
- 카드 클릭 시 확대 모달: 상단 탭으로 썸네일/상세/확대 3종 전환, 전환마다 실제 픽셀 크기
  (`naturalWidth`/`naturalHeight`)와 실제 파일 용량(`Content-Length`)을 함께 표시 (Image
  Processing Service가 실제로 리사이징했음을 시각적으로 증명)

### 스타일 가이드

- Google Fonts(Inter) 1개만 외부 CDN 의존
- 색상 팔레트 3~4개(메인 1 + 배지 4색 + 중립색), 여백 12~16px 이상
- 데스크톱 고정폭 레이아웃 (반응형 불필요 — 발표는 노트북 화면 하나로 진행)

### API 호출

- `app.js`는 상대 경로로 호출 (`fetch('/products', ...)`). Web UI와 Product Service가 같은
  Ingress/오리진 아래 있어 CORS 설정 불필요. 별도 인증 없음.

---

## 13. Dockerfile / 빌드 요구사항

- Product Service, Image Processing Service, Web UI 각각 별도 Dockerfile
- Python 서비스는 `python:3.12-slim` 베이스
- **빌드 컨텍스트는 리포지토리 루트**: `product-service/Dockerfile`은 `run_migration.py`용
  `/migrations`를, `image-processing-service/Dockerfile`은 `cleanup_temp_images.py`용
  `/scripts`를 함께 이미지에 담습니다.
- **타겟 아키텍처**: NHN Cloud 인스턴스는 x86_64(amd64). arm64(Apple Silicon 등)에서 빌드 시
  `--platform linux/amd64` 명시 필수 (안 하면 `exec format error`).
- `web-ui/Dockerfile`은 기본으로 `nginx.k8s.conf`(product-service proxy_pass 없는 버전)를
  사용 — 실배포에서는 Ingress가 `/products` 라우팅을 대신함. 로컬 `docker-compose`는 볼륨으로
  `nginx.conf`(proxy_pass 포함)를 덮어 마운트.

---

## 14. 완료 기준 (Acceptance Criteria)

- [ ] `docker compose up`으로 Product/Image Processing/DB/Redis/RabbitMQ/Object Storage/Web UI가
      함께 기동된다
- [ ] `POST /products`로 이미지 업로드 후 `GET /products/{id}`가 `active`로 전환된다
- [ ] 저해상도(500px 미만) 이미지 업로드 시 `rejected` + `rejection_reason` 기록
- [ ] `GET /products`(파라미터 없음)는 `active` 상품만 반환한다
- [ ] 20MB 초과 업로드는 `413`, 20MB 이하(예: 15MB)는 정상 처리된다
- [ ] 처리 완료(active/rejected 무관) 후 `temp/` 원본이 삭제된다
- [ ] Image Processing Service 강제 종료(SIGKILL) 시 처리 중이던 메시지가 재큐잉된다
- [ ] DB를 내렸다 올려도 두 서비스가 크래시하지 않고 재연결 후 대기 중이던 요청/메시지가
      자동 처리된다
- [ ] `run_migration.py`를 연속 2회 실행해도 에러 없이 종료된다 (재실행 안전성)
- [ ] `cleanup_temp_images.py`는 24시간 이상 지난 `temp/` 파일만 삭제하고 최근 파일은 보존한다
- [ ] Web UI 판매자 화면이 폴링으로 `draft → processing → active/rejected` 전이를 실시간으로
      보여준다
- [ ] 상태별 배지 색상, 등록 시 로딩 상태/성공 토스트가 정상 동작한다
- [ ] Web UI 구매자 화면은 `active` 상품만 카드로 표시한다
- [ ] Product Service 코드 어디에도 `product_images` 테이블 쓰기(INSERT/UPDATE)가 없다
- [ ] README에 "알려진 기술 부채" 섹션이 포함되어 있다

실제 검증 결과와 재현 절차는 [README.md](./README.md#완료-기준-검증-결과), 상세 재현 명령은
[TESTING.md](./TESTING.md)에 정리되어 있습니다.

---

## 관련 문서

- [README.md](./README.md) — 실행 방법, 환경변수 출처, 완료 기준 검증 결과
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 서비스 토폴로지/시퀀스/상태 전이 다이어그램, 코드 구조
- [RELEASE_NOTES.md](./RELEASE_NOTES.md) — 버전별 변경 이력
- [TESTING.md](./TESTING.md) — 테스트 절차, 재현 명령, 발견된 버그 상세
