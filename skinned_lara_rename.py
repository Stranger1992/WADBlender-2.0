"""
Skinned Lara Bone Rename Tool

Provides a panel to rename any armature's bones to Lara's skinned bone names
(Mesh_12 through Mesh_26) used by TEN/TRLE.
"""

import bpy
from bpy.props import (
    EnumProperty,
    PointerProperty,
    StringProperty,
    BoolProperty,
)
from bpy.types import Operator, Panel, PropertyGroup


# Lara's skinned bone names and their display names
SKINNED_BONES = {
    "hips": {
        "target_name": "Mesh_12",
        "display_name": "Hips",
        "patterns": ["hips", "pelvis", "root", "Mesh_12"],
    },
    "thigh_l": {
        "target_name": "Mesh_13",
        "display_name": "Left Thigh",
        "patterns": ["thigh.L", "LeftUpLeg", "Left_Thigh", "Mesh_13"],
    },
    "shin_l": {
        "target_name": "Mesh_14",
        "display_name": "Left Shin",
        "patterns": ["shin.L", "LeftLeg", "Left_Shin", "Mesh_14"],
    },
    "foot_l": {
        "target_name": "Mesh_15",
        "display_name": "Left Foot",
        "patterns": ["foot.L", "LeftFoot", "Left_Foot", "Mesh_15"],
    },
    "thigh_r": {
        "target_name": "Mesh_16",
        "display_name": "Right Thigh",
        "patterns": ["thigh.R", "RightUpLeg", "Right_Thigh", "Mesh_16"],
    },
    "shin_r": {
        "target_name": "Mesh_17",
        "display_name": "Right Shin",
        "patterns": ["shin.R", "RightLeg", "Right_Shin", "Mesh_17"],
    },
    "foot_r": {
        "target_name": "Mesh_18",
        "display_name": "Right Foot",
        "patterns": ["foot.R", "RightFoot", "Right_Foot", "Mesh_18"],
    },
    "torso": {
        "target_name": "Mesh_19",
        "display_name": "Torso",
        "patterns": ["spine", "torso", "chest", "Mesh_19"],
    },
    "upper_arm_r": {
        "target_name": "Mesh_20",
        "display_name": "Right Upper Arm",
        "patterns": ["upper_arm.R", "RightArm", "Right_Upper_Arm", "Mesh_20"],
    },
    "forearm_r": {
        "target_name": "Mesh_21",
        "display_name": "Right Forearm",
        "patterns": ["forearm.R", "RightForeArm", "Right_Forearm", "Mesh_21"],
    },
    "hand_r": {
        "target_name": "Mesh_22",
        "display_name": "Right Hand",
        "patterns": ["hand.R", "RightHand", "Right_Hand", "Mesh_22"],
    },
    "upper_arm_l": {
        "target_name": "Mesh_23",
        "display_name": "Left Upper Arm",
        "patterns": ["upper_arm.L", "LeftArm", "Left_Upper_Arm", "Mesh_23"],
    },
    "forearm_l": {
        "target_name": "Mesh_24",
        "display_name": "Left Forearm",
        "patterns": ["forearm.L", "LeftForeArm", "Left_Forearm", "Mesh_24"],
    },
    "hand_l": {
        "target_name": "Mesh_25",
        "display_name": "Left Hand",
        "patterns": ["hand.L", "LeftHand", "Left_Hand", "Mesh_25"],
    },
    "head": {
        "target_name": "Mesh_26",
        "display_name": "Head",
        "patterns": ["head", "Head", "Mesh_26"],
    },
}


# Cache for bone items to prevent EnumProperty refresh issues
_bone_items_cache = {
    "armature": None,
    "items": [("NONE", "-- None --", "No bone selected")],
}


def get_armature_items(self, context):
    """Get list of armatures in the scene for dropdown."""
    items = [("NONE", "-- Select Armature --", "")]
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            items.append((obj.name, obj.name, f"Armature: {obj.name}"))
    return items


def get_bone_items(self, context):
    """Get list of bones from the selected armature for dropdown with caching."""
    global _bone_items_cache

    settings = context.scene.wadblender_skinned_rename
    armature_name = settings.armature if settings.armature != "NONE" else None

    # Return cached items if armature hasn't changed
    if armature_name == _bone_items_cache["armature"]:
        return _bone_items_cache["items"]

    # Rebuild cache
    items = [("NONE", "-- None --", "No bone selected")]

    if armature_name:
        armature_obj = bpy.data.objects.get(armature_name)
        if armature_obj and armature_obj.type == "ARMATURE":
            for bone in sorted(armature_obj.data.bones, key=lambda b: b.name):
                items.append((bone.name, bone.name, f"Bone: {bone.name}"))

    _bone_items_cache["armature"] = armature_name
    _bone_items_cache["items"] = items

    return items


def invalidate_bone_cache():
    """Invalidate bone items cache when armature selection changes."""
    global _bone_items_cache
    _bone_items_cache["armature"] = None
    _bone_items_cache["items"] = [("NONE", "-- None --", "No bone selected")]


def _on_armature_update(self, context):
    """Callback when armature selection changes."""
    invalidate_bone_cache()


def _find_bone_by_patterns(armature, patterns):
    """Find a bone in armature matching any of the patterns."""
    if not armature or armature.type != "ARMATURE":
        return None

    for bone in armature.data.bones:
        bone_lower = bone.name.lower()
        for pattern in patterns:
            pattern_lower = pattern.lower()
            if pattern_lower in bone_lower or bone.name == pattern:
                return bone.name
    return None


# ============================================================================
# Eyedropper Bone Picker
# ============================================================================

class WadBlenderRenamePickBoneFromSelection(Operator):
    """Set bone mapping from currently selected bone in pose mode."""
    bl_idname = "wadblender.rename_pick_bone_from_selection"
    bl_label = "Pick from Selection"
    bl_description = "Use the currently active bone from the armature"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    bone_slot: StringProperty(
        name="Bone Slot",
        description="Which bone mapping slot to set",
    )

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_skinned_rename
        armature_obj = bpy.data.objects.get(settings.armature) if settings.armature != "NONE" else None
        return (
            armature_obj is not None and
            context.active_object == armature_obj and
            context.mode == "POSE" and
            context.active_pose_bone is not None
        )

    def execute(self, context):
        settings = context.scene.wadblender_skinned_rename
        bone_name = context.active_pose_bone.name

        if self.bone_slot and hasattr(settings, self.bone_slot):
            setattr(settings, self.bone_slot, bone_name)
            self.report({"INFO"}, f"Selected: {bone_name}")
            return {"FINISHED"}

        self.report({"WARNING"}, "Invalid bone slot")
        return {"CANCELLED"}


# ============================================================================
# Settings and Operators
# ============================================================================

class WadBlenderSkinnedRenameSettings(PropertyGroup):
    """Settings for skinned Lara bone renaming."""

    armature: EnumProperty(
        name="Armature",
        description="The armature to rename bones in",
        items=get_armature_items,
        update=_on_armature_update,
    )

    rename_vertex_groups: BoolProperty(
        name="Rename Vertex Groups",
        description="Also rename vertex groups in skinned meshes to match the new bone names",
        default=True,
    )

    # Bone mappings - which source bone maps to which Mesh_XX
    map_hips: EnumProperty(name="Hips → Mesh_12", items=get_bone_items)
    map_thigh_l: EnumProperty(name="Left Thigh → Mesh_13", items=get_bone_items)
    map_shin_l: EnumProperty(name="Left Shin → Mesh_14", items=get_bone_items)
    map_foot_l: EnumProperty(name="Left Foot → Mesh_15", items=get_bone_items)
    map_thigh_r: EnumProperty(name="Right Thigh → Mesh_16", items=get_bone_items)
    map_shin_r: EnumProperty(name="Right Shin → Mesh_17", items=get_bone_items)
    map_foot_r: EnumProperty(name="Right Foot → Mesh_18", items=get_bone_items)
    map_torso: EnumProperty(name="Torso → Mesh_19", items=get_bone_items)
    map_upper_arm_r: EnumProperty(name="Right Upper Arm → Mesh_20", items=get_bone_items)
    map_forearm_r: EnumProperty(name="Right Forearm → Mesh_21", items=get_bone_items)
    map_hand_r: EnumProperty(name="Right Hand → Mesh_22", items=get_bone_items)
    map_upper_arm_l: EnumProperty(name="Left Upper Arm → Mesh_23", items=get_bone_items)
    map_forearm_l: EnumProperty(name="Left Forearm → Mesh_24", items=get_bone_items)
    map_hand_l: EnumProperty(name="Left Hand → Mesh_25", items=get_bone_items)
    map_head: EnumProperty(name="Head → Mesh_26", items=get_bone_items)


class WadBlenderAutoDetectBones(Operator):
    """Auto-detect bone mapping based on common naming conventions."""
    bl_idname = "wadblender.skinned_autodetect"
    bl_label = "Auto-Detect"
    bl_description = "Automatically map bones based on common naming conventions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_skinned_rename
        return settings.armature != "NONE"

    def execute(self, context):
        settings = context.scene.wadblender_skinned_rename
        armature_obj = bpy.data.objects.get(settings.armature)

        if not armature_obj:
            self.report({"WARNING"}, "Armature not found")
            return {"CANCELLED"}

        mapped_count = 0
        for bone_key, bone_info in SKINNED_BONES.items():
            prop_name = f"map_{bone_key}"
            found_bone = _find_bone_by_patterns(armature_obj, bone_info["patterns"])

            if found_bone:
                setattr(settings, prop_name, found_bone)
                mapped_count += 1
            else:
                setattr(settings, prop_name, "NONE")

        self.report({"INFO"}, f"Auto-mapped {mapped_count}/{len(SKINNED_BONES)} bones")
        return {"FINISHED"}


class WadBlenderClearBoneMapping(Operator):
    """Clear all bone mappings."""
    bl_idname = "wadblender.skinned_clear_mapping"
    bl_label = "Clear Mapping"
    bl_description = "Clear all bone mappings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.wadblender_skinned_rename

        for bone_key in SKINNED_BONES.keys():
            prop_name = f"map_{bone_key}"
            setattr(settings, prop_name, "NONE")

        self.report({"INFO"}, "Cleared all bone mappings")
        return {"FINISHED"}


class WadBlenderRenameBones(Operator):
    """Rename bones to Lara's skinned bone names (Mesh_12 to Mesh_26)."""
    bl_idname = "wadblender.skinned_rename_execute"
    bl_label = "Rename Bones"
    bl_description = "Rename the mapped bones to Lara's skinned bone names"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = context.scene.wadblender_skinned_rename
        if settings.armature == "NONE":
            return False
        # Check if at least one mapping exists
        for bone_key in SKINNED_BONES.keys():
            prop_name = f"map_{bone_key}"
            if getattr(settings, prop_name) != "NONE":
                return True
        return False

    def execute(self, context):
        settings = context.scene.wadblender_skinned_rename
        armature_obj = bpy.data.objects.get(settings.armature)

        if not armature_obj:
            self.report({"ERROR"}, "Armature not found")
            return {"CANCELLED"}

        # Build rename mapping
        rename_map = {}  # old_name -> new_name
        for bone_key, bone_info in SKINNED_BONES.items():
            prop_name = f"map_{bone_key}"
            source_bone = getattr(settings, prop_name)
            if source_bone != "NONE":
                target_name = bone_info["target_name"]
                rename_map[source_bone] = target_name

        if not rename_map:
            self.report({"WARNING"}, "No bones mapped for renaming")
            return {"CANCELLED"}

        # Store current mode to restore later
        original_mode = context.mode
        original_active = context.active_object

        # Select and activate the armature
        bpy.context.view_layer.objects.active = armature_obj
        if armature_obj.mode != "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")

        # Rename bones
        renamed_count = 0
        for old_name, new_name in rename_map.items():
            if old_name in armature_obj.data.edit_bones:
                armature_obj.data.edit_bones[old_name].name = new_name
                renamed_count += 1

        bpy.ops.object.mode_set(mode="OBJECT")

        # Rename vertex groups if enabled
        vg_renamed = 0
        if settings.rename_vertex_groups:
            # Find all meshes that use this armature
            for obj in bpy.data.objects:
                if obj.type != "MESH":
                    continue
                # Check if this mesh has an armature modifier pointing to our armature
                uses_armature = False
                for mod in obj.modifiers:
                    if mod.type == "ARMATURE" and mod.object == armature_obj:
                        uses_armature = True
                        break
                # Also check if parented to armature
                if obj.parent == armature_obj:
                    uses_armature = True

                if uses_armature:
                    for old_name, new_name in rename_map.items():
                        if old_name in obj.vertex_groups:
                            obj.vertex_groups[old_name].name = new_name
                            vg_renamed += 1

        # Restore original state
        if original_active:
            bpy.context.view_layer.objects.active = original_active

        # Invalidate cache since bone names changed
        invalidate_bone_cache()

        msg = f"Renamed {renamed_count} bones to skinned names"
        if settings.rename_vertex_groups and vg_renamed > 0:
            msg += f", {vg_renamed} vertex groups updated"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


def _draw_bone_mapping_row(layout, settings, prop_name, target_name):
    """Draw a bone mapping row with dropdown and eyedropper button."""
    row = layout.row(align=True)
    row.prop(settings, prop_name, text=target_name)

    # Eyedropper button - picks from currently selected bone
    op = row.operator("wadblender.rename_pick_bone_from_selection", text="", icon="EYEDROPPER")
    op.bone_slot = prop_name


# ============================================================================
# Panel
# ============================================================================

class WadBlenderSkinnedRenamePanel(Panel):
    """Panel for renaming armature bones to Lara's skinned bone names."""
    bl_label = "Skinned Lara Rename"
    bl_idname = "WADBLENDER_PT_SkinnedRename"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Wad Blender"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.wadblender_skinned_rename

        # Check if armature is selected in pose mode for eyedropper
        armature_obj = bpy.data.objects.get(settings.armature) if settings.armature != "NONE" else None
        can_pick = (
            armature_obj is not None and
            context.active_object == armature_obj and
            context.mode == "POSE" and
            context.active_pose_bone is not None
        )

        # Armature Selection
        box = layout.box()
        box.label(text="Target Armature", icon="ARMATURE_DATA")
        box.prop(settings, "armature", text="")

        if armature_obj:
            bone_count = len(armature_obj.data.bones)
            box.label(text=f"Bones: {bone_count}", icon="BONE_DATA")

        # Bone Mapping
        box = layout.box()
        header = box.row()
        header.label(text="Bone Mapping", icon="BONE_DATA")

        row = box.row(align=True)
        row.operator("wadblender.skinned_autodetect", text="Auto-Detect", icon="VIEWZOOM")
        row.operator("wadblender.skinned_clear_mapping", text="Clear", icon="X")

        # Eyedropper hint
        if armature_obj and context.mode == "POSE":
            if can_pick:
                box.label(text=f"Active: {context.active_pose_bone.name}", icon="CHECKMARK")
            else:
                box.label(text="Select a bone to use eyedropper", icon="INFO")
        elif armature_obj:
            box.label(text="Enter Pose mode for eyedropper", icon="INFO")

        col = box.column(align=True)

        # Root & Spine section
        spine_box = col.box()
        spine_box.label(text="Root & Spine", icon="CON_SPLINEIK")
        spine_col = spine_box.column(align=True)
        _draw_bone_mapping_row(spine_col, settings, "map_hips", "Mesh_12")
        _draw_bone_mapping_row(spine_col, settings, "map_torso", "Mesh_19")
        _draw_bone_mapping_row(spine_col, settings, "map_head", "Mesh_26")

        # Left Leg section
        leg_l_box = col.box()
        leg_l_box.label(text="Left Leg", icon="CON_KINEMATIC")
        leg_l_col = leg_l_box.column(align=True)
        _draw_bone_mapping_row(leg_l_col, settings, "map_thigh_l", "Mesh_13")
        _draw_bone_mapping_row(leg_l_col, settings, "map_shin_l", "Mesh_14")
        _draw_bone_mapping_row(leg_l_col, settings, "map_foot_l", "Mesh_15")

        # Right Leg section
        leg_r_box = col.box()
        leg_r_box.label(text="Right Leg", icon="CON_KINEMATIC")
        leg_r_col = leg_r_box.column(align=True)
        _draw_bone_mapping_row(leg_r_col, settings, "map_thigh_r", "Mesh_16")
        _draw_bone_mapping_row(leg_r_col, settings, "map_shin_r", "Mesh_17")
        _draw_bone_mapping_row(leg_r_col, settings, "map_foot_r", "Mesh_18")

        # Right Arm section
        arm_r_box = col.box()
        arm_r_box.label(text="Right Arm", icon="CON_ARMATURE")
        arm_r_col = arm_r_box.column(align=True)
        _draw_bone_mapping_row(arm_r_col, settings, "map_upper_arm_r", "Mesh_20")
        _draw_bone_mapping_row(arm_r_col, settings, "map_forearm_r", "Mesh_21")
        _draw_bone_mapping_row(arm_r_col, settings, "map_hand_r", "Mesh_22")

        # Left Arm section
        arm_l_box = col.box()
        arm_l_box.label(text="Left Arm", icon="CON_ARMATURE")
        arm_l_col = arm_l_box.column(align=True)
        _draw_bone_mapping_row(arm_l_col, settings, "map_upper_arm_l", "Mesh_23")
        _draw_bone_mapping_row(arm_l_col, settings, "map_forearm_l", "Mesh_24")
        _draw_bone_mapping_row(arm_l_col, settings, "map_hand_l", "Mesh_25")

        # Options
        box = layout.box()
        box.label(text="Options", icon="PREFERENCES")
        box.prop(settings, "rename_vertex_groups")

        # Execute button
        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("wadblender.skinned_rename_execute", text="Rename Bones", icon="BONE_DATA")


# ============================================================================
# Registration
# ============================================================================

def register():
    bpy.utils.register_class(WadBlenderSkinnedRenameSettings)
    bpy.utils.register_class(WadBlenderRenamePickBoneFromSelection)
    bpy.utils.register_class(WadBlenderAutoDetectBones)
    bpy.utils.register_class(WadBlenderClearBoneMapping)
    bpy.utils.register_class(WadBlenderRenameBones)
    bpy.utils.register_class(WadBlenderSkinnedRenamePanel)

    bpy.types.Scene.wadblender_skinned_rename = PointerProperty(type=WadBlenderSkinnedRenameSettings)


def unregister():
    bpy.utils.unregister_class(WadBlenderSkinnedRenamePanel)
    bpy.utils.unregister_class(WadBlenderRenameBones)
    bpy.utils.unregister_class(WadBlenderClearBoneMapping)
    bpy.utils.unregister_class(WadBlenderAutoDetectBones)
    bpy.utils.unregister_class(WadBlenderRenamePickBoneFromSelection)
    bpy.utils.unregister_class(WadBlenderSkinnedRenameSettings)

    del bpy.types.Scene.wadblender_skinned_rename
