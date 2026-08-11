# 로컬 데모 (docker compose)

`docker compose up`으로 전체 스택이 떠 있는 상태에서 실행합니다.

```
bash demo/local/run_demo.sh
```

무엇을 보여주는지:

1. **큐 백로그 시연**: `demo/local/images/demo_backlog_1.jpg` ~ `_5.jpg` (4600x4600, ~18MB 노이즈
   이미지)를 연속 업로드합니다. Image Processing Service는 `prefetch_count=1`이라 메시지를
   한 번에 하나씩만 처리하고, 이미지 1장 처리(다운로드 → 검수 → 3종 리사이징 → 업로드 → DB
   갱신)에 실제로 약 3~4초가 걸립니다. 5장을 한꺼번에 올리면 여러 상품이 동시에 `processing`
   상태로 큐에 쌓여 있다가 순서대로 `active`로 바뀌는 모습을 몇십 초에 걸쳐 볼 수 있습니다.
   → [http://localhost:8080](http://localhost:8080) 판매자 화면을 같이 띄워두고 배지 색이
   바뀌는 걸 보여주면 좋습니다.
2. **반려(rejected) 시연**: `demo_reject.jpg`(100x100, 최소 해상도 500px 미달)를 업로드해
   `rejected` 배지와 사유가 표시되는 것을 보여줍니다.
3. 스크립트 자신도 터미널에 각 상품의 상태를 1초 간격으로 출력하므로, 화면 공유 없이
   터미널만으로도 진행 상황을 설명할 수 있습니다.

## 리허설 사이에 데이터 비우기

`run_demo.sh`를 여러 번 돌려보면 상품이 계속 쌓입니다. 컨테이너를 재기동하지 않고 데이터만
비우려면:

```
bash demo/local/reset_demo_data.sh
```

Postgres의 `products`/`product_images`를 `TRUNCATE ... RESTART IDENTITY`로 비우고(다음 상품
id가 다시 1부터 시작), Redis 캐시와 MinIO에 쌓인 이미지(`temp/`, `products/`)까지 같이
지웁니다. 컨테이너 자체를 완전히 새로 만들고 싶다면(볼륨까지 밀고 싶을 때) 메인
[README.md](../../README.md)의 "발표 전 데이터 초기화" 섹션에 있는
`docker compose down -v && docker compose up --build -d`를 대신 쓰세요 — 더 확실하지만
재기동에 수십 초 더 걸립니다.

## 이미지 재생성

`demo/local/images/`는 git에 커밋하지 않습니다 (바이너리, 용량이 큼). 필요하면 아래 명령으로
다시 생성하세요 (image-processing-service 이미지에 이미 Pillow가 들어있어 재사용합니다):

```
docker compose build image-processing-service
docker run --rm -v "$(pwd)/demo/local:/demo" \
  k8s-product-image-pipeline-image-processing-service \
  python /demo/generate_demo_images.py
```

이미 파일이 있으면 건너뛰므로 안전하게 여러 번 실행할 수 있습니다.

## 처리 시간을 더 길게/짧게 조정하고 싶다면

`generate_demo_images.py`의 `BACKLOG_SPECS`에서 픽셀 크기를 조정하세요. 단, 노이즈 이미지는
압축이 거의 안 되기 때문에 파일 용량이 픽셀 수에 비례해서 커집니다 — `POST /products`의
20MB 제한을 넘기지 않도록 주의하세요 (4600x4600 기준 약 18MB).
