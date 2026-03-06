"""
WAD2 File Format Reader
Based on Tomb Editor's Wad2Loader.cs
Implements chunk-based binary reading with LEB128 encoding
"""

import struct
import io
import zlib
from typing import BinaryIO, Any, Dict, List, Tuple, Optional
from . import model
from . import wad2_chunks


def _decode_png_to_rgba(png_data: bytes) -> Tuple[Optional[bytes], int, int]:
    """
    Decode PNG bytes to raw RGBA pixel data.
    Returns (rgba_bytes, width, height) or (None, 0, 0) on failure.
    """
    buf = io.BytesIO(png_data)

    # Verify PNG signature
    sig = buf.read(8)
    if sig != b'\x89PNG\r\n\x1a\n':
        return None, 0, 0

    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    idat_chunks = []

    while True:
        header = buf.read(8)
        if len(header) < 8:
            break
        length, chunk_type = struct.unpack('>I4s', header)
        chunk_data = buf.read(length)
        buf.read(4)  # CRC

        if chunk_type == b'IHDR':
            width, height, bit_depth, color_type = struct.unpack('>IIBB', chunk_data[:10])
        elif chunk_type == b'IDAT':
            idat_chunks.append(chunk_data)
        elif chunk_type == b'IEND':
            break

    if width == 0 or height == 0 or not idat_chunks:
        return None, 0, 0

    # Decompress all IDAT data
    raw = zlib.decompress(b''.join(idat_chunks))

    # Determine bytes per pixel based on color type
    if color_type == 6:      # RGBA
        bpp = 4
    elif color_type == 2:    # RGB
        bpp = 3
    elif color_type == 4:    # Greyscale + Alpha
        bpp = 2
    elif color_type == 0:    # Greyscale
        bpp = 1
    else:
        return None, 0, 0

    stride = width * bpp + 1  # +1 for filter byte per scanline
    if len(raw) < height * stride:
        return None, 0, 0

    # Reconstruct scanlines with PNG filtering
    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        elif pb <= pc:
            return b
        return c

    prev_row = bytearray(width * bpp)
    rgba = bytearray(width * height * 4)

    for y in range(height):
        offset = y * stride
        filter_type = raw[offset]
        row = bytearray(raw[offset + 1: offset + 1 + width * bpp])

        # Apply PNG filter
        if filter_type == 1:  # Sub
            for i in range(bpp, len(row)):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(len(row)):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(len(row)):
                a = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + (a + prev_row[i]) // 2) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(len(row)):
                a = row[i - bpp] if i >= bpp else 0
                b = prev_row[i]
                c = prev_row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + paeth(a, b, c)) & 0xFF

        # Convert to RGBA
        for x in range(width):
            dst = (y * width + x) * 4
            if bpp == 4:       # RGBA
                src = x * 4
                rgba[dst] = row[src]
                rgba[dst + 1] = row[src + 1]
                rgba[dst + 2] = row[src + 2]
                rgba[dst + 3] = row[src + 3]
            elif bpp == 3:     # RGB -> RGBA
                src = x * 3
                rgba[dst] = row[src]
                rgba[dst + 1] = row[src + 1]
                rgba[dst + 2] = row[src + 2]
                rgba[dst + 3] = 255
            elif bpp == 2:     # GA -> RGBA
                src = x * 2
                rgba[dst] = row[src]
                rgba[dst + 1] = row[src]
                rgba[dst + 2] = row[src]
                rgba[dst + 3] = row[src + 1]
            elif bpp == 1:     # G -> RGBA
                rgba[dst] = row[x]
                rgba[dst + 1] = row[x]
                rgba[dst + 2] = row[x]
                rgba[dst + 3] = 255

        prev_row = row

    return bytes(rgba), width, height


def read_leb128_uint(f: BinaryIO) -> int:
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


def read_leb128_int(f: BinaryIO) -> int:
    """Read LEB128 variable-length signed integer"""
    result = 0
    shift = 0
    byte = 0
    while True:
        byte = struct.unpack('B', f.read(1))[0]
        result |= (byte & 0x7F) << shift
        shift += 7
        if (byte & 0x80) == 0:
            break

    # Sign extend if necessary
    if shift < 64 and (byte & 0x40):
        result |= -(1 << shift)

    return result


def read_string(f: BinaryIO, debug=False) -> str:
    """Read length-prefixed string"""
    pos_before = f.tell() if debug else 0
    length = read_leb128_uint(f)
    if debug:
        print(f'    read_string at 0x{pos_before:04x}: length={length}')
    if length == 0:
        return ""
    data = f.read(length)
    result = data.decode('utf-8', errors='replace')
    if debug:
        print(f'    read_string result: "{result[:50]}"')
    return result


def read_vector3(f: BinaryIO) -> Tuple[float, float, float]:
    """Read 3 floats as a vector"""
    return struct.unpack('fff', f.read(12))


def read_vector2(f: BinaryIO) -> Tuple[float, float]:
    """Read 2 floats as a vector"""
    return struct.unpack('ff', f.read(8))

def read_vector4(f: BinaryIO) -> Tuple[float, float, float, float]:
    """Read 4 floats as a vector"""
    return struct.unpack('ffff', f.read(16))


def read_bool(f: BinaryIO) -> bool:
    """Read boolean value"""
    return struct.unpack('?', f.read(1))[0]


def read_float(f: BinaryIO) -> float:
    """Read single float"""
    return struct.unpack('f', f.read(4))[0]


def read_chunk_id(f: BinaryIO) -> bytes:
    """Read chunk identifier (length-prefixed string as bytes)"""
    length = read_leb128_uint(f)
    if length == 0:
        return b''
    return f.read(length)


def read_leb128_uint_from(data: bytes, offset: int) -> Tuple[Optional[int], int]:
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            return None, offset
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset


def read_chunk_id_from(data: bytes, offset: int) -> Tuple[Optional[bytes], int]:
    length, offset = read_leb128_uint_from(data, offset)
    if length is None or length == 0:
        return None, offset
    if offset + length > len(data):
        return None, offset
    chunk_id = data[offset:offset + length]
    offset += length
    return chunk_id, offset


class ChunkReader:
    """Reads chunks from WAD2 file"""

    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.chunk_stack = []

    def read_chunk_start(self) -> Optional[bytes]:
        """Read the start of a chunk, returning its ID or None if no more chunks"""
        try:
            # If we have a parent chunk, check if we've read all its data
            if self.chunk_stack:
                parent_id, parent_size, parent_start = self.chunk_stack[-1]
                current_pos = self.stream.tell()
                if current_pos >= parent_start + parent_size:
                    return None

            chunk_id = read_chunk_id(self.stream)
            if not chunk_id:
                return None
            chunk_size = read_leb128_uint(self.stream)
            self.chunk_stack.append((chunk_id, chunk_size, self.stream.tell()))
            return chunk_id
        except Exception as e:
            return None

    def read_chunk_end(self):
        """Finish reading current chunk"""
        if self.chunk_stack:
            chunk_id, chunk_size, start_pos = self.chunk_stack.pop()
            # Ensure we're at the end of the chunk
            expected_pos = start_pos + chunk_size
            current_pos = self.stream.tell()
            if current_pos < expected_pos:
                # Skip remaining bytes
                self.stream.seek(expected_pos)

    def read_chunk_string(self) -> str:
        """Read the current chunk's content as a UTF-8 string"""
        if not self.chunk_stack:
            return ""
        chunk_id, chunk_size, start_pos = self.chunk_stack[-1]
        data = self.stream.read(chunk_size)
        return data.decode('utf-8', errors='replace')

    def get_chunk_size(self) -> int:
        """Get the size of the current chunk"""
        if not self.chunk_stack:
            return 0
        return self.chunk_stack[-1][1]


class Wad2Loader:
    """Loads WAD2 files"""

    def __init__(self):
        self.version = 0
        self.sound_system = 0
        self.textures = {}
        self.samples = {}
        self.sound_infos = {}
        self.meshes = {}
        self.sprites = {}
        self.sprite_sequences = {}
        self.moveables = {}
        self.statics = {}
        self.animated_texture_sets = {}

    def _fix_axis_vec3(self, vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Convert WAD2 axes (Y-up) to Blender (Z-up) and face -Y."""
        return (-vec[0], -vec[2], vec[1])

    def _mat_mul(self, a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
        return [
            [
                a[0][0] * b[0][j] + a[0][1] * b[1][j] + a[0][2] * b[2][j]
                for j in range(3)
            ],
            [
                a[1][0] * b[0][j] + a[1][1] * b[1][j] + a[1][2] * b[2][j]
                for j in range(3)
            ],
            [
                a[2][0] * b[0][j] + a[2][1] * b[1][j] + a[2][2] * b[2][j]
                for j in range(3)
            ]
        ]

    def _mat_transpose(self, m: List[List[float]]) -> List[List[float]]:
        return [
            [m[0][0], m[1][0], m[2][0]],
            [m[0][1], m[1][1], m[2][1]],
            [m[0][2], m[1][2], m[2][2]]
        ]

    def _euler_zxy_to_mat(self, rx: float, ry: float, rz: float) -> List[List[float]]:
        import math
        cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)
        sx, sy, sz = math.sin(rx), math.sin(ry), math.sin(rz)
        # R = Rz * Rx * Ry (ZXY order)
        return [
            [cz * cy - sz * sx * sy, -sz * cx, cz * sy + sz * sx * cy],
            [sz * cy + cz * sx * sy, cz * cx, sz * sy - cz * sx * cy],
            [-cx * sy, sx, cx * cy],
        ]

    def _mat_to_euler_zxy(self, m: List[List[float]]) -> Tuple[float, float, float]:
        import math
        sx = max(-1.0, min(1.0, m[2][1]))
        rx = math.asin(sx)
        cx = math.cos(rx)
        if abs(cx) < 1e-6:
            rz = 0.0
            ry = math.atan2(m[0][2], m[0][0])
        else:
            rz = math.atan2(-m[0][1], m[1][1])
            ry = math.atan2(-m[2][0], m[2][2])
        return (rx, ry, rz)

    def _yaw_pitch_roll_to_mat(self, yaw: float, pitch: float, roll: float) -> List[List[float]]:
        import math
        hy = yaw * 0.5
        hp = pitch * 0.5
        hr = roll * 0.5

        sy, cy = math.sin(hy), math.cos(hy)
        sp, cp = math.sin(hp), math.cos(hp)
        sr, cr = math.sin(hr), math.cos(hr)

        x = cy * sp * cr + sy * cp * sr
        y = sy * cp * cr - cy * sp * sr
        z = cy * cp * sr - sy * sp * cr
        w = cy * cp * cr + sy * sp * sr

        xx, yy, zz = x * x, y * y, z * z
        xy, xz, yz = x * y, x * z, y * z
        wx, wy, wz = w * x, w * y, w * z

        return [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ]

    def _mat_to_quat(self, m: List[List[float]]) -> Tuple[float, float, float, float]:
        import math
        trace = m[0][0] + m[1][1] + m[2][2]
        if trace > 0.0:
            s = math.sqrt(trace + 1.0) * 2.0
            w = 0.25 * s
            x = (m[2][1] - m[1][2]) / s
            y = (m[0][2] - m[2][0]) / s
            z = (m[1][0] - m[0][1]) / s
        elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
            s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
            w = (m[2][1] - m[1][2]) / s
            x = 0.25 * s
            y = (m[0][1] + m[1][0]) / s
            z = (m[0][2] + m[2][0]) / s
        elif m[1][1] > m[2][2]:
            s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
            w = (m[0][2] - m[2][0]) / s
            x = (m[0][1] + m[1][0]) / s
            y = 0.25 * s
            z = (m[1][2] + m[2][1]) / s
        else:
            s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
            w = (m[1][0] - m[0][1]) / s
            x = (m[0][2] + m[2][0]) / s
            y = (m[1][2] + m[2][1]) / s
            z = 0.25 * s

        norm = math.sqrt(w * w + x * x + y * y + z * z)
        if norm > 0.0:
            inv = 1.0 / norm
            w *= inv
            x *= inv
            y *= inv
            z *= inv
        return (w, x, y, z)
    def _is_animation_chunk_id(self, chunk_id: Optional[bytes]) -> bool:
        return chunk_id in (
            wad2_chunks.ChunkId.Animation,
            wad2_chunks.ChunkId.AnimationCompact,
            wad2_chunks.ChunkId.AnimationObsolete,
            wad2_chunks.ChunkId.Ani2
        )

    def load(self, filepath: str, options):
        """Load WAD2 file"""
        with open(filepath, 'rb') as f:
            return self.load_from_stream(f, options)

    def load_from_stream(self, stream: BinaryIO, options):
        """Load WAD2 from stream"""
        # Verify magic number
        magic = stream.read(4)
        if magic != b'WAD2':
            raise ValueError(f"Invalid WAD2 magic number: {magic}")

        # Skip version/flags field
        stream.read(4)

        # Create chunk reader
        reader = ChunkReader(stream)

        # Read root chunks
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None:
                break

            if chunk_id == wad2_chunks.ChunkId.SuggestedGameVersion:
                self.version = read_leb128_uint(stream)
            elif chunk_id == wad2_chunks.ChunkId.SoundSystem:
                self.sound_system = read_leb128_uint(stream)
            elif chunk_id == wad2_chunks.ChunkId.Textures:
                self.read_textures(reader, stream)
            elif chunk_id == wad2_chunks.ChunkId.Meshes:
                self.read_meshes(reader, stream)
            elif chunk_id == wad2_chunks.ChunkId.Moveables:
                self.read_moveables(reader, stream)
            elif chunk_id == wad2_chunks.ChunkId.Statics:
                self.read_statics(reader, stream)
            elif chunk_id == wad2_chunks.ChunkId.Sprites:
                self.read_sprites(reader, stream)
            elif chunk_id == wad2_chunks.ChunkId.SpriteSequences:
                self.read_sprite_sequences(reader, stream)
            # Skip other chunks for now

            reader.read_chunk_end()

        # Convert to internal model format
        return self.convert_to_model(options)

    def read_textures(self, reader: ChunkReader, stream: BinaryIO):
        """Read texture data"""
        texture_index = 0
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None or chunk_id != wad2_chunks.ChunkId.Txt:
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            texture = {
                'index': texture_index,
                'name': '',
                'path': '',
                'data': None,
                'width': 0,
                'height': 0
            }

            # Read texture dimensions (two LEB128 integers before sub-chunks)
            texture['width'] = read_leb128_uint(stream)
            texture['height'] = read_leb128_uint(stream)
            print(f"[WAD2 Texture #{texture_index}] LEB128 width={texture['width']}, height={texture['height']}, stream_pos={stream.tell()}")

            # Read texture sub-chunks
            while True:
                sub_id = reader.read_chunk_start()
                if sub_id is None:
                    break

                if sub_id == wad2_chunks.ChunkId.TxtIndex:
                    texture['index'] = read_leb128_uint(stream)
                elif sub_id == wad2_chunks.ChunkId.TxtName:
                    # Chunk content IS the string (no length prefix)
                    texture['name'] = reader.read_chunk_string()
                elif sub_id == wad2_chunks.ChunkId.TxtRelPath:
                    # Chunk content IS the string (no length prefix)
                    texture['path'] = reader.read_chunk_string()
                elif sub_id == wad2_chunks.ChunkId.TxtData:
                    # Read image data - raw BGRA or PNG data
                    chunk_size = reader.get_chunk_size()
                    texture['data'] = stream.read(chunk_size)
                    print(f"[WAD2 TxtData] chunk_size={chunk_size}, actual_read={len(texture['data'])}")

                reader.read_chunk_end()

            self.textures[texture['index']] = texture
            texture_index += 1
            reader.read_chunk_end()

    def read_single_mesh(self, reader: ChunkReader, stream: BinaryIO) -> dict:
        """Read a single mesh (used for embedded meshes in moveables)"""
        mesh = {
            'index': -1,
            'name': '',
            'positions': [],
            'normals': [],
            'shades': [],
            'colors': [],
            'triangles': [],
            'quads': [],
            'sphere': None,
            'bbox': None
        }

        # Read mesh sub-chunks
        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break

            # Handle both verbose and compact chunk IDs
            if sub_id == wad2_chunks.ChunkId.MeshName:
                # Mesh name is chunk content directly (no length prefix)
                mesh['name'] = reader.read_chunk_string()
            elif sub_id == wad2_chunks.ChunkId.Index:
                # Compact: generic index
                mesh['index'] = read_leb128_uint(stream)
            elif sub_id in (wad2_chunks.ChunkId.MeshPositions, wad2_chunks.ChunkId.MeshVrtPos, wad2_chunks.ChunkId.MeshPos):
                data = stream.read(reader.get_chunk_size())
                positions = self._parse_vector_subchunks(data, wad2_chunks.ChunkId.MeshPos)
                if positions:
                    mesh['positions'] = positions
                else:
                    buf = io.BytesIO(data)
                    count = read_leb128_uint(buf)
                    mesh['positions'] = [read_vector3(buf) for _ in range(count)]
            elif sub_id in (wad2_chunks.ChunkId.MeshNormals, wad2_chunks.ChunkId.MeshVrtNorm, wad2_chunks.ChunkId.MeshN):
                data = stream.read(reader.get_chunk_size())
                normals = self._parse_vector_subchunks(data, wad2_chunks.ChunkId.MeshN)
                if normals:
                    mesh['normals'] = normals
                else:
                    buf = io.BytesIO(data)
                    count = read_leb128_uint(buf)
                    mesh['normals'] = [read_vector3(buf) for _ in range(count)]
            elif sub_id in (wad2_chunks.ChunkId.MeshShades, wad2_chunks.ChunkId.MeshVrtShd):
                data = stream.read(reader.get_chunk_size())
                if data:
                    mesh['shades'] = list(data)
            elif sub_id == wad2_chunks.ChunkId.MeshColors:
                data = stream.read(reader.get_chunk_size())
                buf = io.BytesIO(data)
                count = read_leb128_uint(buf)
                mesh['colors'] = [read_vector3(buf) for _ in range(count)]
            elif sub_id in (wad2_chunks.ChunkId.MeshPolygons, wad2_chunks.ChunkId.MeshPolys):
                self.read_mesh_polygons(reader, stream, mesh)
            elif sub_id == wad2_chunks.ChunkId.MeshSphere:
                center = read_vector3(stream)
                radius = read_float(stream)
                mesh['sphere'] = {'center': center, 'radius': radius}
            elif sub_id == wad2_chunks.ChunkId.MeshSphC:
                # Compact sphere - center only
                mesh['sphere'] = mesh.get('sphere', {})
                mesh['sphere']['center'] = read_vector3(stream)
            elif sub_id == wad2_chunks.ChunkId.MeshSphR:
                # Compact sphere - radius only
                if 'sphere' not in mesh:
                    mesh['sphere'] = {'center': (0, 0, 0)}
                mesh['sphere']['radius'] = read_float(stream)
            elif sub_id == wad2_chunks.ChunkId.MeshBBox:
                min_corner = read_vector3(stream)
                max_corner = read_vector3(stream)
                mesh['bbox'] = {'min': min_corner, 'max': max_corner}
            elif sub_id == wad2_chunks.ChunkId.MeshBBMin:
                # Compact bbox min
                if 'bbox' not in mesh:
                    mesh['bbox'] = {}
                mesh['bbox']['min'] = read_vector3(stream)
            elif sub_id == wad2_chunks.ChunkId.MeshBBMax:
                # Compact bbox max
                if 'bbox' not in mesh:
                    mesh['bbox'] = {}
                mesh['bbox']['max'] = read_vector3(stream)

            reader.read_chunk_end()

        return mesh

    def read_meshes(self, reader: ChunkReader, stream: BinaryIO):
        """Read mesh data (root-level meshes chunk)"""
        mesh_index = 0
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None or chunk_id != wad2_chunks.ChunkId.Mesh:
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            mesh = self.read_single_mesh(reader, stream)
            if mesh['index'] == -1:
                mesh['index'] = mesh_index
            self.meshes[mesh_index] = mesh
            mesh_index += 1
            reader.read_chunk_end()

    def read_mesh_polygons(self, reader: ChunkReader, stream: BinaryIO, mesh: dict):
        """Read polygon data for a mesh"""
        max_vertex_index = len(mesh.get('positions', []))
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None:
                break

            # Handle both verbose and compact chunk IDs
            if chunk_id in (wad2_chunks.ChunkId.MeshTriangles,
                            wad2_chunks.ChunkId.MeshTri2,
                            wad2_chunks.ChunkId.MeshTri):
                data = stream.read(reader.get_chunk_size())
                poly = self._parse_polygon_chunk(data, 3, max_vertex_index)
                if poly:
                    mesh['triangles'].append(poly)
            elif chunk_id in (wad2_chunks.ChunkId.MeshQuads,
                              wad2_chunks.ChunkId.MeshQuad2,
                              wad2_chunks.ChunkId.MeshQuad):
                data = stream.read(reader.get_chunk_size())
                poly = self._parse_polygon_chunk(data, 4, max_vertex_index)
                if poly:
                    mesh['quads'].append(poly)

            reader.read_chunk_end()

    def _read_vector2_from(self, data: bytes, offset: int) -> Tuple[Optional[Tuple[float, float]], int]:
        if offset + 8 > len(data):
            return None, offset
        return struct.unpack_from('<ff', data, offset), offset + 8

    def _parse_polygon_chunk(self, data: bytes, vertex_count: int, max_vertex_index: int,
                             has_parent_area: Optional[bool] = None) -> Optional[dict]:
        """Parse a single polygon chunk (W2Tr/W2Uq/W2Tr2/W2Uq2)."""
        offset = 0
        indices: List[int] = []
        for _ in range(vertex_count):
            idx, offset = read_leb128_uint_from(data, offset)
            if idx is None:
                return None
            indices.append(idx)

        shine_strength, offset = read_leb128_uint_from(data, offset)
        if shine_strength is None:
            return None

        texture_idx, offset = read_leb128_uint_from(data, offset)
        if texture_idx is None:
            return None

        uv_bytes = vertex_count * 8
        remaining = len(data) - offset
        if has_parent_area is None:
            if remaining in (uv_bytes + 16 + 3, uv_bytes + 16 + 2):
                has_parent_area = True
            elif remaining in (uv_bytes + 3, uv_bytes + 2):
                has_parent_area = False
            else:
                has_parent_area = remaining >= uv_bytes + 16 + 2

        if has_parent_area:
            _, offset = self._read_vector2_from(data, offset)
            _, offset = self._read_vector2_from(data, offset)
            if offset > len(data):
                return None

        uvs = []
        for _ in range(vertex_count):
            uv, offset = self._read_vector2_from(data, offset)
            if uv is None:
                return None
            uvs.append(uv)

        blend_mode = 0
        double_sided = False
        remaining = len(data) - offset
        if remaining >= 3:
            blend_mode = struct.unpack_from('<h', data, offset)[0]
            double_sided = bool(data[offset + 2])
            offset += 3
        else:
            blend_mode_val, offset2 = read_leb128_uint_from(data, offset)
            if blend_mode_val is not None:
                blend_mode = blend_mode_val
                offset = offset2
                if offset < len(data):
                    double_sided = bool(data[offset])
                    offset += 1

        if offset > len(data):
            return None

        return {
            'indices': indices,
            'texture': texture_idx,
            'uvs': uvs,
            'flipped': False,
            'intensity': 0,
            'shine': shine_strength,
            'opacity': 0,
            'blend_mode': blend_mode,
            'double_sided': double_sided
        }

    def _parse_vector_subchunks(self, data: bytes, expected_id: bytes) -> List[Tuple[float, float, float]]:
        """Parse repeated vector sub-chunks like W2Pos/W2N inside a parent chunk."""
        results = []
        offset = 0
        while offset < len(data):
            chunk_id, offset = read_chunk_id_from(data, offset)
            if not chunk_id:
                break
            size, offset = read_leb128_uint_from(data, offset)
            if size is None:
                break
            if offset + size > len(data):
                break
            chunk_data = data[offset:offset + size]
            offset += size
            if chunk_id == expected_id and size >= 12:
                results.append(struct.unpack_from('<fff', chunk_data, 0))
        return results

    def read_moveables(self, reader: ChunkReader, stream: BinaryIO):
        """Read moveable objects"""
        moveable_index = 0
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None or chunk_id != wad2_chunks.ChunkId.Moveable:
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            # IMPORTANT: In compact WAD2 format, W2Moveable chunks start with a LEB128 ID
            # directly (not as a sub-chunk), followed by W2Mesh/W2Bone2/W2Ani2 chunks
            moveable_id = read_leb128_uint(stream)

            moveable = {
                'id': moveable_id,
                'meshes': [],  # Will store mesh objects OR indices
                'bones': [],
                'animations': []
            }

            # Read moveable sub-chunks
            # In compact format, moveables directly contain W2Mesh, W2Bone2, W2Ani2 chunks
            # In verbose format, they have properties like W2MoveableId, W2MoveableMeshes, etc.
            while True:
                sub_id = reader.read_chunk_start()
                if sub_id is None:
                    break

                if sub_id == wad2_chunks.ChunkId.MoveableId:
                    # Verbose format ID (override the one we read)
                    moveable['id'] = read_leb128_uint(stream)
                elif sub_id == wad2_chunks.ChunkId.MoveableMeshes:
                    # Read mesh indices
                    count = read_leb128_uint(stream)
                    moveable['meshes'] = [read_leb128_uint(stream) for _ in range(count)]
                elif sub_id == wad2_chunks.ChunkId.MoveableBones:
                    moveable['bones'] = self.read_bones(reader, stream)
                elif sub_id == wad2_chunks.ChunkId.MoveableAnimations:
                    moveable['animations'] = self.read_animations(reader, stream)
                elif self._is_animation_chunk_id(sub_id):
                    animation = self.read_single_animation(reader, stream, sub_id)
                    if animation:
                        moveable['animations'].append(animation)
                elif sub_id == wad2_chunks.ChunkId.Mesh:
                    # Compact format: embedded mesh directly in moveable
                    mesh = self.read_single_mesh(reader, stream)
                    moveable['meshes'].append(mesh)
                elif sub_id in (wad2_chunks.ChunkId.Bone2,):
                    # Compact format: embedded bones with op+name header.
                    if not moveable['bones']:
                        moveable['bones'] = []
                    data = stream.read(reader.get_chunk_size())
                    bone = self._parse_bone2_chunk(data)
                    moveable['bones'].append(bone)

                reader.read_chunk_end()

            self.moveables[moveable['id']] = moveable
            moveable_index += 1
            reader.read_chunk_end()

    def read_single_bone(self, reader: ChunkReader, stream: BinaryIO) -> dict:
        """Read a single bone (used for compact format)"""
        bone = {
            'name': '',
            'parent': -1,
            'translation': (0, 0, 0),
            'mesh': -1
        }

        # Read bone sub-chunks
        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break

            # Handle both verbose and compact chunk IDs
            if sub_id == wad2_chunks.ChunkId.MoveableBoneName:
                bone['name'] = read_string(stream)
            elif sub_id == wad2_chunks.ChunkId.MoveableBoneParent:
                bone['parent'] = read_leb128_int(stream)
            elif sub_id in (wad2_chunks.ChunkId.MoveableBoneTranslation, wad2_chunks.ChunkId.BoneTrans):
                bone['translation'] = read_vector3(stream)
            elif sub_id in (wad2_chunks.ChunkId.MoveableBoneMesh, wad2_chunks.ChunkId.BoneMesh):
                bone['mesh'] = read_leb128_int(stream)

            reader.read_chunk_end()

        return bone

    def _parse_bone2_chunk(self, data: bytes) -> dict:
        """Parse compact W2Bone2 chunk data with op+name header."""
        bone = {
            'name': '',
            'parent': -1,
            'translation': (0, 0, 0),
            'mesh': -1,
            'op': 0,
        }
        if len(data) < 5:
            return bone

        bone['op'] = data[0]
        name_len = struct.unpack_from('<I', data, 1)[0]
        name_start = 5
        name_end = name_start + name_len
        if name_end <= len(data) and name_len > 0:
            bone['name'] = data[name_start:name_end].decode('utf-8', errors='replace')
        offset = name_end

        while offset < len(data):
            chunk_id, offset = read_chunk_id_from(data, offset)
            if not chunk_id:
                break
            size, offset = read_leb128_uint_from(data, offset)
            if size is None or offset + size > len(data):
                break
            chunk_data = data[offset:offset + size]
            offset += size
            if chunk_id in (wad2_chunks.ChunkId.MoveableBoneTranslation, wad2_chunks.ChunkId.BoneTrans):
                if len(chunk_data) >= 12:
                    bone['translation'] = struct.unpack_from('<fff', chunk_data, 0)
            elif chunk_id in (wad2_chunks.ChunkId.MoveableBoneMesh, wad2_chunks.ChunkId.BoneMesh):
                if chunk_data:
                    buf = io.BytesIO(chunk_data)
                    bone['mesh'] = read_leb128_uint(buf)
            elif chunk_id == wad2_chunks.ChunkId.MoveableBoneParent:
                if chunk_data:
                    buf = io.BytesIO(chunk_data)
                    bone['parent'] = read_leb128_int(buf)

        return bone

    def read_bones(self, reader: ChunkReader, stream: BinaryIO) -> List[dict]:
        """Read bone hierarchy"""
        bones = []
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None or chunk_id not in (wad2_chunks.ChunkId.MoveableBone, wad2_chunks.ChunkId.Bone2):
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            bone = self.read_single_bone(reader, stream)
            bones.append(bone)
            reader.read_chunk_end()

        return bones

    def read_animations(self, reader: ChunkReader, stream: BinaryIO) -> List[dict]:
        """Read animation data (container of animation chunks)."""
        animations = []
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None or not self._is_animation_chunk_id(chunk_id):
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            animation = self.read_single_animation(reader, stream, chunk_id)
            if animation:
                animations.append(animation)

            reader.read_chunk_end()

        return animations

    def read_single_animation(self, reader: ChunkReader, stream: BinaryIO, chunk_id: bytes) -> Optional[dict]:
        """Read a single animation chunk."""
        if chunk_id == wad2_chunks.ChunkId.Animation:
            return self._read_animation_verbose(reader, stream)
        return self._read_animation_compact(reader, stream, chunk_id)

    def _read_animation_verbose(self, reader: ChunkReader, stream: BinaryIO) -> dict:
        animation = {
            'name': '',
            'keyframes': [],
            'state_id': 0,
            'frame_rate': 0,
            'next_animation': 0,
            'next_frame': 0,
            'state_changes': {},
            'commands': [],
            'velocity': (0, 0, 0),
            'acceleration': (0, 0, 0),
            'frame_duration': 1,
            'speed': 0,
            'end_frame': 0
        }

        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break

            if sub_id == wad2_chunks.ChunkId.AnimationName:
                animation['name'] = read_string(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationStateId:
                animation['state_id'] = read_leb128_uint(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationEndFrame:
                animation['end_frame'] = read_leb128_uint(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationFrameRate:
                animation['frame_rate'] = read_float(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationNextAnimation:
                animation['next_animation'] = read_leb128_int(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationNextFrame:
                animation['next_frame'] = read_leb128_uint(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationVelocity:
                animation['velocity'] = read_vector3(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationAcceleration:
                animation['acceleration'] = read_vector3(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationFrameDuration:
                animation['frame_duration'] = read_leb128_uint(stream)
            elif sub_id == wad2_chunks.ChunkId.AnimationKeyFrames:
                animation['keyframes'] = self.read_keyframes(reader, stream)
            elif sub_id in (wad2_chunks.ChunkId.Cmd, wad2_chunks.ChunkId.Cmd2):
                command = self.read_anim_command_compact(reader, stream)
                if command:
                    animation['commands'].append(command)

            reader.read_chunk_end()

        return animation

    def _read_animation_compact(self, reader: ChunkReader, stream: BinaryIO, chunk_id: bytes) -> dict:
        animation = {
            'name': '',
            'keyframes': [],
            'state_id': 0,
            'frame_rate': 0,
            'next_animation': 0,
            'next_frame': 0,
            'state_changes': {},
            'commands': [],
            'velocity': (0.0, 0.0, 0.0, 0.0),
            'acceleration': (0, 0, 0),
            'frame_duration': 1,
            'speed': 0,
            'end_frame': 0
        }

        animation['state_id'] = read_leb128_uint(stream)
        animation['end_frame'] = read_leb128_uint(stream)
        animation['frame_rate'] = read_leb128_uint(stream)
        animation['frame_duration'] = max(1, animation['frame_rate'])

        if chunk_id == wad2_chunks.ChunkId.AnimationObsolete:
            _ = read_leb128_uint(stream)
            _ = read_leb128_uint(stream)

        old_speed = old_accel = old_lat_speed = old_lat_accel = 0
        if chunk_id != wad2_chunks.ChunkId.Ani2:
            old_speed = read_leb128_int(stream)
            old_accel = read_leb128_int(stream)
            old_lat_speed = read_leb128_int(stream)
            old_lat_accel = read_leb128_int(stream)
            if animation['end_frame'] > 0:
                animation['end_frame'] -= 1

        if animation['end_frame'] == 0xFFFF:
            animation['end_frame'] = 0

        animation['next_animation'] = read_leb128_uint(stream)
        animation['next_frame'] = read_leb128_uint(stream)

        if chunk_id != wad2_chunks.ChunkId.Ani2:
            animation['speed'] = old_speed
            animation['acceleration'] = old_accel

        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break

            if sub_id in (wad2_chunks.ChunkId.AnimationName, wad2_chunks.ChunkId.AnmName):
                animation['name'] = reader.read_chunk_string()
            elif sub_id == wad2_chunks.ChunkId.AniV:
                animation['velocity'] = read_vector4(stream)
            elif sub_id == wad2_chunks.ChunkId.Kf:
                keyframe = self.read_keyframe_compact(reader, stream)
                if keyframe:
                    animation['keyframes'].append(keyframe)
            elif sub_id == wad2_chunks.ChunkId.StCh:
                state_id, dispatches = self.read_state_change_compact(reader, stream)
                if state_id is not None:
                    animation['state_changes'][state_id] = dispatches
            elif sub_id in (wad2_chunks.ChunkId.Cmd, wad2_chunks.ChunkId.Cmd2):
                command = self.read_anim_command_compact(reader, stream)
                if command:
                    animation['commands'].append(command)

            reader.read_chunk_end()

        return animation

    def read_keyframes(self, reader: ChunkReader, stream: BinaryIO) -> List[dict]:
        """Read animation keyframes"""
        keyframes = []
        while True:
            chunk_id = reader.read_chunk_start()
            if chunk_id is None or chunk_id != wad2_chunks.ChunkId.AnimationKeyFrame:
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            keyframe = {
                'offset': (0, 0, 0),
                'angles': [],
                'rotations': [],
                'bbox': None
            }

            # Read keyframe sub-chunks
            while True:
                sub_id = reader.read_chunk_start()
                if sub_id is None:
                    break

                if sub_id == wad2_chunks.ChunkId.AnimationKeyFrameOffset:
                    keyframe['offset'] = read_vector3(stream)
                elif sub_id == wad2_chunks.ChunkId.AnimationKeyFrameAngles:
                    count = read_leb128_uint(stream)
                    keyframe['angles'] = [read_vector3(stream) for _ in range(count)]
                    keyframe['rotations'] = list(keyframe['angles'])
                elif sub_id == wad2_chunks.ChunkId.AnimationKeyFrameBBox:
                    min_corner = read_vector3(stream)
                    max_corner = read_vector3(stream)
                    keyframe['bbox'] = {'min': min_corner, 'max': max_corner}

                reader.read_chunk_end()

            keyframes.append(keyframe)
            reader.read_chunk_end()

        return keyframes

    def read_keyframe_compact(self, reader: ChunkReader, stream: BinaryIO) -> Optional[dict]:
        keyframe = {
            'offset': (0, 0, 0),
            'rotations': [],
            'bbox': None
        }

        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break

            if sub_id == wad2_chunks.ChunkId.KfOffs:
                keyframe['offset'] = read_vector3(stream)
            elif sub_id == wad2_chunks.ChunkId.KfBB:
                bbox_min = (0, 0, 0)
                bbox_max = (0, 0, 0)
                while True:
                    bb_id = reader.read_chunk_start()
                    if bb_id is None:
                        break
                    if bb_id == wad2_chunks.ChunkId.MeshBBMin:
                        bbox_min = read_vector3(stream)
                    elif bb_id == wad2_chunks.ChunkId.MeshBBMax:
                        bbox_max = read_vector3(stream)
                    reader.read_chunk_end()
                keyframe['bbox'] = {'min': bbox_min, 'max': bbox_max}
            elif sub_id == wad2_chunks.ChunkId.KfA:
                keyframe['rotations'].append(read_vector3(stream))

            reader.read_chunk_end()

        return keyframe

    def read_state_change_compact(self, reader: ChunkReader, stream: BinaryIO) -> Tuple[Optional[int], List[Tuple[int, int, int, int]]]:
        state_id = read_leb128_uint(stream)
        dispatches = []

        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break
            if sub_id == wad2_chunks.ChunkId.Disp:
                in_frame = read_leb128_uint(stream)
                out_frame = read_leb128_uint(stream)
                next_anim = read_leb128_uint(stream)
                next_frame = read_leb128_uint(stream)
                dispatches.append((in_frame, out_frame, next_anim, next_frame))
            reader.read_chunk_end()

        return state_id, dispatches

    def read_anim_command_compact(self, reader: ChunkReader, stream: BinaryIO) -> Optional[Tuple[int, int, int, int]]:
        cmd_type = read_leb128_uint(stream)
        param1 = read_leb128_int(stream)
        param2 = read_leb128_int(stream)
        param3 = read_leb128_int(stream)

        while True:
            sub_id = reader.read_chunk_start()
            if sub_id is None:
                break
            reader.read_chunk_end()

        return (cmd_type, param1, param2, param3)

    def read_statics(self, reader: ChunkReader, stream: BinaryIO):
        """Read static objects"""
        static_index = 0
        while True:
            chunk_id = reader.read_chunk_start()
            # Handle both verbose and compact static chunk IDs
            if chunk_id is None or chunk_id not in (wad2_chunks.ChunkId.Static, wad2_chunks.ChunkId.Static2):
                if chunk_id is not None:
                    reader.read_chunk_end()
                break

            # IMPORTANT: Similar to moveables, W2Static chunks start with a LEB128 ID
            # directly, followed by flags, then W2Mesh or property chunks
            static_id = read_leb128_uint(stream)

            # Flags field (present in both W2Static and W2Static2)
            flags = read_leb128_uint(stream)

            # Legacy W2Static format has an additional lighting type field (pre-1.3.12)
            legacy_lighting_type = -1
            if chunk_id == wad2_chunks.ChunkId.Static:
                legacy_lighting_type = read_leb128_uint(stream)

            static = {
                'id': static_id,
                'flags': flags,
                'lighting_type': legacy_lighting_type,
                'mesh': None,  # Can be embedded mesh object OR mesh index
                'visibility_box': None,
                'collision_box': None
            }

            # Read static sub-chunks
            while True:
                sub_id = reader.read_chunk_start()
                if sub_id is None:
                    break

                if sub_id == wad2_chunks.ChunkId.StaticId:
                    # Verbose format ID (override the one we read)
                    static['id'] = read_leb128_uint(stream)
                elif sub_id == wad2_chunks.ChunkId.StaticMesh:
                    # Mesh index reference
                    static['mesh'] = read_leb128_uint(stream)
                elif sub_id == wad2_chunks.ChunkId.Mesh:
                    # Compact format: embedded mesh directly in static
                    static['mesh'] = self.read_single_mesh(reader, stream)
                elif sub_id == wad2_chunks.ChunkId.StaticVisibilityBox:
                    min_corner = read_vector3(stream)
                    max_corner = read_vector3(stream)
                    static['visibility_box'] = {'min': min_corner, 'max': max_corner}
                elif sub_id == wad2_chunks.ChunkId.StaticCollisionBox:
                    min_corner = read_vector3(stream)
                    max_corner = read_vector3(stream)
                    static['collision_box'] = {'min': min_corner, 'max': max_corner}

                reader.read_chunk_end()

            self.statics[static['id']] = static
            static_index += 1
            reader.read_chunk_end()

    def read_sprites(self, reader: ChunkReader, stream: BinaryIO):
        """Read sprite data"""
        # TODO: Implement sprite reading
        pass

    def read_sprite_sequences(self, reader: ChunkReader, stream: BinaryIO):
        """Read sprite sequences"""
        # TODO: Implement sprite sequence reading
        pass

    def convert_to_model(self, options):
        """Convert WAD2 data to internal model format"""
        from . import model

        statics_model = []
        movables_model = []
        textureMaps = []

        # Determine texture map dimensions
        # WAD2 textures may be PNG-compressed; stored width/height can be unreliable.
        # _decode_texture_data updates the texture dict's width/height when decoding PNG.
        mapwidth = 256
        mapheight = 256

        if self.textures:
            for idx in sorted(self.textures.keys()):
                textureMaps.append(self._decode_texture_data(self.textures[idx], mapwidth, mapheight))

            # Use actual dimensions from first texture (updated by PNG decode)
            first_tex = self.textures[next(iter(sorted(self.textures.keys())))]
            mapwidth = max(1, first_tex.get('width', 256))
            mapheight = max(1, first_tex.get('height', 256))

        texture_map = textureMaps[0] if textureMaps else [0.0] * (mapwidth * mapheight * 4)

        # Convert statics
        for static_id, static_data in self.statics.items():
            mesh_data = static_data.get('mesh')
            if mesh_data and isinstance(mesh_data, dict):
                # Embedded mesh
                mesh_model = self._convert_mesh_to_model(mesh_data, mapwidth, mapheight)
                static_model = model.Static(idx=static_data['id'], mesh=mesh_model)
                statics_model.append(static_model)

        # Convert moveables
        for mov_id, mov_data in self.moveables.items():
            meshes_model = []

            # Convert embedded meshes
            for mesh_data in mov_data.get('meshes', []):
                if isinstance(mesh_data, dict):
                    mesh_model = self._convert_mesh_to_model(mesh_data, mapwidth, mapheight)
                    meshes_model.append(mesh_model)

            # Convert bones to joints format (parent mesh index + translation)
            joints = []
            bones = mov_data.get('bones', [])
            if bones and meshes_model:
                mesh_count = len(meshes_model)
                if any('op' in bone for bone in bones):
                    bones_by_mesh = {}
                    for bone_idx, bone in enumerate(bones):
                        mesh_idx = bone.get('mesh', -1)
                        if mesh_idx is None or mesh_idx < 0 or mesh_idx >= mesh_count:
                            mesh_idx = bone_idx if bone_idx < mesh_count else -1
                        if mesh_idx >= 0:
                            bones_by_mesh[mesh_idx] = bone

                    for mesh_idx in range(1, mesh_count):
                        bone = bones_by_mesh.get(mesh_idx)
                        if bone:
                            op = bone.get('op', 0)
                            dx, dy, dz = self._fix_axis_vec3(bone.get('translation', (0, 0, 0)))
                        else:
                            op, dx, dy, dz = 0, 0, 0, 0
                        joints.append([op, dx, dy, dz])
                else:
                    bone_mesh_indices = []
                    for bone_idx, bone in enumerate(bones):
                        mesh_idx = bone.get('mesh', -1)
                        if mesh_idx is None or mesh_idx < 0 or mesh_idx >= mesh_count:
                            mesh_idx = bone_idx if bone_idx < mesh_count else -1
                        bone_mesh_indices.append(mesh_idx)

                    joints = [[-1, 0, 0, 0] for _ in range(mesh_count)]
                    for bone_idx, bone in enumerate(bones):
                        mesh_idx = bone_mesh_indices[bone_idx]
                        if mesh_idx < 0 or mesh_idx >= mesh_count:
                            continue
                        parent_bone_idx = bone.get('parent', -1)
                        parent_mesh_idx = -1
                        if 0 <= parent_bone_idx < len(bone_mesh_indices):
                            parent_mesh_idx = bone_mesh_indices[parent_bone_idx]
                        trans = self._fix_axis_vec3(bone.get('translation', (0, 0, 0)))
                        joints[mesh_idx] = [parent_mesh_idx, trans[0], trans[1], trans[2]]

            # Convert animations
            animations_model = []
            for anim_data in mov_data.get('animations', []):
                anim_model = self._convert_animation_to_model(anim_data)
                animations_model.append(anim_model)

            movable_model = model.Movable(
                idx=mov_data['id'],
                meshes=meshes_model,
                joints=joints,
                animations=animations_model
            )
            movables_model.append(movable_model)

        return model.Wad(
            version=self.version if self.version >= 130 else 130,
            statics=statics_model,
            mapwidth=mapwidth,
            mapheight=mapheight,
            textureMap=texture_map,
            movables=movables_model,
            textureMaps=textureMaps,
            game_version=self.version if self.version < 130 else 0,
        )

    def _decode_texture_data(self, texture: dict, mapwidth: int, mapheight: int) -> List[float]:
        """Decode texture data into normalized float list.
        Handles both raw BGRA and PNG-compressed data."""
        data = texture.get('data')
        stored_w = texture.get('width', 0)
        stored_h = texture.get('height', 0)
        print(f"[WAD2 Texture] stored w={stored_w}, h={stored_h}, "
              f"data={'None' if data is None else f'{len(data)} bytes'}, "
              f"first8={data[:8].hex() if data and len(data) >= 8 else 'N/A'}")

        if not data:
            width = max(1, texture.get('width', mapwidth))
            height = max(1, texture.get('height', mapheight))
            return [0.0] * (width * height * 4)

        # Check if data is PNG (starts with PNG signature)
        is_png = len(data) >= 8 and data[:8] == b'\x89PNG\r\n\x1a\n'

        if is_png:
            rgba, width, height = _decode_png_to_rgba(data)
            if rgba is None:
                width = max(1, texture.get('width', mapwidth))
                height = max(1, texture.get('height', mapheight))
                return [0.0] * (width * height * 4)

            # Update texture dict with actual PNG dimensions
            texture['width'] = width
            texture['height'] = height

            # Convert to normalized float list with vertical flip and magenta keying
            pixels = [0.0] * (width * height * 4)
            for y in range(height):
                dst_row = height - 1 - y
                for x in range(width):
                    src = (y * width + x) * 4
                    dst = (dst_row * width + x) * 4
                    r, g, b, a = rgba[src], rgba[src + 1], rgba[src + 2], rgba[src + 3]
                    # Magenta key: treat (255, 0, 255) as transparent
                    if r == 255 and g == 0 and b == 255:
                        r = g = b = a = 0
                    pixels[dst] = r / 255.0
                    pixels[dst + 1] = g / 255.0
                    pixels[dst + 2] = b / 255.0
                    pixels[dst + 3] = a / 255.0
            return pixels

        # Raw BGRA data path
        width = max(1, texture.get('width', mapwidth))
        height = max(1, texture.get('height', mapheight))
        pixels = [0.0] * (width * height * 4)
        if len(data) < width * height * 4:
            return pixels

        for y in range(height):
            src_row = y
            dst_row = height - 1 - y
            for x in range(width):
                src = (src_row * width + x) * 4
                dst = (dst_row * width + x) * 4
                # WAD2 texture data is stored as BGRA
                b = data[src]
                g = data[src + 1]
                r = data[src + 2]
                a = data[src + 3]
                if r == 255 and g == 0 and b == 255:
                    r = g = b = a = 0
                pixels[dst] = r / 255.0
                pixels[dst + 1] = g / 255.0
                pixels[dst + 2] = b / 255.0
                pixels[dst + 3] = a / 255.0

        return pixels

    def _convert_mesh_to_model(self, mesh_data: dict, mapwidth: int, mapheight: int):
        """Convert WAD2 mesh data to model.Mesh"""
        from . import model

        # Convert vertices to Point
        vertices = [model.Point(*self._fix_axis_vec3(v)) for v in mesh_data.get('positions', [])]

        # Convert normals to Point
        normals = [model.Point(*self._fix_axis_vec3(n)) for n in mesh_data.get('normals', [])]

        # Convert polygons (both triangles and quads)
        polygons = []

        # Process triangles
        for tri in mesh_data.get('triangles', []):
            poly = self._convert_polygon_to_model(tri, 3, mapwidth, mapheight)
            polygons.append(poly)

        # Process quads
        for quad in mesh_data.get('quads', []):
            poly = self._convert_polygon_to_model(quad, 4, mapwidth, mapheight)
            polygons.append(poly)

        # Bounding sphere
        sphere = mesh_data.get('sphere', {})
        if sphere and 'center' in sphere:
            center = self._fix_axis_vec3(sphere['center'])
            bounding_sphere_center = model.Point(center[0], center[1], center[2])
            bounding_sphere_radius = int(sphere.get('radius', 0))
        else:
            bounding_sphere_center = model.Point(0, 0, 0)
            bounding_sphere_radius = 0

        # Shades (vertex lighting)
        shades = mesh_data.get('shades', [])

        valid_polygons = []
        max_index = len(vertices)
        for poly in polygons:
            if all(0 <= idx < max_index for idx in poly.face):
                valid_polygons.append(poly)

        return model.Mesh(
            vertices=vertices,
            polygons=valid_polygons,
            normals=normals,
            boundingSphereCenter=bounding_sphere_center,
            boundingSphereRadius=bounding_sphere_radius,
            shades=shades
        )

    def _convert_polygon_to_model(self, poly_data: dict, vertex_count: int, mapwidth: int, mapheight: int):
        """Convert WAD2 polygon data to model.Polygon"""
        from . import model

        # Face indices
        indices = poly_data.get('indices', [])
        if len(indices) < vertex_count:
            indices = indices + [0] * (vertex_count - len(indices))
        face = tuple(indices[:vertex_count])

        # Texture page and coordinates
        texture_idx = poly_data.get('texture', 0)

        # Use per-texture dimensions for UV normalisation.
        # Using a global mapwidth/mapheight (first texture's size) for all polygons
        # is wrong when textures have different sizes (e.g. 256×256 skin + 4×4 patch).
        if texture_idx in self.textures:
            tex_w = max(1, self.textures[texture_idx].get('width', mapwidth))
            tex_h = max(1, self.textures[texture_idx].get('height', mapheight))
        else:
            tex_w, tex_h = mapwidth, mapheight

        # Texture coordinates (UV)
        uvs = poly_data.get('uvs', [])
        if len(uvs) < vertex_count:
            uvs = uvs + [(0.0, 0.0)] * (vertex_count - len(uvs))
        tbox = []
        for i in range(vertex_count):
            u, v = uvs[i]
            if tex_w > 0 and tex_h > 0:
                u = max(0.0, min(1.0, u / tex_w))
                v = max(0.0, min(1.0, v / tex_h))
                v = 1.0 - v
            else:
                u, v = 0.0, 0.0
            tbox.append((u, v))

        # WAD2 textures are standalone; map texture index to page.
        texture_count = len(self.textures)
        if texture_count > 0 and 0 <= texture_idx < texture_count:
            page = texture_idx
        else:
            page = 0
        x = 0
        y = 0

        poly = model.Polygon(
            face=face,
            tbox=tbox,
            order=vertex_count,  # 3 for triangle, 4 for quad
            intensity=poly_data.get('intensity', 0),
            shine=poly_data.get('shine', 0),
            opacity=poly_data.get('opacity', 0),
            page=page,
            tex_width=tex_w,
            tex_height=tex_h,
            flipX=poly_data.get('flipped', False),
            flipY=False,
            origin=0,
            x=x,
            y=y
        )
        poly.texture_index = texture_idx
        poly.texture_flipped = 1 if poly_data.get('flipped', False) else 0
        return poly

    def _convert_animation_to_model(self, anim_data: dict):
        """Convert WAD2 animation data to model.Animation"""
        from . import model
        import math

        # Convert keyframes
        keyframes_model = []
        axis_mat = [
            [-1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0],
            [0.0, 1.0, 0.0],
        ]
        axis_mat_t = self._mat_transpose(axis_mat)
        for kf_data in anim_data.get('keyframes', []):
            offset = kf_data.get('offset', (0, 0, 0))
            offset = self._fix_axis_vec3(offset)
            rotations = kf_data.get('rotations', []) or kf_data.get('angles', [])
            # WAD2 stores angles in degrees; convert to radians for Blender.
            rotations = [
                (math.radians(r[0]), math.radians(r[1]), math.radians(r[2]))
                for r in rotations
            ]
            # Convert rotation basis from WAD2 to Blender axes.
            converted_rots = []
            for rx, ry, rz in rotations:
                # WAD2 rotations are yaw(Y), pitch(X), roll(Z).
                src = self._yaw_pitch_roll_to_mat(ry, rx, rz)
                tmp = self._mat_mul(axis_mat, src)
                dst = self._mat_mul(tmp, axis_mat_t)
                converted_rots.append(self._mat_to_quat(dst))
            rotations = converted_rots
            bbox = kf_data.get('bbox', {})
            bb1 = tuple(bbox.get('min', (0, 0, 0)))
            bb2 = tuple(bbox.get('max', (0, 0, 0)))

            keyframe = model.Keyframe(
                offset=offset,
                rotations=rotations,
                bb1=bb1,
                bb2=bb2
            )
            keyframes_model.append(keyframe)

        state_changes = anim_data.get('state_changes', {})
        if isinstance(state_changes, list):
            converted = {}
            for entry in state_changes:
                state_id = entry.get('state_id')
                dispatches = entry.get('dispatches', [])
                if state_id is not None:
                    converted[state_id] = dispatches
            state_changes = converted

        return model.Animation(
            stateID=anim_data.get('state_id', 0),
            keyFrames=keyframes_model,
            stateChanges=state_changes,
            commands=anim_data.get('commands', []),
            frameDuration=anim_data.get('frame_duration', 1),
            speed=anim_data.get('speed', 0),
            acceleration=anim_data.get('acceleration', 0),
            frameStart=0,
            frameEnd=anim_data.get('end_frame', 0),
            frameIn=anim_data.get('next_frame', 0),
            nextAnimation=anim_data.get('next_animation', 0)
        )


def readWAD2(filepath: str, options):
    """Read a WAD2 file and return a Wad model"""
    loader = Wad2Loader()
    return loader.load(filepath, options)
