"""
WAD2 File Format Writer
Implements chunk-based binary writing with LEB128 encoding
Compatible with Tomb Editor's WAD2 format
"""

import struct
import io
import math
from typing import BinaryIO, List, Tuple, Optional, Dict, Any
from . import wad2_chunks


def write_leb128_uint(f: BinaryIO, value: int):
    """Write LEB128 variable-length unsigned integer"""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        f.write(struct.pack('B', byte))
        if value == 0:
            break


def write_leb128_int(f: BinaryIO, value: int):
    """Write LEB128 variable-length signed integer"""
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        # Sign bit of byte is second high bit (0x40)
        if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40) != 0):
            more = False
        else:
            byte |= 0x80
        f.write(struct.pack('B', byte))


def write_string(f: BinaryIO, s: str):
    """Write length-prefixed string"""
    data = s.encode('utf-8')
    write_leb128_uint(f, len(data))
    f.write(data)


def write_vector3(f: BinaryIO, vec: Tuple[float, float, float]):
    """Write 3 floats as a vector (little-endian)"""
    f.write(struct.pack('<fff', vec[0], vec[1], vec[2]))


def write_vector2(f: BinaryIO, vec: Tuple[float, float]):
    """Write 2 floats as a vector (little-endian)"""
    f.write(struct.pack('<ff', vec[0], vec[1]))


def write_vector4(f: BinaryIO, vec: Tuple[float, float, float, float]):
    """Write 4 floats as a vector (little-endian)"""
    f.write(struct.pack('<ffff', vec[0], vec[1], vec[2], vec[3]))


def write_bool(f: BinaryIO, value: bool):
    """Write boolean value"""
    f.write(struct.pack('?', value))


def write_float(f: BinaryIO, value: float):
    """Write single float (little-endian)"""
    f.write(struct.pack('<f', value))


def write_chunk_id(f: BinaryIO, chunk_id: bytes):
    """Write chunk identifier (length-prefixed bytes)"""
    write_leb128_uint(f, len(chunk_id))
    f.write(chunk_id)


class ChunkWriter:
    """Writes chunks to WAD2 file"""

    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.chunk_stack = []  # Stack of (chunk_id, buffer)

    def write_chunk_start(self, chunk_id: bytes):
        """Start writing a new chunk"""
        buffer = io.BytesIO()
        self.chunk_stack.append((chunk_id, buffer))

    def write_chunk_end(self):
        """Finish writing current chunk and write to parent/stream"""
        if not self.chunk_stack:
            return

        chunk_id, buffer = self.chunk_stack.pop()
        data = buffer.getvalue()

        # Get target stream (parent buffer or main stream)
        if self.chunk_stack:
            target = self.chunk_stack[-1][1]
        else:
            target = self.stream

        # Write chunk: ID + size + data
        write_chunk_id(target, chunk_id)
        write_leb128_uint(target, len(data))
        target.write(data)

    def get_current_buffer(self) -> BinaryIO:
        """Get the current writing buffer"""
        if self.chunk_stack:
            return self.chunk_stack[-1][1]
        return self.stream

    def write_chunk_string(self, chunk_id: bytes, s: str):
        """Write a simple string chunk"""
        self.write_chunk_start(chunk_id)
        buf = self.get_current_buffer()
        data = s.encode('utf-8')
        buf.write(data)
        self.write_chunk_end()

    def write_chunk_uint(self, chunk_id: bytes, value: int):
        """Write a simple uint chunk"""
        self.write_chunk_start(chunk_id)
        write_leb128_uint(self.get_current_buffer(), value)
        self.write_chunk_end()

    def write_chunk_int(self, chunk_id: bytes, value: int):
        """Write a simple int chunk"""
        self.write_chunk_start(chunk_id)
        write_leb128_int(self.get_current_buffer(), value)
        self.write_chunk_end()

    def write_chunk_float(self, chunk_id: bytes, value: float):
        """Write a simple float chunk"""
        self.write_chunk_start(chunk_id)
        write_float(self.get_current_buffer(), value)
        self.write_chunk_end()

    def write_chunk_vector3(self, chunk_id: bytes, vec: Tuple[float, float, float]):
        """Write a simple vector3 chunk"""
        self.write_chunk_start(chunk_id)
        write_vector3(self.get_current_buffer(), vec)
        self.write_chunk_end()


def _fix_axis_to_wad2(vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Convert Blender axes (Z-up, -Y forward) to WAD2 (Y-up)"""
    # Blender: X right, Y back, Z up
    # WAD2: X right, Y up, Z back
    # So: wad2.x = -blender.x, wad2.y = blender.z, wad2.z = -blender.y
    return (-vec[0], vec[2], -vec[1])


def _quat_to_euler_ypr(quat: Tuple[float, float, float, float]) -> Tuple[float, float, float]:
    """Convert quaternion to yaw-pitch-roll euler angles (in degrees)"""
    w, x, y, z = quat

    # Yaw (Y axis rotation)
    siny_cosp = 2.0 * (w * y + z * x)
    cosy_cosp = 1.0 - 2.0 * (x * x + y * y)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    # Pitch (X axis rotation)
    sinp = 2.0 * (w * x - y * z)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)

    # Roll (Z axis rotation)
    sinr_cosp = 2.0 * (w * z + x * y)
    cosr_cosp = 1.0 - 2.0 * (z * z + x * x)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    return (math.degrees(yaw), math.degrees(pitch), math.degrees(roll))


class Wad2Writer:
    """Writes WAD2 files"""

    def __init__(self):
        self.version = 150  # TEN version
        self.sound_system = 0

    def write(self, filepath: str, wad_data: dict, options):
        """Write WAD2 file"""
        with open(filepath, 'wb') as f:
            self.write_to_stream(f, wad_data, options)

    def write_to_stream(self, stream: BinaryIO, wad_data: dict, options):
        """Write WAD2 to stream (matching Wad2Writer.cs structure)"""
        # Write magic number
        stream.write(b'WAD2')

        # Write version/flags (4 bytes)
        stream.write(struct.pack('<I', 0))

        # Create chunk writer
        writer = ChunkWriter(stream)

        # Write suggested game version
        writer.write_chunk_uint(wad2_chunks.ChunkId.SuggestedGameVersion, self.version)

        # Write sound system (1 = XML-based sound system)
        writer.write_chunk_uint(wad2_chunks.ChunkId.SoundSystem, 1)

        # Write textures
        textures = wad_data.get('textures', [])
        self.write_textures(writer, textures)

        # Write sprites (empty container)
        writer.write_chunk_start(wad2_chunks.ChunkId.Sprites)
        writer.write_chunk_end()

        # Write sprite sequences (empty container)
        writer.write_chunk_start(wad2_chunks.ChunkId.SpriteSequences)
        writer.write_chunk_end()

        # Write moveables
        moveables = wad_data.get('moveables', [])
        self.write_moveables(writer, moveables, options)

        # Write statics
        statics = wad_data.get('statics', [])
        self.write_statics(writer, statics, options)

        # Write metadata
        self.write_metadata(writer)

    def write_metadata(self, writer: ChunkWriter):
        """Write WAD2 metadata chunk"""
        import datetime

        writer.write_chunk_start(wad2_chunks.ChunkId.Metadata)

        # Write timestamp
        now = datetime.datetime.now()
        writer.write_chunk_start(b'W2Timestamp')
        buf = writer.get_current_buffer()
        write_leb128_uint(buf, now.year)
        write_leb128_uint(buf, now.month)
        write_leb128_uint(buf, now.day)
        write_leb128_uint(buf, now.hour)
        write_leb128_uint(buf, now.minute)
        write_leb128_uint(buf, now.second)
        writer.write_chunk_end()

        # Write user notes (empty)
        writer.write_chunk_string(b'W2UserNotes', '')

        writer.write_chunk_end()

    def write_textures(self, writer: ChunkWriter, textures: List[dict]):
        """Write texture data as raw RGBA bytes (width * height * 4)."""
        writer.write_chunk_start(wad2_chunks.ChunkId.Textures)

        for i, texture in enumerate(textures):
            writer.write_chunk_start(wad2_chunks.ChunkId.Txt)
            buf = writer.get_current_buffer()

            width = texture.get('width', 256)
            height = texture.get('height', 256)

            # Write dimensions first (before sub-chunks) - required by WAD2 format
            write_leb128_uint(buf, width)
            write_leb128_uint(buf, height)

            # Write index sub-chunk
            writer.write_chunk_uint(wad2_chunks.ChunkId.TxtIndex, texture.get('index', i))

            # Write name sub-chunk if present
            if texture.get('name'):
                writer.write_chunk_string(wad2_chunks.ChunkId.TxtName, texture['name'])

            # Write texture data as raw bytes
            if texture.get('data'):
                raw_data = texture['data']
                expected = width * height * 4
                if len(raw_data) != expected:
                    if len(raw_data) > expected:
                        raw_data = raw_data[:expected]
                    else:
                        raw_data = raw_data + bytes(expected - len(raw_data))
                writer.write_chunk_start(wad2_chunks.ChunkId.TxtData)
                writer.get_current_buffer().write(raw_data)
                writer.write_chunk_end()

            writer.write_chunk_end()

        writer.write_chunk_end()

    def _create_png(self, bgra_data: bytes, width: int, height: int) -> Optional[bytes]:
        """Deprecated: WAD2 expects raw bytes, not PNG."""
        return None

    def write_meshes(self, writer: ChunkWriter, meshes: List[dict], options):
        """Write root-level mesh data"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Meshes)

        for mesh in meshes:
            self.write_single_mesh(writer, mesh, options)

        writer.write_chunk_end()

    def write_single_mesh(self, writer: ChunkWriter, mesh: dict, options):
        """Write a single mesh matching Wad2Writer.cs format"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Mesh)

        scale = options.get('scale', 512.0)

        # Write mesh index (always 0 for embedded meshes)
        writer.write_chunk_uint(wad2_chunks.ChunkId.MeshIndex, 0)

        # Write mesh name if present
        if mesh.get('name'):
            writer.write_chunk_string(wad2_chunks.ChunkId.MeshName, mesh['name'])

        # Write bounding sphere as container chunk
        sphere = mesh.get('sphere')
        if sphere:
            center = sphere.get('center', (0, 0, 0))
            radius = sphere.get('radius', 0)
            wad_center = _fix_axis_to_wad2((center[0] * scale, center[1] * scale, center[2] * scale))

            writer.write_chunk_start(wad2_chunks.ChunkId.MeshSphere)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshSphC, wad_center)
            writer.write_chunk_float(wad2_chunks.ChunkId.MeshSphR, radius * scale)
            writer.write_chunk_end()

        # Write bounding box as container chunk
        bbox = mesh.get('bbox')
        if bbox:
            bbox_min = bbox.get('min', (0, 0, 0))
            bbox_max = bbox.get('max', (0, 0, 0))
            wad_min = _fix_axis_to_wad2((bbox_min[0] * scale, bbox_min[1] * scale, bbox_min[2] * scale))
            wad_max = _fix_axis_to_wad2((bbox_max[0] * scale, bbox_max[1] * scale, bbox_max[2] * scale))

            writer.write_chunk_start(wad2_chunks.ChunkId.MeshBoundingBox)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMin, wad_min)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMax, wad_max)
            writer.write_chunk_end()

        # Write positions as container with individual position sub-chunks
        positions = mesh.get('positions', [])
        if positions:
            writer.write_chunk_start(wad2_chunks.ChunkId.MeshVertexPositions)
            for pos in positions:
                wad_pos = _fix_axis_to_wad2((pos[0] * scale, pos[1] * scale, pos[2] * scale))
                writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshVertexPosition, wad_pos)
            writer.write_chunk_end()

        # Write normals as container with individual normal sub-chunks
        normals = mesh.get('normals', [])
        if normals:
            writer.write_chunk_start(wad2_chunks.ChunkId.MeshVertexNormals)
            for normal in normals:
                wad_norm = _fix_axis_to_wad2(normal)
                writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshVertexNormal, wad_norm)
            writer.write_chunk_end()

        # Write vertex colors/shades as container with individual color sub-chunks
        shades = mesh.get('shades', [])
        if shades:
            writer.write_chunk_start(wad2_chunks.ChunkId.MeshVertexShades)
            for shade in shades:
                # Convert byte shade to float color (grayscale)
                val = shade / 255.0 if isinstance(shade, int) else 0.5
                writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshVertexColor, (val, val, val))
            writer.write_chunk_end()

        # Write lighting type (default to 0 = Normals)
        writer.write_chunk_uint(wad2_chunks.ChunkId.MeshLightingType, 0)

        # Write polygons as container with individual polygon sub-chunks
        triangles = mesh.get('triangles', [])
        quads = mesh.get('quads', [])
        if triangles or quads:
            writer.write_chunk_start(wad2_chunks.ChunkId.MeshPolys)

            for tri in triangles:
                self.write_polygon(writer, tri, 3, options)

            for quad in quads:
                self.write_polygon(writer, quad, 4, options)

            writer.write_chunk_end()

        writer.write_chunk_end()

    def write_polygon(self, writer: ChunkWriter, poly: dict, vertex_count: int, options):
        """Write a single polygon (triangle or quad)

        Format (W2Tr2/W2Uq2) based on Wad2Writer.cs:
        - vertex_count LEB128 indices
        - LEB128 shine_strength
        - LEB128 texture_index
        - vector2 ParentArea.Start (8 bytes)
        - vector2 ParentArea.End (8 bytes)
        - vertex_count * vector2 UVs (8 bytes each)
        - LEB128 blend_mode
        - bool double_sided (1 byte)
        """
        chunk_id = wad2_chunks.ChunkId.MeshTri2 if vertex_count == 3 else wad2_chunks.ChunkId.MeshQuad2

        writer.write_chunk_start(chunk_id)
        buf = writer.get_current_buffer()

        # Write vertex indices as LEB128
        indices = poly.get('indices', [0] * vertex_count)
        for idx in indices[:vertex_count]:
            write_leb128_uint(buf, idx)

        # Write shine strength as LEB128
        write_leb128_uint(buf, poly.get('shine', 0))

        # Write texture index as LEB128
        write_leb128_uint(buf, poly.get('texture', 0))

        # Write ParentArea (two vector2s = 16 bytes)
        # ParentArea.Start and ParentArea.End - default to 0,0 to full texture
        parent_start = poly.get('parent_area_start', (0.0, 0.0))
        parent_end = poly.get('parent_area_end', (1.0, 1.0))
        write_vector2(buf, parent_start)
        write_vector2(buf, parent_end)

        # Write UVs (vertex_count * 8 bytes)
        uvs = poly.get('uvs', [(0.0, 0.0)] * vertex_count)
        tex_width = options.get('tex_width', 256)
        tex_height = options.get('tex_height', 256)

        for i in range(vertex_count):
            if i < len(uvs):
                u, v = uvs[i]
                # Convert from normalized [0,1] to pixel coordinates
                u_px = u * tex_width
                v_px = (1.0 - v) * tex_height  # Flip V
            else:
                u_px, v_px = 0.0, 0.0
            write_vector2(buf, (u_px, v_px))

        # Write blend mode as LEB128 (not int16!)
        write_leb128_uint(buf, poly.get('blend_mode', 0))

        # Write double-sided flag (1 byte bool)
        write_bool(buf, poly.get('double_sided', False))

        writer.write_chunk_end()

    def write_moveables(self, writer: ChunkWriter, moveables: List[dict], options):
        """Write moveable objects"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Moveables)

        for mov in moveables:
            self.write_single_moveable(writer, mov, options)

        writer.write_chunk_end()

    def write_single_moveable(self, writer: ChunkWriter, mov: dict, options):
        """Write a single moveable"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Moveable)
        buf = writer.get_current_buffer()

        # Write moveable ID first (compact format)
        write_leb128_uint(buf, mov.get('id', 0))

        scale = options.get('scale', 512.0)

        # Write embedded meshes
        meshes = mov.get('meshes', [])
        for mesh in meshes:
            self.write_single_mesh(writer, mesh, options)

        # Write bones using compact format
        bones = mov.get('bones', [])
        for bone in bones:
            self.write_bone_compact(writer, bone, scale)

        # Write animations using compact format
        animations = mov.get('animations', [])
        for anim in animations:
            self.write_animation_compact(writer, anim, scale)

        writer.write_chunk_end()

    def write_bone_compact(self, writer: ChunkWriter, bone: dict, scale: float):
        """Write a bone in compact W2Bone2 format"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Bone2)
        buf = writer.get_current_buffer()

        # Write op code
        buf.write(struct.pack('B', bone.get('op', 0)))

        # Write name (length-prefixed)
        name = bone.get('name', '')
        name_bytes = name.encode('utf-8')
        buf.write(struct.pack('<I', len(name_bytes)))
        buf.write(name_bytes)

        # Write translation sub-chunk
        translation = bone.get('translation', (0, 0, 0))
        wad_trans = _fix_axis_to_wad2((translation[0] * scale, translation[1] * scale, translation[2] * scale))

        # Inline sub-chunk: translation
        write_chunk_id(buf, wad2_chunks.ChunkId.BoneTrans)
        write_leb128_uint(buf, 12)  # 3 floats * 4 bytes
        write_vector3(buf, wad_trans)

        # Write mesh index sub-chunk if present
        mesh_idx = bone.get('mesh', -1)
        if mesh_idx >= 0:
            write_chunk_id(buf, wad2_chunks.ChunkId.BoneMesh)
            # Calculate LEB128 size for mesh index
            mesh_buf = io.BytesIO()
            write_leb128_uint(mesh_buf, mesh_idx)
            mesh_data = mesh_buf.getvalue()
            write_leb128_uint(buf, len(mesh_data))
            buf.write(mesh_data)

        writer.write_chunk_end()

    def write_animation_compact(self, writer: ChunkWriter, anim: dict, scale: float):
        """Write an animation in compact W2Ani2 format (matching Wad2Writer.cs)"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Ani2)
        buf = writer.get_current_buffer()

        # Write header fields (order matches Wad2Writer.cs)
        write_leb128_uint(buf, anim.get('state_id', 0))
        write_leb128_uint(buf, anim.get('end_frame', 0))
        write_leb128_uint(buf, anim.get('frame_rate', 1))
        write_leb128_uint(buf, anim.get('next_animation', 0))
        write_leb128_uint(buf, anim.get('next_frame', 0))

        # Write name sub-chunk if present
        name = anim.get('name', '')
        if name:
            writer.write_chunk_string(wad2_chunks.ChunkId.AnmName, name)

        # Write keyframes
        keyframes = anim.get('keyframes', [])
        for kf in keyframes:
            self.write_keyframe_compact(writer, kf, scale)

        # Write state changes
        state_changes = anim.get('state_changes', {})
        for state_id, dispatches in state_changes.items():
            self.write_state_change_compact(writer, state_id, dispatches)

        # Write commands
        commands = anim.get('commands', [])
        for cmd in commands:
            self.write_command_compact(writer, cmd)

        # Write velocity at the END (matching Wad2Writer.cs)
        velocity = anim.get('velocity', (0.0, 0.0, 0.0, 0.0))
        if isinstance(velocity, (tuple, list)) and len(velocity) >= 4:
            writer.write_chunk_start(wad2_chunks.ChunkId.AniV)
            write_vector4(writer.get_current_buffer(), (
                float(velocity[0]),
                float(velocity[1]),
                float(velocity[2]),
                float(velocity[3])
            ))
            writer.write_chunk_end()

        writer.write_chunk_end()

    def write_keyframe_compact(self, writer: ChunkWriter, kf: dict, scale: float):
        """Write a keyframe in compact format

        Format (W2Kf):
        - W2KfOffs sub-chunk: vector3 offset
        - W2KfBB sub-chunk (optional): contains W2BBMin and W2BBMax
        - W2KfA sub-chunks: one per bone rotation (vector3 angles in degrees)
        """
        writer.write_chunk_start(wad2_chunks.ChunkId.Kf)

        # Write offset sub-chunk
        offset = kf.get('offset', (0, 0, 0))
        wad_offset = _fix_axis_to_wad2((offset[0] * scale, offset[1] * scale, offset[2] * scale))
        writer.write_chunk_vector3(wad2_chunks.ChunkId.KfOffs, wad_offset)

        # Write bounding box if present
        bbox = kf.get('bbox')
        if bbox:
            writer.write_chunk_start(wad2_chunks.ChunkId.KfBB)
            bbox_min = bbox.get('min', (0, 0, 0))
            bbox_max = bbox.get('max', (0, 0, 0))
            # Convert to WAD2 coordinates
            wad_bbox_min = _fix_axis_to_wad2((bbox_min[0] * scale, bbox_min[1] * scale, bbox_min[2] * scale))
            wad_bbox_max = _fix_axis_to_wad2((bbox_max[0] * scale, bbox_max[1] * scale, bbox_max[2] * scale))
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMin, wad_bbox_min)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMax, wad_bbox_max)
            writer.write_chunk_end()

        # Write rotation angles - each as a separate W2KfA sub-chunk
        rotations = kf.get('rotations', [])
        for rot in rotations:
            # Convert quaternion to euler angles in degrees
            if len(rot) == 4:
                # Quaternion format (w, x, y, z)
                yaw, pitch, roll = _quat_to_euler_ypr(rot)
                # WAD2 stores as (X rotation, Y rotation, Z rotation) in degrees
                # which maps to (pitch, yaw, roll)
                writer.write_chunk_vector3(wad2_chunks.ChunkId.KfA, (pitch, yaw, roll))
            elif len(rot) == 3:
                # Already euler angles (degrees)
                writer.write_chunk_vector3(wad2_chunks.ChunkId.KfA, rot)

        writer.write_chunk_end()

    def write_state_change_compact(self, writer: ChunkWriter, state_id: int, dispatches: List):
        """Write a state change in compact format"""
        writer.write_chunk_start(wad2_chunks.ChunkId.StCh)
        buf = writer.get_current_buffer()

        write_leb128_uint(buf, state_id)

        for dispatch in dispatches:
            writer.write_chunk_start(wad2_chunks.ChunkId.Disp)
            disp_buf = writer.get_current_buffer()

            if isinstance(dispatch, (tuple, list)) and len(dispatch) >= 4:
                write_leb128_uint(disp_buf, dispatch[0])  # in_frame
                write_leb128_uint(disp_buf, dispatch[1])  # out_frame
                write_leb128_uint(disp_buf, dispatch[2])  # next_anim
                write_leb128_uint(disp_buf, dispatch[3])  # next_frame
            else:
                # Default values
                write_leb128_uint(disp_buf, 0)
                write_leb128_uint(disp_buf, 0)
                write_leb128_uint(disp_buf, 0)
                write_leb128_uint(disp_buf, 0)

            writer.write_chunk_end()

        writer.write_chunk_end()

    def write_command_compact(self, writer: ChunkWriter, cmd: tuple):
        """Write an animation command in compact format"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Cmd2)
        buf = writer.get_current_buffer()

        if isinstance(cmd, (tuple, list)) and len(cmd) >= 4:
            write_leb128_uint(buf, cmd[0])  # cmd_type
            write_leb128_int(buf, cmd[1])   # param1
            write_leb128_int(buf, cmd[2])   # param2
            write_leb128_int(buf, cmd[3])   # param3
        else:
            write_leb128_uint(buf, 0)
            write_leb128_int(buf, 0)
            write_leb128_int(buf, 0)
            write_leb128_int(buf, 0)

        writer.write_chunk_end()

    def write_statics(self, writer: ChunkWriter, statics: List[dict], options):
        """Write static objects"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Statics)

        for static in statics:
            self.write_single_static(writer, static, options)

        writer.write_chunk_end()

    def write_single_static(self, writer: ChunkWriter, static: dict, options):
        """Write a single static"""
        writer.write_chunk_start(wad2_chunks.ChunkId.Static2)
        buf = writer.get_current_buffer()

        scale = options.get('scale', 512.0)

        # Write static ID
        write_leb128_uint(buf, static.get('id', 0))

        # Write flags
        write_leb128_uint(buf, static.get('flags', 0))

        # Write embedded mesh
        mesh = static.get('mesh')
        if mesh:
            self.write_single_mesh(writer, mesh, options)

        # Write visibility box as container chunk with min/max sub-chunks
        visibility_box = static.get('visibility_box')
        if visibility_box:
            bbox_min = visibility_box.get('min', (0, 0, 0))
            bbox_max = visibility_box.get('max', (0, 0, 0))
            wad_min = _fix_axis_to_wad2((bbox_min[0] * scale, bbox_min[1] * scale, bbox_min[2] * scale))
            wad_max = _fix_axis_to_wad2((bbox_max[0] * scale, bbox_max[1] * scale, bbox_max[2] * scale))

            writer.write_chunk_start(wad2_chunks.ChunkId.StaticVisibilityBox)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMin, wad_min)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMax, wad_max)
            writer.write_chunk_end()

        # Write collision box as container chunk with min/max sub-chunks
        collision_box = static.get('collision_box')
        if collision_box:
            bbox_min = collision_box.get('min', (0, 0, 0))
            bbox_max = collision_box.get('max', (0, 0, 0))
            wad_min = _fix_axis_to_wad2((bbox_min[0] * scale, bbox_min[1] * scale, bbox_min[2] * scale))
            wad_max = _fix_axis_to_wad2((bbox_max[0] * scale, bbox_max[1] * scale, bbox_max[2] * scale))

            writer.write_chunk_start(wad2_chunks.ChunkId.StaticCollisionBox)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMin, wad_min)
            writer.write_chunk_vector3(wad2_chunks.ChunkId.MeshBBMax, wad_max)
            writer.write_chunk_end()

        writer.write_chunk_end()


def write_wad2(filepath: str, wad_data: dict, options: dict):
    """Write a WAD2 file"""
    writer = Wad2Writer()
    writer.write(filepath, wad_data, options)
