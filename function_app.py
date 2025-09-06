import os
import azure.functions as func
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Lee cadena desde env (en local la pondrás en local.settings.json;
# en Azure pondrás Key Vault Reference en App Settings)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida. Configúrala en local.settings.json o en App Settings.")


# Crea pool global (mejor rendimiento en frío)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"ssl": {}}  # Azure MySQL exige TLS
)

app = func.FunctionApp()

@app.function_name(name="profile")
@app.route(route="profile/{username?}", auth_level=func.AuthLevel.ANONYMOUS)
def profile(req: func.HttpRequest) -> func.HttpResponse:
    username = req.route_params.get("username") or req.params.get("username") or "juan"
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, full_name, profile_photo_url FROM profiles WHERE username = :u LIMIT 1"),
                {"u": username}
            ).mappings().first()
        if not row:
            return func.HttpResponse(
                body='{"error":"user_not_found"}',
                status_code=404,
                mimetype="application/json"
            )
        return func.HttpResponse(
            body=(
                f'{{"id":{row["id"]},"username":"{row["username"]}",'
                f'"name":"{row["full_name"]}","profile_photo_url":"{row["profile_photo_url"]}"}}'
            ),
            mimetype="application/json"
        )
    except SQLAlchemyError as e:
        return func.HttpResponse(
            body=f'{{"status":"db_error","detail":"{str(e.__cause__ or e)}"}}',
            status_code=500,
            mimetype="application/json"
        )
