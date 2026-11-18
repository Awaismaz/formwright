/**
 * Planetary gear kinematics for the landing hero (ring fixed, sun input, carrier output).
 *
 * Conventions match scripts/landing_assets.py: every gear file has tooth 0 centred on +X at angle 0; the ring's
 * tooth SPACE 0 is on +X; planet k sits at angle θk = 2πk/N on the carrier. Angles in radians, CCW about +Z.
 */

export type GearSet = { zs: number; zp: number; zr: number; n: number; m: number };

const TAU = Math.PI * 2;
/** Wrap x into [0, p). */
export const wrap = (x: number, p: number) => ((x % p) + p) % p;

/** Overall ratio sun : carrier with the ring held, i = 1 + Zr/Zs. */
export const ratio = (g: GearSet) => 1 + g.zr / g.zs;
/** Carrier (output) angular velocity for sun velocity ws: ωc = ωs · Zs / (Zs + Zr). */
export const carrierSpeed = (ws: number, g: GearSet) => (ws * g.zs) / (g.zs + g.zr);
/** Planet ABSOLUTE spin for sun velocity ws (Willis with ωr = 0): ωp = ωc · (1 − Zr/Zp). Negative = clockwise. */
export const planetSpin = (ws: number, g: GearSet) => carrierSpeed(ws, g) * (1 - g.zr / g.zp);
/** Operating centre distance a = m (Zs + Zp) / 2. */
export const centreDistance = (g: GearSet) => (g.m * (g.zs + g.zp)) / 2;
/** Coaxial condition (Zr = Zs + 2 Zp) and equal-spacing assembly condition ((Zs + Zr) / N integer). */
export const assemblable = (g: GearSet) => g.zr === g.zs + 2 * g.zp && (g.zs + g.zr) % g.n === 0;

/** Carrier angle of planet k. */
export const planetAngle = (k: number, g: GearSet) => (TAU * k) / g.n;

/**
 * Initial spin of planet k (sun and carrier at 0) so its teeth sit in the fixed ring's spaces:
 * the ring-mesh phase (θ − φp)·Zp − θ·Zr ≡ 0 (mod 2π) gives φp = θk (1 − Zr/Zp), taken modulo one planet pitch.
 */
export const planetPhase = (k: number, g: GearSet) => wrap(planetAngle(k, g) * (1 - g.zr / g.zp), TAU / g.zp);

export type Pose = { sun: number; carrier: number; planets: { centre: number; spin: number }[] };

/** Every moving angle for a given sun rotation (rolling without slip, ring fixed). */
export function pose(sunAngle: number, g: GearSet): Pose {
  const carrier = carrierSpeed(sunAngle, g);
  const spin = planetSpin(sunAngle, g);
  return {
    sun: sunAngle, carrier,
    planets: Array.from({ length: g.n }, (_, k) => ({ centre: planetAngle(k, g) + carrier, spin: planetPhase(k, g) + spin })),
  };
}

/**
 * Mesh residuals for planet k at a pose, in radians of tooth phase (0 = perfectly meshed). Ring mesh: a planet tooth
 * centred in a ring space on the line of centres; sun mesh: a sun tooth centred in a planet space on the line of centres.
 */
export function meshResiduals(p: Pose, k: number, g: GearSet): { ring: number; sun: number } {
  const { centre: th, spin: ph } = p.planets[k]!;
  const ring = (th - ph) * g.zp - th * g.zr;
  const sun = (th - p.sun) * g.zs + (th + Math.PI - ph) * g.zp - Math.PI;
  const r = (x: number) => { const w = wrap(x, TAU); return Math.min(w, TAU - w); };
  return { ring: r(ring), sun: r(sun) };
}

/** Smooth spin-up: angle after τ seconds at steady speed ω with first-order lag T (no jump at τ = 0). */
export const spinUp = (tau: number, w: number, T = 1.2) => (tau <= 0 ? 0 : w * (tau - T * (1 - Math.exp(-tau / T))));
