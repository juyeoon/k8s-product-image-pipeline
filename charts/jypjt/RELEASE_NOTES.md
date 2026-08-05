# Release Notes

## v0.1.4 (2026-08-05)

### Fixed

- **구매자 화면 이미지 표시 오류**: Object Storage 공개 URL에 OpenStack Swift 고유 경로 세그먼트(`/v1/AUTH_<account_id>/`)가 누락되어 `400 Bad Request` 발생. Image Processing Service가 URL 생성 시 이 세그먼트를 포함하도록 수정.

### Added

- `OBJECT_STORAGE_ACCOUNT_ID` 환경변수 추가 (선택적) — 값이 설정된 경우에만 공개 URL에 `/v1/AUTH_<id>/`를 삽입. 로컬 개발 환경(MinIO)에서는 해당 경로 구조가 없어 값을 비워두면 기존 URL 형식 그대로 동작.

### Notes

- 이 변경 이전에 등록된 상품(테스트 데이터)의 이미지 URL은 자동으로 갱신되지 않음. 재등록 필요.

---

## v0.1.3 (2026-08-05)

### Fixed

- **Web UI 컨테이너 기동 실패**: K8s 배포용 Nginx 설정(`nginx.k8s.conf`)에 `/health` 경로의 `proxy_pass http://product-service:8000`이 남아있어, K8s Service 이름(`product-service-service`)과 불일치로 Nginx가 시작 시점에 upstream 검증 실패. 해당 location 블록 제거.

---

## v0.1.2 (2026-08-05)

### Fixed

- **Web UI 컨테이너 기동 실패**: `nginx.k8s.conf`에서 `/products` 경로의 `proxy_pass` 제거 (K8s 배포 시 Ingress가 이 라우팅을 대신 처리하므로 불필요 — 로컬 docker-compose 환경과 분리하기 위해 K8s 전용 설정 파일 `nginx.k8s.conf` 신규 도입).
- 이 버전에서는 `/health` 경로의 동일한 문제를 놓쳐 완전히 해결되지 않음 (→ v0.1.3에서 후속 수정).

---

## v0.1.1 (2026-08-04)

### Changed

- `docker-compose.yml`에 하드코딩되어 있던 자격증명을 환경변수로 추출 (레포 정리 포함).

### Added

- Image Processing Service에 `/tmp/healthy` 파일 기반 heartbeat 추가 — RabbitMQ 연결 상태를 Liveness Probe가 확인할 수 있도록 함 (HTTP 서버가 없는 순수 컨슈머 프로세스라 파일 기반으로 대체).
- Image Processing Service `main.py`의 `run_consumer()`를 재연결 루프로 감싸, 실행 중 RabbitMQ 연결이 끊겨도 프로세스가 종료되지 않고 자동 재연결하도록 개선 (기존에는 연결 예외 발생 시 프로세스가 종료되어 K8s 재시작에만 의존하던 구조).

---

## v0.1.0 (2026-08-03)

### Added

- 최초 릴리즈. Product Service, Image Processing Service, Web UI 3개 이미지 최초 빌드 및 Harbor 푸시.

---

## Helm Chart (`charts/jypjt`) v0.1.0 (2026-08-05)

### Added

- 최초 Helm 차트 작성 완료. 전체 컴포넌트(Web UI, Product Service, Image Processing Service, PostgreSQL, Redis, RabbitMQ) + Job/CronJob + Ingress 매니페스트 포함 (총 23개 리소스).
- `helm install`을 통한 최초 배포 성공, E2E 파이프라인 동작 검증 완료 (상품 등록 → 이미지 처리 → 구매자 노출까지 전체 흐름).

### Fixed (배포 과정에서 발견)

- `values.yaml` YAML 문법 오류 수정.
- RabbitMQ Probe(`startupProbe`/`livenessProbe`/`readinessProbe`)에 `timeoutSeconds` 누락으로 인한 반복 재시작 → `timeoutSeconds: 10` 추가로 해결.
- Ingress-NGINX Controller의 MetalLB 가상 IP에 Floating IP를 직접 연결할 방법이 없어, Control Plane에 신규 NIC를 추가하고 `nodeSelector`로 Controller Pod를 고정 배치하는 방식으로 우회. 이 과정에서 Calico의 IP 자동 감지 오작동으로 클러스터 전역 DNS 장애가 발생했으며, `IP_AUTODETECTION_METHOD=interface=eth0` 설정으로 해결.
