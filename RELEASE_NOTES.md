# Release Notes

버전별 변경 이력입니다. 구조/설계에 대한 설명은 [ARCHITECTURE.md](./ARCHITECTURE.md)를 참고하세요
(그 문서는 항상 최신 상태만 반영하고, 과거 버전과의 차이는 여기에 남깁니다).

## v0.1.6

- `web-ui`: 이미지 확대 모달의 "확대" 탭이 실제로는 다른 탭과 동일한 화면 크기로만
  표시되던 문제 수정. zoom 탭에서는 이미지를 실제 픽셀 크기 그대로 표시하고, 모달보다
  크면 스크롤로 확인하도록 변경.

## v0.1.5

- `image-processing-service`: zoom(1600px) 리사이징이 원본보다 작은 목표 크기에서
  업스케일되지 않던 문제 수정. `Image.thumbnail()`은 축소만 하고 확대는 하지 않아, 원본이
  500~1599px인 경우 zoom 결과물이 원본과 동일한 크기로 저장되고 있었다. 긴 변 기준으로
  배율을 직접 계산해 `Image.resize()`로 적용하도록 변경 — 원본이 작으면 확대, 크면 축소.

## v0.1.4

- `image-processing-service`: 공개 이미지 URL 생성에 `OBJECT_STORAGE_ACCOUNT_ID`(선택) 반영.
  설정 시 실제 NHN Cloud Object Storage 형식인 `/v1/AUTH_<계정ID>/<버킷>/<key>`로 URL을 만든다.
  로컬 `docker-compose`(MinIO)는 이 값을 설정하지 않아 기존 `<버킷>/<key>` 형식을 그대로 유지한다.

## v0.1.3

- `web-ui/nginx.k8s.conf`에서 `/health` proxy_pass 블록 제거. `/health`는 Product Service
  전용 엔드포인트라 Web UI 자체 헬스체크(`/` 경로)와 무관하기 때문.

## v0.1.2

- Web UI 이미지가 기본으로 굽는 nginx 설정을 K8s 실배포 기준(`web-ui/nginx.k8s.conf`,
  `/products` proxy_pass 제외 — 실배포에서는 Ingress가 그 역할을 대신함)으로 분리.
- 로컬 `docker-compose`의 `web-ui` 서비스는 기존 `nginx.conf`를 컨테이너 런타임에 volume으로
  덮어 마운트해 `/products` 프록시 동작을 그대로 유지.

## v0.1.1

- `.dockerignore` 추가: 이미지 빌드 컨텍스트에서 `.env` 등 민감 파일 제외.
- Image Processing Service: RabbitMQ 연결 상태를 `/tmp/healthy` heartbeat 파일로 노출
  (HTTP 엔드포인트가 없어 K8s Liveness/Readiness probe가 파일 mtime으로 판단하도록).
- Image Processing Service: 컨슘 도중 RabbitMQ 연결이 끊겨도 프로세스를 종료하지 않고
  `connect_with_retry()`로 재연결한 뒤 컨슘을 재개하는 while 루프 추가 (스펙 9번 항목).
- `docker-compose.yml`: 하드코딩된 로컬 자격증명을 `${VAR}`로 교체하고 `.env.example`에 정리.

## v0.1.0

- Product Service, Image Processing Service, Web UI 최초 구현 (MSA-lite 상품 이미지 파이프라인).
- DB 스키마/마이그레이션, `run_migration.py`, `cleanup_temp_images.py` 스크립트 추가.
- 서비스별 Dockerfile, `docker-compose.yml`로 로컬 통합 실행 구성.
