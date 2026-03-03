import os
import struct
import io
import math
import re
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty
from bpy_extras.io_utils import ExportHelper


def read_uint32(f):
    """Read unsigned 32-bit integer"""
    return struct.unpack('I', f.read(4))[0]


def read_int32(f):
    """Read signed 32-bit integer"""
    return struct.unpack('i', f.read(4))[0]


def write_uint32(f, value):
    """Write unsigned 32-bit integer"""
    f.write(struct.pack('I', value))


def write_int32(f, value):
    """Write signed 32-bit integer"""
    f.write(struct.pack('i', value))


def calculate_meshtree_offsets(collection, scale):
    """
    Calculate meshtree offsets from Blender object positions.
    Returns: (meshes, joints) where joints is [[op, dx, dy, dz], ...]
    """
    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']
    mesh_objects.sort(key=lambda x: x.name)

    if len(mesh_objects) == 0:
        return [], []

    joints = []
    rig = next((obj for obj in collection.objects if obj.type == 'ARMATURE'), None)
    parent_map = {}

    if rig and len(mesh_objects) > 1:
        bone_names = [bone.name for bone in rig.data.bones]

        for i, mesh_obj in enumerate(mesh_objects):
            if i == 0:
                continue

            bone_name = mesh_obj.name
            if bone_name in bone_names:
                bone = rig.data.bones[bone_name]
                if bone.parent:
                    parent_name = bone.parent.name
                    parent_idx = next((j for j, m in enumerate(mesh_objects) if m.name == parent_name), 0)
                    parent_map[i] = parent_idx
                else:
                    parent_map[i] = 0
            else:
                parent_map[i] = i - 1
    else:
        for i in range(1, len(mesh_objects)):
            parent_map[i] = i - 1

    for i in range(1, len(mesh_objects)):
        mesh_obj = mesh_objects[i]
        parent_idx = parent_map.get(i, i - 1)
        parent_obj = mesh_objects[parent_idx]

        bone_name = mesh_obj.name

        # Use mesh local positions (same as Reference code)
        loc = mesh_obj.location
        parent_loc = parent_obj.location

        dx = int((loc.x - parent_loc.x) * scale)
        dy = int((loc.y - parent_loc.y) * scale)
        dz = int((loc.z - parent_loc.z) * scale)

        op = 0

        if rig and bone_name in bone_names:
            bone = rig.data.bones[bone_name]
            if bone.parent:
                parent_name = bone.parent.name
                if i > 0 and mesh_objects[i-1].name == parent_name:
                    op = 0
                else:
                    op = 3

        joints.append([op, dx, dy, dz])

    return mesh_objects, joints


# ============================================================================
# WAD2 Export Functions
# ============================================================================

def extract_mesh_data_from_blender(mesh_obj, scale):
    """Extract mesh data from a Blender mesh object for WAD2 export"""
    mesh = mesh_obj.data
    mesh.calc_loop_triangles()

    positions = []
    for vert in mesh.vertices:
        positions.append((vert.co.x, vert.co.y, vert.co.z))

    normals = []
    for vert in mesh.vertices:
        normals.append((vert.normal.x, vert.normal.y, vert.normal.z))

    uv_layer = mesh.uv_layers.active
    has_uvs = uv_layer is not None

    triangles = []
    quads = []

    for poly in mesh.polygons:
        indices = list(poly.vertices)

        uvs = []
        if has_uvs:
            for loop_idx in poly.loop_indices:
                uv = uv_layer.data[loop_idx].uv
                uvs.append((uv.x, uv.y))
        else:
            uvs = [(0.0, 0.0)] * len(indices)

        mat_idx = poly.material_index

        poly_data = {
            'indices': indices,
            'uvs': uvs,
            'texture': mat_idx,
            'shine': 0,
            'blend_mode': 0,
            'double_sided': False
        }

        if len(indices) == 3:
            triangles.append(poly_data)
        elif len(indices) == 4:
            quads.append(poly_data)
        else:
            for i in range(1, len(indices) - 1):
                tri_indices = [indices[0], indices[i], indices[i + 1]]
                tri_uvs = [uvs[0], uvs[i], uvs[i + 1]] if uvs else [(0, 0)] * 3
                triangles.append({
                    'indices': tri_indices,
                    'uvs': tri_uvs,
                    'texture': mat_idx,
                    'shine': 0,
                    'blend_mode': 0,
                    'double_sided': False
                })

    if positions:
        min_x = min(p[0] for p in positions)
        max_x = max(p[0] for p in positions)
        min_y = min(p[1] for p in positions)
        max_y = max(p[1] for p in positions)
        min_z = min(p[2] for p in positions)
        max_z = max(p[2] for p in positions)

        center = ((min_x + max_x) / 2, (min_y + max_y) / 2, (min_z + max_z) / 2)
        radius = max(
            math.sqrt((p[0] - center[0])**2 + (p[1] - center[1])**2 + (p[2] - center[2])**2)
            for p in positions
        )

        sphere = {'center': center, 'radius': radius}
        bbox = {'min': (min_x, min_y, min_z), 'max': (max_x, max_y, max_z)}
    else:
        sphere = {'center': (0, 0, 0), 'radius': 0}
        bbox = {'min': (0, 0, 0), 'max': (0, 0, 0)}

    return {
        'name': mesh_obj.name,
        'positions': positions,
        'normals': normals,
        'shades': [],
        'triangles': triangles,
        'quads': quads,
        'sphere': sphere,
        'bbox': bbox
    }


def extract_bone_data_from_armature(rig, mesh_objects, scale):
    """Extract bone hierarchy data from armature for WAD2 export"""
    bones = []

    if not rig or rig.type != 'ARMATURE':
        for i, mesh_obj in enumerate(mesh_objects):
            bone = {
                'name': mesh_obj.name,
                'op': 0 if i > 0 else 0,
                'mesh': i,
                'translation': (0, 0, 0) if i == 0 else (
                    mesh_obj.location.x - mesh_objects[i-1].location.x,
                    mesh_obj.location.y - mesh_objects[i-1].location.y,
                    mesh_obj.location.z - mesh_objects[i-1].location.z
                )
            }
            bones.append(bone)
        return bones

    mesh_to_bone = {}
    for bone in rig.data.bones:
        bone_base = bone.name.replace('_BONE', '').replace('.BONE', '')
        for i, mesh_obj in enumerate(mesh_objects):
            mesh_base = mesh_obj.name.split('_')[-1] if '_' in mesh_obj.name else mesh_obj.name
            if bone_base == mesh_base or bone_base in mesh_obj.name or mesh_obj.name in bone_base:
                mesh_to_bone[i] = bone
                break

    stack = []

    for i, mesh_obj in enumerate(mesh_objects):
        bone = mesh_to_bone.get(i)

        if bone:
            if i == 0:
                op = 0
                translation = (0, 0, 0)
            else:
                parent_bone = bone.parent
                if parent_bone:
                    parent_mesh_idx = -1
                    for j, other_bone in mesh_to_bone.items():
                        if other_bone == parent_bone:
                            parent_mesh_idx = j
                            break

                    if parent_mesh_idx == i - 1:
                        op = 0
                    elif parent_mesh_idx >= 0:
                        op = 3
                        if parent_mesh_idx not in stack:
                            stack.append(parent_mesh_idx)
                    else:
                        op = 0
                else:
                    op = 0

                if parent_bone:
                    parent_head = rig.matrix_world @ parent_bone.head_local
                    bone_head = rig.matrix_world @ bone.head_local
                    translation = (
                        bone_head.x - parent_head.x,
                        bone_head.y - parent_head.y,
                        bone_head.z - parent_head.z
                    )
                else:
                    translation = (bone.head_local.x, bone.head_local.y, bone.head_local.z)

            bones.append({
                'name': bone.name,
                'op': op,
                'mesh': i,
                'translation': translation
            })
        else:
            bones.append({
                'name': mesh_obj.name,
                'op': 0,
                'mesh': i,
                'translation': (0, 0, 0) if i == 0 else (
                    mesh_obj.location.x - mesh_objects[i-1].location.x,
                    mesh_obj.location.y - mesh_objects[i-1].location.y,
                    mesh_obj.location.z - mesh_objects[i-1].location.z
                )
            })

    return bones


def extract_animation_data_from_rig(rig, num_bones, scale):
    """Extract animation data from armature for WAD2 export"""
    animations = []

    if not rig or rig.type != 'ARMATURE':
        return animations

    actions = []
    if rig.animation_data:
        if rig.animation_data.action:
            actions.append(rig.animation_data.action)
        if rig.animation_data.nla_tracks:
            for track in rig.animation_data.nla_tracks:
                for strip in track.strips:
                    if strip.action and strip.action not in actions:
                        actions.append(strip.action)

    for action in bpy.data.actions:
        if action not in actions:
            if rig.name in action.name or action.name.startswith(rig.name.split('_')[0]):
                actions.append(action)

    for action in actions:
        anim_data = extract_single_animation(rig, action, num_bones, scale)
        if anim_data:
            animations.append(anim_data)

    return animations


def extract_single_animation(rig, action, num_bones, scale):
    """Extract a single animation from an action"""
    if not action:
        return None

    frame_start = int(action.frame_range[0])
    frame_end = int(action.frame_range[1])

    if frame_end <= frame_start:
        return None

    original_action = rig.animation_data.action if rig.animation_data else None
    original_frame = bpy.context.scene.frame_current

    if not rig.animation_data:
        rig.animation_data_create()
    rig.animation_data.action = action

    bone_names = [bone.name for bone in rig.data.bones]

    keyframes = []
    frame_step = 1

    for frame in range(frame_start, frame_end + 1, frame_step):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()

        kf_data = {
            'offset': (0, 0, 0),
            'rotations': [],
            'bbox': {'min': (-100, -100, -100), 'max': (100, 100, 100)}
        }

        if rig.pose.bones:
            root_bone = rig.pose.bones[0]
            loc = root_bone.matrix.translation
            kf_data['offset'] = (loc.x, loc.y, loc.z)

        for bone_name in bone_names:
            pose_bone = rig.pose.bones.get(bone_name)
            if pose_bone:
                quat = pose_bone.matrix.to_quaternion()
                kf_data['rotations'].append((quat.w, quat.x, quat.y, quat.z))
            else:
                kf_data['rotations'].append((1.0, 0.0, 0.0, 0.0))

        keyframes.append(kf_data)

    if original_action:
        rig.animation_data.action = original_action
    bpy.context.scene.frame_set(original_frame)

    return {
        'name': action.name,
        'state_id': 0,
        'end_frame': len(keyframes) - 1,
        'frame_rate': 1,
        'next_animation': 0,
        'next_frame': 0,
        'velocity': (0.0, 0.0, 0.0, 0.0),
        'keyframes': keyframes,
        'state_changes': {},
        'commands': []
    }


def extract_texture_data_from_materials(mesh_objects):
    """Extract texture data from materials for WAD2 export"""
    textures = []
    texture_map = {}

    for mesh_obj in mesh_objects:
        if not mesh_obj.data.materials:
            continue

        for mat in mesh_obj.data.materials:
            if not mat or mat.name in texture_map:
                continue

            texture_data = None
            if mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        img = node.image
                        width, height = img.size
                        if width > 0 and height > 0:
                            pixels = list(img.pixels)

                            bgra_data = bytearray(width * height * 4)
                            for y in range(height):
                                for x in range(width):
                                    src_idx = ((height - 1 - y) * width + x) * 4
                                    dst_idx = (y * width + x) * 4
                                    r = int(pixels[src_idx] * 255)
                                    g = int(pixels[src_idx + 1] * 255)
                                    b = int(pixels[src_idx + 2] * 255)
                                    a = int(pixels[src_idx + 3] * 255)
                                    bgra_data[dst_idx] = b
                                    bgra_data[dst_idx + 1] = g
                                    bgra_data[dst_idx + 2] = r
                                    bgra_data[dst_idx + 3] = a

                            texture_data = {
                                'index': len(textures),
                                'name': mat.name,
                                'width': width,
                                'height': height,
                                'data': bytes(bgra_data)
                            }
                            break

            if texture_data:
                texture_map[mat.name] = len(textures)
                textures.append(texture_data)
            else:
                texture_map[mat.name] = len(textures)
                textures.append({
                    'index': len(textures),
                    'name': mat.name,
                    'width': 256,
                    'height': 256,
                    'data': bytes([128, 128, 128, 255] * 256 * 256)
                })

    return textures, texture_map


def collect_moveable_data(collection, scale):
    """Collect all moveable data from a collection for WAD2 export"""
    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']
    mesh_objects.sort(key=lambda x: x.name)

    if not mesh_objects:
        return None

    rig = next((obj for obj in collection.objects if obj.type == 'ARMATURE'), None)

    meshes = []
    for mesh_obj in mesh_objects:
        mesh_data = extract_mesh_data_from_blender(mesh_obj, scale)
        meshes.append(mesh_data)

    bones = extract_bone_data_from_armature(rig, mesh_objects, scale)
    animations = extract_animation_data_from_rig(rig, len(mesh_objects), scale)

    return {
        'meshes': meshes,
        'bones': bones,
        'animations': animations
    }


def collect_static_data(collection, scale):
    """Collect static object data from a collection for WAD2 export"""
    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']

    if not mesh_objects:
        return None

    mesh_obj = mesh_objects[0]
    mesh_data = extract_mesh_data_from_blender(mesh_obj, scale)

    return {
        'mesh': mesh_data,
        'visibility_box': mesh_data.get('bbox'),
        'collision_box': mesh_data.get('bbox'),
        'flags': 0
    }


def export_wad2(context, filepath, import_path, scale, game='TR4'):
    """Export WAD2 file with full mesh, texture, and animation data"""
    from .wad import write_wad2

    print("=" * 60)
    print("Exporting WAD2 file...")
    print(f"Export path: {filepath}")
    print(f"Scale: {scale}")
    print(f"Game: {game}")
    print("=" * 60)

    from . import objects
    mov_names, static_names, _, _ = objects.get_names(game)

    name_to_id = {name: int(idx) for idx, name in mov_names.items()}
    static_name_to_id = {name: int(idx) for idx, name in static_names.items()}

    wad_data = {
        'textures': [],
        'meshes': [],
        'moveables': [],
        'statics': []
    }

    options = {
        'scale': scale,
        'tex_width': 256,
        'tex_height': 256
    }

    all_mesh_objects = []

    movables_col = bpy.data.collections.get('Movables')
    if movables_col:
        print(f"\nProcessing Movables collection...")
        for collection in movables_col.children:
            movable_name = collection.name
            print(f"  Processing movable: {movable_name}")

            movable_id = name_to_id.get(movable_name)
            if movable_id is None:
                for suffix in ['_RIG', '_ANIM', '']:
                    test_name = movable_name.replace(suffix, '')
                    if test_name in name_to_id:
                        movable_id = name_to_id[test_name]
                        break

            if movable_id is None:
                match = re.search(r'(\d+)$', movable_name)
                if match:
                    movable_id = int(match.group(1))
                else:
                    movable_id = len(wad_data['moveables'])

            mov_data = collect_moveable_data(collection, scale)
            if mov_data:
                mov_data['id'] = movable_id
                wad_data['moveables'].append(mov_data)

                mesh_objs = [obj for obj in collection.objects if obj.type == 'MESH']
                all_mesh_objects.extend(mesh_objs)

                print(f"    ID: {movable_id}, Meshes: {len(mov_data['meshes'])}, "
                      f"Bones: {len(mov_data['bones'])}, Anims: {len(mov_data['animations'])}")

    statics_col = bpy.data.collections.get('Statics')
    if statics_col:
        print(f"\nProcessing Statics collection...")
        for collection in statics_col.children:
            static_name = collection.name
            print(f"  Processing static: {static_name}")

            static_id = static_name_to_id.get(static_name)
            if static_id is None:
                match = re.search(r'(\d+)$', static_name)
                if match:
                    static_id = int(match.group(1))
                else:
                    static_id = len(wad_data['statics'])

            static_data = collect_static_data(collection, scale)
            if static_data:
                static_data['id'] = static_id
                wad_data['statics'].append(static_data)

                mesh_objs = [obj for obj in collection.objects if obj.type == 'MESH']
                all_mesh_objects.extend(mesh_objs)

                print(f"    ID: {static_id}")

    if all_mesh_objects:
        textures, texture_map = extract_texture_data_from_materials(all_mesh_objects)
        wad_data['textures'] = textures
        print(f"\nExtracted {len(textures)} textures")

    write_wad2.write_wad2(filepath, wad_data, options)

    print("=" * 60)
    print(f"Successfully exported WAD2 to: {filepath}")
    print(f"  Moveables: {len(wad_data['moveables'])}")
    print(f"  Statics: {len(wad_data['statics'])}")
    print(f"  Textures: {len(wad_data['textures'])}")
    print("=" * 60)

    return {'FINISHED'}


def export_wad(context, filepath, import_path, scale, game='TR4'):
    """
    Export WAD file with modified meshtree offsets.
    Strategy: Copy entire original WAD and patch only the joints/links section
    """

    print("=" * 60)
    print("Exporting WAD file...")
    print(f"Import path: {import_path}")
    print(f"Export path: {filepath}")
    print(f"Scale: {scale}")
    print(f"Game: {game}")
    print("=" * 60)

    if not os.path.exists(import_path):
        raise Exception(f"Import WAD file not found: {import_path}")

    from . import objects
    mov_names, _, _, _ = objects.get_names(game)

    name_to_id = {name: idx for idx, name in mov_names.items()}
    print(f"Loaded {len(name_to_id)} movable name mappings for {game}")

    with open(import_path, 'rb') as f:
        original_data = f.read()

    print(f"Read {len(original_data)} bytes from original WAD")

    f = io.BytesIO(original_data)

    version = read_uint32(f)
    print(f"WAD Version: {version}")

    texture_samples_count = read_uint32(f)
    f.seek(f.tell() + texture_samples_count * 8)
    texture_bytes = read_uint32(f)
    f.seek(f.tell() + texture_bytes)
    print(f"Texture section: {texture_samples_count} samples, {texture_bytes} bytes")

    mesh_pointers_count = read_uint32(f)
    f.seek(f.tell() + mesh_pointers_count * 4)
    mesh_words_size = read_uint32(f)
    mesh_data_start = f.tell()
    mesh_data_size = mesh_words_size * 2
    f.seek(f.tell() + mesh_data_size)
    print(f"Mesh section: {mesh_pointers_count} pointers, {mesh_words_size} words")

    animations_count = read_uint32(f)
    f.seek(f.tell() + animations_count * 40)
    state_changes_count = read_uint32(f)
    f.seek(f.tell() + state_changes_count * 6)
    dispatches_count = read_uint32(f)
    f.seek(f.tell() + dispatches_count * 8)
    commands_words_size = read_uint32(f)
    f.seek(f.tell() + commands_words_size * 2)
    print(f"Animation section: {animations_count} anims, {state_changes_count} changes, {dispatches_count} dispatches")

    links_offset = f.tell()
    links_dwords_size = read_uint32(f)
    original_links_data = []
    for _ in range(links_dwords_size):
        original_links_data.append(read_int32(f))
    links_end = f.tell()
    print(f"Links section at offset {links_offset}: {links_dwords_size} dwords ({links_dwords_size * 4} bytes)")

    keyframes_words_size = read_uint32(f)
    f.seek(f.tell() + keyframes_words_size * 2)

    movables_offset = f.tell()
    movables_count = read_uint32(f)
    print(f"Movables section at offset {movables_offset}: {movables_count} movables")

    movables_data = []
    for _ in range(movables_count):
        mov = {
            'obj_ID': read_uint32(f),
            'num_pointers': struct.unpack('H', f.read(2))[0],
            'pointers_index': struct.unpack('H', f.read(2))[0],
            'links_index': read_uint32(f),
            'keyframes_offset': read_uint32(f),
            'anims_index': struct.unpack('h', f.read(2))[0]
        }
        movables_data.append(mov)
        print(f"  Movable {mov['obj_ID']}: {mov['num_pointers']} meshes, links_index={mov['links_index']}")

    modified_joints = {}

    movables_col = bpy.data.collections.get('Movables')
    if movables_col:
        print(f"\nSearching for movables in Blender scene...")
        print(f"Found {len(movables_col.children)} collections in Movables")

        for collection in movables_col.children:
            movable_name = collection.name
            print(f"\nChecking collection: '{movable_name}'")

            mesh_objects, new_joints = calculate_meshtree_offsets(collection, scale)
            print(f"  Found {len(mesh_objects)} mesh objects, {len(new_joints)} joints")

            if len(new_joints) > 0:
                matched = False

                movable_id = None
                if movable_name in name_to_id:
                    movable_id = int(name_to_id[movable_name])
                    print(f"  Found ID {movable_id} from name mapping")

                for mov_data in movables_data:
                    matches = (
                        mov_data['obj_ID'] == movable_id or
                        movable_name.endswith(str(mov_data['obj_ID'])) or
                        movable_name == f"MOVABLE{mov_data['obj_ID']}" or
                        movable_name.startswith(f"MOVABLE{mov_data['obj_ID']}_") or
                        (movable_name + '_RIG').startswith(f"MOVABLE{mov_data['obj_ID']}")
                    )

                    if matches:
                        links_index = mov_data['links_index']
                        num_joints = mov_data['num_pointers'] - 1

                        print(f"  Matched with movable ID {mov_data['obj_ID']} ({num_joints} joints expected, {len(new_joints)} found)")

                        if len(new_joints) == num_joints:
                            preserved_joints = []
                            for i, new_joint in enumerate(new_joints):
                                base_idx = links_index + i * 4
                                if base_idx < len(original_links_data):
                                    original_op = original_links_data[base_idx]
                                    preserved_joints.append([original_op, new_joint[1], new_joint[2], new_joint[3]])
                                else:
                                    preserved_joints.append(new_joint)

                            modified_joints[links_index] = preserved_joints
                            print(f"  Will update {movable_name} (ID {mov_data['obj_ID']}): {num_joints} joints at links_index {links_index}")
                            matched = True
                        else:
                            print(f"  WARNING: {movable_name} joint count mismatch: expected {num_joints}, got {len(new_joints)}")
                        break

                if not matched:
                    print(f"  No matching movable ID found for '{movable_name}'")
            else:
                print(f"  Skipped: no joints found")
    else:
        print("\nNo 'Movables' collection found in scene")

    new_links_data = original_links_data.copy()

    for links_index, new_joints in modified_joints.items():
        for i, joint in enumerate(new_joints):
            base_idx = links_index + i * 4
            if base_idx + 3 < len(new_links_data):
                new_links_data[base_idx] = joint[0]
                new_links_data[base_idx + 1] = joint[1]
                new_links_data[base_idx + 2] = joint[2]
                new_links_data[base_idx + 3] = joint[3]
                print(f"  Patched joint at index {base_idx}: op={joint[0]}, dx={joint[1]}, dy={joint[2]}, dz={joint[3]}")

    with open(filepath, 'wb') as out:
        out.write(original_data[:links_offset])

        write_uint32(out, len(new_links_data))
        for value in new_links_data:
            write_int32(out, value)

        out.write(original_data[links_end:])

    print("=" * 60)
    print(f"Successfully exported WAD to: {filepath}")
    print(f"  Patched {len(modified_joints)} movables")
    print("=" * 60)

    return {'FINISHED'}


class ExportWAD(bpy.types.Operator, ExportHelper):
    """Export modified movable to WAD/WAD2 file"""
    bl_idname = "export_scene.wad"
    bl_label = "Export WAD"
    bl_options = {'PRESET'}

    filename_ext = ".wad"

    filter_glob: StringProperty(
        default="*.wad",
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
        description="Scale factor for converting Blender units to TR units",
        default=512.0,
        min=1.0,
        max=10000.0
    )

    game: EnumProperty(
        name="Game",
        description="Game version for movable name mapping",
        items=[
            ('TR4', "TR4", ""),
            ('TR5', "TR5", ""),
            ('TR5Main', "TR5Main", ""),
            ('TR3', "TR3", ""),
            ('TR2', "TR2", ""),
            ('TR1', "TR1", ""),
        ],
        default='TR4',
    )

    export_format: EnumProperty(
        name="Format",
        description="Export format",
        items=[
            ('WAD', "Classic WAD", "Export as classic WAD format (requires original WAD)"),
            # ('WAD2', "WAD2", "Export as WAD2 format (DISABLED - unstable)"),
        ],
        default='WAD',
    )

    export_textures: BoolProperty(
        name="Export Textures",
        description="Include texture data in WAD2 export",
        default=True,
    )

    export_animations: BoolProperty(
        name="Export Animations",
        description="Include animation data in WAD2 export",
        default=True,
    )

    def execute(self, context):
        # Classic WAD export only
        if not self.import_path or not os.path.exists(self.import_path):
            self.report({'ERROR'}, "Classic WAD export requires original WAD file. Please specify the original WAD path.")
            return {'CANCELLED'}

        # Ensure .wad extension
        if not self.filepath.lower().endswith('.wad'):
            self.filepath = os.path.splitext(self.filepath)[0] + '.wad'

        return export_wad(context, self.filepath, self.import_path, self.scale, self.game)

    def invoke(self, context, event):
        # Auto-detect original WAD path from import
        if hasattr(context.scene, 'wad_import_path') and context.scene.wad_import_path:
            self.import_path = context.scene.wad_import_path
            print(f"Auto-detected original WAD: {self.import_path}")
        else:
            print("No original WAD path found - you'll need to specify it manually")

        return super().invoke(context, event)

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="WAD Export Settings", icon="EXPORT")

        row = box.row()
        row.prop(self, "export_format")

        if self.export_format == 'WAD':
            row = box.row()
            row.prop(self, "import_path")

            if self.import_path:
                row = box.row()
                row.label(text=f"Using: {os.path.basename(self.import_path)}", icon="FILE")
            else:
                row = box.row()
                row.label(text="No original WAD specified", icon="ERROR")
                row = box.row()
                row.label(text="Classic WAD export requires original file")
        else:
            row = box.row()
            row.prop(self, "export_textures")
            row = box.row()
            row.prop(self, "export_animations")

        box.separator()
        row = box.row()
        row.prop(self, "scale")

        row = box.row()
        row.prop(self, "game")


def menu_func_export(self, context):
    self.layout.operator(ExportWAD.bl_idname, text="Tomb Raider WAD (.wad)")


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
