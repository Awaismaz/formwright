/** Pin layout on the source image: pins stay their size on screen at any zoom, so readings that sit close together
 * (e.g. 5 and 6, 10 and 11 on a small sheet at fit zoom) would cover each other. ``spreadPins`` steps an overlapping
 * pin sideways in reading order until it is clear, and returns screen-pixel offsets per pin id. */
export interface PinAt { id: string; x: number; y: number }

export function spreadPins(pins: PinAt[], w: number, h: number, zoom: number, size = 22): Record<string, number> {
  const order = [...pins].sort((a, b) => a.y - b.y || a.x - b.x);
  const placed: { x: number; y: number }[] = [];
  const out: Record<string, number> = {};
  for (const p of order) {
    const sx = p.x * w * zoom;
    const sy = p.y * h * zoom;
    let dx = 0;
    for (let i = 0; i < 16 && placed.some(q => Math.abs(q.x - (sx + dx)) < size && Math.abs(q.y - sy) < size); i++) dx += size;
    placed.push({ x: sx + dx, y: sy });
    out[p.id] = dx;
  }
  return out;
}
