import json
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Matrix, Quaternion, Vector


RETARGET_DATA_KEY = "wadblender_retarget_mapping"
REFERENCE_POSE_KEY = "wadblender_reference_pose"

# Cache for bone items to prevent EnumProperty refresh issues
_bone_items_cache = {
    "armature": None,
    "items": [("NONE", "-- None --", "No bone mapped")],
}

# Lara's bone structure with common naming patterns for auto-detection
# "is_root" = primary root bone (hips for Lara since she has no separate root)
# "transfer_location" = bones that should also receive location data (for upper body movement)
# Note: Lara has no separate root bone - her hips IS the root.
# For source rigs with a separate root bone, we combine root + hips location.
LARA_BONES = {
    "root": {
        "display_name": "Root (if separate)",
        "patterns": ["ROOT", "Root", "root", "Armature", "mixamorig:Hips"],  # Mixamo's "Hips" is actually root
        "is_source_root": True,  # This is the source's root, not Lara's
        "no_target_bone": True,  # Lara doesn't have this bone - location goes to hips
    },
    "hips": {
        "display_name": "Hips",
        "patterns": ["HIPS", "Hips", "pelvis", "Mesh_12"],  # Removed "root" - that's handled above
        "is_root": True,  # Lara's hips IS her root
        "transfer_location": True,
    },
    "torso": {
        "display_name": "Torso",
        "patterns": ["TORSO", "Torso", "spine", "chest", "Mesh_19"],
        "transfer_location": True,  # Critical for arm rotation accuracy
    },
    "head": {
        "display_name": "Head",
        "patterns": ["HEAD", "Head", "Mesh_26"],
    },
    "thigh_l": {
        "display_name": "Left Thigh",
        "patterns": ["LEFT_THIGH", "Thigh_L", "thigh.L", "LeftUpLeg", "Mesh_13"],
    },
    "shin_l": {
        "display_name": "Left Shin",
        "patterns": ["LEFT_SHIN", "Shin_L", "shin.L", "LeftLeg", "Mesh_14"],
    },
    "foot_l": {
        "display_name": "Left Foot",
        "patterns": ["LEFT_FOOT", "Foot_L", "foot.L", "LeftFoot", "Mesh_15"],
    },
    "thigh_r": {
        "display_name": "Right Thigh",
        "patterns": ["RIGHT_THIGH", "Thigh_R", "thigh.R", "RightUpLeg", "Mesh_16"],
    },
    "shin_r": {
        "display_name": "Right Shin",
        "patterns": ["RIGHT_SHIN", "Shin_R", "shin.R", "RightLeg", "Mesh_17"],
    },
    "foot_r": {
        "display_name": "Right Foot",
        "patterns": ["RIGHT_FOOT", "Foot_R", "foot.R", "RightFoot", "Mesh_18"],
    },
    "upper_arm_l": {
        "display_name": "Left Upper Arm",
        "patterns": ["LEFT_UPPER_ARM", "UpperArm_L", "upper_arm.L", "LeftArm", "Mesh_23"],
    },
    "forearm_l": {
        "display_name": "Left Forearm",
        "patterns": ["LEFT_FOREARM", "LowerArm_L", "forearm.L", "LeftForeArm", "Mesh_24"],
    },
    "hand_l": {
        "display_name": "Left Hand",
        "patterns": ["LEFT_HAND", "Hand_L", "hand.L", "LeftHand", "Mesh_25"],
    },
    "upper_arm_r": {
        "display_name": "Right Upper Arm",
        "patterns": ["RIGHT_UPPER_ARM", "UpperArm_R", "upper_arm.R", "RightArm", "Mesh_20"],
    },
    "forearm_r": {
        "display_name": "Right Forearm",
        "patterns": ["RIGHT_FOREARM", "LowerArm_R", "forearm.R", "RightForeArm", "Mesh_21"],
    },
    "hand_r": {
        "display_name": "Right Hand",
        "patterns": ["RIGHT_HAND", "Hand_R", "hand.R", "RightHand", "Mesh_22"],
    },
}


def get_armature_items(self, context):
    """Get list of armatures in the scene for dropdown."""
    items = [("NONE", "-- Select --", "")]
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            items.append((obj.name, obj.name, f"Armature: {obj.name}"))
    return items


def get_bone_items(self, context):
    """Get list of bones from the source armature for dropdown with caching."""
    global _bone_items_cache

    settings = context.scene.wadblender_retarget
    armature_name = settings.source_armature if settings.source_armature != "NONE" else None

    # Return cached items if armature hasn't changed
    if armature_name == _bone_items_cache["armature"]:
        return _bone_items_cache["items"]

    # Rebuild cache
    items = [("NONE", "-- None --", "No bone mapped")]

    if armature_name:
        source_obj = bpy.data.objects.get(armature_name)
        if source_obj and source_obj.type == "ARMATURE":
            for bone in sorted(source_obj.data.bones, key=lambda b: b.name):
                items.append((bone.name, bone.name, f"Bone: {bone.name}"))

    _bone_items_cache["armature"] = armature_name
    _bone_items_cache["items"] = items

    return items


def invalidate_bone_cache():
    """Invalidate bone items cache when armature selection changes."""
    global _bone_items_cache
    _bone_items_cache["armature"] = None
    _bone_items_cache["items"] = [("NONE", "-- None --", "No bone mapped")]


def _on_source_armature_update(self, context):
    """Callback when source armature selection changes."""
    invalidate_bone_cache()


def _find_bone_by_patterns(armature, patterns):
    """Find a bone in armature matching any of the patterns."""
    if not armature or armature.type != "ARMATURE":
        return None

    for bone in armature.data.bones:
        bone_upper = bone.name.upper()
        for pattern in patterns:
            pattern_upper = pattern.upper()
            if pattern_upper in bone_upper or bone.name == pattern:
                return bone.name
    return None


def _swizzle_location(loc, axis_order):
    """
    Remap location axes based on axis_order string.

    Used to convert between different coordinate system conventions:
    - Blender uses Z-up, Y-forward (right-handed)
    - Some systems use Y-up, Z-forward
    - Mixamo/Unity typically use Y-up

    The axis_order string specifies which source axis maps to each target axis.
    For example, "XZY" means: target.x=source.x, target.y=source.z, target.z=source.y
    Negative signs flip that axis direction.
    """
    x, y, z = loc.x, loc.y, loc.z

    if axis_order == "XYZ":
        return Vector((x, y, z))
    elif axis_order == "XZY":
        return Vector((x, z, y))
    elif axis_order == "YXZ":
        return Vector((y, x, z))
    elif axis_order == "YZX":
        return Vector((y, z, x))
    elif axis_order == "ZXY":
        return Vector((z, x, y))
    elif axis_order == "ZYX":
        return Vector((z, y, x))
    elif axis_order == "-XYZ":
        return Vector((-x, y, z))
    elif axis_order == "X-YZ":
        return Vector((x, -y, z))
    elif axis_order == "XY-Z":
        return Vector((x, y, -z))
    elif axis_order == "-X-YZ":
        return Vector((-x, -y, z))
    elif axis_order == "-XY-Z":
        return Vector((-x, y, -z))
    elif axis_order == "X-Y-Z":
        return Vector((x, -y, -z))
    else:
        return Vector((x, y, z))


# ============================================================================
# Eyedropper Bone Picker
# ============================================================================

class WadBlenderPickBone(Operator):
    """Pick a bone from the active armature in pose mode using eyedropper."""
    bl_idname = "wadblender.pick_bone"
    bl_label = "Pick Bone"
    bl_description = "Click on a bone in the 3D view to select it (works in Pose mode)"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    bone_slot: StringProperty(
        name="Bone Slot",
        description="Which bone mapping slot to set",
    )

    def invoke(self, context, event):
        # Store the slot we're picking for
        context.window_manager.wadblender_picking_slot = self.bone_slot
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Click on a bone to select it, or press ESC to cancel")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            # Get the active bone from the source armature
            settings = context.scene.wadblender_retarget
            source_obj = bpy.data.objects.get(settings.source_armature)

            if source_obj and source_obj.type == "ARMATURE":
                # Check if we clicked on a bone
                if context.active_object == source_obj and context.active_bone:
                    bone_name = context.active_bone.name
                    slot = context.window_manager.wadblender_picking_slot

                    if slot and hasattr(settings, slot):
                        setattr(settings, slot, bone_name)
                        self.report({"INFO"}, f"Mapped: {bone_name}")
                    context.area.header_text_set(None)
                    return {"FINISHED"}

            self.report({"WARNING"}, "Select a bone from the source armature")
            return {"RUNNING_MODAL"}

        elif event.type in {"RIGHTMOUSE", "ESC"}:
            context.area.header_text_set(None)
            self.report({"INFO"}, "Bone picking cancelled")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}


class WadBlenderPickBoneFromSelection(Operator):
    """Set bone mapping from currently selected bone in pose mode."""
    bl_idname = "wadblender.pick_bone_from_selection"
    bl_label = "Pick from Selection"
    bl_description = "Use the currently active bone from the source armature"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    bone_slot: StringProperty(
        name="Bone Slot",
        description="Which bone mapping slot to set",
    )

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_retarget
        source_obj = bpy.data.objects.get(settings.source_armature) if settings.source_armature != "NONE" else None
        return (
            source_obj is not None and
            context.active_object == source_obj and
            context.mode == "POSE" and
            context.active_pose_bone is not None
        )

    def execute(self, context):
        settings = context.scene.wadblender_retarget
        bone_name = context.active_pose_bone.name

        if self.bone_slot and hasattr(settings, self.bone_slot):
            setattr(settings, self.bone_slot, bone_name)
            self.report({"INFO"}, f"Mapped: {bone_name}")
            return {"FINISHED"}

        self.report({"WARNING"}, "Invalid bone slot")
        return {"CANCELLED"}


# ============================================================================
# Reference Pose System
# ============================================================================

def _get_reference_pose_data(scene):
    """Get stored reference pose data from scene."""
    raw = scene.get(REFERENCE_POSE_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _save_reference_pose_data(scene, data):
    """Save reference pose data to scene."""
    scene[REFERENCE_POSE_KEY] = json.dumps(data)


def _clear_reference_pose_data(scene):
    """Clear stored reference pose data."""
    if REFERENCE_POSE_KEY in scene:
        del scene[REFERENCE_POSE_KEY]


def _capture_bone_world_rotation(armature, bone_name):
    """Capture the world-space rotation of a pose bone."""
    pose_bone = armature.pose.bones.get(bone_name)
    if not pose_bone:
        return None

    # Get world matrix and extract rotation
    world_mat = armature.matrix_world @ pose_bone.matrix
    return world_mat.to_quaternion()


def _capture_bone_world_location(armature, bone_name):
    """Capture the world-space location of a pose bone head."""
    pose_bone = armature.pose.bones.get(bone_name)
    if not pose_bone:
        return None

    world_mat = armature.matrix_world @ pose_bone.matrix
    return world_mat.translation.copy()


def _capture_reference_pose(context, source_obj, target_obj, bone_mapping):
    """
    Capture the current pose of both rigs as the reference pose.
    This should be called when both rigs are in the SAME pose (e.g., T-pose).

    Returns a dict with world-space rotations and locations for each mapped bone pair.
    """
    bpy.context.view_layer.update()

    ref_data = {
        "source_armature": source_obj.name,
        "target_armature": target_obj.name,
        "bones": {},
    }

    for bone_key, mapping in bone_mapping.items():
        source_bone_name = mapping["source"]
        target_bone_name = mapping["target"]
        transfer_location = mapping.get("transfer_location", False)
        is_source_root = mapping.get("is_source_root", False)

        # Special case: source root bone (no target - location goes to hips)
        if is_source_root:
            source_loc = _capture_bone_world_location(source_obj, source_bone_name)
            if source_loc:
                ref_data["bones"][bone_key] = {
                    "source_bone": source_bone_name,
                    "target_bone": None,
                    "is_source_root": True,
                    "source_ref_loc": list(source_loc),
                }
            continue

        source_rot = _capture_bone_world_rotation(source_obj, source_bone_name)
        target_rot = _capture_bone_world_rotation(target_obj, target_bone_name)

        if source_rot and target_rot:
            bone_data = {
                "source_bone": source_bone_name,
                "target_bone": target_bone_name,
                "source_world_rot": list(source_rot),
                "target_world_rot": list(target_rot),
                "transfer_location": transfer_location,
            }

            # Also capture reference locations for bones that transfer location
            if transfer_location:
                source_loc = _capture_bone_world_location(source_obj, source_bone_name)
                target_loc = _capture_bone_world_location(target_obj, target_bone_name)
                if source_loc and target_loc:
                    bone_data["source_ref_loc"] = list(source_loc)
                    bone_data["target_ref_loc"] = list(target_loc)

            ref_data["bones"][bone_key] = bone_data

    return ref_data


def _retarget_with_reference(source_obj, target_obj, source_pose_bone, target_pose_bone,
                              ref_source_world_rot, ref_target_world_rot):
    """
    Retarget rotation using reference pose method.

    The idea:
    1. In the reference pose, both bones should represent the "same" orientation semantically
    2. Calculate how the source bone has rotated FROM its reference world rotation
    3. Apply that same rotation TO the target's reference world rotation
    4. Convert back to local space for the target

    This works regardless of how the bones are oriented in their rest poses,
    because we're comparing to a user-defined "same pose" state.
    """
    # Get current source world rotation
    source_world_mat = source_obj.matrix_world @ source_pose_bone.matrix
    source_world_rot = source_world_mat.to_quaternion()

    # Calculate the delta from source's reference to current
    # delta = current @ reference^-1 (rotation from ref to current)
    ref_source_quat = Quaternion(ref_source_world_rot)
    source_delta = source_world_rot @ ref_source_quat.inverted()

    # Apply this delta to target's reference rotation
    ref_target_quat = Quaternion(ref_target_world_rot)
    target_world_rot = source_delta @ ref_target_quat

    # Convert target world rotation to local space
    # target_world = armature_world @ bone_matrix
    # bone_matrix = pose_bone.matrix (in armature space)
    # We need to find the local rotation that produces this world rotation

    # Get the target bone's parent world matrix (if any)
    if target_pose_bone.parent:
        parent_world_mat = target_obj.matrix_world @ target_pose_bone.parent.matrix
    else:
        parent_world_mat = target_obj.matrix_world.copy()

    # The target's posed matrix in world space should match target_world_rot
    # world_mat = parent_world @ local_mat @ rest_offset
    # We need to solve for local rotation

    # Get rest pose info
    target_bone = target_obj.data.bones.get(target_pose_bone.name)
    if not target_bone:
        return Quaternion()

    # Rest matrix in armature space
    rest_mat = target_bone.matrix_local

    # Parent's rest matrix
    if target_bone.parent:
        parent_rest_mat = target_bone.parent.matrix_local
        local_rest_mat = parent_rest_mat.inverted() @ rest_mat
    else:
        local_rest_mat = rest_mat

    local_rest_rot = local_rest_mat.to_quaternion()

    # We want: parent_world_rot @ local_rot @ local_rest_rot = target_world_rot
    # Solving: local_rot = parent_world_rot^-1 @ target_world_rot @ local_rest_rot^-1

    parent_world_rot = parent_world_mat.to_quaternion()
    local_rot = parent_world_rot.inverted() @ target_world_rot @ local_rest_rot.inverted()

    return local_rot


# ============================================================================
# Settings and Operators
# ============================================================================

class WadBlenderRetargetSettings(PropertyGroup):
    """Settings for animation retargeting."""

    source_armature: EnumProperty(
        name="Source Rig",
        description="The animated armature to copy from",
        items=get_armature_items,
        update=_on_source_armature_update,
    )

    target_armature: EnumProperty(
        name="Target Rig",
        description="The Lara armature to copy animation to",
        items=get_armature_items,
    )

    # Bone mappings - source bone for each Lara bone
    # Root is special: source rigs may have a separate root bone for world movement
    # Lara doesn't have a root - her hips IS root, so root location goes to hips
    map_root: EnumProperty(
        name="Root (optional)",
        description="Source root bone if separate from hips (e.g., Mixamo). Location will be added to Lara's hips",
        items=get_bone_items,
    )
    map_hips: EnumProperty(name="Hips", items=get_bone_items)
    map_torso: EnumProperty(name="Torso", items=get_bone_items)
    map_head: EnumProperty(name="Head", items=get_bone_items)
    map_thigh_l: EnumProperty(name="Left Thigh", items=get_bone_items)
    map_shin_l: EnumProperty(name="Left Shin", items=get_bone_items)
    map_foot_l: EnumProperty(name="Left Foot", items=get_bone_items)
    map_thigh_r: EnumProperty(name="Right Thigh", items=get_bone_items)
    map_shin_r: EnumProperty(name="Right Shin", items=get_bone_items)
    map_foot_r: EnumProperty(name="Right Foot", items=get_bone_items)
    map_upper_arm_l: EnumProperty(name="Left Upper Arm", items=get_bone_items)
    map_forearm_l: EnumProperty(name="Left Forearm", items=get_bone_items)
    map_hand_l: EnumProperty(name="Left Hand", items=get_bone_items)
    map_upper_arm_r: EnumProperty(name="Right Upper Arm", items=get_bone_items)
    map_forearm_r: EnumProperty(name="Right Forearm", items=get_bone_items)
    map_hand_r: EnumProperty(name="Right Hand", items=get_bone_items)

    # Location options
    include_location: BoolProperty(
        name="Include Location",
        description="Copy location data for root (hips) and upper body (torso) bones",
        default=True,
    )

    include_torso_location: BoolProperty(
        name="Include Torso Location",
        description="Also transfer torso location (fixes arm rotation when upper body moves)",
        default=True,
    )

    location_scale: FloatProperty(
        name="Location Scale",
        description="Scale factor for location transfer. Adjust based on rig size difference (0.01 = meters to Lara units)",
        default=0.01,
        min=0.0001,
        max=100.0,
        step=1,
        precision=4,
    )

    location_axis_order: EnumProperty(
        name="Location Axes",
        description="How to map source XYZ to target XYZ (use if character moves wrong direction)",
        items=[
            ("XYZ", "X Y Z", "No change"),
            ("XZY", "X Z Y", "Swap Y and Z"),
            ("YXZ", "Y X Z", "Swap X and Y"),
            ("YZX", "Y Z X", "Rotate axes"),
            ("ZXY", "Z X Y", "Rotate axes"),
            ("ZYX", "Z Y X", "Swap X and Z"),
            ("-XYZ", "-X Y Z", "Flip X"),
            ("X-YZ", "X -Y Z", "Flip Y"),
            ("XY-Z", "X Y -Z", "Flip Z"),
            ("-X-YZ", "-X -Y Z", "Flip X and Y"),
            ("-XY-Z", "-X Y -Z", "Flip X and Z"),
            ("X-Y-Z", "X -Y -Z", "Flip Y and Z"),
        ],
        default="XYZ",
    )

    bake_step: IntProperty(
        name="Frame Step",
        description="Sample every Nth frame (1 = every frame)",
        default=1,
        min=1,
        max=10,
    )

    use_scene_range: BoolProperty(
        name="Use Scene Range",
        description="Use scene frame range instead of action range",
        default=False,
    )

    create_new_action: BoolProperty(
        name="Create New Action",
        description="Create a new action instead of overwriting existing",
        default=True,
    )

    action_name: StringProperty(
        name="Action Name",
        description="Name for the new action",
        default="Retargeted_Action",
    )


class WadBlenderAutoMapBones(Operator):
    bl_idname = "wadblender.retarget_automap"
    bl_label = "Auto-Detect Mapping"
    bl_description = "Automatically map bones based on common naming conventions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_retarget
        return settings.source_armature != "NONE"

    def execute(self, context):
        settings = context.scene.wadblender_retarget
        source_obj = bpy.data.objects.get(settings.source_armature)

        if not source_obj:
            self.report({"WARNING"}, "Source armature not found")
            return {"CANCELLED"}

        mapped_count = 0
        for bone_key, bone_info in LARA_BONES.items():
            prop_name = f"map_{bone_key}"
            found_bone = _find_bone_by_patterns(source_obj, bone_info["patterns"])

            if found_bone:
                setattr(settings, prop_name, found_bone)
                mapped_count += 1
            else:
                setattr(settings, prop_name, "NONE")

        self.report({"INFO"}, f"Auto-mapped {mapped_count}/{len(LARA_BONES)} bones")
        return {"FINISHED"}


class WadBlenderClearMapping(Operator):
    bl_idname = "wadblender.retarget_clear"
    bl_label = "Clear Mapping"
    bl_description = "Clear all bone mappings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.wadblender_retarget

        for bone_key in LARA_BONES.keys():
            prop_name = f"map_{bone_key}"
            setattr(settings, prop_name, "NONE")

        self.report({"INFO"}, "Cleared all bone mappings")
        return {"FINISHED"}


class WadBlenderCaptureReferencePose(Operator):
    bl_idname = "wadblender.retarget_capture_ref"
    bl_label = "Capture Reference Pose"
    bl_description = "Capture current pose of both rigs as the reference. Both rigs should be in the SAME pose (e.g., T-pose)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_retarget
        return (
            settings.source_armature != "NONE" and
            settings.target_armature != "NONE" and
            settings.source_armature != settings.target_armature
        )

    def execute(self, context):
        settings = context.scene.wadblender_retarget
        source_obj = bpy.data.objects.get(settings.source_armature)
        target_obj = bpy.data.objects.get(settings.target_armature)

        if not source_obj or not target_obj:
            self.report({"ERROR"}, "Source or target armature not found")
            return {"CANCELLED"}

        # Build bone mapping
        bone_mapping = {}
        for bone_key, bone_info in LARA_BONES.items():
            prop_name = f"map_{bone_key}"
            source_bone = getattr(settings, prop_name)

            if source_bone == "NONE":
                continue

            # Special case: root bone doesn't map to a target bone
            # Its location gets added to hips
            if bone_info.get("no_target_bone"):
                bone_mapping[bone_key] = {
                    "source": source_bone,
                    "target": None,  # No target bone
                    "is_source_root": True,
                    "transfer_location": True,
                }
                continue

            target_bone = _find_bone_by_patterns(target_obj, bone_info["patterns"])
            if target_bone:
                bone_mapping[bone_key] = {
                    "source": source_bone,
                    "target": target_bone,
                    "is_root": bone_info.get("is_root", False),
                    "transfer_location": bone_info.get("transfer_location", False),
                }

        if not bone_mapping:
            self.report({"ERROR"}, "No valid bone mappings found. Map bones first.")
            return {"CANCELLED"}

        # Capture reference pose
        ref_data = _capture_reference_pose(context, source_obj, target_obj, bone_mapping)
        _save_reference_pose_data(context.scene, ref_data)

        self.report({"INFO"}, f"Captured reference pose for {len(ref_data['bones'])} bone pairs")
        return {"FINISHED"}


class WadBlenderClearReferencePose(Operator):
    bl_idname = "wadblender.retarget_clear_ref"
    bl_label = "Clear Reference Pose"
    bl_description = "Clear the stored reference pose"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_reference_pose_data(context.scene) is not None

    def execute(self, context):
        _clear_reference_pose_data(context.scene)
        self.report({"INFO"}, "Reference pose cleared")
        return {"FINISHED"}


class WadBlenderSwapSourceTarget(Operator):
    bl_idname = "wadblender.retarget_swap"
    bl_label = "Swap"
    bl_description = "Swap source and target armatures"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.wadblender_retarget
        source = settings.source_armature
        target = settings.target_armature
        settings.source_armature = target
        settings.target_armature = source
        return {"FINISHED"}


class WadBlenderRetargetAnimation(Operator):
    bl_idname = "wadblender.retarget_execute"
    bl_label = "Retarget Animation"
    bl_description = "Copy animation from source rig to target rig using reference pose"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_retarget
        ref_data = _get_reference_pose_data(context.scene)
        return (
            settings.source_armature != "NONE" and
            settings.target_armature != "NONE" and
            settings.source_armature != settings.target_armature and
            ref_data is not None
        )

    def execute(self, context):
        settings = context.scene.wadblender_retarget
        ref_data = _get_reference_pose_data(context.scene)

        if not ref_data:
            self.report({"ERROR"}, "No reference pose captured. Capture reference pose first.")
            return {"CANCELLED"}

        source_obj = bpy.data.objects.get(settings.source_armature)
        target_obj = bpy.data.objects.get(settings.target_armature)

        if not source_obj or not target_obj:
            self.report({"ERROR"}, "Source or target armature not found")
            return {"CANCELLED"}

        # Verify reference pose matches current rigs
        if ref_data.get("source_armature") != source_obj.name or ref_data.get("target_armature") != target_obj.name:
            self.report({"WARNING"}, "Reference pose was captured for different rigs. Results may be incorrect.")

        # Build bone mapping with reference data
        bone_mapping = {}
        source_root_data = None  # Track source root bone separately

        for bone_key, ref_bone_data in ref_data.get("bones", {}).items():
            bone_info = LARA_BONES.get(bone_key)
            if not bone_info:
                continue

            # Special case: source root bone (no target - location goes to hips)
            if ref_bone_data.get("is_source_root"):
                source_root_data = {
                    "source_bone": ref_bone_data["source_bone"],
                    "source_ref_loc": ref_bone_data.get("source_ref_loc"),
                }
                continue

            bone_mapping[bone_key] = {
                "source_bone": ref_bone_data["source_bone"],
                "target_bone": ref_bone_data["target_bone"],
                "ref_source_world_rot": ref_bone_data.get("source_world_rot"),
                "ref_target_world_rot": ref_bone_data.get("target_world_rot"),
                "is_root": bone_info.get("is_root", False),
                "transfer_location": ref_bone_data.get("transfer_location", False),
                "source_ref_loc": ref_bone_data.get("source_ref_loc"),
                "target_ref_loc": ref_bone_data.get("target_ref_loc"),
            }

        if not bone_mapping:
            self.report({"ERROR"}, "No valid bone mappings in reference pose")
            return {"CANCELLED"}

        # Determine frame range
        if settings.use_scene_range:
            start_frame = context.scene.frame_start
            end_frame = context.scene.frame_end
        else:
            if source_obj.animation_data and source_obj.animation_data.action:
                action = source_obj.animation_data.action
                start_frame = int(action.frame_range[0])
                end_frame = int(action.frame_range[1])
            else:
                start_frame = context.scene.frame_start
                end_frame = context.scene.frame_end

        # Create or get action for target
        if settings.create_new_action:
            action_name = settings.action_name
            if action_name in bpy.data.actions:
                i = 1
                while f"{action_name}.{i:03d}" in bpy.data.actions:
                    i += 1
                action_name = f"{action_name}.{i:03d}"

            new_action = bpy.data.actions.new(name=action_name)

            if not target_obj.animation_data:
                target_obj.animation_data_create()
            target_obj.animation_data.action = new_action
        else:
            if not target_obj.animation_data:
                target_obj.animation_data_create()
            if not target_obj.animation_data.action:
                target_obj.animation_data.action = bpy.data.actions.new(name="Retargeted")

        # Retarget frame by frame
        current_frame = context.scene.frame_current

        # Process bones in hierarchy order
        def get_bone_depth(armature, bone_name):
            if not bone_name:
                return 0
            bone = armature.data.bones.get(bone_name)
            depth = 0
            while bone and bone.parent:
                depth += 1
                bone = bone.parent
            return depth

        # Sort by hierarchy depth (bones with None target are filtered out)
        def safe_depth(k):
            target = bone_mapping[k].get("target_bone")
            return get_bone_depth(target_obj, target) if target else -1

        sorted_keys = sorted(
            [k for k in bone_mapping.keys() if bone_mapping[k].get("target_bone")],
            key=safe_depth
        )

        for frame in range(start_frame, end_frame + 1, settings.bake_step):
            context.scene.frame_set(frame)
            bpy.context.view_layer.update()

            for bone_key in sorted_keys:
                mapping = bone_mapping[bone_key]
                source_bone_name = mapping["source_bone"]
                target_bone_name = mapping["target_bone"]
                is_root = mapping["is_root"]

                source_pose = source_obj.pose.bones.get(source_bone_name)
                target_pose = target_obj.pose.bones.get(target_bone_name)

                if not source_pose or not target_pose:
                    continue

                # Retarget rotation using reference pose method
                retargeted_rot = _retarget_with_reference(
                    source_obj, target_obj,
                    source_pose, target_pose,
                    mapping["ref_source_world_rot"],
                    mapping["ref_target_world_rot"]
                )

                # Set target rotation
                if target_pose.rotation_mode == "QUATERNION":
                    target_pose.rotation_quaternion = retargeted_rot
                    target_pose.keyframe_insert(data_path="rotation_quaternion", frame=frame)
                else:
                    target_pose.rotation_euler = retargeted_rot.to_euler(target_pose.rotation_mode)
                    target_pose.keyframe_insert(data_path="rotation_euler", frame=frame)

                # Copy location for bones that transfer location (root and upper body)
                transfer_location = mapping.get("transfer_location", False)
                # Check if this bone should transfer location based on settings
                should_transfer = (
                    transfer_location and
                    settings.include_location and
                    (is_root or settings.include_torso_location)
                )
                if should_transfer:
                    source_ref_loc = mapping.get("source_ref_loc")
                    target_ref_loc = mapping.get("target_ref_loc")

                    if source_ref_loc and target_ref_loc:
                        # Get current source world location
                        source_world_mat = source_obj.matrix_world @ source_pose.matrix
                        source_world_loc = source_world_mat.translation

                        # Calculate delta from reference location in source world space
                        ref_source_vec = Vector(source_ref_loc)
                        world_delta = source_world_loc - ref_source_vec

                        # If this is hips (Lara's root) and source has a separate root bone,
                        # add the source root's location delta too
                        if is_root and source_root_data:
                            root_bone_name = source_root_data["source_bone"]
                            root_ref_loc = source_root_data.get("source_ref_loc")
                            root_pose = source_obj.pose.bones.get(root_bone_name)

                            if root_pose and root_ref_loc:
                                root_world_mat = source_obj.matrix_world @ root_pose.matrix
                                root_world_loc = root_world_mat.translation
                                root_ref_vec = Vector(root_ref_loc)
                                root_delta = root_world_loc - root_ref_vec
                                # Add root's movement to hips movement
                                world_delta = world_delta + root_delta

                        # Apply axis swizzle to convert between coordinate systems
                        swizzled_delta = _swizzle_location(world_delta, settings.location_axis_order)

                        # Scale the delta for rig size differences
                        scaled_delta = swizzled_delta * settings.location_scale

                        # For Lara's root (hips), apply directly since she has no parent
                        if is_root:
                            target_pose.location = scaled_delta
                        else:
                            # For non-root bones, convert to local space
                            target_bone = target_obj.data.bones.get(target_bone_name)
                            if target_bone and target_pose.parent:
                                parent_world_mat = target_obj.matrix_world @ target_pose.parent.matrix
                                parent_space_delta = parent_world_mat.inverted().to_3x3() @ scaled_delta

                                parent_rest = target_bone.parent.matrix_local
                                bone_rest = target_bone.matrix_local
                                local_rest = parent_rest.inverted() @ bone_rest
                                local_delta = local_rest.inverted().to_3x3() @ parent_space_delta

                                target_pose.location = local_delta
                            else:
                                target_pose.location = scaled_delta

                    target_pose.keyframe_insert(data_path="location", frame=frame)

            bpy.context.view_layer.update()

        context.scene.frame_set(current_frame)

        self.report({"INFO"}, f"Retargeted {len(bone_mapping)} bones over {(end_frame - start_frame) // settings.bake_step + 1} frames")
        return {"FINISHED"}


def _draw_bone_mapping_row(layout, settings, prop_name):
    """Draw a bone mapping row with dropdown and eyedropper button."""
    row = layout.row(align=True)
    row.prop(settings, prop_name)

    # Eyedropper button - picks from currently selected bone
    op = row.operator("wadblender.pick_bone_from_selection", text="", icon="EYEDROPPER")
    op.bone_slot = prop_name


class WadBlenderRetargetPanel(Panel):
    bl_label = "Animation Retargeting"
    bl_idname = "WADBLENDER_PT_Retarget"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wad Blender"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.wadblender_retarget
        ref_data = _get_reference_pose_data(context.scene)

        # Check if source armature is selected in pose mode for eyedropper
        source_obj = bpy.data.objects.get(settings.source_armature) if settings.source_armature != "NONE" else None
        can_pick = (
            source_obj is not None and
            context.active_object == source_obj and
            context.mode == "POSE" and
            context.active_pose_bone is not None
        )

        # Rig Selection
        box = layout.box()
        box.label(text="Rigs", icon="ARMATURE_DATA")

        row = box.row(align=True)
        row.prop(settings, "source_armature", text="Source")

        row = box.row(align=True)
        row.prop(settings, "target_armature", text="Target")

        row = box.row()
        row.operator("wadblender.retarget_swap", text="Swap", icon="FILE_REFRESH")

        # Bone Mapping
        box = layout.box()
        header = box.row()
        header.label(text="Bone Mapping", icon="BONE_DATA")

        row = box.row(align=True)
        row.operator("wadblender.retarget_automap", text="Auto-Detect", icon="VIEWZOOM")
        row.operator("wadblender.retarget_clear", text="Clear", icon="X")

        # Eyedropper hint
        if source_obj and context.mode == "POSE":
            if can_pick:
                box.label(text=f"Active: {context.active_pose_bone.name}", icon="CHECKMARK")
            else:
                box.label(text="Select a bone to use eyedropper", icon="INFO")
        elif source_obj:
            box.label(text="Enter Pose mode for eyedropper", icon="INFO")

        # Show mappings in collapsible sections
        col = box.column(align=True)

        # Root/Spine section
        spine_box = col.box()
        spine_box.label(text="Root & Spine", icon="CON_SPLINEIK")
        spine_col = spine_box.column(align=True)
        # Root is optional - only needed if source has separate root bone
        root_row = spine_col.row(align=True)
        root_row.prop(settings, "map_root")
        op = root_row.operator("wadblender.pick_bone_from_selection", text="", icon="EYEDROPPER")
        op.bone_slot = "map_root"
        spine_col.label(text="(Only if source has separate root)", icon="INFO")
        _draw_bone_mapping_row(spine_col, settings, "map_hips")
        _draw_bone_mapping_row(spine_col, settings, "map_torso")
        _draw_bone_mapping_row(spine_col, settings, "map_head")

        # Left Leg
        leg_l_box = col.box()
        leg_l_box.label(text="Left Leg", icon="CON_KINEMATIC")
        leg_l_col = leg_l_box.column(align=True)
        _draw_bone_mapping_row(leg_l_col, settings, "map_thigh_l")
        _draw_bone_mapping_row(leg_l_col, settings, "map_shin_l")
        _draw_bone_mapping_row(leg_l_col, settings, "map_foot_l")

        # Right Leg
        leg_r_box = col.box()
        leg_r_box.label(text="Right Leg", icon="CON_KINEMATIC")
        leg_r_col = leg_r_box.column(align=True)
        _draw_bone_mapping_row(leg_r_col, settings, "map_thigh_r")
        _draw_bone_mapping_row(leg_r_col, settings, "map_shin_r")
        _draw_bone_mapping_row(leg_r_col, settings, "map_foot_r")

        # Left Arm
        arm_l_box = col.box()
        arm_l_box.label(text="Left Arm", icon="CON_ARMATURE")
        arm_l_col = arm_l_box.column(align=True)
        _draw_bone_mapping_row(arm_l_col, settings, "map_upper_arm_l")
        _draw_bone_mapping_row(arm_l_col, settings, "map_forearm_l")
        _draw_bone_mapping_row(arm_l_col, settings, "map_hand_l")

        # Right Arm
        arm_r_box = col.box()
        arm_r_box.label(text="Right Arm", icon="CON_ARMATURE")
        arm_r_col = arm_r_box.column(align=True)
        _draw_bone_mapping_row(arm_r_col, settings, "map_upper_arm_r")
        _draw_bone_mapping_row(arm_r_col, settings, "map_forearm_r")
        _draw_bone_mapping_row(arm_r_col, settings, "map_hand_r")

        # Reference Pose Section
        box = layout.box()
        box.label(text="Reference Pose", icon="POSE_HLT")

        if ref_data:
            ref_bone_count = len(ref_data.get("bones", {}))
            box.label(text=f"Captured: {ref_bone_count} bones", icon="CHECKMARK")
            row = box.row(align=True)
            row.operator("wadblender.retarget_capture_ref", text="Re-capture", icon="FILE_REFRESH")
            row.operator("wadblender.retarget_clear_ref", text="Clear", icon="X")
        else:
            box.label(text="No reference pose captured", icon="ERROR")
            box.label(text="1. Pose both rigs in the SAME pose")
            box.label(text="2. Click 'Capture Reference Pose'")
            box.operator("wadblender.retarget_capture_ref", text="Capture Reference Pose", icon="POSE_HLT")

        # Options
        box = layout.box()
        box.label(text="Options", icon="PREFERENCES")

        # Location options
        box.prop(settings, "include_location")
        if settings.include_location:
            box.prop(settings, "include_torso_location")
            box.prop(settings, "location_scale")
            box.prop(settings, "location_axis_order")

        # Frame options
        box.separator()
        box.prop(settings, "bake_step")
        box.prop(settings, "use_scene_range")

        box.separator()
        box.prop(settings, "create_new_action")
        if settings.create_new_action:
            box.prop(settings, "action_name")

        # Execute
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.enabled = ref_data is not None
        row.operator("wadblender.retarget_execute", text="Retarget Animation", icon="ACTION")

        if not ref_data:
            layout.label(text="Capture reference pose first!", icon="INFO")


def register():
    bpy.utils.register_class(WadBlenderRetargetSettings)
    bpy.utils.register_class(WadBlenderPickBone)
    bpy.utils.register_class(WadBlenderPickBoneFromSelection)
    bpy.utils.register_class(WadBlenderAutoMapBones)
    bpy.utils.register_class(WadBlenderClearMapping)
    bpy.utils.register_class(WadBlenderCaptureReferencePose)
    bpy.utils.register_class(WadBlenderClearReferencePose)
    bpy.utils.register_class(WadBlenderSwapSourceTarget)
    bpy.utils.register_class(WadBlenderRetargetAnimation)
    bpy.utils.register_class(WadBlenderRetargetPanel)

    bpy.types.Scene.wadblender_retarget = PointerProperty(type=WadBlenderRetargetSettings)

    # Window manager property for modal bone picking
    bpy.types.WindowManager.wadblender_picking_slot = StringProperty(
        name="Picking Slot",
        default="",
    )


def unregister():
    bpy.utils.unregister_class(WadBlenderRetargetPanel)
    bpy.utils.unregister_class(WadBlenderRetargetAnimation)
    bpy.utils.unregister_class(WadBlenderSwapSourceTarget)
    bpy.utils.unregister_class(WadBlenderClearReferencePose)
    bpy.utils.unregister_class(WadBlenderCaptureReferencePose)
    bpy.utils.unregister_class(WadBlenderClearMapping)
    bpy.utils.unregister_class(WadBlenderAutoMapBones)
    bpy.utils.unregister_class(WadBlenderPickBoneFromSelection)
    bpy.utils.unregister_class(WadBlenderPickBone)
    bpy.utils.unregister_class(WadBlenderRetargetSettings)

    del bpy.types.WindowManager.wadblender_picking_slot
    del bpy.types.Scene.wadblender_retarget
