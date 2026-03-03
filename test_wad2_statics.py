"""Test WAD2 statics with debugging"""
import sys
from wad import read_wad2

class Options:
    texture_pages = False

# Test WAD2 file
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

# Patch the loader to add debug output
original_read_statics = read_wad2.Wad2Loader.read_statics

def debug_read_statics(self, reader, stream):
    """Read static objects with debug output"""
    static_index = 0
    print(f'[DEBUG] Starting to read statics...')

    while static_index < 5:  # Limit to first 5 for debugging
        pos_before = stream.tell()
        chunk_id = reader.read_chunk_start()
        print(f'[DEBUG] Static loop iteration {static_index}, pos=0x{pos_before:08x}, chunk_id={chunk_id}')

        if chunk_id is None or chunk_id not in (read_wad2.wad2_chunks.ChunkId.Static, read_wad2.wad2_chunks.ChunkId.Static2):
            if chunk_id is not None:
                chunk_name = chunk_id.decode('ascii', errors='replace')
                chunk_name_safe = chunk_name.encode('ascii', errors='replace').decode('ascii')
                print(f'[DEBUG] Got non-Static chunk: {chunk_name_safe}, ending static reading')
                reader.read_chunk_end()
            else:
                print(f'[DEBUG] Got None chunk_id, ending static reading')
            break

        # Read static ID
        static_id = read_wad2.read_leb128_uint(stream)
        print(f'[DEBUG] Reading static {static_index}, ID={static_id}')

        # Read extra field (might be flags or count?)
        extra_byte = read_wad2.read_leb128_uint(stream)
        print(f'[DEBUG]   Extra field after ID: {extra_byte}')

        static = {
            'id': static_id,
            'mesh': None,
            'visibility_box': None,
            'collision_box': None
        }

        # Read static sub-chunks
        sub_count = 0
        while True:
            sub_pos = stream.tell()
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                print(f'[DEBUG]   End of static sub-chunks (read {sub_count} sub-chunks)')
                break

            sub_name = sub_id.decode('ascii', errors='replace') if sub_id else '(none)'
            sub_name_safe = sub_name.encode('ascii', errors='replace').decode('ascii')
            print(f'[DEBUG]   Sub-chunk [{sub_count}]: {sub_name_safe} at 0x{sub_pos:08x}')
            sub_count += 1

            if sub_id == read_wad2.wad2_chunks.ChunkId.Mesh:
                mesh = self.read_single_mesh(reader, stream)
                static['mesh'] = mesh
                mesh_name = mesh.get("name", "unnamed")
                mesh_name_safe = mesh_name.encode('ascii', errors='replace').decode('ascii')
                print(f'[DEBUG]     Mesh: {mesh_name_safe}, {len(mesh.get("positions", []))} vertices')
            elif sub_id == read_wad2.wad2_chunks.ChunkId.StaticMesh:
                mesh_idx = read_wad2.read_leb128_uint(stream)
                static['mesh'] = mesh_idx
                print(f'[DEBUG]     Mesh index: {mesh_idx}')

            reader.read_chunk_end()

        self.statics[static['id']] = static
        print(f'[DEBUG] Finished static {static_index}: {static}')
        static_index += 1
        reader.read_chunk_end()

    print(f'[DEBUG] Total statics read: {static_index}')

read_wad2.Wad2Loader.read_statics = debug_read_statics

try:
    loader = read_wad2.Wad2Loader()
    print(f'Loading WAD2 file: {wad2_path}')

    with open(wad2_path, 'rb') as f:
        wad = loader.load_from_stream(f, Options())

    print(f'\n[OK] Successfully loaded WAD2 file')
    print(f'  Statics: {len(loader.statics)}')

except Exception as e:
    print(f'[ERROR] Error loading WAD2: {e}')
    import traceback
    traceback.print_exc()
