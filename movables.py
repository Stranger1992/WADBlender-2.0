import math

import bpy

from .objects import movables2discard
from .create_materials import apply_textures, pack_textures, pack_wad2_textures
from .animations import create_animations, save_animations_data

def paint_vertex(mesh):
    vcol_layer = mesh.color_attributes.new(name='shade', type='BYTE_COLOR', domain='CORNER')

    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vcol_layer.data[loop_index].color = (0.5, 0.5, 0.5, 1.0)




def main(context, materials, wad, options):
    movable_objects = {}
    animations = {}
    main_collection = bpy.data.collections.get('Collection')
    if bpy.data.collections.find('Movables') == -1:
        col_movables = bpy.data.collections.new('Movables')
    else:
        col_movables = bpy.data.collections['Movables']

    if 'Movables' not in main_collection.children:
        main_collection.children.link(col_movables)

    for i, movable in enumerate(wad.movables):
        idx = str(movable.idx)
        if idx in options.mov_names:
            name = options.mov_names[idx]
            if name == 'VEHICLE_EXTRA':
                name = 'VEHICLE_EXTRA_MVB'
        else:
            name = 'MOVABLE' + idx

        if options.single_object and name != options.object:
            continue

        if not options.single_object and name in movables2discard:
            continue

        collection = bpy.data.collections.new(name)
        col_movables.children.link(collection)

        meshes = []
        meshes2 = []
        model_meshes = []  # WAD2: keep model mesh data for pack_wad2_textures
        for j, m in enumerate(movable.meshes):
            verts = [[v / options.scale for v in e] for e in m.vertices]
            faces = [e.face for e in m.polygons]
            shine = [e.shine for e in m.polygons]
            shineIntensity = [e.intensity for e in m.polygons]
            opacity = [e.opacity for e in m.polygons]
            mesh_name = name + '.' + str(j).zfill(3)
            mesh_data = bpy.data.meshes.new(mesh_name)
            mesh_obj = bpy.data.objects.new(mesh_name, mesh_data)
            mesh_obj['boundingSphereCenter'] = [e / options.scale for e in m.boundingSphereCenter]
            mesh_obj['boundingSphereRadius'] = m.boundingSphereRadius / options.scale

            mesh_obj['shine'] = shine
            mesh_obj['shineIntensity'] = shineIntensity
            mesh_obj['opacity'] = opacity

            collection.objects.link(mesh_obj)
            bpy.context.view_layer.objects.active = mesh_obj
            mesh_data.from_pydata(verts, [], faces)
            mesh_data.update()

            # Store texture data as custom properties on each face
            # Only for classic WAD - needed for export
            # Note: Blender 5.0+ doesn't support custom properties on polygons, so we skip this
            if not options.is_wad2:
                try:
                    for poly_idx, (blender_poly, wad_poly) in enumerate(zip(mesh_data.polygons, m.polygons)):
                        if hasattr(wad_poly, 'texture_index'):
                            blender_poly['wad_texture_index'] = wad_poly.texture_index
                            blender_poly['wad_texture_flipped'] = wad_poly.texture_flipped
                            blender_poly['wad_intensity'] = wad_poly.intensity
                            blender_poly['wad_shine'] = wad_poly.shine
                            blender_poly['wad_opacity'] = wad_poly.opacity
                except TypeError:
                    # Blender 5.0+ doesn't support polygon custom properties
                    # Classic WAD export will need to be adjusted to work without these
                    pass

            # Use smooth shading with weighted normals for better appearance
            for polygon in mesh_data.polygons:
                polygon.use_smooth = True
            mesh_data.update()

            # Calculate weighted normals for smooth shading
            bpy.context.view_layer.objects.active = mesh_obj
            bpy.ops.object.shade_smooth()
            # mesh_obj.data.use_auto_smooth removed in Blender 5.0+

            if not options.one_material_per_object:
                if getattr(options, 'wad2_pack_textures', False):
                    model_meshes.append(m)  # collect for pack_wad2_textures
                else:
                    apply_textures(context, m, mesh_obj, materials, options)
                if options.flip_normals:
                    mesh_data.flip_normals()
            else:
                meshes2.append(m)
            paint_vertex(mesh_data)
            meshes.append(mesh_obj)

        if options.one_material_per_object:
            pack_textures(context, meshes2, meshes, options, name)
            for obj in meshes:
                if options.flip_normals:
                    obj.data.flip_normals()
        elif getattr(options, 'wad2_pack_textures', False) and model_meshes:
            wad = getattr(options, 'wad', None)
            if wad:
                pack_wad2_textures(context, model_meshes, meshes, options, wad, name)

        movable_objects[name] = meshes
        animations[name] = movable.animations

        meshnames = [m.name for m in meshes]
        
        parent = meshes[0].name
        prev = parent
        stack = [meshes[0].name] * 100
        cpivot_points = {}
        cpivot_points[meshes[0].name] = (0., 0., 0.)
        parents = {}
        if len(meshes) > 1:
            use_op_joints = len(movable.joints) == len(meshes) - 1 and all(
                len(joint) >= 1 and joint[0] in (0, 1, 2, 3) for joint in movable.joints
            )
            if options.is_wad2 and not use_op_joints:
                for j in range(1, len(meshes)):
                    cur = meshnames[j]
                    joint_idx = j if len(movable.joints) == len(meshes) else j - 1
                    if joint_idx < len(movable.joints):
                        parent_idx, dx, dy, dz = movable.joints[joint_idx]
                    else:
                        parent_idx, dx, dy, dz = -1, 0, 0, 0

                    if 0 <= parent_idx < len(meshes):
                        parent = meshnames[parent_idx]
                    else:
                        parent = meshnames[0]

                    parents[cur] = parent
                    px, py, pz = cpivot_points[parent]
                    s = options.scale
                    cpivot_points[cur] = (px + dx / s, py + dy / s, pz + dz / s)
                    mesh_obj = next(mesh for mesh in meshes if mesh.name == cur)
                    mesh_obj.location = cpivot_points[cur]
                    prev = cur
            else:
                for j in range(1, len(meshes)):
                    if j - 1 < len(movable.joints):
                        op, dx, dy, dz = movable.joints[j-1]
                    else:
                        op, dx, dy, dz = 0, 0, 0, 0
                    cur = meshnames[j]
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
                    px, py, pz = cpivot_points[parent]
                    s = options.scale
                    cpivot_points[cur] = (px + dx / s, py + dy / s, pz + dz / s)
                    mesh_obj = next(mesh for mesh in meshes if mesh.name == cur)
                    mesh_obj.location = cpivot_points[cur]
                    prev = cur

        amt = bpy.data.armatures.new(name)
        rig = bpy.data.objects.new(name + '_RIG', amt)
        collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig

        bone_tail_offset = (0.0, 100 / options.scale, 0.0)

        bpy.ops.object.mode_set(mode='EDIT')
        for cur in meshnames:
            if cur not in parents:
                bone = amt.edit_bones.new(cur)
                bx, by, bz = (0.0, 0.0, 0.0)
                ox, oy, oz = bone_tail_offset
                bone.head, bone.tail = (bx, by, bz), (bx + ox, by + oy, bz + oz)
                bone = None
            else:
                tail = [child for child, parent in parents.items() if parent == cur]
                
                if len(tail) > 0:
                    bone = amt.edit_bones.new(cur)
                    bone.head, bone.tail = cpivot_points[cur], cpivot_points[tail[0]]
                    x, y, z = cpivot_points[cur]
                    ox, oy, oz = bone_tail_offset
                    bone.head, bone.tail = cpivot_points[cur], (x + ox, y + oy, z + oz)
                    bone.parent = amt.edit_bones[parents[cur]]
                    if bone.head == bone.tail:
                        if getattr(options, "is_wad2", False):
                            bone.tail[2] -= 0.001
                        else:
                            bone.tail[1] += 0.001
                    bone = None
                else:
                    bone = amt.edit_bones.new(cur)
                    x, y, z = cpivot_points[cur]
                    ox, oy, oz = bone_tail_offset
                    bone.head, bone.tail = cpivot_points[cur], (x + ox, y + oy, z + oz)
                    bone.parent = amt.edit_bones[parents[cur]]
                    bone = None

        bone = None
        bpy.ops.object.mode_set(mode="OBJECT")

        for i in range(len(meshes)):
            mesh = meshes[i]
            bonename = mesh.name
            mesh.vertex_groups.new(name=bonename)
            mesh = None
            
        for i in range(len(meshes)):
            mesh = meshes[i]
            bonename = mesh.name
            vertices = [vert.index for vert in mesh.data.vertices]
            mesh.vertex_groups[bonename].add(vertices, 1.0, "ADD")
            mesh.parent = rig
            modifier = mesh.modifiers.new(type='ARMATURE', name=rig.name)
            modifier.object = rig

        if options.import_anims:
            create_animations(idx, rig, meshnames, animations[name], options)

        if options.export_json:
            save_animations_data(idx, animations[name], name, options)

        if not getattr(options, "is_wad2", False):
            # Set rotation for visual display but DON'T apply transform
            # This keeps coordinates in TR space for correct export
            rig.rotation_mode = 'ZXY'
            rig.rotation_euler[1] = math.pi
            rig.rotation_euler[0] = math.pi/2

        if options.export_fbx:
            filepath = options.path + '\\{}.fbx'.format(name)
            bpy.ops.object.select_all(action='DESELECT')

            bpy.context.view_layer.objects.active = rig
            for obj in collection.objects:
                obj.select_set(True)
            bpy.ops.export_scene.fbx(filepath=filepath, axis_forward='Z', use_selection=True, add_leaf_bones=False, bake_anim_use_all_actions =False)


        if options.export_obj:
            filepath = options.path + '\\{}.obj'.format(name)
            bpy.ops.object.select_all(action='DESELECT')

            bpy.context.view_layer.objects.active = rig
            for obj in collection.objects:
                obj.select_set(True)
            bpy.ops.export_scene.obj(filepath=filepath, axis_forward='Z', use_selection=True)
            
        if not options.single_object:
            bpy.context.view_layer.layer_collection.children['Collection'].children['Movables'].children[name].hide_viewport = True
