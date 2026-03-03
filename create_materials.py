from os import path
from math import floor

import bpy
import bmesh

from . import sprytile_utils as sprytile

def _set_material_blend_mode(mat, mode):
    """Set material transparency mode compatible with Blender 4.2+ and older.
    
    mode: 'CLIP' for alpha test, 'BLEND' for alpha blend/additive
    """
    # Blender 4.2+ / 5.0: render_method replaces blend_method
    if hasattr(mat, 'render_method'):
        if mode == 'CLIP':
            mat.render_method = 'DITHERED'
        else:
            mat.render_method = 'BLENDED'
    elif hasattr(mat, 'blend_method'):
        # Blender < 4.2
        mat.blend_method = mode
        if mode == 'CLIP':
            mat.alpha_threshold = 0.5


def generateNodesSetup(name, uvmap):
    # Reuse existing material if present
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    # Create material
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True

    # Transparency settings
    _set_material_blend_mode(mat, 'CLIP')

    # Load texture
    img = bpy.data.images.load(uvmap)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Base texture
    tex_base = nodes.new("ShaderNodeTexImage")
    tex_base.image = img
    tex_base.interpolation = 'Closest'
    tex_base.location = (-600, 100)

    # Emission texture (duplicate)
    tex_emit = nodes.new("ShaderNodeTexImage")
    tex_emit.image = img
    tex_emit.interpolation = 'Closest'
    tex_emit.location = (-600, -100)

    # Principled BSDF
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-200, 0)

    # Output
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (200, 0)

    # Links
    links.new(tex_base.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex_base.outputs["Alpha"], bsdf.inputs["Alpha"])

    links.new(tex_emit.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0

    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    return mat


def generateAdditiveNodesSetup(name, uvmap):
    """Create a material with additive (screen-like) blending.
    
    Uses emission-only rendering with alpha blending to approximate
    the additive blend mode used by Tomb Raider engines.
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    _set_material_blend_mode(mat, 'BLEND')
    mat.use_backface_culling = False

    img = bpy.data.images.load(uvmap)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # Texture
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = 'Closest'
    tex.location = (-600, 0)

    # Emission shader (additive blending is emission-only)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (-200, 100)

    # Transparent shader
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (-200, -100)

    # Mix shader: use texture luminance/alpha to blend between
    # transparent and emission
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (100, 0)

    # Output
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)

    # Links
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    emission.inputs["Strength"].default_value = 1.5

    # Use alpha as mix factor (transparent where alpha=0, emissive where alpha>0)
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(emission.outputs["Emission"], mix.inputs[2])

    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    return mat

def setShineOpacity(obj, face, polygon, roughness_layer, opacity_layer):
    try:
        if obj.get('opacity') is not None:
            for loop in face.loops:
                intensity = 1 - polygon.intensity / 31 if polygon.shine == 1 else 0
                loop[roughness_layer] = (intensity, intensity, intensity, 1)

                alpha = polygon.opacity
                loop[opacity_layer] = (alpha, alpha, alpha, 1)
        else:
            for loop in face.loops:
                loop[roughness_layer] = (0, 0, 0, 1)
                loop[opacity_layer] = (0, 0, 0, 1)
    except Exception as e:
        print(f"[WAD Import] Shine/Opacity error on face {face.index}: {e}")



def setUV(face, polygon, uvrect, uv_layer):
    try:
        if len(uvrect) == len(face.loops):
            uv = uvrect
        elif len(uvrect) < len(face.loops):
            uv = list(uvrect) + [uvrect[-1]] * (len(face.loops) - len(uvrect))
        else:
            a, b, c, d = uvrect
            if len(polygon.face) == 4:
                uv = (a, b, c, d)
            else:
                if polygon.order == 0:
                    uv = (a, b, d)
                elif polygon.order == 2:
                    uv = (b, c, a)
                elif polygon.order == 4:
                    uv = (c, d, b)
                else:
                    uv = (d, a, c)

        for k, loop in enumerate(face.loops):
            loop[uv_layer].uv = uv[min(k, len(uv)-1)]
    except Exception as e:
        print(f"[WAD Import] UV error on face {face.index}: {e}")

def createPageMaterial(filepath, context):
    sprytile_installed = sprytile.check_install()
    obj = context.object

    # Extract EXACT material name expected by importer
    base = path.basename(filepath)
    if "." in base:
        material_name = base.rsplit(".", 1)[0]   # <-- FIXED
    else:
        material_name = base

    # Ensure the material exists
    if material_name in bpy.data.materials:
        mat = bpy.data.materials[material_name]
    else:
        mat = generateNodesSetup(material_name, filepath)

    bpy.data.materials.update()

    mat.name = material_name

    if sprytile_installed:
        sprytile.update(context)

    return mat


def pack_textures(context, meshes, objects, options, name):
    from PIL import Image
    from .texture_packer import pack_object_textures

    sprytile_installed = sprytile.check_install()

    texture_path = options.path + options.wadname + ".png"
    uvtable, new_texture_map = pack_object_textures(meshes, texture_path)

    im = Image.fromarray(new_texture_map)
    if name == '':
        name = objects[0].name
    path = options.path + name + ".png"
    saved_successfully = False
    try:
        im.save(path)
        saved_successfully = True
    except (PermissionError, OSError) as e:
        print(f"Warning: Could not save texture to {path}: {str(e)}")

    # Only proceed if texture was saved successfully
    if not saved_successfully:
        print(f"Error: Texture could not be saved. Skipping material setup for {name}")
        return

    mats = [generateNodesSetup(name, path)]

    for mesh, obj in zip(meshes, objects):
        sprytile.assign_material(context, obj, mats[0], sprytile_installed)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()
        roughness_layer = bm.loops.layers.color.new("shine")
        opacity_layer = bm.loops.layers.color.new("opacity")
        sprytile.verify_bmesh_layers(bm)
        for face_idx, (polygon, face) in enumerate(zip(mesh.polygons, bm.faces)):
            a, b, c, d = polygon.tbox

            x0, y0 = polygon.x, polygon.y
            w, h = polygon.tex_width, polygon.tex_height
            mw, mh = new_texture_map.shape[1], new_texture_map.shape[0]

            p = uvtable[(x0, y0, w, h)]  # top left corner
            left, top = p[0] / mw, 1 - p[1] / mh
            right, bottom = (p[0] + w) / mw, 1 - (p[1] + h) / mh

            a = (left, top)
            b = (right, top)
            c = (right, bottom)
            d = (left, bottom)

            tile = min(a, b, c, d)
            tile_x, tile_y = tile
            tile_x = floor(tile_x * (mw+1))
            tile_y = floor(tile_y * (mh+1))

            uvrect = [a, b, c, d]
            if polygon.flipX:
                uvrect = [b, a, d, c]

            if polygon.flipY:
                uvrect = [d, c, b, a]

            face.material_index = 0
            setUV(face, polygon, uvrect, uv_layer)
            setShineOpacity(obj, face, polygon, roughness_layer, opacity_layer)

            if sprytile_installed:
                sprytile.write_metadata(
                    context, obj, face_idx, bm, 
                    polygon.tex_width, polygon.tex_height, 
                    tile_x, tile_y, polygon.flipX, polygon.flipY, mw
                )

        bm.to_mesh(obj.data)


def pack_wad2_textures(context, meshes, objects, options, wad, name=''):
    """
    Pack WAD2 per-page textures into a single compact atlas for the
    given meshes/objects, then apply the remapped UVs.

    This replaces the multi-material-per-page approach with a single
    packed texture containing only the regions actually used by the meshes.
    """
    import numpy as np
    from .texture_packer import pack_wad2_textures as _pack_wad2

    sprytile_installed = sprytile.check_install()

    # Convert the WAD2 texture page float lists to uint8 numpy arrays.
    # Each page is a flat list of floats (R,G,B,A in [0..1]),
    # stored bottom-up (Blender convention). We need top-down for packing.
    texture_images = []
    for page_idx, page_pixels in enumerate(wad.textureMaps):
        pixel_count = len(page_pixels) // 4
        if pixel_count == 0:
            texture_images.append(np.zeros((1, 1, 4), dtype=np.uint8))
            continue

        # Determine page dimensions
        if pixel_count == wad.mapwidth * wad.mapheight:
            pw, ph = wad.mapwidth, wad.mapheight
        else:
            import math
            sq = int(math.isqrt(pixel_count))
            if sq * sq == pixel_count:
                pw = ph = sq
            else:
                pw, ph = pixel_count, 1

        # Convert float [0..1] to uint8 [0..255], reshape to (H, W, 4)
        arr = np.array(page_pixels, dtype=np.float32).reshape((ph, pw, 4))
        # Flip vertically: Blender stores bottom-up, we need top-down
        arr = np.flipud(arr)
        arr = (arr * 255).clip(0, 255).astype(np.uint8)
        texture_images.append(arr)

    if not texture_images:
        print("[WAD2 Pack] No texture pages found, skipping packing.")
        return

    # Run the packer
    padding = getattr(options, 'texture_padding', 4)
    atlas, uv_updates = _pack_wad2(meshes, texture_images, padding=padding, bleed=padding)

    # Diagnostic: summarize what was packed
    total_polys = sum(len(m.polygons) for m in meshes)
    pages_used = set()
    for m in meshes:
        for p in m.polygons:
            pages_used.add(p.page)
    print(f"[WAD2 Pack] {len(meshes)} meshes, {total_polys} polygons, "
          f"using pages {sorted(pages_used)} out of {len(texture_images)} total pages")
    print(f"[WAD2 Pack] Atlas shape: {atlas.shape}, UV updates: {len(uv_updates)}")

    if atlas.size == 0 or not uv_updates:
        print("[WAD2 Pack] Packing produced no results, skipping.")
        return

    # Build lookup for fast UV update: (mesh_idx, poly_idx) -> new_tbox
    uv_lookup = {}
    for mesh_idx, poly_idx, new_tbox in uv_updates:
        uv_lookup[(mesh_idx, poly_idx)] = new_tbox

    # Save atlas using Blender's image API (no PIL needed)
    if name == '':
        name = objects[0].name if objects else options.wadname
    atlas_name = name + "_packed"
    atlas_path = options.path + atlas_name + ".png"

    atlas_h, atlas_w = atlas.shape[:2]

    # Convert uint8 top-down atlas to Blender's bottom-up float format
    atlas_flipped = np.flipud(atlas).astype(np.float32) / 255.0
    pixels_flat = atlas_flipped.flatten().tolist()

    bpy_img = bpy.data.images.new(atlas_name, atlas_w, atlas_h, alpha=True)
    bpy_img.pixels = pixels_flat

    saved_successfully = False
    try:
        bpy_img.filepath_raw = atlas_path
        bpy_img.file_format = 'PNG'
        bpy_img.save()
        saved_successfully = True
    except (RuntimeError, PermissionError, OSError) as e:
        print(f"Warning: Could not save packed atlas to {atlas_path}: {str(e)}")

    if not saved_successfully:
        print(f"Error: Packed atlas could not be saved. Skipping material setup for {name}")
        return

    # Create material using the saved image
    mat_normal = generateNodesSetup(atlas_name, atlas_path)

    # Check if any polygon uses additive blending (blend_mode >= 2)
    has_additive = False
    additive_count = 0
    normal_count = 0
    for mesh in meshes:
        for polygon in mesh.polygons:
            bm = getattr(polygon, 'blend_mode', 0)
            if bm >= 2:
                has_additive = True
                additive_count += 1
            else:
                normal_count += 1
    print(f"[WAD2 Pack] Blend modes: {normal_count} normal, {additive_count} additive")

    mat_additive = None
    if has_additive:
        mat_additive = generateAdditiveNodesSetup(atlas_name + "_additive", atlas_path)

    # Apply to each object
    for mesh_idx, (mesh, obj) in enumerate(zip(meshes, objects)):
        # Explicitly assign materials to the object's mesh data
        obj.data.materials.clear()
        obj.data.materials.append(mat_normal)      # index 0: normal
        if mat_additive:
            obj.data.materials.append(mat_additive)  # index 1: additive

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.verify()
        roughness_layer = bm.loops.layers.color.new("shine")
        opacity_layer = bm.loops.layers.color.new("opacity")
        sprytile.verify_bmesh_layers(bm)

        for poly_idx, (polygon, face) in enumerate(zip(mesh.polygons, bm.faces)):
            # Assign material based on blend mode
            blend = getattr(polygon, 'blend_mode', 0)
            if blend >= 2 and mat_additive:
                face.material_index = 1  # additive
            else:
                face.material_index = 0  # normal

            # Use remapped UVs if available, otherwise fall back to original
            key = (mesh_idx, poly_idx)
            if key in uv_lookup:
                new_tbox = uv_lookup[key]
                # WAD2 tbox already has per-vertex UVs with flips baked in
                # from _convert_polygon_to_model, so pass straight through.
                setUV(face, polygon, list(new_tbox), uv_layer)
            else:
                # Fallback: use original tbox
                setUV(face, polygon, polygon.tbox, uv_layer)

            setShineOpacity(obj, face, polygon, roughness_layer, opacity_layer)

        bm.to_mesh(obj.data)
        obj.data.update()


def apply_textures(context, mesh, obj, materials, options, name=''):
    sprytile_installed = sprytile.check_install()
    for i in range(len(materials)):
        obj.data.materials.append(materials[i])

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    uv_layer = bm.loops.layers.uv.verify()
    roughness_layer = bm.loops.layers.color.new("shine")
    opacity_layer = bm.loops.layers.color.new("opacity")
    sprytile.verify_bmesh_layers(bm)
    for idx, (polygon, face) in enumerate(zip(mesh.polygons, bm.faces)):
        tile = min(polygon.tbox)
        tile_x, tile_y = tile
        tile_x = floor(tile_x * 256)
        tile_y = floor(tile_y * 256)

        mat_index = polygon.page if polygon.page < len(materials) else 0
        face.material_index = mat_index
        setUV(face, polygon, polygon.tbox, uv_layer)
        setShineOpacity(obj, face, polygon, roughness_layer, opacity_layer)

        if sprytile_installed and options.texture_pages:
            sprytile.write_metadata(
                context, obj, idx, bm, 
                polygon.tex_width, polygon.tex_height, 
                tile_x, tile_y, polygon.flipX, polygon.flipY
            )

    bm.to_mesh(obj.data)
