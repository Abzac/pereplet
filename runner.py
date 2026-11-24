"""Loopback-only application host."""
import os
import uvicorn
from backend.server import app

config = uvicorn.Config(app, host='127.0.0.1', port=int(os.environ.get('PEREPLET_PORT', '18765')), log_level='info')
server = uvicorn.Server(config)


@app.post('/api/shutdown')
async def shutdown():
    server.should_exit = True
    return {'stopping': True}


if __name__ == '__main__':
    from backend import library
    from backend.catalog_defaults import seed_catalogs
    from backend.starter_library import seed_starter_library
    seed_starter_library()
    seed_catalogs()
    server.run()
