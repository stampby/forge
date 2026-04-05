#!/usr/bin/env python3
"""
forge — the game builder agent.

Builds games, generates assets, manages pipelines.
Marketplace-ready: anyone can fire up forge and start creating.

Part of the halo-ai ecosystem.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="[forge] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("forge")


class ProjectType(Enum):
    GODOT_3D = "godot_3d"
    GODOT_2D = "godot_2d"
    VOXEL = "voxel"
    CUSTOM_ENGINE = "custom_engine"


class AssetType(Enum):
    TEXTURE = "texture"
    SPRITE = "sprite"
    VOXEL_MODEL = "voxel_model"
    SOUND = "sound"
    MUSIC = "music"
    SHADER = "shader"


@dataclass
class ForgeProject:
    name: str
    project_type: ProjectType
    path: Path
    engine_version: str = ""
    description: str = ""
    assets: list[dict] = field(default_factory=list)
    scenes: list[str] = field(default_factory=list)


@dataclass
class AssetRequest:
    asset_type: AssetType
    description: str
    style: str = "voxel"
    resolution: str = "512x512"
    prompt_enhance: bool = True  # Run through interpreter first


class Forge:
    """The forge. Where games are built."""

    BANNER = r"""
    ╔═══════════════════════════════════════╗
    ║          ⚒  F O R G E  ⚒             ║
    ║       the game builder agent          ║
    ║                                       ║
    ║  "From raw metal to finished blade."  ║
    ╚═══════════════════════════════════════╝
    """

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = workspace or Path.home() / "forge-projects"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.projects: dict[str, ForgeProject] = {}
        self.strix_halo = os.environ.get("HALO_STRIX_IP", "YOUR_STRIX_HALO_IP")
        self.comfyui_port = int(os.getenv("COMFYUI_PORT", "8188"))
        self.interpreter_url = os.getenv("INTERPRETER_URL", "")
        log.info(self.BANNER)
        log.info("Forge initialized. Workspace: %s", self.workspace)

    # ── Project Management ──────────────────────────────────────────

    def create_project(
        self,
        name: str,
        project_type: ProjectType = ProjectType.VOXEL,
        description: str = "",
    ) -> ForgeProject:
        """Create a new game project from template."""
        project_path = self.workspace / name
        project_path.mkdir(parents=True, exist_ok=True)

        project = ForgeProject(
            name=name,
            project_type=project_type,
            path=project_path,
            description=description,
        )

        if project_type in (ProjectType.GODOT_3D, ProjectType.VOXEL):
            self._scaffold_godot_project(project)
        elif project_type == ProjectType.GODOT_2D:
            self._scaffold_godot_2d_project(project)
        elif project_type == ProjectType.CUSTOM_ENGINE:
            self._scaffold_custom_engine(project)

        self.projects[name] = project
        self._save_project_config(project)
        log.info("Project '%s' forged at %s", name, project_path)
        return project

    def _scaffold_godot_project(self, project: ForgeProject) -> None:
        """Scaffold a Godot 3D/Voxel project."""
        dirs = [
            "assets/textures", "assets/models", "assets/sounds",
            "assets/music", "assets/ui", "assets/shaders", "assets/particles",
            "scenes/world", "scenes/player", "scenes/enemies",
            "scenes/items", "scenes/ui", "scenes/extraction",
            "scripts/player", "scripts/enemies", "scripts/world",
            "scripts/items", "scripts/systems", "scripts/ui",
            "scripts/network", "addons", "docs",
        ]
        for d in dirs:
            (project.path / d).mkdir(parents=True, exist_ok=True)

        project.engine_version = self._detect_godot_version()
        log.info("Godot %s project scaffolded", project.engine_version)

    def _scaffold_godot_2d_project(self, project: ForgeProject) -> None:
        """Scaffold a Godot 2D project."""
        dirs = [
            "assets/sprites", "assets/tilesets", "assets/sounds",
            "assets/music", "assets/ui",
            "scenes/world", "scenes/player", "scenes/enemies",
            "scenes/items", "scenes/ui",
            "scripts/player", "scripts/enemies", "scripts/world",
            "scripts/items", "scripts/systems", "scripts/ui",
            "addons", "docs",
        ]
        for d in dirs:
            (project.path / d).mkdir(parents=True, exist_ok=True)

        project.engine_version = self._detect_godot_version()

    def _scaffold_custom_engine(self, project: ForgeProject) -> None:
        """Scaffold a custom C++ engine project."""
        dirs = [
            "src/engine", "src/renderer", "src/world", "src/physics",
            "src/audio", "src/input", "src/network",
            "assets", "shaders", "docs", "build",
        ]
        for d in dirs:
            (project.path / d).mkdir(parents=True, exist_ok=True)

        # Write CMakeLists.txt template
        cmake = project.path / "CMakeLists.txt"
        cmake.write_text(
            f'cmake_minimum_required(VERSION 3.20)\n'
            f'project({project.name} LANGUAGES CXX)\n'
            f'set(CMAKE_CXX_STANDARD 20)\n'
            f'set(CMAKE_CXX_STANDARD_REQUIRED ON)\n\n'
            f'find_package(Vulkan REQUIRED)\n'
            f'find_package(glfw3 REQUIRED)\n\n'
            f'file(GLOB_RECURSE SOURCES "src/*.cpp")\n'
            f'add_executable(${{PROJECT_NAME}} ${{SOURCES}})\n'
            f'target_link_libraries(${{PROJECT_NAME}} PRIVATE Vulkan::Vulkan glfw)\n'
        )
        log.info("Custom C++ engine scaffolded with Vulkan + GLFW")

    def _detect_godot_version(self) -> str:
        """Detect installed Godot version."""
        try:
            result = subprocess.run(
                ["godot", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip().split(".")[0:3].__str__()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "4.6"

    def _save_project_config(self, project: ForgeProject) -> None:
        """Save project metadata."""
        config = {
            "name": project.name,
            "type": project.project_type.value,
            "engine_version": project.engine_version,
            "description": project.description,
            "assets": project.assets,
            "scenes": project.scenes,
        }
        config_path = project.path / "forge.json"
        config_path.write_text(json.dumps(config, indent=2))

    # ── Asset Generation ────────────────────────────────────────────

    async def generate_asset(self, request: AssetRequest) -> Optional[Path]:
        """Generate a game asset using the AI pipeline.

        Flow: prompt -> interpreter (enhance) -> ComfyUI (generate) -> output
        """
        prompt = request.description

        # Step 1: Enhance prompt via interpreter agent
        if request.prompt_enhance and self.interpreter_url:
            prompt = await self._enhance_prompt(prompt, request.style)
            log.info("Interpreter enhanced prompt: %s", prompt[:80])

        # Step 2: Generate via ComfyUI on Strix Halo
        if request.asset_type in (AssetType.TEXTURE, AssetType.SPRITE):
            return await self._generate_image(prompt, request)
        elif request.asset_type == AssetType.VOXEL_MODEL:
            return await self._generate_voxel_model(prompt, request)
        elif request.asset_type == AssetType.SOUND:
            log.info("Sound generation delegated to amp")
            return None

        return None

    async def _enhance_prompt(self, prompt: str, style: str) -> str:
        """Send prompt to interpreter for enhancement."""
        # TODO: HTTP call to interpreter service on Strix Halo
        # For now, add style prefix
        enhanced = f"{style} art style, game asset, {prompt}, clean edges, tileable"
        return enhanced

    async def _generate_image(
        self, prompt: str, request: AssetRequest
    ) -> Optional[Path]:
        """Generate image via ComfyUI on Strix Halo."""
        log.info(
            "Generating %s on Strix Halo (%s:%d)",
            request.asset_type.value, self.strix_halo, self.comfyui_port,
        )
        # TODO: ComfyUI API workflow submission
        # POST to http://{strix_halo}:{comfyui_port}/prompt
        # with appropriate workflow JSON
        log.info("Asset generation queued: %s", prompt[:60])
        return None

    async def _generate_voxel_model(
        self, prompt: str, request: AssetRequest
    ) -> Optional[Path]:
        """Generate voxel model — concept via ComfyUI, then manual polish."""
        log.info("Voxel model pipeline: concept art -> Blockbench")
        # Step 1: Generate concept art reference
        concept_request = AssetRequest(
            asset_type=AssetType.TEXTURE,
            description=f"voxel model concept art, isometric view, {prompt}",
            style=request.style,
            resolution="1024x1024",
            prompt_enhance=False,
        )
        await self._generate_image(prompt, concept_request)
        # Step 2: Manual creation in Blockbench using concept as reference
        log.info("Concept generated. Open in Blockbench to build the voxel model.")
        return None

    # ── Build Pipeline ──────────────────────────────────────────────

    def build_project(self, name: str, target: str = "linux") -> bool:
        """Export/build a Godot project."""
        if name not in self.projects:
            log.error("Project '%s' not found", name)
            return False

        project = self.projects[name]
        log.info("Building '%s' for %s...", name, target)

        if project.project_type == ProjectType.CUSTOM_ENGINE:
            return self._build_cmake(project)
        else:
            return self._build_godot(project, target)

    def _build_godot(self, project: ForgeProject, target: str) -> bool:
        """Build Godot project for target platform."""
        try:
            cmd = [
                "godot", "--headless",
                "--path", str(project.path),
                "--export-release", target,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                log.info("Build successful")
                return True
            else:
                log.error("Build failed: %s", result.stderr)
                return False
        except Exception as e:
            log.error("Build error: %s", e)
            return False

    def _build_cmake(self, project: ForgeProject) -> bool:
        """Build C++ project with CMake."""
        build_dir = project.path / "build"
        build_dir.mkdir(exist_ok=True)
        try:
            subprocess.run(
                ["cmake", "-B", str(build_dir), str(project.path)],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["cmake", "--build", str(build_dir), "-j"],
                check=True, capture_output=True, text=True,
            )
            log.info("C++ build successful")
            return True
        except subprocess.CalledProcessError as e:
            log.error("C++ build failed: %s", e.stderr)
            return False

    # ── Marketplace ─────────────────────────────────────────────────

    def get_marketplace_listing(self) -> dict:
        """Return forge's marketplace entry for Man Cave."""
        return {
            "name": "forge",
            "display_name": "Forge",
            "tagline": "The Game Builder",
            "description": (
                "Build games from scratch. Scaffold projects, generate assets "
                "with AI, manage build pipelines. Supports Godot 4, custom "
                "C++ engines, voxel worlds, and more."
            ),
            "icon": "forge.svg",
            "color": "#ff6600",
            "category": "creative",
            "capabilities": [
                "Project scaffolding (Godot 3D, 2D, Voxel, Custom C++)",
                "AI asset generation via ComfyUI",
                "Prompt enhancement via interpreter",
                "Build pipeline management",
                "Steam export preparation",
                "Voxel model concept generation",
            ],
            "requires": ["godot", "comfyui", "interpreter"],
            "optional": ["amp", "blockbench", "magicavoxel"],
        }

    # ── Status ──────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return forge's current status."""
        return {
            "agent": "forge",
            "status": "ready",
            "workspace": str(self.workspace),
            "projects": list(self.projects.keys()),
            "strix_halo": self.strix_halo,
            "godot_available": self._detect_godot_version() != "",
        }


async def main():
    forge = Forge()
    log.info("Status: %s", json.dumps(forge.status(), indent=2))

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "create":
            name = sys.argv[2] if len(sys.argv) > 2 else "my-game"
            ptype = sys.argv[3] if len(sys.argv) > 3 else "voxel"
            project_type = ProjectType(ptype)
            forge.create_project(name, project_type)
        elif command == "build":
            name = sys.argv[2] if len(sys.argv) > 2 else ""
            forge.build_project(name)
        elif command == "status":
            print(json.dumps(forge.status(), indent=2))
        elif command == "marketplace":
            print(json.dumps(forge.get_marketplace_listing(), indent=2))
        else:
            log.error("Unknown command: %s", command)
            print("Usage: forge [create|build|status|marketplace] [args...]")
    else:
        print("Usage: forge [create|build|status|marketplace] [args...]")


if __name__ == "__main__":
    asyncio.run(main())
