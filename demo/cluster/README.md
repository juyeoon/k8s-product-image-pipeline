# 클러스터 데모 (NHN Cloud)

발표 당일 실제 클러스터에서 진행하는 시연입니다. 시연 대본 자체는
[`docs/demo_script_skeleton.md`](../../docs/demo_script_skeleton.md)를 참고하세요. 이 문서는
그 중 **데이터 초기화** 절차만 다룹니다.

`demo/local/reset_demo_data.sh`는 로컬 docker compose 전용(MinIO, localhost)이라 여기서는
쓸 수 없습니다. DB/Redis 접속 정보가 클러스터 안(`db-credentials` Secret, `app-config`
ConfigMap)에만 있어서, 대신 `reset_demo_data.py`를 K8s Job으로 실행합니다.

## 리허설/시연 사이에 데이터 비우기

```bash
# 1) 스크립트를 ConfigMap으로 등록 (최초 1회, 또는 스크립트 수정 시 재등록)
kubectl create configmap reset-demo-script \
  --from-file=demo/cluster/reset_demo_data.py \
  -n jypjt --dry-run=client -o yaml | kubectl apply -f -

# 2) Job 실행 (반복 시연 때마다 이 명령만 다시 실행 — generateName이라 매번 새 이름)
kubectl create -f demo/cluster/reset-demo-data-job.yaml

# 3) 결과 확인
kubectl get jobs -n jypjt
kubectl logs -n jypjt job/<방금 생성된 Job 이름>
```

`db-migration-job.yaml`과 동일한 패턴으로, `product-service` 이미지(psycopg2/redis 라이브러리
포함)를 재사용하고 기존 Secret/ConfigMap을 `envFrom`으로 그대로 주입합니다. `products`/
`product_images`를 `TRUNCATE ... RESTART IDENTITY`로 비우고 Redis 캐시도 지우지만,
**NHN Cloud Object Storage에 쌓인 이미지 파일은 지우지 않습니다** — 버킷 정리가 필요하면
`scripts/cleanup_temp_images.py`와는 별개로 수동 처리해야 합니다.

`reset-demo-data-job.yaml`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  generateName: reset-demo-data-
  namespace: jypjt
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: reset-demo-data
          image: harbor.jypjt.local/jypjt/product-service:v0.1.4
          command: ["python", "/scripts/reset_demo_data.py", "--yes"]
          envFrom:
            - secretRef:
                name: db-credentials
            - configMapRef:
                name: app-config
          volumeMounts:
            - name: script
              mountPath: /scripts
      volumes:
        - name: script
          configMap:
            name: reset-demo-script
```

## 시연 중 쓸 이미지

로컬 데모용으로 만든 `demo/local/images/`의 노이즈 이미지(백로그 시연용)와 반려용 저해상도
이미지를 그대로 재사용해도 됩니다. 클러스터 전용 이미지가 따로 필요하지는 않습니다.
