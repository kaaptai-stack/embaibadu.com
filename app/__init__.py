import os

from flask import Flask

from app.config import Config
from app.extensions import db, login_manager, csrf, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(os.path.join(app.instance_path), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth.routes import auth_bp
    from app.member.routes import member_bp
    from app.directory.routes import directory_bp
    from app.admin.routes import admin_bp
    from app.devtools.routes import devtools_bp
    from app.main.routes import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(member_bp)
    app.register_blueprint(directory_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(devtools_bp, url_prefix="/dev")

    @app.after_request
    def add_noindex_header(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.config import Config as Cfg

        return {"site_name": Cfg.SITE_NAME, "current_user_obj": current_user}

    return app
