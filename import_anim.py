import math
import re
import xml.etree.ElementTree as ET

import bpy
from bpy_extras import anim_utils
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, EnumProperty, IntProperty
from bpy.types import Operator
from mathutils import Matrix


AXIS_MAT = Matrix(((-1.0, 0.0, 0.0),
                   (0.0, 0.0, -1.0),
                   (0.0, 1.0, 0.0)))
AXIS_MAT_T = AXIS_MAT.transposed()


def _yaw_pitch_roll_to_mat(yaw: float, pitch: float, roll: float) -> Matrix:
    hy = yaw * 0.5
    hp = pitch * 0.5
    hr = roll * 0.5

    sy, cy = math.sin(hy), math.cos(hy)
    sp, cp = math.sin(hp), math.cos(hp)
    sr, cr = math.sin(hr), math.cos(hr)

    x = cy * sp * cr + sy * cp * sr
    y = sy * cp * cr - cy * sp * sr
    z = cy * cp * sr - sy * sp * cr
    w = cy * cp * cr + sy * sp * sr

    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return Matrix((
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    ))


def _wad_to_blender_vec(vec):
    return (-vec[0], -vec[2], vec[1])


def _get_text(node, default="0"):
    if node is None or node.text is None:
        return default
    return node.text.strip()


def _read_float(node, default=0.0):
    try:
        return float(_get_text(node, str(default)))
    except ValueError:
        return default


def _read_int(node, default=0):
    try:
        return int(float(_get_text(node, str(default))))
    except ValueError:
        return default


def _detect_xml_encoding(data, declared):
    if data.startswith(b"\xff\xfe"):
        return "utf-16le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16be"
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    sample = data[:200]
    if b"\x00" in sample:
        even_nulls = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0)
        odd_nulls = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
        if odd_nulls > even_nulls:
            return "utf-16le"
        if even_nulls > odd_nulls:
            return "utf-16be"
        return "utf-16"

    if declared:
        if declared.startswith("utf-16"):
            return "utf-8"
        return declared
    return "utf-8"


def _read_xml_text(filepath):
    with open(filepath, "rb") as handle:
        data = handle.read()

    declared = None
    match = re.search(br'encoding=["\']([^"\']+)["\']', data[:200])
    if match:
        declared = match.group(1).decode("ascii", errors="ignore").lower()

    candidates = []
    detected = _detect_xml_encoding(data, declared)
    candidates.append(detected)
    if declared and declared not in candidates:
        candidates.append(declared)
    candidates.extend(["utf-8-sig", "utf-8", "latin1"])

    text = None
    for enc in candidates:
        try:
            text = data.decode(enc)
            break
        except UnicodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")

    idx = text.find("<")
    if idx > 0:
        text = text[idx:]
    return text


def _parse_anim_file(filepath):
    xml_text = _read_xml_text(filepath)
    root = ET.fromstring(xml_text)

    frame_rate = _read_int(root.find("FrameRate"), 1)
    name = _get_text(root.find("Name"), "Animation")

    keyframes = []
    keyframes_node = root.find("KeyFrames")
    if keyframes_node is not None:
        for wadkf in keyframes_node.findall("WadKeyFrame"):
            offset_node = wadkf.find("Offset")
            offset = (
                _read_float(offset_node.find("X")) if offset_node is not None else 0.0,
                _read_float(offset_node.find("Y")) if offset_node is not None else 0.0,
                _read_float(offset_node.find("Z")) if offset_node is not None else 0.0,
            )

            angles = []
            angles_node = wadkf.find("Angles")
            if angles_node is not None:
                for rot in angles_node.findall("WadKeyFrameRotation"):
                    rot_node = rot.find("Rotations")
                    if rot_node is None:
                        continue
                    ang = (
                        _read_float(rot_node.find("X")),
                        _read_float(rot_node.find("Y")),
                        _read_float(rot_node.find("Z")),
                    )
                    angles.append(ang)

            keyframes.append({"offset": offset, "angles": angles})

    return {
        "name": name,
        "frame_rate": max(1, frame_rate),
        "keyframes": keyframes,
    }


def _ensure_action_slot(rig, action):
    rig.animation_data.action = action
    if rig.animation_data.action_slot is None:
        if len(rig.animation_data.action_suitable_slots) > 0:
            rig.animation_data.action_slot = rig.animation_data.action_suitable_slots[0]
        else:
            slot = action.slots.new(id_type='OBJECT', name=rig.name)
            rig.animation_data.action_slot = slot
    return rig.animation_data.action_slot


def import_anim_to_rig(filepath, rig, scale):
    anim = _parse_anim_file(filepath)
    keyframes = anim["keyframes"]
    if not keyframes:
        return None

    if rig.animation_data is None:
        rig.animation_data_create()

    action = bpy.data.actions.new(anim["name"])
    slot = _ensure_action_slot(rig, action)
    channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
    fcurves = channelbag.fcurves

    bonenames = [bone.name for bone in rig.pose.bones]
    if not bonenames:
        return None

    root_bone = bonenames[0]
    frame_rate = anim["frame_rate"]
    frame_count = len(keyframes)

    # Root translation
    for axis in range(3):
        fc = fcurves.new(data_path=f'pose.bones["{root_bone}"].location', index=axis)
        fc.keyframe_points.add(frame_count)

    # Rotations
    for bone in bonenames:
        for axis in range(4):
            fc = fcurves.new(
                data_path=f'pose.bones["{bone}"].rotation_quaternion',
                index=axis
            )
            fc.keyframe_points.add(frame_count)

    for i, kf in enumerate(keyframes):
        frame = i * frame_rate
        offset = _wad_to_blender_vec(kf["offset"])
        offset = (offset[0] / scale, offset[1] / scale, offset[2] / scale)

        for axis in range(3):
            fc = fcurves.find(f'pose.bones["{root_bone}"].location', index=axis)
            fc.keyframe_points[i].co = (frame, offset[axis])

        angles = kf["angles"]
        for b_idx, bone in enumerate(bonenames):
            if b_idx < len(angles):
                ax, ay, az = angles[b_idx]
                # WAD stores degrees (X,Y,Z) with yaw(Y), pitch(X), roll(Z)
                pitch = math.radians(ax)
                yaw = math.radians(ay)
                roll = math.radians(az)
                src = _yaw_pitch_roll_to_mat(yaw, pitch, roll)
                dst = AXIS_MAT @ src @ AXIS_MAT_T
                quat = dst.to_quaternion()
            else:
                quat = Matrix.Identity(3).to_quaternion()

            for axis in range(4):
                fc = fcurves.find(f'pose.bones["{bone}"].rotation_quaternion', index=axis)
                fc.keyframe_points[i].co = (frame, quat[axis])

    action.use_fake_user = True
    return action


class ImportAnim(Operator, ImportHelper):
    bl_idname = "wadblender.import_anim"
    bl_label = "Import Wad Tool Animation"

    filename_ext = ".anim"

    filter_glob: StringProperty(
        default="*.anim",
        options={'HIDDEN'},
        maxlen=255,
    )

    scale: IntProperty(
        name="Scale",
        description="Dividing by 512, one TRLE click becomes 0.5 meters",
        default=512,
        min=1,
        max=100000
    )

    def get_armatures(self, context):
        items = []
        for obj in bpy.data.objects:
            if obj.type == "ARMATURE":
                items.append((obj.name, obj.name, obj.name))
        return items

    armature: EnumProperty(
        name="Armature", items=get_armatures,
        description="Target armature for the animation."
    )

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text='WAD Blender', icon="BLENDER")

        box = layout.box()
        box.prop(self, "armature")
        box.prop(self, "scale")

    def execute(self, context):
        if not self.armature:
            self.report({'ERROR'}, "No armature found.")
            return {'CANCELLED'}

        rig = bpy.data.objects.get(self.armature)
        if rig is None or rig.type != "ARMATURE":
            self.report({'ERROR'}, "Selected armature is invalid.")
            return {'CANCELLED'}

        action = import_anim_to_rig(self.filepath, rig, self.scale)
        if action is None:
            self.report({'ERROR'}, "Failed to import animation.")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Imported animation '{action.name}'")
        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator("wadblender.import_anim", text="TRLE Animation (.anim)")


def register():
    bpy.utils.register_class(ImportAnim)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_class(ImportAnim)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    register()
