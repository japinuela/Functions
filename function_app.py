import os, json, logging
import azure.functions as func
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


app = func.FunctionApp()

_have_sqlalchemy: Optional[bool] = None
_engine = None

def _try_import_sqlalchemy() -> bool:
    global _have_sqlalchemy
    if _have_sqlalchemy is None:
        try:
            from sqlalchemy import create_engine  # noqa
            _have_sqlalchemy = True
        except Exception as e:
            logging.exception("SQLAlchemy import failed")
            _have_sqlalchemy = False
    return _have_sqlalchemy

def _get_engine():
    global _engine
    if _engine is None:
        if not _try_import_sqlalchemy():
            return None
        from sqlalchemy import create_engine
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            return None
        _engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=300, connect_args={"ssl": {}})
    return _engine


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    # Health NO debe depender de la DB
    return func.HttpResponse('{"status":"ok"}', mimetype="application/json")

@app.route(route="profile/{username?}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def profile(req: func.HttpRequest) -> func.HttpResponse:
    username = req.route_params.get("username") or req.params.get("username") or "juan"
    present = bool(os.getenv("DATABASE_URL"))
    engine = _get_engine()
    if engine is None:
        return func.HttpResponse(
            '{"status":"config_error","detail":"DATABASE_URL no definido"}',
            status_code=500, mimetype="application/json"
        )
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, full_name, profile_photo_url "
                     "FROM profiles WHERE username = :u LIMIT 1"),
                {"u": username}
            ).mappings().first()
        if not row:
            return func.HttpResponse('{"error":"user_not_found"}', status_code=404, mimetype="application/json")
        body = (
            f'{{"id":{row["id"]},"username":"{row["username"]}",'
            f'"name":"{row["full_name"]}","profile_photo_url":"{row["profile_photo_url"]}"}}'
        )
        return func.HttpResponse(body, mimetype="application/json")
    except SQLAlchemyError as e:
        return func.HttpResponse(
            f'{{"status":"db_error","detail":"{str(e.__cause__ or e)}"}}',
            status_code=500, mimetype="application/json"
        )


@app.route(route="diag", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def diag(req: func.HttpRequest) -> func.HttpResponse:
    present = bool(os.getenv("DATABASE_URL"))
    engine_ok = False
    detail = None
    eng = _get_engine()
    if eng is None:
        detail = "no-sqlalchemy-or-no-DATABASE_URL"
    else:
        try:
            from sqlalchemy import text
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            engine_ok = True
        except Exception as e:
            detail = str(e)
            logging.exception("Engine connect failed")
    payload = {"has_sqlalchemy": _have_sqlalchemy, "has_database_url": present, "engine_connect_ok": engine_ok, "detail": detail}
    return func.HttpResponse(json.dumps(payload), mimetype="application/json")

# tu /health y /profile tal como los tienes
