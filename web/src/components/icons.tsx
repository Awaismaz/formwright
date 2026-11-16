import {
  Box, Boxes, CircleDot, Cog, CornerDownRight, Factory, Gauge, Minus, Package, Printer, Ruler, ScanLine, Shapes, Square,
  type LucideIcon,
} from "lucide-react";

const MAP: Record<string, LucideIcon> = {
  box: Box, ruler: Ruler, scan: ScanLine, boxes: Boxes, factory: Factory, gauge: Gauge, printer: Printer,
  shapes: Shapes, square: Square, "corner-down-right": CornerDownRight, minus: Minus, package: Package,
  "circle-dot": CircleDot, cog: Cog,
};

export function Icon({ name, className }: { name: string; className?: string }) {
  const C = MAP[name] ?? Box;
  return <C className={className ?? "h-4 w-4"} />;
}
