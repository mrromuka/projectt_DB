
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'buyer';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check') THEN
        ALTER TABLE users
            ADD CONSTRAINT users_role_check CHECK (role IN ('buyer', 'seller', 'admin'));
    END IF;
END $$;

-- Продавец = аккаунт пользователя + запись в sellers
ALTER TABLE sellers ADD COLUMN IF NOT EXISTS user_id INT UNIQUE REFERENCES users(user_id);

-- Товар можно скрыть (вместо удаления, чтобы не ломать историю заказов)
ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
