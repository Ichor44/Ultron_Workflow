"""
Procedural 3D Model Generation Skill

Generates basic geometric primitives (cube, sphere, cylinder, cone, torus)
and exports them as STL (binary/ASCII) or OBJ files.
"""

import math
import struct
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass

NAME = "procgen_3d"
DESCRIPTION = "Procedural 3D CAD model generation - creates basic geometric primitives (cube, sphere, cylinder, cone, torus) and exports them as STL or OBJ files for 3D printing and CAD"
TRIGGERS = ["cad", "3d cad", "3d model", "create 3d model", "generate 3d", "procedural generation", "make stl", "make obj", "3d primitive", "3d print", "3d printing", "stl file", "obj file", "geometric", "shape", "cube", "sphere", "cylinder", "cone", "torus", "3d design", "model design", "part design", "mechanical design"]


@dataclass
class Mesh:
    """Simple triangle mesh container."""
    vertices: List[Tuple[float, float, float]]
    faces: List[Tuple[int, int, int]]
    normals: Optional[List[Tuple[float, float, float]]] = None

    def translate(self, dx: float, dy: float, dz: float) -> "Mesh":
        return Mesh(
            vertices=[(x + dx, y + dy, z + dz) for x, y, z in self.vertices],
            faces=self.faces.copy(),
            normals=self.normals.copy() if self.normals else None
        )

    def scale(self, sx: float, sy: float, sz: float) -> "Mesh":
        return Mesh(
            vertices=[(x * sx, y * sy, z * sz) for x, y, z in self.vertices],
            faces=self.faces.copy(),
            normals=self.normals.copy() if self.normals else None
        )

    def rotate_x(self, angle: float) -> "Mesh":
        """Rotate around X axis (radians)."""
        c, s = math.cos(angle), math.sin(angle)
        return Mesh(
            vertices=[(x, y * c - z * s, y * s + z * c) for x, y, z in self.vertices],
            faces=self.faces.copy(),
            normals=[(nx, ny * c - nz * s, ny * s + nz * c) for nx, ny, nz in self.normals] if self.normals else None
        )

    def rotate_y(self, angle: float) -> "Mesh":
        """Rotate around Y axis (radians)."""
        c, s = math.cos(angle), math.sin(angle)
        return Mesh(
            vertices=[(x * c + z * s, y, -x * s + z * c) for x, y, z in self.vertices],
            faces=self.faces.copy(),
            normals=[(nx * c + nz * s, ny, -nx * s + nz * c) for nx, ny, nz in self.normals] if self.normals else None
        )

    def rotate_z(self, angle: float) -> "Mesh":
        """Rotate around Z axis (radians)."""
        c, s = math.cos(angle), math.sin(angle)
        return Mesh(
            vertices=[(x * c - y * s, x * s + y * c, z) for x, y, z in self.vertices],
            faces=self.faces.copy(),
            normals=[(nx * c - ny * s, nx * s + ny * c, nz) for nx, ny, nz in self.normals] if self.normals else None
        )

    def merge(self, other: "Mesh") -> "Mesh":
        """Merge another mesh into this one."""
        offset = len(self.vertices)
        return Mesh(
            vertices=self.vertices + other.vertices,
            faces=self.faces + [(a + offset, b + offset, c + offset) for a, b, c in other.faces],
            normals=(self.normals + other.normals) if self.normals and other.normals else None
        )


# ===== Primitive Generators =====

def make_cube(size: float = 1.0, center: bool = True) -> Mesh:
    """Generate a cube mesh."""
    half = size / 2.0
    if center:
        vertices = [
            (-half, -half, -half), (half, -half, -half), (half, half, -half), (-half, half, -half),
            (-half, -half, half),  (half, -half, half),  (half, half, half),  (-half, half, half),
        ]
    else:
        vertices = [
            (0, 0, 0), (size, 0, 0), (size, size, 0), (0, size, 0),
            (0, 0, size), (size, 0, size), (size, size, size), (0, size, size),
        ]

    # Faces with outward normals (CCW winding)
    faces = [
        (0, 1, 2), (0, 2, 3),  # -Z
        (4, 5, 6), (4, 6, 7),  # +Z
        (0, 4, 7), (0, 7, 3),  # -X
        (1, 5, 6), (1, 6, 2),  # +X
        (0, 1, 5), (0, 5, 4),  # -Y
        (3, 2, 6), (3, 6, 7),  # +Y
    ]

    normals = [
        (0, 0, -1), (0, 0, -1),
        (0, 0, 1), (0, 0, 1),
        (-1, 0, 0), (-1, 0, 0),
        (1, 0, 0), (1, 0, 0),
        (0, -1, 0), (0, -1, 0),
        (0, 1, 0), (0, 1, 0),
    ]
    return Mesh(vertices, faces, normals)


def make_sphere(radius: float = 1.0, segments: int = 16, rings: int = 8) -> Mesh:
    """Generate a UV sphere mesh."""
    vertices = []
    normals = []
    faces = []

    for r in range(rings + 1):
        theta = math.pi * r / rings
        sin_theta = math.sin(theta)
        cos_theta = math.cos(theta)
        for s in range(segments):
            phi = 2 * math.pi * s / segments
            x = radius * sin_theta * math.cos(phi)
            y = radius * sin_theta * math.sin(phi)
            z = radius * cos_theta
            vertices.append((x, y, z))
            normals.append((x / radius, y / radius, z / radius))

    for r in range(rings):
        for s in range(segments):
            curr = r * segments + s
            next_s = r * segments + (s + 1) % segments
            next_r = (r + 1) * segments + s
            next_r_s = (r + 1) * segments + (s + 1) % segments

            if r > 0:
                faces.append((curr, next_r, next_s))
            if r < rings - 1:
                faces.append((next_s, next_r, next_r_s))

    return Mesh(vertices, faces, normals)


def make_cylinder(radius: float = 1.0, height: float = 2.0, segments: int = 16, capped: bool = True) -> Mesh:
    """Generate a cylinder mesh."""
    vertices = []
    normals = []
    faces = []
    half_h = height / 2.0

    # Top and bottom center vertices
    top_center = len(vertices)
    vertices.append((0, 0, half_h))
    normals.append((0, 0, 1))
    bottom_center = len(vertices)
    vertices.append((0, 0, -half_h))
    normals.append((0, 0, -1))

    # Side vertices
    side_start = len(vertices)
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        vertices.append((x, y, half_h))    # top ring
        vertices.append((x, y, -half_h))   # bottom ring
        nx, ny = math.cos(angle), math.sin(angle)
        normals.append((nx, ny, 0))
        normals.append((nx, ny, 0))

    # Side faces
    for i in range(segments):
        next_i = (i + 1) % segments
        top_curr = side_start + i * 2
        top_next = side_start + next_i * 2
        bot_curr = top_curr + 1
        bot_next = top_next + 1
        faces.append((top_curr, bot_curr, top_next))
        faces.append((top_next, bot_curr, bot_next))

    # Caps
    if capped:
        for i in range(segments):
            next_i = (i + 1) % segments
            top_curr = side_start + i * 2
            top_next = side_start + next_i * 2
            bot_curr = top_curr + 1
            bot_next = top_next + 1
            # Top cap (CCW from above)
            faces.append((top_center, top_next, top_curr))
            # Bottom cap (CCW from below)
            faces.append((bottom_center, bot_curr, bot_next))

    return Mesh(vertices, faces, normals)


def make_cone(radius: float = 1.0, height: float = 2.0, segments: int = 16, capped: bool = True) -> Mesh:
    """Generate a cone mesh."""
    vertices = []
    normals = []
    faces = []
    half_h = height / 2.0

    # Apex and base center
    apex = len(vertices)
    vertices.append((0, 0, half_h))
    normals.append((0, 0, 1))
    base_center = len(vertices)
    vertices.append((0, 0, -half_h))
    normals.append((0, 0, -1))

    # Base ring vertices
    base_start = len(vertices)
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        vertices.append((x, y, -half_h))
        # Normal points outward and slightly up (45 deg for cone)
        normals.append((x / radius * 0.707, y / radius * 0.707, 0.707))

    # Side faces (apex to base ring)
    for i in range(segments):
        next_i = (i + 1) % segments
        faces.append((apex, base_start + next_i, base_start + i))

    # Base cap
    if capped:
        for i in range(segments):
            next_i = (i + 1) % segments
            faces.append((base_center, base_start + i, base_start + next_i))

    return Mesh(vertices, faces, normals)


def make_torus(major_radius: float = 1.0, minor_radius: float = 0.3, major_segments: int = 32, minor_segments: int = 16) -> Mesh:
    """Generate a torus mesh."""
    vertices = []
    normals = []
    faces = []

    for i in range(major_segments):
        u = 2 * math.pi * i / major_segments
        cu, su = math.cos(u), math.sin(u)
        for j in range(minor_segments):
            v = 2 * math.pi * j / minor_segments
            cv, sv = math.cos(v), math.sin(v)

            x = (major_radius + minor_radius * cv) * cu
            y = (major_radius + minor_radius * cv) * su
            z = minor_radius * sv
            vertices.append((x, y, z))

            nx = cv * cu
            ny = cv * su
            nz = sv
            normals.append((nx, ny, nz))

    for i in range(major_segments):
        next_i = (i + 1) % major_segments
        for j in range(minor_segments):
            next_j = (j + 1) % minor_segments
            a = i * minor_segments + j
            b = i * minor_segments + next_j
            c = next_i * minor_segments + j
            d = next_i * minor_segments + next_j
            faces.append((a, c, b))
            faces.append((b, c, d))

    return Mesh(vertices, faces, normals)


# ===== Export Functions =====

def _face_normal(v1, v2, v3):
    """Compute a unit face normal via cross product."""
    ux, uy, uz = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
    vx, vy, vz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length > 0:
        nx, ny, nz = nx / length, ny / length, nz / length
    return nx, ny, nz


def export_stl(mesh: Mesh, path: Path, binary: bool = True) -> None:
    """Export mesh as STL file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if binary:
        with open(path, "wb") as f:
            # 80-byte header
            f.write(b"Generated by procgen_3d skill" + b"\x00" * 51)
            # Number of triangles (4 bytes)
            f.write(struct.pack("<I", len(mesh.faces)))
            for a, b, c in mesh.faces:
                nx, ny, nz = _face_normal(mesh.vertices[a], mesh.vertices[b], mesh.vertices[c])
                f.write(struct.pack("<fff", nx, ny, nz))
                f.write(struct.pack("<fff", *mesh.vertices[a]))
                f.write(struct.pack("<fff", *mesh.vertices[b]))
                f.write(struct.pack("<fff", *mesh.vertices[c]))
                f.write(struct.pack("<H", 0))  # attribute byte count
    else:
        with open(path, "w") as f:
            f.write("solid procgen_model\n")
            for a, b, c in mesh.faces:
                nx, ny, nz = _face_normal(mesh.vertices[a], mesh.vertices[b], mesh.vertices[c])
                f.write(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}\n")
                f.write("    outer loop\n")
                f.write(f"      vertex {mesh.vertices[a][0]:.6f} {mesh.vertices[a][1]:.6f} {mesh.vertices[a][2]:.6f}\n")
                f.write(f"      vertex {mesh.vertices[b][0]:.6f} {mesh.vertices[b][1]:.6f} {mesh.vertices[b][2]:.6f}\n")
                f.write(f"      vertex {mesh.vertices[c][0]:.6f} {mesh.vertices[c][1]:.6f} {mesh.vertices[c][2]:.6f}\n")
                f.write("    endloop\n")
                f.write("  endfacet\n")
            f.write("endsolid procgen_model\n")


def export_obj(mesh: Mesh, path: Path) -> None:
    """Export mesh as OBJ file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("# Generated by procgen_3d skill\n")
        for v in mesh.vertices:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        if mesh.normals:
            for n in mesh.normals:
                f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
        for a, b, c in mesh.faces:
            # OBJ indices are 1-based
            if mesh.normals:
                f.write(f"f {a+1}//{a+1} {b+1}//{b+1} {c+1}//{c+1}\n")
            else:
                f.write(f"f {a+1} {b+1} {c+1}\n")


# ===== Main Entry Point =====

def run(
    primitive: str = "cube",
    output: str = "model.stl",
    format: str = "stl",
    # Primitive parameters
    size: float = 1.0,
    radius: float = 1.0,
    height: float = 2.0,
    major_radius: float = 1.0,
    minor_radius: float = 0.3,
    segments: int = 16,
    rings: int = 8,
    major_segments: int = 32,
    minor_segments: int = 16,
    capped: bool = True,
    center: bool = True,
    # Transformations
    translate_x: float = 0.0,
    translate_y: float = 0.0,
    translate_z: float = 0.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    scale_z: float = 1.0,
    rotate_x: float = 0.0,
    rotate_y: float = 0.0,
    rotate_z: float = 0.0,
    binary_stl: bool = True,
) -> str:
    """
    Generate a 3D model procedurally and save to file.

    Args:
        primitive: One of "cube", "sphere", "cylinder", "cone", "torus"
        output: Output file path (e.g., "models/cube.stl")
        format: "stl" or "obj"
        Primitive-specific parameters:
            cube: size, center
            sphere: radius, segments, rings
            cylinder: radius, height, segments, capped
            cone: radius, height, segments, capped
            torus: major_radius, minor_radius, major_segments, minor_segments
        Transformations (applied in order: scale -> rotate -> translate):
            translate_x/y/z: Translation
            scale_x/y/z: Scaling factors
            rotate_x/y/z: Rotation in degrees
        binary_stl: Use binary STL (True) or ASCII (False)

    Returns:
        Success message with file path and stats.
    """
    primitive = primitive.lower()
    format = format.lower()

    # Generate base mesh
    makers = {
        "cube": lambda: make_cube(size=size, center=center),
        "sphere": lambda: make_sphere(radius=radius, segments=segments, rings=rings),
        "cylinder": lambda: make_cylinder(radius=radius, height=height, segments=segments, capped=capped),
        "cone": lambda: make_cone(radius=radius, height=height, segments=segments, capped=capped),
        "torus": lambda: make_torus(major_radius=major_radius, minor_radius=minor_radius,
                                    major_segments=major_segments, minor_segments=minor_segments),
    }
    if primitive not in makers:
        return f"Error: Unknown primitive '{primitive}'. Choose from: cube, sphere, cylinder, cone, torus"
    mesh = makers[primitive]()

    # Apply transformations (scale -> rotate -> translate)
    if scale_x != 1.0 or scale_y != 1.0 or scale_z != 1.0:
        mesh = mesh.scale(scale_x, scale_y, scale_z)

    if rotate_x != 0.0:
        mesh = mesh.rotate_x(math.radians(rotate_x))
    if rotate_y != 0.0:
        mesh = mesh.rotate_y(math.radians(rotate_y))
    if rotate_z != 0.0:
        mesh = mesh.rotate_z(math.radians(rotate_z))

    if translate_x != 0.0 or translate_y != 0.0 or translate_z != 0.0:
        mesh = mesh.translate(translate_x, translate_y, translate_z)

    # Export
    out_path = Path(output)
    if format == "stl":
        export_stl(mesh, out_path, binary=binary_stl)
    elif format == "obj":
        export_obj(mesh, out_path)
    else:
        return f"Error: Unknown format '{format}'. Use 'stl' or 'obj'"

    return f"Generated {primitive} ({len(mesh.vertices)} vertices, {len(mesh.faces)} faces) -> {out_path.absolute()}"


if __name__ == "__main__":
    # Quick demo
    import sys
    if len(sys.argv) > 1:
        print(run(primitive=sys.argv[1], output=f"demo_{sys.argv[1]}.stl"))
    else:
        print(run("cube", "demo_cube.stl"))
        print(run("sphere", "demo_sphere.stl"))
        print(run("cylinder", "demo_cylinder.stl"))
        print(run("cone", "demo_cone.stl"))
        print(run("torus", "demo_torus.stl"))