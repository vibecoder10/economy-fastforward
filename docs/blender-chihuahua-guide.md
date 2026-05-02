# Blender Chihuahua Modeling Guide (for Blender MCP Agent)

Reference subject: short-haired **apple-head Chihuahua**, cream/white coat, standing 3/4 pose, large upright triangular ears, big round dark eyes, small black nose, slim legs, tail held up.

This guide is written for an agent driving Blender through the **Blender MCP** (`blender-mcp`). The MCP typically exposes:

- `get_scene_info()` / `get_object_info(name)` — inspect state
- `execute_blender_code(code: str)` — run arbitrary Python
- `get_viewport_screenshot(max_size=800)` — visually verify progress
- `download_polyhaven_asset(...)` — optional HDRIs / textures

**Verify visually after every major phase** using `get_viewport_screenshot`. Do NOT proceed if proportions look wrong — fix first.

---

## 0. Reference anatomy (what the agent must replicate)

| Feature | Spec (from photo) |
|---|---|
| Coat | Smooth, short, cream/white, faint warm tint inside ears |
| Skull | Apple-shaped (rounded dome, distinct stop) |
| Muzzle | Short, ~1/3 of head length, slight upward tilt |
| Eyes | Large, round, very dark brown / near-black, slightly protruding |
| Ears | Erect, large, triangular, broad at base, ~45° outward flare |
| Body | Compact, slightly longer than tall, level topline |
| Legs | Slim, straight, fine bone; rear with subtle angulation |
| Paws | Small, oval ("hare foot"), 4 visible toes per paw |
| Tail | Medium length, curved up and forward, NOT touching back |
| Pose | Standing, weight even, head slightly turned to camera-right |

**Approximate target dimensions** (real-world scale, meters):
- Total length nose-to-tail-base: **0.32 m**
- Shoulder height: **0.20 m**
- Head length: **0.09 m**
- Ear height: **0.07 m**

Set Blender units to Metric, scale 1.0, before starting.

---

## 1. Scene setup

```python
import bpy

# Wipe default scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Units
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1.0

# Camera — 3/4 front view matching the reference
cam_data = bpy.data.cameras.new("Cam")
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (0.55, -0.55, 0.22)
cam.rotation_euler = (1.40, 0.0, 0.78)  # ~80°, 0°, 45°
bpy.context.scene.camera = cam

# Three-point lighting (clean white-product look like the reference)
def add_light(name, kind, loc, energy, size=0.5):
    d = bpy.data.lights.new(name, kind)
    d.energy = energy
    if kind == 'AREA': d.size = size
    o = bpy.data.objects.new(name, d)
    o.location = loc
    bpy.context.collection.objects.link(o)
    return o

add_light("Key",  'AREA', ( 1.0, -1.0, 1.2), 200, 1.0)
add_light("Fill", 'AREA', (-1.2, -0.6, 0.8),  80, 1.2)
add_light("Rim",  'AREA', ( 0.0,  1.2, 1.0), 120, 0.8)

# White seamless background
world = bpy.data.worlds.new("W")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
```

**Verify:** `get_viewport_screenshot()` — should see empty white scene with camera-friendly angle.

---

## 2. Blocking pass (primitive proportions)

Build the silhouette with primitives BEFORE any sculpting. Lock proportions early — they're the #1 thing humans read as "wrong" in animal models.

Coordinate convention: **+X = right, +Y = forward (nose direction), +Z = up**. Dog faces **+Y**.

```python
import bpy

def add_uvsphere(name, loc, scale, segs=32, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segs, ring_count=rings, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    bpy.ops.object.shade_smooth()
    return o

# --- TORSO (slightly elongated sphere) ---
torso = add_uvsphere("Torso", (0, 0.00, 0.135), (0.060, 0.110, 0.070))

# --- CHEST (deeper front) ---
chest = add_uvsphere("Chest", (0, 0.10, 0.130), (0.055, 0.060, 0.065))

# --- HIPS ---
hips = add_uvsphere("Hips", (0, -0.09, 0.135), (0.058, 0.060, 0.065))

# --- NECK (short, angled up-forward) ---
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.030, depth=0.07,
                                    location=(0, 0.155, 0.165))
neck = bpy.context.active_object
neck.name = "Neck"
neck.rotation_euler = (1.05, 0, 0)  # tip forward + up
bpy.ops.object.shade_smooth()

# --- HEAD (apple skull) ---
head = add_uvsphere("Head", (0, 0.195, 0.205), (0.040, 0.045, 0.045))

# --- MUZZLE (short, ~1/3 head length, slight upward tilt) ---
muzzle = add_uvsphere("Muzzle", (0, 0.235, 0.190), (0.022, 0.028, 0.022))

# --- NOSE (small black bump) ---
nose = add_uvsphere("Nose", (0, 0.258, 0.196), (0.008, 0.008, 0.007))

# --- EARS (large erect triangles — use cones flared outward) ---
def make_ear(side):  # side = -1 left, +1 right
    bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=0.022, radius2=0.0,
                                    depth=0.075,
                                    location=(0.022*side, 0.190, 0.255))
    e = bpy.context.active_object
    e.name = f"Ear.{'L' if side<0 else 'R'}"
    e.rotation_euler = (-0.15, 0.45*side, 0)  # flare outward, tip slightly back
    bpy.ops.object.shade_smooth()
    return e

make_ear(-1)
make_ear( 1)

# --- LEGS (4 thin cylinders) ---
def make_leg(name, x, y):
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.012, depth=0.135,
                                        location=(x, y, 0.07))
    l = bpy.context.active_object
    l.name = name
    bpy.ops.object.shade_smooth()
    return l

make_leg("Leg.FL", -0.035, 0.085)
make_leg("Leg.FR",  0.035, 0.085)
make_leg("Leg.BL", -0.040, -0.090)
make_leg("Leg.BR",  0.040, -0.090)

# --- PAWS ---
def make_paw(name, x, y):
    bpy.ops.mesh.primitive_uv_sphere_add(location=(x, y, 0.012))
    p = bpy.context.active_object
    p.name = name
    p.scale = (0.014, 0.018, 0.010)
    bpy.ops.object.shade_smooth()
    return p

make_paw("Paw.FL", -0.035, 0.090)
make_paw("Paw.FR",  0.035, 0.090)
make_paw("Paw.BL", -0.040, -0.085)
make_paw("Paw.BR",  0.040, -0.085)

# --- TAIL (curved up and forward, ~5cm) ---
bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.008, depth=0.06,
                                    location=(0, -0.16, 0.18))
tail = bpy.context.active_object
tail.name = "Tail"
tail.rotation_euler = (-0.6, 0, 0)  # angled up-back
bpy.ops.object.shade_smooth()
```

**Verify:** screenshot from camera. Silhouette should already read as a Chihuahua. If not — fix scales NOW, not after sculpting.

Common blocking mistakes to check:
- Ears too small → must be ~35% of head height, broad-based
- Muzzle too long → Chihuahuas have SHORT muzzles, not Greyhound snouts
- Legs too thick → fine-boned breed, radius ≤ 0.012 m
- Tail touching back → it curves up but stays clear of the spine

---

## 3. Unification & topology pass

Merge the blocking pieces into a single continuous mesh, then retopologize so the body deforms cleanly later.

```python
import bpy

# Select all body parts and join into one mesh
bpy.ops.object.select_all(action='DESELECT')
parts = ["Torso","Chest","Hips","Neck","Head","Muzzle",
         "Leg.FL","Leg.FR","Leg.BL","Leg.BR",
         "Paw.FL","Paw.FR","Paw.BL","Paw.BR","Tail"]
for n in parts:
    bpy.data.objects[n].select_set(True)
bpy.context.view_layer.objects.active = bpy.data.objects["Torso"]
bpy.ops.object.join()
body = bpy.context.active_object
body.name = "Chihuahua_Body"

# Boolean union to merge intersections cleanly (single-mesh result)
# Or use Remesh + Voxel for an organic seamless surface.
mod = body.modifiers.new("Remesh", 'REMESH')
mod.mode = 'VOXEL'
mod.voxel_size = 0.004        # 4mm — fine enough to keep ears + paws
mod.use_smooth_shade = True
bpy.ops.object.modifier_apply(modifier="Remesh")

# Light decimation to keep poly count workable
dec = body.modifiers.new("Decimate", 'DECIMATE')
dec.ratio = 0.4
bpy.ops.object.modifier_apply(modifier="Decimate")

# Subsurface for smooth final
sub = body.modifiers.new("Subsurf", 'SUBSURF')
sub.levels = 2
sub.render_levels = 3
```

> **Trade-off note:** Voxel remesh destroys the ear thinness if the voxel is too coarse. If ears look blobby, lower `voxel_size` to 0.003 OR remesh body separately and keep ears as sub-objects until rigging.

Keep `Nose` and `Ear.L`/`Ear.R` as **separate objects** if voxel remesh ruins their crispness — parent them to body instead of joining.

---

## 4. Sculpt-pass refinements

Switch to Sculpt Mode and use these brushes/strokes to add the breed-defining details.

```python
import bpy
bpy.context.view_layer.objects.active = bpy.data.objects["Chihuahua_Body"]
bpy.ops.object.mode_set(mode='SCULPT')
```

Then have the agent run these targeted sculpt operations (use `bpy.ops.sculpt.brush_stroke` programmatically OR delegate to interactive brushes if MCP supports it):

| Area | Brush | What to do |
|---|---|---|
| **Apple skull** | Inflate (small) | Push the dome upward between the ears — Chihuahua trademark |
| **Stop** | Crease | Define the sharp brow break where muzzle meets skull |
| **Eye sockets** | Draw (negative) | Two shallow ovals where eyes will sit, slightly forward-facing |
| **Cheeks** | Smooth | Keep cheek area lean — no Pug-like jowls |
| **Chest** | Inflate | Gentle forward bulge for prosternum |
| **Belly** | Smooth + slight pinch | Tucked-up belly line behind ribcage |
| **Shoulder blades** | Crease (very subtle) | Hint of scapula above front legs |
| **Tail base** | Pinch | Sharper transition from rump to tail |
| **Paws** | Crease | 3 shallow lines per paw to suggest toes |

Work at brush radius ~0.01 m and strength 0.3 max — over-sculpting destroys the smooth-coat silhouette.

---

## 5. Eyes (separate objects)

Eyes are NOT part of the body mesh. They're separate spheres with their own materials so they can be glossy.

```python
import bpy

def add_eye(name, x):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0085,
                                         location=(x, 0.222, 0.215))
    e = bpy.context.active_object
    e.name = name
    bpy.ops.object.shade_smooth()
    return e

add_eye("Eye.L", -0.018)
add_eye("Eye.R",  0.018)
```

The eyes should sit ~70% recessed into the sockets you sculpted in step 4 — only the front cap visible.

---

## 6. Materials (Principled BSDF)

```python
import bpy

def make_mat(name, base, rough=0.6, spec=0.5, subsurf=0.0, subsurf_color=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = base
    p.inputs["Roughness"].default_value = rough
    if "Specular IOR Level" in p.inputs:
        p.inputs["Specular IOR Level"].default_value = spec
    if subsurf and "Subsurface Weight" in p.inputs:
        p.inputs["Subsurface Weight"].default_value = subsurf
        if subsurf_color and "Subsurface Radius" in p.inputs:
            p.inputs["Subsurface Radius"].default_value = subsurf_color
    return m

# Coat: cream white with subtle SSS for warmth
coat = make_mat("Coat",
                base=(0.96, 0.93, 0.86, 1.0),
                rough=0.55, spec=0.35,
                subsurf=0.15, subsurf_color=(0.011, 0.005, 0.003))

# Inner-ear: warm pink-tan
inner_ear = make_mat("InnerEar",
                     base=(0.85, 0.62, 0.55, 1.0),
                     rough=0.7, spec=0.3)

# Nose: matte black, slightly bumpy feel via roughness
nose_mat = make_mat("Nose",
                    base=(0.02, 0.02, 0.02, 1.0),
                    rough=0.35, spec=0.5)

# Eyes: very dark brown, glossy
eye_mat = make_mat("Eye",
                   base=(0.04, 0.025, 0.02, 1.0),
                   rough=0.05, spec=1.0)

# Assign
bpy.data.objects["Chihuahua_Body"].data.materials.append(coat)
if "Nose" in bpy.data.objects:
    bpy.data.objects["Nose"].data.materials.append(nose_mat)
for n in ("Eye.L","Eye.R"):
    if n in bpy.data.objects:
        bpy.data.objects[n].data.materials.append(eye_mat)
for n in ("Ear.L","Ear.R"):
    if n in bpy.data.objects:
        bpy.data.objects[n].data.materials.append(inner_ear)
```

> **Important:** The reference photo shows pure white-ish coat, but a *fully* white material reads as plastic. The cream tint (R 0.96, G 0.93, B 0.86) keeps it photogenic without yellowing it.

### Optional: fur via Geometry Nodes hair

Short-haired Chihuahuas have visible-but-tight fur. If render fidelity matters more than render speed:

1. Add a **Geometry Nodes** modifier with the *Hair Curves* preset.
2. Hair length: **0.0015–0.0030 m** (1.5–3 mm).
3. Density: ~120,000 strands.
4. Children/clumping: low (smooth coat, not fluffy).
5. Match the coat material color in the hair shader.

Skip fur for first pass — it triples render time and the silhouette already reads correctly without it.

---

## 7. Rig (optional, for posing)

A 12-bone rig is enough to pose a static showcase render:

```
Root
└── Spine
    ├── Neck → Head
    ├── ShoulderL → UpperArmL → ForearmL → PawL
    ├── ShoulderR → UpperArmR → ForearmR → PawR
    ├── HipL → ThighL → ShinL → PawBL
    ├── HipR → ThighR → ShinR → PawBR
    └── TailBase → TailMid → TailTip
```

Use `bpy.ops.object.armature_add()` and place bones along the body's centerline. Parent the body mesh with **Automatic Weights**, then test-pose the head turn, ear flick, and tail curl to validate weights.

If the user only wants a static mesh matching the reference, **skip rigging entirely.**

---

## 8. Render & verify

```python
import bpy
scene = bpy.context.scene
scene.render.engine = 'CYCLES'           # or 'BLENDER_EEVEE_NEXT' for fast preview
scene.cycles.samples = 128
scene.render.resolution_x = 1080
scene.render.resolution_y = 1080
scene.render.film_transparent = False
scene.view_settings.look = 'AgX - Medium High Contrast'
```

**Verification checklist (run `get_viewport_screenshot` and compare to reference):**

- [ ] Apple-shaped skull is round, not flat
- [ ] Ears are large, erect, triangular, flared outward — NOT folded
- [ ] Eyes are large, dark, round, slightly protruding
- [ ] Muzzle is short (~1/3 head length), not pointed
- [ ] Nose is small, black, sits at the front of the muzzle
- [ ] Body is compact, level topline
- [ ] Legs are slim and straight
- [ ] Tail curves up and forward, clear of the back
- [ ] Coat is cream/white with warm undertone, not chalk-white
- [ ] Inner ears show warm pink tint

**If any item fails, return to the relevant phase — do NOT report "done".** Per the project's Visual Output Verification Rule, a model that doesn't match the reference must be fixed before delivery.

---

## 9. Save & export

```python
import bpy
bpy.ops.wm.save_as_mainfile(filepath="/tmp/chihuahua.blend")

# Optional: export for downstream use
bpy.ops.wm.obj_export(filepath="/tmp/chihuahua.obj",
                      export_selected_objects=False,
                      export_materials=True)
# or GLB for web/Three.js
bpy.ops.export_scene.gltf(filepath="/tmp/chihuahua.glb",
                          export_format='GLB',
                          export_apply=True)
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Ears look blobby after remesh | Voxel size too coarse | Lower `voxel_size` to 0.003, or keep ears separate |
| Body looks "melted" | Too many subsurf levels on heavy mesh | Drop subsurf to level 1, raise decimate ratio |
| Coat reads as plastic | Pure white + zero SSS | Add subsurface weight 0.1–0.2, slight cream tint |
| Eyes look dead | Roughness too high | Drop eye roughness to 0.03–0.05, keep specular at 1.0 |
| Snout too long | Used wrong reference (deer-head Chihuahua) | This guide targets **apple-head**: muzzle ≤ 0.028 m deep |
| Head tilts wrong | Neck rotation off | Neck should pitch ~60° up-forward (`rotation_euler.x ≈ 1.05`) |
| Tail intersects body | Tail rotation too aggressive | Use `rotation_euler.x = -0.6` (about -34°), not -90° |

---

## Phase order summary (the agent should follow this exactly)

1. **Setup scene** (units, camera, lights, world)
2. **Blocking** with primitives → `get_viewport_screenshot` → fix proportions
3. **Join + voxel remesh** body, keep ears/eyes/nose separate if needed
4. **Sculpt pass** for breed-defining details (apple skull, stop, sockets, paws)
5. **Add eyes** as separate spheres
6. **Materials** (coat, inner ear, nose, eyes)
7. **(Optional) hair** for short coat
8. **(Optional) rig**
9. **Render** + run verification checklist against reference photo
10. **Save** `.blend`, export `.glb`/`.obj` if requested

Do not skip the verification step. The output must match the reference Chihuahua's silhouette and proportions before reporting completion.
