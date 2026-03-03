from . import data
from . import read_wad2
from . import wad2_chunks


def preview(f, movable_names, static_names):
    data.read_uint32(f)
    texture_samples_count = data.read_uint32(f)
    f.read(8 * texture_samples_count)
    bytes_size = data.read_uint32(f)
    f.read(bytes_size)
    mesh_pointers_count = data.read_uint32(f)
    f.read(mesh_pointers_count * 4)
    words_size = data.read_uint32(f)
    f.read(words_size * 2)
    animations_count = data.read_uint32(f)
    f.read(animations_count * 40)
    state_changes_count = data.read_uint32(f)
    f.read(state_changes_count * 6)
    dispatches_count = data.read_uint32(f)
    f.read(dispatches_count*8)
    words_size = data.read_uint32(f)
    f.read(words_size * 2)
    dwords_size = data.read_uint32(f)
    f.read(dwords_size * 4)
    keyframes_words_size = data.read_uint32(f)
    f.read(keyframes_words_size * 2)

    movables_count = data.read_uint32(f)
    movables_data = [data.Movable.decode(f) for _ in range(movables_count)]
    movables = []
    for mov in movables_data:
        idx = str(mov.obj_ID)
        if idx in movable_names:
            movables.append(movable_names[idx])
        else:
            movables.append('MOVABLE' + idx)


    statics_count = data.read_uint32(f)
    statics_data = [data.Static.decode(f) for _ in range(statics_count)]
    statics = []
    for stat in statics_data:
        idx = str(stat.obj_ID)
        if idx in static_names:
            statics.append(static_names[idx])
        else:
            statics.append('STATIC' + idx)

    return movables, statics


def preview_wad2(f):
    """Quick preview of WAD2 file to list movables and statics by name."""
    movables = []
    statics = []

    try:
        reader = read_wad2.ChunkReader(f)

        # Read root chunk
        root_id = reader.read_chunk_start()
        if root_id != wad2_chunks.ChunkId.Wad2:
            return movables, statics

        # Skip through chunks looking for moveables and statics
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None:
                break

            if chunk_id == wad2_chunks.ChunkId.Moveables:
                # Read moveable chunks
                while True:
                    mov_id = reader.read_chunk_start()
                    if mov_id is None or mov_id != wad2_chunks.ChunkId.Moveable:
                        if mov_id is not None:
                            reader.read_chunk_end()
                        break

                    # Read the moveable ID (LEB128 at start of chunk)
                    moveable_id = read_wad2.read_leb128_uint(f)
                    movables.append(f'MOVABLE{moveable_id}')

                    # Skip rest of moveable data by ending the chunk
                    reader.read_chunk_end()

            elif chunk_id == wad2_chunks.ChunkId.Statics:
                # Read static chunks
                while True:
                    stat_id = reader.read_chunk_start()
                    if stat_id is None or stat_id != wad2_chunks.ChunkId.Static:
                        if stat_id is not None:
                            reader.read_chunk_end()
                        break

                    # Read the static ID
                    static_id = read_wad2.read_leb128_uint(f)
                    statics.append(f'STATIC{static_id}')

                    # Skip rest of static data
                    reader.read_chunk_end()

            reader.read_chunk_end()

    except Exception:
        # If preview fails, return what we have
        pass

    return movables, statics
