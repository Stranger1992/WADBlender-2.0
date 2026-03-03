import json
import math
import re

import bpy
from bpy.props import BoolProperty, IntProperty, FloatProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel
from mathutils import Vector, Matrix, Quaternion


CONSTRAINTS_KEY = "wadblender_ik_constraints"
LARA_BONE_RENAME_KEY = "wadblender_lara_anim_bone_map"
IK_SETUP_KEY = "wadblender_ik_setup"

# IK chain definitions for Lara rig
# IK constraint goes on the end effector bone (foot/hand)
# Chain length of 3 includes: foot + shin + thigh (or hand + forearm + upper_arm)
LARA_IK_CHAINS = {
    # Legs: IK constraint on FOOT bone, chain_length=3 affects foot+shin+thigh
    # Target position is at the foot (end of chain)
    # Pole target at knee (forward, since knees bend forward)
    "leg_l": {
        "ik_bone_patterns": ["LEFT_FOOT", "Foot_L", "Mesh_15"],  # IK constraint goes here
        "chain_length": 3,  # Affects foot + shin + thigh
        "pole_direction": (0, -1, 0),  # In front of Lara (negative Y in Lara's coordinate space)
        "pole_distance": 0.2,  # Closer poles = more responsive control
        "pole_bone_patterns": ["LEFT_SHIN", "Shin_L", "Mesh_14"],  # For pole position calculation
        "pole_angle": -90,  # Degrees
        "display_name": "Left Leg",
    },
    "leg_r": {
        "ik_bone_patterns": ["RIGHT_FOOT", "Foot_R", "Mesh_18"],
        "chain_length": 3,  # Affects foot + shin + thigh
        "pole_direction": (0, -1, 0),  # In front of Lara (negative Y in Lara's coordinate space)
        "pole_distance": 0.2,  # Closer poles = more responsive control
        "pole_bone_patterns": ["RIGHT_SHIN", "Shin_R", "Mesh_17"],
        "pole_angle": -90,  # Degrees
        "display_name": "Right Leg",
    },
    # Arms: IK constraint on HAND bone, chain_length=3 affects hand+forearm+upper_arm
    # Target position is at the hand (end of chain)
    # Pole target at elbow (backward, since elbows bend backward)
    "arm_l": {
        "ik_bone_patterns": ["LEFT_HAND", "Hand_L", "Mesh_25"],
        "chain_length": 3,  # Affects hand + forearm + upper_arm
        "pole_direction": (0, -1, 0),  # Backward (elbows bend back, so pole is behind)
        "pole_distance": 0.15,  # Closer poles = more responsive control
        "pole_bone_patterns": ["LEFT_FOREARM", "LowerArm_L", "Mesh_24"],
        "display_name": "Left Arm",
    },
    "arm_r": {
        "ik_bone_patterns": ["RIGHT_HAND", "Hand_R", "Mesh_22"],
        "chain_length": 3,  # Affects hand + forearm + upper_arm
        "pole_direction": (0, -1, 0),
        "pole_distance": 0.15,  # Closer poles = more responsive control
        "pole_bone_patterns": ["RIGHT_FOREARM", "LowerArm_R", "Mesh_21"],
        "display_name": "Right Arm",
    },
}

LARA_ANIM_BONE_MAP = {
    "LARA_HIPS_BONE": "Hips",
    "LARA_LEFT_THIGH_BONE": "Thigh_L",
    "LARA_LEFT_SHIN_BONE": "Shin_L",
    "LARA_LEFT_FOOT_BONE": "Foot_L",
    "LARA_RIGHT_THIGH_BONE": "Thigh_R",
    "LARA_RIGHT_SHIN_BONE": "Shin_R",
    "LARA_RIGHT_FOOT_BONE": "Foot_R",
    "LARA_TORSO_BONE": "Torso",
    "LARA_RIGHT_UPPER_ARM_BONE": "UpperArm_R",
    "LARA_RIGHT_FOREARM_BONE": "LowerArm_R",
    "LARA_RIGHT_HAND_BONE": "Hand_R",
    "LARA_LEFT_UPPER_ARM_BONE": "UpperArm_L",
    "LARA_LEFT_FOREARM_BONE": "LowerArm_L",
    "LARA_LEFT_HAND_BONE": "Hand_L",
    "LARA_HEAD_BONE": "Head",
}

LARA_MESH_TO_ANIM_MAP = {
    "Mesh_12": "Hips",
    "Mesh_13": "Thigh_L",
    "Mesh_14": "Shin_L",
    "Mesh_15": "Foot_L",
    "Mesh_16": "Thigh_R",
    "Mesh_17": "Shin_R",
    "Mesh_18": "Foot_R",
    "Mesh_19": "Torso",
    "Mesh_20": "UpperArm_R",
    "Mesh_21": "LowerArm_R",
    "Mesh_22": "Hand_R",
    "Mesh_23": "UpperArm_L",
    "Mesh_24": "LowerArm_L",
    "Mesh_25": "Hand_L",
    "Mesh_26": "Head",
}


def _collect_ik_constraints(rig):
    entries = []
    for bone in rig.pose.bones:
        for constraint in bone.constraints:
            if constraint.type != "IK":
                continue
            entries.append({
                "bone": bone.name,
                "constraint": constraint.name,
                "mute": bool(constraint.mute),
                "influence": float(constraint.influence),
            })
    return entries


def _save_constraints_state(rig, entries):
    rig[CONSTRAINTS_KEY] = json.dumps(entries)


def _load_constraints_state(rig):
    raw = rig.get(CONSTRAINTS_KEY)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return []


def _apply_constraints_state(rig, entries):
    restored = 0
    for entry in entries:
        bone = rig.pose.bones.get(entry.get("bone", ""))
        if bone is None:
            continue
        constraint = bone.constraints.get(entry.get("constraint", ""))
        if constraint is None:
            continue
        constraint.mute = bool(entry.get("mute", False))
        constraint.influence = float(entry.get("influence", 1.0))
        restored += 1
    return restored


def _mute_constraints(rig, entries):
    muted = 0
    for entry in entries:
        bone = rig.pose.bones.get(entry.get("bone", ""))
        if bone is None:
            continue
        constraint = bone.constraints.get(entry.get("constraint", ""))
        if constraint is None:
            continue
        constraint.mute = True
        muted += 1
    return muted


def _get_frame_range(scene, rig, use_scene_range):
    if not use_scene_range and rig.animation_data and rig.animation_data.action:
        start, end = rig.animation_data.action.frame_range
        return int(math.floor(start)), int(math.ceil(end))
    return scene.frame_start, scene.frame_end


def _set_bone_rotation_mode(rig, mode):
    prev = {}
    for bone in rig.pose.bones:
        prev[bone.name] = bone.rotation_mode
        bone.rotation_mode = mode
    return prev


def _restore_bone_rotation_mode(rig, modes):
    for bone in rig.pose.bones:
        mode = modes.get(bone.name)
        if mode:
            bone.rotation_mode = mode


def _canonical_lara_bone(name):
    if name in LARA_MESH_TO_ANIM_MAP:
        return name
    match = re.match(r"^(.*?)(?:\.\d+)?_BONE$", name)
    if match:
        return f"{match.group(1)}_BONE"
    return name


def _build_lara_anim_mapping(rig):
    mapping = {}
    for bone in rig.data.edit_bones:
        key = _canonical_lara_bone(bone.name)
        if key in LARA_ANIM_BONE_MAP:
            mapping[bone.name] = LARA_ANIM_BONE_MAP[key]
        elif key in LARA_MESH_TO_ANIM_MAP:
            mapping[bone.name] = LARA_MESH_TO_ANIM_MAP[key]
    return mapping


def _rename_bones(rig, name_map):
    bones = rig.data.edit_bones
    temp_map = {}
    for old_name, new_name in name_map.items():
        if old_name not in bones or new_name == old_name:
            continue
        temp_name = f"__wadtmp__{old_name}"
        while temp_name in bones:
            temp_name = f"{temp_name}_x"
        bones[old_name].name = temp_name
        temp_map[temp_name] = new_name

    for temp_name, new_name in temp_map.items():
        if temp_name in bones:
            bones[temp_name].name = new_name


def _rename_vertex_groups(obj, name_map):
    temp_map = {}
    for vg in obj.vertex_groups:
        if vg.name not in name_map:
            continue
        new_name = name_map[vg.name]
        if new_name == vg.name:
            continue
        temp_name = f"__wadtmp__{vg.name}"
        while obj.vertex_groups.get(temp_name):
            temp_name = f"{temp_name}_x"
        vg.name = temp_name
        temp_map[temp_name] = new_name

    for temp_name, new_name in temp_map.items():
        vg = obj.vertex_groups.get(temp_name)
        if vg:
            vg.name = new_name


def _iter_meshes_for_rig(rig):
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if obj.parent == rig:
            yield obj
            continue
        for mod in obj.modifiers:
            if mod.type == "ARMATURE" and mod.object == rig:
                yield obj
                break


class WadBlenderBakeIKToFK(Operator):
    bl_idname = "wadblender.bake_ik_to_fk"
    bl_label = "Bake IK to FK"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig = context.active_object
        if rig is None or rig.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature to bake.")
            return {"CANCELLED"}

        scene = context.scene
        step = max(1, int(scene.wadblender_ik_bake_step))
        use_scene_range = bool(scene.wadblender_ik_use_scene_range)
        only_selected = bool(scene.wadblender_ik_only_selected)
        mute_constraints = bool(scene.wadblender_ik_mute_constraints)
        force_quaternion = bool(scene.wadblender_ik_force_quaternion)

        if only_selected:
            has_selection = any(bone.bone.select for bone in rig.pose.bones)
            if not has_selection:
                self.report({"ERROR"}, "No bones selected for baking.")
                return {"CANCELLED"}

        frame_start, frame_end = _get_frame_range(scene, rig, use_scene_range)
        if frame_end < frame_start:
            frame_start, frame_end = frame_end, frame_start

        if rig.animation_data is None:
            rig.animation_data_create()
        if rig.animation_data.action is None:
            rig.animation_data.action = bpy.data.actions.new("IK_Bake")

        prev_mode = rig.mode
        prev_active = context.view_layer.objects.active
        prev_selected = [obj for obj in context.selected_objects]

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode="POSE")

        prev_rot_modes = {}
        if force_quaternion:
            prev_rot_modes = _set_bone_rotation_mode(rig, "QUATERNION")

        try:
            bpy.ops.nla.bake(
                frame_start=frame_start,
                frame_end=frame_end,
                step=step,
                only_selected=only_selected,
                visual_keying=True,
                clear_constraints=False,
                clear_parents=False,
                use_current_action=True,
                bake_types={"POSE"},
            )
        finally:
            if force_quaternion:
                _restore_bone_rotation_mode(rig, prev_rot_modes)

        if mute_constraints:
            entries = _collect_ik_constraints(rig)
            if entries:
                _save_constraints_state(rig, entries)
                _mute_constraints(rig, entries)

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        for obj in prev_selected:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if prev_active and prev_active.name in bpy.data.objects:
            context.view_layer.objects.active = prev_active
            if prev_active == rig and prev_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=prev_mode)

        return {"FINISHED"}


class WadBlenderRestoreIKConstraints(Operator):
    bl_idname = "wadblender.restore_ik_constraints"
    bl_label = "Restore IK Constraints"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig = context.active_object
        if rig is None or rig.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature to restore constraints.")
            return {"CANCELLED"}

        entries = _load_constraints_state(rig)
        if not entries:
            self.report({"WARNING"}, "No stored IK constraints to restore.")
            return {"CANCELLED"}

        restored = _apply_constraints_state(rig, entries)
        if restored == 0:
            self.report({"WARNING"}, "No matching constraints found to restore.")
            return {"CANCELLED"}

        return {"FINISHED"}


class WadBlenderToggleLaraAnimNames(Operator):
    bl_idname = "wadblender.toggle_lara_anim_names"
    bl_label = "Toggle Lara Anim Names"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig = context.active_object
        if rig is None or rig.type != "ARMATURE":
            self.report({"ERROR"}, "Select an armature to rename.")
            return {"CANCELLED"}

        prev_mode = rig.mode
        bpy.ops.object.mode_set(mode="EDIT")

        if LARA_BONE_RENAME_KEY in rig:
            data = rig.get(LARA_BONE_RENAME_KEY)
            try:
                stored = json.loads(data)
            except (TypeError, ValueError):
                stored = {}
            bone_map = stored.get("bone_map", {})
            if not bone_map:
                self.report({"WARNING"}, "No stored Lara rename data found.")
                bpy.ops.object.mode_set(mode=prev_mode)
                return {"CANCELLED"}

            inverse = {v: k for k, v in bone_map.items()}
            _rename_bones(rig, inverse)
            bpy.ops.object.mode_set(mode="OBJECT")
            for obj in _iter_meshes_for_rig(rig):
                _rename_vertex_groups(obj, inverse)
            del rig[LARA_BONE_RENAME_KEY]
        else:
            bone_map = _build_lara_anim_mapping(rig)
            if not bone_map:
                self.report({"WARNING"}, "No Lara bones found to rename.")
                bpy.ops.object.mode_set(mode=prev_mode)
                return {"CANCELLED"}

            targets = list(bone_map.values())
            if len(set(targets)) != len(targets):
                self.report({"ERROR"}, "Rename map has duplicate target names.")
                bpy.ops.object.mode_set(mode=prev_mode)
                return {"CANCELLED"}

            _rename_bones(rig, bone_map)
            bpy.ops.object.mode_set(mode="OBJECT")
            for obj in _iter_meshes_for_rig(rig):
                _rename_vertex_groups(obj, bone_map)
            rig[LARA_BONE_RENAME_KEY] = json.dumps({"bone_map": bone_map})

        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)

        return {"FINISHED"}


# ============================================================================
# IK Setup Functions
# ============================================================================

def _find_bone_by_patterns(rig, patterns):
    """Find a bone matching any of the given patterns."""
    for bone in rig.data.bones:
        bone_name_upper = bone.name.upper()
        for pattern in patterns:
            pattern_upper = pattern.upper()
            # Check exact match or pattern contained in bone name
            if pattern_upper in bone_name_upper or bone.name == pattern:
                return bone.name
    return None


def _find_pose_bone_by_patterns(rig, patterns):
    """Find a pose bone matching any of the given patterns."""
    bone_name = _find_bone_by_patterns(rig, patterns)
    if bone_name:
        return rig.pose.bones.get(bone_name)
    return None


def _has_ik_setup(rig):
    """Check if rig already has IK setup."""
    return IK_SETUP_KEY in rig


def _get_ik_setup_data(rig):
    """Get stored IK setup data."""
    raw = rig.get(IK_SETUP_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _save_ik_setup_data(rig, data):
    """Save IK setup data to rig."""
    rig[IK_SETUP_KEY] = json.dumps(data)


def _calculate_pole_position(rig, ik_bone_name, chain_length, pole_direction, pole_distance):
    """Calculate the pole target position for an IK chain."""
    pose_bone = rig.pose.bones.get(ik_bone_name)
    if not pose_bone:
        return None

    # Get the chain bones
    chain_bones = [pose_bone]
    current = pose_bone
    for _ in range(chain_length - 1):
        if current.parent:
            chain_bones.insert(0, current.parent)
            current = current.parent

    if len(chain_bones) < 2:
        return None

    # Calculate midpoint of the chain
    start_pos = rig.matrix_world @ chain_bones[0].head
    mid_pos = rig.matrix_world @ chain_bones[0].tail  # Joint position
    end_pos = rig.matrix_world @ chain_bones[-1].tail

    # Pole should be offset from the middle joint
    pole_dir = Vector(pole_direction).normalized()

    # Calculate the plane normal from start to end
    chain_vec = (end_pos - start_pos).normalized()

    # Project pole direction onto plane perpendicular to chain
    pole_offset = pole_dir - pole_dir.dot(chain_vec) * chain_vec
    if pole_offset.length < 0.001:
        # Fallback if pole_dir is parallel to chain
        pole_offset = Vector((0, -1, 0))

    pole_offset.normalize()

    # Scale by distance
    chain_length_val = (end_pos - start_pos).length
    pole_pos = mid_pos + pole_offset * chain_length_val * pole_distance

    return pole_pos


def _calculate_pole_angle(rig, ik_bone_name, target_pos, pole_pos):
    """Calculate the pole angle for correct IK orientation."""
    pose_bone = rig.pose.bones.get(ik_bone_name)
    if not pose_bone or not pose_bone.parent:
        return 0.0

    # Get world positions
    parent_head = rig.matrix_world @ pose_bone.parent.head
    bone_head = rig.matrix_world @ pose_bone.head
    bone_tail = rig.matrix_world @ pose_bone.tail

    # Vector from parent to bone
    limb_vec = (bone_head - parent_head).normalized()

    # Vector from bone to target
    to_target = (target_pos - bone_head).normalized()

    # Vector from bone to pole
    to_pole = (pole_pos - bone_head).normalized()

    # Calculate the angle
    # This is a simplified calculation - may need adjustment
    cross = limb_vec.cross(to_target)
    if cross.length > 0.001:
        cross.normalize()
        dot = to_pole.dot(cross)
        angle = math.acos(max(-1, min(1, dot)))
        # Determine sign
        if to_pole.dot(limb_vec.cross(cross)) < 0:
            angle = -angle
        return angle

    return 0.0


def _create_ik_bones(rig, chain_name, chain_config):
    """Create IK target and pole bones for a chain.

    IK target goes at the END of the chain (foot/hand position).
    Pole target goes at the MIDDLE joint (knee/elbow).
    IK constraint is placed on the end bone (foot/hand) with chain_length=2.
    """
    ik_bone_name = _find_bone_by_patterns(rig, chain_config["ik_bone_patterns"])

    if not ik_bone_name:
        return None, None, None

    ik_edit_bone = rig.data.edit_bones.get(ik_bone_name)
    if not ik_edit_bone:
        return None, None, None

    # IK target position is at the TAIL of the IK bone (end of foot/hand)
    # This is where we want the limb to reach
    target_pos = ik_edit_bone.tail.copy()

    # Create IK target bone at the foot/hand position
    ik_target_name = f"IK_{chain_name}"
    ik_target = rig.data.edit_bones.new(ik_target_name)
    ik_target.head = target_pos
    # Point the target bone outward a bit for visibility
    ik_target.tail = target_pos + Vector((0, 0.08, 0))
    ik_target.use_deform = False

    # Create pole target bone at the middle joint (knee/elbow)
    pole_name = f"Pole_{chain_name}"
    pole_target = rig.data.edit_bones.new(pole_name)

    # Find the middle joint bone for pole positioning
    pole_bone_patterns = chain_config.get("pole_bone_patterns", [])
    if pole_bone_patterns:
        pole_ref_name = _find_bone_by_patterns(rig, pole_bone_patterns)
        pole_ref_bone = rig.data.edit_bones.get(pole_ref_name) if pole_ref_name else None
    else:
        # Fallback: use parent of IK bone
        pole_ref_bone = ik_edit_bone.parent

    if pole_ref_bone:
        # Pole position: at the joint (head of the middle bone), offset in pole direction
        joint_pos = pole_ref_bone.head.copy()

        # Get the chain root (thigh/upper arm) for calculating chain direction
        chain_root = pole_ref_bone.parent if pole_ref_bone.parent else pole_ref_bone

        # Calculate pole offset
        pole_dir = Vector(chain_config["pole_direction"]).normalized()

        # Calculate chain vector from root to end
        chain_vec = (target_pos - chain_root.head).normalized()

        # Project pole direction to be more perpendicular to chain
        pole_offset = pole_dir - pole_dir.dot(chain_vec) * chain_vec * 0.5
        if pole_offset.length < 0.001:
            pole_offset = pole_dir
        pole_offset.normalize()

        # Distance based on limb length
        chain_len = (target_pos - chain_root.head).length
        pole_pos = joint_pos + pole_offset * chain_len * chain_config["pole_distance"]
    else:
        # Fallback
        pole_pos = ik_edit_bone.head + Vector(chain_config["pole_direction"]) * 0.3

    pole_target.head = pole_pos
    pole_target.tail = pole_pos + Vector((0, 0.05, 0))
    pole_target.use_deform = False

    return ik_bone_name, ik_target_name, pole_name


def _setup_ik_constraint(rig, ik_bone_name, target_bone_name, pole_bone_name, chain_length, pole_angle_deg=0.0, use_rotation=False, rotation_weight=0.01):
    """Add IK constraint to the bone."""
    pose_bone = rig.pose.bones.get(ik_bone_name)
    if not pose_bone:
        return None

    # Remove existing IK constraint if any
    for constraint in pose_bone.constraints:
        if constraint.type == "IK" and constraint.name.startswith("WadBlender_IK"):
            pose_bone.constraints.remove(constraint)

    # Add new IK constraint
    ik_constraint = pose_bone.constraints.new("IK")
    ik_constraint.name = "WadBlender_IK"
    ik_constraint.target = rig
    ik_constraint.subtarget = target_bone_name
    ik_constraint.pole_target = rig
    ik_constraint.pole_subtarget = pole_bone_name
    ik_constraint.chain_count = chain_length
    ik_constraint.use_stretch = False

    # Set pole angle (convert degrees to radians)
    ik_constraint.pole_angle = math.radians(pole_angle_deg)

    # Rotation settings - minimal rotation influence keeps feet/hands grounded
    ik_constraint.use_rotation = use_rotation
    if use_rotation:
        ik_constraint.orient_weight = rotation_weight

    return ik_constraint


def _add_ikfk_property(rig, chain_name, display_name):
    """Add IK/FK switch custom property to the rig."""
    prop_name = f"IK_FK_{chain_name}"

    # Add custom property if it doesn't exist
    if prop_name not in rig:
        rig[prop_name] = 1.0  # Default to IK enabled

    # Set up property UI
    id_props = rig.id_properties_ui(prop_name)
    id_props.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                    description=f"IK/FK switch for {display_name} (1=IK, 0=FK)")

    return prop_name


def _add_ikfk_driver(rig, ik_bone_name, prop_name):
    """Add driver to IK constraint influence based on IK/FK property."""
    pose_bone = rig.pose.bones.get(ik_bone_name)
    if not pose_bone:
        return False

    ik_constraint = None
    for constraint in pose_bone.constraints:
        if constraint.type == "IK" and constraint.name.startswith("WadBlender_IK"):
            ik_constraint = constraint
            break

    if not ik_constraint:
        return False

    # Add driver
    try:
        driver = ik_constraint.driver_add("influence").driver
        driver.type = "AVERAGE"

        var = driver.variables.new()
        var.name = "ikfk"
        var.type = "SINGLE_PROP"
        var.targets[0].id = rig
        var.targets[0].data_path = f'["{prop_name}"]'

        return True
    except Exception:
        return False


def _create_cube_widget():
    """Create a cube widget mesh for IK targets."""
    mesh = bpy.data.meshes.new("WGT_ik_cube")
    size = 0.5
    verts = [
        (-size, -size, -size), (size, -size, -size),
        (size, size, -size), (-size, size, -size),
        (-size, -size, size), (size, -size, size),
        (size, size, size), (-size, size, size),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    return mesh


def _create_sphere_widget():
    """Create a denser sphere widget mesh for pole targets."""
    mesh = bpy.data.meshes.new("WGT_pole_sphere")

    # Create a proper UV sphere-like wireframe with 3 rings
    import math
    verts = []
    edges = []

    # Parameters for denser sphere
    size = 0.25
    h_segments = 8  # horizontal segments
    v_segments = 4  # vertical segments (half sphere rings)

    # Add top and bottom poles
    verts.append((0, 0, size))   # top pole, index 0
    verts.append((0, 0, -size))  # bottom pole, index 1

    # Add ring vertices
    for v in range(1, v_segments):
        phi = math.pi * v / v_segments  # angle from top
        z = size * math.cos(phi)
        ring_radius = size * math.sin(phi)

        for h in range(h_segments):
            theta = 2 * math.pi * h / h_segments
            x = ring_radius * math.cos(theta)
            y = ring_radius * math.sin(theta)
            verts.append((x, y, z))

    # Connect top pole to first ring
    first_ring_start = 2
    for h in range(h_segments):
        edges.append((0, first_ring_start + h))

    # Connect rings horizontally and vertically
    for v in range(1, v_segments):
        ring_start = 2 + (v - 1) * h_segments
        for h in range(h_segments):
            # Horizontal edge (around ring)
            next_h = (h + 1) % h_segments
            edges.append((ring_start + h, ring_start + next_h))

            # Vertical edge (between rings)
            if v < v_segments - 1:
                next_ring_start = ring_start + h_segments
                edges.append((ring_start + h, next_ring_start + h))

    # Connect bottom pole to last ring
    last_ring_start = 2 + (v_segments - 2) * h_segments
    for h in range(h_segments):
        edges.append((1, last_ring_start + h))

    mesh.from_pydata(verts, edges, [])
    mesh.update()
    return mesh


def _get_or_create_widget(shape_type):
    """Get existing widget or create new one."""
    widget_name = f"WGT_{shape_type}"
    widget = bpy.data.objects.get(widget_name)

    if widget:
        return widget

    # Create mesh based on type
    if shape_type == "ik_cube":
        mesh = _create_cube_widget()
    elif shape_type == "pole_sphere":
        mesh = _create_sphere_widget()
    else:
        return None

    widget = bpy.data.objects.new(widget_name, mesh)

    # Set wire display properties
    widget.display_type = 'WIRE'
    widget.show_in_front = True

    # Add to a hidden collection
    widget_col = bpy.data.collections.get("WadBlender_Widgets")
    if not widget_col:
        widget_col = bpy.data.collections.new("WadBlender_Widgets")
        bpy.context.scene.collection.children.link(widget_col)
        widget_col.hide_viewport = True
        widget_col.hide_render = True

    widget_col.objects.link(widget)
    return widget


def _set_bone_custom_shape(rig, bone_name, shape_type="cube", scale=1.0, translation=(0, 0, 0)):
    """Set custom display shape for control bones.

    Args:
        rig: The armature object
        bone_name: Name of the pose bone
        shape_type: "ik_cube" for IK targets, "pole_sphere" for poles
        scale: Scale multiplier for the widget
        translation: (x, y, z) offset for the widget
    """
    pose_bone = rig.pose.bones.get(bone_name)
    if not pose_bone:
        return

    widget = _get_or_create_widget(shape_type)
    if not widget:
        return

    pose_bone.custom_shape = widget
    pose_bone.use_custom_shape_bone_size = True  # Scale relative to bone length

    # Set scale (uniform for simplicity)
    pose_bone.custom_shape_scale_xyz = (scale, scale, scale)

    # Set translation offset
    pose_bone.custom_shape_translation = Vector(translation)

    # Set wire width (Blender 4.0+)
    try:
        pose_bone.custom_shape_wire_width = 3.0
    except AttributeError:
        pass  # Older Blender versions don't have this


# ============================================================================
# Space Switching Functions
# ============================================================================

# Space types for IK targets and poles
SPACE_WORLD = 'WORLD'
SPACE_ROOT = 'ROOT'
SPACE_HIPS = 'HIPS'
SPACE_LOCAL = 'LOCAL'  # For poles: relative to IK target

SPACE_ITEMS = [
    (SPACE_WORLD, "World", "World space - stays fixed in scene"),
    (SPACE_ROOT, "Root", "Root space - follows armature object"),
    (SPACE_HIPS, "Hips", "Hips space - follows hips bone"),
]

POLE_SPACE_ITEMS = [
    (SPACE_WORLD, "World", "World space - stays fixed in scene"),
    (SPACE_ROOT, "Root", "Root space - follows armature object"),
    (SPACE_LOCAL, "IK Target", "Local space - follows IK target"),
]


def _find_hips_bone(rig):
    """Find the hips/root bone in the rig."""
    hips_patterns = ["HIPS", "Hips", "ROOT", "Root", "Mesh_12", "pelvis", "Pelvis"]
    return _find_bone_by_patterns(rig, hips_patterns)


def _get_bone_world_matrix(rig, bone_name):
    """Get the world-space matrix of a pose bone."""
    pose_bone = rig.pose.bones.get(bone_name)
    if pose_bone:
        return rig.matrix_world @ pose_bone.matrix
    return rig.matrix_world


def _set_bone_world_location(rig, bone_name, world_pos):
    """Set a bone's location to match a world position."""
    pose_bone = rig.pose.bones.get(bone_name)
    if not pose_bone:
        return False

    # Convert world position to bone's local space
    if pose_bone.parent:
        parent_matrix = rig.matrix_world @ pose_bone.parent.matrix
        local_pos = parent_matrix.inverted() @ world_pos
    else:
        local_pos = rig.matrix_world.inverted() @ world_pos

    # Account for bone's rest position
    rest_pos = pose_bone.bone.head_local
    if pose_bone.parent:
        parent_rest = pose_bone.parent.bone.matrix_local
        rest_pos = parent_rest.inverted() @ Vector(rest_pos)

    pose_bone.location = local_pos - Vector(rest_pos)
    return True


def _setup_space_constraint(rig, bone_name, space, hips_bone_name=None):
    """Setup Copy Location constraint for space switching."""
    pose_bone = rig.pose.bones.get(bone_name)
    if not pose_bone:
        return None

    # Remove existing space constraint
    for c in list(pose_bone.constraints):
        if c.name.startswith("WB_Space_"):
            pose_bone.constraints.remove(c)

    if space == SPACE_WORLD:
        # No constraint needed - bone is free in world space
        return None

    # Create child-of constraint for parenting behavior
    constraint = pose_bone.constraints.new('CHILD_OF')
    constraint.name = f"WB_Space_{space}"
    constraint.target = rig

    if space == SPACE_ROOT:
        # Parent to armature root (no subtarget = object space)
        constraint.subtarget = ""
        constraint.use_location_x = True
        constraint.use_location_y = True
        constraint.use_location_z = True
        constraint.use_rotation_x = False
        constraint.use_rotation_y = False
        constraint.use_rotation_z = False
        constraint.use_scale_x = False
        constraint.use_scale_y = False
        constraint.use_scale_z = False
    elif space == SPACE_HIPS and hips_bone_name:
        constraint.subtarget = hips_bone_name
        constraint.use_location_x = True
        constraint.use_location_y = True
        constraint.use_location_z = True
        constraint.use_rotation_x = False
        constraint.use_rotation_y = False
        constraint.use_rotation_z = False
        constraint.use_scale_x = False
        constraint.use_scale_y = False
        constraint.use_scale_z = False

    # Set inverse to maintain current position
    constraint.set_inverse_pending = True

    return constraint


def _setup_pole_space_constraint(rig, pole_bone_name, space, ik_target_name=None):
    """Setup constraint for pole space switching."""
    pose_bone = rig.pose.bones.get(pole_bone_name)
    if not pose_bone:
        return None

    # Remove existing space constraint
    for c in list(pose_bone.constraints):
        if c.name.startswith("WB_PoleSpace_"):
            pose_bone.constraints.remove(c)

    if space == SPACE_WORLD:
        return None

    constraint = pose_bone.constraints.new('CHILD_OF')
    constraint.name = f"WB_PoleSpace_{space}"
    constraint.target = rig

    if space == SPACE_ROOT:
        constraint.subtarget = ""
    elif space == SPACE_LOCAL and ik_target_name:
        constraint.subtarget = ik_target_name

    constraint.use_location_x = True
    constraint.use_location_y = True
    constraint.use_location_z = True
    constraint.use_rotation_x = False
    constraint.use_rotation_y = False
    constraint.use_rotation_z = False
    constraint.use_scale_x = False
    constraint.use_scale_y = False
    constraint.use_scale_z = False

    constraint.set_inverse_pending = True
    return constraint


# ============================================================================
# IK/FK Snapping Functions
# ============================================================================

def _get_fk_chain_bones(rig, ik_bone_name, chain_length):
    """Get the FK bone chain from end to root."""
    chain = []
    pose_bone = rig.pose.bones.get(ik_bone_name)
    if not pose_bone:
        return chain

    current = pose_bone
    for _ in range(chain_length):
        chain.append(current)
        if current.parent:
            current = current.parent
        else:
            break

    return chain


def _snap_ik_to_fk(rig, chain_name, chain_data):
    """Snap IK controls to match current FK pose."""
    ik_bone_name = chain_data.get("ik_bone")
    ik_target_name = chain_data.get("ik_target")
    pole_target_name = chain_data.get("pole_target")
    chain_length = chain_data.get("chain_length", 3)

    if not all([ik_bone_name, ik_target_name]):
        return False

    # Get the FK chain
    fk_chain = _get_fk_chain_bones(rig, ik_bone_name, chain_length)
    if not fk_chain:
        return False

    # Get world position of the end effector (foot/hand)
    end_bone = fk_chain[0]  # First in chain is the end bone
    end_world_pos = rig.matrix_world @ end_bone.tail

    # Set IK target to match end effector position
    ik_target = rig.pose.bones.get(ik_target_name)
    if ik_target:
        # Convert to IK target's local space
        if ik_target.parent:
            parent_mat = rig.matrix_world @ ik_target.parent.matrix
            local_pos = parent_mat.inverted() @ end_world_pos
        else:
            local_pos = rig.matrix_world.inverted() @ end_world_pos

        ik_target.location = local_pos - Vector(ik_target.bone.head_local)

    # Set pole target to match current knee/elbow direction
    if pole_target_name and len(fk_chain) >= 2:
        pole_target = rig.pose.bones.get(pole_target_name)
        mid_bone = fk_chain[1]  # Middle bone (shin/forearm)

        if pole_target and mid_bone:
            # Get the current bend direction from the middle bone
            mid_world_pos = rig.matrix_world @ mid_bone.head

            # Calculate pole position: offset from middle joint in bend direction
            if len(fk_chain) >= 3:
                root_bone = fk_chain[2]
                root_pos = rig.matrix_world @ root_bone.head
                end_pos = rig.matrix_world @ fk_chain[0].tail

                # Calculate chain length for proportional pole distance
                chain_len = (end_pos - root_pos).length
                # Pole distance is 20% of chain length (matches setup values)
                pole_dist = chain_len * 0.2

                # Vector from root to end (ideal straight line)
                chain_vec = (end_pos - root_pos).normalized()

                # Vector from root to middle joint (actual position)
                to_mid = mid_world_pos - root_pos

                # Pole direction is perpendicular component
                pole_dir = to_mid - to_mid.dot(chain_vec) * chain_vec
                if pole_dir.length > 0.001:
                    pole_dir.normalize()
                    pole_world_pos = mid_world_pos + pole_dir * pole_dist
                else:
                    # Fallback: use a default direction
                    pole_world_pos = mid_world_pos + Vector((0, -pole_dist, 0))
            else:
                pole_world_pos = mid_world_pos + Vector((0, -0.1, 0))

            # Set pole target position
            if pole_target.parent:
                parent_mat = rig.matrix_world @ pole_target.parent.matrix
                local_pos = parent_mat.inverted() @ pole_world_pos
            else:
                local_pos = rig.matrix_world.inverted() @ pole_world_pos

            pole_target.location = local_pos - Vector(pole_target.bone.head_local)

    return True


def _snap_fk_to_ik(rig, chain_name, chain_data):
    """Snap FK bones to match current IK pose (visual pose)."""
    ik_bone_name = chain_data.get("ik_bone")
    chain_length = chain_data.get("chain_length", 3)

    if not ik_bone_name:
        return False

    # Get the FK chain
    fk_chain = _get_fk_chain_bones(rig, ik_bone_name, chain_length)
    if not fk_chain:
        return False

    # Store visual transforms and apply to FK
    for pose_bone in fk_chain:
        # Get the visual (evaluated) matrix
        visual_matrix = pose_bone.matrix.copy()

        # Convert to local space rotation
        if pose_bone.parent:
            parent_matrix = pose_bone.parent.matrix
            local_matrix = parent_matrix.inverted() @ visual_matrix
        else:
            local_matrix = rig.matrix_world.inverted() @ (rig.matrix_world @ visual_matrix)

        # Extract rotation based on bone's rotation mode
        if pose_bone.rotation_mode == 'QUATERNION':
            pose_bone.rotation_quaternion = local_matrix.to_quaternion()
        elif pose_bone.rotation_mode == 'AXIS_ANGLE':
            axis, angle = local_matrix.to_quaternion().to_axis_angle()
            pose_bone.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
        else:
            pose_bone.rotation_euler = local_matrix.to_euler(pose_bone.rotation_mode)

    return True


class WadBlenderSnapIKToFK(Operator):
    """Snap IK controls to match FK pose"""
    bl_idname = "wadblender.snap_ik_to_fk"
    bl_label = "Snap IK → FK"
    bl_description = "Move IK controls to match current FK bone positions"
    bl_options = {"REGISTER", "UNDO"}

    chain: StringProperty(name="Chain", default="all")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)

        if not setup_data:
            self.report({"WARNING"}, "No IK setup found.")
            return {"CANCELLED"}

        chains = setup_data.get("chains", {})
        snapped = []

        for chain_name, chain_data in chains.items():
            if self.chain != "all" and self.chain != chain_name:
                continue
            if _snap_ik_to_fk(rig, chain_name, chain_data):
                snapped.append(chain_data.get("display_name", chain_name))

        if snapped:
            self.report({"INFO"}, f"Snapped IK to FK: {', '.join(snapped)}")
        return {"FINISHED"}


class WadBlenderSnapFKToIK(Operator):
    """Snap FK bones to match IK pose"""
    bl_idname = "wadblender.snap_fk_to_ik"
    bl_label = "Snap FK → IK"
    bl_description = "Set FK bone rotations to match current IK visual pose"
    bl_options = {"REGISTER", "UNDO"}

    chain: StringProperty(name="Chain", default="all")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)

        if not setup_data:
            self.report({"WARNING"}, "No IK setup found.")
            return {"CANCELLED"}

        chains = setup_data.get("chains", {})
        snapped = []

        for chain_name, chain_data in chains.items():
            if self.chain != "all" and self.chain != chain_name:
                continue
            if _snap_fk_to_ik(rig, chain_name, chain_data):
                snapped.append(chain_data.get("display_name", chain_name))

        if snapped:
            self.report({"INFO"}, f"Snapped FK to IK: {', '.join(snapped)}")
        return {"FINISHED"}


class WadBlenderSetIKSpace(Operator):
    """Set IK target space"""
    bl_idname = "wadblender.set_ik_space"
    bl_label = "Set IK Space"
    bl_description = "Change the parent space of IK target"
    bl_options = {"REGISTER", "UNDO"}

    chain: StringProperty(name="Chain")
    space: EnumProperty(
        name="Space",
        items=SPACE_ITEMS,
        default=SPACE_WORLD,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)
        chains = setup_data.get("chains", {})

        if self.chain not in chains:
            self.report({"WARNING"}, f"Chain '{self.chain}' not found.")
            return {"CANCELLED"}

        chain_data = chains[self.chain]
        ik_target_name = chain_data.get("ik_target")

        if not ik_target_name:
            return {"CANCELLED"}

        # Store current world position
        ik_target = rig.pose.bones.get(ik_target_name)
        if ik_target:
            world_pos = rig.matrix_world @ ik_target.head

        # Find hips bone for hips space
        hips_bone = _find_hips_bone(rig)

        # Setup the constraint
        _setup_space_constraint(rig, ik_target_name, self.space, hips_bone)

        # Update stored space in setup data
        chain_data["ik_space"] = self.space
        _save_ik_setup_data(rig, setup_data)

        # Force update
        context.view_layer.update()

        self.report({"INFO"}, f"Set {chain_data.get('display_name', self.chain)} IK to {self.space} space")
        return {"FINISHED"}


class WadBlenderSetPoleSpace(Operator):
    """Set pole target space"""
    bl_idname = "wadblender.set_pole_space"
    bl_label = "Set Pole Space"
    bl_description = "Change the parent space of pole target"
    bl_options = {"REGISTER", "UNDO"}

    chain: StringProperty(name="Chain")
    space: EnumProperty(
        name="Space",
        items=POLE_SPACE_ITEMS,
        default=SPACE_WORLD,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)
        chains = setup_data.get("chains", {})

        if self.chain not in chains:
            self.report({"WARNING"}, f"Chain '{self.chain}' not found.")
            return {"CANCELLED"}

        chain_data = chains[self.chain]
        pole_target_name = chain_data.get("pole_target")
        ik_target_name = chain_data.get("ik_target")

        if not pole_target_name:
            return {"CANCELLED"}

        # Setup the constraint
        _setup_pole_space_constraint(rig, pole_target_name, self.space, ik_target_name)

        # Update stored space in setup data
        chain_data["pole_space"] = self.space
        _save_ik_setup_data(rig, setup_data)

        # Force update
        context.view_layer.update()

        self.report({"INFO"}, f"Set {chain_data.get('display_name', self.chain)} pole to {self.space} space")
        return {"FINISHED"}


class WadBlenderAdjustPoleAngle(Operator):
    """Adjust pole angle for IK chain"""
    bl_idname = "wadblender.adjust_pole_angle"
    bl_label = "Adjust Pole Angle"
    bl_description = "Fine-tune the pole angle to fix knee/elbow bend direction"
    bl_options = {"REGISTER", "UNDO"}

    chain: StringProperty(name="Chain")
    angle_offset: FloatProperty(
        name="Angle Offset",
        description="Offset in degrees to add to pole angle",
        default=0.0,
        min=-180.0,
        max=180.0,
        step=500,  # 5 degree steps
        subtype='ANGLE',
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)
        chains = setup_data.get("chains", {})

        if self.chain not in chains:
            self.report({"WARNING"}, f"Chain '{self.chain}' not found.")
            return {"CANCELLED"}

        chain_data = chains[self.chain]
        ik_bone_name = chain_data.get("ik_bone")

        if not ik_bone_name:
            return {"CANCELLED"}

        # Find and update the IK constraint
        pose_bone = rig.pose.bones.get(ik_bone_name)
        if pose_bone:
            for constraint in pose_bone.constraints:
                if constraint.type == "IK" and constraint.name.startswith("WadBlender_IK"):
                    # Apply angle offset (convert from degrees in UI to radians)
                    constraint.pole_angle += self.angle_offset
                    break

        # Store in setup data
        current_offset = chain_data.get("pole_angle_offset", 0.0)
        chain_data["pole_angle_offset"] = current_offset + self.angle_offset
        _save_ik_setup_data(rig, setup_data)

        context.view_layer.update()

        offset_deg = math.degrees(chain_data["pole_angle_offset"])
        self.report({"INFO"}, f"Pole angle offset: {offset_deg:.1f}°")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "angle_offset", text="Adjust by")


class WadBlenderSetupIK(Operator):
    bl_idname = "wadblender.setup_ik"
    bl_label = "Setup IK Controls"
    bl_description = "Create IK handles with pole targets for Lara's arms and legs"
    bl_options = {"REGISTER", "UNDO"}

    setup_legs: BoolProperty(
        name="Legs",
        description="Setup IK for legs",
        default=True,
    )

    setup_arms: BoolProperty(
        name="Arms",
        description="Setup IK for arms",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE"

    def execute(self, context):
        rig = context.active_object

        if _has_ik_setup(rig):
            self.report({"WARNING"}, "IK setup already exists. Remove it first to recreate.")
            return {"CANCELLED"}

        prev_mode = rig.mode
        setup_data = {"chains": {}}
        created_chains = []

        # Enter edit mode to create bones
        bpy.ops.object.mode_set(mode="EDIT")

        for chain_name, config in LARA_IK_CHAINS.items():
            # Filter by user selection
            if "leg" in chain_name and not self.setup_legs:
                continue
            if "arm" in chain_name and not self.setup_arms:
                continue

            result = _create_ik_bones(rig, chain_name, config)
            if result[0]:
                ik_bone_name, ik_target_name, pole_name = result
                setup_data["chains"][chain_name] = {
                    "ik_bone": ik_bone_name,
                    "ik_target": ik_target_name,
                    "pole_target": pole_name,
                    "chain_length": config["chain_length"],
                    "display_name": config["display_name"],
                }
                created_chains.append(chain_name)

        # Switch to pose mode to add constraints
        bpy.ops.object.mode_set(mode="POSE")

        for chain_name in created_chains:
            chain_data = setup_data["chains"][chain_name]
            config = LARA_IK_CHAINS[chain_name]

            # Setup IK constraint
            pole_angle = config.get("pole_angle", 0.0)
            _setup_ik_constraint(
                rig,
                chain_data["ik_bone"],
                chain_data["ik_target"],
                chain_data["pole_target"],
                chain_data["chain_length"],
                pole_angle,
                use_rotation=True,
                rotation_weight=0.01,
            )

            # Add IK/FK switch property
            prop_name = _add_ikfk_property(rig, chain_name, chain_data["display_name"])
            chain_data["ikfk_prop"] = prop_name

            # Add driver for IK/FK switching
            _add_ikfk_driver(rig, chain_data["ik_bone"], prop_name)

            # Set custom shapes for control bones
            # IK targets: cube offset -0.09 in Y to cage feet/hands
            _set_bone_custom_shape(rig, chain_data["ik_target"], "ik_cube",
                                   scale=1.0, translation=(0, -0.09, 0))
            # Pole targets: larger sphere (4x) for better visibility
            _set_bone_custom_shape(rig, chain_data["pole_target"], "pole_sphere",
                                   scale=4.0, translation=(0, 0, 0))

            # Set bone colors for visibility
            ik_pose_bone = rig.pose.bones.get(chain_data["ik_target"])
            pole_pose_bone = rig.pose.bones.get(chain_data["pole_target"])

            if ik_pose_bone:
                ik_pose_bone.color.palette = 'THEME02'  # Red/Orange
            if pole_pose_bone:
                pole_pose_bone.color.palette = 'THEME04'  # Yellow

        # Save setup data
        _save_ik_setup_data(rig, setup_data)

        # Restore mode
        if prev_mode != "POSE":
            bpy.ops.object.mode_set(mode=prev_mode)

        if created_chains:
            self.report({"INFO"}, f"Created IK setup for: {', '.join(created_chains)}")
        else:
            self.report({"WARNING"}, "No matching bones found for IK setup.")
            return {"CANCELLED"}

        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "setup_legs")
        layout.prop(self, "setup_arms")


class WadBlenderRemoveIK(Operator):
    bl_idname = "wadblender.remove_ik"
    bl_label = "Remove IK Controls"
    bl_description = "Remove IK setup from the rig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)

        if not setup_data:
            self.report({"WARNING"}, "No IK setup found to remove.")
            return {"CANCELLED"}

        prev_mode = rig.mode

        # Remove constraints first (pose mode)
        bpy.ops.object.mode_set(mode="POSE")

        for chain_name, chain_data in setup_data.get("chains", {}).items():
            ik_bone_name = chain_data.get("ik_bone")
            if ik_bone_name:
                pose_bone = rig.pose.bones.get(ik_bone_name)
                if pose_bone:
                    for constraint in list(pose_bone.constraints):
                        if constraint.type == "IK" and constraint.name.startswith("WadBlender_IK"):
                            # Remove driver first
                            try:
                                constraint.driver_remove("influence")
                            except Exception:
                                pass
                            pose_bone.constraints.remove(constraint)

            # Remove IK/FK property
            prop_name = chain_data.get("ikfk_prop")
            if prop_name and prop_name in rig:
                del rig[prop_name]

        # Remove bones (edit mode)
        bpy.ops.object.mode_set(mode="EDIT")

        for chain_name, chain_data in setup_data.get("chains", {}).items():
            for bone_key in ["ik_target", "pole_target"]:
                bone_name = chain_data.get(bone_key)
                if bone_name and bone_name in rig.data.edit_bones:
                    rig.data.edit_bones.remove(rig.data.edit_bones[bone_name])

        # Remove setup data
        if IK_SETUP_KEY in rig:
            del rig[IK_SETUP_KEY]

        # Restore mode
        bpy.ops.object.mode_set(mode="OBJECT")
        if prev_mode not in ("EDIT", "OBJECT"):
            bpy.ops.object.mode_set(mode=prev_mode)

        self.report({"INFO"}, "IK setup removed.")
        return {"FINISHED"}


class WadBlenderToggleIKFK(Operator):
    bl_idname = "wadblender.toggle_ikfk"
    bl_label = "Toggle IK/FK"
    bl_description = "Toggle between IK and FK mode for selected chain"
    bl_options = {"REGISTER", "UNDO"}

    chain: bpy.props.StringProperty(name="Chain", default="all")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE" and _has_ik_setup(obj)

    def execute(self, context):
        rig = context.active_object
        setup_data = _get_ik_setup_data(rig)

        if not setup_data:
            return {"CANCELLED"}

        chains_to_toggle = []
        if self.chain == "all":
            chains_to_toggle = list(setup_data.get("chains", {}).keys())
        elif self.chain in setup_data.get("chains", {}):
            chains_to_toggle = [self.chain]

        for chain_name in chains_to_toggle:
            chain_data = setup_data["chains"][chain_name]
            prop_name = chain_data.get("ikfk_prop")
            if prop_name and prop_name in rig:
                current = rig[prop_name]
                rig[prop_name] = 0.0 if current > 0.5 else 1.0

        return {"FINISHED"}


class WadBlenderIKPanel(Panel):
    bl_label = "IK/FK Tools"
    bl_idname = "WADBLENDER_PT_IKTools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wad Blender"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "ARMATURE"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        rig = context.active_object

        # IK Setup Section
        box = layout.box()
        box.label(text="IK Setup", icon="CON_KINEMATIC")

        if rig and _has_ik_setup(rig):
            # Show IK/FK controls when setup exists
            setup_data = _get_ik_setup_data(rig)
            chains = setup_data.get("chains", {})

            if chains:
                col = box.column(align=True)
                for chain_name, chain_data in chains.items():
                    prop_name = chain_data.get("ikfk_prop")
                    display_name = chain_data.get("display_name", chain_name)
                    if prop_name and prop_name in rig:
                        row = col.row(align=True)
                        row.prop(rig, f'["{prop_name}"]', text=display_name, slider=True)
                        # Toggle button
                        op = row.operator("wadblender.toggle_ikfk", text="", icon="FILE_REFRESH")
                        op.chain = chain_name

            row = box.row()
            row.operator("wadblender.toggle_ikfk", text="Toggle All IK/FK", icon="FILE_REFRESH").chain = "all"

            # Snapping Section
            box.separator()
            box.label(text="Snapping:", icon="SNAP_ON")
            row = box.row(align=True)
            row.operator("wadblender.snap_ik_to_fk", text="IK → FK", icon="FORWARD").chain = "all"
            row.operator("wadblender.snap_fk_to_ik", text="FK → IK", icon="BACK").chain = "all"

            # Space Switching Section
            box.separator()
            box.label(text="Space Switching:", icon="ORIENTATION_GLOBAL")
            for chain_name, chain_data in chains.items():
                display_name = chain_data.get("display_name", chain_name)
                ik_space = chain_data.get("ik_space", SPACE_WORLD)
                pole_space = chain_data.get("pole_space", SPACE_WORLD)

                # Collapsible sub-box for each chain
                sub_box = box.box()
                sub_box.label(text=display_name)

                row = sub_box.row(align=True)
                row.label(text="IK:")
                for space_id, space_name, _ in SPACE_ITEMS:
                    op = row.operator(
                        "wadblender.set_ik_space",
                        text=space_name,
                        depress=(ik_space == space_id)
                    )
                    op.chain = chain_name
                    op.space = space_id

                row = sub_box.row(align=True)
                row.label(text="Pole:")
                for space_id, space_name, _ in POLE_SPACE_ITEMS:
                    op = row.operator(
                        "wadblender.set_pole_space",
                        text=space_name,
                        depress=(pole_space == space_id)
                    )
                    op.chain = chain_name
                    op.space = space_id

                # Pole angle adjustment
                row = sub_box.row(align=True)
                row.label(text="Pole ∠:")
                op = row.operator("wadblender.adjust_pole_angle", text="Adjust")
                op.chain = chain_name

            box.separator()
            box.operator("wadblender.remove_ik", text="Remove IK Setup", icon="X")
        else:
            # Show setup button when no IK exists
            box.operator("wadblender.setup_ik", text="Setup IK Controls", icon="CON_KINEMATIC")

        # Bake Section
        box = layout.box()
        box.label(text="Bake IK to FK", icon="ACTION")
        box.prop(scene, "wadblender_ik_use_scene_range")
        box.prop(scene, "wadblender_ik_bake_step")
        box.prop(scene, "wadblender_ik_only_selected")
        box.prop(scene, "wadblender_ik_force_quaternion")
        box.prop(scene, "wadblender_ik_mute_constraints")
        box.operator("wadblender.bake_ik_to_fk", icon="ACTION")

        row = layout.row()
        row.operator("wadblender.restore_ik_constraints", icon="CONSTRAINT")

        # Bone Renaming Section
        if rig and rig.type == "ARMATURE":
            box = layout.box()
            box.label(text="Bone Names", icon="ARMATURE_DATA")
            if LARA_BONE_RENAME_KEY in rig:
                label = "Restore Lara Bone Names"
            else:
                label = "Rename Lara Bones (Anim)"
            box.operator("wadblender.toggle_lara_anim_names", text=label, icon="ARMATURE_DATA")


def register():
    bpy.types.Scene.wadblender_ik_use_scene_range = BoolProperty(
        name="Use Scene Range",
        description="Bake using the scene frame range instead of the action range",
        default=False,
    )
    bpy.types.Scene.wadblender_ik_bake_step = IntProperty(
        name="Step",
        description="Frame step for baking",
        default=1,
        min=1,
        max=1000,
    )
    bpy.types.Scene.wadblender_ik_only_selected = BoolProperty(
        name="Only Selected Bones",
        description="Bake only selected pose bones",
        default=False,
    )
    bpy.types.Scene.wadblender_ik_force_quaternion = BoolProperty(
        name="Force Quaternion",
        description="Bake with bones in quaternion rotation mode",
        default=True,
    )
    bpy.types.Scene.wadblender_ik_mute_constraints = BoolProperty(
        name="Mute IK Constraints",
        description="Mute IK constraints after baking (non-destructive)",
        default=True,
    )

    bpy.utils.register_class(WadBlenderBakeIKToFK)
    bpy.utils.register_class(WadBlenderRestoreIKConstraints)
    bpy.utils.register_class(WadBlenderToggleLaraAnimNames)
    bpy.utils.register_class(WadBlenderSetupIK)
    bpy.utils.register_class(WadBlenderRemoveIK)
    bpy.utils.register_class(WadBlenderToggleIKFK)
    bpy.utils.register_class(WadBlenderSnapIKToFK)
    bpy.utils.register_class(WadBlenderSnapFKToIK)
    bpy.utils.register_class(WadBlenderSetIKSpace)
    bpy.utils.register_class(WadBlenderSetPoleSpace)
    bpy.utils.register_class(WadBlenderAdjustPoleAngle)
    bpy.utils.register_class(WadBlenderIKPanel)


def unregister():
    bpy.utils.unregister_class(WadBlenderIKPanel)
    bpy.utils.unregister_class(WadBlenderAdjustPoleAngle)
    bpy.utils.unregister_class(WadBlenderSetPoleSpace)
    bpy.utils.unregister_class(WadBlenderSetIKSpace)
    bpy.utils.unregister_class(WadBlenderSnapFKToIK)
    bpy.utils.unregister_class(WadBlenderSnapIKToFK)
    bpy.utils.unregister_class(WadBlenderToggleIKFK)
    bpy.utils.unregister_class(WadBlenderRemoveIK)
    bpy.utils.unregister_class(WadBlenderSetupIK)
    bpy.utils.unregister_class(WadBlenderToggleLaraAnimNames)
    bpy.utils.unregister_class(WadBlenderRestoreIKConstraints)
    bpy.utils.unregister_class(WadBlenderBakeIKToFK)

    del bpy.types.Scene.wadblender_ik_use_scene_range
    del bpy.types.Scene.wadblender_ik_bake_step
    del bpy.types.Scene.wadblender_ik_only_selected
    del bpy.types.Scene.wadblender_ik_force_quaternion
    del bpy.types.Scene.wadblender_ik_mute_constraints
