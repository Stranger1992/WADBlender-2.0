"""
WAD / WAD2 Exporter for Blender.

Classic WAD:  Patch-based — reads original WAD, replaces meshtree offsets
              from modified Blender armatures, writes patched binary.
WAD2:         Full export — extracts meshes, textures, bones, animations
              from Blender scene and writes a new .wad2 using the chunk-
              based format matching Tomb Editor's Wad2Writer.cs exactly.
"""

import os
import struct
import io
import math
import re
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty
from bpy_extras.io_utils import ExportHelper


# ============================================================================
# Shared helpers
# ============================================================================

def read_uint32(f):
    return struct.unpack('I', f.read(4))[0]


def read_int32(f):
    return struct.unpack('i', f.read(4))[0]


def write_uint32(f, value):
    f.write(struct.pack('I', value))


def write_int32(f, value):
    f.write(struct.pack('i', value))


# ============================================================================
# WAD2 Export — Blender scene → WAD2 file
# ============================================================================

# ---------- Texture extraction ------------------------------------------------

def _get_texture_image(mat):
    """Return the first TEX_IMAGE node's image from a material, or None."""
    if not mat or not mat.use_nodes:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            return node.image
    return None


def _image_to_bgra_bytes(image):
    """
    Convert a Blender image to raw BGRA pixel bytes (top-down scanline order),
    which is the format Tomb Editor's ImageC stores internally and writes to
    WAD2 TextureData chunks.
    """
    w, h = image.size
    if w == 0 or h == 0:
        return b''

    # Force-load pixel data from disk if not already in memory.
    # Small images that were never displayed in Blender's viewport may have
    # has_data=False; accessing pixels without loading returns all-zero bytes.
    if not image.has_data and image.source == 'FILE':
        try:
            image.reload()
        except Exception:
            pass

    # Blender stores pixels as flat RGBA floats, bottom-up row order
    pixels = image.pixels[:]
    if len(pixels) < w * h * 4:
        return bytes(w * h * 4)  # black placeholder if still not loaded
    out = bytearray(w * h * 4)

    for y in range(h):
        src_y = h - 1 - y        # flip: Blender bottom-up → WAD2 top-down
        for x in range(w):
            si = (src_y * w + x) * 4
            di = (y * w + x) * 4
            r = int(min(255, max(0, pixels[si + 0] * 255 + 0.5)))
            g = int(min(255, max(0, pixels[si + 1] * 255 + 0.5)))
            b = int(min(255, max(0, pixels[si + 2] * 255 + 0.5)))
            a = int(min(255, max(0, pixels[si + 3] * 255 + 0.5)))
            out[di + 0] = b          # BGRA order
            out[di + 1] = g
            out[di + 2] = r
            out[di + 3] = a

    return bytes(out)


def _build_texture_table(context):
    """
    Scan all materials for unique texture images.
    Returns (textures_list, image_name→table_index map).
    """
    textures = []
    img_to_idx = {}

    for mat in bpy.data.materials:
        img = _get_texture_image(mat)
        if img and img.name not in img_to_idx:
            w, h = img.size
            if w == 0 or h == 0:
                continue
            textures.append({
                'width':    w,
                'height':   h,
                'data':     _image_to_bgra_bytes(img),
                'name':     '',
                'rel_path': '',
                '_img':     img,          # keep reference for UV → pixel conversion
            })
            img_to_idx[img.name] = len(textures) - 1

    return textures, img_to_idx


def _tex_index_for_material(mat, img_to_idx):
    """Return the texture-table index for a material, or 0."""
    img = _get_texture_image(mat)
    if img and img.name in img_to_idx:
        return img_to_idx[img.name]
    return 0


def _tex_dims_for_material(mat, textures, img_to_idx):
    """Return (width, height) of the texture backing a material."""
    idx = _tex_index_for_material(mat, img_to_idx)
    if 0 <= idx < len(textures):
        return textures[idx]['width'], textures[idx]['height']
    return 256, 256


# ---------- Mesh extraction ---------------------------------------------------

def _extract_mesh(mesh_obj, textures, img_to_idx, scale):
    """
    Extract a single Blender mesh object into the dict expected by write_wad2.
    Coordinates are scaled to TR units.  UVs are converted back to pixel
    coordinates (reversing the 0-1 normalisation and V-flip done on import).
    """
    # Evaluate mesh with modifiers applied
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj  = mesh_obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.data

    # -- Positions (float, scaled) --
    # Blender (Z-up, Y-forward) → WAD2 (Y-up): inverse of _fix_axis_vec3 = (-bx, bz, -by)
    positions = []
    for v in eval_mesh.vertices:
        positions.append((-v.co.x * scale, v.co.z * scale, -v.co.y * scale))

    # -- Normals --
    # Same inverse axis transform, then negate for handedness flip (det=-1 reversal)
    # Result: (nx, -nz, ny)
    normals = []
    for v in eval_mesh.vertices:
        normals.append((v.normal.x, -v.normal.z, v.normal.y))

    # -- Vertex colours (from "shade" colour attribute if present) --
    colors = []
    shade_layer = None
    for attr in eval_mesh.color_attributes:
        shade_layer = attr          # use the first one
        break
    if shade_layer and shade_layer.domain == 'CORNER':
        accum = {}
        for poly in eval_mesh.polygons:
            for li in poly.loop_indices:
                vi = eval_mesh.loops[li].vertex_index
                c  = shade_layer.data[li].color
                if vi not in accum:
                    accum[vi] = [0.0, 0.0, 0.0, 0]
                accum[vi][0] += c[0]
                accum[vi][1] += c[1]
                accum[vi][2] += c[2]
                accum[vi][3] += 1
        for vi in range(len(eval_mesh.vertices)):
            if vi in accum and accum[vi][3] > 0:
                n = accum[vi][3]
                colors.append((accum[vi][0]/n, accum[vi][1]/n, accum[vi][2]/n))
            else:
                colors.append((1.0, 1.0, 1.0))

    # -- UV layer --
    uv_layer = eval_mesh.uv_layers.active

    # -- Polygons --
    polygons = []
    for poly in eval_mesh.polygons:
        verts = list(poly.vertices)

        # Get material → texture index + dimensions
        mat = (mesh_obj.data.materials[poly.material_index]
               if poly.material_index < len(mesh_obj.data.materials) else None)
        tex_idx = _tex_index_for_material(mat, img_to_idx)
        tw, th  = _tex_dims_for_material(mat, textures, img_to_idx)

        # Detect blend mode from material name
        blend_mode = 0
        if mat:
            mname = mat.name.lower()
            if 'additive' in mname:
                blend_mode = 2
            elif 'alphatest' in mname or 'alpha_test' in mname:
                blend_mode = 1

        # Read per-polygon custom properties stored on import
        shine = 0
        double_sided = False

        # UV → pixel coordinates (reverse import transform)
        raw_uvs = []
        if uv_layer:
            for li in poly.loop_indices:
                u, v = uv_layer.data[li].uv
                # Import did: u = u_pixel / tex_w,  v = 1.0 - (v_pixel / tex_h)
                # Reverse:
                u_px = u * tw
                v_px = (1.0 - v) * th
                raw_uvs.append((u_px, v_px))
        else:
            raw_uvs = [(0.0, 0.0)] * len(verts)

        # ParentArea — bounding rectangle of the UVs in pixel space
        if raw_uvs:
            min_u = min(uv[0] for uv in raw_uvs)
            min_v = min(uv[1] for uv in raw_uvs)
            max_u = max(uv[0] for uv in raw_uvs)
            max_v = max(uv[1] for uv in raw_uvs)
            parent_area = (min_u, min_v, max_u, max_v)
        else:
            parent_area = (0.0, 0.0, float(tw), float(th))

        # Triangulate n-gons (>4 verts)
        if len(verts) > 4:
            for i in range(1, len(verts) - 1):
                tri_verts = [verts[0], verts[i], verts[i+1]]
                tri_uvs   = [raw_uvs[0], raw_uvs[i], raw_uvs[i+1]]
                _add_polygon(polygons, 'tri', tri_verts, tri_uvs,
                             shine, tex_idx, parent_area, blend_mode, double_sided)
        elif len(verts) in (3, 4):
            shape = 'quad' if len(verts) == 4 else 'tri'
            _add_polygon(polygons, shape, verts, raw_uvs,
                         shine, tex_idx, parent_area, blend_mode, double_sided)

    # -- Bounds --
    if positions:
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]
        bbox_min = (min(xs), min(ys), min(zs))
        bbox_max = (max(xs), max(ys), max(zs))
        cx, cy, cz = ((bbox_min[i] + bbox_max[i]) / 2 for i in range(3))
        radius = max(math.sqrt((p[0]-cx)**2 + (p[1]-cy)**2 + (p[2]-cz)**2)
                     for p in positions)
    else:
        bbox_min = bbox_max = (0, 0, 0)
        cx = cy = cz = radius = 0.0

    return {
        'name':           mesh_obj.name,
        'positions':      positions,
        'normals':        normals,
        'colors':         colors,
        'sphere_center':  (cx, cy, cz),
        'sphere_radius':  radius,
        'bbox_min':       bbox_min,
        'bbox_max':       bbox_max,
        'polygons':       polygons,
        'lighting_type':  0,
        'hidden':         False,
    }


def _add_polygon(out, shape, indices, uvs, shine, tex_idx,
                 parent_area, blend_mode, double_sided):
    out.append({
        'shape':         shape,
        'indices':       indices,
        'shine':         shine,
        'texture_index': tex_idx,
        'parent_area':   parent_area,
        'uvs':           uvs,
        'blend_mode':    blend_mode,
        'double_sided':  double_sided,
    })


# ---------- Bone extraction ---------------------------------------------------

def _extract_bones(rig, mesh_objects, scale):
    """
    Build the WAD2 Bone2 list from an armature.

    Returns list of dicts: {op, name, translation, mesh_index}.
    OpCodes:  0 = Push, 1 = Pop, 2 = Read/Peek, 3 = NotUseStack (simple chain)
    C# enum WadLinkOpcode: Push=0, Pop=1, Read=2, NotUseStack=3
    """
    bones = []

    if not rig or rig.type != 'ARMATURE':
        # No armature → simple linear chain (all NotUseStack)
        for i, obj in enumerate(mesh_objects):
            bone_name = 'bone_0_root' if i == 0 else f'bone_{i}'
            if i == 0:
                bones.append({'op': 0, 'name': bone_name,
                              'translation': (0.0, 0.0, 0.0), 'mesh_index': 0})
            else:
                prev = mesh_objects[i - 1]
                # Blender→WAD2: inverse of _fix_axis_vec3 = (-Δbx, Δbz, -Δby)
                dbx = obj.location.x - prev.location.x
                dby = obj.location.y - prev.location.y
                dbz = obj.location.z - prev.location.z
                bones.append({'op': 0, 'name': bone_name,
                              'translation': (-dbx * scale, dbz * scale, -dby * scale),
                              'mesh_index': i})
        return bones

    # Build a mapping: mesh_name → armature bone
    arm_bones = rig.data.bones
    name_lookup = {b.name: b for b in arm_bones}

    for i, mesh_obj in enumerate(mesh_objects):
        bone = name_lookup.get(mesh_obj.name)

        if i == 0:
            # Root — always Push, zero translation
            bones.append({
                'op':          0,
                'name':        'bone_0_root',
                'translation': (0.0, 0.0, 0.0),
                'mesh_index':  0,
            })
            continue

        # Translation relative to parent mesh
        if bone and bone.parent:
            parent_name = bone.parent.name
            parent_mesh = next((m for m in mesh_objects if m.name == parent_name), None)
            if parent_mesh:
                dbx = mesh_obj.location.x - parent_mesh.location.x
                dby = mesh_obj.location.y - parent_mesh.location.y
                dbz = mesh_obj.location.z - parent_mesh.location.z
            else:
                dbx = mesh_obj.location.x
                dby = mesh_obj.location.y
                dbz = mesh_obj.location.z
            # Blender→WAD2: inverse of _fix_axis_vec3 = (-Δbx, Δbz, -Δby)
            dx = -dbx * scale
            dy =  dbz * scale
            dz = -dby * scale

            # Determine stack opcode from sibling structure
            siblings = list(bone.parent.children)
            if len(siblings) <= 1:
                op = 0    # NotUseStack — single child
            else:
                idx_in_siblings = siblings.index(bone)
                if idx_in_siblings == 0:
                    op = 2   # Push
                elif idx_in_siblings == len(siblings) - 1:
                    op = 1   # Pop
                else:
                    op = 3   # Read (peek)
        else:
            # Orphan bone or no parent info — chain
            prev = mesh_objects[i - 1]
            dbx = mesh_obj.location.x - prev.location.x
            dby = mesh_obj.location.y - prev.location.y
            dbz = mesh_obj.location.z - prev.location.z
            # Blender→WAD2: inverse of _fix_axis_vec3 = (-Δbx, Δbz, -Δby)
            dx = -dbx * scale
            dy =  dbz * scale
            dz = -dby * scale
            op = 0

        bones.append({
            'op':          op,
            'name':        f'bone_{i}',
            'translation': (dx, dy, dz),
            'mesh_index':  i,
        })

    return bones


# ---------- Animation extraction ----------------------------------------------

def _extract_animations(rig, mesh_objects, scale):
    """
    Extract all NLA-strip / active-action animations from an armature.
    Returns list of animation dicts for write_wad2.

    Angles are stored as (pitch_deg, yaw_deg, roll_deg) in WAD space,
    matching WadKeyFrameRotation.Rotations (degrees).
    """
    if not rig or rig.type != 'ARMATURE' or not rig.animation_data:
        return []

    # Reuse the working conversion helpers from the .anim exporter.
    from .export_anim import (
        AXIS_MAT, AXIS_MAT_T, _get_action_fcurves,
        _build_curve_map, _evaluate_quat,
        _mat_to_yaw_pitch_roll, _blender_to_wad_vec,
    )

    # Collect unique actions from NLA tracks and active action
    actions = []
    if rig.animation_data.nla_tracks:
        for track in rig.animation_data.nla_tracks:
            for strip in track.strips:
                if strip.action and strip.action not in actions:
                    actions.append(strip.action)
    if rig.animation_data.action:
        if rig.animation_data.action not in actions:
            actions.append(rig.animation_data.action)

    if not actions:
        return []

    bone_names = [m.name for m in mesh_objects]
    old_action = rig.animation_data.action
    old_frame  = bpy.context.scene.frame_current

    animations = []
    for action in actions:
        rig.animation_data.action = action

        frame_start = int(action.frame_range[0])
        frame_end   = int(action.frame_range[1])

        # Use the slot-aware fcurve getter (handles new Blender action API)
        fcurves   = _get_action_fcurves(rig, action)
        curve_map = _build_curve_map(fcurves)

        # Gather unique keyframe positions from fcurves
        kf_frames = sorted(set(
            int(kp.co[0])
            for fc in fcurves
            for kp in fc.keyframe_points
            if frame_start <= int(kp.co[0]) <= frame_end
        ))
        if not kf_frames:
            kf_frames = [frame_start]

        keyframes = []
        for frame in kf_frames:
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()

            # Root bone offset: Blender → WAD space
            root_offset = (0.0, 0.0, 0.0)
            if bone_names and bone_names[0] in rig.pose.bones:
                root_loc_path = f'pose.bones["{bone_names[0]}"].location'
                loc = [0.0, 0.0, 0.0]
                for axis in range(3):
                    fc = curve_map.get((root_loc_path, axis))
                    if fc:
                        loc[axis] = fc.evaluate(frame) * scale
                root_offset = _blender_to_wad_vec(loc)

            # Per-bone angles: convert quaternion → WAD rotation matrix
            # → extract yaw/pitch/roll in degrees (pitch, yaw, roll).
            # Matches WadKeyFrameRotation.Rotations storage format.
            angles = []
            for bn in bone_names:
                if bn in rig.pose.bones:
                    bone = rig.pose.bones[bn]
                    q      = _evaluate_quat(curve_map, bone, frame)
                    mat_b  = q.to_matrix()
                    mat_w  = AXIS_MAT_T @ mat_b @ AXIS_MAT
                    yaw, pitch, roll = _mat_to_yaw_pitch_roll(mat_w)
                    angles.append((
                        math.degrees(pitch),
                        math.degrees(yaw),
                        math.degrees(roll),
                    ))
                else:
                    angles.append((0.0, 0.0, 0.0))

            keyframes.append({
                'offset':  root_offset,
                'bb_min':  (0.0, 0.0, 0.0),
                'bb_max':  (0.0, 0.0, 0.0),
                'angles':  angles,
            })

        # Read optional custom properties from the action
        state_id   = int(action.get('state_id', 0))
        next_anim  = int(action.get('next_animation', 0))
        next_frame = int(action.get('next_frame', 0))
        frame_rate = int(action.get('frame_rate', 1))

        # State changes from custom prop (JSON list if present)
        state_changes = []
        sc_raw = action.get('state_changes')
        if sc_raw and isinstance(sc_raw, str):
            import json
            try:
                state_changes = json.loads(sc_raw)
            except Exception:
                pass

        # Anim commands
        commands = []
        cmd_raw = action.get('anim_commands')
        if cmd_raw and isinstance(cmd_raw, str):
            import json
            try:
                commands = json.loads(cmd_raw)
            except Exception:
                pass

        animations.append({
            'state_id':                state_id,
            'end_frame':               max(0, frame_end - frame_start),
            'frame_rate':              frame_rate,
            'next_animation':          next_anim,
            'next_frame':              next_frame,
            'name':                    action.name,
            'keyframes':               keyframes,
            'state_changes':           state_changes,
            'commands':                commands,
            'start_velocity':          float(action.get('start_velocity', 0)),
            'end_velocity':            float(action.get('end_velocity', 0)),
            'start_lateral_velocity':  float(action.get('start_lateral_velocity', 0)),
            'end_lateral_velocity':    float(action.get('end_lateral_velocity', 0)),
        })

    # Restore state
    rig.animation_data.action = old_action
    bpy.context.scene.frame_set(old_frame)

    return animations


# ---------- Slot-ID resolution ------------------------------------------------

def _resolve_slot_id(collection_or_object, name_to_id):
    """
    Determine the numeric slot ID for a collection or object.
    Priority:
      1. Custom property 'wad_slot_id'
      2. name_to_id reverse lookup
      3. Trailing digits in the name (e.g. 'BADDY_1' → 1)
      4. Fallback to 0
    """
    name = collection_or_object.name

    # 1. Explicit custom property
    sid = collection_or_object.get('wad_slot_id')
    if sid is not None:
        return int(sid)

    # 2. Name mapping
    if name in name_to_id:
        return int(name_to_id[name])

    # 3. Trailing digits
    m = re.search(r'(\d+)$', name)
    if m:
        return int(m.group(1))

    return 0


# ---------- Main WAD2 export entry point --------------------------------------

def export_wad2(context, filepath, scale, game, export_anims=True):
    """Export the Blender scene as a WAD2 file."""
    from .wad.write_wad2 import write_wad2_file
    from datetime import datetime

    print("=" * 60)
    print("WAD2 Export")
    print("=" * 60)

    # Build reverse name→ID map from the objects module (if available)
    name_to_id = {}
    try:
        from . import objects
        mov_names, static_names, _, _ = objects.get_names(game)
        name_to_id = {v: k for k, v in mov_names.items()}
        static_name_to_id = {v: k for k, v in static_names.items()}
        name_to_id.update(static_name_to_id)
    except Exception as e:
        print(f"[WAD2 Export] Could not load name mapping: {e}")

    # Build texture table
    textures, img_to_idx = _build_texture_table(context)
    print(f"Textures: {len(textures)}")

    # ---- Moveables ----
    moveables = []
    movables_col = bpy.data.collections.get('Movables')
    if movables_col:
        for col in movables_col.children:
            mesh_objects = sorted(
                [o for o in col.objects if o.type == 'MESH'],
                key=lambda o: o.name
            )
            if not mesh_objects:
                print(f"  {col.name}: skipped (no meshes)")
                continue

            rig = next((o for o in col.objects if o.type == 'ARMATURE'), None)
            mov_id = _resolve_slot_id(col, name_to_id)

            meshes = []
            for mobj in mesh_objects:
                md = _extract_mesh(mobj, textures, img_to_idx, scale)
                meshes.append(md)

            bones = _extract_bones(rig, mesh_objects, scale)

            animations = []
            if export_anims:
                animations = _extract_animations(rig, mesh_objects, scale)

            if not animations:
                # WadTool requires at least one animation with one keyframe to
                # call BuildHierarchy/BuildAnimationPose and display all meshes.
                # Generate a minimal rest-pose animation as fallback.
                animations = [{
                    'state_id':               0,
                    'end_frame':              0,
                    'frame_rate':             1,
                    'next_animation':         0,
                    'next_frame':             0,
                    'name':                   'DEFAULT',
                    'keyframes': [{
                        'offset':  (0.0, 0.0, 0.0),
                        'bb_min':  (0.0, 0.0, 0.0),
                        'bb_max':  (0.0, 0.0, 0.0),
                        'angles':  [(0.0, 0.0, 0.0)] * len(mesh_objects),
                    }],
                    'state_changes':          [],
                    'commands':               [],
                    'start_velocity':         0.0,
                    'end_velocity':           0.0,
                    'start_lateral_velocity': 0.0,
                    'end_lateral_velocity':   0.0,
                }]

            moveables.append({
                'id':         mov_id,
                'meshes':     meshes,
                'bones':      bones,
                'animations': animations,
            })

            total_polys = sum(len(m['polygons']) for m in meshes)
            print(f"  {col.name} (ID {mov_id}): {len(meshes)} meshes, "
                  f"{len(bones)} bones, {len(animations)} anims, "
                  f"{total_polys} polys")

    # ---- Statics ----
    statics_list = []
    statics_col = bpy.data.collections.get('Statics')
    if statics_col:
        # Statics may be direct objects or sub-collections
        static_objs = [o for o in statics_col.objects if o.type == 'MESH']
        # Also check child collections
        for child_col in statics_col.children:
            static_objs.extend(o for o in child_col.objects if o.type == 'MESH')

        for obj in static_objs:
            static_id = _resolve_slot_id(obj, name_to_id)
            md = _extract_mesh(obj, textures, img_to_idx, scale)

            statics_list.append({
                'id':             static_id,
                'flags':          0,
                'mesh':           md,
                'ambient_light':  0,
                'shatter':        False,
                'shatter_sound':  0,
                'vis_box_min':    md['bbox_min'],
                'vis_box_max':    md['bbox_max'],
                'col_box_min':    md['bbox_min'],
                'col_box_max':    md['bbox_max'],
            })
            print(f"  Static {obj.name} (ID {static_id}): "
                  f"{len(md['positions'])} verts, {len(md['polygons'])} polys")

    # ---- Assemble & write ----
    now = datetime.now()
    wad2_data = {
        'game_version': _game_to_version(game),
        'textures':     textures,
        'moveables':    moveables,
        'statics':      statics_list,
        'timestamp':    (now.year, now.month, now.day,
                         now.hour, now.minute, now.second),
        'user_notes':   'Exported from Blender via WADBlender',
    }

    # Strip internal-only keys from textures before writing
    for t in wad2_data['textures']:
        t.pop('_img', None)

    write_wad2_file(filepath, wad2_data)

    print("=" * 60)
    print(f"WAD2 exported: {filepath}")
    print(f"  {len(textures)} textures, {len(moveables)} moveables, "
          f"{len(statics_list)} statics")
    print("=" * 60)

    return {'FINISHED'}


def _game_to_version(game_str):
    return {'TR1': 1, 'TR2': 2, 'TR3': 3, 'TR4': 4,
            'TR5': 5, 'TR5Main': 5, 'TEN': 4}.get(game_str, 4)


# ============================================================================
# Classic WAD Export (patch-based)
# ============================================================================

def export_wad(context, filepath, import_path, scale, game):
    """Export by patching meshtree offsets in the original classic WAD."""
    from . import objects
    mov_names, _, _, _ = objects.get_names(game)
    name_to_id = {name: idx for idx, name in mov_names.items()}
    print(f"Loaded {len(name_to_id)} movable name mappings for {game}")

    with open(import_path, 'rb') as f:
        original_data = f.read()

    f = io.BytesIO(original_data)

    version = read_uint32(f)
    assert 129 <= version <= 130, f"Unsupported WAD version: {version}"

    texture_samples_count = read_uint32(f)
    f.seek(f.tell() + texture_samples_count * 8)
    bytes_size = read_uint32(f)
    f.seek(f.tell() + bytes_size)
    mesh_pointers_count = read_uint32(f)
    f.seek(f.tell() + mesh_pointers_count * 4)
    words_size = read_uint32(f)
    f.seek(f.tell() + words_size * 2)
    animations_count = read_uint32(f)
    f.seek(f.tell() + animations_count * 40)
    state_changes_count = read_uint32(f)
    f.seek(f.tell() + state_changes_count * 6)
    dispatches_count = read_uint32(f)
    f.seek(f.tell() + dispatches_count * 8)
    commands_words = read_uint32(f)
    f.seek(f.tell() + commands_words * 2)

    links_offset = f.tell()
    dwords_size = read_uint32(f)
    original_links = [read_int32(f) for _ in range(dwords_size)]
    links_end = f.tell()

    keyframes_words = read_uint32(f)
    f.seek(f.tell() + keyframes_words * 2)

    movables_count = read_uint32(f)
    movables_data = []
    for _ in range(movables_count):
        movables_data.append({
            'obj_ID':           read_uint32(f),
            'num_pointers':     struct.unpack('H', f.read(2))[0],
            'pointers_index':   struct.unpack('H', f.read(2))[0],
            'links_index':      read_uint32(f),
            'keyframes_offset': read_uint32(f),
            'anims_index':      struct.unpack('h', f.read(2))[0],
        })

    modified_joints = {}
    movables_col = bpy.data.collections.get('Movables')
    if movables_col:
        for collection in movables_col.children:
            mesh_objects, new_joints = calculate_meshtree_offsets(collection, scale)
            if not new_joints:
                continue

            col_name = collection.name
            movable_id = name_to_id.get(col_name)
            if movable_id is not None:
                movable_id = int(movable_id)

            for md in movables_data:
                matches = (
                    md['obj_ID'] == movable_id or
                    col_name.endswith(str(md['obj_ID'])) or
                    col_name == f"MOVABLE{md['obj_ID']}" or
                    col_name.startswith(f"MOVABLE{md['obj_ID']}_")
                )
                if not matches:
                    continue

                num_joints = md['num_pointers'] - 1
                if len(new_joints) != num_joints:
                    print(f"  WARNING: {col_name} joint count mismatch "
                          f"({len(new_joints)} vs {num_joints})")
                    break

                li = md['links_index']
                patched = []
                for i, nj in enumerate(new_joints):
                    base = li + i * 4
                    orig_op = (original_links[base] if base < len(original_links) else nj[0])
                    patched.append([orig_op, nj[1], nj[2], nj[3]])
                modified_joints[li] = patched
                break

    new_links = original_links.copy()
    for li, joints in modified_joints.items():
        for i, j in enumerate(joints):
            base = li + i * 4
            if base + 3 < len(new_links):
                new_links[base:base+4] = j

    with open(filepath, 'wb') as out:
        out.write(original_data[:links_offset])
        write_uint32(out, len(new_links))
        for v in new_links:
            write_int32(out, v)
        out.write(original_data[links_end:])

    print(f"Classic WAD exported: {filepath} ({len(modified_joints)} movables patched)")
    return {'FINISHED'}


def calculate_meshtree_offsets(collection, scale):
    """Calculate meshtree offsets from Blender armature/mesh positions."""
    mesh_objects = sorted(
        [o for o in collection.objects if o.type == 'MESH'],
        key=lambda o: o.name
    )
    if not mesh_objects:
        return [], []

    rig = next((o for o in collection.objects if o.type == 'ARMATURE'), None)
    parent_map = {}

    if rig and len(mesh_objects) > 1:
        bone_names = [b.name for b in rig.data.bones]
        for i, mobj in enumerate(mesh_objects):
            if i == 0:
                continue
            bn = mobj.name
            if bn in bone_names:
                bone = rig.data.bones[bn]
                if bone.parent:
                    pn = bone.parent.name
                    pi = next((j for j, m in enumerate(mesh_objects) if m.name == pn), 0)
                    parent_map[i] = pi
                else:
                    parent_map[i] = 0
            else:
                parent_map[i] = i - 1
    else:
        for i in range(1, len(mesh_objects)):
            parent_map[i] = i - 1

    joints = []
    bone_names = [b.name for b in rig.data.bones] if rig else []
    for i in range(1, len(mesh_objects)):
        mobj = mesh_objects[i]
        pi = parent_map.get(i, i - 1)
        pobj = mesh_objects[pi]

        dx = int((mobj.location.x - pobj.location.x) * scale)
        dy = int((mobj.location.y - pobj.location.y) * scale)
        dz = int((mobj.location.z - pobj.location.z) * scale)

        op = 0
        if rig and mobj.name in bone_names:
            bone = rig.data.bones[mobj.name]
            if bone.parent:
                if i > 0 and mesh_objects[i-1].name == bone.parent.name:
                    op = 0
                else:
                    op = 3
        joints.append([op, dx, dy, dz])

    return mesh_objects, joints


# ============================================================================
# Blender Operator
# ============================================================================

class ExportWAD(bpy.types.Operator, ExportHelper):
    """Export scene to WAD or WAD2 file"""
    bl_idname = "export_scene.wad"
    bl_label = "Export WAD"
    bl_options = {'PRESET'}

    filename_ext = ".wad2"

    filter_glob: StringProperty(
        default="*.wad;*.wad2",
        options={'HIDDEN'},
    )

    import_path: StringProperty(
        name="Original WAD",
        description="Path to original WAD file (for classic WAD export only)",
        default="",
        subtype='FILE_PATH'
    )

    scale: FloatProperty(
        name="Scale",
        description="Scale factor (Blender units → TR units)",
        default=512.0,
        min=1.0,
        max=10000.0
    )

    game: EnumProperty(
        name="Game",
        description="Target game version",
        items=[
            ('TEN', "TEN (Tomb Engine)", ""),
            ('TR4', "TR4", ""),
            ('TR5', "TR5", ""),
            ('TR5Main', "TR5Main", ""),
            ('TR3', "TR3", ""),
            ('TR2', "TR2", ""),
            ('TR1', "TR1", ""),
        ],
        default='TEN',
    )

    export_format: EnumProperty(
        name="Format",
        description="Export format",
        items=[
            ('WAD2', "WAD2", "Export as WAD2 (for Tomb Editor / TEN)"),
            ('WAD',  "Classic WAD", "Patch meshtree offsets in original WAD"),
        ],
        default='WAD2',
    )

    export_animations: BoolProperty(
        name="Export Animations",
        description="Include animation data in WAD2 export",
        default=True,
    )

    def execute(self, context):
        if self.export_format == 'WAD2':
            if not self.filepath.lower().endswith('.wad2'):
                self.filepath = os.path.splitext(self.filepath)[0] + '.wad2'
            return export_wad2(context, self.filepath, self.scale,
                               self.game, self.export_animations)
        else:
            if not self.import_path or not os.path.exists(self.import_path):
                self.report({'ERROR'},
                            "Classic WAD export requires the original WAD file.")
                return {'CANCELLED'}
            if not self.filepath.lower().endswith('.wad'):
                self.filepath = os.path.splitext(self.filepath)[0] + '.wad'
            return export_wad(context, self.filepath, self.import_path,
                              self.scale, self.game)

    def invoke(self, context, event):
        if hasattr(context.scene, 'wad_import_path') and context.scene.wad_import_path:
            self.import_path = context.scene.wad_import_path
            if self.import_path.lower().endswith('.wad2'):
                self.export_format = 'WAD2'
                self.filename_ext = '.wad2'
        return super().invoke(context, event)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Export Settings", icon="EXPORT")

        box.prop(self, "export_format")

        if self.export_format == 'WAD':
            box.prop(self, "import_path")
            if self.import_path:
                box.label(text=f"Using: {os.path.basename(self.import_path)}",
                          icon="FILE")
            else:
                box.label(text="Original WAD file required", icon="ERROR")
        else:
            box.prop(self, "export_animations")

        box.separator()
        box.prop(self, "scale")
        box.prop(self, "game")


def menu_func_export(self, context):
    self.layout.operator(ExportWAD.bl_idname,
                         text="Tomb Raider WAD (.wad/.wad2)")


def register():
    bpy.utils.register_class(ExportWAD)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.Scene.wad_import_path = StringProperty(
        name="WAD Import Path",
        description="Path to the imported WAD file",
        default=""
    )


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(ExportWAD)
    del bpy.types.Scene.wad_import_path


if __name__ == "__main__":
    register()
