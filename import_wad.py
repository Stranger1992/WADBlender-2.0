import os
import tempfile

import bpy
from collections import Counter
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty

from . import lara, movables, statics, objects, lara_rigless, lara_skinned
from .wad import read, read_wad2, preview
from .create_materials import generateNodesSetup, createPageMaterial

# Constants
TEXTURE_PAGE_SIZE = 256
DEFAULT_SCALE = 512
WAD_EXTENSIONS = {'.wad', '.WAD'}
WAD2_EXTENSIONS = {'.wad2', '.WAD2'}


def check_requirements():
    try:
        import numpy
        import PIL
        return True
    except ImportError as e:
        return False


def rename_dups(obj_names):
    """Add obj numeric idx to name when it appears multiple times in catalog"""
    names = Counter(obj_names.values())
    for name, cnt in names.items():
        if cnt > 1:
            for idx in obj_names:
                if obj_names[idx] == name:
                    obj_names[idx] += idx


class ImportWADContext:
    update_single_obj_chkbox = False
    selected_obj = 'None'

    last_selected_file = ''
    last_objects_list = []
    cur_selected_file = ''
    has_numpy = check_requirements()
    mov_names = {}
    static_names = {}
    anim_names = {}
    state_names = {}
    for game in ['TR1', 'TR2', 'TR3', 'TR4', 'TR5', 'TR5Main']:
        mov_names[game], static_names[game], \
        anim_names[game], state_names[game] = objects.get_names(game)
        rename_dups(mov_names[game])
        rename_dups(static_names[game])


    game = 'TR4'

    @classmethod
    def set_game(cls, game):
        if cls.game != game:
            cls.game = game
            cls.last_selected_file = ''
            cls.last_objects_list.clear()


class ImportWAD(Operator, ImportHelper):
    """Load a TRLE WAD file"""
    bl_idname = "wadblender.import_wad"
    bl_label = "Import WAD"

    filename_ext = ".wad"

    filter_glob: StringProperty(
        default="*.wad;*.WAD;*.wad2;*.WAD2",
        options={'HIDDEN'},
        maxlen=255,
    )

    # if user has choosen a single object instad of batch import
    single_object: BoolProperty(default=False)

    batch_import: EnumProperty(
        name="Import",
        description="",
        items=(
            ('OPT_LARA', "Lara Full Model", "Import all Lara objects"),
            ('OPT_OUTFIT', "Lara's Outfit", "Import only LARA_SKIN and LARA_SKIN_JOINTS meshes"),
            ('OPT_OUTFIT_SKINNED', "Lara's Outfit (Skinned)", "Import Lara's outfit with skinning/armature for TEN"),
            ('OPT_MOVABLES', "All Movables", "Import all Movable objects"),
            ('OPT_STATICS', "All Statics", "Import all Static objects"),
            ('OPT_EVERYTHING', "Everything", "Import Everything"),
        ),
        default='OPT_EVERYTHING',
    )

    batch_import_nolara: EnumProperty(
        name="Import",
        description="",
        items=(
            ('OPT_MOVABLES', "All Movables", "Import all Movable objects"),
            ('OPT_STATICS', "All Statics", "Import all Static objects"),
            ('OPT_EVERYTHING', "Everything", "Import Everything"),
        ),
        default='OPT_EVERYTHING',
    )

    texture_type: EnumProperty(
        name="Import mode",
        description="",
        items=(
            ('OPT_OBJECT', "One texture per object",
             "Each object has its own material with its own textures only."),
            ('OPT_PAGES', "Texture Pages",
             "256x256 texture pages are shared across all objects"),
            ('OPT_FULL', "Full Texture Map",
             "The entire wad texture map is shared across all objects"),
        ),
        default='OPT_OBJECT',
    )

    texture_type_nolib: EnumProperty(
        name="Import mode",
        description="",
        items=(
            ('OPT_FULL', "Full Texture Map",
             "The entire wad texture map is shared across all objects"),
        ),
        default='OPT_FULL',
    )

    # WAD2-specific texture mode
    texture_type_wad2: EnumProperty(
        name="Import mode",
        description="",
        items=(
            ('OPT_PACKED', "Packed (one texture per object)",
             "Each object gets a single packed texture containing only its used regions."),
            ('OPT_PAGES', "Texture Pages",
             "Individual texture pages are shared across all objects (original WAD2 textures)"),
        ),
        default='OPT_PACKED',
    )

    texture_padding: IntProperty(
        name="Texture Padding",
        description="Pixels of padding and bleed between packed texture regions. Higher values prevent seam artifacts in mipmaps and normal maps",
        default=4,
        min=0,
        max=8
    )

    scale_setting: IntProperty(
        name="Scale",
        description="Dividing by 512, one TRLE click becomes 0.5 meters",
        default=DEFAULT_SCALE,
        min=1,
        max=100000
    )

    import_anims: BoolProperty(
        name="Import Animations",
        description="Import Lara and Movables Animations",
        default=True,
    )

    discard_junk: BoolProperty(
        name="Discard Placeholders",
        description="Do not load triggers, particle emitters, AI, etc",
        default=True,
    )

    texture_pages: BoolProperty(
        name="Texture pages",
        description="Split texture map in 256x256 pages",
        default=False,
    )

    export_fbx: BoolProperty(
        name="Objects and Animations (FBX)",
        description="Export objects and animations in FBX format",
        default=False,
    )

    export_obj: BoolProperty(
        name="Objects (OBJ)",
        description="Export objects and animations in OBJ format",
        default=False,
    )

    export_json: BoolProperty(
        name="Additional Data (JSON)",
        description="Export additional wad data in json format",
        default=False,
    )

    flip_normals: BoolProperty(
        name="Flip Normals",
        description="TRLE and Blender normals point to opposite directions",
        default=True,
    )

    one_material_per_object: BoolProperty(
        name="One material per object",
        description="If checked, each object has its own texture map and other textures are discarded",
        default=False,
    )

    wad_format: EnumProperty(
        name="WAD Format",
        description="Choose WAD format type",
        items=(
            ('AUTO', "Auto-detect", "Detect format from file extension (.wad or .wad2)"),
            ('WAD', "Classic WAD", "Import as classic WAD format (opcode-based bones)"),
            ('WAD2', "WAD2", "Import as WAD2 format (parent-indexed bones)"),
        ),
        default='AUTO',
    )

    game: EnumProperty(
        name="Game slot names",
        description="",
        items=(
            ('TR1', "TR1", ""),
            ('TR2', "TR2", ""),
            ('TR3', "TR3", ""),
            ('TR4', "TR4", ""),
            ('TR5', "TR5", ""),
            ('TR5Main', "TR5Main", ""),
        ),
        default='TR4',
    )

    anims_names_opt: EnumProperty(
        name="Animation names",
        description="",
        items=[
            ('OPT_SAMEASOBJECTS', "Same as SLOT names", ""),
            ('TR1', "TR1", ""),
            ('TR2', "TR2", ""),
            ('TR3', "TR3", ""),
            ('TR4', "TR4", ""),
            ('TR5', "TR5", ""),
            ('TR5Main', "TR5Main", ""),
        ][::-1],
        default='OPT_SAMEASOBJECTS',
    )

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text='WAD Blender', icon="BLENDER")
        box = layout.box()
        box.label(text="Settings", icon="SETTINGS")

        row = box.row(align=True)
        if self.game in {'TR1', 'TR2', 'TR3'}:
            row.prop(self, "batch_import_nolara")
        else:
            row.prop(self, "batch_import")

        row = box.row(align=True)
        row.prop(self, "discard_junk")

        row = box.label(text="or select file and")
        row = box.row()
        ImportWADContext.cur_selected_file = self.filepath
        row.operator("wadblender.popup_search")
        if ImportWADContext.selected_obj == 'None':
            self.single_object = False
        elif ImportWADContext.update_single_obj_chkbox:
            self.single_object = True
            ImportWADContext.update_single_obj_chkbox = False

        row.prop(self, "single_object", text=ImportWADContext.selected_obj)

        row = box.label(text='Materials:')

        col = box.column()

        # Show appropriate texture mode selector based on file type
        is_wad2 = self.filepath.lower().endswith('.wad2')
        if is_wad2:
            # Always show WAD2 selector - libs are checked at import time
            col.prop(self, "texture_type_wad2", expand=True)
            if self.texture_type_wad2 == 'OPT_PACKED':
                row = box.row(align=True)
                row.prop(self, "texture_padding")
        elif ImportWADContext.has_numpy:
            col.prop(self, "texture_type", expand=True)
        else:
            col.prop(self, "texture_type_nolib", expand=True)

        if not ImportWADContext.has_numpy:
            row = layout.row()
            row.operator("wadblender.install_requirements", icon='COLORSET_05_VEC')

        row = box.row(align=True)
        row.prop(self, "import_anims")

        row = box.split(factor=0.5, align=True)
        row.label(text="WAD Format")
        row.prop(self, "wad_format", text="")

        row = box.split(factor=0.5, align=True)
        row.label(text="Game Slot Names")
        row.prop(self, "game", text="")
        ImportWADContext.set_game(self.game)

        row = box.row()
        row.prop(self, "scale_setting")

        row = layout.box()
        row.label(text="Batch Export:", icon="EXPORT")
        row.prop(self, "export_fbx")
        row.prop(self, "export_obj")
        row.prop(self, "export_json")

        box = layout.box()
        box.label(text="Advanced", icon="SETTINGS")
        box.prop(self, "flip_normals")
        box.label(text="Animation names")
        box.prop(self, "anims_names_opt", text="")

    def _create_options(self):
        """Create and configure import options object."""
        class ImportOptions:
            pass

        options = ImportOptions()
        options.filepath = self.filepath
        options.wadname = os.path.basename(self.filepath)[:-4]
        options.scale = int(self.scale_setting)
        options.import_anims = self.import_anims
        options.discard_junk = self.discard_junk
        options.export_json = self.export_json
        options.export_fbx = self.export_fbx
        options.export_obj = self.export_obj
        options.single_object = self.single_object
        options.object = ImportWADContext.selected_obj
        options.flip_normals = self.flip_normals
        options.path = tempfile.gettempdir() + os.sep
        options.original_path, _ = os.path.split(options.filepath)

        # Set name mappings from context
        options.mov_names = ImportWADContext.mov_names[ImportWADContext.game]
        options.static_names = ImportWADContext.static_names[ImportWADContext.game]
        options.state_names = ImportWADContext.state_names[ImportWADContext.game]
        if self.anims_names_opt == 'OPT_SAMEASOBJECTS':
            options.anim_names = ImportWADContext.anim_names[ImportWADContext.game]
        else:
            options.anim_names = ImportWADContext.anim_names[self.anims_names_opt]

        # Detect WAD format
        if self.wad_format == 'AUTO':
            is_wad2 = options.filepath.lower().endswith('.wad2')
        elif self.wad_format == 'WAD2':
            is_wad2 = True
        else:
            is_wad2 = False

        options.is_wad2 = is_wad2

        # Set texture options
        if is_wad2:
            # Check numpy availability at runtime (the class-level check
            # can be stale if libraries were installed after addon load).
            # PIL is optional - we fall back to Blender's image API if missing.
            try:
                import numpy
                has_numpy_rt = True
            except ImportError:
                has_numpy_rt = False

            if has_numpy_rt:
                options.wad2_pack_textures = self.texture_type_wad2 == 'OPT_PACKED'
                options.texture_padding = self.texture_padding
                options.texture_pages = True  # Always need pages loaded for WAD2
                options.one_material_per_object = False
            else:
                options.wad2_pack_textures = False
                options.texture_pages = True
                options.one_material_per_object = False
            print(f"[WAD2 Options] wad2_pack_textures={options.wad2_pack_textures}, "
                  f"texture_type_wad2={self.texture_type_wad2}, "
                  f"has_numpy_rt={has_numpy_rt}")
        else:
            options.wad2_pack_textures = False
            if ImportWADContext.has_numpy:
                options.one_material_per_object = self.texture_type == 'OPT_OBJECT'
                options.texture_pages = self.texture_type == 'OPT_PAGES'
            else:
                options.one_material_per_object = False
                options.texture_pages = False

        return options

    def _load_wad_file(self, options):
        """Load WAD or WAD2 file and return wad object."""
        with open(options.filepath, "rb") as f:
            if options.is_wad2:
                loader = read_wad2.Wad2Loader()
                return loader.load_from_stream(f, options)
            else:
                return read.readWAD(f, options)

    def _setup_materials(self, context, wad, options):
        """Create or load materials for the WAD textures."""
        materials = []

        if options.is_wad2 and options.wad2_pack_textures:
            # WAD2 packed mode: we still need to save the page textures
            # so the packer can read them, but we don't create per-page
            # materials here. Instead, pack_wad2_textures() in
            # create_materials.py handles material creation per-object.
            # We just need to ensure the page data is available on `wad`.
            #
            # Return empty materials list — pack_wad2_textures() will
            # create the material when called per-object.
            return materials

        if options.texture_pages:
            first_page_name = f'{options.wadname}_PAGE0'

            if first_page_name not in bpy.data.materials:
                # Create new materials
                for i, page in enumerate(wad.textureMaps):
                    name = f'{options.wadname}_PAGE{i}'
                    # Derive image dimensions from pixel data
                    pixel_count = len(page) // 4
                    if pixel_count == wad.mapwidth * wad.mapheight:
                        w, h = wad.mapwidth, wad.mapheight
                    elif pixel_count > 0:
                        # Try square, then fall back to width=pixel_count, height=1
                        import math
                        sq = int(math.isqrt(pixel_count))
                        if sq * sq == pixel_count:
                            w = h = sq
                        else:
                            w, h = pixel_count, 1
                    else:
                        w = h = TEXTURE_PAGE_SIZE
                    print(f"[WAD Import] Page {i}: {len(page)} floats, {pixel_count} pixels -> {w}x{h} image")
                    uvmap = bpy.data.images.new(name, w, h, alpha=True)
                    uvmap.pixels = page
                    texture_path = options.path + name + ".png"
                    self._save_texture(uvmap, texture_path)
                    material = createPageMaterial(texture_path, context)
                    materials.append(material)
            else:
                # Load existing materials
                for i, _ in enumerate(wad.textureMaps):
                    name = f'{options.wadname}_PAGE{i}'
                    materials.append(bpy.data.materials[name])
        else:
            # Generate full texture map image
            w, h = wad.mapwidth, wad.mapheight
            uvmap = bpy.data.images.new(options.wadname, w, h, alpha=True)
            uvmap.pixels = wad.textureMap
            texture_path = options.path + options.wadname + ".png"
            self._save_texture(uvmap, texture_path)

            if not options.one_material_per_object:
                materials = [generateNodesSetup(options.wadname, texture_path)]

        return materials

    def _save_texture(self, uvmap, texture_path):
        """Save texture to disk with error handling."""
        try:
            uvmap.filepath_raw = texture_path
            uvmap.file_format = 'PNG'
            uvmap.save()
        except (RuntimeError, PermissionError) as e:
            self.report({'WARNING'}, f"Could not save texture to {texture_path}: {str(e)}")

    def _import_objects(self, context, materials, wad, options):
        """Import objects based on user selection."""
        if options.single_object:
            self._import_single_object(context, materials, wad, options)
        else:
            self._import_batch(context, materials, wad, options)

    def _import_single_object(self, context, materials, wad, options):
        """Import a single selected object."""
        found = False
        for idx, name in options.mov_names.items():
            if options.object == name:
                movables.main(context, materials, wad, options)
                found = True
                break
        else:
            if options.object.startswith('movable'):
                movables.main(context, materials, wad, options)
                found = True

        if not found:
            statics.main(context, materials, wad, options)

    def _import_batch(self, context, materials, wad, options):
        """Import multiple objects based on batch selection."""
        import_type = self.batch_import_nolara if self.game in {'TR1', 'TR2', 'TR3'} else self.batch_import

        if import_type == 'OPT_LARA':
            lara.main(context, materials, wad, options)
        elif import_type == 'OPT_OUTFIT':
            lara_rigless.main(context, materials, wad, options)
        elif import_type == 'OPT_OUTFIT_SKINNED':
            lara_skinned.main(context, materials, wad, options)
        elif import_type == 'OPT_MOVABLES':
            movables.main(context, materials, wad, options)
        elif import_type == 'OPT_STATICS':
            statics.main(context, materials, wad, options)
        else:
            # Import everything
            if self.game not in {'TR1', 'TR2', 'TR3'} and not options.is_wad2:
                lara.main(context, materials, wad, options)
                bpy.ops.object.select_all(action='DESELECT')

            movables.main(context, materials, wad, options)
            bpy.ops.object.select_all(action='DESELECT')
            statics.main(context, materials, wad, options)

        bpy.ops.object.select_all(action='DESELECT')

    def execute(self, context):
        options = self._create_options()

        # Apply WAD2-specific settings (for non-packed mode)
        if options.is_wad2 and not options.wad2_pack_textures:
            options.flip_normals = True

        # Always flip normals for WAD2
        if options.is_wad2:
            options.flip_normals = False

        wad = self._load_wad_file(options)

        # Store wad on options so pack_wad2_textures can access texture data
        if options.is_wad2 and options.wad2_pack_textures:
            options.wad = wad

        materials = self._setup_materials(context, wad, options)
        self._import_objects(context, materials, wad, options)

        # Store the import path for later export
        context.scene.wad_import_path = options.filepath

        ImportWADContext.last_selected_file = 'None'
        ImportWADContext.last_objects_list.clear()
        return {"FINISHED"}


# menu entry
def menu_func_import(self, context):
    self.layout.operator(ImportWAD.bl_idname, text="TRLE WAD file (.wad)")


def _get_file_extension(filepath):
    """Get lowercase file extension."""
    return os.path.splitext(filepath)[1].lower()


def _clear_preview_state():
    """Reset preview state to defaults."""
    ImportWADContext.last_objects_list.clear()
    ImportWADContext.selected_obj = 'None'


def item_cb(self, context):
    """Populates popup search box with objects from selected WAD file."""
    filepath = ImportWADContext.cur_selected_file

    if filepath == ImportWADContext.last_selected_file:
        return [(o, o, "") for o in ImportWADContext.last_objects_list]

    ImportWADContext.last_selected_file = filepath
    _clear_preview_state()

    if not os.path.exists(filepath):
        return []

    ext = _get_file_extension(filepath)

    try:
        with open(filepath, "rb") as f:
            if ext == '.wad':
                game = ImportWADContext.game
                mov_list, static_list = preview.preview(
                    f,
                    ImportWADContext.mov_names[game],
                    ImportWADContext.static_names[game]
                )
                ImportWADContext.last_objects_list.extend(mov_list + static_list)
            elif ext == '.wad2':
                mov_list, static_list = preview.preview_wad2(f)
                ImportWADContext.last_objects_list.extend(mov_list + static_list)
    except Exception:
        _clear_preview_state()

    return [(o, o, "") for o in ImportWADContext.last_objects_list]


class PopUpSearch(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "wadblender.popup_search"
    bl_label = "Choose Object"
    bl_property = "objs_enum"

    objs_enum: bpy.props.EnumProperty(items=item_cb)

    def execute(self, context):
        ImportWADContext.update_single_obj_chkbox = True
        ImportWADContext.selected_obj = self.objs_enum
        context.area.tag_redraw()
        return {'FINISHED'}

    def invoke(self, context, event):
        wm = context.window_manager
        wm.invoke_search_popup(self)
        return {'FINISHED'}


class InstallRequirements(bpy.types.Operator):
    bl_idname = "wadblender.install_requirements"
    bl_label = "Install libraries"
    bl_description = "Install Numpy and PIL python libraries to enable additional texture mappings and Sprytile compatibility"

    def execute(self, context):
        import subprocess
        import sys

        # path to python.exe
        python_exe = os.path.join(sys.prefix, 'bin', 'python.exe')

        # upgrade pip
        subprocess.call([python_exe, "-m", "ensurepip"])
        subprocess.call(
            [python_exe, "-m", "pip", "install", "--upgrade", "pip"]
        )

        # install required packages
        subprocess.call([python_exe, "-m", "pip", "install", "numpy"])
        subprocess.call([python_exe, "-m", "pip", "install", "pillow"])
        ImportWADContext.has_numpy = check_requirements()

        return{'FINISHED'}


def register():
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.utils.register_class(ImportWAD)
    bpy.utils.register_class(PopUpSearch)
    bpy.utils.register_class(InstallRequirements)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(ImportWAD)
    bpy.utils.unregister_class(PopUpSearch)
    bpy.utils.unregister_class(InstallRequirements)
