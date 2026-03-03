"""
WAD2 Writer — exports Blender scene data to WAD2 format.

Binary format matches Tomb Editor's Wad2Writer.cs / Wad2Loader.cs exactly:
  - ChunkWriter framing: magic, chunk IDs as LEB128-length-prefixed strings,
    chunk sizes as LEB128, nested children terminated by zero-length ID.
  - Textures stored as raw BGRA byte arrays.
  - Polygons written as W2Tr2/W2Uq2 with ParentArea, per-vertex UVs in
    pixel coordinates, LEB128-encoded BlendMode, and boolean DoubleSided.

Reference chunk IDs from Wad2Chunks.cs.
"""

import struct
import io
import math
from typing import List, Dict, Tuple, Optional, BinaryIO


# ---------------------------------------------------------------------------
# LEB128 helpers
# ---------------------------------------------------------------------------

def write_leb128_unsigned(f: BinaryIO, value: int):
    """Write an unsigned LEB128 integer."""
    if value < 0:
        raise ValueError(f"Cannot write negative value {value} as unsigned LEB128")
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        f.write(struct.pack('B', byte))
        if value == 0:
            break


def write_leb128_signed(f: BinaryIO, value: int):
    """Write a signed LEB128 integer (matches C# LEB128.Write(long))."""
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        # Sign bit of byte is second high order bit (0x40)
        if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40) != 0):
            more = False
        else:
            byte |= 0x80
        f.write(struct.pack('B', byte))


def write_string(f: BinaryIO, s: str):
    """Write a UTF-8 length-prefixed string (LEB128 length)."""
    encoded = s.encode('utf-8')
    write_leb128_unsigned(f, len(encoded))
    f.write(encoded)


def write_string_utf8(f: BinaryIO, s: str):
    """Write a UTF-8 string with int32 length prefix.

    Matches C# ``BinaryWriterFast.WriteStringUTF8`` which uses a 4-byte
    little-endian length prefix, NOT LEB128.
    """
    encoded = s.encode('utf-8')
    f.write(struct.pack('<i', len(encoded)))
    f.write(encoded)


def write_vector2(f: BinaryIO, x: float, y: float):
    f.write(struct.pack('<ff', x, y))


def write_vector3(f: BinaryIO, x: float, y: float, z: float):
    f.write(struct.pack('<fff', x, y, z))


def write_vector4(f: BinaryIO, x: float, y: float, z: float, w: float):
    f.write(struct.pack('<ffff', x, y, z, w))


def write_bool(f: BinaryIO, val: bool):
    f.write(struct.pack('?', val))


def write_float(f: BinaryIO, val: float):
    f.write(struct.pack('<f', val))


# ---------------------------------------------------------------------------
# Chunk writer (mirrors C# ChunkWriter)
# ---------------------------------------------------------------------------

class ChunkWriter:
    """
    Writes WAD2 chunks.  Each chunk is:
      - Chunk ID: LEB128 string length + UTF-8 bytes
      - Chunk size: LEB128 uint (size of the body that follows)
      - Chunk body: raw bytes
    A parent chunk's body contains child chunks terminated by a zero-length
    chunk ID (a single 0x00 byte).
    """

    def __init__(self, stream: BinaryIO):
        self.stream = stream

    # -- low-level helpers --------------------------------------------------

    def _write_chunk_id(self, chunk_id: str):
        """Write a chunk ID as a length-prefixed UTF-8 string."""
        encoded = chunk_id.encode('utf-8')
        write_leb128_unsigned(self.stream, len(encoded))
        self.stream.write(encoded)

    def _write_chunk_end(self):
        """Write the terminator for a children-bearing chunk (zero-length ID)."""
        write_leb128_unsigned(self.stream, 0)

    # -- public API ---------------------------------------------------------

    def write_chunk_with_children(self, chunk_id: str, write_fn):
        """Write a chunk that contains child chunks.

        *write_fn* is called to write the children; afterwards a terminator
        is emitted.  The whole thing is buffered so the chunk size can be
        back-patched.
        """
        # Buffer the body so we know its size before writing
        body_buf = io.BytesIO()
        saved = self.stream
        self.stream = body_buf
        write_fn()
        self._write_chunk_end()
        self.stream = saved

        body = body_buf.getvalue()
        self._write_chunk_id(chunk_id)
        write_leb128_unsigned(self.stream, len(body))
        self.stream.write(body)

    def write_chunk_raw(self, chunk_id: str, data: bytes):
        """Write a chunk whose body is a raw byte blob."""
        self._write_chunk_id(chunk_id)
        write_leb128_unsigned(self.stream, len(data))
        self.stream.write(data)

    def write_chunk_int(self, chunk_id: str, value: int):
        """Write a chunk containing a single LEB128 signed int."""
        buf = io.BytesIO()
        write_leb128_signed(buf, value)
        self.write_chunk_raw(chunk_id, buf.getvalue())

    def write_chunk_float(self, chunk_id: str, value: float):
        buf = struct.pack('<f', value)
        self.write_chunk_raw(chunk_id, buf)

    def write_chunk_bool(self, chunk_id: str, value: bool):
        self.write_chunk_raw(chunk_id, struct.pack('?', value))

    def write_chunk_string(self, chunk_id: str, s: str):
        buf = io.BytesIO()
        write_string(buf, s)
        self.write_chunk_raw(chunk_id, buf.getvalue())

    def write_chunk_vector3(self, chunk_id: str, v):
        """v is (x, y, z) or any 3-element iterable."""
        buf = struct.pack('<fff', v[0], v[1], v[2])
        self.write_chunk_raw(chunk_id, buf)

    def write_chunk_vector2(self, chunk_id: str, v):
        buf = struct.pack('<ff', v[0], v[1])
        self.write_chunk_raw(chunk_id, buf)

    def write_chunk_vector4(self, chunk_id: str, v):
        buf = struct.pack('<ffff', v[0], v[1], v[2], v[3])
        self.write_chunk_raw(chunk_id, buf)

    def write_chunk_bytes(self, chunk_id: str, data: bytes):
        """Write a chunk whose body is a raw byte array (e.g. texture data)."""
        self.write_chunk_raw(chunk_id, data)


# ---------------------------------------------------------------------------
# Chunk IDs — must match Wad2Chunks.cs exactly
# ---------------------------------------------------------------------------

class W2:
    """WAD2 chunk ID strings matching Wad2Chunks.cs."""
    GameVersion = "W2SuggestedGameVersion"
    SoundSystem = "W2SoundSystem"
    Metadata = "W2Metadata"
    Timestamp = "W2Timestamp"
    UserNotes = "W2UserNotes"

    # Textures
    Textures = "W2Textures"
    Texture = "W2Txt"
    TextureIndex = "W2Index"
    TextureData = "W2TxtData"
    TextureName = "W2TxtName"
    TextureRelativePath = "W2TxtRelPath"

    # Meshes
    Meshes = "W2Meshes"
    Mesh = "W2Mesh"
    MeshIndex = "W2Index"
    MeshName = "W2MeshName"
    MeshSphere = "W2MeshSphere"
    MeshSphereCenter = "W2SphC"
    MeshSphereRadius = "W2SphR"
    MeshBoundingBox = "W2BBox"
    MeshBoundingBoxMin = "W2BBMin"
    MeshBoundingBoxMax = "W2BBMax"
    MeshVertexPositions = "W2VrtPos"
    MeshVertexPosition = "W2Pos"
    MeshVertexNormals = "W2VrtNorm"
    MeshVertexNormal = "W2N"
    MeshVertexShades = "W2VrtShd"
    MeshVertexColor = "W2VxCol"
    MeshVertexAttributes = "W2VrtAttr"
    MeshVertexAttribute = "W2VxAttr"
    MeshVertexWeights = "W2VrtWghts"
    MeshVertexWeight = "W2VrtWght"
    MeshLightingType = "W2MeshLightType"
    MeshVisibility = "W2MeshVisible"
    MeshPolygons = "W2Polys"
    MeshTriangle2 = "W2Tr2"
    MeshQuad2 = "W2Uq2"

    # Moveables
    Moveables = "W2Moveables"
    Moveable = "W2Moveable"
    MoveableSkin = "W2MovSkin"
    MoveableBone = "W2Bone2"
    MoveableBoneName = "W2BoneName"
    MoveableBoneTranslation = "W2BoneTrans"
    MoveableBoneMeshPointer = "W2BoneMesh"

    # Animations
    Animation = "W2Ani3"
    AnimationName = "W2AnmName"
    AnimationVelocities = "W2AniV"
    KeyFrames = "W2Kfs"
    KeyFrame = "W2Kf"
    KeyFrameOffset = "W2KfOffs"
    KeyFrameBoundingBox = "W2KfBB"
    KeyFrameAngle = "W2KfA"
    StateChange = "W2StCh"
    Dispatch = "W2Disp2"
    AnimCommand = "W2Cmd2"
    AnimCommandSoundInfo = "W2CmdSnd"
    CurveStart = "W2CurveStart"
    CurveEnd = "W2CurveEnd"
    CurveStartHandle = "W2CurveHStart"
    CurveEndHandle = "W2CurveHEnd"

    # Statics
    Statics = "W2Statics"
    Static = "W2Static2"
    StaticVisibilityBox = "W2StaticVB"
    StaticCollisionBox = "W2StaticCB"
    StaticAmbientLight = "W2StaticAmbientLight"
    StaticShatter = "W2StaticShatter"
    StaticShatterSound = "W2StaticShatterSound"
    StaticLight = "W2StaticLight"
    StaticLightPosition = "W2StaticLightPos"
    StaticLightRadius = "W2StaticLightR"
    StaticLightIntensity = "W2StaticLightI"

    # Sprites (stubs)
    Sprites = "W2Sprites"
    SpriteSequences = "W2SpriteSequences"

    # Animated texture sets (stubs)
    AnimatedTextureSets = "W2AnimatedTextureSets"


# ---------------------------------------------------------------------------
# Game version enum (matches C# TRVersion.Game)
# ---------------------------------------------------------------------------

GAME_VERSIONS = {
    'TR1': 0, 'TR2': 1, 'TR3': 2, 'TR4': 3, 'TR5': 4,
    'TRNG': 5, 'TombEngine': 6,
    'TR1X': 7, 'TR2X': 8,
}


# ---------------------------------------------------------------------------
# Write functions (match C# Wad2Writer exactly)
# ---------------------------------------------------------------------------

def _write_texture(cw: ChunkWriter, texture: dict, index: int):
    """Write a single texture chunk.

    C# layout:
        LEB128 width, LEB128 height,
        W2TxtName string, W2TxtRelPath string, W2TxtData byte[]
    """
    def _inner():
        write_leb128_unsigned(cw.stream, texture['width'])
        write_leb128_unsigned(cw.stream, texture['height'])
        cw.write_chunk_string(W2.TextureName, texture.get('name', ''))
        cw.write_chunk_string(W2.TextureRelativePath, texture.get('rel_path', ''))
        cw.write_chunk_bytes(W2.TextureData, texture['data'])

    cw.write_chunk_with_children(W2.Texture, _inner)


def _write_textures(cw: ChunkWriter, textures: List[dict]):
    def _inner():
        for i, tex in enumerate(textures):
            _write_texture(cw, tex, i)
    cw.write_chunk_with_children(W2.Textures, _inner)


def _write_mesh(cw: ChunkWriter, mesh: dict, texture_map: Dict[int, int]):
    """Write a single mesh chunk.

    mesh dict keys:
        name, positions [(x,y,z)...], normals [(x,y,z)...],
        shades [float...] (vertex colours as 0-1 greyscale or (r,g,b)),
        triangles [poly_dict...], quads [poly_dict...],
        sphere {center, radius}, bbox {min, max}
    """
    def _inner():
        cw.write_chunk_int(W2.MeshIndex, 0)
        cw.write_chunk_string(W2.MeshName, mesh.get('name', ''))

        # Bounding sphere
        sphere = mesh.get('sphere', {})
        center = sphere.get('center', (0, 0, 0))
        radius = sphere.get('radius', 0)
        def _sphere():
            cw.write_chunk_vector3(W2.MeshSphereCenter, center)
            cw.write_chunk_float(W2.MeshSphereRadius, float(radius))
        cw.write_chunk_with_children(W2.MeshSphere, _sphere)

        # Bounding box
        bbox = mesh.get('bbox', {})
        def _bbox():
            cw.write_chunk_vector3(W2.MeshBoundingBoxMin, bbox.get('min', (0, 0, 0)))
            cw.write_chunk_vector3(W2.MeshBoundingBoxMax, bbox.get('max', (0, 0, 0)))
        cw.write_chunk_with_children(W2.MeshBoundingBox, _bbox)

        # Vertex positions
        def _positions():
            for pos in mesh.get('positions', []):
                cw.write_chunk_vector3(W2.MeshVertexPosition, pos)
        cw.write_chunk_with_children(W2.MeshVertexPositions, _positions)

        # Vertex normals
        def _normals():
            for n in mesh.get('normals', []):
                cw.write_chunk_vector3(W2.MeshVertexNormal, n)
        cw.write_chunk_with_children(W2.MeshVertexNormals, _normals)

        # Vertex colours / shades
        shades = mesh.get('shades', [])
        if shades:
            def _shades():
                for shade in shades:
                    if isinstance(shade, (int, float)):
                        v = float(shade)
                        cw.write_chunk_vector3(W2.MeshVertexColor, (v, v, v))
                    else:
                        cw.write_chunk_vector3(W2.MeshVertexColor, shade)
            cw.write_chunk_with_children(W2.MeshVertexShades, _shades)

        # Vertex attributes (stub — write empty container)
        cw.write_chunk_with_children(W2.MeshVertexAttributes, lambda: None)

        # Vertex weights (stub)
        cw.write_chunk_with_children(W2.MeshVertexWeights, lambda: None)

        # Lighting type: 0 = default
        cw.write_chunk_int(W2.MeshLightingType, 0)
        # Visibility: False = visible
        cw.write_chunk_bool(W2.MeshVisibility, False)

        # Polygons
        def _polys():
            for poly in mesh.get('triangles', []):
                _write_polygon(cw, poly, is_quad=False, texture_map=texture_map)
            for poly in mesh.get('quads', []):
                _write_polygon(cw, poly, is_quad=True, texture_map=texture_map)
        cw.write_chunk_with_children(W2.MeshPolygons, _polys)

    cw.write_chunk_with_children(W2.Mesh, _inner)


def _write_polygon(cw: ChunkWriter, poly: dict, is_quad: bool, texture_map: Dict[int, int]):
    """Write a single polygon chunk (W2Tr2 or W2Uq2).

    C# binary layout inside the chunk body:
        LEB128 Index0, Index1, Index2, [Index3 if quad]
        LEB128 ShineStrength
        LEB128 TextureIndex
        Vector2 ParentArea.Start  (always written for W2Tr2/W2Uq2)
        Vector2 ParentArea.End
        Vector2 TexCoord0, TexCoord1, TexCoord2, [TexCoord3 if quad]
        LEB128 signed BlendMode
        bool DoubleSided
    """
    chunk_id = W2.MeshQuad2 if is_quad else W2.MeshTriangle2
    indices = poly.get('indices', [])
    vertex_count = 4 if is_quad else 3

    def _inner():
        # Vertex indices
        for i in range(vertex_count):
            idx = indices[i] if i < len(indices) else 0
            write_leb128_unsigned(cw.stream, idx)

        # Shine strength
        write_leb128_unsigned(cw.stream, poly.get('shine', 0))

        # Texture index — map material index to WAD2 texture table index
        mat_idx = poly.get('texture', 0)
        tex_idx = texture_map.get(mat_idx, 0)
        write_leb128_unsigned(cw.stream, tex_idx)

        # ParentArea (Start + End) — write zeros (no parent atlas)
        write_vector2(cw.stream, 0.0, 0.0)
        write_vector2(cw.stream, 0.0, 0.0)

        # UV coordinates in pixel space
        uvs = poly.get('uvs', [])
        for i in range(vertex_count):
            if i < len(uvs):
                u, v = uvs[i]
            else:
                u, v = 0.0, 0.0
            write_vector2(cw.stream, u, v)

        # BlendMode as LEB128 signed long
        write_leb128_signed(cw.stream, poly.get('blend_mode', 0))

        # DoubleSided as boolean byte
        write_bool(cw.stream, poly.get('double_sided', False))

    cw.write_chunk_with_children(chunk_id, _inner)


def _write_bone(cw: ChunkWriter, bone: dict, index: int):
    """Write a single bone chunk (W2Bone2).

    C# layout:
        LEB128 OpCode
        string Name (raw UTF-8, not chunk)
        W2BoneTrans Vector3
        W2BoneMesh int
    """
    def _inner():
        write_leb128_unsigned(cw.stream, bone.get('op', 0))
        write_string_utf8(cw.stream, bone.get('name', f'bone_{index}'))
        cw.write_chunk_vector3(W2.MoveableBoneTranslation, bone.get('translation', (0, 0, 0)))
        cw.write_chunk_int(W2.MoveableBoneMeshPointer, bone.get('mesh', index))
    cw.write_chunk_with_children(W2.MoveableBone, _inner)


def _write_animation(cw: ChunkWriter, anim: dict):
    """Write a single animation chunk (W2Ani3)."""
    def _inner():
        write_leb128_unsigned(cw.stream, anim.get('state_id', 0))
        write_leb128_unsigned(cw.stream, anim.get('end_frame', 0))
        write_leb128_unsigned(cw.stream, anim.get('frame_rate', 1))
        write_leb128_unsigned(cw.stream, anim.get('next_animation', 0))
        write_leb128_unsigned(cw.stream, anim.get('next_frame', 0))

        # Blend frame count (new in Animation3 format)
        write_leb128_unsigned(cw.stream, 0)

        # Blend curves (start, end, handles) — default linear
        cw.write_chunk_vector2(W2.CurveStart, (0.0, 0.0))
        cw.write_chunk_vector2(W2.CurveEnd, (1.0, 1.0))
        cw.write_chunk_vector2(W2.CurveStartHandle, (0.25, 0.25))
        cw.write_chunk_vector2(W2.CurveEndHandle, (0.75, 0.75))

        # Animation name
        cw.write_chunk_string(W2.AnimationName, anim.get('name', ''))

        # Keyframes
        for kf in anim.get('keyframes', []):
            _write_keyframe(cw, kf)

        # State changes
        for state_id, dispatches in anim.get('state_changes', {}).items():
            _write_state_change(cw, state_id, dispatches)

        # Anim commands
        for cmd in anim.get('commands', []):
            _write_anim_command(cw, cmd)

        # Velocities: (startVel, endVel, startLateral, endLateral)
        vel = anim.get('velocity', (0.0, 0.0, 0.0, 0.0))
        cw.write_chunk_vector4(W2.AnimationVelocities, vel)

    cw.write_chunk_with_children(W2.Animation, _inner)


def _write_keyframe(cw: ChunkWriter, kf: dict):
    def _inner():
        offset = kf.get('offset', (0, 0, 0))
        cw.write_chunk_vector3(W2.KeyFrameOffset, offset)

        bbox = kf.get('bbox', {})
        def _bbox():
            cw.write_chunk_vector3(W2.MeshBoundingBoxMin, bbox.get('min', (-100, -100, -100)))
            cw.write_chunk_vector3(W2.MeshBoundingBoxMax, bbox.get('max', (100, 100, 100)))
        cw.write_chunk_with_children(W2.KeyFrameBoundingBox, _bbox)

        for rot in kf.get('rotations', []):
            # Rotations stored as euler angles (x, y, z) in radians
            if len(rot) == 4:
                # Quaternion (w, x, y, z) — convert to euler
                w, x, y, z = rot
                # Simple quaternion to euler (XYZ order)
                sinr_cosp = 2 * (w * x + y * z)
                cosr_cosp = 1 - 2 * (x * x + y * y)
                rx = math.atan2(sinr_cosp, cosr_cosp)

                sinp = 2 * (w * y - z * x)
                sinp = max(-1.0, min(1.0, sinp))
                ry = math.asin(sinp)

                siny_cosp = 2 * (w * z + x * y)
                cosy_cosp = 1 - 2 * (y * y + z * z)
                rz = math.atan2(siny_cosp, cosy_cosp)

                cw.write_chunk_vector3(W2.KeyFrameAngle, (
                    math.degrees(rx), math.degrees(ry), math.degrees(rz)
                ))
            elif len(rot) == 3:
                cw.write_chunk_vector3(W2.KeyFrameAngle, rot)
            else:
                cw.write_chunk_vector3(W2.KeyFrameAngle, (0, 0, 0))

    cw.write_chunk_with_children(W2.KeyFrame, _inner)


def _write_state_change(cw: ChunkWriter, state_id, dispatches):
    def _inner():
        write_leb128_unsigned(cw.stream, state_id)
        for d in dispatches:
            _write_dispatch(cw, d)
    cw.write_chunk_with_children(W2.StateChange, _inner)


def _write_dispatch(cw: ChunkWriter, d):
    def _inner():
        if isinstance(d, dict):
            write_leb128_unsigned(cw.stream, d.get('in_frame', 0))
            write_leb128_unsigned(cw.stream, d.get('out_frame', 0))
            write_leb128_unsigned(cw.stream, d.get('next_animation', 0))
            write_leb128_unsigned(cw.stream, d.get('next_frame_low', 0))
            write_leb128_unsigned(cw.stream, d.get('next_frame_high', 0))
            write_leb128_unsigned(cw.stream, 0)  # blend frame count
            cw.write_chunk_vector2(W2.CurveStart, (0.0, 0.0))
            cw.write_chunk_vector2(W2.CurveEnd, (1.0, 1.0))
            cw.write_chunk_vector2(W2.CurveStartHandle, (0.25, 0.25))
            cw.write_chunk_vector2(W2.CurveEndHandle, (0.75, 0.75))
        else:
            # model.Dispatch tuple: (in_range, out_range, next_anim, frame_in)
            write_leb128_unsigned(cw.stream, d[0] if len(d) > 0 else 0)
            write_leb128_unsigned(cw.stream, d[1] if len(d) > 1 else 0)
            write_leb128_unsigned(cw.stream, d[2] if len(d) > 2 else 0)
            write_leb128_unsigned(cw.stream, d[3] if len(d) > 3 else 0)
            write_leb128_unsigned(cw.stream, 0)  # next_frame_high
            write_leb128_unsigned(cw.stream, 0)  # blend frame count
            cw.write_chunk_vector2(W2.CurveStart, (0.0, 0.0))
            cw.write_chunk_vector2(W2.CurveEnd, (1.0, 1.0))
            cw.write_chunk_vector2(W2.CurveStartHandle, (0.25, 0.25))
            cw.write_chunk_vector2(W2.CurveEndHandle, (0.75, 0.75))
    cw.write_chunk_with_children(W2.Dispatch, _inner)


def _write_anim_command(cw: ChunkWriter, cmd):
    def _inner():
        if isinstance(cmd, (list, tuple)):
            write_leb128_unsigned(cw.stream, cmd[0] if len(cmd) > 0 else 0)
            write_leb128_signed(cw.stream, cmd[1] if len(cmd) > 1 else 0)
            write_leb128_signed(cw.stream, cmd[2] if len(cmd) > 2 else 0)
            write_leb128_signed(cw.stream, cmd[3] if len(cmd) > 3 else 0)
        else:
            write_leb128_unsigned(cw.stream, 0)
            write_leb128_signed(cw.stream, 0)
            write_leb128_signed(cw.stream, 0)
            write_leb128_signed(cw.stream, 0)
        cw.write_chunk_int(W2.AnimCommandSoundInfo, -1)
    cw.write_chunk_with_children(W2.AnimCommand, _inner)


def _write_moveable(cw: ChunkWriter, moveable: dict, texture_map: Dict[int, int]):
    """Write a single moveable with meshes, bones, and animations."""
    def _inner():
        write_leb128_unsigned(cw.stream, moveable['id'])

        # Write meshes
        for mesh in moveable.get('meshes', []):
            _write_mesh(cw, mesh, texture_map)

        # Skin mesh (optional)
        skin = moveable.get('skin')
        if skin:
            def _skin():
                _write_mesh(cw, skin, texture_map)
            cw.write_chunk_with_children(W2.MoveableSkin, _skin)

        # Bones
        for i, bone in enumerate(moveable.get('bones', [])):
            _write_bone(cw, bone, i)

        # Animations
        for anim in moveable.get('animations', []):
            _write_animation(cw, anim)

    cw.write_chunk_with_children(W2.Moveable, _inner)


def _write_moveables(cw: ChunkWriter, moveables: List[dict], texture_map: Dict[int, int]):
    def _inner():
        for mov in moveables:
            _write_moveable(cw, mov, texture_map)
    cw.write_chunk_with_children(W2.Moveables, _inner)


def _write_static(cw: ChunkWriter, static: dict, texture_map: Dict[int, int]):
    """Write a single static object (W2Static2)."""
    def _inner():
        write_leb128_unsigned(cw.stream, static['id'])
        write_leb128_unsigned(cw.stream, static.get('flags', 0))

        _write_mesh(cw, static['mesh'], texture_map)

        cw.write_chunk_int(W2.StaticAmbientLight, static.get('ambient_light', 0))
        cw.write_chunk_bool(W2.StaticShatter, static.get('shatter', False))
        cw.write_chunk_int(W2.StaticShatterSound, static.get('shatter_sound', 0))

        # Lights (optional)
        for light in static.get('lights', []):
            def _light():
                cw.write_chunk_vector3(W2.StaticLightPosition, light.get('position', (0, 0, 0)))
                cw.write_chunk_float(W2.StaticLightRadius, light.get('radius', 1.0))
                cw.write_chunk_float(W2.StaticLightIntensity, light.get('intensity', 0.5))
            cw.write_chunk_with_children(W2.StaticLight, _light)

        # Visibility box
        vis_box = static.get('visibility_box', {})
        def _vis():
            cw.write_chunk_vector3(W2.MeshBoundingBoxMin, vis_box.get('min', (0, 0, 0)))
            cw.write_chunk_vector3(W2.MeshBoundingBoxMax, vis_box.get('max', (0, 0, 0)))
        cw.write_chunk_with_children(W2.StaticVisibilityBox, _vis)

        # Collision box
        col_box = static.get('collision_box', vis_box)
        def _col():
            cw.write_chunk_vector3(W2.MeshBoundingBoxMin, col_box.get('min', (0, 0, 0)))
            cw.write_chunk_vector3(W2.MeshBoundingBoxMax, col_box.get('max', (0, 0, 0)))
        cw.write_chunk_with_children(W2.StaticCollisionBox, _col)

    cw.write_chunk_with_children(W2.Static, _inner)


def _write_statics(cw: ChunkWriter, statics: List[dict], texture_map: Dict[int, int]):
    def _inner():
        for s in statics:
            _write_static(cw, s, texture_map)
    cw.write_chunk_with_children(W2.Statics, _inner)


def _write_metadata(cw: ChunkWriter, game_version: str = 'TR4'):
    """Write metadata: timestamp and user notes."""
    import datetime
    now = datetime.datetime.now()

    def _inner():
        def _timestamp():
            write_leb128_unsigned(cw.stream, now.year)
            write_leb128_unsigned(cw.stream, now.month)
            write_leb128_unsigned(cw.stream, now.day)
            write_leb128_unsigned(cw.stream, now.hour)
            write_leb128_unsigned(cw.stream, now.minute)
            write_leb128_unsigned(cw.stream, now.second)
        cw.write_chunk_with_children(W2.Timestamp, _timestamp)
        cw.write_chunk_string(W2.UserNotes, '')

    cw.write_chunk_with_children(W2.Metadata, _inner)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_wad2(filepath: str, wad_data: dict, options: dict = None):
    """Write a complete WAD2 file.

    Parameters
    ----------
    filepath : str
        Output .wad2 file path.
    wad_data : dict
        Keys: 'textures' (list of dict), 'moveables' (list of dict),
              'statics' (list of dict).
        Each texture dict: {width, height, data (BGRA bytes), name, rel_path}
        Each moveable dict: {id, meshes, bones, animations, skin?}
        Each static dict: {id, mesh, visibility_box, collision_box, flags}
    options : dict, optional
        Keys: 'game' (str), 'scale' (float).
    """
    if options is None:
        options = {}

    game = options.get('game', 'TR4')
    textures = wad_data.get('textures', [])
    moveables = wad_data.get('moveables', [])
    statics = wad_data.get('statics', [])

    # Build texture map: material_index -> WAD2 texture table index
    texture_map = {}
    for i, tex in enumerate(textures):
        texture_map[tex.get('index', i)] = i

    # Write to memory first, then save (same strategy as C# writer)
    buf = io.BytesIO()

    # Magic number: WAD2
    buf.write(b'WAD2')

    # Compression type: 0 = None (matches C# ChunkWriter.Compression.None)
    buf.write(struct.pack('<I', 0))

    cw = ChunkWriter(buf)

    # Game version
    game_ver = GAME_VERSIONS.get(game, 3)  # Default TR4
    cw.write_chunk_int(W2.GameVersion, game_ver)

    # Sound system: XML = 1
    cw.write_chunk_int(W2.SoundSystem, 1)

    # Textures
    _write_textures(cw, textures)

    # Sprites (empty)
    cw.write_chunk_with_children(W2.Sprites, lambda: None)

    # Sprite sequences (empty)
    cw.write_chunk_with_children(W2.SpriteSequences, lambda: None)

    # Moveables
    _write_moveables(cw, moveables, texture_map)

    # Statics
    _write_statics(cw, statics, texture_map)

    # Metadata
    _write_metadata(cw, game)

    # Animated texture sets (empty)
    cw.write_chunk_with_children(W2.AnimatedTextureSets, lambda: None)

    # Final terminator (end of root)
    cw._write_chunk_end()

    # Write to file
    with open(filepath, 'wb') as f:
        f.write(buf.getvalue())

    print(f"[WAD2 Export] Written {len(buf.getvalue())} bytes to {filepath}")
    print(f"[WAD2 Export] {len(textures)} textures, {len(moveables)} moveables, {len(statics)} statics")
