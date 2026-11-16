"""Formwright Mesh Studio: encode a turntable PNG sequence to H.264 MP4 with Blender's own video encoder.

Runs ONLY inside a separate Blender process:  blender -b --factory-startup --python encode.py -- <job_dir> <fps>
Reads <job_dir>/frames/f_*.png and writes <job_dir>/turntable_####-####.mp4 (renamed by the caller).
"""
# ruff: noqa
import os
import sys

import bpy

ARGV = sys.argv[sys.argv.index("--") + 1:]
JOB = os.path.abspath(ARGV[0])
FPS = int(ARGV[1])
FRAMES = os.path.join(JOB, "frames")
files = sorted(f for f in os.listdir(FRAMES) if f.startswith("f_") and f.endswith(".png"))
if not files:
    raise SystemExit("FW_ERROR no frames")
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
ed = sc.sequence_editor_create()
coll = ed.strips if hasattr(ed, "strips") else ed.sequences
strip = coll.new_image(name="turntable", filepath=os.path.join(FRAMES, files[0]), channel=1, frame_start=1)
for f in files[1:]:
    strip.elements.append(f)
img = bpy.data.images.load(os.path.join(FRAMES, files[0]))
sc.render.resolution_x, sc.render.resolution_y = img.size[0], img.size[1]
sc.render.resolution_percentage = 100
sc.frame_start, sc.frame_end = 1, len(files)
sc.render.fps = FPS
ims = sc.render.image_settings
if hasattr(ims, "media_type"):
    ims.media_type = "VIDEO"
ims.file_format = "FFMPEG"
sc.render.ffmpeg.format = "MPEG4"
sc.render.ffmpeg.codec = "H264"
sc.render.ffmpeg.constant_rate_factor = "HIGH"
sc.render.ffmpeg.ffmpeg_preset = "GOOD"
sc.view_settings.view_transform = "Standard"
out = os.path.abspath(os.path.join(JOB, "turntable_"))
if os.path.commonpath([out, JOB]) != JOB:
    raise SystemExit("FW_ERROR output path outside the job folder")
sc.render.filepath = out
bpy.ops.render.render(animation=True)
print("FW_DONE", flush=True)
