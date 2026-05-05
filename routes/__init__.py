"""Flask blueprints — one module per domain.

Imported in server.py like:
    from routes.auth   import bp as auth_bp
    from routes.apps   import bp as apps_bp
    ...
    app.register_blueprint(auth_bp)
"""
