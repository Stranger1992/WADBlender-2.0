"""Hex dump at static chunk position"""
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

with open(wad2_path, 'rb') as f:
    # First static is at 0x0068f7fc
    f.seek(0x0068f7fc)

    # Read 200 bytes to see the structure
    data = f.read(200)
    print(f'Hex dump at 0x0068f7fc (first W2Static2):')
    for i in range(0, len(data), 16):
        hex_str = ' '.join(f'{b:02x}' for b in data[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
        print(f'{0x0068f7fc+i:08x}: {hex_str:<48} {ascii_str}')

    # Decode the structure manually
    print('\nManual decode:')
    f.seek(0x0068f7fc)
    # Read chunk ID
    length = int.from_bytes(f.read(1), 'little')
    print(f'  Chunk ID length: {length}')
    chunk_id = f.read(length)
    print(f'  Chunk ID: {chunk_id}')
    # Read size (LEB128)
    size_bytes = []
    while True:
        b = f.read(1)[0]
        size_bytes.append(b)
        if (b & 0x80) == 0:
            break
    print(f'  Size bytes: {[hex(b) for b in size_bytes]}')
    # Calculate size
    size = 0
    shift = 0
    for b in size_bytes:
        size |= (b & 0x7F) << shift
        shift += 7
    print(f'  Calculated size: {size}')
    print(f'  Content starts at: 0x{f.tell():08x}')

    # Read ID
    id_value = f.read(1)[0]
    print(f'  ID: {id_value}')
    print(f'  After ID at: 0x{f.tell():08x}')

    # Check what's next (should be W2Mesh)
    next_length = int.from_bytes(f.read(1), 'little')
    print(f'  Next chunk ID length: {next_length}')
    next_chunk_id = f.read(next_length)
    print(f'  Next chunk ID: {next_chunk_id}')
