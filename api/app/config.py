"""Runtime configuration.

Everything that differs between local, test and production lives here. The two flags that matter
most are ``FAKE_GOOGLE`` and ``FAKE_LLM``: with both on, the whole backend runs with no network and
no credentials. With either off, the matching block of settings below has to be filled in; the
README lists them per client.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _alias(*names: str) -> AliasChoices:
    """The field name first so ``Settings(field=...)`` beats a stray environment variable."""
    return AliasChoices(*names)


# The value that ships in this repository. ``create_app`` refuses to start with it outside local
# and test - see ``app.main.guard_environment``.
DEFAULT_SESSION_SECRET = "dev-only-session-secret-change-me"
MIN_SESSION_SECRET_LENGTH = 32
# The two environments where the developer conveniences (a default secret, AUTH_DEV_USER, a
# wildcard CORS origin, a cookie without Secure) are allowed.
UNGUARDED_ENVIRONMENTS = ("local", "test")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- core -------------------------------------------------------------------------------
    app_name: str = "Meeting Desk"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://meetingdesk:meetingdesk@localhost:5432/meetingdesk"
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- fakes ------------------------------------------------------------------------------
    fake_google: bool = True
    fake_llm: bool = True
    seed_demo: bool = True

    # --- auth -------------------------------------------------------------------------------
    session_secret: str = DEFAULT_SESSION_SECRET
    session_cookie: str = "md_session"
    session_max_age_days: int = 30
    # The OAuth "state" round trip rides on Starlette's SessionMiddleware. Its own cookie name so it
    # cannot be confused with the sign-in cookie above, and ten minutes rather than a browser
    # session: nothing in it is worth keeping once the flow is over.
    state_cookie: str = "md_oauth_state"
    state_cookie_max_age_seconds: int = 600
    # When set, every request is authenticated as this email without touching Google. Local and
    # tests only; a deployment must leave it empty.
    auth_dev_user: str | None = None
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oidc_redirect_uri: str = "http://localhost:8000/auth/callback"
    google_hosted_domain: str = "simpleo.ai"
    web_base_url: str = "http://localhost:5173"
    # The built web app (``web/dist``). When set, the API serves it at "/" with an SPA fallback so
    # one container answers both; empty means the API is API-only and Vite serves the app.
    web_dist: str = ""
    # Comma-separated emails put on the allow-list as admins at every startup. This is how the
    # first admin gets in on a fresh database in real mode: with ``FAKE_GOOGLE=0`` nothing seeds
    # the allow-list, so without it every sign-in is refused and there is nobody to ask. Idempotent;
    # promotes a member to admin, never demotes; removing an email here does not remove the entry.
    bootstrap_admins: str = ""

    @property
    def bootstrap_admin_emails(self) -> list[str]:
        seen: list[str] = []
        for raw in self.bootstrap_admins.split(","):
            email = raw.strip().lower()
            if email and "@" in email and email not in seen:
                seen.append(email)
        return seen

    # --- admin connections (the OAuth app the Google clients run as) -------------------------
    # "Connect an account" is the authorization-code flow with offline access; the callback lands
    # here. The refresh token is Fernet-encrypted with TOKEN_KEY before it is stored.
    google_connect_redirect_uri: str = "http://localhost:8000/admin/connections/callback"
    token_key: str = Field("", validation_alias=_alias("token_key", "MEETING_DESK_TOKEN_KEY"))
    token_key_previous: str = Field(
        "", validation_alias=_alias("token_key_previous", "MEETING_DESK_TOKEN_KEY_PREVIOUS")
    )
    token_key_version: int = Field(
        1, validation_alias=_alias("token_key_version", "MEETING_DESK_TOKEN_KEY_VERSION")
    )

    # --- google api behaviour ----------------------------------------------------------------
    google_api_timeout_seconds: float = 30.0
    google_max_retries: int = 5  # 429 / rateLimitExceeded, exponential backoff
    google_backoff_base_seconds: float = 0.5
    google_connection_backoff_seconds: int = 60  # a rate-limited connection is skipped this long
    sheets_max_rows: int = 5000  # the table region is never read past this row

    # --- behaviour --------------------------------------------------------------------------
    display_timezone: str = "Asia/Kolkata"
    calendar_cache_seconds: int = 60
    # Refresh skips the cache, but not more often than this: a held-down button must not become one
    # Calendar call per click per connection.
    calendar_refresh_min_seconds: int = 10
    calendar_lookback_days: int = 7
    tab_read_max_age_seconds: int = 300
    transfer_undo_minutes: int = 10
    point_undo_seconds: int = 10
    soft_delete_retention_days: int = 30

    # --- extraction -------------------------------------------------------------------------
    extraction_provider: str = "fake"  # fake | vertex | bedrock
    vertex_project: str = ""
    vertex_location: str = "asia-south1"
    vertex_model: str = "gemini-2.5-flash"
    bedrock_region: str = "ap-south-1"
    # Bedrock has no Gemini; the fallback runs a Claude model in Mumbai. Confirm the id per account.
    bedrock_model: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    bedrock_fallback_enabled: bool = Field(
        False, validation_alias=_alias("bedrock_fallback_enabled", "EXTRACT_FALLBACK_TO_BEDROCK")
    )
    extraction_max_output_tokens: int = 8192

    # --- telemetry (docs/ALERT-EMISSION-STANDARD-SUMMARY.md) --------------------------------
    # /metrics is served by a second ASGI app on its own port, never on the API's router, so the
    # public ingress cannot reach it. Off in tests: the socket guard forbids listening sockets.
    metrics_enabled: bool = True
    metrics_port: int = 9464
    metrics_host: str = "0.0.0.0"
    log_level: str = "INFO"
    app_version: str = "0.1.0"
    git_commit: str = "unknown"

    # --- jobs (procrastinate on Postgres) ---------------------------------------------------
    # Off by default so a SQLite run and the tests need no queue; the route then runs extraction
    # inline. On, the API enqueues and ``make worker`` runs the tasks.
    jobs_enabled: bool = False
    jobs_database_url: str = ""  # defaults to DATABASE_URL

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_guarded(self) -> bool:
        """True in every environment that is not local or test: the startup guards apply."""
        return self.environment not in UNGUARDED_ENVIRONMENTS

    @property
    def jobs_conninfo(self) -> str:
        """A libpq conninfo for procrastinate's psycopg connector, from the SQLAlchemy URL."""
        url = self.jobs_database_url or self.database_url
        return url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests call this after changing the environment."""
    get_settings.cache_clear()
