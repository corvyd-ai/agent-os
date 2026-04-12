"""agent-os Dashboard — FastAPI backend + bundled frontend.

The API is exposed under /api/*. When a built dashboard frontend is available,
the same FastAPI app serves it at / as static files, so a single
`agent-os dashboard` invocation is enough for a production deployment.

Frontend asset lookup order:
1. `<package>/_frontend/` — bundled into the wheel via hatchling force-include.
   This is the normal path for `pip install agent-os[dashboard]` users.
2. `<package>/frontend/dist/` — sibling directory for editable installs
   (`pip install -e .`) where someone has run `npm run build` locally.

If neither exists, the app still works as an API-only service (the usual dev
flow, where the frontend is served by Vite on a separate port and proxies /api
requests to this backend).
"""

import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent_os import __version__

from .routers import agents, controls, conversation, costs, feedback, health, messages, notes, overview, strategy, tasks

app = FastAPI(
    title="agent-os Dashboard",
    description="Observability dashboard for the agent-os platform",
    version=__version__,
)

# CORS for the Vite dev server (local development only — in production the
# frontend is served from the same origin, so CORS isn't involved).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

# API routers — all prefixed with /api internally
app.include_router(overview.router)
app.include_router(agents.router)
app.include_router(tasks.router)
app.include_router(costs.router)
app.include_router(strategy.router)
app.include_router(messages.router)
app.include_router(health.router)
app.include_router(conversation.router)
app.include_router(feedback.router)  # legacy /api/feedback routes (backward compat)
app.include_router(notes.router)  # new /api/notes routes
app.include_router(controls.router)  # schedule, budget, autonomy, backlog controls


@app.get("/api/ping")
async def ping():
    return {"status": "ok"}


@app.get("/api/info")
async def info():
    return {"version": __version__}


def _find_frontend_dist() -> pathlib.Path | None:
    """Locate the built dashboard frontend, if any."""
    here = pathlib.Path(__file__).resolve().parent  # .../agent_os/dashboard/

    # 1. Wheel install: force-included at <package>/_frontend/
    bundled = here / "_frontend"
    if bundled.is_dir():
        return bundled

    # 2. Editable install: frontend/dist/ is a sibling directory
    editable = here / "frontend" / "dist"
    if editable.is_dir():
        return editable

    return None


_dist = _find_frontend_dist()
if _dist is not None:
    # html=True serves index.html at / and falls back to it for unknown paths,
    # which the React app needs for client-side routing.
    # Mounted LAST so /api/* routes registered above take precedence.
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
