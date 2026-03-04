"""
WAD2 File Format Writer
Based on Tomb Editor's Wad2Writer.cs and Wad2Chunks.cs

Implements chunk-based binary writing with LEB128 encoding.
Produces files byte-compatible with Tomb Editor / WadTool.
"""

import struct
import io
from typing import List, Tuple, Optional


# ---------------------------------------------------------------------------
# LEB128 encoding
# ---------------------------------------------------------------------------

def write_leb128_unsigned(stream, value: int):
    """Write unsigned LEB128 variable-length integer."""
    if value < 0:
        raise ValueError(f"Cannot encode negative value {value} as unsigned LEB128")
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        stream.write(struct.pack('B', byte))
        if value == 0:
            break


def write_leb128_signed(stream, value: int):
    """Write signed LEB128 variable-length integer."""
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40) != 0):
            more = False
        else:
            byte |= 0x80
        stream.write(struct.pack('B', byte))


def write_leb128_unsigned_padded(stream, value: int, num_bytes: int = 4):
    """
    Write unsigned LEB128 padded to exactly *num_bytes*.

    The C# ChunkWriter pre-allocates a fixed-width field for chunk sizes
    (4 bytes by default, 5 for the Textures chunk) then patches it after
    writing the body.  WadTool / Tomb Editor expect this fixed width.
    """
    for i in range(num_bytes):
        byte = value & 0x7F
        value >>= 7
        if i < num_bytes - 1:
            byte |= 0x80          # continuation bit on all but last byte
        stream.write(struct.pack('B', byte))


# ---------------------------------------------------------------------------
# Chunk ID strings (from Wad2Chunks.cs)
# ---------------------------------------------------------------------------

class Wad2Chunks:
    """Chunk identifier strings matching Tomb Editor's Wad2Chunks.cs"""
    MagicNumber = b'\x57\x41\x44\x32'  # "WAD2"

    GameVersion         = b'W2SuggestedGameVersion'
    SoundSystem         = b'W2SoundSystem'
    Metadata            = b'W2Metadata'
    Timestamp           = b'W2Timestamp'
    UserNotes           = b'W2UserNotes'

    # Textures
    Textures            = b'W2Textures'
    Texture             = b'W2Txt'
    TextureIndex        = b'W2Index'
    TextureData         = b'W2TxtData'
    TextureName         = b'W2TxtName'
    TextureRelativePath = b'W2TxtRelPath'

    # Sprites
    Sprites             = b'W2Sprites'
    Sprite              = b'W2Spr'

    # Sprite Sequences
    SpriteSequences     = b'W2SpriteSequences'
    SpriteSequence      = b'W2SpriteSeq'

    # Meshes
    Mesh                = b'W2Mesh'
    MeshIndex           = b'W2Index'
    MeshName            = b'W2MeshName'
    MeshSphere          = b'W2MeshSphere'
    MeshSphereCenter    = b'W2SphC'
    MeshSphereRadius    = b'W2SphR'
    MeshBoundingBox     = b'W2BBox'
    MeshBoundingBoxMin  = b'W2BBMin'
    MeshBoundingBoxMax  = b'W2BBMax'
    MeshVertexPositions = b'W2VrtPos'
    MeshVertexPosition  = b'W2Pos'
    MeshVertexNormals   = b'W2VrtNorm'
    MeshVertexNormal    = b'W2N'
    MeshVertexShades    = b'W2VrtShd'
    MeshVertexColor     = b'W2VxCol'
    MeshVertexAttributes = b'W2VrtAttr'
    MeshVertexAttribute = b'W2VxAttr'
    MeshVertexWeights   = b'W2VrtWghts'
    MeshVertexWeight    = b'W2VrtWght'
    MeshLightingType    = b'W2MeshLightType'
    MeshVisibility      = b'W2MeshVisible'
    MeshPolygons        = b'W2Polys'
    MeshTriangle2       = b'W2Tr2'
    MeshQuad2           = b'W2Uq2'

    # Moveables
    Moveables           = b'W2Moveables'
    Moveable            = b'W2Moveable'
    MoveableSkin        = b'W2MovSkin'
    MoveableBoneNew     = b'W2Bone2'
    MoveableBoneName    = b'W2BoneName'
    MoveableBoneMeshPointer = b'W2BoneMesh'
    MoveableBoneTranslation = b'W2BoneTrans'

    # Animations
    Animation2          = b'W2Ani2'
    AnimationVelocities = b'W2AniV'
    AnimationName       = b'W2AnmName'
    KeyFrame            = b'W2Kf'
    KeyFrameOffset      = b'W2KfOffs'
    KeyFrameBoundingBox = b'W2KfBB'
    KeyFrameAngle       = b'W2KfA'
    StateChange         = b'W2StCh'
    Dispatch            = b'W2Disp'
    AnimCommand2        = b'W2Cmd2'
    AnimCommandSoundInfo = b'W2CmdSnd'

    # Statics
    Statics             = b'W2Statics'
    Static2             = b'W2Static2'
    StaticVisibilityBox = b'W2StaticVB'
    StaticCollisionBox  = b'W2StaticCB'
    StaticAmbientLight  = b'W2StaticAmbientLight'
    StaticShatter       = b'W2StaticShatter'
    StaticShatterSound  = b'W2StaticShatterSound'
    StaticLight         = b'W2StaticLight'
    StaticLightPosition = b'W2StaticLightPos'
    StaticLightRadius   = b'W2StaticLightR'
    StaticLightIntensity = b'W2StaticLightI'

    # Animated textures
    AnimatedTextureSets = b'W2AnimatedTextureSets'


# ---------------------------------------------------------------------------
# ChunkWriter -- mirrors Tomb Editor's ChunkWriter class
# ---------------------------------------------------------------------------

class ChunkWriter:
    """
    Writes WAD2 chunk-based binary format.

    Each chunk is:
        [LEB128 chunk-id-length] [chunk-id bytes] [padded-LEB128 data-length] [data bytes]

    The C# ChunkWriter uses **fixed-width** LEB128 for chunk data sizes
    (4 bytes by default, 5 bytes for very large chunks like Textures).
    Chunk ID string lengths use standard minimal LEB128.

    Child-bearing chunks end their data with a 0x00 byte (zero-length chunk ID
    acting as end-of-children sentinel).
    """

    # Default size-field width in bytes (matches C# ChunkWriter default)
    DEFAULT_SIZE_BYTES = 4

    def __init__(self, stream, size_bytes: int = 4):
        self.stream = stream
        self.size_bytes = size_bytes

    # -- Low-level writing helpers --

    def _write_chunk_id(self, chunk_id: bytes):
        """Write a chunk identifier (minimal LEB128-length-prefixed bytes)."""
        write_leb128_signed(self.stream, len(chunk_id))
        self.stream.write(chunk_id)

    def _write_size(self, size: int, num_bytes: int = None):
        """Write chunk data size as padded LEB128."""
        if num_bytes is None:
            num_bytes = self.size_bytes
        write_leb128_unsigned_padded(self.stream, size, num_bytes)

    def _write_chunk_end_marker(self):
        """Write child-chunk-list end sentinel (a single 0x00 byte)."""
        self.stream.write(b'\x00')

    # -- Leaf chunk helpers (no children) --
    # Leaf chunks use MINIMAL LEB128 for their size field,
    # matching the C# WriteChunkInt / WriteChunkString / etc. behaviour.

    def write_chunk_int(self, chunk_id: bytes, value: int):
        """Write a chunk containing a single LEB128 signed integer."""
        buf = io.BytesIO()
        write_leb128_signed(buf, value)
        data = buf.getvalue()
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(data))
        self.stream.write(data)

    def write_chunk_string(self, chunk_id: bytes, text: str):
        """Write a chunk containing a raw UTF-8 string (no length prefix in body)."""
        encoded = text.encode('utf-8')
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(encoded))
        self.stream.write(encoded)

    def write_chunk_float(self, chunk_id: bytes, value: float):
        """Write a chunk containing a single 32-bit float."""
        data = struct.pack('<f', value)
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(data))
        self.stream.write(data)

    def write_chunk_vector3(self, chunk_id: bytes, x: float, y: float, z: float):
        """Write a chunk containing three 32-bit floats."""
        data = struct.pack('<fff', x, y, z)
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(data))
        self.stream.write(data)

    def write_chunk_vector4(self, chunk_id: bytes, x: float, y: float, z: float, w: float):
        """Write a chunk containing four 32-bit floats."""
        data = struct.pack('<ffff', x, y, z, w)
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(data))
        self.stream.write(data)

    def write_chunk_bool(self, chunk_id: bytes, value: bool):
        """Write a chunk containing a single boolean byte."""
        data = struct.pack('?', value)
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(data))
        self.stream.write(data)

    def write_chunk_bytes(self, chunk_id: bytes, data: bytes):
        """Write a chunk containing raw byte data."""
        self._write_chunk_id(chunk_id)
        write_leb128_signed(self.stream, len(data))
        self.stream.write(data)

    # -- Parent chunk helpers (with children) --

    def write_chunk_with_children(self, chunk_id: bytes, write_fn,
                                  size_bytes: int = None):
        """
        Write a chunk whose body is produced by *write_fn* writing children
        into a temporary buffer.  The end-of-children sentinel is appended
        automatically.

        *size_bytes* overrides the width of this chunk's size field
        (use 5 for Textures which can be very large).
        """
        if size_bytes is None:
            size_bytes = self.size_bytes
        buf = io.BytesIO()
        child_writer = ChunkWriter(buf, size_bytes=ChunkWriter.DEFAULT_SIZE_BYTES)
        write_fn(child_writer)
        child_writer._write_chunk_end_marker()
        data = buf.getvalue()
        self._write_chunk_id(chunk_id)
        self._write_size(len(data), size_bytes)
        self.stream.write(data)

    # -- Raw data helpers (write into current chunk body) --

    def write_raw(self, data: bytes):
        self.stream.write(data)

    def write_raw_leb128_unsigned(self, value: int):
        write_leb128_unsigned(self.stream, value)

    def write_raw_leb128_signed(self, value: int):
        write_leb128_signed(self.stream, value)

    def write_raw_float(self, value: float):
        self.stream.write(struct.pack('<f', value))

    def write_raw_vector2(self, x: float, y: float):
        self.stream.write(struct.pack('<ff', x, y))

    def write_raw_vector3(self, x: float, y: float, z: float):
        self.stream.write(struct.pack('<fff', x, y, z))

    def write_raw_bool(self, value: bool):
        self.stream.write(struct.pack('?', value))

    def write_raw_string_utf8(self, text: str):
        """Write a LEB128-length-prefixed UTF-8 string (no chunk framing)."""
        encoded = text.encode('utf-8')
        write_leb128_signed(self.stream, len(encoded))
        self.stream.write(encoded)

    def write_raw_int32(self, value: int):
        self.stream.write(struct.pack('<i', value))


# ---------------------------------------------------------------------------
# WAD2 high-level serialisation (mirrors Wad2Writer.cs)
# ---------------------------------------------------------------------------

def write_wad2_file(filepath: str, wad2_data: dict):
    """
    Write a complete WAD2 file.

    wad2_data keys:
        'game_version': int (e.g. 4 for TR4/TEN)
        'textures': list of {'width', 'height', 'data' (PNG bytes), 'name', 'rel_path'}
        'moveables': list of moveable dicts
        'statics': list of static dicts
        'timestamp': (year, month, day, hour, minute, second) or None
        'user_notes': str
    """
    buf = io.BytesIO()
    _write_wad2_to_stream(buf, wad2_data)

    with open(filepath, 'wb') as f:
        f.write(buf.getvalue())


def _write_wad2_to_stream(stream, wad2_data: dict):
    """Write WAD2 data to a stream."""
    stream.write(Wad2Chunks.MagicNumber)
    stream.write(b'\x00\x00\x00\x00')  # Compression: None

    cw = ChunkWriter(stream)

    cw.write_chunk_int(Wad2Chunks.GameVersion, wad2_data.get('game_version', 4))
    cw.write_chunk_int(Wad2Chunks.SoundSystem, 1)  # XML

    textures = wad2_data.get('textures', [])
    _write_textures(cw, textures)  # uses size_bytes=5 internally

    # Sprites (empty)
    cw.write_chunk_with_children(Wad2Chunks.Sprites, lambda w: None)

    # Sprite sequences (empty)
    cw.write_chunk_with_children(Wad2Chunks.SpriteSequences, lambda w: None)

    _write_moveables(cw, wad2_data.get('moveables', []))
    _write_statics(cw, wad2_data.get('statics', []))

    _write_metadata(cw, wad2_data.get('timestamp', None),
                    wad2_data.get('user_notes', ''))

    # Animated texture sets (empty) — uses 10-byte size (C# long.MaxValue)
    cw.write_chunk_with_children(Wad2Chunks.AnimatedTextureSets, lambda w: None,
                                 size_bytes=10)

    # Root end marker
    cw._write_chunk_end_marker()


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------

def _write_textures(cw: ChunkWriter, textures: list):
    def _inner(w):
        for tex in textures:
            def _tex_inner(tw, t=tex):
                tw.write_raw_leb128_signed(t['width'])
                tw.write_raw_leb128_signed(t['height'])
                tw.write_chunk_string(Wad2Chunks.TextureName, '')
                tw.write_chunk_string(Wad2Chunks.TextureRelativePath, '')
                tw.write_chunk_bytes(Wad2Chunks.TextureData, t['data'])
            w.write_chunk_with_children(Wad2Chunks.Texture, _tex_inner)
    # Textures chunk can be very large — use 5-byte LEB128 size
    # (matches C# LEB128.MaximumSize5Byte)
    cw.write_chunk_with_children(Wad2Chunks.Textures, _inner, size_bytes=5)


# ---------------------------------------------------------------------------
# Meshes
# ---------------------------------------------------------------------------

def _write_mesh(cw: ChunkWriter, mesh: dict):
    """
    Write a W2Mesh chunk.

    mesh keys:
        'name': str
        'positions': [(x,y,z), ...]
        'normals': [(x,y,z), ...]
        'colors': [(r,g,b), ...]  (0..1 floats, or empty)
        'sphere_center': (x,y,z)
        'sphere_radius': float
        'bbox_min': (x,y,z)
        'bbox_max': (x,y,z)
        'polygons': list of:
            'shape': 'tri' or 'quad'
            'indices': [i0, i1, i2] or [i0, i1, i2, i3]
            'shine': int
            'texture_index': int
            'parent_area': (sx, sy, ex, ey) floats
            'uvs': [(u,v), ...]
            'blend_mode': int
            'double_sided': bool
    """
    def _inner(w):
        w.write_chunk_int(Wad2Chunks.MeshIndex, 0)
        w.write_chunk_string(Wad2Chunks.MeshName, mesh.get('name', ''))

        sc = mesh.get('sphere_center', (0, 0, 0))
        sr = mesh.get('sphere_radius', 0.0)
        def _sphere(sw):
            sw.write_chunk_vector3(Wad2Chunks.MeshSphereCenter, sc[0], sc[1], sc[2])
            sw.write_chunk_float(Wad2Chunks.MeshSphereRadius, sr)
        w.write_chunk_with_children(Wad2Chunks.MeshSphere, _sphere)

        bmin = mesh.get('bbox_min', (0, 0, 0))
        bmax = mesh.get('bbox_max', (0, 0, 0))
        def _bbox(bw):
            bw.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMin, bmin[0], bmin[1], bmin[2])
            bw.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMax, bmax[0], bmax[1], bmax[2])
        w.write_chunk_with_children(Wad2Chunks.MeshBoundingBox, _bbox)

        def _positions(pw):
            for pos in mesh.get('positions', []):
                pw.write_chunk_vector3(Wad2Chunks.MeshVertexPosition, pos[0], pos[1], pos[2])
        w.write_chunk_with_children(Wad2Chunks.MeshVertexPositions, _positions)

        def _normals(nw):
            for n in mesh.get('normals', []):
                nw.write_chunk_vector3(Wad2Chunks.MeshVertexNormal, n[0], n[1], n[2])
        w.write_chunk_with_children(Wad2Chunks.MeshVertexNormals, _normals)

        colors = mesh.get('colors', [])
        if colors:
            def _colors(sw):
                for c in colors:
                    sw.write_chunk_vector3(Wad2Chunks.MeshVertexColor, c[0], c[1], c[2])
            w.write_chunk_with_children(Wad2Chunks.MeshVertexShades, _colors)
        else:
            w.write_chunk_with_children(Wad2Chunks.MeshVertexShades, lambda sw: None)

        w.write_chunk_with_children(Wad2Chunks.MeshVertexAttributes, lambda aw: None)
        w.write_chunk_with_children(Wad2Chunks.MeshVertexWeights, lambda ww: None)

        w.write_chunk_int(Wad2Chunks.MeshLightingType, mesh.get('lighting_type', 0))
        w.write_chunk_bool(Wad2Chunks.MeshVisibility, mesh.get('hidden', False))

        def _polygons(pw):
            for poly in mesh.get('polygons', []):
                is_quad = poly['shape'] == 'quad'
                chunk_id = Wad2Chunks.MeshQuad2 if is_quad else Wad2Chunks.MeshTriangle2

                def _poly_inner(ppw, p=poly, q=is_quad):
                    for idx in p['indices']:
                        ppw.write_raw_leb128_signed(idx)
                    ppw.write_raw_leb128_signed(p.get('shine', 0))
                    ppw.write_raw_leb128_signed(p.get('texture_index', 0))

                    pa = p.get('parent_area', (0.0, 0.0, 1.0, 1.0))
                    ppw.write_raw_vector2(pa[0], pa[1])
                    ppw.write_raw_vector2(pa[2], pa[3])

                    for uv in p['uvs']:
                        ppw.write_raw_vector2(uv[0], uv[1])

                    ppw.write_raw_leb128_signed(p.get('blend_mode', 0))
                    ppw.write_raw_bool(p.get('double_sided', False))

                pw.write_chunk_with_children(chunk_id, _poly_inner)
        w.write_chunk_with_children(Wad2Chunks.MeshPolygons, _polygons)

    cw.write_chunk_with_children(Wad2Chunks.Mesh, _inner)


# ---------------------------------------------------------------------------
# Moveables
# ---------------------------------------------------------------------------

def _write_moveables(cw: ChunkWriter, moveables: list):
    def _inner(w):
        for mov in moveables:
            def _mov_inner(mw, m=mov):
                mw.write_raw_leb128_signed(m['id'])

                for mesh in m.get('meshes', []):
                    _write_mesh(mw, mesh)

                for bone in m.get('bones', []):
                    def _bone_inner(bw, b=bone):
                        bw.write_raw_leb128_signed(b.get('op', 0))
                        bw.write_raw_string_utf8(b.get('name', ''))
                        t = b.get('translation', (0, 0, 0))
                        bw.write_chunk_vector3(Wad2Chunks.MoveableBoneTranslation,
                                               t[0], t[1], t[2])
                        bw.write_chunk_int(Wad2Chunks.MoveableBoneMeshPointer,
                                           b.get('mesh_index', 0))
                    mw.write_chunk_with_children(Wad2Chunks.MoveableBoneNew, _bone_inner)

                for anim in m.get('animations', []):
                    def _anim_inner(aw, a=anim):
                        aw.write_raw_leb128_signed(a.get('state_id', 0))
                        aw.write_raw_leb128_signed(a.get('end_frame', 0))
                        aw.write_raw_leb128_signed(a.get('frame_rate', 1))
                        aw.write_raw_leb128_signed(a.get('next_animation', 0))
                        aw.write_raw_leb128_signed(a.get('next_frame', 0))

                        aw.write_chunk_string(Wad2Chunks.AnimationName, a.get('name', ''))

                        for kf in a.get('keyframes', []):
                            def _kf_inner(kw, k=kf):
                                off = k.get('offset', (0, 0, 0))
                                kw.write_chunk_vector3(Wad2Chunks.KeyFrameOffset,
                                                       off[0], off[1], off[2])
                                bb_min = k.get('bb_min', (0, 0, 0))
                                bb_max = k.get('bb_max', (0, 0, 0))
                                def _kfbb(bbw):
                                    bbw.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMin,
                                                            bb_min[0], bb_min[1], bb_min[2])
                                    bbw.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMax,
                                                            bb_max[0], bb_max[1], bb_max[2])
                                kw.write_chunk_with_children(Wad2Chunks.KeyFrameBoundingBox, _kfbb)
                                for angle in k.get('angles', []):
                                    kw.write_chunk_vector3(Wad2Chunks.KeyFrameAngle,
                                                           angle[0], angle[1], angle[2])
                            aw.write_chunk_with_children(Wad2Chunks.KeyFrame, _kf_inner)

                        for sc in a.get('state_changes', []):
                            def _sc_inner(sw, s=sc):
                                sw.write_raw_leb128_signed(s['state_id'])
                                for disp in s.get('dispatches', []):
                                    def _disp_inner(dw, d=disp):
                                        dw.write_raw_leb128_signed(d['in_frame'])
                                        dw.write_raw_leb128_signed(d['out_frame'])
                                        dw.write_raw_leb128_signed(d['next_animation'])
                                        dw.write_raw_leb128_signed(d['next_frame'])
                                    sw.write_chunk_with_children(Wad2Chunks.Dispatch, _disp_inner)
                            aw.write_chunk_with_children(Wad2Chunks.StateChange, _sc_inner)

                        for cmd in a.get('commands', []):
                            def _cmd_inner(cmdw, c=cmd):
                                cmdw.write_raw_leb128_signed(c.get('type', 0))
                                cmdw.write_raw_leb128_signed(c.get('param1', 0))
                                cmdw.write_raw_leb128_signed(c.get('param2', 0))
                                cmdw.write_raw_leb128_signed(c.get('param3', 0))
                                cmdw.write_chunk_int(Wad2Chunks.AnimCommandSoundInfo, -1)
                            aw.write_chunk_with_children(Wad2Chunks.AnimCommand2, _cmd_inner)

                        aw.write_chunk_vector4(Wad2Chunks.AnimationVelocities,
                                               a.get('start_velocity', 0.0),
                                               a.get('end_velocity', 0.0),
                                               a.get('start_lateral_velocity', 0.0),
                                               a.get('end_lateral_velocity', 0.0))

                    mw.write_chunk_with_children(Wad2Chunks.Animation2, _anim_inner)

            w.write_chunk_with_children(Wad2Chunks.Moveable, _mov_inner)
    cw.write_chunk_with_children(Wad2Chunks.Moveables, _inner)


# ---------------------------------------------------------------------------
# Statics
# ---------------------------------------------------------------------------

def _write_statics(cw: ChunkWriter, statics: list):
    def _inner(w):
        for static in statics:
            def _static_inner(sw, s=static):
                sw.write_raw_leb128_signed(s['id'])
                sw.write_raw_leb128_signed(s.get('flags', 0))

                _write_mesh(sw, s['mesh'])

                sw.write_chunk_int(Wad2Chunks.StaticAmbientLight,
                                   s.get('ambient_light', 0))
                sw.write_chunk_bool(Wad2Chunks.StaticShatter,
                                    s.get('shatter', False))
                sw.write_chunk_int(Wad2Chunks.StaticShatterSound,
                                   s.get('shatter_sound', 0))

                vmin = s.get('vis_box_min', (0, 0, 0))
                vmax = s.get('vis_box_max', (0, 0, 0))
                def _vbox(vw):
                    vw.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMin, vmin[0], vmin[1], vmin[2])
                    vw.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMax, vmax[0], vmax[1], vmax[2])
                sw.write_chunk_with_children(Wad2Chunks.StaticVisibilityBox, _vbox)

                cmin = s.get('col_box_min', (0, 0, 0))
                cmax = s.get('col_box_max', (0, 0, 0))
                def _cbox(cw2):
                    cw2.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMin, cmin[0], cmin[1], cmin[2])
                    cw2.write_chunk_vector3(Wad2Chunks.MeshBoundingBoxMax, cmax[0], cmax[1], cmax[2])
                sw.write_chunk_with_children(Wad2Chunks.StaticCollisionBox, _cbox)

            w.write_chunk_with_children(Wad2Chunks.Static2, _static_inner)
    cw.write_chunk_with_children(Wad2Chunks.Statics, _inner)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _write_metadata(cw: ChunkWriter, timestamp, user_notes: str):
    def _inner(w):
        if timestamp:
            def _ts(tw):
                tw.write_raw_leb128_signed(timestamp[0])
                tw.write_raw_leb128_signed(timestamp[1])
                tw.write_raw_leb128_signed(timestamp[2])
                tw.write_raw_leb128_signed(timestamp[3])
                tw.write_raw_leb128_signed(timestamp[4])
                tw.write_raw_leb128_signed(timestamp[5])
            w.write_chunk_with_children(Wad2Chunks.Timestamp, _ts)
        w.write_chunk_string(Wad2Chunks.UserNotes, user_notes or '')
    cw.write_chunk_with_children(Wad2Chunks.Metadata, _inner)
