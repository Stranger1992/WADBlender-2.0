"""Test WAD2 with verbose debugging"""
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
    while True:
        chunk_id = reader.read_chunk_start()
        print(f'[DEBUG] Moveable chunk_id: {chunk_id}')
        if chunk_id is None or chunk_id != read_wad2.wad2_chunks.ChunkId.Moveable:
            if chunk_id is not None:
                reader.read_chunk_end()
            break

        moveable = {
            'id': moveable_index,
            'meshes': [],
            'bones': [],
            'animations': []
        }

        print(f'[DEBUG] Reading moveable {moveable_index}...')

        # Read moveable sub-chunks
        sub_count = 0
        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                print(f'[DEBUG]   End of moveable sub-chunks (read {sub_count})')
                break

            sub_name = sub_id.decode('ascii', errors='replace') if sub_id else '(none)'
            print(f'[DEBUG]   Sub-chunk: {sub_name}')
            sub_count += 1

            if sub_id == read_wad2.wad2_chunks.ChunkId.Mesh:
                print(f'[DEBUG]     Reading embedded mesh...')
                mesh = self.read_single_mesh(reader, stream)
                moveable['meshes'].append(mesh)
                print(f'[DEBUG]     Mesh has {len(mesh.get("positions", []))} vertices')

            reader.read_chunk_end()

            if sub_count > 50:  # Safety limit
                print(f'[DEBUG]   Safety limit reached!')
                break

        self.moveables[moveable['id']] = moveable
        moveable_index += 1
        reader.read_chunk_end()

        if moveable_index >= 3:  # Only read first 3 for debugging
            break

read_wad2.Wad2Loader.read_moveables = debug_read_moveables

try:
    loader = read_wad2.Wad2Loader()
    print(f'Loading WAD2 file: {wad2_path}')

    with open(wad2_path, 'rb') as f:
        magic = f.read(4)
        print(f'Magic bytes: {magic}')
        if magic != b'WAD2':
            print(f'[ERROR] Invalid magic number')
            sys.exit(1)
        f.seek(0)

        wad = loader.load_from_stream(f, Options())

    print(f'\n[OK] Successfully loaded WAD2 file')
    print(f'  Moveables: {len(loader.moveables)}')

    for mov_id, mov in list(loader.moveables.items())[:3]:
        print(f'\n  Moveable {mov_id}:')
        print(f'    Embedded meshes: {len(mov["meshes"])}')

except Exception as e:
    print(f'[ERROR] Error loading WAD2: {e}')
    import traceback
    traceback.print_exc()
