"""ASGI entry — bind PORT from the pipeline env file."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "config.asgi:application",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )
