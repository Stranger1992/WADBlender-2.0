"""Test WAD2 to model conversion"""
import sys
from wad import read_wad2

class Options:
    texture_pages = False

# Test WAD2 file
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

try:
    print(f'Loading and converting WAD2 file: {wad2_path}')

    with open(wad2_path, 'rb') as f:
        loader = read_wad2.Wad2Loader()
        wad_model = loader.load_from_stream(f, Options())

    print(f'\n[OK] Successfully converted WAD2 file to model')
    print(f'  Version: {wad_model.version}')
    print(f'  Map dimensions: {wad_model.mapwidth}x{wad_model.mapheight}')
    print(f'  Statics: {len(wad_model.statics)}')
    print(f'  Moveables: {len(wad_model.movables)}')

    # Show statics details
    if wad_model.statics:
        print(f'\n  === STATICS (converted to model) ===')
        for static in wad_model.statics[:3]:
            print(f'  Static {static.idx}:')
            print(f'    Vertices: {len(static.mesh.vertices)}')
            print(f'    Polygons: {len(static.mesh.polygons)}')
            print(f'    Normals: {len(static.mesh.normals)}')
            print(f'    Bounding sphere: center={static.mesh.boundingSphereCenter}, radius={static.mesh.boundingSphereRadius}')

    # Show moveables details
    if wad_model.movables:
        print(f'\n  === MOVEABLES (converted to model) ===')
        for movable in wad_model.movables[:2]:
            print(f'  Moveable {movable.idx}:')
            print(f'    Meshes: {len(movable.meshes)}')
            print(f'    Joints: {len(movable.joints)}')
            print(f'    Animations: {len(movable.animations)}')
            if movable.meshes:
                first_mesh = movable.meshes[0]
                print(f'    First mesh: {len(first_mesh.vertices)} vertices, {len(first_mesh.polygons)} polygons')

except Exception as e:
    print(f'[ERROR] Error converting WAD2: {e}')
    import traceback
    traceback.print_exc()
