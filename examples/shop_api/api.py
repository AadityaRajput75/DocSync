from fastapi import FastAPI

from pricing import calculate_total

app = FastAPI()


@app.get("/products")
def list_products(limit: int = 10):
    """List product identifiers with a configurable result limit."""
    return {"products": list(range(limit))}


@app.post("/orders")
def create_order(quantity: int = 1):
    """Create an order priced at ten units per item."""
    return {"total": calculate_total(10, quantity)}


@app.delete("/orders/{order_id}")
def cancel_order(order_id: int):
    """Cancel an order by identifier."""
    return {"id": order_id, "cancelled": True}
