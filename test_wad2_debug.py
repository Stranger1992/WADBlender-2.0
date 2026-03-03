"""Debug WAD2 file structure"""
import sys
import struct

wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

def read_leb128_uint(f):
    """Read LEB128 variable-length unsigned integer"""
    result = 0
    shift = 0
    while True:
        byte = struct.unpack('B', f.read(1))[0]
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result

def read_chunk_id(f):
    """Read chunk identifier (length-prefixed string as bytes)"""
    length = read_leb128_uint(f)
    if length == 0:
        return b''
    return f.read(length)

def read_string(f):
    """Read length-prefixed string"""
    length = read_leb128_uint(f)
    if length == 0:
        return ""
    data = f.read(length)
    return data.decode('utf-8', errors='replace')

def parse_wad2_manually(filepath):
    """Manually parse WAD2 to understand structure"""
    with open(filepath, 'rb') as f:
        # Verify magic
        magic = f.read(4)
        print(f'Magic: {magic}')
        assert magic == b'WAD2'

        # Skip version/flags
        f.read(4)

        print('\n=== ROOT CHUNKS ===')

        # Read root chunks
        root_chunk_count = 0
        while root_chunk_count < 10:  # Limit iterations for safety
            pos = f.tell()
            try:
                chunk_id = read_chunk_id(f)
                if not chunk_id:
                    break
                chunk_size = read_leb128_uint(f)
                content_start = f.tell()

                chunk_name = chunk_id.decode('ascii', errors='replace')
                print(f'\n[{root_chunk_count}] Chunk at 0x{pos:04x}: {chunk_name}')
                print(f'    Size: {chunk_size} bytes')
                print(f'    Content: 0x{content_start:04x} - 0x{content_start + chunk_size:04x}')

                # Handle specific chunks
                if chunk_id == b'W2SuggestedGameVersion':
                    version = read_leb128_uint(f)
                    print(f'    Version: {version}')

                elif chunk_id == b'W2SoundSystem':
                    sound_sys = read_leb128_uint(f)
                    print(f'    Sound system: {sound_sys}')

                elif chunk_id == b'W2Textures':
                    print(f'    === TEXTURES ===')
                    # Parse texture sub-chunks
                    texture_count = 0
                    while f.tell() < content_start + chunk_size and texture_count < 5:
                        sub_pos = f.tell()
                        sub_id = read_chunk_id(f)
                        if not sub_id:
                            break
                        sub_size = read_leb128_uint(f)
                        sub_content_start = f.tell()

                        sub_name = sub_id.decode('ascii', errors='replace')
                        print(f'      [{texture_count}] Sub-chunk at 0x{sub_pos:04x}: {sub_name}')
                        print(f'          Size: {sub_size} bytes')
                        print(f'          Content: 0x{sub_content_start:04x} - 0x{sub_content_start + sub_size:04x}')

                        if sub_id == b'W2Txt':
                            # Read texture dimensions
                            width = read_leb128_uint(f)
                            height = read_leb128_uint(f)
                            print(f'          Dimensions: {width}x{height}')

                            # Parse texture properties
                            tex_prop_count = 0
                            while f.tell() < sub_content_start + sub_size and tex_prop_count < 10:
                                prop_pos = f.tell()
                                prop_id = read_chunk_id(f)
                                if not prop_id:
                                    break
                                prop_size = read_leb128_uint(f)
                                prop_content_start = f.tell()

                                prop_name = prop_id.decode('ascii', errors='replace')
                                prop_name_safe = prop_name.encode('ascii', errors='replace').decode('ascii')
                                print(f'            [{tex_prop_count}] Property at 0x{prop_pos:04x}: {prop_name_safe}')
                                print(f'                Size: {prop_size} bytes')

                                if prop_id == b'W2TxtIndex':
                                    idx = read_leb128_uint(f)
                                    print(f'                Index: {idx}')
                                elif prop_id == b'W2TxtName':
                                    # Chunk content IS the string directly (no length prefix)
                                    name_bytes = f.read(prop_size)
                                    name = name_bytes.decode('utf-8', errors='replace')
                                    name_safe = name.encode('ascii', errors='replace').decode('ascii')
                                    print(f'                Name: "{name_safe}"')
                                elif prop_id == b'W2TxtRelPath':
                                    # Chunk content IS the string directly (no length prefix)
                                    path_bytes = f.read(prop_size)
                                    path = path_bytes.decode('utf-8', errors='replace')
                                    path_safe = path.encode('ascii', errors='replace').decode('ascii')
                                    print(f'                Path: "{path_safe}"')
                                elif prop_id == b'W2TxtData':
                                    data_size = read_leb128_uint(f)
                                    print(f'                Image data size: {data_size} bytes')
                                    # Skip the image data
                                    f.seek(prop_content_start + prop_size)
                                else:
                                    # Skip unknown property
                                    f.seek(prop_content_start + prop_size)

                                tex_prop_count += 1

                            # Make sure we're at the end of W2Txt chunk
                            f.seek(sub_content_start + sub_size)
                        else:
                            # Skip unknown sub-chunk
                            f.seek(sub_content_start + sub_size)

                        texture_count += 1

                    # Make sure we're at the end of W2Textures chunk
                    f.seek(content_start + chunk_size)

                elif chunk_id == b'W2Meshes':
                    print(f'    === MESHES ===')
                    # Just skip for now
                    f.seek(content_start + chunk_size)

                elif chunk_id == b'W2Moveables':
                    print(f'    === MOVEABLES ===')
                    # Parse first moveable to understand structure
                    moveable_count = 0
                    while f.tell() < content_start + chunk_size and moveable_count < 2:
                        mov_pos = f.tell()
                        mov_id = read_chunk_id(f)
                        if not mov_id or mov_id != b'W2Moveable':
                            break
                        mov_size = read_leb128_uint(f)
                        mov_content_start = f.tell()

                        print(f'      [{moveable_count}] Moveable at 0x{mov_pos:04x}')
                        print(f'          Size: {mov_size} bytes')

                        # Read moveable properties
                        prop_count = 0
                        while f.tell() < mov_content_start + mov_size and prop_count < 10:
                            prop_pos = f.tell()
                            prop_id = read_chunk_id(f)
                            if not prop_id:
                                print(f'          (End of moveable properties at 0x{prop_pos:04x})')
                                break
                            prop_size = read_leb128_uint(f)
                            prop_content_start = f.tell()

                            prop_name = prop_id.decode('ascii', errors='replace')
                            print(f'          [{prop_count}] {prop_name} at 0x{prop_pos:04x}, size: {prop_size}')
                            prop_count += 1

                            if prop_id == b'W2MoveableId':
                                mov_obj_id = read_leb128_uint(f)
                                print(f'              ID: {mov_obj_id}')
                            elif prop_id == b'W2Mesh':
                                # Direct mesh data!
                                print(f'              Direct mesh embedded!')
                                # Read dimensions
                                width = read_leb128_uint(f)
                                height = read_leb128_uint(f)
                                print(f'              Mesh dimensions(?): {width}x{height}')
                            elif prop_id == b'W2MoveableMeshes':
                                # This contains mesh indices OR embedded meshes
                                # First value should be count
                                saved_pos = f.tell()
                                try:
                                    mesh_count = read_leb128_uint(f)
                                    print(f'              Mesh count: {mesh_count}')
                                    # Check if next is a chunk or an integer
                                    next_byte = f.read(1)
                                    f.seek(saved_pos + 1)
                                    if next_byte and next_byte[0] < 20:  # Likely an index
                                        print(f'              (Appears to be mesh indices)')
                                    else:
                                        print(f'              (Might contain embedded W2Mesh chunks)')
                                except:
                                    pass
                                f.seek(saved_pos)
                            elif prop_id == b'W2MoveableSkin':
                                # Skin contains embedded meshes
                                print(f'              Skin chunk - checking for embedded meshes')
                                skin_saved = f.tell()
                                mesh_count = 0
                                while f.tell() < prop_content_start + prop_size:
                                    mesh_pos = f.tell()
                                    mesh_id = read_chunk_id(f)
                                    if not mesh_id:
                                        break
                                    if mesh_id == b'W2Mesh':
                                        mesh_size = read_leb128_uint(f)
                                        print(f'                Found W2Mesh at 0x{mesh_pos:04x}, size: {mesh_size}')
                                        f.seek(f.tell() + mesh_size)
                                        mesh_count += 1
                                    else:
                                        break
                                print(f'              Found {mesh_count} embedded meshes in skin')
                                f.seek(skin_saved)
                            elif prop_id == b'W2MoveableBones':
                                # Parse bone structure
                                bone_count = 0
                                while f.tell() < prop_content_start + prop_size and bone_count < 3:
                                    bone_pos = f.tell()
                                    bone_id = read_chunk_id(f)
                                    if not bone_id or bone_id != b'W2MoveableBone':
                                        break
                                    bone_size = read_leb128_uint(f)
                                    print(f'                Bone [{bone_count}] at 0x{bone_pos:04x}')
                                    f.seek(f.tell() + bone_size)
                                    bone_count += 1
                                print(f'              Total bones: {bone_count}+')

                            # Skip to end of property
                            f.seek(prop_content_start + prop_size)

                        # Move to next moveable
                        f.seek(mov_content_start + mov_size)
                        moveable_count += 1

                    print(f'      Total moveables: {moveable_count}+')
                    f.seek(content_start + chunk_size)

                elif chunk_id == b'W2Statics':
                    print(f'    === STATICS ===')
                    # Just skip for now
                    f.seek(content_start + chunk_size)

                else:
                    # Skip unknown chunk
                    print(f'    (Skipping unknown chunk)')
                    f.seek(content_start + chunk_size)

                root_chunk_count += 1

            except Exception as e:
                print(f'\nError at position 0x{f.tell():04x}: {e}')
                import traceback
                traceback.print_exc()
                break

        print(f'\n\nTotal root chunks read: {root_chunk_count}')
        print(f'Final file position: 0x{f.tell():04x}')

try:
    parse_wad2_manually(wad2_path)
except Exception as e:
    print(f'[ERROR] {e}')
    import traceback
    traceback.print_exc()
