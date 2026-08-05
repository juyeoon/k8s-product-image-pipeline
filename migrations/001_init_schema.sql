-- Product Service 소유
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price INTEGER NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft/processing/active/rejected
    rejection_reason TEXT,        -- rejected일 때만 값 존재
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
