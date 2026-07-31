# 테스트 문서

이 문서는 `docker compose`로 로컬 스택을 띄운 상태에서 이 리포지토리의 핵심 동작을
검증하는 절차와, 지금까지 실제로 실행해서 확인한 결과를 기록합니다. 코드가 바뀔 때마다
이 문서의 명령어들을 다시 돌려서 회귀를 확인하는 용도로 씁니다.

> 완료 기준(스펙 15번 항목) 체크리스트 결과 요약은 [README.md](./README.md)의
> "완료 기준 검증 결과" 섹션에 있습니다. 이 문서는 그걸 어떻게 검증했는지의 실행 절차와,
> 추가로 검증한 항목(Web UI 강화 기능, 동시성 버그)까지 더 자세히 다룹니다.

## 테스트 환경 준비

```
docker compose down -v          # 이전 데이터가 남아있다면 완전 초기화
docker compose up --build -d
sleep 15                        # 모든 컨테이너가 healthy 상태가 될 때까지 대기
curl -s http://localhost:8000/health   # {"status":"ok"} 확인
curl -s "http://localhost:8000/products?status=all"   # [] 확인
```

Windows에서 큰 파일을 `curl -F image=@...`로 업로드할 때 Git Bash의 네이티브 curl이 가끔
`curl: (26) Failed to open/read local data from file`를 내는 경우가 있었습니다(파일 자체
문제가 아니라 클라이언트 쪽 이슈). 재현이 안 되면 아래처럼 컨테이너 안에서 curl을 돌리면
우회됩니다:

```
docker run --rm --network k8s-product-image-pipeline_default -v "$(pwd)/demo/images:/data" \
  curlimages/curl -F "name=x" -F "price=1" -F "description=x" \
  -F "image=@/data/demo_backlog_1.jpg" http://product-service:8000/products
```

## 1. 핵심 업로드/처리 파이프라인

| 테스트 | 명령 | 기대 결과 |
|---|---|---|
| 정상 이미지 → active | 500px 이상 jpg/png 업로드 후 `GET /products/{id}` 폴링 | `draft → processing → active`, `images`에 thumbnail/detail/zoom 3개 URL |
| 저해상도 → rejected | 500px 미만 이미지 업로드 | `rejected` + `rejection_reason`에 미달 사유 |
| 20MB 초과 → 413 | 21MB 이상 업로드 | `413 Payload Too Large` |
| 20MB 이하 대용량 정상 처리 | 10~18MB 유효 이미지 업로드 | 정상적으로 `active` 전환 |
| `GET /products` (기본) | active 상품만, 캐싱됨 | `draft`/`processing`/`rejected` 제외 |
| `GET /products?status=all` | 상태 무관 전체 | 개수가 실제 DB row 수와 일치 |
| `temp/` 원본 삭제 | 위 테스트들 후 MinIO `temp/` 확인 | active/rejected 무관하게 비어 있음 |
| Product Service의 `product_images` 쓰기 금지 | `grep -rn "INSERT INTO product_images\|UPDATE product_images" product-service/` | 매치 없음 |

실행 예:

```bash
SCRATCH=demo/images   # 또는 임의의 테스트 이미지 폴더

# 정상
curl -s -X POST http://localhost:8000/products \
  -F "name=t1" -F "price=100" -F "description=d" -F "image=@$SCRATCH/demo_backlog_1.jpg"

# 저해상도(500px 미만 이미지 필요 - demo/images/demo_reject.jpg 사용)
curl -s -X POST http://localhost:8000/products \
  -F "name=t2" -F "price=100" -F "description=d" -F "image=@demo/images/demo_reject.jpg"

# 상태 확인
curl -s http://localhost:8000/products/1
curl -s "http://localhost:8000/products?status=all"
```

## 2. 장애 복원력 (Chaos) 테스트

| 시나리오 | 명령 | 기대 결과 |
|---|---|---|
| Image Processing Service 강제 종료(SIGKILL) | 대용량 이미지 업로드 직후 `docker compose kill -s SIGKILL image-processing-service` | RabbitMQ가 unacked 메시지를 자동 재큐잉(`rabbitmqctl list_queues`로 `messages` 증가 확인), 재기동 후 정상 처리 |
| Image Processing Service 정상 종료(SIGTERM) | `docker compose kill -s SIGTERM image-processing-service` | 처리 중이던 메시지를 마무리한 뒤 `exit code 0`으로 종료 (`docker inspect`로 확인) |
| DB 중단/복구 | `docker compose stop postgres` → 몇 초 뒤 `docker compose start postgres` | 두 서비스 모두 크래시하지 않고, 재연결 후 대기 중이던 요청/메시지가 자동 처리됨 |
| `/health`는 DB 장애 중에도 빠르게 응답 | DB 중단 상태에서 `curl --max-time 15 http://localhost:8000/health` | 몇 초 안에 `503` (수십 초~분 단위로 블로킹되면 버그, 아래 3번 참고) |
| 재시도 3회 초과 → DLQ 이동 | 존재하지 않는 `temp_image_key`로 메시지를 직접 발행 (아래 명령) | 재시도 로그가 `retry_count=0,1,2,3` 순서로 찍히고 `image_processing.dlq`로 이동 |

DLQ 테스트 명령:

```bash
docker compose exec -T rabbitmq rabbitmqadmin -u app -p app_password publish \
  exchange=amq.default routing_key=image_processing \
  payload='{"product_id": 999, "temp_image_key": "temp/does_not_exist.jpg"}'

docker compose exec -T rabbitmq rabbitmqctl list_queues name messages messages_unacknowledged
# image_processing.dlq 쪽에 메시지가 1개 있어야 함
```

## 3. 운영 스크립트

| 스크립트 | 명령 | 기대 결과 |
|---|---|---|
| `run_migration.py` 재실행 안전성 | `docker compose run --rm --no-deps product-service python migrations/run_migration.py` 를 2회 연속 | 둘 다 에러 없이 `all_migrations_completed` 로그 |
| `cleanup_temp_images.py` — 최근 파일 보존 | `temp/`에 새 파일 업로드 후 즉시 실행 | `scanned=1 deleted=0` |
| `cleanup_temp_images.py` — 기준 초과 파일 삭제 | 스크립트의 `MAX_AGE`를 일시적으로 짧게(`timedelta(seconds=5)`) 바꿔 재현 | 5초 지난 파일이 실제로 `delete_object` 호출과 함께 삭제됨 |

## 4. Web UI 강화 기능

브라우저(`http://localhost:8080`)에서 직접 확인이 필요합니다. API/정적 자원 레벨은 curl로도
확인 가능합니다.

| 기능 | 확인 방법 |
|---|---|
| 판매자 목록이 서버 기반으로 갱신 | `GET /products?status=all`을 curl로 등록한 상품도 Web UI 판매자 목록에 뜨는지 확인 (`demo/run_demo.sh`로 재현) |
| 반려 사유 텍스트 상시 표시 | `rejected` 상품 배지 아래에 hover 없이 바로 사유 텍스트가 보이는지 |
| `processing` 배지 펄스 애니메이션 | `curl -s http://localhost:8080/style.css \| grep badge-pulse` |
| 구매자 카드 설명 표시 | `description`을 채워 등록 후 구매자 화면 카드에 표시되는지 |
| 이미지 확대 모달 + 사이즈 탭 | 카드 클릭 → 썸네일/상세/확대 탭 전환 시 `naturalWidth/Height`와 `Content-Length` 기반 용량이 바뀌는지 |

## 5. 발견 및 수정된 버그

### 5-1. `/health`가 DB 장애 시 최대 6분까지 블로킹 (1차 발견)

`health_check()`가 일반 쿼리 경로와 같은 재연결 재시도(최대 10회, 백오프 최대 60초) 로직을
타고 있었습니다. `product-service/db.py`, `product-service/cache.py`의 `health_check()`를
분리해 짧은 타임아웃(2초) 단발 확인으로 수정했습니다.

### 5-2. 동시 요청이 하나라도 블로킹되면 전체 이벤트 루프가 멈추는 문제 (2차 발견)

1차 수정 후에도, Web UI가 2.5초 간격으로 폴링하는 `GET /products?status=all` 요청 하나가
DB 재연결 재시도에 걸리면 — 그 요청 자체는 물론 **동시에 들어온 다른 모든 요청(`/health` 포함)까지
전부 응답이 멈추는** 문제를 발견했습니다.

원인: `main.py`의 라우트 핸들러가 `async def`인데, 그 안에서 동기(blocking) 함수인 `db.py`/
`cache.py`/`queue_publisher.py`의 호출을 `await` 없이 직접 실행하고 있었습니다. 이러면 그
호출이 블로킹되는 동안 uvicorn의 단일 이벤트 루프 자체가 멈춰서, 같은 프로세스가 처리해야 할
다른 모든 요청도 함께 멈춥니다.

수정: `create_product`는 `async def`를 유지하되 내부의 동기 호출들(`db.insert_draft_product`,
`storage.upload_temp_image`, `queue_publisher.publish_image_processing_task`)을
`starlette.concurrency.run_in_threadpool`로 감쌌습니다. `list_products`, `get_product`,
`health`는 async가 필요 없어서 일반 `def`로 바꿨습니다 — FastAPI/Starlette가 일반 `def`
핸들러는 자동으로 스레드풀에서 실행해주므로 이벤트 루프를 막지 않습니다.

재현 및 검증 방법:

```bash
# 백그라운드에서 브라우저 폴링을 흉내냄
( for i in $(seq 1 40); do curl -s -o /dev/null "http://localhost:8000/products?status=all"; sleep 0.5; done ) &

docker compose stop postgres
sleep 2
time curl -s -w "\nHTTP:%{http_code}\n" --max-time 15 http://localhost:8000/health
# 수정 전: HTTP:000 (15초 타임아웃까지 응답 없음)
# 수정 후: 약 3초 안에 HTTP:503

docker compose start postgres
```

이 버그는 K8s Liveness Probe 관점에서 특히 중요합니다 — 서버가 "DB만 unhealthy"인 상태를
넘어 **프로세스 전체가 멈춘 것처럼** 보이면, 실제로는 살아있는 프로세스인데도 K8s가 죽었다고
오판해 불필요하게 재시작시킬 수 있습니다.

## 재현 스크립트

전체 파이프라인(업로드 → 큐 백로그 → active/rejected 전이)을 한 번에 재현하려면:

```
bash demo/reset_demo_data.sh   # 데이터 초기화
bash demo/run_demo.sh          # 5장 백로그 업로드 + 반려 1장 + 상태 변화 관찰
```

자세한 내용은 [demo/README.md](./demo/README.md) 참고.
