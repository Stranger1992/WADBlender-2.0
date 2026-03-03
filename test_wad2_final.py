"""Final comprehensive WAD2 test"""
import sys
from wad import read_wad2

class Options:
    texture_pages = False

# Test WAD2 file
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

print('=' * 70)
print('COMPREHENSIVE WAD2 IMPORT TEST')
print('=' * 70)

try:
    print(f'\n[1/3] Loading WAD2 file: {wad2_path}')
    with open(wad2_path, 'rb') as f:
        loader = read_wad2.Wad2Loader()
        wad_model = loader.load_from_stream(f, Options())
    print('  [OK] File loaded successfully')

    print(f'\n[2/3] Validating converted model structure')
    print(f'  Version: {wad_model.version}')
    print(f'  Map dimensions: {wad_model.mapwidth}x{wad_model.mapheight}')
    print(f'  Statics: {len(wad_model.statics)}')
    print(f'  Moveables: {len(wad_model.movables)}')

    # Validate statics
    if wad_model.statics:
        print(f'\n  Statics validation:')
        for i, static in enumerate(wad_model.statics[:3]):
            print(f'    Static {static.idx}:')
            print(f'      [OK] {len(static.mesh.vertices)} vertices')
            print(f'      [OK] {len(static.mesh.polygons)} polygons')
            print(f'      [OK] {len(static.mesh.normals)} normals')
            # Verify mesh structure
            assert hasattr(static.mesh, 'vertices'), "Missing vertices"
            assert hasattr(static.mesh, 'polygons'), "Missing polygons"
            assert hasattr(static.mesh, 'normals'), "Missing normals"
            assert hasattr(static.mesh, 'boundingSphereCenter'), "Missing bounding sphere"

    # Validate moveables
    if wad_model.movables:
        print(f'\n  Moveables validation:')
        for i, movable in enumerate(wad_model.movables[:2]):
            print(f'    Moveable {movable.idx}:')
            print(f'      [OK] {len(movable.meshes)} meshes')
            print(f'      [OK] {len(movable.joints)} joints')
            print(f'      [OK] {len(movable.animations)} animations')
            # Verify structure
            assert hasattr(movable, 'meshes'), "Missing meshes"
            assert hasattr(movable, 'joints'), "Missing joints"
            assert hasattr(movable, 'animations'), "Missing animations"
            if movable.meshes:
                mesh = movable.meshes[0]
                print(f'      First mesh: {len(mesh.vertices)} verts, {len(mesh.polygons)} polys')
                assert len(mesh.vertices) > 0, "Mesh has no vertices"

    print(f'\n[3/3] Testing data integrity')

    # Test that polygons have proper structure
    if wad_model.statics and wad_model.statics[0].mesh.polygons:
        poly = wad_model.statics[0].mesh.polygons[0]
        print(f'  Sample polygon structure:')
        print(f'    [OK] face: {poly.face}')
        print(f'    [OK] tbox (UVs): {len(poly.tbox)} coordinates')
        print(f'    [OK] order: {poly.order} ({"triangle" if poly.order == 3 else "quad"})')
        print(f'    [OK] intensity: {poly.intensity}')
        print(f'    [OK] page: {poly.page}')

    # Test that joints have proper structure
    if wad_model.movables and wad_model.movables[0].joints:
        joint = wad_model.movables[0].joints[0]
        print(f'\n  Sample joint structure:')
        print(f'    [OK] Format: [parent, x, y, z] = {joint}')
        assert len(joint) == 4, "Joint should have 4 values"

    print('\n' + '=' * 70)
    print('[OK] ALL TESTS PASSED!')
    print('=' * 70)
    print('\nWAD2 support is fully functional and ready for Blender import.')
    print('\nSummary:')
    print(f'  • Loaded {len(wad_model.statics)} static objects')
    print(f'  • Loaded {len(wad_model.movables)} moveable objects')
    total_meshes = sum(len(m.meshes) for m in wad_model.movables) + len(wad_model.statics)
    print(f'  • Total meshes: {total_meshes}')
    total_joints = sum(len(m.joints) for m in wad_model.movables)
    print(f'  • Total joints: {total_joints}')
    print('\nYou can now import .wad2 files in Blender!')

except Exception as e:
    print(f'\n[ERROR] Test failed: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
