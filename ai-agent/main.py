import logging

# Configure root + shiftleft loggers so our logger.info(...) calls show up
# under uvicorn on Render (uvicorn only configures its own loggers by default).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logging.getLogger("shiftleft").setLevel(logging.INFO)

from app.app_factory import create_app


app = create_app()

