import sys, os, json, logging
import azure.functions as func
from typing import Optional
import socket
from urllib.parse import urlparse
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
    return func.HttpResponse('{"status":"ok", "version":"2.0"}', mimetype="application/json")

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

@app.function_name(name="diag")
@app.route(route="diag", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def diag(req: func.HttpRequest) -> func.HttpResponse:
    present = bool(os.getenv("DATABASE_URL"))
    eng = _get_engine()
    if not present:
        return func.HttpResponse('{"has_database_url":false}', mimetype="application/json", status_code=500)
    if eng is None:
        return func.HttpResponse('{"engine":"missing"}', mimetype="application/json", status_code=500)
    try:
        from sqlalchemy import text
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return func.HttpResponse('{"ok":true}', mimetype="application/json")
    except Exception as e:
        return func.HttpResponse(f'{{"ok":false,"detail":"{e}"}}', mimetype="application/json", status_code=500)

@app.function_name(name="diag_lite")
@app.route(route="diag-lite", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def diag_lite(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # No tocar SQL aquí, solo señales del runtime
        has_db_url = bool(os.getenv("DATABASE_URL"))
        try:
            import sqlalchemy  # noqa
            has_sqlalchemy = True
        except Exception:
            has_sqlalchemy = False

        payload = {
            "python": sys.version,
            "has_DATABASE_URL": has_db_url,
            "has_sqlalchemy": has_sqlalchemy,
            "env_flags": {
                "FUNCTIONS_WORKER_RUNTIME": os.getenv("FUNCTIONS_WORKER_RUNTIME"),
                "FUNCTIONS_EXTENSION_VERSION": os.getenv("FUNCTIONS_EXTENSION_VERSION"),
                "SCM_DO_BUILD_DURING_DEPLOYMENT": os.getenv("SCM_DO_BUILD_DURING_DEPLOYMENT"),
                "WEBSITE_RUN_FROM_PACKAGE": os.getenv("WEBSITE_RUN_FROM_PACKAGE"),
            }
        }
        return func.HttpResponse(json.dumps(payload), mimetype="application/json")
    except Exception as e:
        logging.exception("diag-lite failed")
        return func.HttpResponse(f'{{"error":"{e}"}}', mimetype="application/json", status_code=500)


@app.function_name(name="diag_db")
@app.route(route="diag-db", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def diag_db(req: func.HttpRequest) -> func.HttpResponse:
    info = {"has_db_url": bool(os.getenv("DATABASE_URL")), "sqlalchemy_error": "", "pymysql_error": ""}
    # 1) Importar drivers
    try:
        import sqlalchemy as _sa  # noqa
        info["has_sqlalchemy"] = True
    except Exception as e:
        info["has_sqlalchemy"] = False
        info["sqlalchemy_error"] = str(e)

    try:
        import pymysql as _pm  # noqa
        info["has_pymysql"] = True
    except Exception as e:
        info["has_pymysql"] = False
        info["pymysql_error"] = str(e)

    # 2) Descomponer URL y probar DNS/TCP 3306
    dsn = os.getenv("DATABASE_URL", "")
    host = None
    try:
        # sqlalchemy URL; para parseo básico usamos urlparse sobre la parte después de '://'
        # ejemplo mysql+pymysql://user:pass@host:3306/db
        host = dsn.split("@", 1)[-1].split("/", 1)[0].split(":")[0] if dsn else None
        info["db_host"] = host
        if host:
            ip = socket.gethostbyname(host)
            info["db_host_ip"] = ip
            with socket.create_connection((host, 3306), timeout=5):
                info["tcp_3306_ok"] = True
        else:
            info["tcp_3306_ok"] = False
    except Exception as e:
        info["tcp_3306_ok"] = False
        info["tcp_error"] = str(e)

    # 3) Probar SELECT 1 con SQLAlchemy (TLS implícito)
    try:
        eng = _get_engine()
        if eng is None:
            info["engine"] = "not-initialized"
        else:
            from sqlalchemy import text
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            info["engine_connect_ok"] = True
    except Exception as e:
        info["engine_connect_ok"] = False
        info["engine_error"] = str(e)

    return func.HttpResponse(json.dumps(info), mimetype="application/json")