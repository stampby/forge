# forge

**The game builder agent.** From raw metal to finished blade.

Part of the [halo-ai](https://github.com/bong-water-water-bong/halo-ai) ecosystem. Available in the [Man Cave](https://github.com/bong-water-water-bong/man-cave) marketplace.

## What forge does

- **Scaffold game projects** — Godot 3D, 2D, Voxel, or custom C++ engines
- **Generate assets with AI** — textures, sprites, concept art via ComfyUI on Strix Halo
- **Enhance prompts** — routes through [interpreter](https://github.com/bong-water-water-bong/interpreter) for better generation results
- **Build pipelines** — export for Linux, Windows, Mac, Steam
- **Voxel model pipeline** — concept art generation -> Blockbench/MagicaVoxel workflow

## Quick start

```bash
# Create a voxel game project
python3 src/agent/forge_agent.py create my-game voxel

# Check status
python3 src/agent/forge_agent.py status

# View marketplace listing
python3 src/agent/forge_agent.py marketplace
```

## Asset pipeline

```
Your idea
    ↓
interpreter (prompt enhancement)
    ↓
ComfyUI on Strix Halo (image generation)
    ↓
Blockbench / MagicaVoxel (3D modeling)
    ↓
Godot (game engine)
    ↓
amp (sound design)
    ↓
forge (build & export)
    ↓
Steam / itch.io
```

## Integrations

| Agent | Role |
|-------|------|
| **interpreter** | Enhances prompts before asset generation |
| **amp** | Handles all audio — SFX, music, mastering |
| **echo** | Community announcements, Discord updates |
| **meek** | Security scanning on builds before release |

## Project types

| Type | Engine | Use case |
|------|--------|----------|
| `voxel` | Godot 4 + godot_voxel | Voxel worlds, extraction games |
| `godot_3d` | Godot 4 | 3D games |
| `godot_2d` | Godot 4 | 2D / pixel art games |
| `custom_engine` | C++ / Vulkan | Build your own engine |

## Requirements

- Godot 4.6+ (`sudo pacman -S godot`)
- Python 3.11+
- ComfyUI on Strix Halo (for asset generation)
- Blockbench or MagicaVoxel (for voxel modeling)

## Family

forge is part of the halo-ai agent family. Color: `#ff6600`. He builds things.

While amp masters sound and interpreter refines language, forge takes raw ideas and hammers them into playable games.

---

*"From raw metal to finished blade."*
