import json
from typing import List, Tuple, Dict
from collections import defaultdict

import bpy
from bpy_extras import anim_utils
from mathutils import Euler, Quaternion


def create_animations(item_idx, rig, bonenames, animations, options):
    if rig.animation_data is None:
        rig.animation_data_create()

    for idx, animation in enumerate(animations):
        if item_idx in options.anim_names and str(idx) in options.anim_names[item_idx]:
            name = ' - '.join((rig.name, str(idx).zfill(3), options.anim_names[item_idx][str(idx)])) 
        else:
            name = ' - '.join((rig.name, str(idx).zfill(3))) 
        action = bpy.data.actions.new(name)

        offsets = [keyframe.offset for keyframe in animation.keyFrames]
        rotations = defaultdict(list)
        for keyframe in animation.keyFrames:
            for bonename, rot in zip(bonenames, keyframe.rotations):
                if len(rot) == 4:
                    quat = Quaternion(rot)
                else:
                    angle = Euler(rot, 'ZXY')
                    quat = angle.to_quaternion()
                rotations[bonename].append(quat)

        # Blender 5.0+ uses channelbags instead of direct action.fcurves
        # Assign action to rig
        rig.animation_data.action = action
        # Check if slot was auto-assigned, if not create and assign one
        if rig.animation_data.action_slot is None:
            # Check for suitable existing slots
            if len(rig.animation_data.action_suitable_slots) > 0:
                rig.animation_data.action_slot = rig.animation_data.action_suitable_slots[0]
            else:
                # Create a new slot and assign it
                slot = action.slots.new(id_type='OBJECT', name=rig.name)
                rig.animation_data.action_slot = slot
        # Get the assigned slot
        slot = rig.animation_data.action_slot
        # Use helper function to ensure channelbag exists
        channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        fcurves = channelbag.fcurves

        for axis in [0, 1, 2]:
            fc = fcurves.new(
                data_path='pose.bones["{}"].location'.format(bonenames[0]), index=axis)
            keyframe_points = fc.keyframe_points
            keyframe_points.add(len(offsets))
            for j, val in enumerate(offsets):
                k = 0
                v = val[axis]

                keyframe_points[j].co = (j, v / options.scale)

        for bonename in bonenames:
            for axis in [0, 1, 2, 3]:
                data_path = 'pose.bones["{}"].rotation_quaternion'.format(
                    bonename)
                fc = fcurves.new(data_path=data_path, index=axis)
                keyframe_points = fc.keyframe_points
                keyframe_points.add(len(rotations[bonename]))
                for j, rot in enumerate(rotations[bonename]):
                    keyframe_points[j].co = (j, rot[axis])

        action.use_fake_user = True

        # Store WAD animation metadata as custom properties so the exporter
        # can round-trip them accurately.
        action['state_id']               = animation.stateID
        action['frame_rate']             = animation.frameDuration
        action['next_animation']         = animation.nextAnimation
        action['next_frame']             = animation.frameIn
        action['start_velocity']         = float(animation.speed)
        action['end_velocity']           = float(animation.acceleration)
        action['start_lateral_velocity'] = 0.0
        action['end_lateral_velocity']   = 0.0

        # State changes: {state_id: [(in, out, next_anim, next_frame), ...]}
        sc_list = []
        for sc_id, dispatches in animation.stateChanges.items():
            disp_list = []
            for d in dispatches:
                if isinstance(d, (list, tuple)) and len(d) >= 4:
                    disp_list.append({
                        'in_frame':      int(d[0]),
                        'out_frame':     int(d[1]),
                        'next_animation': int(d[2]),
                        'next_frame':    int(d[3]),
                    })
                elif isinstance(d, dict):
                    disp_list.append(d)
            sc_list.append({'state_id': int(sc_id), 'dispatches': disp_list})
        action['state_changes'] = json.dumps(sc_list)

        # Anim commands: [(type, param1, param2, param3), ...]
        cmd_list = []
        for cmd in animation.commands:
            if isinstance(cmd, (list, tuple)) and len(cmd) >= 4:
                cmd_list.append({
                    'type':   int(cmd[0]),
                    'param1': int(cmd[1]),
                    'param2': int(cmd[2]),
                    'param3': int(cmd[3]),
                })
            elif isinstance(cmd, dict):
                cmd_list.append(cmd)
        action['anim_commands'] = json.dumps(cmd_list)

        track = rig.animation_data.nla_tracks.new()
        name = action.name
        action = bpy.data.actions[name]
        track.name = name
        track.strips.new(action.name, start=0, action=action)

    if options.export_fbx:
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        filepath = options.path + '\\{}.fbx'.format(rig.name)
        bpy.ops.export_scene.fbx(
            filepath=filepath, axis_forward='Z', use_selection=True,
            add_leaf_bones=False, bake_anim_use_all_actions=False, 
            bake_anim_use_nla_strips=True
            )


def save_animations_data(item_idx, animations, filename, options):
    path = options.path

    states = set()
    for idx, a in enumerate(animations):
        states.add(a.stateID)

    class AnimationData:
        idx: str
        name: str
        bboxes: List[Tuple]
        stateChanges: Dict[str, List[Tuple]]
        commands: List[Tuple[int]]
        frameDuration: int
        speed: int
        acceleration: int
        frameStart: int
        frameEnd: int
        frameIn: int
        nextAnimation: str

    saves = {}

    animations_names = options.anim_names
    states_names = options.state_names

    for state in states:
        animations_state = []
        for idx, a in enumerate(animations):
            if a.stateID != state:
                continue

            data = AnimationData()
            data.idx = str(idx).zfill(3)
            str_idx = str(idx)
            if item_idx in animations_names and str_idx in animations_names[item_idx]:
                data.name = animations_names[item_idx][str_idx]
            else:
                data.name = data.idx

            data.frameDuration = a.frameDuration
            data.speed = a.speed
            data.acceleration = a.acceleration
            data.frameStart = a.frameStart
            data.frameEnd = a.frameEnd
            data.frameIN = a.frameIn
            data.nextAnimation = str(a.nextAnimation).zfill(3)

            bboxes = []
            for keyframe in a.keyFrames:
                x0, y0, z0 = keyframe.bb1
                x1, y1, z1 = keyframe.bb2
                bboxes.append((x0, y0, z0, x1, y1, z1))

            data.bboxes = bboxes
            data.commands = a.commands

            data.stateChanges = {}
            for sc, dispatches in a.stateChanges.items():
                d = []
                for dispatch in dispatches:
                    nextAnim = str(dispatch[2]).zfill(3)
                    d.append([dispatch[0], dispatch[1], nextAnim, dispatch[3]])

                data.stateChanges[str(sc).zfill(3)] = d

            animations_state.append(data.__dict__)

        s = str(state).zfill(3)
        if item_idx in states_names and str(state) in states_names[item_idx]:
            saves[s] = states_names[item_idx][str(state)], animations_state
        else:
            saves[s] = 'UNKNOWN_STATE', animations_state

    with open(path + '\\' + filename + '.json', 'w') as f:
        json.dump(saves, f, indent=4)
