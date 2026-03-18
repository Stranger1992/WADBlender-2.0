# WAD Blender 2.0 Feature Overview

This add-on focuses on moving Tomb Raider WAD/WAD2 content between the TRLE toolchain and Blender while preserving geometry, textures, rigs, and animations. Features are grouped by workflow below.

## Importing
- WAD/WAD2 import (Tomb Raider Level Editor assets)
  - Lara full model: skin, joints, and skeleton
  - All movables and all statics (with vertex-painted light data)
  - Import everything in one pass or pick a single object via “Choose Object”
  - Discard placeholder meshes for AI/emitters
  - Material modes: one texture per object, 256×256 texture pages, or full texture map (first two are Sprytile-compatible)
  - Import animations as Blender actions and NLA strips
  - Game slot naming for objects/animations across TR game versions
  - Scale option (512 → 2 meters per TRLE block)
  - Reuse previously imported texture pages when names match
- Mixamo animation import and retargeting to the `LARA_RIG` armature
- FBX animation import (AoD and other sources) via rig retargeting

## Exporting
- WAD/WAD2 export for updated assets
- Animation export
  - Tomb Editor `.anim` (TRLE animation format)
  - WadMerger `.trw`
- Batch export helpers
  - Objects + animations to FBX
  - Objects to OBJ
  - Per-object JSON metadata (state changes, speeds, commands)

## Material, texture, and mesh tools
- Object Panel utilities
  - Create blank 256×256 texture page and assign as material
  - Add/import PNG textures to materials
  - Create vertex color layers for shade, shine, and opacity attributes
- Shine & opacity/translucency editor (face selection; shine 0-31)
- Texture packing/atlas generation for imported UV regions
- Sprytile compatibility with appended Sprytile metadata
- Optional library install (NumPy, PIL) for enhanced texture mappings and Sprytile workflows

## Rigging and animation utilities
- KeeMap rig retargeting add-on (with WADBlender compatibility tweaks and inversion options)
- IK Baker tool
- Skinned Lara batch renaming helpers

## Notes and limitations
- Add-on is still under active development.
- Importing multiple WADs into one .blend can create name conflicts (duplicate object/collection names or texture page reuse) because there is no automatic deduplication. As a workaround, import into separate files, or prefix/rename imported collections and texture pages before bringing in a second WAD. Automatic conflict resolution is not yet implemented.
- The importer currently requires the main armature to be named exactly `LARA_RIG`; custom naming is not supported yet.
- FBX export may require adjusting NLA strips.
