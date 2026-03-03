"""
Texture Packer for WAD/WAD2 Blender Importer

Extracts only the texture regions actually referenced by mesh UVs,
packs them into a compact atlas using a shelf/skyline bin-packing
algorithm, and returns a UV remap table + the new texture image.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional


# ---------------------------------------------------------------------------
# Rectangle packing – Skyline / shelf algorithm
# ---------------------------------------------------------------------------

class _SkylinePacker:
    """
    Skyline-based 2D rectangle bin packer.

    Places rectangles along a "skyline" (the top edge of already-placed
    content). Fast and produces good results for texture atlases.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # Skyline is a list of (x, y, width) segments.
        # Initially one segment spanning the full width at y=0.
        self.skyline: List[List[int]] = [[0, 0, width]]

    def pack(self, w: int, h: int) -> Optional[Tuple[int, int]]:
        """Try to place a rectangle of size (w, h). Returns (x, y) or None."""
        best_y = self.height
        best_idx = -1
        best_x = 0

        for i, (sx, sy, sw) in enumerate(self.skyline):
            # Check if the rectangle can start at this segment
            y = self._fit(i, w, h)
            if y is not None and y < best_y:
                best_y = y
                best_idx = i
                best_x = sx

        if best_idx == -1 or best_y + h > self.height:
            return None

        # Place the rectangle
        new_seg = [best_x, best_y + h, w]

        # Remove segments that are fully covered
        i = best_idx
        remaining_w = w
        while i < len(self.skyline) and remaining_w > 0:
            sx, sy, sw = self.skyline[i]
            if sw <= remaining_w:
                remaining_w -= sw
                self.skyline.pop(i)
            else:
                # Partially covered – shrink this segment
                self.skyline[i][0] += remaining_w
                self.skyline[i][2] -= remaining_w
                remaining_w = 0

        self.skyline.insert(best_idx, new_seg)
        self._merge()
        return (best_x, best_y)

    def _fit(self, idx: int, w: int, h: int) -> Optional[int]:
        """Check if a rect of (w, h) fits starting at skyline segment idx."""
        sx, sy, sw = self.skyline[idx]
        if sx + w > self.width:
            return None

        remaining = w
        y = sy
        i = idx
        while remaining > 0 and i < len(self.skyline):
            y = max(y, self.skyline[i][1])
            if y + h > self.height:
                return None
            remaining -= self.skyline[i][2]
            i += 1

        return y

    def _merge(self):
        """Merge adjacent segments with the same height."""
        i = 0
        while i < len(self.skyline) - 1:
            if self.skyline[i][1] == self.skyline[i + 1][1]:
                self.skyline[i][2] += self.skyline[i + 1][2]
                self.skyline.pop(i + 1)
            else:
                i += 1


def _next_power_of_two(v: int) -> int:
    """Round up to the next power of two (minimum 16)."""
    v = max(v, 16)
    v -= 1
    v |= v >> 1
    v |= v >> 2
    v |= v >> 4
    v |= v >> 8
    v |= v >> 16
    return v + 1


def _pack_rects(
    rects: List[Tuple[int, int]],
    padding: int = 1,
) -> Tuple[Dict[int, Tuple[int, int]], int, int]:
    """
    Pack a list of (width, height) rectangles into the smallest
    power-of-two atlas. Tries non-square dimensions (e.g. 256x128)
    to minimize wasted space. Returns {index: (x, y)}, atlas_w, atlas_h.
    """
    if not rects:
        return {}, 0, 0

    # Add padding to each rect
    padded = [(w + padding * 2, h + padding * 2) for w, h in rects]

    # Sort by area descending (biggest first = top-left), then by height as tiebreaker
    order = sorted(range(len(padded)), key=lambda i: (padded[i][0] * padded[i][1], padded[i][1]), reverse=True)

    # Determine minimum dimensions from the largest single rect
    max_w = max(w for w, h in padded)
    max_h = max(h for w, h in padded)
    min_w = _next_power_of_two(max_w)
    min_h = _next_power_of_two(max_h)

    total_area = sum(w * h for w, h in padded)
    start_side = _next_power_of_two(int(total_area ** 0.5))

    def _try_pack(aw, ah):
        """Attempt to pack all rects into aw x ah. Returns placements or None."""
        packer = _SkylinePacker(aw, ah)
        placements = {}
        for idx in order:
            w, h = padded[idx]
            pos = packer.pack(w, h)
            if pos is None:
                return None
            placements[idx] = (pos[0] + padding, pos[1] + padding)
        return placements

    # Generate candidate sizes: try various non-square PoT combinations
    # sorted by total area (smallest first)
    candidates = set()
    for w_exp in range(4, 14):  # 16 to 8192
        for h_exp in range(4, 14):
            w = 1 << w_exp
            h = 1 << h_exp
            if w >= min_w and h >= min_h and w * h >= total_area:
                candidates.add((w * h, w, h))

    # Sort by area, then prefer squarer shapes as tiebreaker
    candidates = sorted(candidates, key=lambda c: (c[0], abs(c[1] - c[2])))

    # Try each candidate size, smallest first
    for area, aw, ah in candidates:
        result = _try_pack(aw, ah)
        if result is not None:
            return result, aw, ah

    # Fallback: keep doubling a square until it fits
    side = max(start_side, min_w, min_h)
    for attempt in range(10):
        result = _try_pack(side, side)
        if result is not None:
            return result, side, side
        side *= 2

    print("[TexturePacker] Warning: Could not fit all rects into atlas")
    return {}, side, side


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pack_object_textures(
    meshes,
    texture_path: str,
    padding: int = 1,
) -> Tuple[Dict[Tuple[int, int, int, int], Tuple[int, int]], np.ndarray]:
    """
    Extract used texture regions from the full texture map, repack them
    into a compact atlas, and return a UV remap table.

    This handles classic WAD files where there's a single tall texture map
    and each polygon references a region via (x, y, width, height) in
    pixel coordinates.

    Parameters
    ----------
    meshes : list of model.Mesh
        The meshes whose polygons reference texture regions.
    texture_path : str
        Path to the full texture map PNG on disk.

    Returns
    -------
    uvtable : dict
        Maps (x, y, w, h) -> (new_x, new_y) in the packed atlas.
    atlas : np.ndarray
        The new RGBA texture atlas as a uint8 numpy array (H, W, 4).
    """
    from PIL import Image

    # Load the source texture map
    src_img = Image.open(texture_path).convert('RGBA')
    src_arr = np.array(src_img)  # (H, W, 4) uint8

    # 1. Collect unique texture regions from all polygons
    unique_regions: Dict[Tuple[int, int, int, int], None] = {}
    for mesh in meshes:
        for polygon in mesh.polygons:
            key = (polygon.x, polygon.y, polygon.tex_width, polygon.tex_height)
            unique_regions[key] = None

    region_list = list(unique_regions.keys())

    if not region_list:
        # No regions – return an empty 1x1 atlas
        return {}, np.zeros((1, 1, 4), dtype=np.uint8)

    # 2. Pack rectangles
    rect_sizes = [(w, h) for (_, _, w, h) in region_list]
    placements, atlas_w, atlas_h = _pack_rects(rect_sizes, padding=padding)

    if not placements:
        # Packing failed – fall back to source dimensions
        return {}, src_arr

    # 3. Blit regions into new atlas
    atlas = np.zeros((atlas_h, atlas_w, 4), dtype=np.uint8)
    uvtable: Dict[Tuple[int, int, int, int], Tuple[int, int]] = {}

    for i, (x, y, w, h) in enumerate(region_list):
        if i not in placements:
            continue

        nx, ny = placements[i]

        # Clamp source region to image bounds
        sy_end = min(y + h, src_arr.shape[0])
        sx_end = min(x + w, src_arr.shape[1])
        actual_h = sy_end - y
        actual_w = sx_end - x

        if actual_h > 0 and actual_w > 0:
            atlas[ny:ny + actual_h, nx:nx + actual_w] = \
                src_arr[y:sy_end, x:sx_end]

        uvtable[(x, y, w, h)] = (nx, ny)

    return uvtable, atlas


def pack_wad2_textures(
    meshes,
    texture_images: List[np.ndarray],
    padding: int = 4,
    bleed: int = 4,
) -> Tuple[np.ndarray, List]:
    """
    Repack WAD2 per-page textures into a single compact atlas.

    WAD2 files store textures as separate images (one per "page").
    Each polygon has UV coordinates normalized to its page's dimensions
    and a `page` index. This function:

    1. For each polygon, computes the pixel-space bounding box of its UVs
       on the source texture page.
    2. Collects all unique regions across all pages.
    3. Packs them into a single atlas.
    4. Rewrites each polygon's tbox/UV data to reference the new atlas.

    Parameters
    ----------
    meshes : list of model.Mesh
        Meshes with polygons that have .page, .tbox (normalized UVs).
    texture_images : list of np.ndarray
        Each element is an RGBA uint8 array (H, W, 4) for that page index.
    padding : int
        Pixels of padding around each region in the atlas.
    bleed : int
        Pixels of edge-colour bleed into the padding area. Must be <= padding.
        Used to prevent colour bleeding when generating mipmaps/normal maps.

    Returns
    -------
    atlas : np.ndarray
        The packed RGBA atlas (H, W, 4), uint8.
    polygon_uv_updates : list of (mesh_idx, poly_idx, new_tbox)
        New UV coordinates (normalized to atlas) for each polygon.
    """
    if not texture_images:
        return np.zeros((1, 1, 4), dtype=np.uint8), []

    # 1. For each polygon, compute the source pixel region
    #    tbox contains normalized UVs, page tells us which texture.
    RegionKey = Tuple[int, int, int, int, int]  # (page, px, py, pw, ph)
    unique_regions: Dict[RegionKey, None] = {}
    poly_region_map: List[Tuple[int, int, RegionKey]] = []  # (mesh_idx, poly_idx, key)

    for mesh_idx, mesh in enumerate(meshes):
        for poly_idx, polygon in enumerate(mesh.polygons):
            page = polygon.page
            if page < 0 or page >= len(texture_images):
                page = 0

            tex_h, tex_w = texture_images[page].shape[:2]

            # Get pixel-space bounding box from UV coordinates
            us = []
            vs = []
            for u, v in polygon.tbox:
                # tbox UVs are normalized [0,1], with v=1 at top
                # Clamp to [0, dim-1] to stay within pixel bounds
                px = max(0.0, min(u * tex_w, tex_w - 0.001))
                py = max(0.0, min((1.0 - v) * tex_h, tex_h - 0.001))
                us.append(px)
                vs.append(py)

            min_u = max(0, int(min(us)))
            min_v = max(0, int(min(vs)))
            max_u = min(tex_w, int(max(us)) + 1)   # exclusive end, ceil
            max_v = min(tex_h, int(max(vs)) + 1)

            pw = max(1, max_u - min_u)
            ph = max(1, max_v - min_v)

            key = (page, min_u, min_v, pw, ph)
            unique_regions[key] = None
            poly_region_map.append((mesh_idx, poly_idx, key))

    region_list = list(unique_regions.keys())

    if not region_list:
        return np.zeros((1, 1, 4), dtype=np.uint8), []

    # Diagnostic: print region summary
    pages_seen = set()
    total_region_area = 0
    for page, px, py, pw, ph in region_list:
        pages_seen.add(page)
        total_region_area += pw * ph
    total_page_area = sum(img.shape[0] * img.shape[1] for i, img in enumerate(texture_images) if i in pages_seen)
    print(f"[TexturePacker] {len(region_list)} unique regions from {len(pages_seen)} pages")
    print(f"[TexturePacker] Total region area: {total_region_area} px, "
          f"total source page area: {total_page_area} px, "
          f"ratio: {total_region_area/max(1,total_page_area)*100:.1f}%")
    for i, (page, px, py, pw, ph) in enumerate(region_list[:10]):
        print(f"[TexturePacker]   Region {i}: page={page} pos=({px},{py}) size={pw}x{ph}")
    if len(region_list) > 10:
        print(f"[TexturePacker]   ... and {len(region_list)-10} more")

    # 2. Pack rectangles
    rect_sizes = [(pw, ph) for (_, _, _, pw, ph) in region_list]
    placements, atlas_w, atlas_h = _pack_rects(rect_sizes, padding=padding)

    if not placements:
        return np.zeros((1, 1, 4), dtype=np.uint8), []

    # Build lookup: region_key -> (new_x, new_y)
    region_key_to_idx = {key: i for i, key in enumerate(region_list)}
    region_placement: Dict[RegionKey, Tuple[int, int]] = {}
    for i, key in enumerate(region_list):
        if i in placements:
            region_placement[key] = placements[i]

    # 3. Blit regions into atlas, then apply texture bleed
    atlas = np.zeros((atlas_h, atlas_w, 4), dtype=np.uint8)

    for key, (nx, ny) in region_placement.items():
        page, sx, sy, pw, ph = key
        src = texture_images[page]
        src_h, src_w = src.shape[:2]

        # Clamp to source bounds
        sy_end = min(sy + ph, src_h)
        sx_end = min(sx + pw, src_w)
        ah = sy_end - sy
        aw = sx_end - sx

        if ah > 0 and aw > 0:
            atlas[ny:ny + ah, nx:nx + aw] = src[sy:sy_end, sx:sx_end]

            # Texture bleed: extend edge pixels into padding area.
            # This prevents colour bleeding from adjacent tiles when
            # mipmaps or bilinear filtering sample beyond the tile edge.
            bleed_dist = min(bleed, padding)  # Can't bleed more than padding allows
            if bleed_dist > 0:
                # Top edge: copy first row upward
                for b in range(1, bleed_dist + 1):
                    if ny - b >= 0:
                        atlas[ny - b, nx:nx + aw] = atlas[ny, nx:nx + aw]
                # Bottom edge: copy last row downward
                for b in range(1, bleed_dist + 1):
                    if ny + ah - 1 + b < atlas_h:
                        atlas[ny + ah - 1 + b, nx:nx + aw] = atlas[ny + ah - 1, nx:nx + aw]
                # Left edge: copy first column leftward
                for b in range(1, bleed_dist + 1):
                    if nx - b >= 0:
                        atlas[ny:ny + ah, nx - b] = atlas[ny:ny + ah, nx]
                # Right edge: copy last column rightward
                for b in range(1, bleed_dist + 1):
                    if nx + aw - 1 + b < atlas_w:
                        atlas[ny:ny + ah, nx + aw - 1 + b] = atlas[ny:ny + ah, nx + aw - 1]

    # 4. Compute new UV coordinates for each polygon
    polygon_uv_updates = []
    for mesh_idx, poly_idx, key in poly_region_map:
        if key not in region_placement:
            continue

        page, src_x, src_y, pw, ph = key
        nx, ny = region_placement[key]
        tex_h, tex_w = texture_images[page].shape[:2]

        mesh = meshes[mesh_idx]
        polygon = mesh.polygons[poly_idx]

        new_tbox = []
        for u, v in polygon.tbox:
            # Original pixel position on source page
            px = u * tex_w
            py = (1.0 - v) * tex_h

            # Offset into the region
            local_x = px - src_x
            local_y = py - src_y

            # New position in atlas
            atlas_px = nx + local_x
            atlas_py = ny + local_y

            # Normalize to atlas dimensions
            new_u = atlas_px / atlas_w
            new_v = 1.0 - (atlas_py / atlas_h)

            new_tbox.append((new_u, new_v))

        polygon_uv_updates.append((mesh_idx, poly_idx, new_tbox))

    return atlas, polygon_uv_updates
