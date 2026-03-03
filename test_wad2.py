import sys
from wad import read_wad2

class Options:
    texture_pages = False

# Test WAD2 file
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

try:
    loader = read_wad2.Wad2Loader()
    print(f'Loading WAD2 file: {wad2_path}')

    with open(wad2_path, 'rb') as f:
        # Verify magic
        magic = f.read(4)
        print(f'Magic bytes: {magic}')
        if magic != b'WAD2':
            print(f'[ERROR] Invalid magic number')
            sys.exit(1)
        f.seek(0)

        # Load the file
        wad = loader.load_from_stream(f, Options())

    print(f'[OK] Successfully loaded WAD2 file')
    print(f'  Version: {loader.version}')
    print(f'  Sound system: {loader.sound_system}')
    print(f'  Textures: {len(loader.textures)}')
    print(f'  Meshes: {len(loader.meshes)}')
    print(f'  Moveables: {len(loader.moveables)}')
    print(f'  Statics: {len(loader.statics)}')

    if loader.textures:
        first_tex = loader.textures[next(iter(loader.textures))]
        tex_name = first_tex.get("name", "unnamed")
        # Handle non-ASCII characters in texture name
        tex_name_safe = tex_name.encode('ascii', errors='replace').decode('ascii')
        print(f'  First texture: {tex_name_safe} ({first_tex["width"]}x{first_tex["height"]})')

    if loader.meshes:
        first_mesh = loader.meshes[next(iter(loader.meshes))]
        print(f'  First mesh: {len(first_mesh.get("positions", []))} vertices')

    # Show moveables details
    if loader.moveables:
        print(f'\n  === MOVEABLES DETAILS ===')
        for mov_id, mov in list(loader.moveables.items())[:3]:  # Show first 3
            print(f'  Moveable {mov_id}:')
            print(f'    Embedded meshes: {len(mov["meshes"])}')
            if mov["meshes"] and isinstance(mov["meshes"][0], dict):
                # Embedded mesh objects
                first_mesh = mov["meshes"][0]
                mesh_name = first_mesh.get("name", "unnamed")
                mesh_name_safe = mesh_name.encode('ascii', errors='replace').decode('ascii')
                print(f'    First mesh: {mesh_name_safe}')
                print(f'      Vertices: {len(first_mesh.get("positions", []))}')
                print(f'      Triangles: {len(first_mesh.get("triangles", []))}')
                print(f'      Quads: {len(first_mesh.get("quads", []))}')
            print(f'    Bones: {len(mov["bones"])}')
            print(f'    Animations: {len(mov["animations"])}')

    # Show statics details
    if loader.statics:
        print(f'\n  === STATICS DETAILS ===')
        for static_id, static in list(loader.statics.items())[:3]:  # Show first 3
            print(f'  Static {static_id}:')
            if isinstance(static['mesh'], dict):
                # Embedded mesh object
                mesh = static['mesh']
                mesh_name = mesh.get("name", "unnamed")
                mesh_name_safe = mesh_name.encode('ascii', errors='replace').decode('ascii')
                print(f'    Mesh: {mesh_name_safe}')
                print(f'      Vertices: {len(mesh.get("positions", []))}')
                print(f'      Triangles: {len(mesh.get("triangles", []))}')
                print(f'      Quads: {len(mesh.get("quads", []))}')
            else:
                # Mesh index reference
                print(f'    Mesh index: {static["mesh"]}')
            if static.get('visibility_box'):
                print(f'    Visibility box: present')
            if static.get('collision_box'):
                print(f'    Collision box: present')

except Exception as e:
    print(f'[ERROR] Error loading WAD2: {e}')
    import traceback
    traceback.print_exc()
