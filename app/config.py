import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _database_uri():
    # Render (and most PaaS providers) inject DATABASE_URL for the attached Postgres
    # instance; SQLAlchemy 1.4+/2.0 requires the "postgresql://" scheme, not "postgres://"
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("postgres://", "postgresql://", 1)
    return "sqlite:///" + os.path.join(BASE_DIR, "instance", "emba.db")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # 4 MB max upload
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}
    SITE_NAME = "IBA EMBA Member Association"
    DIRECTORY_PAGE_SIZE = 20
