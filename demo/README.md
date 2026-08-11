# 발표 시연 자료

시연 환경에 따라 두 가지로 나뉩니다.

- **[local/](./local/README.md)** — 로컬 PC에서 `docker compose`로 전체 스택(MinIO 포함)을 띄워
  진행하는 데모. 리허설·개발 중 반복 확인용.
- **[cluster/](./cluster/README.md)** — 실제 NHN Cloud K8s 클러스터에서 진행하는 발표 당일용
  데모. DB/Redis 접속 정보가 클러스터 안 Secret/ConfigMap에만 있어 로컬과 실행 방식이 다릅니다.
