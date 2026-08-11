# 클라우드 네이티브 쿠버네티스 환경 구축: 상품 이미지 등록 파이프라인 운영

> NHN Cloud 위에 관리형 쿠버네티스 서비스 없이 kubeadm으로 클러스터를 직접 구축하고,
> 이커머스 상품 이미지 처리 파이프라인을 GitOps로 배포한 뒤, 장애를 주입해 자동 복구를 수치로 검증한 프로젝트입니다.

|          |                                                                                           |
| -------- | ----------------------------------------------------------------------------------------- |
| 기간     | 2026-07-31 ~ 2026-08-07 (구축·실험 8일) + 문서화                                          |
| 역할     | 인프라 설계 · 클러스터 구축 · 배포 파이프라인 · 장애 대응 (애플리케이션 코드는 AI에 위임) |
| 클라우드 | NHN Cloud (OpenStack 기반) — 전 구간 단일 클라우드                                        |

## 핵심 결과

| 지표            | 값                                                      |
| --------------- | ------------------------------------------------------- |
| Pod Kill MTTR   | 12초 — 그중 11초가 Readiness Probe 대기임을 분해해 확인 |
| HPA 스케일아웃  | CPU 91% 도달 시 Replica 2 → 3, 직후 68~72%로 하강       |
| 부하 테스트     | 45,898요청 / 실패율 0.00% / 응답시간 Avg 3ms            |
| 기록한 의사결정 | 40건 — 전부 A/B 비교 + 기각 사유 포함                   |

---

## 아키텍처

![전체 쿠버네티스 아키텍처](./docs/full_k8s_architecture.svg)

### 서비스 흐름

```
판매자 → Ingress → Product Service → (상품 draft 생성 + RabbitMQ 발행) → 즉시 202 응답
                                            ↓
                          Image Processing Service (큐 소비)
                                            ↓
                       룰 기반 검수 → 3종 리사이징(thumbnail/detail/zoom)
                                            ↓
                       Object Storage 업로드 → 상태 active (또는 rejected)
                                            ↓
구매자 → Ingress → Product Service → active 상품만 조회 (Redis 캐싱)
```

상품은 `draft → processing → active | rejected` 상태 기계를 따릅니다. 비동기 큐를 쓴 이유는 이미지 검수·리사이징이 실제로 무거운 작업이기 때문이고, 이 부하가 뒤에서 HPA 실험의 재료가 됩니다.

### API 엔드포인트 (Product Service)

| 메서드 / 경로                   | 응답                                                                         |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `POST /products`                | `202` `{product_id, status:"draft"}` · `400`(미지원 포맷) · `413`(20MB 초과) |
| `GET /products` (`?status=all`) | `200` 목록 (Redis 캐싱)                                                      |
| `GET /products/{id}`            | `200` 상세 · `404`                                                           |
| `GET /health`                   | `200` · `503` (DB/Redis 상태 포함)                                           |

세 서비스 모두 HPA를 붙였습니다 — Product Service와 Image Processing Service는 2~4개, Web UI는 2~3개입니다. Web UI만 상한이 낮은 건 정적 파일 서빙이라 부하 대비 확장 필요가 작기 때문입니다.

Image Processing Service는 HTTP 엔드포인트가 없는 순수 RabbitMQ 컨슈머입니다. 그래서 Liveness Probe를 HTTP로 걸 수 없어, 파일 기반 heartbeat(`/tmp/healthy`)를 두고 `find -mmin -2`로 신선도를 검사합니다.

### 이미지 처리 스펙

| 항목      | 값                                                                 |
| --------- | ------------------------------------------------------------------ |
| 지원 포맷 | JPEG, PNG (결과물은 항상 JPEG `quality=85`)                        |
| 검수 룰   | 가로·세로 중 하나라도 500px 미만이면 반려                          |
| 리사이징  | thumbnail 200px / detail 800px / zoom 1600px (긴 변 기준, LANCZOS) |

---

## 왜 관리형 서비스를 쓰지 않았나

NKS(NHN Kubernetes Service)를 쓰면 클러스터는 몇 분 만에 생깁니다. 그런데 그렇게 하면 CNI·스토리지·로드밸런서 계층을 한 번도 안 보고 지나가게 됩니다.

이 프로젝트의 목적은 동작하는 서비스를 만드는 게 아니라 인프라를 이해하는 것이었으므로, 의도적으로 kubeadm 직접 구축을 택했습니다.

![NHN Cloud 인프라 · 네트워크 구성](./docs/infra_network_architecture.svg)

인스턴스 7대를 직접 올리고, 신뢰 경계마다 보안 그룹과 키페어를 나눴습니다. Floating IP는 Bastion · Control Plane · Harbor 세 곳에만 부여하고 나머지는 사설망 전용으로 뒀습니다.

### 그래서 직접 만난 문제들

- NHN Cloud의 Floating IP는 인스턴스 NIC에만 붙는데, MetalLB의 가상 IP는 어디에도 속하지 않아 연결 방법이 없었습니다
- 같은 VPC 안에서는 서로의 Floating IP로 통신이 안 되는 Hairpin NAT 구조였습니다
- Prometheus TSDB는 NFS를 공식 미지원인데, 클러스터의 유일한 StorageClass가 NFS였습니다
- NHN Cloud 보안 그룹 콘솔에는 IP-in-IP 프로토콜 옵션이 없어 Calico를 IPIP에서 VXLAN으로 바꿔야 했습니다

이 문제들은 관리형 서비스를 썼다면 만나지 않았을 것들입니다. 편한 길을 의도적으로 가지 않은 것이 이 프로젝트의 내용 대부분을 만들었습니다.

---

## 기술 스택

| 계층              | 구성                                                                                     | 설치 방식                    |
| ----------------- | ---------------------------------------------------------------------------------------- | ---------------------------- |
| 클러스터          | Kubernetes v1.35 (kubeadm), Worker 3대 + Control Plane 1대                               | 직접 구축                    |
| CNI               | Calico v3.32 (VXLAN — IPIP는 SG 제약으로 불가)                                           | 공식 매니페스트              |
| 로드밸런서        | MetalLB (L2 모드)                                                                        | Helm                         |
| Ingress           | Ingress-NGINX v1.15.1 (Control Plane 고정 배치)                                          | Helm                         |
| 스토리지          | NFS 전용 인스턴스 + `nfs-subdir-external-provisioner`                                    | Helm                         |
| 애플리케이션      | Python 3.12, FastAPI 0.115 / Pillow 11.1, PostgreSQL(StatefulSet), Redis, RabbitMQ       | 자체 작성 Helm 차트 + ArgoCD |
| 인스턴스          | 7대 — Bastion `m2.c1m2`(1vCPU/2GB·HDD 20GB), 나머지 6대 `m2.c2m4`(2vCPU/4GB·SSD 40~50GB) | NHN Cloud 직접 생성          |
| 이미지 레지스트리 | Harbor v2.13 (전용 인스턴스, 전용 SG/키페어)                                             | Docker Compose               |
| 시크릿 관리       | OpenBao + External Secrets Operator                                                      | Helm                         |
| GitOps            | ArgoCD (Auto-sync + Self-heal + Prune)                                                   | 공식 매니페스트              |
| 관측성            | kube-prometheus-stack, postgres_exporter, Grafana                                        | Helm                         |
| 부하 도구         | Locust 2.46                                                                              | venv                         |

### 설치 방식을 통일하지 않은 이유

컴포넌트마다 설치 방식이 다른 건 임의가 아니라 세 가지 원칙에 따른 것입니다.

1. 공식 1순위 경로를 따른다 — ArgoCD·Calico는 공식 매니페스트, Helm 차트를 공식 제공하면 Helm
2. "배포 대상 앱"과 "배포를 수행하는 도구"를 구분한다 — 앱만 ArgoCD가 관리하고, 운영 도구는 관리 밖에 둡니다
3. 관리형 서비스는 의도적으로 쓰지 않는다

---

## GitOps 파이프라인

```
로컬 Helm 차트 수정 → git push → ArgoCD가 main 브랜치 감지 → 자동 Sync → 클러스터 반영
```

- ArgoCD Application 1개가 umbrella Helm 차트 전체(리소스 23개)를 관리합니다
- 컨테이너 이미지는 Harbor(사설 레지스트리), Helm 차트 소스는 Git에 둡니다 — 차트를 Harbor OCI에 두면 `helm package` + `helm push` 스텝이 CI에 추가로 필요해 "Git이 유일한 진실"에서 벗어나기 때문입니다

### 검증한 것

| 항목                 | 결과                                                            |
| -------------------- | --------------------------------------------------------------- |
| Git 변경 → 자동 반영 | `values.yaml` push만으로 커밋 해시 자동 갱신 및 Deployment 반영 |
| Self-heal            | `kubectl set image`로 수동 변경 → 수 초 내 Git 선언값으로 원복  |
| 배포 이력            | Sync 이력이 커밋 해시·시각과 함께 기록, Rollback 버튼 존재      |

### 부수 학습 — 롤백조차 Git을 거친다

Auto-sync가 켜진 상태에서는 UI의 Rollback 버튼을 눌러도 Git이 최신이므로 Self-heal이 즉시 되돌립니다. 실제 롤백은 `git revert` 후 push가 정공법이며, GitOps에서는 롤백조차 Git을 거치도록 구조적으로 강제됩니다.

---

## 메시지 파이프라인의 신뢰성 설계

인프라가 복구돼도 처리 중이던 메시지가 사라지면 의미가 없습니다. 큐 계층에서 어디까지 보장하고 어디부터는 보장하지 않는지를 명시합니다.

| 무엇을                  | 어떻게                                                 | 그래서 무엇이 보장되나                                   |
| ----------------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| 큐를 디스크에 저장      | `queue_declare(durable=True)`                          | RabbitMQ가 재시작해도 큐가 사라지지 않음                 |
| 메시지를 디스크에 저장  | `delivery_mode=2`                                      | 큐 안에 쌓여 있던 작업도 함께 살아남음                   |
| 처리 후에만 완료 처리   | 수동 ack, 한 번에 1건씩                                | 처리 도중 컨슈머가 죽으면 그 작업이 다시 큐로 돌아감     |
| 실패한 작업 격리        | 재시도 횟수를 메시지에 기록, 3회 넘으면 별도 큐로 이동 | 계속 실패하는 작업 하나가 뒤의 정상 작업을 막지 않음     |
| (미적용) 발행 성공 확인 | Publisher Confirm 미사용                               | ⚠️ 메시지를 보낸 직후 브로커가 죽는 순간은 방어하지 못함 |

용어를 풀면 이렇습니다.

- **큐를 디스크에 저장한다**는 건, RabbitMQ Pod가 재시작돼도 처리 대기 중이던 상품이 그대로 남아 있다는 뜻입니다. 이게 없으면 등록은 됐는데 아무 일도 일어나지 않는 상품이 생깁니다.
- **수동 ack**는 "다 처리했다"고 컨슈머가 직접 알려주는 방식입니다. 자동으로 처리하면 메시지를 받자마자 완료로 간주하므로, 처리 중에 죽으면 그 작업이 사라집니다.
- **실패 작업 격리**는 깨진 이미지처럼 몇 번을 다시 시도해도 실패하는 작업을 따로 치워두는 장치입니다. 안 그러면 그 하나가 계속 재시도되면서 뒤에 줄 선 정상 작업들이 처리되지 못합니다.

### 어디까지 보장하고, 어디부터는 안 하는가

한 번 보낸 작업은 최소 한 번은 처리된다 — 여기까지가 보장 범위입니다. 다만 완전한 보장은 아닙니다. 메시지를 보낸 직후 RabbitMQ가 죽는 아주 짧은 순간은 막지 못합니다. 이걸 막으려면 발행 성공을 매번 확인받는 설정이 필요한데, 넣지 않았습니다.

이 한계를 알면서 넘어간 이유는 큐의 역할 때문입니다. 여기서 큐는 결제나 정산처럼 한 건도 틀리면 안 되는 흐름이 아니라, 이미지 처리를 사용자 응답과 분리하기 위한 장치입니다. 최악의 경우 상품 하나가 `draft`에 남고, 그건 재등록으로 복구됩니다.

### 실패 처리를 직접 구현한 이유

RabbitMQ에는 실패한 메시지를 자동으로 격리해주는 기능이 있습니다. 그런데 이 프로젝트는 그걸 쓰지 않고 직접 구현했습니다.

이유는 **재시도 횟수를 세기 위해서**입니다. RabbitMQ 기본 방식은 실패한 메시지를 큐에 도로 넣기만 하고, 그게 몇 번째 시도인지는 남기지 않습니다. 그래서 같은 작업이 무한히 반복될 수 있습니다. 대신 메시지에 "지금 몇 번째 시도"라는 표시를 달아서 다시 넣으면, 3번을 넘겼을 때 격리 큐로 보낼 수 있습니다.

### 연결 끊김에 대한 방어 — 실측으로 검증된 부분

두 서비스 모두 DB·RabbitMQ 연결에 지수 백오프 재시도를 넣었습니다(초기 2초, ×2 증가, 최대 60초 캡, 10회).

#### 이 로직이 들어간 경위

처음부터 있던 게 아닙니다. Helm 차트의 Liveness Probe를 설계하다 코드를 확인해보니, 컨슈머 실행 중 연결이 끊기면 재시도 없이 예외가 전파되어 프로세스가 그냥 종료되는 구조였습니다. K8s가 재시작은 해주지만 `CrashLoopBackOff` 백오프가 누적되면 복구 시간이 실제보다 나쁘게 측정되므로, 재연결 루프를 넣도록 수정했습니다.

#### 실제로 두 번 검증됨

- 상품 등록 도중 `ConnectionResetError` 발생 → 자체 재연결로 복구해 정상 처리 완료
- Pod 재시작 직후 `Connection refused` 약 1분 반복 → 백오프(2s→4s→8s→16s→32s) 후 `rabbitmq_connected` / `consumer_started` 복구

> `GET /health`는 이 재시도 경로를 타지 않습니다. `connect_timeout=2`로 1회만 확인합니다. Probe가 재시도 루프에 들어가면 DB 장애 시 헬스체크가 수 분간 블로킹되어 Probe 자체가 무의미해지기 때문입니다.

---

## 장애 실험 결과

계획한 4개 시나리오 중 2개를 실행했습니다. 나머지 2개를 제외한 판단 근거는 아래 "알려진 한계"에 있습니다.

### 시나리오 1 — Pod Kill

`product-service` Pod를 강제 종료하고 복구까지의 시간을 초 단위로 추적했습니다.

| 시각     | 일어난 일                                  |
| -------- | ------------------------------------------ |
| 0s       | Pod 생성 → `Pending` → `ContainerCreating` |
| 1s       | 컨테이너 프로세스 시작                     |
| 1s ~ 11s | `initialDelaySeconds: 10` 대기             |
| 12s      | 첫 Readiness Probe 통과 → `Ready` (MTTR)   |

![Pod Kill MTTR 12초의 내역](./docs/pod_kill_mttr_timeline.svg)

#### 이 분해에서 나온 결론

컨테이너가 뜨는 데는 1초, 나머지 11초는 전부 Probe 대기였습니다.

이 분해가 중요한 이유는 "복구 시간을 줄이려면 뭘 바꾸나"의 답이 달라지기 때문입니다. 기동이 느렸다면 이미지나 노드를 손봐야 하지만, 실제 병목은 제가 Helm 차트에 직접 써넣은 설정값이었습니다. 즉 복구 시간의 주도권은 Kubernetes가 아니라 운영자에게 있었습니다.

#### 부수 확인

이미지 pull 76ms(Harbor 사설망), Anti-Affinity로 두 Replica가 서로 다른 노드에 분산, `curl` 21회 연속 `200`으로 무중단 확인.

### 시나리오 4 — CPU Stress → HPA

| 시도 | 부하     | CPU    | Replicas | 결과                     |
| ---- | -------- | ------ | -------- | ------------------------ |
| 1차  | 100 유저 | 21~23% | 2        | 미발동                   |
| 2차  | 400 유저 | 62~66% | 2        | 미발동 — 임계값 70% 직전 |
| 3차  | 800 유저 | 84~91% | 2 → 3    | 스케일아웃               |

2차 시도가 이 실험에서 가장 유용한 데이터였습니다. 부하를 4배로 올렸는데도 66%에서 멈춰 아무 일도 일어나지 않았고, 이는 "HPA는 임계값을 넘어야만 동작한다" 를 실측으로 보여줍니다. 한 번에 성공했다면 얻지 못했을 관찰입니다.

#### 결과

스케일아웃 이후 CPU가 68~72%로 하강해 늘어난 Pod가 실제로 부하를 나눠 받았음이 확인됐고, 전체 45,898요청 중 실패는 0건이었습니다.

#### 추가로 확인한 것 — HPA 퍼센트의 기준

HPA의 `averageUtilization`은 `limits`가 아니라 `requests` 기준입니다. CPU 91%일 때 실사용은 91m로 `limits`(250m)의 36%에 불과했고, 따라서 스로틀링이 발생하기 한참 전에 HPA가 먼저 확장했습니다.

---

## 트러블슈팅 (전체 기록 중 3건)

### 1. NIC 하나를 추가했더니 클러스터 DNS가 마비됨

MetalLB의 가상 IP에 Floating IP를 붙일 방법이 없어, 사설 IP를 수동 지정한 NIC를 만들어 Control Plane에 추가했습니다.

그러자 클러스터 전체 DNS가 죽었습니다.

원인은 Calico가 새로 생긴 `eth1`을 노드 IP로 잘못 인식해 BGP 피어링이 전면 단절된 것이었습니다. `IP_AUTODETECTION_METHOD=interface=eth0`으로 해결했습니다.

인프라 계층의 작은 변경이 전혀 다른 계층으로 번지는 걸 직접 겪은 사례입니다.

### 2. "ArgoCD가 되돌렸다"는 오진

Git에서 replica를 2→3으로 올렸는데 수 초 뒤 2로 돌아갔습니다. 처음엔 ArgoCD Self-heal 때문이라고 판단했지만, `kubectl describe hpa`의 Events에는 `SuccessfulRescale ... All metrics below target`이 찍혀 있었습니다 — 실제로는 HPA의 정상적인 스케일 다운이었습니다.

문제의 본질은 "누가 되돌렸나"가 아니라 `replicas` 필드를 ArgoCD와 HPA가 동시에 소유하려는 구조였습니다. `ignoreDifferences`로 해결했는데, 여기서 한 번 더 틀렸습니다 — `RespectIgnoreDifferences=true`를 같이 넣지 않으면 diff 판정에서만 빠지고 Sync 때는 Git 값이 재적용되어 반쪽 해결이 됩니다.

> 같은 종류의 문제를 4단계에서 또 만났습니다. Calico가 Tigera Operator가 아닌 공식 매니페스트로 설치돼 있어서 DaemonSet을 직접 고칠 수 있었는데, Operator 방식이었다면 Operator가 원복했을 것입니다. 도구도 단계도 달랐지만 "이 리소스의 소유자가 누구인가"라는 같은 문제였습니다.

### 3. 설정을 넣었는데 읽지를 않았다

Worker에서 `ImagePullBackOff`가 났고 에러는 `dial tcp <Harbor>:443: i/o timeout`이었습니다. HTTP뿐인 Harbor에 containerd가 HTTPS로 붙는 상황이라 `certs.d/hosts.toml`을 만들었는데, 여전히 443으로 시도했습니다.

근본 원인은 containerd의 `config_path`가 기본값인 빈 문자열이라 `certs.d` 폴더를 아예 읽지 않고 있었던 것이었습니다.

이걸 고치자 이번엔 포트만 80으로 바뀐 같은 에러가 났습니다 — Hairpin NAT였습니다. 그리고 여기도 한 겹 더 있었습니다. 이미지를 사설 IP로 재푸시해도 안 됐는데, Harbor가 토큰 발급 시 `harbor.yml`의 `hostname` 값을 realm 헤더로 그대로 안내하기 때문이었습니다. `hostname`을 `harbor.jypjt.local`로 바꿔 해결했습니다.

#### 배운 것

설정이 안 먹으면 그 설정을 읽고 있는지부터 확인해야 합니다. 그리고 에러가 미묘하게 바뀌었다면(443→80) 첫 번째 문제는 해결됐고 두 번째가 드러난 것입니다.

---

## 의사결정 기록

모든 주요 선택을 A안/B안 비교 + 채택 근거 + 기각 사유 형식으로 40건 남겼습니다. 결정을 바꾼 경우 바꾼 이유까지 기록했습니다.

### 대표 사례

| #   | 결정                                         | 요지                                                                                    |
| --- | -------------------------------------------- | --------------------------------------------------------------------------------------- |
| #2  | MSA-lite 채택                                | 서비스는 분리, DB는 공유. 경계를 먼저 긋고 저장소는 나중에 나누는 순서                  |
| #18 | Helm 차트를 Harbor OCI → Git 경로로 변경     | CI 자동화 확장성을 기준으로 재평가한 결과                                               |
| #31 | Ingress를 Control Plane에 고정               | "죽으면 자동 복구 안 됨"이라는 트레이드오프를, 장애 실험 대상이 아닌 노드에 몰아서 감수 |
| #33 | HPA `replicas`를 ArgoCD diff에서 제외        | 두 자동화의 필드 소유권 충돌 해소                                                       |
| #36 | Prometheus를 `emptyDir` + Control Plane 고정 | NFS 미지원 회피 + 관측자와 피관측자 분리                                                |
| #40 | 장애 시나리오 4개 → 2개                      | 복구/확장이라는 다른 축을 하나씩 증명하는 조합 선택                                     |

전체 기록: [`k8s_portfolio_roadmap.md`](./docs/k8s_portfolio_roadmap.md)

---

## 알려진 한계

숨기지 않고 적습니다. 어디까지 검증했고 어디부터는 설계뿐인지를 구분하는 것이 이 문서의 목적입니다.

### 검증하지 못한 것

| 항목                          | 상태                     | 사유                                                                              |
| ----------------------------- | ------------------------ | --------------------------------------------------------------------------------- |
| PDB(PodDisruptionBudget) 효과 | 설계만 적용, 동작 미확인 | Node Failure 시나리오 미실행                                                      |
| Memory Limit 타당성           | 계산 근거만 있음         | OOMKilled 시나리오 미실행                                                         |
| HPA 반응 시간 / 스케일인      | 미측정                   | 실험 설계 미흡 — 부하 규모를 사전 산정하지 않고 3회 재시도하며 기준 시각이 흐려짐 |

앞의 두 개는 판단해서 안 한 것이고(결정 #40), 마지막 하나는 놓친 것입니다. 둘은 다르므로 구분해서 적습니다.

### 인지하고 있는 기술 부채

| 항목                             | 다음 단계                                                                                                                        |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| DB 공유 (분산 모놀리스 리스크)   | DB 분리 + 이벤트 기반 상태 동기화                                                                                                |
| NFS 단일 장애점                  | Longhorn 전환 (Worker 3대 구성은 이미 이를 염두에 둠)                                                                            |
| OpenBao Auto-unseal 미적용       | 재시작마다 수동 unseal 필요. 외부 KMS 연동으로 해소                                                                              |
| TLS/HTTPS 미적용                 | `cert-manager` + 자체 서명 인증서                                                                                                |
| Alertmanager 미연동              | 기본 룰은 이미 포함되어 있어 Webhook 등록 20~30분으로 복구 가능                                                                  |
| CI 파이프라인 부재               | GitHub Actions. 차트를 Git에 둔 것(#18)이 이를 위한 준비                                                                         |
| Network Policy 미적용            | 서비스별 최소 통신 경로 제한                                                                                                     |
| 클러스터 밖 서버가 관측 사각지대 | node-exporter가 DaemonSet이라 K8s 노드 4대만 수집됩니다. PostgreSQL 데이터가 저장되는 NFS 서버의 디스크 포화는 탐지되지 않습니다 |

---

## 저장소 구조

```
├── charts/jypjt/                 # 애플리케이션 umbrella Helm 차트 (ArgoCD가 참조하는 경로)
│                                 #   Chart.yaml, values.yaml, templates/
├── argocd/                       # ArgoCD Application 정의 (차트 밖에 위치 — 순환 구조 방지)
├── manifests/                    # ArgoCD 관리 밖의 운영 도구 설정
│   ├── ingress-nginx/            #   Ingress-NGINX values
│   └── monitoring/               #   kube-prometheus-stack values
├── product-service/              # 상품 등록·조회 API (FastAPI)
├── image-processing-service/     # 큐 소비, 검수, 리사이징 (Pillow)
├── web-ui/                       # 시연용 정적 웹 UI (nginx:alpine)
├── migrations/                   # DB 스키마 (001_init_schema.sql + run_migration.py)
├── scripts/                      # cleanup_temp_images.py, locustfile.py
├── demo/
│   ├── local/                    # 로컬 docker compose 시연 (MinIO 포함)
│   └── cluster/                  # 실제 NHN Cloud 클러스터 시연 (데이터 초기화 Job)
└── docs/                         # 로드맵, 회고, 아키텍처 다이어그램 3종
```

### 설계 의도가 담긴 배치 두 가지

- `argocd/`를 차트 밖에 둔 이유: 차트 안에 넣으면 "이 차트를 배포하라는 지시"가 그 차트 안에 있는 순환 구조가 됩니다.
- `manifests/`와 `charts/`를 나눈 이유: 앞서 말한 "배포 대상 앱 vs 배포를 수행하는 도구" 구분이 디렉터리 수준에도 반영돼 있습니다. `charts/`는 ArgoCD가 관리하고, `manifests/`는 `helm upgrade`로 직접 적용합니다. 다만 ServiceMonitor만은 예외적으로 `charts/`에 있는데, 그건 "Prometheus 설정"이 아니라 "우리 앱이 무엇을 노출하는가에 대한 선언" 이라 앱의 일부이기 때문입니다.

### 로컬 실행

저장소 루트의 `docker-compose.yml`로 전체 스택(서비스 2종 + PostgreSQL + Redis + RabbitMQ)을 띄울 수 있습니다. `.env.example`을 복사해 Object Storage 자격증명을 채우면 됩니다.

---

## 문서

### 인프라 · 운영 기록

| 문서                                                       | 내용                                                        |
| ---------------------------------------------------------- | ----------------------------------------------------------- |
| [로드맵 및 의사결정 기록](./docs/k8s_portfolio_roadmap.md) | 단계별 계획·체크포인트, 의사결정 40건, 트러블슈팅 전체 기록 |
| [회고 및 장애 분석(RCA)](./docs/retrospective.md)          | 시나리오별 RCA, 정량 지표, 시행착오, 배운 것                |
| [진행 로그](./docs/project_schedule_log.md)                | 날짜별 실제 작업 기록, 계획 대비 편차                       |

### 애플리케이션 문서

| 문서                                         | 내용                                                  |
| -------------------------------------------- | ----------------------------------------------------- |
| [ARCHITECTURE.md](./ARCHITECTURE.md)         | 서비스 간 흐름, 데이터 모델, 테이블 소유권            |
| [APPLICATION_SPEC.md](./APPLICATION_SPEC.md) | API 스펙, 상태 전이 규칙                              |
| [RELEASE_NOTES.md](./RELEASE_NOTES.md)       | 이미지 `v0.1.0`~`v0.1.4`, Helm Chart 버전별 변경 내역 |
| [TESTING.md](./TESTING.md)                   | 테스트 절차                                           |
| [demo/README.md](./demo/README.md)           | 시연용 데이터 생성 및 초기화                          |
