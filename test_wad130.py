import sys
from wad import read

class Options:
    texture_pages = False

# Test version 130 WAD
wad_path = r'C:\Users\Jonathan\Desktop\TRLE\Michiel_Wadmerger198_beta3\WADMerger_198b3\Wad Files\Catacombsv130.wad'
with open(wad_path, 'rb') as f:
    try:
        wad = read.readWAD(f, Options())
        print(f'[OK] Successfully loaded WAD version {wad.version}')
        print(f'  Movables: {len(wad.movables)}')
        print(f'  Statics: {len(wad.statics)}')
        print(f'  Texture map: {wad.mapwidth}x{wad.mapheight}')
        if wad.movables:
            print(f'  First movable ID: {wad.movables[0].idx}')
            print(f'  First movable meshes: {len(wad.movables[0].meshes)}')
    except Exception as e:
        print(f'[ERROR] Error loading WAD: {e}')
        import traceback
        traceback.print_exc()
