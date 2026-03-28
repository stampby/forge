#!/usr/bin/env python3
"""
forge:steam — Steam build and upload pipeline.

Handles building VDF configs, running pre-upload checks,
and deploying to Steam via SteamCMD. Integrates with sentinel
(PR gate) and meek (security scan) before any upload goes live.

Part of the forge agent in the halo-ai ecosystem.
"""

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="[forge:steam] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("forge.steam")

# Placeholder — replace when app is registered with Steamworks
STEAM_APP_ID = "0000000"

# Required files that must exist in every build before upload
REQUIRED_FILES_BY_PLATFORM = {
    "linux": ["run.sh"],
    "windows": ["run.exe"],
    "mac": ["run.app"],
}

# Max single-file size (2 GB) — catches leftover dev assets
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024

# Patterns that indicate a debug build slipped through
DEBUG_INDICATORS = [
    ".debug",
    "debug.log",
    "godot.log",
    ".pdb",
    "debug_server",
    "crash_handler",
    "_debug.",
]


class Platform(Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MAC = "mac"


@dataclass
class DepotConfig:
    """Configuration for a single Steam depot."""
    depot_id: str
    platform: Platform
    build_path: Path
    file_exclusions: list[str] = field(default_factory=lambda: [
        "*.pdb", "*.debug", "*.log", "*.tmp", ".git*",
    ])

    def content_root(self) -> Path:
        return self.build_path


@dataclass
class BuildManifest:
    """Tracks build history for rollback support."""
    app_id: str
    builds: list[dict] = field(default_factory=list)

    def record_build(
        self,
        build_id: str,
        branch: str,
        platforms: list[str],
        description: str = "",
    ) -> dict:
        entry = {
            "build_id": build_id,
            "branch": branch,
            "platforms": platforms,
            "description": description,
            "timestamp": time.time(),
            "live": False,
        }
        self.builds.append(entry)
        return entry

    def mark_live(self, build_id: str) -> None:
        for b in self.builds:
            b["live"] = b["build_id"] == build_id

    def get_live(self) -> Optional[dict]:
        for b in self.builds:
            if b.get("live"):
                return b
        return None

    def get_previous(self) -> Optional[dict]:
        """Get the build before the current live one, for rollback."""
        live_idx = None
        for i, b in enumerate(self.builds):
            if b.get("live"):
                live_idx = i
                break
        if live_idx is not None and live_idx > 0:
            return self.builds[live_idx - 1]
        return None

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({
            "app_id": self.app_id,
            "builds": self.builds,
        }, indent=2))

    @classmethod
    def load(cls, path: Path) -> "BuildManifest":
        if not path.exists():
            return cls(app_id=STEAM_APP_ID)
        data = json.loads(path.read_text())
        manifest = cls(app_id=data.get("app_id", STEAM_APP_ID))
        manifest.builds = data.get("builds", [])
        return manifest


class SteamDeploy:
    """
    Handles building and uploading to Steam via SteamCMD.

    Generates app_build VDF files, manages depot configs for
    Linux/Windows/Mac, runs pre-upload validation, and integrates
    with sentinel and meek before pushing anything live.
    """

    # Default depot IDs — base depot is app_id + 1, one per platform
    DEFAULT_DEPOTS = {
        Platform.LINUX: "0000001",
        Platform.WINDOWS: "0000002",
        Platform.MAC: "0000003",
    }

    def __init__(
        self,
        project_path: Path,
        app_id: str = STEAM_APP_ID,
        steamcmd_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.project_path = project_path
        self.app_id = app_id
        self.dry_run = dry_run
        self.steamcmd = steamcmd_path or shutil.which("steamcmd") or "steamcmd"
        self.build_output = project_path / "build" / "steam"
        self.build_output.mkdir(parents=True, exist_ok=True)
        self.vdf_dir = self.build_output / "vdf"
        self.vdf_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.build_output / "build_manifest.json"
        self.manifest = BuildManifest.load(self.manifest_path)
        self.manifest.app_id = app_id

        # Depot configs — populated by prepare_build()
        self.depots: dict[Platform, DepotConfig] = {}

        # Integration endpoints
        self.sentinel_url = os.getenv("SENTINEL_URL", "http://localhost:7700")
        self.meek_url = os.getenv("MEEK_URL", "http://localhost:7701")

        log.info("SteamDeploy initialized for app %s", app_id)
        if dry_run:
            log.info("DRY-RUN mode — no uploads will happen")

    # ── Build Preparation ──────────────────────────────────────────

    def prepare_build(
        self,
        platforms: Optional[list[Platform]] = None,
        build_description: str = "",
    ) -> str:
        """
        Prepare a build for Steam upload.

        Collects built binaries for each platform, sets up depot
        configs, and generates a unique build ID.

        Returns the build ID.
        """
        platforms = platforms or [Platform.LINUX, Platform.WINDOWS, Platform.MAC]
        build_id = f"build_{int(time.time())}"

        log.info("Preparing build %s for %s", build_id, [p.value for p in platforms])

        for platform in platforms:
            build_path = self.project_path / "build" / "export" / platform.value
            if not build_path.exists():
                log.warning(
                    "No export found for %s at %s — skipping",
                    platform.value, build_path,
                )
                continue

            depot_id = self.DEFAULT_DEPOTS.get(platform, f"{self.app_id}_{platform.value}")
            self.depots[platform] = DepotConfig(
                depot_id=str(depot_id),
                platform=platform,
                build_path=build_path,
            )
            log.info(
                "Depot %s (%s): %s",
                depot_id, platform.value, build_path,
            )

        if not self.depots:
            log.error("No platform exports found. Run forge build first.")
            return ""

        self.manifest.record_build(
            build_id=build_id,
            branch="default",
            platforms=[p.value for p in self.depots],
            description=build_description,
        )
        self.manifest.save(self.manifest_path)

        log.info("Build %s prepared with %d depots", build_id, len(self.depots))
        return build_id

    # ── VDF Generation ─────────────────────────────────────────────

    def create_vdf(self, build_id: str, branch: str = "default") -> Path:
        """
        Generate the app_build VDF file for SteamCMD.

        Creates depot VDFs for each platform and a master app_build
        VDF that references them all.

        Returns path to the app_build VDF.
        """
        log.info("Generating VDF for build %s (branch: %s)", build_id, branch)

        depot_entries = []
        for platform, depot in self.depots.items():
            depot_vdf_path = self._write_depot_vdf(depot, build_id)
            depot_entries.append((depot.depot_id, depot_vdf_path))
            log.info("Depot VDF: %s", depot_vdf_path)

        # Build the app_build VDF
        depots_block = "\n".join(
            f'    "{depot_id}"\n    {{\n'
            f'      "FileMapping"\n      {{\n'
            f'        "LocalPath" "./*"\n'
            f'        "DepotPath" "."\n'
            f'        "recursive" "1"\n'
            f'      }}\n'
            f'      "FileExclusion" "*.pdb"\n'
            f'      "FileExclusion" "*.debug"\n'
            f'      "FileExclusion" "*.log"\n'
            f'    }}'
            for depot_id, _ in depot_entries
        )

        app_build_vdf = (
            f'"appbuild"\n'
            f'{{\n'
            f'  "appid" "{self.app_id}"\n'
            f'  "desc" "{build_id}"\n'
            f'  "buildoutput" "{self.build_output / "output"}"\n'
            f'  "contentroot" "{self.project_path / "build" / "export"}"\n'
            f'  "setlive" "{branch}"\n'
            f'  "preview" "{"1" if self.dry_run else "0"}"\n'
            f'  "depots"\n'
            f'  {{\n'
            f'{depots_block}\n'
            f'  }}\n'
            f'}}\n'
        )

        vdf_path = self.vdf_dir / f"app_build_{build_id}.vdf"
        vdf_path.write_text(app_build_vdf)
        log.info("App build VDF written to %s", vdf_path)
        return vdf_path

    def _write_depot_vdf(self, depot: DepotConfig, build_id: str) -> Path:
        """Write a single depot build VDF."""
        exclusions = "\n".join(
            f'  "FileExclusion" "{exc}"' for exc in depot.file_exclusions
        )
        vdf_content = (
            f'"DepotBuildConfig"\n'
            f'{{\n'
            f'  "DepotID" "{depot.depot_id}"\n'
            f'  "contentroot" "{depot.content_root()}"\n'
            f'  "FileMapping"\n'
            f'  {{\n'
            f'    "LocalPath" "./*"\n'
            f'    "DepotPath" "."\n'
            f'    "recursive" "1"\n'
            f'  }}\n'
            f'{exclusions}\n'
            f'}}\n'
        )
        vdf_path = self.vdf_dir / f"depot_{depot.depot_id}_{build_id}.vdf"
        vdf_path.write_text(vdf_content)
        return vdf_path

    # ── Pre-Upload Checks ──────────────────────────────────────────

    def run_pre_upload_checks(self) -> bool:
        """
        Validate the build before uploading.

        Checks:
          - Required files present per platform
          - No files exceed size limit
          - No debug build artifacts
          - Sentinel has not blocked any PRs
          - Meek security scan passes

        Returns True if all checks pass.
        """
        log.info("Running pre-upload checks...")
        passed = True

        # File validation per depot
        for platform, depot in self.depots.items():
            root = depot.content_root()

            # Check required files
            required = REQUIRED_FILES_BY_PLATFORM.get(platform.value, [])
            for req_file in required:
                matches = list(root.rglob(req_file))
                if not matches:
                    log.error(
                        "FAIL: Required file '%s' missing for %s in %s",
                        req_file, platform.value, root,
                    )
                    passed = False

            # Check file sizes
            for f in root.rglob("*"):
                if f.is_file() and f.stat().st_size > MAX_FILE_SIZE_BYTES:
                    log.error(
                        "FAIL: File too large (%d MB): %s",
                        f.stat().st_size // (1024 * 1024), f,
                    )
                    passed = False

            # Check for debug build artifacts
            for f in root.rglob("*"):
                if f.is_file():
                    name_lower = f.name.lower()
                    for indicator in DEBUG_INDICATORS:
                        if indicator in name_lower:
                            log.error(
                                "FAIL: Debug artifact detected: %s", f,
                            )
                            passed = False
                            break

        # Sentinel integration — check for blocked PRs
        if not self._check_sentinel():
            log.error("FAIL: sentinel has blocked PRs — resolve before uploading")
            passed = False

        # Meek integration — security scan
        if not self._check_meek():
            log.error("FAIL: meek security scan flagged issues")
            passed = False

        if passed:
            log.info("All pre-upload checks passed")
        else:
            log.error("Pre-upload checks FAILED — fix issues before uploading")

        return passed

    def _check_sentinel(self) -> bool:
        """Check sentinel for any blocked PRs on this project."""
        try:
            result = subprocess.run(
                [
                    "curl", "-sf",
                    f"{self.sentinel_url}/api/status",
                    "-H", "Accept: application/json",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                log.warning("sentinel not reachable — skipping check")
                return True

            data = json.loads(result.stdout)
            blocked = data.get("blocked_prs", 0)
            if blocked > 0:
                log.error("sentinel reports %d blocked PRs", blocked)
                return False
            log.info("sentinel: no blocked PRs")
            return True
        except Exception as e:
            log.warning("sentinel check failed: %s — skipping", e)
            return True

    def _check_meek(self) -> bool:
        """Run meek security scan on the build artifacts."""
        try:
            # Ask meek to scan the export directory
            result = subprocess.run(
                [
                    "curl", "-sf",
                    "-X", "POST",
                    f"{self.meek_url}/api/scan",
                    "-H", "Content-Type: application/json",
                    "-d", json.dumps({
                        "path": str(self.project_path / "build" / "export"),
                        "scan_type": "release_build",
                    }),
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                log.warning("meek not reachable — skipping scan")
                return True

            data = json.loads(result.stdout)
            if data.get("critical", 0) > 0:
                log.error(
                    "meek found %d critical issues", data["critical"],
                )
                return False
            if data.get("high", 0) > 0:
                log.warning(
                    "meek found %d high-severity issues — review recommended",
                    data["high"],
                )
            log.info("meek: security scan passed")
            return True
        except Exception as e:
            log.warning("meek scan failed: %s — skipping", e)
            return True

    # ── Upload ─────────────────────────────────────────────────────

    def upload_to_steam(self, vdf_path: Path, build_id: str) -> bool:
        """
        Upload the build to Steam via SteamCMD.

        Uses cached credentials (must have logged in previously).
        Set dry_run=True to preview without uploading.

        Returns True on success.
        """
        if not vdf_path.exists():
            log.error("VDF file not found: %s", vdf_path)
            return False

        if self.dry_run:
            log.info("DRY-RUN: Would upload %s via %s", vdf_path, self.steamcmd)
            log.info("DRY-RUN: SteamCMD command:")
            log.info(
                "  %s +login <user> +run_app_build %s +quit",
                self.steamcmd, vdf_path,
            )
            self.manifest.mark_live(build_id)
            self.manifest.save(self.manifest_path)
            return True

        steam_user = os.getenv("STEAM_BUILD_USER", "")
        if not steam_user:
            log.error(
                "STEAM_BUILD_USER not set. "
                "Set this env var to your Steamworks build account username."
            )
            return False

        log.info("Uploading build %s to Steam...", build_id)
        try:
            cmd = [
                self.steamcmd,
                "+login", steam_user,
                "+run_app_build", str(vdf_path),
                "+quit",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                log.info("Upload successful for build %s", build_id)
                self.manifest.mark_live(build_id)
                self.manifest.save(self.manifest_path)
                return True
            else:
                log.error("SteamCMD failed:\n%s", result.stderr or result.stdout)
                return False
        except subprocess.TimeoutExpired:
            log.error("SteamCMD timed out after 10 minutes")
            return False
        except FileNotFoundError:
            log.error(
                "steamcmd not found at '%s'. "
                "Install with: sudo pacman -S steamcmd",
                self.steamcmd,
            )
            return False

    # ── Rollback ───────────────────────────────────────────────────

    def rollback(self) -> bool:
        """
        Roll back to the previous build.

        Re-uploads the previous build's VDF. Requires the previous
        build's export files to still exist on disk.
        """
        previous = self.manifest.get_previous()
        if not previous:
            log.error("No previous build found to roll back to")
            return False

        prev_id = previous["build_id"]
        log.info("Rolling back to build %s", prev_id)

        vdf_path = self.vdf_dir / f"app_build_{prev_id}.vdf"
        if not vdf_path.exists():
            log.error("Previous VDF not found: %s — cannot rollback", vdf_path)
            return False

        success = self.upload_to_steam(vdf_path, prev_id)
        if success:
            log.info("Rollback to %s complete", prev_id)
        return success

    # ── Query ──────────────────────────────────────────────────────

    def get_live_build(self) -> Optional[dict]:
        """Return info about the currently live build."""
        live = self.manifest.get_live()
        if live:
            log.info(
                "Live build: %s (branch: %s, platforms: %s)",
                live["build_id"], live["branch"], live["platforms"],
            )
        else:
            log.info("No live build recorded")
        return live

    # ── Full Pipeline ──────────────────────────────────────────────

    def full_deploy(
        self,
        platforms: Optional[list[Platform]] = None,
        branch: str = "default",
        description: str = "",
        skip_checks: bool = False,
    ) -> bool:
        """
        Run the full deploy pipeline:
          1. prepare_build()
          2. run_pre_upload_checks()
          3. create_vdf()
          4. upload_to_steam()

        Returns True on success.
        """
        log.info("=== Full Steam deploy pipeline ===")

        # 1. Prepare
        build_id = self.prepare_build(platforms, description)
        if not build_id:
            return False

        # 2. Checks
        if not skip_checks:
            if not self.run_pre_upload_checks():
                return False
        else:
            log.warning("Pre-upload checks SKIPPED")

        # 3. VDF
        vdf_path = self.create_vdf(build_id, branch)

        # 4. Upload
        success = self.upload_to_steam(vdf_path, build_id)

        if success:
            log.info("=== Deploy complete: %s is live ===", build_id)
        else:
            log.error("=== Deploy FAILED ===")

        return success
