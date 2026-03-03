"""Find all W2 chunk types in moveable section"""
wad2_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\CatacombWad2.wad2'

with open(wad2_path, 'rb') as f:
    data = f.read()

# Search for W2 chunks in the moveable section (0x25dba4 to 0x68f7ee)
moveable_start = 0x25dba4
moveable_end = 0x68f7ee

chunks_found = set()
pos = moveable_start
while pos < moveable_end - 20:
    if data[pos:pos+2] == b'W2':
        # Try to read as chunk ID
        # Check if previous byte could be a length
        if pos > 0:
            potential_len = data[pos-1]
            if 2 <= potential_len <= 30:  # Reasonable chunk ID length
                chunk_id = data[pos:pos+potential_len]
                if chunk_id.startswith(b'W2') and chunk_id.isascii():
                    chunks_found.add(chunk_id)
    pos += 1

print('Chunks found in moveable section:')
for chunk in sorted(chunks_found):
    try:
        print(f'  {chunk.decode("ascii")}')
    except:
        print(f'  {chunk}')
