# function_app.py
import os
import azure.functions as func
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional

app = func.FunctionApp()
_engine: Optional[any] = None  # cache global

def get_engine():
    """Crea el engine sólo cuando se necesita, y lo cachea."""
    global _engine
    if _engine is None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            # No reventar el indexado; devolver None y que la función responda 500 con mensaje claro
            return None
        _engine = create_engine(
            db_url, pool_pre_ping=True, pool_recycle=300, connect_args={"ssl": {}}
        )
    return _engine

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    # Health NO debe depender de la DB
    return func.HttpResponse('{"status":"ok"}', mimetype="application/json")

@app.route(route="profile/{username?}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def profile(req: func.HttpRequest) -> func.HttpResponse:
    username = req.route_params.get("username") or req.params.get("username") or "juan"
    engine = get_engine()
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
