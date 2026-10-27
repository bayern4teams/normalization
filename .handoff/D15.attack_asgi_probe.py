"""Direct ASGI scope probes: client None / unix / odd types, websocket. Run with uv run --python 3.12."""
import asyncio
from normapi.app import create_app
app = create_app()

async def call(scope):
    out = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(m): out.append(m)
    try:
        await app(scope, receive, send)
    except Exception as e:
        return f"EXC {type(e).__name__}: {e}"
    return [m.get("status") or m.get("type") for m in out][:2]

def http(client, host=b"localhost", path="/openapi.json"):
    return {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": [(b"host", host)], "client": client, "server": ("127.0.0.1", 80)}
async def main():
    for c in [None, ("", 0), ("unix", 0), ["127.0.0.1", 1], ("127.0.0.1", 1), ("::ffff:127.0.0.1", 1), ("127.0.0.1\n", 1),
              ("8.8.8.8", 1), (b"127.0.0.1", 1), ("localhost", 1), ()]:
        print("http client", repr(c), "->", await call(http(c)))
    for c in [None, ("8.8.8.8", 1), ("127.0.0.1", 1)]:
        s = http(c); s["type"] = "websocket"; s["scheme"] = "ws"; s["subprotocols"] = []
        print("ws client", repr(c), "->", await call(s))
    s = http(("8.8.8.8", 1)); s.pop("client")
    print("http no client key ->", await call(s))
asyncio.run(main())
