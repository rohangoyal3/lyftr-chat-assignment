import os

import uvicorn

from .main import create_app


if __name__ == "__main__":
    app = create_app()
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
