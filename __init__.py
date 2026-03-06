# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
from . import developer_utils, import_wad, export_wad, export_anim, import_anim, import_mixamo, export_trw, object_panel, shine_panel, ik_baker, retarget, skinned_lara_rename

from .KeemapRetargetingAddon import (KeeMapBoneList, KeeMapBoneOperators,
                                     KeeMapBoneSettings, KeeMapPanels,
                                     KeeMapSettings)


bl_info = {
    "name": "WAD Blender 2.0",
    "description": "Import/Export Tomb Raider WAD and WAD2 files and animations into Blender",
    "author": "JonnyvdS, Stranger1992",
    "version": (2, 0, 0),
    "blender": (5, 0, 1),
    "location": "import.wad",
    "warning": "This addon is still in development.",
    "wiki_url": "",
    "category": "Import-Export"}


developer_utils.setup_addon_modules(__path__, __name__, "bpy" in locals())

def register():
    import_wad.register()
    export_wad.register()
    import_mixamo.register()
    import_anim.register()
    export_anim.register()
    export_trw.register()
    object_panel.register()
    shine_panel.register()
    ik_baker.register()
    retarget.register()
    skinned_lara_rename.register()

    KeeMapBoneList.register()
    KeeMapBoneOperators.register()
    KeeMapBoneSettings.register()
    KeeMapPanels.register()
    KeeMapSettings.register()


def unregister():
    import_wad.unregister()
    export_wad.unregister()
    import_mixamo.unregister()
    import_anim.unregister()
    export_anim.unregister()
    export_trw.unregister()
    object_panel.unregister()
    shine_panel.unregister()
    ik_baker.unregister()
    retarget.unregister()
    skinned_lara_rename.unregister()

    KeeMapBoneList.unregister()
    KeeMapBoneOperators.unregister()
    KeeMapBoneSettings.unregister()
    KeeMapPanels.unregister()
    KeeMapSettings.unregister()


if __name__ == "__main__":
    register()

    # test call
    bpy.ops.import_wad.objects('INVOKE_DEFAULT')
