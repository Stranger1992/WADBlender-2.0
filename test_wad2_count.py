"""Test WAD2 moveable count with detailed debugging"""
import sys
from wad import read_wad2

class Options:
    texture_pages = False

# Test WAD2 file
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

# Patch the loader to add debug output
original_read_moveables = read_wad2.Wad2Loader.read_moveables

def debug_read_moveables(self, reader, stream):
    """Read moveable objects with debug output"""
    moveable_index = 0
    print(f'[DEBUG] Starting to read moveables...')

    while True:
        pos_before = stream.tell()
        chunk_id = reader.read_chunk_start()
        print(f'[DEBUG] Moveable loop iteration {moveable_index}, pos=0x{pos_before:08x}, chunk_id={chunk_id}')

        if chunk_id is None or chunk_id != read_wad2.wad2_chunks.ChunkId.Moveable:
            if chunk_id is not None:
                print(f'[DEBUG] Got non-Moveable chunk: {chunk_id}, ending moveable reading')
                reader.read_chunk_end()
            else:
                print(f'[DEBUG] Got None chunk_id, ending moveable reading')
            break

        # Read moveable ID
        moveable_id = read_wad2.read_leb128_uint(stream)
        print(f'[DEBUG] Reading moveable {moveable_index}, ID={moveable_id}')

        moveable = {
            'id': moveable_id,
            'meshes': [],
            'bones': [],
            'animations': []
        }

        # Read moveable sub-chunks
        sub_count = 0
        while True:
            sub_pos = stream.tell()
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                print(f'[DEBUG]   End of moveable sub-chunks (read {sub_count} sub-chunks)')
                break

            sub_name = sub_id.decode('ascii', errors='replace') if sub_id else '(none)'
            # Encode to ASCII for safe printing
            sub_name_safe = sub_name.encode('ascii', errors='replace').decode('ascii')
            print(f'[DEBUG]   Sub-chunk [{sub_count}]: {sub_name_safe} at 0x{sub_pos:08x}')
            sub_count += 1

            if sub_id == read_wad2.wad2_chunks.ChunkId.Mesh:
                mesh = self.read_single_mesh(reader, stream)
                moveable['meshes'].append(mesh)
                mesh_name = mesh.get("name", "unnamed")
                mesh_name_safe = mesh_name.encode('ascii', errors='replace').decode('ascii')
                print(f'[DEBUG]     Mesh: {mesh_name_safe}, {len(mesh.get("positions", []))} vertices')
            elif sub_id == read_wad2.wad2_chunks.ChunkId.Bone2:
                bone = self.read_single_bone(reader, stream)
                moveable['bones'].append(bone)
                bone_name = bone.get("name", "unnamed")
                bone_name_safe = bone_name.encode('ascii', errors='replace').decode('ascii')
                print(f'[DEBUG]     Bone: {bone_name_safe}')
            elif sub_id == read_wad2.wad2_chunks.ChunkId.Ani2:
                # Just skip for now
                print(f'[DEBUG]     Animation chunk (skipping)')

            reader.read_chunk_end()

        self.moveables[moveable['id']] = moveable
        print(f'[DEBUG] Finished moveable {moveable_index}: {len(moveable["meshes"])} meshes, {len(moveable["bones"])} bones')
        moveable_index += 1
        reader.read_chunk_end()

    print(f'[DEBUG] Total moveables read: {moveable_index}')

read_wad2.Wad2Loader.read_moveables = debug_read_moveables

try:
    loader = read_wad2.Wad2Loader()
    print(f'Loading WAD2 file: {wad2_path}')

    with open(wad2_path, 'rb') as f:
        wad = loader.load_from_stream(f, Options())

    print(f'\n[OK] Successfully loaded WAD2 file')
    print(f'  Moveables: {len(loader.moveables)}')
    print(f'  Statics: {len(loader.statics)}')

except Exception as e:
    print(f'[ERROR] Error loading WAD2: {e}')
    import traceback
    traceback.print_exc()
