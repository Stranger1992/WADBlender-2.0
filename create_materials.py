from os import path
from math import floor

import bpy
import bmesh

from . import sprytile_utils as sprytile

def generateNodesSetup(name, uvmap):
    # Reuse existing material if present
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    # Create material
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True

    # Transparency settings
    mat.blend_method = 'CLIP'
    mat.alpha_threshold = 0.5

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