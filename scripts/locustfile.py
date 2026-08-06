import random
from locust import HttpUser, task, between

class ProductBrowser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.product_ids = []
        resp = self.client.get("/products")
        if resp.status_code == 200:
            try:
                data = resp.json()
                self.product_ids = [item["id"] for item in data if "id" in item]
            except Exception:
                pass

    @task(3)
    def list_products(self):
        self.client.get("/products")

    @task(1)
    def view_product_detail(self):
        if self.product_ids:
            pid = random.choice(self.product_ids)
            self.client.get(f"/products/{pid}")