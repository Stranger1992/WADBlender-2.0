import os
import math
import re
import xml.etree.ElementTree as ET

import bpy
from bpy_extras import anim_utils
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, EnumProperty, IntProperty
from bpy.types import Operator
from mathutils import Matrix, Quaternion, Euler


template = """<?xml version="1.0" encoding="utf-8"?>
<WadAnimation xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <FrameRate>1</FrameRate>
    <StateId>2</StateId>
    <EndFrame>43</EndFrame>
    <NextAnimation>103</NextAnimation>
    <NextFrame>0</NextFrame>
    <Name>STAND_IDLE</Name>
    <StartVelocity>0</StartVelocity>
    <EndVelocity>0</EndVelocity>
    <StartLateralVelocity>0</StartLateralVelocity>
    <EndLateralVelocity>0</EndLateralVelocity>
    <KeyFrames />
    <StateChanges />
    <AnimCommands />
</WadAnimation>
"""

AXIS_MAT = Matrix(((-1.0, 0.0, 0.0),
                   (0.0, 0.0, -1.0),
                   (0.0, 1.0, 0.0)))
AXIS_MAT_T = AXIS_MAT.transposed()


def _detect_xml_encoding(path):
    try:
        with open(path, "rb") as handle:
            head = handle.read(200)
        match = re.search(br'encoding=["\']([^"\']+)["\']', head)
        if match:
            return match.group(1).decode("ascii", errors="ignore")
    except OSError:
        pass
    return "utf-8"


def _get_or_create(root, tag):
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    return node


def _blender_to_wad_vec(vec):
    return (-vec[0], vec[2], -vec[1])


def _mat_to_yaw_pitch_roll(mat: Matrix):
    m12 = mat[1][2]
    m02 = mat[0][2]
    m22 = mat[2][2]
    m10 = mat[1][0]
    m11 = mat[1][1]

    v = max(-1.0, min(1.0, -m12))
    pitch = math.asin(v)
    cx = math.cos(pitch)
    eps = 1e-6

    if abs(cx) < eps:
        if pitch > 0.0:
            yaw = math.atan2(mat[0][1], mat[0][0])
        else:
            yaw = math.atan2(-mat[0][1], mat[0][0])
        roll = 0.0
    else:
        yaw = math.atan2(m02, m22)
        roll = math.atan2(m10, m11)

    return yaw, pitch, roll


def _get_action_fcurves(rig, action):
    if hasattr(action, "fcurves") and action.fcurves:
        return action.fcurves

    slot = None
    if rig.animation_data and rig.animation_data.action == action:
        slot = rig.animation_data.action_slot

    if slot is None and hasattr(action, "slots"):
        for candidate in action.slots:
            if getattr(candidate, "id_type", None) == "OBJECT" and candidate.name == rig.name:
                slot = candidate
                break
        if slot is None and len(action.slots) > 0:
            slot = action.slots[0]

    if slot is None and hasattr(action, "slots"):
        try:
            slot = action.slots.new(id_type="OBJECT", name=rig.name)
        except Exception:
            slot = None

    if slot is not None:
        channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        return channelbag.fcurves

    return action.fcurves if hasattr(action, "fcurves") else []


def _build_curve_map(fcurves):
    return {(fc.data_path, fc.array_index): fc for fc in fcurves}


def _eval_curve(curve_map, data_path, index, frame, default):
    fc = curve_map.get((data_path, index))
    return fc.evaluate(frame) if fc else default


def _evaluate_quat(curve_map, bone, frame):
    quat_path = f'pose.bones["{bone.name}"].rotation_quaternion'
    has_quat = any((quat_path, idx) in curve_map for idx in range(4))
    if has_quat:
        comps = []
        for idx in range(4):
            default = 1.0 if idx == 0 else 0.0
            comps.append(_eval_curve(curve_map, quat_path, idx, frame, default))
        quat = Quaternion(comps)
    else:
        euler_path = f'pose.bones["{bone.name}"].rotation_euler'
        has_euler = any((euler_path, idx) in curve_map for idx in range(3))
        if has_euler:
            comps = []
            for idx in range(3):
                comps.append(_eval_curve(curve_map, euler_path, idx, frame, 0.0))
            mode = bone.rotation_mode
            if mode in {"QUATERNION", "AXIS_ANGLE"}:
                mode = "XYZ"
            quat = Euler(comps, mode).to_quaternion()
        else:
            quat = Quaternion((1.0, 0.0, 0.0, 0.0))

    length = math.sqrt(quat[0] * quat[0] + quat[1] * quat[1] + quat[2] * quat[2] + quat[3] * quat[3])
    if length == 0.0:
        quat = Quaternion((1.0, 0.0, 0.0, 0.0))
    else:
        quat.normalize()
    return quat


def export_anim(filepath, rig_name, scale, frame_rate):
    import json as _json

    if os.path.exists(filepath):
        tree = ET.parse(filepath)
        root = tree.getroot()
        encoding = _detect_xml_encoding(filepath)
    else:
        root = ET.fromstring(template)
        tree = ET.ElementTree(root)
        encoding = "utf-8"

    keyframes_node = root.find("KeyFrames")
    if keyframes_node is None:
        keyframes_node = ET.SubElement(root, "KeyFrames")
    for keyframe in list(keyframes_node):
        keyframes_node.remove(keyframe)

    rig = bpy.data.objects.get(rig_name)
    if rig is None or rig.type != "ARMATURE":
        raise ValueError("Selected armature is invalid.")
    if rig.animation_data is None or rig.animation_data.action is None:
        raise ValueError("Selected armature has no active action.")

    action = rig.animation_data.action
    fcurves = _get_action_fcurves(rig, action)
    curve_map = _build_curve_map(fcurves)

    bones = list(rig.pose.bones)
    if not bones:
        raise ValueError("Selected armature has no bones.")

    root_bone = bones[0].name

    # frame_rate (UI prop) = sampling step in Blender frames.
    # xml_frame_rate = WAD frame duration stored as custom property (how many
    # game frames each keyframe lasts).  Falls back to the UI value if no
    # custom property is present.
    frame_rate = max(1, int(frame_rate))
    xml_frame_rate = int(action.get('frame_rate', frame_rate))

    start, end = action.frame_range
    start = int(math.floor(start))
    end = int(math.ceil(end))
    if end < start:
        start, end = end, start
    frames = list(range(start, end + 1, frame_rate))
    if not frames:
        frames = [start]

    # Write all animation metadata from stored custom properties.
    _get_or_create(root, "FrameRate").text = str(xml_frame_rate)
    # EndFrame = frame_duration × num_keyframes (matches Tomb Editor convention).
    _get_or_create(root, "EndFrame").text = str(xml_frame_rate * len(frames))
    _get_or_create(root, "StateId").text = str(int(action.get('state_id', 0)))
    _get_or_create(root, "NextAnimation").text = str(int(action.get('next_animation', 0)))
    _get_or_create(root, "NextFrame").text = str(int(action.get('next_frame', 0)))
    _get_or_create(root, "Name").text = action.name
    _get_or_create(root, "StartVelocity").text = str(float(action.get('start_velocity', 0)))
    _get_or_create(root, "EndVelocity").text = str(float(action.get('end_velocity', 0)))
    _get_or_create(root, "StartLateralVelocity").text = str(float(action.get('start_lateral_velocity', 0)))
    _get_or_create(root, "EndLateralVelocity").text = str(float(action.get('end_lateral_velocity', 0)))

    root_loc_path = f'pose.bones["{root_bone}"].location'

    for frame in frames:
        wadkf = ET.SubElement(keyframes_node, "WadKeyFrame")

        bbox = ET.SubElement(wadkf, "BoundingBox")
        minimum = ET.SubElement(bbox, "Minimum")
        ET.SubElement(minimum, "X").text = "0"
        ET.SubElement(minimum, "Y").text = "0"
        ET.SubElement(minimum, "Z").text = "0"

        maximum = ET.SubElement(bbox, "Maximum")
        ET.SubElement(maximum, "X").text = "0"
        ET.SubElement(maximum, "Y").text = "0"
        ET.SubElement(maximum, "Z").text = "0"

        loc = [
            _eval_curve(curve_map, root_loc_path, axis, frame, 0.0)
            for axis in range(3)
        ]
        loc_scaled = (loc[0] * scale, loc[1] * scale, loc[2] * scale)
        offset = _blender_to_wad_vec(loc_scaled)

        offset_node = ET.SubElement(wadkf, "Offset")
        ET.SubElement(offset_node, "X").text = "%.6f" % offset[0]
        ET.SubElement(offset_node, "Y").text = "%.6f" % offset[1]
        ET.SubElement(offset_node, "Z").text = "%.6f" % offset[2]

        angles_node = ET.SubElement(wadkf, "Angles")
        for bone in bones:
            quat = _evaluate_quat(curve_map, bone, frame)
            mat_b = quat.to_matrix()
            mat_w = AXIS_MAT_T @ mat_b @ AXIS_MAT
            yaw, pitch, roll = _mat_to_yaw_pitch_roll(mat_w)

            rot = ET.SubElement(angles_node, "WadKeyFrameRotation")
            rot = ET.SubElement(rot, "Rotations")
            ET.SubElement(rot, "X").text = "%.6f" % math.degrees(pitch)
            ET.SubElement(rot, "Y").text = "%.6f" % math.degrees(yaw)
            ET.SubElement(rot, "Z").text = "%.6f" % math.degrees(roll)

    # Write StateChanges from custom property JSON.
    sc_node = root.find("StateChanges")
    if sc_node is None:
        sc_node = ET.SubElement(root, "StateChanges")
    for child in list(sc_node):
        sc_node.remove(child)

    sc_raw = action.get('state_changes')
    if sc_raw and isinstance(sc_raw, str):
        try:
            sc_list = _json.loads(sc_raw)
            for sc_entry in sc_list:
                wsc = ET.SubElement(sc_node, "WadStateChange")
                ET.SubElement(wsc, "StateId").text = str(int(sc_entry.get('state_id', 0)))
                dispatches_node = ET.SubElement(wsc, "Dispatches")
                for d in sc_entry.get('dispatches', []):
                    wad_d = ET.SubElement(dispatches_node, "WadAnimDispatch")
                    ET.SubElement(wad_d, "InFrame").text = str(int(d.get('in_frame', 0)))
                    ET.SubElement(wad_d, "OutFrame").text = str(int(d.get('out_frame', 0)))
                    ET.SubElement(wad_d, "NextAnimation").text = str(int(d.get('next_animation', 0)))
                    ET.SubElement(wad_d, "NextFrame").text = str(int(d.get('next_frame', 0)))
        except Exception:
            pass

    # Write AnimCommands from custom property JSON.
    cmd_node = root.find("AnimCommands")
    if cmd_node is None:
        cmd_node = ET.SubElement(root, "AnimCommands")
    for child in list(cmd_node):
        cmd_node.remove(child)

    cmd_raw = action.get('anim_commands')
    if cmd_raw and isinstance(cmd_raw, str):
        try:
            cmd_list = _json.loads(cmd_raw)
            for cmd in cmd_list:
                wac = ET.SubElement(cmd_node, "WadAnimCommand")
                ET.SubElement(wac, "Type").text = str(int(cmd.get('type', 0)))
                ET.SubElement(wac, "Parameter1").text = str(int(cmd.get('param1', 0)))
                ET.SubElement(wac, "Parameter2").text = str(int(cmd.get('param2', 0)))
                ET.SubElement(wac, "Parameter3").text = str(int(cmd.get('param3', 0)))
        except Exception:
            pass

    tree.write(filepath, encoding=encoding, xml_declaration=True)


def export(context, filepath, rig_name, scale, frame_rate):
    export_anim(filepath, rig_name, scale, frame_rate)
    return {"FINISHED"}


class ExportAnim(Operator, ExportHelper):
    bl_idname = "wadblender.export_anim"
    bl_label = "Export Wad Tool Animation"

    filename_ext = ".anim"

    filter_glob: StringProperty(
        default="*.anim",
        options={"HIDDEN"},
        maxlen=255,
    )

    def get_actions(self, context):
        actions = []
        for obj in bpy.data.objects:
            if obj.type != "ARMATURE":
                continue
            action_name = (
                obj.animation_data.action.name
                if obj.animation_data and obj.animation_data.action
                else ""
            )
            if action_name:
                actions.append((obj.name, action_name, action_name))
        return actions

    actions: EnumProperty(
        name="Action",
        items=get_actions,
        description="Animation to export.",
    )

    scale: IntProperty(
        name="Scale",
        description="Dividing by 512, one TRLE click becomes 0.5 meters",
        default=512,
        min=1,
        max=100000,
    )

    frame_rate: IntProperty(
        name="Frame Rate",
        description="Number of frames between keyframes",
        default=1,
        min=1,
        max=100000,
    )

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text="WAD Blender", icon="BLENDER")

        box = layout.box()
        box.prop(self, "actions")
        box.prop(self, "scale")
        box.prop(self, "frame_rate")

    def execute(self, context):
        try:
            return export(context, self.filepath, self.actions, self.scale, self.frame_rate)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


def menu_func_export(self, context):
    self.layout.operator("wadblender.export_anim", text="TRLE Animation (.anim)")


def register():
    bpy.utils.register_class(ExportAnim)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_class(ExportAnim)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


if __name__ == "__main__":
    register()

    # test call
    bpy.ops.export_anim.data("INVOKE_DEFAULT")
