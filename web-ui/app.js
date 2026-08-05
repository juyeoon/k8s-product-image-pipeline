const POLL_INTERVAL_MS = 2500;

const BADGE_LABEL = {
  draft: '등록 대기',
  processing: '처리 중',
  active: '판매 중',
  rejected: '반려',
};

const tabSeller = document.getElementById('tab-seller');
const tabBuyer = document.getElementById('tab-buyer');
const sellerView = document.getElementById('seller-view');
const buyerView = document.getElementById('buyer-view');
const productForm = document.getElementById('product-form');
const submitButton = document.getElementById('submit-button');
const sellerProductList = document.getElementById('seller-product-list');
const buyerProductGrid = document.getElementById('buyer-product-grid');
const toast = document.getElementById('toast');
const imageModal = document.getElementById('image-modal');
const modalBackdrop = document.getElementById('modal-backdrop');
const modalClose = document.getElementById('modal-close');
const modalImage = document.getElementById('modal-image');
const modalCaption = document.getElementById('modal-caption');
const modalSizeTabs = document.getElementById('modal-size-tabs');
const modalMeta = document.getElementById('modal-meta');

// 실제로 Image Processing Service가 3가지 사이즈로 리사이징했다는 것을 데모 중 눈으로
// 확인할 수 있도록, 사이즈별 실제 픽셀 크기(naturalWidth/Height)와 파일 용량(Content-Length)을
// 탭을 눌러볼 때마다 보여준다.
const SIZE_ORDER = ['thumbnail', 'detail', 'zoom'];
const SIZE_LABEL = { thumbnail: '썸네일', detail: '상세', zoom: '확대' };

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove('hidden');
  setTimeout(() => {
    toast.classList.add('hidden');
  }, 2000);
}

function switchView(view) {
  const showSeller = view === 'seller';
  sellerView.classList.toggle('hidden', !showSeller);
  buyerView.classList.toggle('hidden', showSeller);
  tabSeller.classList.toggle('active', showSeller);
  tabBuyer.classList.toggle('active', !showSeller);
  if (!showSeller) {
    loadBuyerProducts();
  }
}

tabSeller.addEventListener('click', () => switchView('seller'));
tabBuyer.addEventListener('click', () => switchView('buyer'));

async function loadSellerProducts() {
  // 브라우저 세션 상태가 아니라 서버에서 직접 조회한다 - 이 브라우저의 폼으로 등록했든,
  // 다른 곳에서 API로(예: demo/run_demo.sh) 등록했든 상관없이 전체 상품과 상태 전이를 보여준다.
  try {
    const response = await fetch('/products?status=all');
    const products = await response.json();

    if (products.length === 0) {
      sellerProductList.innerHTML = '<li class="empty-message">아직 등록한 상품이 없습니다.</li>';
      return;
    }

    sellerProductList.innerHTML = products
      .map(
        (product) => `
          <li>
            <div class="product-row">
              <div>
                <span class="product-name">${escapeHtml(product.name)}</span>
                <span class="product-price">${product.price.toLocaleString()}원</span>
              </div>
              <span class="badge badge-${product.status}">${BADGE_LABEL[product.status] || product.status}</span>
            </div>
            ${product.rejection_reason ? `<div class="rejection-reason">사유: ${escapeHtml(product.rejection_reason)}</div>` : ''}
          </li>
        `
      )
      .join('');
  } catch (error) {
    sellerProductList.innerHTML = '<li class="empty-message">상품 목록을 불러오지 못했습니다.</li>';
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

productForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const name = document.getElementById('field-name').value;
  const price = Number(document.getElementById('field-price').value);
  const description = document.getElementById('field-description').value;
  const imageFile = document.getElementById('field-image').files[0];

  const formData = new FormData();
  formData.append('name', name);
  formData.append('price', price);
  formData.append('description', description);
  formData.append('image', imageFile);

  submitButton.disabled = true;
  submitButton.textContent = '등록 중...';

  try {
    const response = await fetch('/products', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      alert(`등록 실패: ${body.detail || response.status}`);
      return;
    }

    await response.json();
    await loadSellerProducts();
    productForm.reset();
    showToast('등록되었습니다');
  } catch (error) {
    alert(`등록 중 오류가 발생했습니다: ${error.message}`);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = '등록';
  }
});

async function loadBuyerProducts() {
  try {
    const response = await fetch('/products');
    const products = await response.json();

    if (products.length === 0) {
      buyerProductGrid.innerHTML = '<p class="empty-message">판매 중인 상품이 없습니다.</p>';
      return;
    }

    buyerProductGrid.innerHTML = products
      .map(
        (product) => `
          <div class="product-card" data-product-id="${product.id}">
            <img src="${product.thumbnail_url || ''}" alt="${escapeHtml(product.name)}" />
            <div class="name">${escapeHtml(product.name)}</div>
            <div class="price">${product.price.toLocaleString()}원</div>
            ${product.description ? `<div class="description">${escapeHtml(product.description)}</div>` : ''}
          </div>
        `
      )
      .join('');
  } catch (error) {
    buyerProductGrid.innerHTML = '<p class="empty-message">상품 목록을 불러오지 못했습니다.</p>';
  }
}

function formatBytes(bytes) {
  if (bytes == null) return '?';
  if (bytes < 1024) return `${bytes}B`;
  return `${(bytes / 1024).toFixed(1)}KB`;
}

async function fetchImageMeta(url) {
  // 파일 용량은 HEAD 요청의 Content-Length로, 실제 픽셀 크기는 이미지가 로드된 뒤
  // naturalWidth/naturalHeight로 읽는다 - 둘 다 서버가 실제로 다른 크기의 파일을
  // 만들었는지 확인할 수 있는 근거가 된다.
  let byteSize = null;
  try {
    const response = await fetch(url, { method: 'HEAD' });
    const contentLength = response.headers.get('content-length');
    if (contentLength) byteSize = Number(contentLength);
  } catch (error) {
    // 용량 조회 실패는 무시하고 픽셀 크기만 보여준다.
  }
  return byteSize;
}

function renderSizeTabs(imagesBySize, activeSizeType) {
  modalSizeTabs.innerHTML = SIZE_ORDER.filter((sizeType) => imagesBySize[sizeType])
    .map(
      (sizeType) => `
        <button type="button" class="size-tab-button${sizeType === activeSizeType ? ' active' : ''}" data-size-type="${sizeType}">
          ${SIZE_LABEL[sizeType]}
        </button>
      `
    )
    .join('');
}

async function showSizeImage(imagesBySize, sizeType, caption) {
  const url = imagesBySize[sizeType];
  if (!url) return;

  renderSizeTabs(imagesBySize, sizeType);
  modalCaption.textContent = caption;
  modalMeta.textContent = '불러오는 중...';

  modalImage.onload = async () => {
    const byteSize = await fetchImageMeta(url);
    modalMeta.textContent =
      `${SIZE_LABEL[sizeType]} · 실제 픽셀 크기 ${modalImage.naturalWidth} × ${modalImage.naturalHeight}px` +
      (byteSize != null ? ` · 파일 용량 ${formatBytes(byteSize)}` : '');
  };
  modalImage.src = url;
  modalImage.alt = caption;
}

function openImageModal(imagesBySize, caption) {
  const defaultSize = SIZE_ORDER.find((sizeType) => imagesBySize[sizeType]);
  imageModal.classList.remove('hidden');
  if (defaultSize) showSizeImage(imagesBySize, defaultSize, caption);
}

function closeImageModal() {
  imageModal.classList.add('hidden');
  modalImage.onload = null;
  modalImage.src = '';
  modalMeta.textContent = '';
}

modalSizeTabs.addEventListener('click', (event) => {
  const button = event.target.closest('.size-tab-button');
  if (!button || !currentImagesBySize) return;
  showSizeImage(currentImagesBySize, button.dataset.sizeType, modalCaption.textContent);
});

let currentImagesBySize = null;

buyerProductGrid.addEventListener('click', async (event) => {
  const card = event.target.closest('.product-card');
  if (!card) return;

  const productId = card.dataset.productId;
  const name = card.querySelector('.name')?.textContent || '';
  const thumbnailUrl = card.querySelector('img')?.src || '';

  // 우선 썸네일만으로 즉시 모달을 열고, 상세 조회 결과가 오면 탭을 채운다.
  currentImagesBySize = { thumbnail: thumbnailUrl };
  openImageModal(currentImagesBySize, name);

  try {
    const response = await fetch(`/products/${productId}`);
    if (!response.ok) return;
    const detail = await response.json();
    currentImagesBySize = Object.fromEntries((detail.images || []).map((img) => [img.size_type, img.url]));
    const defaultSize = SIZE_ORDER.find((sizeType) => currentImagesBySize[sizeType]) || 'thumbnail';
    showSizeImage(currentImagesBySize, defaultSize, name);
  } catch (error) {
    // 상세 조회에 실패해도 이미 열려 있는 썸네일 모달은 그대로 유지한다.
  }
});

modalClose.addEventListener('click', closeImageModal);
modalBackdrop.addEventListener('click', closeImageModal);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeImageModal();
});

loadSellerProducts();
setInterval(loadSellerProducts, POLL_INTERVAL_MS);
