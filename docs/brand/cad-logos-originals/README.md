# CAD tool logos (landing page)

Originals as supplied by the founder (2026-11-19). The landing page's CAD integrations grid
(`web/src/components/landing/CadTools.tsx`) shows square symbol tiles made from these in
`web/public/landing/logos/<slug>.(svg|png)`.

Regenerate the tiles (crops each symbol away from its wordmark, white to transparent, 256 px):

```
uv run python docs/brand/cad-logos-originals/make_logos.py docs/brand/cad-logos-originals web/public/landing/logos
```

The marks are trademarks of their owners (Dassault Systèmes, PTC, Autodesk, Siemens, Onshape/PTC, FreeCAD, Blender
Foundation). Check each owner's brand guidelines before a public launch.
