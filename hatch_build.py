"""Builds the web app into the wheel (ADR 30 in docs/adr).

A wheel carries `src/openticker/adapters/inbound/web/dist/`, which `pnpm
build` in `ui/` writes. With pnpm this hook builds it; without, a dist/
already there is used, and a wheel without one serves the "isn't built" page
(the REST API and MCP work either way). Editable installs skip it: a
contributor runs `pnpm build` or `pnpm dev` themselves.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebAppBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        root = Path(self.root)
        ui = root / "ui"
        built = root / "src/openticker/adapters/inbound/web/dist/index.html"
        pnpm = shutil.which("pnpm")
        if pnpm and (ui / "package.json").exists():
            subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=ui, check=True)
            subprocess.run([pnpm, "build"], cwd=ui, check=True)
        elif built.exists():
            print("pnpm not found: packaging the web app already built", file=sys.stderr)
        else:
            print(
                "warning: pnpm not found and the web app isn't built; this wheel will serve "
                "the 'isn't built' page (the REST API and MCP still work)",
                file=sys.stderr,
            )
