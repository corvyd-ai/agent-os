"""agent-os Dashboard — FastAPI backend.

Read-only API that serves agent-os filesystem data to the dashboard frontend.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import agents, controls, conversation, costs, feedback, health, messages, notes, overview, strategy, tasks

app = FastAPI(
    title="agent-os Dashboard",
    description="Read-only observability dashboard for the agent-os platform",
    version="0.1.0",
)

# CORS for Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5175"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(overview.router)
app.include_router(agents.router)
app.include_router(tasks.router)
app.include_router(costs.router)
app.include_router(strategy.router)
app.include_router(messages.router)
app.include_router(health.router)
app.include_router(conversation.router)
app.include_router(feedback.router)  # legacy /api/feedback routes (backward compat)
app.include_router(notes.router)    # new /api/notes routes
app.include_router(controls.router)  # schedule, budget, autonomy, backlog controls


@app.get("/api/ping")
async def ping():
    return {"status": "ok"}
