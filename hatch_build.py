"""Custom hatchling build hook for agent-os.

Conditionally bundles the built dashboard frontend (dashboard/frontend/dist/)
into the wheel at agent_os/dashboard/_frontend/ — but only when the dist
directory actually exists. This lets `pip install -e .` succeed without
requiring Node.js to be present at install time, while still producing a
self-contained wheel when `python -m build` runs after `npm run build`.

Activated via `[tool.hatch.build.targets.wheel.hooks.custom]` in pyproject.toml.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        dist = Path(self.root) / "dashboard" / "frontend" / "dist"
        if not dist.is_dir():
            # No built frontend — produce an API-only wheel. Dev/test installs
            # hit this path. Production wheel builds in CI build the frontend
            # first, so this never triggers there.
            return

        if "force_include" not in build_data:
            build_data["force_include"] = {}
        build_data["force_include"][str(dist)] = "agent_os/dashboard/_frontend"
