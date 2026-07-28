import asyncio

from app.crawl.session import create_session
from app.crawl.walker import DomWalker
from app.export.normalize import normalize_captures
from app.export.openapi import build_openapi_spec
from app.export.postman import build_postman_collection


async def main():
    session = create_session(headless=True)
    await session.start("http://localhost:8100/index.html")

    def on_status(status):
        print(f"[status] {status.value}")

    walker = DomWalker(session.page, max_steps=15, on_status_change=on_status)
    await walker.run()

    print(f"\nCaptured {len(session.captured)} raw requests")
    for c in session.captured[:10]:
        print(f"  {c.method} {c.url} -> {c.status_code}")

    endpoints = normalize_captures(session.captured)
    print(f"\nNormalized to {len(endpoints)} endpoints")
    for e in endpoints:
        print(f"  {e.method} {e.host}{e.path_template} (hits={e.hit_count})")

    spec = build_openapi_spec(endpoints)
    collection = build_postman_collection(endpoints)
    print(f"\nOpenAPI paths: {list(spec['paths'].keys())}")
    print(f"Postman items: {len(collection['item'])}")

    await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
