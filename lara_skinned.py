import os
import math
from collections import defaultdict

import bpy

from .create_materials import apply_textures, pack_textures
from .objects import lara_skin_names, lara_skin_joints_names


# Bone name mapping from Lara mesh names to TEN format
BONE_RENAME_MAP = {
    'LARA_HIPS_BONE': 'Mesh_12',
    'LARA_LEFT_THIGH_BONE': 'Mesh_13',
    'LARA_LEFT_SHIN_BONE': 'Mesh_14',
    'LARA_LEFT_FOOT_BONE': 'Mesh_15',
    'LARA_RIGHT_THIGH_BONE': 'Mesh_16',
    'LARA_RIGHT_SHIN_BONE': 'Mesh_17',
    'LARA_RIGHT_FOOT_BONE': 'Mesh_18',
    'LARA_TORSO_BONE': 'Mesh_19',
    'LARA_RIGHT_UPPER_ARM_BONE': 'Mesh_20',
    'LARA_RIGHT_FOREARM_BONE': 'Mesh_21',
    'LARA_RIGHT_HAND_BONE': 'Mesh_22',
    'LARA_LEFT_UPPER_ARM_BONE': 'Mesh_23',
    'LARA_LEFT_FOREARM_BONE': 'Mesh_24',
    'LARA_LEFT_HAND_BONE': 'Mesh_25',
    'LARA_HEAD_BONE': 'Mesh_26',
}


def extract_pivot_points(meshnames, joints, scale, is_wad2=False):
    root_name = meshnames[0]
    parent = root_name
    prev = parent
    stack = [root_name] * 1000
    pivot_points = {}
    pivot_points[root_name] = (0., 0., 0.)
    parents = {}
    for j in range(1, len(meshnames)):
        cur = meshnames[j]
        use_op_joints = len(joints) == len(meshnames) - 1 and all(
            len(joint) >= 1 and joint[0] in (0, 1, 2, 3) for joint in joints
        )
        if is_wad2 and not use_op_joints:
            def resolve(idx, visiting):
                name = meshnames[idx]
                if name in pivot_points:
                    return
                if idx in visiting:
                    return
                visiting.add(idx)

                joint_idx = idx if len(joints) == len(meshnames) else idx - 1
                if 0 <= joint_idx < len(joints):
                    parent_idx, dx, dy, dz = joints[joint_idx]
                else:
                    parent_idx, dx, dy, dz = -1, 0, 0, 0

                if 0 <= parent_idx < len(meshnames):
                    parent_name = meshnames[parent_idx]
                else:
                    parent_name = root_name
                parents[name] = parent_name

                if parent_name not in pivot_points:
                    resolve(parent_idx, visiting)

                px, py, pz = pivot_points.get(parent_name, (0.0, 0.0, 0.0))
                pivot_points[name] = (px + dx / scale, py + dy / scale, pz + dz / scale)
                visiting.remove(idx)

            resolve(j, set())
            prev = cur
            continue
        else:
            if j - 1 < len(joints):
                op, dx, dy, dz = joints[j-1]
            else:
                op, dx, dy, dz = 0, 0, 0, 0
            if op == 0:
                parent = prev
            elif op == 1:
                parent = stack.pop()
            elif op == 2:
                parent = prev
                stack.append(parent)
            else:
                parent = stack[-1]

        parents[cur] = parent
        px, py, pz = pivot_points[parent]
        pivot_points[cur] = (px + dx / scale, py + dy / scale, pz + dz / scale)
        prev = cur

    return pivot_points


def join_skin(lara_skin_meshes, lara_skin_joints_meshes, vertexfile, d=0.005):
    def find_overlapping_vertices(bone, joint):
        bone = next(mesh for mesh in lara_skin_meshes if bone in mesh.name)
        joint = next(mesh for mesh in lara_skin_joints_meshes if joint in mesh.name)

        vertices = []
        for vert in bone.data.vertices:
            dist = float('inf')
            idx = -1
            for v in joint.data.vertices:
                cur_dist = (joint.matrix_world @ v.co - bone.matrix_world @ vert.co).length
                if cur_dist < dist:
                    dist = cur_dist
                    idx = v.index

            if dist < d:
                vertices.append(idx)

        joint.vertex_groups.new(name=bone.name + '_BONE')
        joint.vertex_groups[bone.name + '_BONE'].add(vertices, 1.0, "ADD")
        return vertices

    vx = defaultdict(set)
    for i, sjm in enumerate(lara_skin_joints_meshes):
        for v in sjm.data.vertices:
            vx[i].add(v.index)

    with open(vertexfile, 'r') as f:
        lines = f.readlines()

    for line in lines:
        joint, bone = line.split()
        idx = next((k for k, e in enumerate(lara_skin_joints_meshes) if joint in e.name), None)
        if idx is None:
            continue
        try:
            vertices = find_overlapping_vertices(bone, joint)
        except StopIteration:
            continue
        for e in vertices:
            vx[idx].discard(e)

    for k, v in vx.items():
        joint = lara_skin_joints_meshes[k]
        for vg in joint.vertex_groups:
            vg.add(list(vx[k]), 1.0, "ADD")


def create_lara_skeleton(rig, pivot_points, lara_skin_meshes, lara_skin_joints_meshes, bonesfile, vertexfile, scale, is_wad2=False):
    bpy.ops.object.mode_set(mode='EDIT')
    amt = rig.data

    def create_bone(node, parent=None, child=None):
        bonename = next(
            mesh.name + '_BONE' for mesh in lara_skin_meshes if node in mesh.name)
        bone = amt.edit_bones.new(bonename)
        bone.head = pivot_points[node]
        x, y, z = pivot_points[node]

        tail_dir = (0.0, 1.0, 0.0)

        tail_len = 100 / scale if 'foot' in bonename else 45 / scale
        dx, dy, dz = tail_dir
        bone.tail = (x + dx * tail_len, y + dy * tail_len, z + dz * tail_len)

        if parent is not None:
            parent = next(
                mesh.name + '_BONE' for mesh in lara_skin_meshes if parent in mesh.name)
            bone.parent = amt.edit_bones[parent]

    with open(bonesfile, 'r') as f:
        for line in f:
            create_bone(*line.split())

    for mesh in lara_skin_meshes:
        bonename = mesh.name + '_BONE'
        mesh.vertex_groups.new(name=bonename)
        mesh.vertex_groups[bonename].add(
            [vert.index for vert in mesh.data.vertices], 1.0, "ADD")
        mesh.parent = rig
        modifier = mesh.modifiers.new(type='ARMATURE', name=rig.name)
        modifier.object = rig

    join_skin(lara_skin_meshes, lara_skin_joints_meshes, vertexfile)

    for mesh in lara_skin_joints_meshes:
        mesh.parent = rig
        modifier = mesh.modifiers.new(type='ARMATURE', name=rig.name)
        modifier.object = rig


def paint_vertex(mesh):
    vcol_layer = mesh.color_attributes.new(name='shade', type='BYTE_COLOR', domain='CORNER')

    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vcol_layer.data[loop_index].color = (0.5, 0.5, 0.5, 1.0)


def main(context, materials, wad, options):
    """Import only LARA with skinned mesh and TEN bone names"""

    print("=" * 60)
    print("Importing Lara's Outfit (Skinned) with TEN bone names...")
    print("=" * 60)

    # Create collection (clean up any existing one first)
    main_collection = bpy.data.collections.get('Collection')

    # Remove existing Lara_Skinned collection if it exists
    old_col = bpy.data.collections.get('Lara_Skinned')
    if old_col:
        # Remove all objects in the collection
        for obj in old_col.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        # Remove the collection itself
        bpy.data.collections.remove(old_col)

    col_skinned = bpy.data.collections.new('Lara_Skinned')
    main_collection.children.link(col_skinned)

    # Find LARA, LARA_SKIN, and LARA_SKIN_JOINTS movables
    movables = {}
    pivot_points = {}
    meshes2 = []
    lara_objs = []

    for movable in wad.movables:
        idx = str(movable.idx)
        if idx in options.mov_names:
            movable_name = options.mov_names[idx]
        else:
            movable_name = 'MOVABLE' + idx

        if movable_name not in {'LARA_SKIN', 'LARA_SKIN_JOINTS'}:
            continue

        mesh_objects = []
        bodyparts_names = []

        for j, m in enumerate(movable.meshes):
            verts = [[v/options.scale for v in e] for e in m.vertices]
            faces = [e.face for e in m.polygons]

            if movable_name == 'LARA_SKIN':
                bodypart_name = lara_skin_names[j]
            elif movable_name == 'LARA_SKIN_JOINTS':
                bodypart_name = lara_skin_joints_names[j]
            else:
                bodypart_name = lara_skin_names[j]

            bodyparts_names.append(bodypart_name)

            mesh_name = 'LARA_' + bodypart_name
            mesh_data = bpy.data.meshes.new(mesh_name)
            mesh_data.from_pydata(verts, [], faces)
            mesh_data.update()

            mesh_obj = bpy.data.objects.new(mesh_name, mesh_data)
            col_skinned.objects.link(mesh_obj)

            # Smooth shading
            for polygon in mesh_data.polygons:
                polygon.use_smooth = True
            mesh_data.update()

            bpy.context.view_layer.objects.active = mesh_obj
            bpy.ops.object.shade_smooth()
            # mesh_obj.data.use_auto_smooth removed in Blender 5.0+

            if not options.one_material_per_object:
                apply_textures(context, m, mesh_obj, materials, options)
                if options.flip_normals:
                    mesh_obj.data.flip_normals()
            else:
                meshes2.append(m)
                lara_objs.append(mesh_obj)

            mesh_objects.append(mesh_obj)
            paint_vertex(mesh_data)

        movables[movable_name] = mesh_objects
        ppoints = extract_pivot_points(bodyparts_names, movable.joints, options.scale, options.is_wad2)
        pivot_points[movable_name] = ppoints

        for bodypart, obj in zip(bodyparts_names, mesh_objects):
            obj.location = ppoints[bodypart]

    if options.one_material_per_object:
        pack_textures(context, meshes2, lara_objs, options, 'LARA')
        for obj in lara_objs:
            if options.flip_normals:
                obj.data.flip_normals()

    # Create armature
    amt = bpy.data.armatures.new('Lara_Skinned_BONES')
    rig = bpy.data.objects.new("Lara_Rig_Skinned", amt)
    col_skinned.objects.link(rig)
    bpy.context.view_layer.objects.active = rig

    # Create skeleton
    cur_script_path = os.path.dirname(os.path.realpath(__file__))
    bonesfile = cur_script_path + '\\resources\\bones.txt'
    vertexfile = cur_script_path + '\\resources\\skin_links.txt'
    create_lara_skeleton(rig, pivot_points['LARA_SKIN'], movables['LARA_SKIN'],
                        movables['LARA_SKIN_JOINTS'], bonesfile, vertexfile, options.scale, options.is_wad2)

    # Rename bones to TEN format
    # Make sure we're in EDIT mode to rename bones
    bpy.context.view_layer.objects.active = rig
    if rig.mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')

    # Get actual bone names (they have .001 suffix BEFORE _BONE)
    # Pattern: LARA_HIPS.001_BONE instead of LARA_HIPS_BONE
    bone_name_mapping = {}
    for edit_bone in rig.data.edit_bones:
        # Extract base name by removing .001_BONE or _BONE suffix
        bone_base = edit_bone.name
        if '_BONE' in bone_base:
            # Remove _BONE suffix
            bone_base = bone_base.replace('_BONE', '')
            # Remove .001 or similar numeric suffix
            if '.' in bone_base:
                bone_base = bone_base.split('.')[0]

            # Reconstruct expected name: LARA_HIPS -> LARA_HIPS_BONE
            expected_name = bone_base + '_BONE'

            # Check if this matches any of our map entries
            if expected_name in BONE_RENAME_MAP:
                bone_name_mapping[edit_bone.name] = BONE_RENAME_MAP[expected_name]

    # Rename the bones
    for old_name, new_name in bone_name_mapping.items():
        if old_name in rig.data.edit_bones:
            rig.data.edit_bones[old_name].name = new_name

    bpy.ops.object.mode_set(mode='OBJECT')

    # Rename vertex groups in mesh objects
    all_meshes = movables['LARA_SKIN'] + movables['LARA_SKIN_JOINTS']
    for mesh_obj in all_meshes:
        # Build mapping for this mesh's vertex groups (same pattern as bones)
        vg_name_mapping = {}
        for vg in mesh_obj.vertex_groups:
            vg_base = vg.name
            if '_BONE' in vg_base:
                # Remove _BONE suffix
                vg_base = vg_base.replace('_BONE', '')
                # Remove .001 or similar numeric suffix
                if '.' in vg_base:
                    vg_base = vg_base.split('.')[0]

                # Reconstruct expected name
                expected_name = vg_base + '_BONE'

                # Check if this matches any of our map entries
                if expected_name in BONE_RENAME_MAP:
                    vg_name_mapping[vg.name] = BONE_RENAME_MAP[expected_name]

        # Rename vertex groups
        for old_name, new_name in vg_name_mapping.items():
            if old_name in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups[old_name].name = new_name

    # Apply rotation
    rig.rotation_mode = 'ZXY'
    if not getattr(options, "is_wad2", False):
        rig.rotation_euler[1] = math.pi
        rig.rotation_euler[0] = math.pi/2
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    print(f"Successfully imported skinned Lara with TEN bone names")
    print("Bones renamed to Mesh_12 through Mesh_26")
    print("=" * 60)
