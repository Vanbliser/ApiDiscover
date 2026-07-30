from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()
DIR = Path(__file__).parent


@app.get("/index.html")
def index():
    return FileResponse(DIR / "index.html")


@app.get("/page2.html")
def page2():
    return FileResponse(DIR / "page2.html")


@app.get("/app.js")
def app_js():
    return FileResponse(DIR / "app.js", media_type="application/javascript")


@app.get("/api/users")
def users(limit: int = 10):
    return {"users": [{"id": i, "name": f"user{i}"} for i in range(limit)]}


@app.get("/api/orders/{order_id}")
def order(order_id: int):
    return {"order_id": order_id, "status": "shipped"}


@app.get("/api/hidden/stats")
def hidden_stats():
    """Never linked from any button/click handler — only discoverable via JS scanning."""
    return {"visits": 42, "hidden": True}
