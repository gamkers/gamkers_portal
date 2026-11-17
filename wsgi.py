import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app

application = create_app()

if __name__ == "__main__":
    app_env = os.getenv("APP_ENV", "production").lower()

    if app_env == "development":
        application.run(
            host="127.0.0.1",
            port=18080,
            debug=True
        )
    else:
        raise RuntimeError(
            "Use a production WSGI server to run this application."
        )
