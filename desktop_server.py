"""Private loopback server owned by the desktop process and its Windows job."""
import os
import uvicorn
from backend.server import app
from backend import library
from backend.catalog_defaults import seed_catalogs
from backend.starter_library import seed_starter_library

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ["PEREPLET_PORT"]), log_level="info"))

@app.post('/api/shutdown')
async def shutdown():
    server.should_exit = True
    return {"stopping": True}

if __name__ == '__main__':
    seed_starter_library()
    seed_catalogs()
    server.run()
