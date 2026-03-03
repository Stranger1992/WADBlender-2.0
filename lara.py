import os
import math
from collections import defaultdict

import bpy

from .create_materials import apply_textures, pack_textures
from .animations import create_animations, save_animations_data
from .objects import lara_skin_names, lara_skin_joints_names


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
            # find closest skin joint vertex
            dist = float('inf')
            idx = -1
            for v in joint.data.vertices:
                cur_dist = (joint.matrix_world @ v.co - bone.matrix_world @ vert.co).length
                if cur_dist < dist:
                    dist = cur_dist
                    idx = v.index
            
            # if vertex is close enough, add it to vertex group
            if dist < d :
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
        # find non overlapping skin joint vertices (the ones that do not connect directly to adjacent meshes)
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

    # add them to all vertex groups (e.g. the vertices in the middle of the knee 
    # are added to the vertex groups of both thigh and leg)
    for k, v in vx.items():
        joint = lara_skin_joints_meshes[k]
        for vg in joint.vertex_groups:
            vg.add(list(vx[k]), 1.0, "ADD")


def create_lara_skeleton(rig, pivot_points, lara_skin_meshes, lara_skin_joints_meshes, bonesfile, vertexfile, scale, is_wad2=False):
    # create bones
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

    # weight paint
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
    meshes2replace = {}
    meshes2replace['LARA'] = []
    meshes2replace['PISTOLS_ANIM'] = ['LEFT_THIGH', 'RIGHT_THIGH', 'RIGHT_HAND', 'LEFT_HAND']
    meshes2replace['UZI_ANIM'] = ['LEFT_THIGH', 'RIGHT_THIGH', 'RIGHT_HAND', 'LEFT_HAND', 'HEAD']
    meshes2replace['SHOTGUN_ANIM'] = ['RIGHT_HAND', 'HEAD']
    meshes2replace['CROSSBOW_ANIM'] = ['RIGHT_HAND', 'HEAD']
    meshes2replace['GRENADE_GUN_ANIM'] = ['RIGHT_HAND', 'HEAD']
    meshes2replace['SIXSHOOTER_ANIM'] = ['LEFT_THIGH', 'RIGHT_HAND']
    meshes2replace['FLARE_ANIM'] = ['LEFT_HAND']
    meshes2replace['CROWBAR_ANIM'] = ['RIGHT_HAND']
    meshes2replace['TORCH_ANIM'] = ['LEFT_HAND']
    meshes2replace['VEHICLE_EXTRA'] = []
    meshes2replace['LARA_SCREAM'] = ['HEAD']

    main_collection = bpy.data.collections.get('Collection')
    col_lara = bpy.data.collections.new('Lara')
    main_collection.children.link(col_lara)

    for anim, replacements in meshes2replace.items():
        found = False
        for movable in wad.movables:
            item_idx = str(movable.idx)
            if item_idx in options.mov_names:
                movable_name = options.mov_names[item_idx]
            else:
                movable_name = 'MOVABLE' + item_idx

            if movable_name == anim:
                found = True
                break

        if not found:
            continue

        indices = [lara_skin_names.index(name) for name in replacements if name in lara_skin_names]

        if anim not in meshes2replace:
            continue

        col = bpy.data.collections.new(anim)
        col_lara.children.link(col)

        movables = {}
        pivot_points = {}
        animations = {}
        meshes2 = []  
        lara_objs = [] 
        for i, movable in enumerate(wad.movables):
            idx = str(movable.idx)
            if idx in options.mov_names:
                movable_name = options.mov_names[idx]
            else:
                movable_name = 'MOVABLE' + idx
            if movable_name not in {anim, 'LARA_SKIN', 'LARA_SKIN_JOINTS'}:
                continue


            animations[movable_name] = movable.animations

            mesh_objects = []
            bodyparts_names = []
            for j, m in enumerate(movable.meshes):
                verts = [[v/options.scale for v in e] for e in m.vertices]
                faces = [e.face for e in m.polygons]
                normals = m.normals

                if movable_name == 'LARA_SKIN':
                    bodypart_name = lara_skin_names[j] 
                elif movable_name == 'LARA_SKIN_JOINTS':
                    bodypart_name = lara_skin_joints_names[j]
                else:
                    bodypart_name = lara_skin_names[j] + '.gun'

                bodyparts_names.append(bodypart_name)

                mesh_name = anim + '_' + bodypart_name
                mesh_data = bpy.data.meshes.new(mesh_name)
                mesh_data.from_pydata(verts, [], faces)
                mesh_data.update()

                mesh_obj = bpy.data.objects.new(mesh_name, mesh_data)
                col.objects.link(mesh_obj)

                # Use smooth shading with weighted normals for better appearance
                for polygon in mesh_data.polygons:
                    polygon.use_smooth = True
                mesh_data.update()

                # Calculate weighted normals for smooth shading
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
            pack_textures(context, meshes2, lara_objs, options, anim)

            for obj in lara_objs:
                if options.flip_normals:
                    obj.data.flip_normals()

        lara_skin_meshes = movables.get('LARA_SKIN', [])
        lara_skin_joints = movables.get('LARA_SKIN_JOINTS', [])
        anim_meshes = movables.get(anim, [])
        if not lara_skin_meshes or not lara_skin_joints or not anim_meshes:
            continue

        for i in range(len(lara_skin_meshes)):
            if i in indices:
                if i < len(anim_meshes):
                    bpy.data.objects.remove(lara_skin_meshes[i], do_unlink=True)
                    lara_skin_meshes[i] = anim_meshes[i]
            else:
                if i < len(anim_meshes):
                    bpy.data.objects.remove(anim_meshes[i], do_unlink=True)

        for i in range(len(lara_skin_meshes), len(anim_meshes)):
            bpy.data.objects.remove(anim_meshes[i], do_unlink=True)

        for obj in lara_skin_meshes:
            if obj.name.endswith('.gun'):
                obj.name = obj.name[:-4]

        amt = bpy.data.armatures.new(anim + '_BONES')
        rig = bpy.data.objects.new(anim + "_RIG", amt)
        col.objects.link(rig)
        bpy.context.view_layer.objects.active = rig

        cur_script_path = os.path.dirname(os.path.realpath(__file__))
        bonesfile = cur_script_path + '\\resources\\bones.txt'
        vertexfile = cur_script_path + '\\resources\\skin_links.txt'
        create_lara_skeleton(rig, pivot_points['LARA_SKIN'], lara_skin_meshes,
                            lara_skin_joints, bonesfile, vertexfile, options.scale, options.is_wad2)

        bonenames = [mesh_data.name + '_BONE' for mesh_data in lara_skin_meshes]

        rig.rotation_mode = 'ZXY'
        bpy.ops.object.mode_set(mode="OBJECT")
        if not getattr(options, "is_wad2", False):
            rig.rotation_euler[1] = math.pi
            rig.rotation_euler[0] = math.pi/2
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        if options.export_fbx:
            filepath = options.path + '\\{}.fbx'.format(anim)
            bpy.ops.object.select_all(action='DESELECT')

            bpy.context.view_layer.objects.active = rig
            for obj in col.objects:
                obj.select_set(True)
            bpy.ops.export_scene.fbx(filepath=filepath, axis_forward='Z', use_selection=True, add_leaf_bones=False, bake_anim_use_all_actions =False)

        if options.export_obj:
            filepath = options.path + '\\{}.obj'.format(anim)

            bpy.ops.object.select_all(action='DESELECT')
            for obj in col.objects:
                obj.select_set(True)
            bpy.ops.export_scene.obj(filepath=filepath, axis_forward='Z', use_selection=True)

        if options.import_anims:
            create_animations(item_idx, rig, bonenames, animations[anim], options)

        if options.export_json:
            save_animations_data(item_idx, animations[anim], anim, options)
            
        bpy.context.view_layer.layer_collection.children['Collection'].children['Lara'].children[anim].hide_viewport = True
