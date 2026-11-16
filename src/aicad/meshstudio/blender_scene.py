"""Formwright Mesh Studio scene script. Runs ONLY inside a separate Blender process:

    blender -b --factory-startup --python scene.py -- <job_dir> <geometry.npz>

It is never imported by Formwright (Blender is GPL; we only drive it from the command line). The SPEC line below is
replaced with the job's preset values by `aicad.meshstudio.scene.build_script`, so each job folder holds a
self-contained, reproducible script. Every file it writes must resolve inside <job_dir>.
"""
# ruff: noqa
import json
import math
import os
import sys

import bpy
import numpy as np

SPEC = {}  # @@SPEC@@

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
JOB = os.path.abspath(ARGV[0])
GEOM = os.path.abspath(ARGV[1])


def out_path(name):
    p = os.path.abspath(os.path.join(JOB, name))
    if os.path.commonpath([p, JOB]) != JOB:
        raise SystemExit("FW_ERROR output path outside the job folder")
    return p


def say(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------ scene
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = "METRIC"
sc.unit_settings.length_unit = "MILLIMETERS"


def build_part():
    d = np.load(GEOM)
    v, f, n = d["v"], d["f"], d["n"]
    me = bpy.data.meshes.new("Part")
    me.vertices.add(len(v))
    me.vertices.foreach_set("co", v.ravel())
    me.loops.add(f.size)
    me.loops.foreach_set("vertex_index", f.ravel())
    me.polygons.add(len(f))
    me.polygons.foreach_set("loop_start", np.arange(0, f.size, 3, dtype=np.int32))
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    me.shade_smooth()
    me.normals_split_custom_set(n.astype(np.float64).reshape(-1, 3))
    ob = bpy.data.objects.new(SPEC["object"]["name"], me)
    sc.collection.objects.link(ob)
    return ob


def node(nt, kind, loc, **inputs):
    nd = nt.nodes.new(kind)
    nd.location = loc
    for k, val in inputs.items():
        nd.inputs[k].default_value = val
    return nd


def make_material(m, simple):
    mat = bpy.data.materials.new(m["label"])
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    outn = node(nt, "ShaderNodeOutputMaterial", (900, 0))
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", (600, 0))
    nt.links.new(bsdf.outputs["BSDF"], outn.inputs["Surface"])
    base = list(m["base"]) + [1.0]
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Metallic"].default_value = m["metallic"]
    bsdf.inputs["Roughness"].default_value = m["roughness"]
    bsdf.inputs["IOR"].default_value = 1.5
    mat.diffuse_color = base
    mat.metallic = m["metallic"]
    mat.roughness = m["roughness"]
    if simple:  # exports: flat PBR values only, which glTF/OBJ carry faithfully
        return mat
    if m.get("coat"):
        bsdf.inputs["Coat Weight"].default_value = m["coat"]
        bsdf.inputs["Coat Roughness"].default_value = m.get("coat_roughness", 0.1)
    if m.get("sheen"):
        bsdf.inputs["Sheen Weight"].default_value = m["sheen"]
        bsdf.inputs["Sheen Roughness"].default_value = 0.6
    if m.get("subsurface"):
        bsdf.inputs["Subsurface Weight"].default_value = m["subsurface"]
        bsdf.inputs["Subsurface Radius"].default_value = (0.002, 0.002, 0.002)
        bsdf.inputs["Subsurface Scale"].default_value = 0.001
    tex = node(nt, "ShaderNodeTexCoord", (-900, 0))
    # roughness variation: broad, low-amplitude noise so large flats don't look CG-perfect
    if m.get("rough_var"):
        nz = node(nt, "ShaderNodeTexNoise", (-600, 200), Scale=SPEC["scale"]["rough_noise"], Detail=3.0)
        nt.links.new(tex.outputs["Object"], nz.inputs["Vector"])
        mr = node(nt, "ShaderNodeMapRange", (-300, 200))
        mr.inputs["From Min"].default_value = 0.3
        mr.inputs["From Max"].default_value = 0.7
        mr.inputs["To Min"].default_value = max(0.02, m["roughness"] - m["rough_var"])
        mr.inputs["To Max"].default_value = min(1.0, m["roughness"] + m["rough_var"])
        nt.links.new(nz.outputs["Fac"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])
    normal = None
    if SPEC["bevel_m"] > 0:  # rounded-edge shading: catches the thin highlight real edge-breaks have
        bev = node(nt, "ShaderNodeBevel", (-300, -350))
        bev.samples = 8
        bev.inputs["Radius"].default_value = SPEC["bevel_m"]
        normal = bev.outputs["Normal"]
    bump_h = None
    if m.get("grain"):
        gz = node(nt, "ShaderNodeTexNoise", (-600, -100), Scale=1.0 / max(1e-6, m["grain_mm"] * 0.001),
                  Detail=2.0, Roughness=0.6)
        nt.links.new(tex.outputs["Object"], gz.inputs["Vector"])
        bump_h = (gz.outputs["Fac"], m["grain"])
    if m.get("brushed"):
        mp = node(nt, "ShaderNodeMapping", (-600, -250))
        mp.inputs["Scale"].default_value = (1.0, 1.0, 400.0)  # long streaks along the part's local X/Y plane
        nt.links.new(tex.outputs["Object"], mp.inputs["Vector"])
        bz = node(nt, "ShaderNodeTexNoise", (-400, -250), Scale=2000.0, Detail=1.0)
        nt.links.new(mp.outputs["Vector"], bz.inputs["Vector"])
        bump_h = (bz.outputs["Fac"], m["brushed"])
    if bump_h is not None:
        bump = node(nt, "ShaderNodeBump", (200, -250), Strength=bump_h[1], Distance=0.00005)
        nt.links.new(bump_h[0], bump.inputs["Height"])
        if normal is not None:
            nt.links.new(normal, bump.inputs["Normal"])
        normal = bump.outputs["Normal"]
    if normal is not None:
        nt.links.new(normal, bsdf.inputs["Normal"])
    if m.get("aniso"):
        bsdf.inputs["Anisotropic"].default_value = m["aniso"]
        tg = node(nt, "ShaderNodeTangent", (200, -500))
        tg.direction_type = "RADIAL"
        tg.axis = "Z"
        nt.links.new(tg.outputs["Tangent"], bsdf.inputs["Tangent"])
    return mat


def set_matrix(ob, rows):
    from mathutils import Matrix

    ob.matrix_world = Matrix(rows)


def build_world(w):
    world = bpy.data.worlds.new("Studio")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    outn = node(nt, "ShaderNodeOutputWorld", (600, 0))
    bg = node(nt, "ShaderNodeBackground", (400, 0), Strength=w["strength"])
    tc = node(nt, "ShaderNodeTexCoord", (-400, 0))
    sep = node(nt, "ShaderNodeSeparateXYZ", (-200, 0))
    nt.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    mr = node(nt, "ShaderNodeMapRange", (0, 0))
    mr.inputs["From Min"].default_value = -1.0
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (200, 0)
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, list(w["bottom"]) + [1.0]
    els[1].position, els[1].color = 1.0, list(w["top"]) + [1.0]
    mid = els.new(0.5)
    mid.color = list(w["horizon"]) + [1.0]
    low = els.new(0.44)
    low.color = list(w["bottom"]) + [1.0]
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], outn.inputs["Surface"])


def build_lights(lights):
    for li in lights:
        ld = bpy.data.lights.new(li["name"], "AREA")
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = li["size"]
        ld.energy = li["power"]
        ld.color = (1.0, 0.985, 0.97)
        if hasattr(ld, "use_shadow"):
            ld.use_shadow = li["shadow"]
        elif hasattr(ld, "cycles"):
            ld.cycles.cast_shadow = li["shadow"]
        ob = bpy.data.objects.new(li["name"], ld)
        sc.collection.objects.link(ob)
        set_matrix(ob, li["matrix"])
        ob.visible_camera = False


def build_floor(fl):
    me = bpy.data.meshes.new("Floor")
    s = fl["size"]
    me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("Floor (shadow catcher)", me)
    ob.location.z = fl["z"]
    sc.collection.objects.link(ob)
    ob.is_shadow_catcher = True
    mat = bpy.data.materials.new("Floor")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = list(fl["albedo"]) + [1.0]
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    me.materials.append(mat)


def build_camera(c):
    cd = bpy.data.cameras.new("Camera")
    cd.type = c["type"]
    cd.lens = c["lens"]
    cd.sensor_width = 36.0
    cd.sensor_fit = "AUTO"
    cd.ortho_scale = c["ortho_scale"]
    cd.shift_x, cd.shift_y = c["shift"]
    cd.clip_start, cd.clip_end = c["clip"]
    ob = bpy.data.objects.new("Camera", cd)
    sc.collection.objects.link(ob)
    set_matrix(ob, c["matrix"])
    sc.camera = ob


def configure_render(r):
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    if r["device"] == "GPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = r["backend"]
        prefs.refresh_devices()
        for dev in prefs.devices:
            dev.use = dev.type == r["backend"]
        cy.device = "GPU"
    else:
        cy.device = "CPU"
        sc.render.threads_mode = "FIXED"
        sc.render.threads = r["threads"]
    cy.samples = r["samples"]
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = r["noise_threshold"]
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.seed = 0
    cy.max_bounces = r["bounces"]
    cy.glossy_bounces = r["bounces"]
    cy.diffuse_bounces = 4
    cy.transmission_bounces = 4
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.blur_glossy = 0.5
    cy.sample_clamp_indirect = 8.0
    sc.render.film_transparent = True
    sc.render.resolution_x, sc.render.resolution_y = r["res"]
    sc.render.resolution_percentage = 100
    linear_output()
    sc.view_settings.view_transform = r["view"]
    sc.view_settings.look = r["look"]
    sc.view_settings.exposure = r["exposure"]
    sc.render.use_persistent_data = True


def linear_output():
    """Renders are written as linear half-float EXR first, so exposure can be chosen from the real highlight values
    before the view transform compresses them (see expose_and_write)."""
    im = sc.render.image_settings
    im.file_format = "OPEN_EXR"
    im.color_mode = "RGBA"
    im.color_depth = "16"
    im.exr_codec = "ZIP"


def png_output():
    im = sc.render.image_settings
    im.file_format = "PNG"
    im.color_mode = "RGBA"
    im.color_depth = "8"
    im.compression = 40


def _object_mins(path):
    """Per-pixel minimum of R, G, B (linear) over the part's opaque pixels: a pixel whose minimum channel is high is
    near white after the view transform, i.e. a blown highlight with no colour or detail left."""
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    px = px.reshape(-1, 4)
    return px[px[:, 3] >= 0.98, :3].min(axis=1)


def expose_and_write(exr_paths, png_paths):
    """Highlight protection (AMI-12). Measure the share of the part's pixels that would land in the view transform's
    white shoulder; when it exceeds the allowed share, lower the exposure just enough (never brighten, never more
    than the floor). One exposure for every frame, so a turntable doesn't flicker. Then write the display-referred
    PNGs with the scene's colour management and delete the linear files."""
    r = SPEC["render"]
    ae = r.get("auto_exposure") or {}
    step = max(1, len(exr_paths) // 12)
    mins = np.concatenate([_object_mins(p) for p in exr_paths[::step]]) * (2.0 ** r["exposure"])
    ev, before = 0.0, 0.0
    if mins.size and ae:
        before = float((mins >= ae["shoulder"]).mean())
        if before > ae["max_fraction"]:
            q = float(np.quantile(mins, 1.0 - ae["max_fraction"]))
            ev = max(ae["min_ev"], math.log2(ae["shoulder"] / q))
    after = float((mins * 2.0 ** ev >= ae.get("shoulder", 1.0)).mean()) if mins.size else 0.0
    sc.view_settings.exposure = r["exposure"] + ev
    png_output()
    for src, dst in zip(exr_paths, png_paths):
        img = bpy.data.images.load(src)
        img.save_render(dst, scene=sc)
        bpy.data.images.remove(img)
        os.remove(src)
    say("FW_EXPOSURE %.4f %.5f %.5f" % (ev, before, after))


def main():
    mode = SPEC["mode"]
    part = build_part()
    simple = mode == "export"
    part.data.materials.append(make_material(SPEC["material"], simple))
    if mode == "export":
        bpy.ops.object.select_all(action="DESELECT")
        part.select_set(True)
        bpy.context.view_layer.objects.active = part
        o = SPEC["outputs"]
        if o.get("glb"):
            bpy.ops.export_scene.gltf(filepath=out_path(o["glb"]), export_format="GLB", use_selection=True,
                                      export_yup=True, export_apply=True, export_extras=True)
        if o.get("obj"):
            bpy.ops.wm.obj_export(filepath=out_path(o["obj"]), export_selected_objects=True, global_scale=1000.0,
                                  forward_axis="Y", up_axis="Z", export_materials=True, export_normals=True,
                                  export_uv=False)
        if o.get("stl"):
            bpy.ops.wm.stl_export(filepath=out_path(o["stl"]), export_selected_objects=True, global_scale=1000.0,
                                  forward_axis="Y", up_axis="Z", ascii_format=False)
        say("FW_DONE")
        return
    # posed part on a turntable pivot (pivot animated for turntables, so the .blend keeps the animation)
    pivot = bpy.data.objects.new("Turntable", None)
    sc.collection.objects.link(pivot)
    pivot.location = SPEC["pivot"]
    part.parent = pivot
    set_matrix(part, SPEC["object"]["matrix"])
    part["formwright"] = "Visualisation mesh tessellated from the verified model; not the exact geometry."
    build_world(SPEC["lighting"]["world"])
    build_lights(SPEC["lighting"]["lights"])
    build_floor(SPEC["floor"])
    build_camera(SPEC["camera"])
    configure_render(SPEC["render"])
    o = SPEC["outputs"]
    tt = SPEC.get("turntable")
    if tt:
        n = tt["frames"]
        sc.frame_start, sc.frame_end = 1, n
        sc.render.fps = tt["fps"]
        bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
        pivot.rotation_euler = (0.0, 0.0, 0.0)
        pivot.keyframe_insert("rotation_euler", index=2, frame=1)
        pivot.rotation_euler = (0.0, 0.0, 2 * math.pi)
        pivot.keyframe_insert("rotation_euler", index=2, frame=n + 1)
        frames_dir = out_path(o["frames_dir"])
        os.makedirs(frames_dir, exist_ok=True)
        # one animation render keeps the device, kernels and scene loaded between frames (much faster than
        # rendering each frame as a separate still)
        def _frame_done(scene, *args):
            say("FW_FRAME %d/%d" % (scene.frame_current, n))

        bpy.app.handlers.render_write.append(_frame_done)
        sc.render.filepath = out_path(os.path.join(o["frames_dir"], "f_"))
        sc.render.use_file_extension = True
        bpy.ops.render.render(animation=True)
        exrs = [out_path(os.path.join(o["frames_dir"], "f_%04d.exr" % k)) for k in range(1, n + 1)]
        expose_and_write(exrs, [p[:-4] + ".png" for p in exrs])
        if o.get("blend"):  # saved after exposure, so the scene reproduces the delivered frames
            png_output()
            sc.render.filepath = "//frames/f_"
            bpy.ops.wm.save_as_mainfile(filepath=out_path(o["blend"]), compress=True, copy=True)
    else:
        sc.render.filepath = out_path("linear.exr")
        bpy.ops.render.render(write_still=True)
        say("FW_FRAME 1/1")
        expose_and_write([out_path("linear.exr")], [out_path(o["image"])])
        if o.get("blend"):
            png_output()
            sc.render.filepath = "//render.png"
            bpy.ops.wm.save_as_mainfile(filepath=out_path(o["blend"]), compress=True, copy=True)
    say("FW_DONE")


try:
    main()
except SystemExit:
    raise
except Exception as e:  # report and exit non-zero so the runner marks the job failed
    import traceback

    traceback.print_exc()
    say("FW_ERROR %s" % type(e).__name__)
    sys.exit(3)
