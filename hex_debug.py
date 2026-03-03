"""Quick hex dump at specific position"""
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

with open(wad2_path, 'rb') as f:
    # Let's look before the moveable content start
    # 0x25dba4 = W2Moveable chunk starts
    f.seek(0x25dba4)

    # Read 80 bytes to see the whole thing
    data = f.read(80)
    print(f'Hex dump at 0x25dba4 (W2Moveable chunk start):')
    for i in range(0, len(data), 16):
        hex_str = ' '.join(f'{b:02x}' for b in data[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
        print(f'{0x25dba4+i:08x}: {hex_str:<48} {ascii_str}')

    # Decode the header manually
    print('\nManual decode:')
    f.seek(0x25dba4)
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
