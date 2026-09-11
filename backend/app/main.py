"""
IMedora Backend — Application Entry Point

This is a placeholder entry point. No routes, database connections,
or business logic have been implemented yet. Once a web framework
is chosen (e.g. FastAPI), this file will bootstrap the application,
register API routers from `app/api/`, and wire up middleware from
`app/middleware/`.
"""


def create_app():
    """
    Placeholder application factory.

    Future responsibilities:
      - Initialize the web framework app instance
      - Register API routers (auth, users, hospitals, departments,
        devices, maintenance, tickets, parts, reports, risk,
        quality assurance, AI assistant)
      - Attach middleware (auth, logging, error handling, CORS)
      - Load configuration from environment variables
    """
    raise NotImplementedError("Application factory not yet implemented.")


if __name__ == "__main__":
    create_app()
